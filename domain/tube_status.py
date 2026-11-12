from __future__ import annotations

from typing import Any


TUBE_OPERATION_STATUSES = {
    "IN_SERVICE": "사용 중",
    "PLUGGED": "실제 Plugging 완료",
}


def normalize_tube_status(value: Any) -> str:
    status = str(value or "IN_SERVICE").strip().upper() or "IN_SERVICE"
    return "IN_SERVICE" if status in {"ACTIVE", "UNUSED"} else status

