from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ..backup_manager import (
    backup_management_data as _backup_management_data,
    run_database_backup,
    run_database_restore,
    save_backup_settings as _save_backup_settings,
)
from ..database_monitor import database_lock_summary
from ..hx_configuration import APP_DIR, CUMULATIVE_REPORT, DB_PATH, REPORT_DIR
from ..iris_v2_database import create_v2_engine, session_scope, verify_v2_db
from ..iris_v2_importer import import_file
from ..iris_v2_models import Plant, ProcessUnit


def _normalize_master_code(value: Any, label: str) -> str:
    code = str(value or "").strip().upper()
    if not code:
        raise ValueError(f"{label}는 필수입니다.")
    if len(code) > 50 or not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", code):
        raise ValueError(f"{label}는 영문, 숫자, 하이픈(-), 밑줄(_)만 사용할 수 있습니다.")
    return code


def load_json(path: Path, dry_run: bool = False, plant_code: str | None = None,
              unit_code: str | None = None, *, importer=import_file) -> dict[str, Any]:
    selected_plant = _normalize_master_code(plant_code, "생산공장 코드")
    selected_unit = _normalize_master_code(unit_code, "생산라인 코드")
    if not re.fullmatch(r"P[1-9][0-9]*", selected_plant):
        raise ValueError("생산공장 코드는 P1, P2, P3 … 형식이어야 합니다.")
    with session_scope(DB_PATH) as session:
        plant = session.scalar(select(Plant).where(Plant.plant_code == selected_plant))
        if not plant:
            raise ValueError("등록된 생산공장을 선택해 주세요. 공장·생산라인에서 먼저 등록할 수 있습니다.")
        unit = session.scalar(select(ProcessUnit).where(
            ProcessUnit.plant_id == plant.plant_id,
            ProcessUnit.unit_code == selected_unit,
        ))
        if not unit:
            raise ValueError("선택한 생산공장에 등록된 생산라인을 선택해 주세요.")
    return importer(path, plant_code=selected_plant, unit_code=selected_unit,
                    dry_run=dry_run, report_dir=REPORT_DIR,
                    cumulative_path=CUMULATIVE_REPORT, db_path=DB_PATH)


def database_health() -> dict[str, Any]:
    return verify_v2_db(DB_PATH)


def database_monitor_data() -> dict[str, Any]:
    health = database_health()
    engine = create_v2_engine(DB_PATH)
    try:
        with engine.connect() as connection:
            database_name = connection.exec_driver_sql("SELECT DATABASE()").scalar()
            journal_mode = connection.exec_driver_sql("SELECT @@default_storage_engine").scalar()
            busy_timeout_ms = connection.exec_driver_sql("SELECT @@innodb_lock_wait_timeout * 1000").scalar()
    finally:
        engine.dispose()
    return {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "health": health,
        "journal_mode": str(journal_mode or "").upper(),
        "busy_timeout_ms": int(busy_timeout_ms or 0),
        "locks": database_lock_summary(DB_PATH),
        "database_connection": f"MariaDB · {engine.url.host}:{engine.url.port or 3306} / {database_name}",
    }


def backup_management_data() -> dict[str, Any]:
    return _backup_management_data(APP_DIR, DB_PATH)


def save_backup_schedule(data: dict[str, Any]) -> dict[str, Any]:
    return _save_backup_settings(APP_DIR, {
        "enabled": str(data.get("enabled") or "").lower() in {"1", "true", "on", "yes"},
        "frequency": data.get("frequency"),
        "scheduled_time": data.get("scheduled_time"),
        "weekday": data.get("weekday"),
        "retention_count": data.get("retention_count"),
    })


def run_backup_now(requested_by: str | None = None) -> dict[str, Any]:
    return run_database_backup(APP_DIR, DB_PATH, trigger="manual", requested_by=requested_by)


def restore_database(backup_name: str, reason: str, requested_by: str | None = None) -> dict[str, Any]:
    return run_database_restore(
        APP_DIR,
        DB_PATH,
        backup_name,
        requested_by=requested_by,
        reason=reason,
    )
