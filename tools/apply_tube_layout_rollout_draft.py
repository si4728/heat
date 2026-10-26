from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any


EXPECTED_REVISION_COUNT = 52
EXPECTED_POINT_COUNT = 19_289
EXPECTED_EXISTING_LINK_COUNT = 1_056
EXPECTED_NEW_CANDIDATE_COUNT = 18_233
REQUIRED_CONFIRMATION = "USER_CONFIRMED_52_DRAFT_LAYOUTS"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_sqlite_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {path}")
        for line in connection.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    finally:
        connection.close()
    return digest.hexdigest()


def split_sources(value: str) -> list[str]:
    return [item.strip() for item in value.split(" | ") if item.strip()]


def source_file(source_root: Path, relative_path: str) -> Path:
    return source_root.joinpath(*PureWindowsPath(relative_path).parts)


def snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "tube_count": connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0],
        "tube_xy_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0],
        "layout_revision_count": connection.execute("SELECT count(*) FROM tube_layout_revision").fetchone()[0],
        "layout_point_count": connection.execute("SELECT count(*) FROM tube_layout_point").fetchone()[0],
        "approved_revision_count": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }


def build_plan(review_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    classifications = read_csv(review_dir / "rollout_candidate_classification.csv")
    selected = [row for row in classifications if row["classification"] == "AUTO_APPROVAL_CANDIDATE"]
    if len(selected) != EXPECTED_REVISION_COUNT:
        raise RuntimeError(f"Expected {EXPECTED_REVISION_COUNT} approved candidates, found {len(selected)}")
    if any(row["reasons"] or row["current_db_status"] != "NOT_LOADED" for row in selected):
        raise RuntimeError("Candidate classification changed or includes an already-loaded revision")

    revision_source = {row["source_path"]: row for row in read_csv(review_dir / "layout_revisions.csv")}
    revisions = [revision_source[row["source_path"]] for row in selected]
    if len({int(row["bundle_id"]) for row in revisions}) != EXPECTED_REVISION_COUNT:
        raise RuntimeError("The approved candidate set must contain one revision per bundle")

    selected_bundles = {int(row["bundle_id"]) for row in revisions}
    points = [
        row for row in read_csv(review_dir / "tube_layout_candidates.csv")
        if int(row["bundle_id"]) in selected_bundles
    ]
    existing_links = sum(bool(row["existing_tube_id"]) for row in points)
    new_candidates = sum(not bool(row["existing_tube_id"]) for row in points)
    if (len(points), existing_links, new_candidates) != (
        EXPECTED_POINT_COUNT, EXPECTED_EXISTING_LINK_COUNT, EXPECTED_NEW_CANDIDATE_COUNT
    ):
        raise RuntimeError(
            "Candidate point manifest changed: "
            f"points={len(points)}, links={existing_links}, new={new_candidates}"
        )
    if any(row["review_status"] != "PENDING" for row in points):
        raise RuntimeError("Candidate point review status changed")
    return revisions, points


def create_backup(db_path: Path, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        raise FileExistsError(backup_path)
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def apply_draft(
    db_path: Path,
    source_root: Path,
    revisions: list[dict[str, str]],
    points: list[dict[str, str]],
) -> dict[str, Any]:
    points_by_bundle: dict[int, list[dict[str, str]]] = {}
    for row in points:
        points_by_bundle.setdefault(int(row["bundle_id"]), []).append(row)

    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    before = snapshot(connection)
    if before["quick_check"] != "ok" or before["foreign_key_issues"]:
        connection.close()
        raise RuntimeError(f"Database failed pre-apply checks: {before}")

    inserted_revisions = 0
    inserted_points = 0
    staged_revision_ids: list[int] = []
    review_time = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for revision in revisions:
            bundle_id = int(revision["bundle_id"])
            relative_path = revision["source_path"]
            physical_source = source_file(source_root, relative_path)
            if not physical_source.is_file():
                raise FileNotFoundError(physical_source)
            cursor = connection.execute(
                """INSERT INTO tube_layout_revision (
                       bundle_id, inspection_id, source_path, source_checksum,
                       source_section_id, source_section_name, source_coordinate_unit,
                       source_origin_code, source_row_spacing, source_column_spacing,
                       source_scale_metric, rotation_degrees, flip_x, flip_y,
                       revision_status, review_note, reviewed_by, reviewed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'GRID', ?, ?, ?, ?, NULL, NULL, NULL,
                             'DRAFT', ?, ?, ?)""",
                (
                    bundle_id,
                    int(revision["inspection_id"]),
                    relative_path,
                    sha256(physical_source),
                    int(revision["section_id"]),
                    revision["section_name"],
                    int(revision["origin_code"]) if revision["origin_code"] else None,
                    float(revision["row_spacing"]) if revision["row_spacing"] else None,
                    float(revision["column_spacing"]) if revision["column_spacing"] else None,
                    1 if revision["scale_metric"].lower() == "true" else 0,
                    "Validated rollout candidate: MDB, report, Tube Map, master count and section agree. Operational approval pending.",
                    "USER_CONFIRMED_DRAFT_STAGE",
                    review_time,
                ),
            )
            inserted_revisions += 1
            revision_id = int(cursor.lastrowid)
            staged_revision_ids.append(revision_id)

            revision_points = points_by_bundle[bundle_id]
            for point in revision_points:
                if relative_path not in split_sources(point["source_paths"]):
                    raise RuntimeError(f"Point provenance mismatch: bundle={bundle_id}, source={relative_path}")
                connection.execute(
                    """INSERT INTO tube_layout_point (
                           layout_revision_id, tube_id, source_tube_id,
                           source_row, source_column, source_x, source_y,
                           source_original_x, source_original_y,
                           mapping_status, verification_status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                    (
                        revision_id,
                        int(point["existing_tube_id"]) if point["existing_tube_id"] else None,
                        point["existing_tube_no"] or f"{point['row']}-{point['column']}",
                        int(point["row"]),
                        int(point["column"]),
                        float(point["source_x"]),
                        float(point["source_y"]),
                        float(point["original_x"]) if point["original_x"] else None,
                        float(point["original_y"]) if point["original_y"] else None,
                        point["mapping_status"],
                    ),
                )
                inserted_points += 1

        if inserted_revisions != EXPECTED_REVISION_COUNT or inserted_points != EXPECTED_POINT_COUNT:
            raise RuntimeError(
                f"Insert count mismatch: revisions={inserted_revisions}, points={inserted_points}"
            )
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed inside transaction")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    placeholders = ",".join("?" for _ in staged_revision_ids)
    staged = dict(connection.execute(
        f"""SELECT count(*) AS revisions,
                   sum(revision_status='DRAFT') AS drafts
            FROM tube_layout_revision
            WHERE layout_revision_id IN ({placeholders})""",
        staged_revision_ids,
    ).fetchone())
    staged_points = dict(connection.execute(
        f"""SELECT count(*) AS points,
                   sum(p.verification_status='PENDING') AS pending,
                   sum(p.tube_id IS NOT NULL) AS existing_links,
                   sum(p.tube_id IS NULL) AS unlinked
            FROM tube_layout_point p
            WHERE p.layout_revision_id IN ({placeholders})""",
        staged_revision_ids,
    ).fetchone())
    connection.close()

    if after["tube_count"] != before["tube_count"] or after["tube_xy_count"] != before["tube_xy_count"]:
        raise RuntimeError("Existing tube master data changed unexpectedly")
    if after["approved_revision_count"] != before["approved_revision_count"]:
        raise RuntimeError("Operational approval state changed unexpectedly")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-apply checks: {after}")
    if staged != {"revisions": EXPECTED_REVISION_COUNT, "drafts": EXPECTED_REVISION_COUNT}:
        raise RuntimeError(f"Staged revision validation failed: {staged}")
    expected_staged_points = {
        "points": EXPECTED_POINT_COUNT,
        "pending": EXPECTED_POINT_COUNT,
        "existing_links": EXPECTED_EXISTING_LINK_COUNT,
        "unlinked": EXPECTED_NEW_CANDIDATE_COUNT,
    }
    if staged_points != expected_staged_points:
        raise RuntimeError(f"Staged point validation failed: {staged_points}")

    return {
        "before": before,
        "after": after,
        "staged_revisions": staged,
        "staged_points": staged_points,
        "staged_revision_ids": staged_revision_ids,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage the 52 validated Tube Layout candidates as DRAFT.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    revisions, points = build_plan(review_dir)
    plan = {
        "revision_count": len(revisions),
        "point_count": len(points),
        "existing_tube_links": sum(bool(row["existing_tube_id"]) for row in points),
        "unlinked_source_points": sum(not bool(row["existing_tube_id"]) for row in points),
        "target_status": "DRAFT",
        "operational_approval_changes": 0,
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_layout_rollout_draft_{stamp}.db"
    db_sha_before = sha256(db_path)
    logical_before = logical_sqlite_sha256(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_sqlite_sha256(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash does not match the source database")

    result = apply_draft(db_path, args.source_root.resolve(), revisions, points)
    result.update(plan)
    result.update({
        "database_apply": True,
        "confirmation": args.confirmed_by,
        "backup_file": str(backup_path),
        "database_sha256_before": db_sha_before,
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    result_path = review_dir / "rollout_draft_apply_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
