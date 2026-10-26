from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


CANONICAL_REVISION_ID = 4
DUPLICATE_REVISION_ID = 3
BUNDLE_ID = 29
POINT_COUNT = 20
LINKED_COUNT = 8
CONFIRMATION = "USER_CONFIRMED_E331A_CANONICAL_LAYOUT"
EXPECTED = {
    3: {
        "source_path": r"VCM1\2025\E-331A\E-331A BOTTOM\MAP\E-331A (BTM) CARTO.MDB",
        "checksum": "cc79d910827032c82d906f9e14d27043fbfb20e76ace8887695ef9bf3ada5000",
    },
    4: {
        "source_path": r"VCM1\2025\E-331A\E-331A TOP\MAP\E-331A (TOP) CARTO.MDB",
        "checksum": "8564d8e351b1072bf409ab4a8aed2c3d8b6365dafef352dd43c214f02269041d",
    },
}


def file_sha256(path: Path) -> str:
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
            raise RuntimeError(f"Database integrity check failed: {path}")
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
        "rejected_revisions": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='REJECTED'"
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


def point_signature(connection: sqlite3.Connection, revision_id: int) -> list[tuple[Any, ...]]:
    return connection.execute(
        """SELECT source_row, source_column, source_x, source_y
           FROM tube_layout_point
           WHERE layout_revision_id=?
           ORDER BY source_row, source_column, layout_point_id""",
        (revision_id,),
    ).fetchall()


def validate_target(connection: sqlite3.Connection) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT layout_revision_id, bundle_id, source_path, source_checksum,
                  revision_status, physical_tube_count, layout_point_count,
                  layout_count_basis
           FROM tube_layout_revision
           WHERE layout_revision_id IN (?, ?)
           ORDER BY layout_revision_id""",
        (DUPLICATE_REVISION_ID, CANONICAL_REVISION_ID),
    ).fetchall()
    if len(rows) != 2:
        raise RuntimeError(f"Expected two E-331A revisions, found {len(rows)}")
    for row in rows:
        expected = EXPECTED[int(row["layout_revision_id"])]
        if int(row["bundle_id"]) != BUNDLE_ID:
            raise RuntimeError(f"Revision {row['layout_revision_id']} bundle mismatch")
        if row["source_path"] != expected["source_path"] or row["source_checksum"] != expected["checksum"]:
            raise RuntimeError(f"Revision {row['layout_revision_id']} source identity mismatch")
        if row["revision_status"] != "DRAFT":
            raise RuntimeError(f"Revision {row['layout_revision_id']} is not DRAFT")
        if int(row["physical_tube_count"]) != POINT_COUNT or int(row["layout_point_count"]) != POINT_COUNT:
            raise RuntimeError(f"Revision {row['layout_revision_id']} count metadata mismatch")
        if row["layout_count_basis"] != "PHYSICAL_TUBE":
            raise RuntimeError(f"Revision {row['layout_revision_id']} count basis mismatch")

        counts = connection.execute(
            """SELECT count(*) AS total,
                      sum(tube_id IS NOT NULL) AS linked,
                      sum(source_x IS NULL OR source_y IS NULL) AS missing_xy,
                      sum(conflict_code IS NOT NULL) AS conflicts,
                      sum(canonical_x IS NOT NULL OR canonical_y IS NOT NULL) AS canonical_set
               FROM tube_layout_point WHERE layout_revision_id=?""",
            (row["layout_revision_id"],),
        ).fetchone()
        actual = tuple(int(value or 0) for value in counts)
        if actual != (POINT_COUNT, LINKED_COUNT, 0, 0, 0):
            raise RuntimeError(f"Revision {row['layout_revision_id']} point validation failed: {actual}")

    if point_signature(connection, DUPLICATE_REVISION_ID) != point_signature(connection, CANONICAL_REVISION_ID):
        raise RuntimeError("TOP and BTM coordinate signatures differ")
    approved_for_bundle = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE bundle_id=? AND revision_status='APPROVED'",
        (BUNDLE_ID,),
    ).fetchone()[0]
    if approved_for_bundle:
        raise RuntimeError("Bundle 29 already has an approved revision")
    return {
        "bundle_id": BUNDLE_ID,
        "canonical_revision_id": CANONICAL_REVISION_ID,
        "duplicate_revision_id": DUPLICATE_REVISION_ID,
        "point_count": POINT_COUNT,
        "linked_count": LINKED_COUNT,
        "unlinked_count": POINT_COUNT - LINKED_COUNT,
        "coordinate_sets_identical": True,
    }


def apply_approval(db_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.execute("PRAGMA foreign_keys=ON")
    before = snapshot(connection)
    if before["quick_check"] != "ok" or before["foreign_key_issues"]:
        connection.close()
        raise RuntimeError(f"Database failed pre-approval checks: {before}")
    approved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        precheck = validate_target(connection)
        point_cursor = connection.execute(
            """UPDATE tube_layout_point
               SET canonical_x=source_x,
                   canonical_y=source_y,
                   verification_status='VERIFIED',
                   review_note='E-331A 20-point source grid verified; TOP and BTM coordinate sets are identical.'
               WHERE layout_revision_id=?""",
            (CANONICAL_REVISION_ID,),
        )
        revision_cursor = connection.execute(
            """UPDATE tube_layout_revision
               SET normalized_view_direction='PDF_SOURCE_VIEW',
                   rotation_degrees=0,
                   flip_x=0,
                   flip_y=0,
                   scale_x=1,
                   scale_y=1,
                   offset_x=0,
                   offset_y=0,
                   revision_status='APPROVED',
                   coverage_status='FULL',
                   count_discrepancy_note='Documented Tube Map label typo: E-330C; surrounding report and MDB provenance identify E-331A TOP.',
                   review_note='Canonical E-331A 20-point layout. TOP and BTM grids are coordinate-identical; both source paths retained as provenance.',
                   approved_by=?,
                   approved_at=?
               WHERE layout_revision_id=?""",
            (CONFIRMATION, approved_at, CANONICAL_REVISION_ID),
        )
        duplicate_cursor = connection.execute(
            """UPDATE tube_layout_revision
               SET revision_status='REJECTED',
                   coverage_status='FULL',
                   count_discrepancy_note='Duplicate of canonical Revision 4; Tube Map heading E-330C is a documented source-label typo.',
                   review_note='Non-canonical duplicate source retained for provenance. Coordinates are identical to approved E-331A TOP Revision 4.',
                   reviewed_by=?,
                   reviewed_at=?
               WHERE layout_revision_id=?""",
            (CONFIRMATION, approved_at, DUPLICATE_REVISION_ID),
        )
        if point_cursor.rowcount != POINT_COUNT or revision_cursor.rowcount != 1 or duplicate_cursor.rowcount != 1:
            raise RuntimeError(
                f"Update count mismatch: points={point_cursor.rowcount}, canonical={revision_cursor.rowcount}, duplicate={duplicate_cursor.rowcount}"
            )
        approved_for_bundle = connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE bundle_id=? AND revision_status='APPROVED'",
            (BUNDLE_ID,),
        ).fetchone()[0]
        verified = connection.execute(
            """SELECT count(*) FROM tube_layout_point
               WHERE layout_revision_id=? AND verification_status='VERIFIED'
                 AND canonical_x=source_x AND canonical_y=source_y""",
            (CANONICAL_REVISION_ID,),
        ).fetchone()[0]
        duplicate_pending = connection.execute(
            """SELECT count(*) FROM tube_layout_point
               WHERE layout_revision_id=? AND verification_status='PENDING'
                 AND canonical_x IS NULL AND canonical_y IS NULL""",
            (DUPLICATE_REVISION_ID,),
        ).fetchone()[0]
        if approved_for_bundle != 1 or verified != POINT_COUNT or duplicate_pending != POINT_COUNT:
            raise RuntimeError("In-transaction canonical/duplicate verification failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    connection.close()
    expected_deltas = {
        "approved_revisions": 1,
        "draft_revisions": -2,
        "rejected_revisions": 1,
        "verified_points": POINT_COUNT,
        "pending_points": -POINT_COUNT,
    }
    for key, delta in expected_deltas.items():
        if after[key] - before[key] != delta:
            raise RuntimeError(f"Unexpected {key} delta: {after[key] - before[key]} != {delta}")
    if before["tube_count"] != after["tube_count"] or before["tube_xy_count"] != after["tube_xy_count"]:
        raise RuntimeError("Tube master data changed unexpectedly")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"Database failed post-approval checks: {after}")
    return {"precheck": precheck, "before": before, "after": after, "approved_at": approved_at}


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve the canonical E-331A 20-point Tube Layout.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.confirmed_by != CONFIRMATION:
        raise RuntimeError(f"--confirmed-by must be {CONFIRMATION!r}")

    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    if not args.apply:
        connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            precheck = validate_target(connection)
            state = snapshot(connection)
        finally:
            connection.close()
        print(json.dumps({"database_apply": False, "precheck": precheck, "state": state}, indent=2))
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = workspace / "backups" / "files" / f"iris_db_before_e331a_canonical_approval_{stamp}.db"
    logical_before = logical_sqlite_sha256(db_path)
    create_backup(db_path, backup_path)
    backup_logical = logical_sqlite_sha256(backup_path)
    if backup_logical != logical_before:
        raise RuntimeError("Backup logical hash mismatch")

    result = apply_approval(db_path)
    result.update({
        "database_apply": True,
        "confirmation": args.confirmed_by,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": logical_before,
        "backup_logical_sha256": backup_logical,
        "database_sha256_after": file_sha256(db_path),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    output = workspace / "outputs" / "tube_layout_review_20260908" / "e331a_canonical_approval_result.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
