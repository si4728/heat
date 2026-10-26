from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


CONFIRMATION = "USER_APPROVED_REJECTED_LAYOUT_POINT_CLEANUP"
EXPECTED_REVISIONS = 2
EXPECTED_POINTS = 667


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


def snapshot(connection: sqlite3.Connection) -> dict:
    return {
        "revision_status_counts": dict(
            connection.execute(
                "SELECT revision_status, count(*) FROM tube_layout_revision GROUP BY revision_status"
            ).fetchall()
        ),
        "point_status_counts": dict(
            connection.execute(
                "SELECT verification_status, count(*) FROM tube_layout_point GROUP BY verification_status"
            ).fetchall()
        ),
        "rejected_revision_pending_points": connection.execute(
            """SELECT count(*)
               FROM tube_layout_point p
               JOIN tube_layout_revision r ON r.layout_revision_id=p.layout_revision_id
               WHERE r.revision_status='REJECTED' AND p.verification_status='PENDING'"""
        ).fetchone()[0],
        "total_revisions": connection.execute("SELECT count(*) FROM tube_layout_revision").fetchone()[0],
        "total_points": connection.execute("SELECT count(*) FROM tube_layout_point").fetchone()[0],
        "tube_rows": connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0],
        "tube_rows_with_xy": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL OR position_y IS NOT NULL"
        ).fetchone()[0],
    }


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
    before = snapshot(connection)
    rejected_revisions = connection.execute(
        """SELECT r.layout_revision_id, b.bundle_code, count(p.layout_point_id)
           FROM tube_layout_revision r
           JOIN tube_bundle b ON b.bundle_id=r.bundle_id
           LEFT JOIN tube_layout_point p ON p.layout_revision_id=r.layout_revision_id
           WHERE r.revision_status='REJECTED'
           GROUP BY r.layout_revision_id, b.bundle_code
           ORDER BY r.layout_revision_id"""
    ).fetchall()
    if len(rejected_revisions) != EXPECTED_REVISIONS:
        raise RuntimeError(f"Expected {EXPECTED_REVISIONS} rejected revisions, got {len(rejected_revisions)}")
    if before["rejected_revision_pending_points"] != EXPECTED_POINTS:
        raise RuntimeError(
            f"Expected {EXPECTED_POINTS} rejected-revision pending points, got "
            f"{before['rejected_revision_pending_points']}"
        )
    if before["revision_status_counts"].get("DRAFT", 0) != 0:
        raise RuntimeError("Unexpected DRAFT revisions; cleanup scope must be re-reviewed")

    if not args.apply:
        print(json.dumps({"database_apply": False, "before": before}, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_rejected_layout_point_cleanup_{stamp}.db"
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
            """UPDATE tube_layout_point
               SET verification_status='REJECTED'
               WHERE verification_status='PENDING'
                 AND layout_revision_id IN (
                     SELECT layout_revision_id FROM tube_layout_revision
                     WHERE revision_status='REJECTED'
                 )"""
        )
        if cursor.rowcount != EXPECTED_POINTS:
            raise RuntimeError(f"Updated {cursor.rowcount} points, expected {EXPECTED_POINTS}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    verify = sqlite3.connect(db_path)
    after = snapshot(verify)
    quick_check = verify.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(verify.execute("PRAGMA foreign_key_check").fetchall())
    verify.close()
    if after["rejected_revision_pending_points"] != 0:
        raise RuntimeError("Rejected revisions still contain pending points")
    if after["point_status_counts"].get("REJECTED", 0) != EXPECTED_POINTS:
        raise RuntimeError("Rejected point count mismatch after cleanup")
    for protected_key in ("revision_status_counts", "total_revisions", "total_points", "tube_rows", "tube_rows_with_xy"):
        if after[protected_key] != before[protected_key]:
            raise RuntimeError(f"Protected state changed: {protected_key}")

    result = {
        "database_apply": True,
        "completed_at": now,
        "scope": "PENDING points belonging to REJECTED layout revisions only",
        "updated_points": EXPECTED_POINTS,
        "rejected_revisions": [
            {"layout_revision_id": row[0], "bundle_code": row[1], "point_count": row[2]}
            for row in rejected_revisions
        ],
        "backup_file": str(backup_path),
        "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": backup_hash,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "before": before,
        "after": after,
    }
    output_dir = workspace / "outputs" / "tube_layout_review_20260910"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "rejected_layout_point_cleanup_result.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
