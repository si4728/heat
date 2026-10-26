from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_CONFIRMATION = "USER_CONFIRMED_UBEND_OPERATIONAL_APPROVAL"
EXPECTED_REVISIONS = 5
EXPECTED_POINTS = 2610
EXPECTED_PHYSICAL_TUBES = 1305


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
        "draft_count": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='DRAFT'"
        ).fetchone()[0],
        "verified_points": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='VERIFIED'"
        ).fetchone()[0],
        "pending_points": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='PENDING'"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Operationally approve the five reviewed U-Bend layouts.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    staged = json.loads((review_dir / "ubend_draft_apply_result.json").read_text(encoding="utf-8"))
    ids = [int(value) for value in staged["inserted_revision_ids"]]
    if len(ids) != EXPECTED_REVISIONS:
        raise RuntimeError("U-Bend staged revision manifest changed")
    placeholders = ",".join("?" for _ in ids)

    read_connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    precheck = read_connection.execute(
        f"""SELECT count(*) AS revisions,
                   sum(revision_status='DRAFT') AS drafts,
                   sum(layout_count_basis='TUBE_END') AS tube_end_basis,
                   sum(coverage_status='FULL') AS full_coverage,
                   sum(physical_tube_count) AS physical_tubes,
                   sum(layout_point_count) AS declared_points
            FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders})""",
        ids,
    ).fetchone()
    point_precheck = read_connection.execute(
        f"""SELECT count(*) AS points,
                   sum(verification_status='PENDING') AS pending,
                   sum(canonical_x IS NOT NULL OR canonical_y IS NOT NULL) AS canonical_set,
                   sum(conflict_code IS NOT NULL) AS conflicts
            FROM tube_layout_point WHERE layout_revision_id IN ({placeholders})""",
        ids,
    ).fetchone()
    read_connection.close()
    actual = {
        "revisions": int(precheck[0]), "drafts": int(precheck[1]),
        "tube_end_basis": int(precheck[2]), "full_coverage": int(precheck[3]),
        "physical_tubes": int(precheck[4]), "declared_points": int(precheck[5]),
        "points": int(point_precheck[0]), "pending": int(point_precheck[1]),
        "canonical_set": int(point_precheck[2]), "conflicts": int(point_precheck[3]),
    }
    wanted = {
        "revisions": 5, "drafts": 5, "tube_end_basis": 5, "full_coverage": 5,
        "physical_tubes": EXPECTED_PHYSICAL_TUBES, "declared_points": EXPECTED_POINTS,
        "points": EXPECTED_POINTS, "pending": EXPECTED_POINTS,
        "canonical_set": 0, "conflicts": 0,
    }
    if actual != wanted:
        raise RuntimeError(f"U-Bend pre-approval validation failed: {actual} != {wanted}")
    if not args.apply:
        print(json.dumps({"precheck": actual, "revision_ids": ids, "database_apply": False}, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_ubend_layout_approval_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    logical_before = logical_hash(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_hash(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    connection = sqlite3.connect(db_path, timeout=30)
    before = snapshot(connection)
    approved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        points_cursor = connection.execute(
            f"""UPDATE tube_layout_point
                SET canonical_x=source_x, canonical_y=source_y,
                    verification_status='VERIFIED',
                    review_note='U-Bend Tube Sheet end coordinate verified against source MDB and report map.'
                WHERE layout_revision_id IN ({placeholders})""",
            ids,
        )
        revisions_cursor = connection.execute(
            f"""UPDATE tube_layout_revision
                SET normalized_view_direction='PDF_SOURCE_VIEW',
                    rotation_degrees=0, flip_x=0, flip_y=0,
                    scale_x=1, scale_y=1, offset_x=0, offset_y=0,
                    revision_status='APPROVED',
                    review_note=review_note || ' Operational U-Bend end-position layout approved.',
                    approved_by='USER_CONFIRMED_UBEND_OPERATIONAL_APPROVAL',
                    approved_at=?
                WHERE layout_revision_id IN ({placeholders})""",
            [approved_at, *ids],
        )
        if points_cursor.rowcount != EXPECTED_POINTS or revisions_cursor.rowcount != EXPECTED_REVISIONS:
            raise RuntimeError("U-Bend approval update count mismatch")
        verified = connection.execute(
            f"""SELECT count(*) FROM tube_layout_point
                WHERE layout_revision_id IN ({placeholders})
                  AND verification_status='VERIFIED'
                  AND canonical_x=source_x AND canonical_y=source_y""",
            ids,
        ).fetchone()[0]
        approved = connection.execute(
            f"SELECT count(*) FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders}) AND revision_status='APPROVED'",
            ids,
        ).fetchone()[0]
        if verified != EXPECTED_POINTS or approved != EXPECTED_REVISIONS:
            raise RuntimeError("U-Bend in-transaction verification failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    connection.close()
    protected = ("tube_count", "tube_xy_count", "revision_count", "point_count")
    if any(before[key] != after[key] for key in protected):
        raise RuntimeError(f"Protected state changed: before={before}, after={after}")
    if after["approved_count"] - before["approved_count"] != 5:
        raise RuntimeError("Approved revision delta mismatch")
    if after["verified_points"] - before["verified_points"] != EXPECTED_POINTS:
        raise RuntimeError("Verified point delta mismatch")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-approval checks: {after}")

    result = {
        "status": "PASS", "revision_ids": ids, "precheck": actual,
        "before": before, "after": after, "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (review_dir / "ubend_operational_approval_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
