"""Append-only monthly JSON Lines usage history, isolated within IRIS2."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import threading

from iris2.hx_configuration import APP_DIR

KST = timezone(timedelta(hours=9))
_WRITE_LOCK = threading.Lock()
SELECTION_KEYS = ('exchanger_id', 'exchanger_ids', 'unit_codes', 'inspection_id')


def _bounded(value, depth=0):
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, list) and depth < 3:
        return [_bounded(item, depth + 1) for item in value[:500]]
    if type(value) is float and not math.isfinite(value):
        return {'invalid_number': str(value)}
    if value is None or type(value) in (bool, int, float):
        return value
    return {'invalid_type': type(value).__name__}


def input_context(data):
    """Whitelist user input fields; never persist request tokens or credentials."""
    data = data if isinstance(data, dict) else {}

    return dict(question=_bounded(data.get('question')),
                selection={key: _bounded(data[key]) for key in SELECTION_KEYS if key in data})


def proposal_context(record, proposal):
    if not isinstance(proposal, dict):
        return
    sql = proposal.get('sql')
    if isinstance(sql, str):
        record['sql'] = sql[:12000]
        record['sql_truncated'] = len(sql) > 12000
    parameters = proposal.get('parameters')
    if isinstance(parameters, list):
        record['parameters'] = _bounded(parameters)


@contextmanager
def _exclusive_file(fd):
    # One byte at offset zero serializes writers without creating lock files.
    # Windows permits locking beyond EOF, including a new empty file.
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f'Unsupported usage log value: {type(value).__name__}')


def append_usage(record, *, directory=None, now=None):
    now = now or datetime.now(KST)
    if now.tzinfo is None:
        raise ValueError('Usage log timestamp must include a timezone')
    now = now.astimezone(KST)
    root = Path(directory or APP_DIR / 'logs' / 'text_to_sql').resolve()
    if not root.is_relative_to(APP_DIR.resolve()):
        raise ValueError('Text-to-SQL usage logs must remain within IRIS2')
    path = (root / f'text_to_sql_{now:%Y-%m}.txt').resolve()
    if not path.is_relative_to(root):
        raise ValueError('Invalid usage log path')
    payload = (json.dumps(dict(record, logged_at=now.isoformat(timespec='milliseconds')),
                          ensure_ascii=False, allow_nan=False, default=_json_value,
                          separators=(',', ':')) + '\n').encode('utf-8')
    with _WRITE_LOCK:
        root.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_APPEND | getattr(os, 'O_BINARY', 0), 0o600)
        try:
            with _exclusive_file(fd):
                original_size = os.fstat(fd).st_size
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(fd, remaining)
                        if written <= 0:
                            raise OSError('Usage log append failed')
                        remaining = remaining[written:]
                    os.fsync(fd)
                except OSError:
                    # Preserve prior complete records when an append fails midway.
                    try:
                        os.ftruncate(fd, original_size)
                    except OSError:
                        pass
                    raise
        finally:
            os.close(fd)
    return path
