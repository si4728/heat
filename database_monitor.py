"""MariaDB lock-event monitoring with local append-only log files."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


_WRITE_LOCK = threading.Lock()
_LOCK_ERROR_MARKERS = ("deadlock found", "lock wait timeout", "(1213,", "(1205,")


def lock_event_path(db_path: str | Path) -> Path:
    path = Path(db_path).expanduser().resolve()
    return path.with_name(f"{path.name}.lock-events.jsonl")


def is_database_lock_error(error: BaseException | str) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in _LOCK_ERROR_MARKERS)


def record_database_lock(
    db_path: str | Path,
    error: BaseException | str,
    statement: str | None = None,
) -> None:
    """Append a redacted lock event without another database transaction."""
    operation = ""
    if statement:
        operation = statement.lstrip().split(None, 1)[0].upper()[:20]
    event = {
        "occurred_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "message": "MariaDB transaction lock conflict",
        "operation": operation,
        "process_id": os.getpid(),
    }
    path = lock_event_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK, path.open("a", encoding="utf-8") as event_file:
            event_file.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        # Monitoring must never hide or replace the original database error.
        return


def database_lock_summary(db_path: str | Path, *, limit: int = 100) -> dict[str, Any]:
    path = lock_event_path(db_path)
    events: list[dict[str, Any]] = []
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8") as event_file:
                for line in event_file:
                    try:
                        event = json.loads(line)
                        event["_occurred_at"] = datetime.fromisoformat(event["occurred_at"])
                        events.append(event)
                    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                        continue
        except OSError:
            events = []

    now = datetime.now().astimezone()
    one_day_ago = now - timedelta(days=1)
    seven_days_ago = now - timedelta(days=7)
    for event in events:
        if event["_occurred_at"].tzinfo is None:
            event["_occurred_at"] = event["_occurred_at"].replace(tzinfo=now.tzinfo)
    events.sort(key=lambda item: item["_occurred_at"], reverse=True)
    last_24_hours = sum(event["_occurred_at"] >= one_day_ago for event in events)
    last_7_days = sum(event["_occurred_at"] >= seven_days_ago for event in events)
    for event in events:
        event.pop("_occurred_at", None)
    return {
        "last_24_hours": last_24_hours,
        "last_7_days": last_7_days,
        "total": len(events),
        "latest_at": events[0]["occurred_at"] if events else None,
        "events": events[:limit],
        "log_path": str(path),
    }
