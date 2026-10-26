from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


APPROVED_REVISIONS = {
    1: {
        "bundle_id": 24,
        "source_path": r"VCM1\2025\E-281B\MAP\E-281B CARTO.MDB",
        "checksum": "fe36890e5d8f4e961a740c0ad0035dc2329a7a0550e880e8f9d95fa0fc156055",
        "points": 46,
    },
    2: {
        "bundle_id": 25,
        "source_path": r"VCM1\2025\E-282\MAP\E-282 CARTO.MDB",
        "checksum": "e7c373d2f43b54ee45d945c8fecee33faa658cfe661dd89b5ffb53ebbe8c322f",
        "points": 732,
    },
    6: {
        "bundle_id": 46,
        "source_path": r"VCM2\2025\E-106\MAP\E-106.MDB",
        "checksum": "6520f75f154b72516795cdf04807a5d663bc8fd7722e25665ea8145134485dbf",
        "points": 647,
    },
}
DEFERRED_BUNDLE_ID = 29
REQUIRED_APPROVAL = "운영 Layout 승인"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def logical_sqlite_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError(f"DB 무결성 검사 실패: {path}")
        for line in connection.iterdump():
            digest.update(line.encode("utf-8"))
            digest.update(b"\n")
    finally:
        connection.close()
    return digest.hexdigest()


def snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    return {
        "tube_count": connection.execute("SELECT count(*) FROM heat_exchanger_tube").fetchone()[0],
        "tube_xy_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0],
        "approved_revisions": connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
        ).fetchone()[0],
        "verified_points": connection.execute(
            "SELECT count(*) FROM tube_layout_point WHERE verification_status='VERIFIED'"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }


def validate_revisions(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    for revision_id, expected in APPROVED_REVISIONS.items():
        row = connection.execute(
            """SELECT layout_revision_id, bundle_id, source_path, source_checksum,
                      revision_status
               FROM tube_layout_revision WHERE layout_revision_id=?""",
            (revision_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Revision {revision_id}가 없습니다.")
        for field, expected_value in (
            ("bundle_id", expected["bundle_id"]),
            ("source_path", expected["source_path"]),
            ("source_checksum", expected["checksum"]),
        ):
            if row[field] != expected_value:
                raise RuntimeError(
                    f"Revision {revision_id} {field} 불일치: {row[field]!r} != {expected_value!r}"
                )
        if row["revision_status"] not in {"DRAFT", "APPROVED"}:
            raise RuntimeError(f"Revision {revision_id} 상태가 승인 대상이 아닙니다: {row['revision_status']}")
        counts = connection.execute(
            """SELECT count(*) total,
                      sum(conflict_code IS NOT NULL) conflicts,
                      sum(source_x IS NULL OR source_y IS NULL) missing_xy
               FROM tube_layout_point WHERE layout_revision_id=?""",
            (revision_id,),
        ).fetchone()
        if counts["total"] != expected["points"] or counts["conflicts"] or counts["missing_xy"]:
            raise RuntimeError(f"Revision {revision_id} Point 검증 실패: {dict(counts)}")

    deferred = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE bundle_id=? AND revision_status='APPROVED'",
        (DEFERRED_BUNDLE_ID,),
    ).fetchone()[0]
    if deferred:
        raise RuntimeError("보류 대상 E-331A Bundle에 승인 Revision이 존재합니다.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve the reviewed Tube Layout pilot revisions.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--backup-file", type=Path, required=True)
    parser.add_argument("--expected-db-sha256", required=True)
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    db_path = args.db.resolve()
    backup_path = args.backup_file.resolve()
    if db_path != workspace / "data" / "heat_exchanger_db3.db":
        raise RuntimeError(f"승인된 DB 경로가 아닙니다: {db_path}")
    if not backup_path.is_file():
        raise FileNotFoundError(backup_path)
    current_file_hash = file_sha256(db_path)
    if current_file_hash != args.expected_db_sha256:
        raise RuntimeError("현재 DB 해시가 승인 직전 해시와 다릅니다.")
    current_logical_hash = logical_sqlite_sha256(db_path)
    backup_logical_hash = logical_sqlite_sha256(backup_path)
    if current_logical_hash != backup_logical_hash:
        raise RuntimeError("백업 DB가 현재 DB와 논리적으로 동일하지 않습니다.")

    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    validate_revisions(connection)
    before = snapshot(connection)
    plan = {
        "approve_revision_ids": sorted(APPROVED_REVISIONS),
        "approve_bundle_ids": sorted(item["bundle_id"] for item in APPROVED_REVISIONS.values()),
        "deferred_bundle_id": DEFERRED_BUNDLE_ID,
        "point_count": sum(item["points"] for item in APPROVED_REVISIONS.values()),
        "database_apply": bool(args.apply),
    }
    if not args.apply:
        connection.close()
        print(json.dumps({"plan": plan, "before": before}, ensure_ascii=False, indent=2))
        return 0
    if args.approved_by != REQUIRED_APPROVAL:
        connection.close()
        raise RuntimeError(f"--approved-by 값은 '{REQUIRED_APPROVAL}'이어야 합니다.")

    approved_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for revision_id in APPROVED_REVISIONS:
            connection.execute(
                """UPDATE tube_layout_point
                   SET canonical_x=source_x,
                       canonical_y=source_y,
                       verification_status='VERIFIED',
                       review_note='원본 PDF 화면 좌표계 X 오른쪽 Y 아래 기준 검증'
                   WHERE layout_revision_id=?""",
                (revision_id,),
            )
            connection.execute(
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
                       review_note='원본 PDF 방향 유지. X 오른쪽, Y 아래, 기본 회전 0도.',
                       approved_by=?,
                       approved_at=?
                   WHERE layout_revision_id=?""",
                (args.approved_by, approved_at, revision_id),
            )
        if connection.execute(
            "SELECT count(*) FROM tube_layout_revision WHERE bundle_id=? AND revision_status='APPROVED'",
            (DEFERRED_BUNDLE_ID,),
        ).fetchone()[0]:
            raise RuntimeError("보류 대상 E-331A가 승인되었습니다.")
        fk_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise RuntimeError(f"외래키 오류 {len(fk_issues)}건")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = snapshot(connection)
    approved_rows = [
        dict(row) for row in connection.execute(
            """SELECT layout_revision_id, bundle_id, source_path, revision_status,
                      normalized_view_direction, rotation_degrees, flip_x, flip_y
               FROM tube_layout_revision
               WHERE revision_status='APPROVED'
               ORDER BY bundle_id"""
        )
    ]
    deferred_rows = [
        dict(row) for row in connection.execute(
            """SELECT layout_revision_id, bundle_id, source_path, revision_status
               FROM tube_layout_revision WHERE bundle_id=? ORDER BY layout_revision_id""",
            (DEFERRED_BUNDLE_ID,),
        )
    ]
    connection.close()
    if before["tube_count"] != after["tube_count"] or before["tube_xy_count"] != after["tube_xy_count"]:
        raise RuntimeError("기존 튜브 마스터 또는 position_x/y가 변경되었습니다.")
    if after["quick_check"] != "ok" or after["foreign_key_issues"]:
        raise RuntimeError(f"적용 후 DB 무결성 오류: {after}")

    report = {
        "completed_at": approved_at,
        "approved_by": args.approved_by,
        "plan": plan,
        "before": before,
        "after": after,
        "approved_revisions": approved_rows,
        "deferred_revisions": deferred_rows,
        "backup_file": str(backup_path),
        "database_sha256_before": current_file_hash,
        "database_sha256_after": file_sha256(db_path),
        "database_logical_sha256_before": current_logical_hash,
        "backup_logical_sha256": backup_logical_hash,
    }
    args.report.resolve().write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
