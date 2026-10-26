"""Scheduled, auditable MariaDB backups for the local IRIS installation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any


BACKUP_SCHEMA_VERSION = 2
BUSINESS_TIMEZONE = timezone(timedelta(hours=9), "Asia/Seoul")
DEFAULT_SETTINGS = {
    "schema_version": BACKUP_SCHEMA_VERSION,
    "enabled": True,
    "frequency": "daily",
    "scheduled_time": "02:00",
    "weekday": 0,
    "retention_count": 30,
    "backup_content": ["mariadb_schemas"],
        "timezone": "Asia/Seoul",
}
WEEKDAY_LABELS = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")

_FILE_LOCK = threading.RLock()
_BACKUP_LOCK = threading.Lock()
_SCHEDULER_LOCK = threading.Lock()
_SCHEDULER_STARTED = False


def backup_paths(app_dir: str | Path) -> dict[str, Path]:
    root = Path(app_dir).expanduser().resolve() / "backups"
    return {
        "root": root,
        "settings": root / "config" / "backup_settings.json",
        "log": root / "logs" / "backup_log.jsonl",
        "files": root / "files",
    }


def _ensure_directories(app_dir: str | Path) -> dict[str, Path]:
    paths = backup_paths(app_dir)
    for key in ("settings", "log", "files"):
        target = paths[key].parent if key != "files" else paths[key]
        target.mkdir(parents=True, exist_ok=True)
    return paths


def _validate_settings(values: dict[str, Any]) -> dict[str, Any]:
    frequency = str(values.get("frequency", "daily")).strip().lower()
    if frequency not in {"daily", "weekly"}:
        raise ValueError("백업 주기는 매일 또는 매주만 선택할 수 있습니다.")
    scheduled_time = str(values.get("scheduled_time", "02:00")).strip()
    try:
        datetime.strptime(scheduled_time, "%H:%M")
    except ValueError as exc:
        raise ValueError("백업 실행시간은 HH:MM 형식이어야 합니다.") from exc
    try:
        weekday = int(values.get("weekday", 0))
        retention_count = int(values.get("retention_count", 30))
    except (TypeError, ValueError) as exc:
        raise ValueError("실행요일과 보관 개수는 숫자여야 합니다.") from exc
    if weekday not in range(7):
        raise ValueError("실행요일 값이 올바르지 않습니다.")
    if not 1 <= retention_count <= 365:
        raise ValueError("백업 보관 개수는 1~365 사이여야 합니다.")
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "enabled": values.get("enabled", False) is True or str(values.get("enabled", "")).strip().lower() in {"1", "true", "on", "yes"},
        "frequency": frequency,
        "scheduled_time": scheduled_time,
        "weekday": weekday,
        "retention_count": retention_count,
        "backup_content": ["mariadb_schemas"],
        "timezone": "Asia/Seoul",
    }


def load_backup_settings(app_dir: str | Path) -> dict[str, Any]:
    paths = _ensure_directories(app_dir)
    with _FILE_LOCK:
        if not paths["settings"].is_file():
            save_backup_settings(app_dir, DEFAULT_SETTINGS)
        try:
            values = json.loads(paths["settings"].read_text(encoding="utf-8"))
            return _validate_settings(values)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"백업 설정 파일을 읽을 수 없습니다: {exc}") from exc


def save_backup_settings(app_dir: str | Path, values: dict[str, Any]) -> dict[str, Any]:
    settings = _validate_settings(values)
    paths = _ensure_directories(app_dir)
    temporary = paths["settings"].with_suffix(".json.tmp")
    with _FILE_LOCK:
        temporary.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, paths["settings"])
    return settings


def _empty_log_record() -> dict[str, Any]:
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "event_id": "",
        "started_at": "",
        "completed_at": "",
        "trigger": "",
        "scheduled_for": None,
        "requested_by": None,
        "status": "",
        "source_database": "",
        "backup_file": None,
        "backup_content": ["mariadb_schemas"],
        "timezone": "Asia/Seoul",
        "file_size_bytes": 0,
        "sha256": None,
        "integrity_check": None,
        "removed_files": [],
        "error": None,
        "operation": "BACKUP",
        "reason": None,
        "pre_restore_file": None,
        "restored_schemas": None,
        "source_sha256": None,
        "restored_sha256": None,
        "foreign_key_issue_count": None,
        "rollback_performed": False,
    }


def _append_log(app_dir: str | Path, record: dict[str, Any]) -> None:
    paths = _ensure_directories(app_dir)
    normalized = _empty_log_record()
    normalized.update(record)
    with _FILE_LOCK, paths["log"].open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(normalized, ensure_ascii=False) + "\n")


def read_backup_log(app_dir: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    path = _ensure_directories(app_dir)["log"]
    records: list[dict[str, Any]] = []
    if path.is_file():
        with _FILE_LOCK:
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        normalized = _empty_log_record()
                        normalized.update(record)
                        records.append(normalized)
            except OSError:
                return []
    def started_timestamp(row):
        try:
            value=datetime.fromisoformat(row.get('started_at') or '')
            if value.tzinfo is None:value=value.replace(tzinfo=BUSINESS_TIMEZONE)
            return value.timestamp()
        except (ValueError,TypeError):return float('-inf')
    records.sort(key=started_timestamp,reverse=True)
    return records[:limit] if limit is not None else records


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for block in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class BackupBusy(RuntimeError):
    pass


@contextmanager
def _operation_lock(app_dir):
    if not _BACKUP_LOCK.acquire(blocking=False):
        raise BackupBusy("Another backup or restore is running")
    stream=None
    locked=False
    try:
        stream=(_ensure_directories(app_dir)['root']/'.operation.lock').open('a+b')
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:
            raise BackupBusy("Another backup or restore process is running") from None
        yield
    finally:
        if stream is not None:
            if locked:
                stream.seek(0)
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
            stream.close()
        _BACKUP_LOCK.release()


def _valid_backup_record(app_dir,record):
    if record.get('operation','BACKUP')!='BACKUP' or record.get('status') not in {'SUCCESS','SUCCESS_WITH_NOTE'}:return False
    try:
        path=Path(record.get('backup_file') or '').resolve()
        if path.parent!=backup_paths(app_dir)['files'].resolve() or not path.is_file() or path.stat().st_size==0:return False
        return bool(record.get('sha256')) and _sha256(path)==record['sha256']
    except OSError:return False


def run_database_backup(app_dir, db_path, *, trigger="manual", scheduled_for=None, requested_by=None):
    from .mariadb_operations import create_backup, configured_schema_roles
    with _operation_lock(app_dir):
        if trigger=="scheduled":
            latest=backup_schedule_status(app_dir)
            if not latest['due'] or latest['scheduled_for']!=scheduled_for:
                return {"status":"SKIPPED","operation":"BACKUP"}
        paths=_ensure_directories(app_dir)
        record=_empty_log_record()
        record.update(event_id=uuid.uuid4().hex,started_at=datetime.now(BUSINESS_TIMEZONE).isoformat(),trigger=trigger,
            scheduled_for=scheduled_for,requested_by=requested_by,source_database="MariaDB: "+", ".join(configured_schema_roles().values()))
        try:
            destination=paths['files']/('iris2_mariadb_'+datetime.now(BUSINESS_TIMEZONE).strftime('%Y%m%d_%H%M%S_%f')+'.zip')
            manifest=create_backup(destination)
            record.update(status='SUCCESS',backup_file=str(destination),file_size_bytes=destination.stat().st_size,sha256=_sha256(destination),integrity_check='manifest_with_data_baseline' if manifest.get('fingerprints') else 'manifest_source_changed')
            settings=load_backup_settings(app_dir)
            files=sorted(paths['files'].glob('iris2_mariadb_*.zip'),key=lambda path:path.stat().st_mtime,reverse=True)
            for old in files[settings['retention_count']:]:
                if old.resolve().parent!=paths['files'].resolve():raise ValueError('Invalid retention path')
                try:
                    old.unlink();record['removed_files'].append(str(old))
                except OSError:
                    record['status']='SUCCESS_WITH_NOTE'
                    record.setdefault('warnings',[]).append('RETENTION_DELETE_FAILED')
        except Exception:
            record.update(status='FAILED',error='MariaDB backup failed. Check database connectivity and available disk space.')
        record['completed_at']=datetime.now(BUSINESS_TIMEZONE).isoformat()
        _append_log(app_dir,record)
        return record


def run_database_restore(app_dir,db_path,backup_name,*,requested_by=None,reason=""):
    from .mariadb_operations import restore_to_isolated_schemas, verify_restored_backup, grant_restored_application_access
    if len(str(reason).strip())<5:raise ValueError('A restore reason of at least five characters is required')
    paths=_ensure_directories(app_dir)
    if Path(backup_name).name!=backup_name:raise ValueError('Invalid backup name')
    candidate=(paths['files']/backup_name).resolve()
    if candidate.parent!=paths['files'].resolve() or not candidate.is_file():raise ValueError('Backup not found')
    with _operation_lock(app_dir):
        record=_empty_log_record();record.update(event_id=uuid.uuid4().hex,operation='RESTORE_VALIDATION',reason=reason,
            requested_by=requested_by,started_at=datetime.now(BUSINESS_TIMEZONE).isoformat(),trigger='manual',backup_file=str(candidate))
        try:
            targets=restore_to_isolated_schemas(candidate,'_restore_'+datetime.now(BUSINESS_TIMEZONE).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
            verification=verify_restored_backup(candidate,targets)
            grant_restored_application_access(targets)
            full=all(value['mode']=='FULL_DATA_AND_DEFINITIONS' for value in verification.values())
            record.update(status='SUCCESS' if full else 'SUCCESS_WITH_NOTE',integrity_check='full_data_and_definitions' if full else 'structure_only',restored_schemas=targets,verification=verification,application_access_verified=True)
        except Exception:
            record.update(status='FAILED',error='Isolated restore failed. Check the private server log.')
        record['completed_at']=datetime.now(BUSINESS_TIMEZONE).isoformat();_append_log(app_dir,record)
        return record


def _scheduled_slot(settings: dict[str, Any], now: datetime) -> datetime:
    hour, minute = (int(part) for part in settings["scheduled_time"].split(":"))
    scheduled_time = datetime_time(hour, minute, tzinfo=now.tzinfo)
    if settings["frequency"] == "daily":
        slot = datetime.combine(now.date(), scheduled_time)
        return slot if slot <= now else slot - timedelta(days=1)
    days_since_target = (now.weekday() - settings["weekday"]) % 7
    slot = datetime.combine(now.date() - timedelta(days=days_since_target), scheduled_time)
    return slot if slot <= now else slot - timedelta(days=7)


def backup_schedule_status(app_dir: str | Path, now: datetime | None = None) -> dict[str, Any]:
    settings = load_backup_settings(app_dir)
    now = now or datetime.now(BUSINESS_TIMEZONE)
    now = now.replace(tzinfo=BUSINESS_TIMEZONE) if now.tzinfo is None else now.astimezone(BUSINESS_TIMEZONE)
    slot = _scheduled_slot(settings, now)
    records = read_backup_log(app_dir)
    successful_for_slot = []
    for row in records:
        if not _valid_backup_record(app_dir,row) or not row["started_at"]:
            continue
        try:
            started_at = datetime.fromisoformat(row["started_at"])
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=now.tzinfo)
        except (TypeError, ValueError):
            continue
        if started_at >= slot:
            successful_for_slot.append(row)
    scheduled_attempts = [
        row for row in records
        if row.get("operation","BACKUP")=="BACKUP" and row["trigger"] == "scheduled" and row["scheduled_for"] == slot.isoformat(timespec="seconds")
    ]
    period = timedelta(days=1 if settings["frequency"] == "daily" else 7)
    due = settings["enabled"] and not successful_for_slot
    next_run = slot if due else slot + period
    if due and scheduled_attempts:
        try:
            last_attempt_at = datetime.fromisoformat(
                scheduled_attempts[0]["completed_at"] or scheduled_attempts[0]["started_at"]
            )
            if last_attempt_at.tzinfo is None:
                last_attempt_at = last_attempt_at.replace(tzinfo=now.tzinfo)
            retry_at = last_attempt_at + timedelta(minutes=30)
            if retry_at > now:
                due = False
                next_run = retry_at
        except (TypeError, ValueError):
            pass
    return {
        "due": due,
        "scheduled_for": slot.isoformat(timespec="seconds"),
        "next_run": next_run.isoformat(timespec="seconds") if settings["enabled"] else None,
    }


def backup_management_data(
    app_dir: str | Path,
    db_path: str | Path,
    *,
    log_limit: int = 100,
) -> dict[str, Any]:
    paths = _ensure_directories(app_dir)
    settings = load_backup_settings(app_dir)
    records = read_backup_log(app_dir, limit=log_limit)
    successful = [row for row in records if _valid_backup_record(app_dir,row)]
    files = sorted(
        (
            {"path": str(path), "name": path.name, "size_bytes": path.stat().st_size,
             "modified_at": datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")}
            for path in paths["files"].glob("iris2_mariadb_*.zip") if path.is_file()
        ),
        key=lambda item: item["modified_at"],
        reverse=True,
    )
    from .mariadb_operations import configured_schema_roles
    return {
        "settings": settings,
        "schedule": backup_schedule_status(app_dir),
        "records": records,
        "last_success": successful[0] if successful else None,
        "files": files,
        "paths": {key: str(value) for key, value in paths.items()},
        "source_database": "MariaDB: "+", ".join(configured_schema_roles().values()),
        "source_size_bytes": _database_size(),
        "weekday_labels": WEEKDAY_LABELS,
        "scheduler": scheduler_status(app_dir),
    }


def run_due_backup(app_dir: str | Path, db_path: str | Path) -> dict[str, Any] | None:
    schedule = backup_schedule_status(app_dir)
    if not schedule["due"]:
        return None
    try:
        return run_database_backup(app_dir,db_path,trigger="scheduled",scheduled_for=schedule["scheduled_for"],requested_by="scheduler")
    except BackupBusy:
        return None


def start_backup_scheduler(
    app_dir: str | Path,
    db_path: str | Path,
    *,
    poll_seconds: int = 30,
) -> bool:
    global _SCHEDULER_STARTED
    with _SCHEDULER_LOCK:
        if _SCHEDULER_STARTED:
            return False
        _SCHEDULER_STARTED = True

    def scheduler_loop() -> None:
        while True:
            try:
                _write_scheduler_status(app_dir,poll_seconds,last_result="CHECKING")
                result=run_due_backup(app_dir, db_path)
                _write_scheduler_status(app_dir,poll_seconds,last_result=result.get('status') if result else None)
            except Exception:
                _write_scheduler_status(app_dir,poll_seconds,error="SCHEDULER_CHECK_FAILED")
            threading.Event().wait(max(5, poll_seconds))

    threading.Thread(
        target=scheduler_loop,
        name="iris-backup-scheduler",
        daemon=True,
    ).start()
    return True


def _database_size():
    from .database import get_engine
    from .mariadb_operations import configured_schema_roles
    names=tuple(configured_schema_roles().values())
    with get_engine().connect() as connection:
        sql="SELECT COALESCE(SUM(data_length+index_length),0) FROM information_schema.tables WHERE table_schema IN ("+",".join(['%s']*len(names))+")"
        return int(connection.exec_driver_sql(sql,names).scalar())



def _write_scheduler_status(app_dir,poll_seconds,*,error=None,last_result=None):
    path=backup_paths(app_dir)['root']/'scheduler_status.json'
    value={'pid':os.getpid(),'heartbeat_at':datetime.now(BUSINESS_TIMEZONE).isoformat(),'poll_seconds':poll_seconds,'timezone':'Asia/Seoul','error':error,'last_result':last_result,'requires_web_server':True}
    temporary=path.with_suffix('.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');temporary.replace(path)


def scheduler_status(app_dir):
    path=backup_paths(app_dir)['root']/'scheduler_status.json'
    try:
        value=json.loads(path.read_text(encoding='utf-8'))
        age=(datetime.now(BUSINESS_TIMEZONE)-datetime.fromisoformat(value['heartbeat_at'])).total_seconds()
        value['running']=0<=age<=max(600 if value.get('last_result')=='CHECKING' else 90,int(value['poll_seconds'])*3)
        return value
    except (OSError,KeyError,ValueError,TypeError):return {'running':False,'timezone':'Asia/Seoul','requires_web_server':True,'error':None}
