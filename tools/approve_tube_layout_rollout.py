from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


EXPECTED = {
    "VCM1": {"revisions": 11, "points": 1348, "existing_links": 119, "unlinked": 1229},
    "VCM2": {"revisions": 41, "points": 17941, "existing_links": 937, "unlinked": 17004},
}
REQUIRED_CONFIRMATION = "USER_CONFIRMED_OPERATIONAL_ROLLOUT"


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


def snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "tube_count": connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0],
        "tube_xy_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0],
        "approved_revisions": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
        ).fetchone()[0],
        "draft_revisions": connection.execute(
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


def target_ids(workspace: Path, unit: str) -> list[int]:
    result = json.loads(
        (workspace / "outputs" / "tube_layout_review_20260908" / "rollout_draft_apply_result.json")
        .read_text(encoding="utf-8")
    )
    ids = [int(value) for value in result["staged_revision_ids"]]
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute(
            f"SELECT layout_revision_id, source_path FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders})",
            ids,
        ).fetchall()
    finally:
        connection.close()
    return [int(row[0]) for row in rows if str(row[1]).upper().startswith(unit + "\\")]


def validate_target(connection: sqlite3.Connection, ids: list[int], unit: str) -> dict[str, int]:
    expected = EXPECTED[unit]
    placeholders = ",".join("?" for _ in ids)
    revision = connection.execute(
        f"""SELECT count(*) AS revisions,
                   sum(revision_status='DRAFT') AS drafts,
                   count(DISTINCT bundle_id) AS bundles
            FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders})""",
        ids,
    ).fetchone()
    points = connection.execute(
        f"""SELECT count(*) AS points,
                   sum(verification_status='PENDING') AS pending,
                   sum(tube_id IS NOT NULL) AS existing_links,
                   sum(tube_id IS NULL) AS unlinked,
                   sum(canonical_x IS NOT NULL OR canonical_y IS NOT NULL) AS canonical_set,
                   sum(conflict_code IS NOT NULL) AS conflicts
            FROM tube_layout_point WHERE layout_revision_id IN ({placeholders})""",
        ids,
    ).fetchone()
    actual = {
        "revisions": int(revision[0]), "drafts": int(revision[1]), "bundles": int(revision[2]),
        "points": int(points[0]), "pending": int(points[1]),
        "existing_links": int(points[2]), "unlinked": int(points[3]),
        "canonical_set": int(points[4]), "conflicts": int(points[5]),
    }
    wanted = {
        "revisions": expected["revisions"], "drafts": expected["revisions"],
        "bundles": expected["revisions"], "points": expected["points"],
        "pending": expected["points"], "existing_links": expected["existing_links"],
        "unlinked": expected["unlinked"], "canonical_set": 0, "conflicts": 0,
    }
    if actual != wanted:
        raise RuntimeError(f"{unit} pre-approval validation failed: {actual} != {wanted}")
    return actual


def approve(db_path: Path, ids: list[int], unit: str) -> dict[str, Any]:
    connection = sqlite3.connect(db_path, timeout=30)
    before = snapshot(connection)
    if before["quick_check"] != "ok" or before["foreign_key_issues"]:
        connection.close()
        raise RuntimeError(f"Database failed pre-approval checks: {before}")
    expected = EXPECTED[unit]
    placeholders = ",".join("?" for _ in ids)
    approved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        precheck = validate_target(connection, ids, unit)
        point_cursor = connection.execute(
            f"""UPDATE tube_layout_point
                SET canonical_x=source_x,
                    canonical_y=source_y,
                    verification_status='VERIFIED',
                    review_note='Source MDB coordinates verified against the report Tube Map.'
                WHERE layout_revision_id IN ({placeholders})""",
            ids,
        )
        revision_cursor = connection.execute(
            f"""UPDATE tube_layout_revision
                SET normalized_view_direction='PDF_SOURCE_VIEW',
                    rotation_degrees=0,
                    flip_x=0,
                    flip_y=0,
                    scale_x=1,
                    scale_y=1,
                    offset_x=0,
                    offset_y=0,
                    revision_status='APPROVED',
                    review_note=review_note || ' Operational source-grid use approved; no silent axis rotation.',
                    approved_by='USER_CONFIRMED_OPERATIONAL_ROLLOUT',
                    approved_at=?
                WHERE layout_revision_id IN ({placeholders})""",
            [approved_at, *ids],
        )
        if point_cursor.rowcount != expected["points"] or revision_cursor.rowcount != expected["revisions"]:
            raise RuntimeError(
                f"{unit} update count mismatch: revisions={revision_cursor.rowcount}, points={point_cursor.rowcount}"
            )
        approved = connection.execute(
            f"SELECT count(*) FROM tube_layout_revision WHERE layout_revision_id IN ({placeholders}) AND revision_status='APPROVED'",
            ids,
        ).fetchone()[0]
        verified = connection.execute(
            f"""SELECT count(*) FROM tube_layout_point
                WHERE layout_revision_id IN ({placeholders})
                  AND verification_status='VERIFIED'
                  AND canonical_x=source_x AND canonical_y=source_y""",
            ids,
        ).fetchone()[0]
        if approved != expected["revisions"] or verified != expected["points"]:
            raise RuntimeError(f"{unit} in-transaction verification failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError(f"{unit} foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    connection.close()
    if after["tube_count"] != before["tube_count"] or after["tube_xy_count"] != before["tube_xy_count"]:
        raise RuntimeError("Existing Tube master data changed unexpectedly")
    if after["approved_revisions"] - before["approved_revisions"] != expected["revisions"]:
        raise RuntimeError(f"{unit} approved revision delta is incorrect")
    if after["verified_points"] - before["verified_points"] != expected["points"]:
        raise RuntimeError(f"{unit} verified point delta is incorrect")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-approval checks: {after}")
    return {"unit": unit, "precheck": precheck, "before": before, "after": after, "revision_ids": ids}


def main() -> int:
    parser = argparse.ArgumentParser(description="Operationally approve one validated Tube Layout rollout wave.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--unit", choices=sorted(EXPECTED), required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != REQUIRED_CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {REQUIRED_CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    ids = target_ids(workspace, args.unit)
    if len(ids) != EXPECTED[args.unit]["revisions"]:
        raise RuntimeError(f"{args.unit} revision ID count mismatch: {len(ids)}")
    if not args.apply:
        print(json.dumps({"unit": args.unit, **EXPECTED[args.unit], "revision_ids": ids}, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_layout_{args.unit.lower()}_approval_{stamp}.db"
    logical_before = logical_sqlite_sha256(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_sqlite_sha256(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    result = approve(db_path, ids, args.unit)
    result.update({
        "database_apply": True,
        "confirmation": args.confirmed_by,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    output = workspace / "outputs" / "tube_layout_review_20260908" / f"{args.unit.lower()}_operational_approval_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
