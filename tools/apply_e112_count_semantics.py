from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


CONFIRMATION = "USER_APPROVED_E112_COUNT_SEMANTICS"
REVISION_ID = 33
EXPECTED_POINTS = 81


def logical_hash(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        for line in connection.iterdump():
            digest.update((line + "\n").encode())
    finally:
        connection.close()
    return digest.hexdigest()


def revision_snapshot(connection: sqlite3.Connection) -> dict:
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        """SELECT r.layout_revision_id, r.bundle_id, r.revision_status,
                  r.physical_tube_count, r.layout_point_count,
                  r.layout_count_basis, r.coverage_status, r.unresolved_count,
                  r.source_path, r.source_section_name,
                  count(p.layout_point_id) AS point_count,
                  sum(p.verification_status='VERIFIED') AS verified_count,
                  sum(p.tube_id IS NOT NULL) AS linked_count
           FROM tube_layout_revision r
           LEFT JOIN tube_layout_point p
             ON p.layout_revision_id=r.layout_revision_id
           WHERE r.layout_revision_id=?
           GROUP BY r.layout_revision_id""",
        (REVISION_ID,),
    ).fetchone()
    if not row:
        raise RuntimeError("E-112 Revision #33 was not found")
    return dict(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {CONFIRMATION}")

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    before = revision_snapshot(connection)
    expected = {
        "revision_status": "APPROVED",
        "physical_tube_count": EXPECTED_POINTS,
        "layout_point_count": EXPECTED_POINTS,
        "layout_count_basis": "UNKNOWN",
        "coverage_status": "UNKNOWN",
        "unresolved_count": 0,
        "point_count": EXPECTED_POINTS,
        "verified_count": EXPECTED_POINTS,
    }
    for key, value in expected.items():
        if before[key] != value:
            raise RuntimeError(f"Precheck mismatch for {key}: {before[key]!r} != {value!r}")
    if "E-112" not in before["source_path"]:
        raise RuntimeError("Revision #33 source identity is not E-112")
    if not args.apply:
        print(json.dumps({"database_apply": False, "precheck": before}, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_e112_count_semantics_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    before_hash = logical_hash(db_path)
    backup = sqlite3.connect(backup_path)
    connection.backup(backup)
    backup.close()
    backup_hash = logical_hash(backup_path)
    if backup_hash != before_hash:
        raise RuntimeError("Backup logical hash mismatch")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """UPDATE tube_layout_revision
               SET layout_count_basis='PHYSICAL_TUBE',
                   coverage_status='FULL',
                   count_discrepancy_note=(
                       CASE WHEN count_discrepancy_note IS NULL OR trim(count_discrepancy_note)=''
                            THEN ? ELSE count_discrepancy_note || ' | ' || ? END
                   )
               WHERE layout_revision_id=?
                 AND revision_status='APPROVED'
                 AND layout_count_basis='UNKNOWN'
                 AND coverage_status='UNKNOWN'""",
            (
                "E-112 source evidence: 2020/2023/2025 total=81; 2025 U-Bend, Front View (North) - Inlet; layout=81.",
                "E-112 source evidence: 2020/2023/2025 total=81; 2025 U-Bend, Front View (North) - Inlet; layout=81.",
                REVISION_ID,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Expected one revision update, got {cursor.rowcount}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    verify = sqlite3.connect(db_path)
    after = revision_snapshot(verify)
    quick_check = verify.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(verify.execute("PRAGMA foreign_key_check").fetchall())
    global_counts = {
        "revision_status": dict(verify.execute(
            "SELECT revision_status, count(*) FROM tube_layout_revision GROUP BY revision_status"
        ).fetchall()),
        "point_status": dict(verify.execute(
            "SELECT verification_status, count(*) FROM tube_layout_point GROUP BY verification_status"
        ).fetchall()),
    }
    verify.close()
    if after["layout_count_basis"] != "PHYSICAL_TUBE" or after["coverage_status"] != "FULL":
        raise RuntimeError("E-112 count semantics verification failed")
    for protected in ("revision_status", "physical_tube_count", "layout_point_count", "unresolved_count", "point_count", "verified_count", "linked_count"):
        if after[protected] != before[protected]:
            raise RuntimeError(f"Protected field changed: {protected}")

    result = {
        "database_apply": True,
        "completed_at": now,
        "updated_revision_count": 1,
        "updated_fields": {
            "layout_count_basis": ["UNKNOWN", "PHYSICAL_TUBE"],
            "coverage_status": ["UNKNOWN", "FULL"],
        },
        "backup_file": str(backup_path),
        "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": backup_hash,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "before": before,
        "after": after,
        "global_counts": global_counts,
    }
    output_dir = workspace / "outputs" / "tube_layout_review_20260910"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "e112_count_semantics_result.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
