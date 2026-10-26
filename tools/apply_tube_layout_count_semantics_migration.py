from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


REQUIRED_CONFIRMATION = "USER_CONFIRMED_LAYOUT_COUNT_SEMANTICS_MIGRATION"
NEW_COLUMNS = (
    "physical_tube_count",
    "layout_point_count",
    "layout_count_basis",
    "coverage_status",
    "unresolved_count",
    "count_discrepancy_note",
)


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


def create_backup(source_path: Path, backup_path: Path) -> None:
    source = sqlite3.connect(source_path)
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def snapshot(connection: sqlite3.Connection) -> dict[str, int | str]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Tube Layout count-semantics columns.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    migration_path = workspace / "docs" / "migration_tube_layout_count_semantics.sql"
    read_connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        existing = {row[1] for row in read_connection.execute("PRAGMA table_info(tube_layout_revision)")}
        before_preview = snapshot(read_connection)
    finally:
        read_connection.close()
    missing = [column for column in NEW_COLUMNS if column not in existing]
    if not args.apply:
        print(json.dumps({"new_columns": missing, "before": before_preview, "database_apply": False}, indent=2))
        return 0
    if missing != list(NEW_COLUMNS):
        raise RuntimeError(f"Unexpected pre-migration schema; missing columns: {missing}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_layout_count_semantics_{stamp}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    logical_before = logical_hash(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_hash(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    connection = sqlite3.connect(db_path, timeout=30)
    before = snapshot(connection)
    try:
        sql = migration_path.read_text(encoding="utf-8")
        connection.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
    except Exception:
        connection.rollback()
        connection.close()
        raise
    after = snapshot(connection)
    columns = {row[1]: row for row in connection.execute("PRAGMA table_info(tube_layout_revision)")}
    defaults = {
        "layout_count_basis_unknown": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE layout_count_basis='UNKNOWN'"
        ).fetchone()[0],
        "coverage_status_unknown": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE coverage_status='UNKNOWN'"
        ).fetchone()[0],
        "unresolved_count_zero": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE unresolved_count=0"
        ).fetchone()[0],
    }
    connection.close()
    if not all(column in columns for column in NEW_COLUMNS):
        raise RuntimeError("Not all columns were added")
    if before != after:
        raise RuntimeError(f"Protected database counts/state changed: {before} != {after}")
    if any(value != before["layout_revision_count"] for value in defaults.values()):
        raise RuntimeError(f"Default-value validation failed: {defaults}")

    result = {
        "status": "PASS",
        "added_columns": list(NEW_COLUMNS),
        "before": before,
        "after": after,
        "default_validation": defaults,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    output = workspace / "outputs" / "tube_layout_review_20260908" / "count_semantics_migration_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
