from __future__ import annotations

from typing import Any


TUBE_OPERATION_STATUSES = {
    "IN_SERVICE": "사용 중",
    "PLUGGED": "사용중지 (Plugged)",
}


def normalize_tube_status(value: Any) -> str:
    status = str(value or "IN_SERVICE").strip().upper()
    return "IN_SERVICE" if status in {"ACTIVE", "UNUSED"} else status

