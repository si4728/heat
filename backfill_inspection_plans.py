"""Create completed inspection plans from dated IRIS inspection performance."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from iris2.inspection_plan_rules import (
    inspection_plan_application_date,
    inspection_plan_approval_date,
)
from iris2.iris_v2_database import init_v2_db


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR / "data" / "heat_exchanger_db3.db"


def parse_db_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_before_inspection_plan_backfill_{stamp}{db_path.suffix}"
    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("검사계획 반영 전 백업 DB 무결성 검사에 실패했습니다.")
    finally:
        destination.close()
        source.close()
    return backup_path


def load_candidates(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(connection.execute(
        """
        SELECT i.iris_inspection_id,
               i.heat_exchanger_id,
               i.report_date,
               COALESCE(i.inspection_method, 'IRIS') AS inspection_method,
               COALESCE(s.scope_code, 'ALL') AS scope_code
          FROM iris_inspection i
          LEFT JOIN inspection_scope s
            ON s.inspection_scope_id = i.inspection_scope_id
         WHERE i.report_date IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM inspection_plan_v2 p
                WHERE p.completed_inspection_id = i.iris_inspection_id
           )
         ORDER BY i.report_date, i.iris_inspection_id
        """
    ))


def backfill(db_path: Path, *, apply: bool, backup_dir: Path) -> dict:
    backup_path = create_backup(db_path, backup_dir) if apply else None
    if apply:
        init_v2_db(db_path)

    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("반영 전 DB 무결성 검사에 실패했습니다.")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(inspection_plan_v2)")}
        required_columns = {"application_date", "approval_date"}
        if not required_columns.issubset(columns):
            if apply:
                raise RuntimeError("검사계획 2.7.0 컬럼 생성에 실패했습니다.")
            candidate_count = connection.execute(
                "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NOT NULL"
            ).fetchone()[0]
            return {
                "mode": "DRY_RUN",
                "candidate_count": candidate_count,
                "missing_report_date_count": connection.execute(
                    "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NULL"
                ).fetchone()[0],
                "note": "Apply mode will migrate the schema to 2.7.0 before inserting plans.",
            }

        candidates = load_candidates(connection)
        connection.execute("BEGIN IMMEDIATE")
        inserted = 0
        for row in candidates:
            inspection_date = parse_db_datetime(row["report_date"])
            application_date = inspection_plan_application_date(inspection_date)
            approval_date = inspection_plan_approval_date(application_date)
            connection.execute(
                """
                INSERT INTO inspection_plan_v2 (
                    heat_exchanger_id, planned_date, application_date, approval_date,
                    inspection_method, scope_code, status, priority,
                    completed_inspection_id, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'COMPLETED', 'NORMAL', ?, ?, ?, ?)
                """,
                (
                    row["heat_exchanger_id"], inspection_date.isoformat(sep=" "),
                    application_date.isoformat(sep=" "), approval_date.isoformat(sep=" "),
                    row["inspection_method"], row["scope_code"], row["iris_inspection_id"],
                    "검사 실적 기반 자동 생성: 검사 3개월 전 평일 신청, 신청 후 7일 이내 평일 승인",
                    application_date.isoformat(sep=" "), inspection_date.isoformat(sep=" "),
                ),
            )
            inserted += 1

        invalid_weekdays = connection.execute(
            """
            SELECT COUNT(*) FROM inspection_plan_v2
             WHERE completed_inspection_id IS NOT NULL
               AND (strftime('%w', application_date) IN ('0','6')
                    OR strftime('%w', approval_date) IN ('0','6'))
            """
        ).fetchone()[0]
        approvals_over_seven_days = connection.execute(
            """
            SELECT COUNT(*) FROM inspection_plan_v2
             WHERE completed_inspection_id IS NOT NULL
               AND (julianday(approval_date) - julianday(application_date) NOT BETWEEN 0 AND 7)
            """
        ).fetchone()[0]
        duplicate_links = connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT completed_inspection_id
                  FROM inspection_plan_v2
                 WHERE completed_inspection_id IS NOT NULL
                 GROUP BY completed_inspection_id HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]
        fk_issues = len(list(connection.execute("PRAGMA foreign_key_check")))
        if invalid_weekdays or approvals_over_seven_days or duplicate_links or fk_issues:
            raise RuntimeError(
                "검사계획 검증 실패: "
                f"주말={invalid_weekdays}, 승인기한={approvals_over_seven_days}, "
                f"중복={duplicate_links}, FK={fk_issues}"
            )
        result = {
            "mode": "APPLY" if apply else "DRY_RUN",
            "inserted_count": inserted,
            "total_completed_plan_count": connection.execute(
                "SELECT COUNT(*) FROM inspection_plan_v2 WHERE completed_inspection_id IS NOT NULL"
            ).fetchone()[0],
            "missing_report_date_count": connection.execute(
                "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NULL"
            ).fetchone()[0],
            "weekday_violation_count": 0,
            "approval_over_seven_days_count": 0,
            "duplicate_completed_inspection_count": 0,
            "foreign_key_issue_count": 0,
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "backup_path": str(backup_path) if backup_path else None,
        }
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="검사 실적 기반 검사계획/승인 데이터 생성")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=APP_DIR / "backups")
    parser.add_argument("--apply", action="store_true", help="DB에 실제 반영; 기본은 dry-run")
    args = parser.parse_args()
    result = backfill(
        args.db.resolve(), apply=args.apply, backup_dir=args.backup_dir.resolve()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
