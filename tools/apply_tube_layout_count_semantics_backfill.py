from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REQUIRED_CONFIRMATION = "USER_CONFIRMED_COUNT_SEMANTICS_BACKFILL"
EXPECTED_REVISION_COUNT = 58
EXPECTED_BASIS = {"PHYSICAL_TUBE": 57, "UNKNOWN": 1}
EXPECTED_COVERAGE = {"CONFLICT": 2, "FULL": 55, "UNKNOWN": 1}
EXPECTED_STATUS = {"APPROVED": 55, "DRAFT": 3}


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
        "verified_point_count": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='VERIFIED'"
        ).fetchone()[0],
        "pending_point_count": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='PENDING'"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }


def validate_plan(rows: list[dict[str, str]]) -> None:
    if len(rows) != EXPECTED_REVISION_COUNT:
        raise RuntimeError(f"Expected {EXPECTED_REVISION_COUNT} plan rows, found {len(rows)}")
    if len({int(row["layout_revision_id"]) for row in rows}) != EXPECTED_REVISION_COUNT:
        raise RuntimeError("Backfill plan contains duplicate revision IDs")
    basis = dict(sorted(Counter(row["layout_count_basis"] for row in rows).items()))
    coverage = dict(sorted(Counter(row["coverage_status"] for row in rows).items()))
    statuses = dict(sorted(Counter(row["revision_status"] for row in rows).items()))
    if basis != EXPECTED_BASIS or coverage != EXPECTED_COVERAGE or statuses != EXPECTED_STATUS:
        raise RuntimeError(
            f"Backfill plan changed: basis={basis}, coverage={coverage}, statuses={statuses}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply reviewed Tube Layout count semantics.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    plan_path = review_dir / "count_semantics_backfill_plan.csv"
    plan_rows = read_csv(plan_path)
    validate_plan(plan_rows)
    plan = {
        "revision_count": len(plan_rows),
        "basis_counts": EXPECTED_BASIS,
        "coverage_counts": EXPECTED_COVERAGE,
        "status_counts": EXPECTED_STATUS,
        "plan_sha256": sha256(plan_path),
        "protected_status_and_coordinate_changes": 0,
    }
    if not args.apply:
        print(json.dumps({**plan, "database_apply": False}, ensure_ascii=False, indent=2))
        return 0

    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    before = snapshot(connection)
    if before["quick_check"] != "ok" or before["foreign_key_issues"]:
        connection.close()
        raise RuntimeError(f"Database failed pre-backfill checks: {before}")
    current_rows = {
        int(row["layout_revision_id"]): row
        for row in connection.execute("SELECT * FROM tube_layout_revision")
    }
    for planned in plan_rows:
        revision_id = int(planned["layout_revision_id"])
        current = current_rows.get(revision_id)
        if current is None:
            connection.close()
            raise RuntimeError(f"Revision {revision_id} is missing")
        if current["source_path"] != planned["source_path"] or current["revision_status"] != planned["revision_status"]:
            connection.close()
            raise RuntimeError(f"Revision {revision_id} identity/status changed")
        if current["physical_tube_count"] is not None or current["layout_point_count"] is not None:
            connection.close()
            raise RuntimeError(f"Revision {revision_id} was already backfilled")
        if current["layout_count_basis"] != "UNKNOWN" or current["coverage_status"] != "UNKNOWN":
            connection.close()
            raise RuntimeError(f"Revision {revision_id} semantic defaults changed")
    connection.close()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_layout_count_backfill_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    logical_before = logical_hash(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_hash(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.execute("BEGIN IMMEDIATE")
        updated = 0
        for row in plan_rows:
            cursor = connection.execute(
                """UPDATE tube_layout_revision
                   SET physical_tube_count=?, layout_point_count=?, layout_count_basis=?,
                       coverage_status=?, unresolved_count=?, count_discrepancy_note=?
                   WHERE layout_revision_id=? AND source_path=? AND revision_status=?""",
                (
                    int(row["physical_tube_count"]), int(row["layout_point_count"]),
                    row["layout_count_basis"], row["coverage_status"],
                    int(row["unresolved_count"]), row["count_discrepancy_note"] or None,
                    int(row["layout_revision_id"]), row["source_path"], row["revision_status"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Revision {row['layout_revision_id']} update failed")
            updated += 1
        if updated != EXPECTED_REVISION_COUNT:
            raise RuntimeError(f"Updated {updated} revisions, expected {EXPECTED_REVISION_COUNT}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    basis_counts = dict(sorted(
        (row[0], row[1]) for row in connection.execute(
            "SELECT layout_count_basis, count(*) FROM tube_layout_revision GROUP BY layout_count_basis"
        )
    ))
    coverage_counts = dict(sorted(
        (row[0], row[1]) for row in connection.execute(
            "SELECT coverage_status, count(*) FROM tube_layout_revision GROUP BY coverage_status"
        )
    ))
    semantic_rows = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE physical_tube_count IS NOT NULL AND layout_point_count IS NOT NULL"
    ).fetchone()[0]
    connection.close()

    protected_keys = (
        "tube_count", "tube_xy_count", "revision_count", "point_count", "approved_count",
        "draft_count", "verified_point_count", "pending_point_count",
    )
    if any(before[key] != after[key] for key in protected_keys):
        raise RuntimeError(f"Protected state changed: before={before}, after={after}")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-backfill checks: {after}")
    if basis_counts != EXPECTED_BASIS or coverage_counts != EXPECTED_COVERAGE or semantic_rows != 58:
        raise RuntimeError(
            f"Semantic validation failed: basis={basis_counts}, coverage={coverage_counts}, rows={semantic_rows}"
        )

    result = {
        "status": "PASS",
        **plan,
        "before": before,
        "after": after,
        "semantic_row_count": semantic_rows,
        "actual_basis_counts": basis_counts,
        "actual_coverage_counts": coverage_counts,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    output = review_dir / "count_semantics_backfill_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
