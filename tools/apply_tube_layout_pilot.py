from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any


PILOT_BUNDLE_IDS = (24, 25, 29, 46)
REQUIRED_APPROVAL = "DB 반영 승인"


def sha256(path: Path) -> str:
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def split_sources(value: str) -> list[str]:
    return [item.strip() for item in value.split(" | ") if item.strip()]


def resolve_source(root: Path, relative: str) -> Path:
    return root.joinpath(*PureWindowsPath(relative).parts)


def validate_target(db_path: Path, workspace: Path) -> None:
    resolved_db = db_path.resolve()
    resolved_workspace = workspace.resolve()
    if resolved_db != resolved_workspace / "data" / "heat_exchanger_db3.db":
        raise RuntimeError(f"승인된 DB 경로가 아닙니다: {resolved_db}")
    if not resolved_db.is_file():
        raise FileNotFoundError(resolved_db)


def build_plan(review_dir: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    revisions = [
        row for row in read_csv(review_dir / "layout_revisions.csv")
        if int(row["bundle_id"]) in PILOT_BUNDLE_IDS
    ]
    candidates = [
        row for row in read_csv(review_dir / "tube_layout_candidates.csv")
        if int(row["bundle_id"]) in PILOT_BUNDLE_IDS
    ]
    if len(revisions) != 6:
        raise RuntimeError(f"Pilot Revision은 6개여야 합니다: {len(revisions)}")
    if len(candidates) != 1445:
        raise RuntimeError(f"Pilot 고유 좌표는 1,445개여야 합니다: {len(candidates)}")
    if any(row["review_status"] != "PENDING" for row in candidates):
        raise RuntimeError("충돌 또는 검토 상태가 변경된 좌표 후보가 있습니다.")
    if any(row["count_status"] != "MATCH" for row in revisions):
        raise RuntimeError("Section 수량 검증을 통과하지 못한 Revision이 있습니다.")
    return revisions, candidates


def point_count(revisions: list[dict[str, str]], candidates: list[dict[str, str]]) -> int:
    return sum(
        1
        for revision in revisions
        for candidate in candidates
        if candidate["bundle_id"] == revision["bundle_id"]
        and revision["source_path"] in split_sources(candidate["source_paths"])
    )


def database_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    snapshot: dict[str, Any] = {
        "existing_tube_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube"
        ).fetchone()[0],
        "existing_xy_count": connection.execute(
            "SELECT count(*) FROM heat_exchanger_tube WHERE position_x IS NOT NULL AND position_y IS NOT NULL"
        ).fetchone()[0],
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }
    snapshot["layout_revision_count"] = (
        connection.execute("SELECT count(*) FROM tube_layout_revision").fetchone()[0]
        if "tube_layout_revision" in tables else 0
    )
    snapshot["layout_point_count"] = (
        connection.execute("SELECT count(*) FROM tube_layout_point").fetchone()[0]
        if "tube_layout_point" in tables else 0
    )
    return snapshot


def apply(
    db_path: Path,
    migration_path: Path,
    source_root: Path,
    revisions: list[dict[str, str]],
    candidates: list[dict[str, str]],
    approved_by: str,
) -> dict[str, Any]:
    connection = sqlite3.connect(db_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    before = database_snapshot(connection)
    if before["quick_check"] != "ok" or before["foreign_key_issues"]:
        connection.close()
        raise RuntimeError(f"적용 전 DB 무결성 오류: {before}")
    try:
        migration_sql = migration_path.read_text(encoding="utf-8")
        connection.executescript("BEGIN IMMEDIATE;\n" + migration_sql)
        inserted_revisions = 0
        inserted_points = 0
        revision_ids: dict[tuple[int, str, int], int] = {}

        for row in revisions:
            source_path = row["source_path"]
            source_file = resolve_source(source_root, source_path)
            if not source_file.is_file():
                raise FileNotFoundError(f"원본 MDB가 없습니다: {source_file}")
            key = (int(row["bundle_id"]), source_path, int(row["section_id"]))
            cursor = connection.execute(
                """INSERT OR IGNORE INTO tube_layout_revision (
                       bundle_id, inspection_id, source_path, source_checksum,
                       source_section_id, source_section_name, source_coordinate_unit,
                       source_origin_code, source_row_spacing, source_column_spacing,
                       source_scale_metric, rotation_degrees, flip_x, flip_y,
                       revision_status, review_note, reviewed_by, reviewed_at
                   ) VALUES (?, ?, ?, ?, ?, ?, 'GRID', ?, ?, ?, ?, ?, NULL, NULL,
                             'DRAFT', ?, ?, ?)""",
                (
                    key[0], int(row["inspection_id"]), source_path, sha256(source_file),
                    key[2], row["section_name"],
                    int(row["origin_code"]) if row["origin_code"] else None,
                    float(row["row_spacing"]) if row["row_spacing"] else None,
                    float(row["column_spacing"]) if row["column_spacing"] else None,
                    1 if row["scale_metric"].lower() == "true" else 0,
                    None,
                    "Pilot 원천 좌표 적재. 방향과 축 반전은 별도 화면 대조 후 확정.",
                    approved_by,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
            inserted_revisions += cursor.rowcount
            revision_id = connection.execute(
                """SELECT layout_revision_id FROM tube_layout_revision
                   WHERE bundle_id=? AND source_path=? AND source_section_id=?""",
                key,
            ).fetchone()[0]
            revision_ids[key] = int(revision_id)

        for revision in revisions:
            key = (
                int(revision["bundle_id"]), revision["source_path"],
                int(revision["section_id"]),
            )
            revision_id = revision_ids[key]
            for row in candidates:
                if int(row["bundle_id"]) != key[0]:
                    continue
                if key[1] not in split_sources(row["source_paths"]):
                    continue
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO tube_layout_point (
                           layout_revision_id, tube_id, source_tube_id,
                           source_row, source_column, source_x, source_y,
                           source_original_x, source_original_y,
                           mapping_status, verification_status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                    (
                        revision_id,
                        int(row["existing_tube_id"]) if row["existing_tube_id"] else None,
                        row["existing_tube_no"] or f"{row['row']}-{row['column']}",
                        int(row["row"]), int(row["column"]),
                        float(row["source_x"]), float(row["source_y"]),
                        float(row["original_x"]) if row["original_x"] else None,
                        float(row["original_y"]) if row["original_y"] else None,
                        row["mapping_status"],
                    ),
                )
                inserted_points += cursor.rowcount

        fk_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        if fk_issues:
            raise RuntimeError(f"적용 중 외래키 오류 {len(fk_issues)}건")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise

    after = database_snapshot(connection)
    pilot = {
        "revision_count": connection.execute(
            f"SELECT count(*) FROM tube_layout_revision WHERE bundle_id IN ({','.join('?' for _ in PILOT_BUNDLE_IDS)})",
            PILOT_BUNDLE_IDS,
        ).fetchone()[0],
        "point_count": connection.execute(
            f"""SELECT count(*) FROM tube_layout_point p
                JOIN tube_layout_revision r ON r.layout_revision_id=p.layout_revision_id
                WHERE r.bundle_id IN ({','.join('?' for _ in PILOT_BUNDLE_IDS)})""",
            PILOT_BUNDLE_IDS,
        ).fetchone()[0],
        "linked_existing_tube_count": connection.execute(
            f"""SELECT count(*) FROM tube_layout_point p
                JOIN tube_layout_revision r ON r.layout_revision_id=p.layout_revision_id
                WHERE r.bundle_id IN ({','.join('?' for _ in PILOT_BUNDLE_IDS)})
                  AND p.tube_id IS NOT NULL""",
            PILOT_BUNDLE_IDS,
        ).fetchone()[0],
        "approved_revision_count": connection.execute(
            f"SELECT count(*) FROM tube_layout_revision WHERE bundle_id IN ({','.join('?' for _ in PILOT_BUNDLE_IDS)}) AND revision_status='APPROVED'",
            PILOT_BUNDLE_IDS,
        ).fetchone()[0],
    }
    connection.close()
    if after["existing_tube_count"] != before["existing_tube_count"]:
        raise RuntimeError("기존 튜브 마스터 건수가 변경되었습니다.")
    if after["existing_xy_count"] != before["existing_xy_count"]:
        raise RuntimeError("기존 튜브 position_x/y가 변경되었습니다.")
    return {
        "before": before,
        "after": after,
        "pilot": pilot,
        "inserted_revisions": inserted_revisions,
        "inserted_points": inserted_points,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply approved Tube Layout pilot staging records.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--migration", type=Path, required=True)
    parser.add_argument("--backup-file", type=Path)
    parser.add_argument("--expected-db-sha256")
    parser.add_argument("--approved-by", default="")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    validate_target(args.db, args.workspace)
    revisions, candidates = build_plan(args.review_dir)
    plan = {
        "pilot_bundle_ids": list(PILOT_BUNDLE_IDS),
        "revision_count": len(revisions),
        "unique_coordinate_count": len(candidates),
        "point_rows_to_stage": point_count(revisions, candidates),
        "existing_tube_links": sum(bool(row["existing_tube_id"]) for row in candidates),
        "new_tube_candidates_not_created": sum(not bool(row["existing_tube_id"]) for row in candidates),
        "database_apply": bool(args.apply),
    }
    if not args.apply:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.approved_by != REQUIRED_APPROVAL:
        raise RuntimeError(f"--approved-by 값은 '{REQUIRED_APPROVAL}'이어야 합니다.")
    if not args.backup_file or not args.backup_file.resolve().is_file():
        raise RuntimeError("검증 가능한 백업 파일이 필요합니다.")
    current_hash = sha256(args.db.resolve())
    backup_hash = sha256(args.backup_file.resolve())
    if not args.expected_db_sha256 or current_hash != args.expected_db_sha256:
        raise RuntimeError("현재 DB 해시가 승인 직전 해시와 다릅니다.")
    current_logical_hash = logical_sqlite_sha256(args.db.resolve())
    backup_logical_hash = logical_sqlite_sha256(args.backup_file.resolve())
    if backup_logical_hash != current_logical_hash:
        raise RuntimeError("백업 DB의 논리 데이터가 현재 DB와 다릅니다.")

    result = apply(
        args.db.resolve(), args.migration.resolve(), args.source_root.resolve(),
        revisions, candidates, args.approved_by,
    )
    result.update(plan)
    result.update({
        "database_apply": True,
        "approved_by": args.approved_by,
        "backup_file": str(args.backup_file.resolve()),
        "database_sha256_before": current_hash,
        "backup_sha256": backup_hash,
        "database_logical_sha256_before": current_logical_hash,
        "backup_logical_sha256": backup_logical_hash,
        "database_sha256_after": sha256(args.db.resolve()),
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    })
    report_path = args.review_dir.resolve() / "pilot_apply_result.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
