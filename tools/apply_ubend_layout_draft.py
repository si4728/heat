from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any


TARGETS = {"E-550", "E-201A", "E-201B", "E-201D", "E-401"}
EXPECTED_REVISIONS = 5
EXPECTED_POINTS = 2610
EXPECTED_LINKS = 52
EXPECTED_UNLINKED = 2558
REQUIRED_CONFIRMATION = "USER_CONFIRMED_UBEND_DRAFT_STAGE"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_hash(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        for line in connection.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    finally:
        connection.close()
    return digest.hexdigest()


def create_backup(db_path: Path, backup_path: Path) -> None:
    source = sqlite3.connect(db_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def split_sources(value: str) -> list[str]:
    return [item.strip() for item in value.split(" | ") if item.strip()]


def source_file(root: Path, relative: str) -> Path:
    return root.joinpath(*PureWindowsPath(relative).parts)


def snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "tube_count": connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0],
        "tube_xy_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0],
        "revision_count": connection.execute("SELECT count(*) FROM tube_layout_revision").fetchone()[0],
        "point_count": connection.execute("SELECT count(*) FROM tube_layout_point").fetchone()[0],
        "approved_count": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
        ).fetchone()[0],
        "verified_points": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='VERIFIED'"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }


def build_plan(review_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    classifications = [
        row for row in read_csv(review_dir / "rollout_candidate_classification.csv")
        if row["equipment_code"] in TARGETS
    ]
    if len(classifications) != EXPECTED_REVISIONS or any(
        row["classification"] != "REVIEW_REQUIRED" for row in classifications
    ):
        raise RuntimeError("U-Bend candidate classification changed")
    revision_by_path = {
        row["source_path"]: row for row in read_csv(review_dir / "layout_revisions.csv")
    }
    revisions = [revision_by_path[row["source_path"]] | {
        "physical_tube_count": row["report_total_tube_count"],
        "classification_reasons": row["reasons"],
    } for row in classifications]
    bundles = {int(row["bundle_id"]) for row in revisions}
    points = [
        row for row in read_csv(review_dir / "tube_layout_candidates.csv")
        if int(row["bundle_id"]) in bundles
    ]
    links = sum(bool(row["existing_tube_id"]) for row in points)
    if (len(revisions), len(points), links, len(points) - links) != (
        EXPECTED_REVISIONS, EXPECTED_POINTS, EXPECTED_LINKS, EXPECTED_UNLINKED
    ):
        raise RuntimeError("U-Bend DRAFT manifest counts changed")
    for revision in revisions:
        if int(revision["source_tube_count"]) != 2 * int(revision["physical_tube_count"]):
            raise RuntimeError(f"Not a two-end U-Bend count: {revision['source_path']}")
    return revisions, points


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage the five reviewed U-Bend layouts as DRAFT.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    source_root = args.source_root.resolve()
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    revisions, points = build_plan(review_dir)
    plan = {
        "equipment_codes": sorted(TARGETS),
        "revision_count": len(revisions),
        "physical_tube_count": sum(int(row["physical_tube_count"]) for row in revisions),
        "layout_point_count": len(points),
        "existing_tube_links": EXPECTED_LINKS,
        "unlinked_source_points": EXPECTED_UNLINKED,
        "layout_count_basis": "TUBE_END",
        "coverage_status": "FULL",
        "target_status": "DRAFT",
    }
    if not args.apply:
        print(json.dumps({**plan, "database_apply": False}, ensure_ascii=False, indent=2))
        return 0

    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        existing_paths = {
            row[0] for row in connection.execute("SELECT source_path FROM tube_layout_revision")
        }
    finally:
        connection.close()
    overlap = existing_paths & {row["source_path"] for row in revisions}
    if overlap:
        raise RuntimeError(f"Target revisions already exist: {sorted(overlap)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_ubend_layout_draft_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    logical_before = logical_hash(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_hash(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    points_by_bundle: dict[int, list[dict[str, str]]] = {}
    for point in points:
        points_by_bundle.setdefault(int(point["bundle_id"]), []).append(point)
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    before = snapshot(connection)
    inserted_ids: list[int] = []
    inserted_points = 0
    reviewed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for revision in revisions:
            bundle_id = int(revision["bundle_id"])
            relative_path = revision["source_path"]
            physical = source_file(source_root, relative_path)
            if not physical.is_file():
                raise FileNotFoundError(physical)
            cursor = connection.execute(
                """INSERT INTO tube_layout_revision (
                       bundle_id, inspection_id, source_path, source_checksum,
                       source_section_id, source_section_name, source_coordinate_unit,
                       source_origin_code, source_row_spacing, source_column_spacing,
                       source_scale_metric, physical_tube_count, layout_point_count,
                       layout_count_basis, coverage_status, unresolved_count,
                       count_discrepancy_note, revision_status, review_note,
                       reviewed_by, reviewed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'GRID', ?, ?, ?, ?, ?, ?,
                             'TUBE_END', 'FULL', 0, ?, 'DRAFT', ?, ?, ?)""",
                (
                    bundle_id, int(revision["inspection_id"]), relative_path, sha256(physical),
                    int(revision["section_id"]), revision["section_name"],
                    int(revision["origin_code"]) if revision["origin_code"] else None,
                    float(revision["row_spacing"]) if revision["row_spacing"] else None,
                    float(revision["column_spacing"]) if revision["column_spacing"] else None,
                    1 if revision["scale_metric"].lower() == "true" else 0,
                    int(revision["physical_tube_count"]), int(revision["source_tube_count"]),
                    "Report physical Tube count differs from the Tube Sheet map because the U-Bend layout shows two ends per physical Tube.",
                    "U-Bend Tube Sheet end layout staged after count-semantics review; operational approval pending.",
                    "USER_CONFIRMED_UBEND_DRAFT_STAGE", reviewed_at,
                ),
            )
            revision_id = int(cursor.lastrowid)
            inserted_ids.append(revision_id)
            for point in points_by_bundle[bundle_id]:
                if relative_path not in split_sources(point["source_paths"]):
                    raise RuntimeError(f"Point provenance mismatch: {relative_path}")
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
                        int(point["row"]), int(point["column"]),
                        float(point["source_x"]), float(point["source_y"]),
                        float(point["original_x"]) if point["original_x"] else None,
                        float(point["original_y"]) if point["original_y"] else None,
                        point["mapping_status"],
                    ),
                )
                inserted_points += 1
        if len(inserted_ids) != EXPECTED_REVISIONS or inserted_points != EXPECTED_POINTS:
            raise RuntimeError("Inserted counts do not match the approved plan")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    placeholders = ",".join("?" for _ in inserted_ids)
    staged = dict(connection.execute(
        f"""SELECT count(*) AS revisions, sum(revision_status='DRAFT') AS drafts,
                   sum(layout_count_basis='TUBE_END') AS tube_end_basis,
                   sum(coverage_status='FULL') AS full_coverage,
                   sum(physical_tube_count) AS physical_tubes,
                   sum(layout_point_count) AS layout_points
            FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders})""",
        inserted_ids,
    ).fetchone())
    connection.close()
    if after["approved_count"] != before["approved_count"] or after["verified_points"] != before["verified_points"]:
        raise RuntimeError("Operational approval state changed unexpectedly")
    if after["tube_count"] != before["tube_count"] or after["tube_xy_count"] != before["tube_xy_count"]:
        raise RuntimeError("Tube master data changed unexpectedly")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-stage checks: {after}")

    result = {
        "status": "PASS", **plan, "inserted_revision_ids": inserted_ids,
        "inserted_point_count": inserted_points, "staged_validation": staged,
        "before": before, "after": after, "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    output = review_dir / "ubend_draft_apply_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
