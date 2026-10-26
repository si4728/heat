from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


DUPLICATE_REVISION_ID = 5
CANONICAL_REVISION_ID = 6
BUNDLE_ID = 46
POINT_COUNT = 647
LINKED_COUNT = 96
CONFIRMATION = "USER_REQUESTED_E106_DUPLICATE_CLEANUP"


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


def signature(connection: sqlite3.Connection, revision_id: int) -> list[tuple]:
    return connection.execute(
        """SELECT source_row, source_column, source_x, source_y
           FROM tube_layout_point WHERE layout_revision_id=?
           ORDER BY source_row, source_column, layout_point_id""",
        (revision_id,),
    ).fetchall()


def validate(connection: sqlite3.Connection) -> dict:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT layout_revision_id,bundle_id,inspection_id,source_path,source_checksum,
                  revision_status,physical_tube_count,layout_point_count,coverage_status
           FROM tube_layout_revision WHERE layout_revision_id IN (5,6)
           ORDER BY layout_revision_id"""
    ).fetchall()
    if len(rows) != 2:
        raise RuntimeError("Expected E-106 revisions 5 and 6")
    duplicate, canonical = rows
    if duplicate["bundle_id"] != BUNDLE_ID or canonical["bundle_id"] != BUNDLE_ID:
        raise RuntimeError("E-106 bundle identity mismatch")
    if duplicate["inspection_id"] != canonical["inspection_id"]:
        raise RuntimeError("Inspection identity mismatch")
    if duplicate["revision_status"] != "DRAFT" or canonical["revision_status"] != "APPROVED":
        raise RuntimeError("Unexpected revision statuses")
    for row in rows:
        if row["physical_tube_count"] != POINT_COUNT or row["layout_point_count"] != POINT_COUNT:
            raise RuntimeError("Unexpected E-106 point count")
        counts = connection.execute(
            "SELECT count(*),sum(tube_id IS NOT NULL) FROM tube_layout_point WHERE layout_revision_id=?",
            (row["layout_revision_id"],),
        ).fetchone()
        if tuple(counts) != (POINT_COUNT, LINKED_COUNT):
            raise RuntimeError(f"Point/link count mismatch: {tuple(counts)}")
    if signature(connection, 5) != signature(connection, 6):
        raise RuntimeError("Coordinate signatures are not identical")
    return {
        "bundle_id": BUNDLE_ID,
        "duplicate_revision_id": DUPLICATE_REVISION_ID,
        "canonical_revision_id": CANONICAL_REVISION_ID,
        "coordinate_sets_identical": True,
        "point_count": POINT_COUNT,
        "linked_count": LINKED_COUNT,
        "sources": [dict(row) for row in rows],
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
    precheck = validate(connection)
    if not args.apply:
        print(json.dumps({"database_apply": False, "precheck": precheck}, ensure_ascii=False, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_e106_duplicate_cleanup_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    before_hash = logical_hash(db_path)
    backup = sqlite3.connect(backup_path)
    connection.backup(backup)
    backup.close()
    if logical_hash(backup_path) != before_hash:
        raise RuntimeError("Backup logical hash mismatch")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """UPDATE tube_layout_revision
               SET revision_status='REJECTED',
                   review_note='Non-canonical duplicate of approved E-106 Revision 6; identical 647-point coordinate set retained for provenance.',
                   reviewed_by=?, reviewed_at=?
               WHERE layout_revision_id=? AND revision_status='DRAFT'""",
            (CONFIRMATION, now, DUPLICATE_REVISION_ID),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Duplicate revision update count mismatch")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    verify = sqlite3.connect(db_path)
    result = {
        "database_apply": True,
        "completed_at": now,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": logical_hash(backup_path),
        "quick_check": verify.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(verify.execute("PRAGMA foreign_key_check").fetchall()),
        "status_counts": dict(verify.execute("SELECT revision_status,count(*) FROM tube_layout_revision GROUP BY revision_status").fetchall()),
        "precheck": precheck,
    }
    verify.close()
    output_dir = workspace / "outputs" / "tube_layout_review_20260909"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "e106_duplicate_cleanup_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
