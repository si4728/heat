from __future__ import annotations

import re
from typing import Any


DIRECTIONS = (
    "TOP", "BTM", "BOTTOM", "NORTH", "SOUTH", "EAST", "WEST", "FRONT", "REAR",
)


def normalize_equipment_code(value: Any) -> tuple[str, str, list[str]]:
    """Split a Master equipment code from an optional inspection scope.

    Accepted scope forms include ``E-121A(TOP)``, ``E-121A TOP`` and the
    numbered section form ``E-332-1``.  The numbered form requires a complete
    equipment number before the final hyphen, so a normal code such as
    ``E-111`` is never shortened to ``E``.
    """
    text = re.sub(r"\s+", " ", str(value or "").strip().upper())
    base_text = text
    raw_scope = "ALL"

    parenthesized = re.fullmatch(r"([^()]+)(?:\(([^()]*)\))?", text)
    if parenthesized:
        base_text = parenthesized.group(1).strip()
        raw_scope = (parenthesized.group(2) or "ALL").strip()

    if raw_scope == "ALL":
        direction_suffix = re.fullmatch(
            rf"(.+?)\s+({'|'.join(DIRECTIONS)})", base_text
        )
        if direction_suffix:
            base_text = direction_suffix.group(1).strip()
            raw_scope = direction_suffix.group(2)
        else:
            numbered_suffix = re.fullmatch(r"(.+-\d+[A-Z]?)-(\d+)", base_text)
            if numbered_suffix:
                base_text = numbered_suffix.group(1)
                raw_scope = numbered_suffix.group(2)

    base = re.sub(r"\s+", "", base_text)
    raw_scope = re.sub(r"\s+", "", raw_scope).replace("BOTTOM", "BTM")
    if raw_scope == "ALL":
        return base, "ALL", []

    directions: list[str] = []
    remaining = raw_scope
    for direction in DIRECTIONS:
        canonical = "BTM" if direction == "BOTTOM" else direction
        if direction in remaining and canonical not in directions:
            directions.append(canonical)
            remaining = remaining.replace(direction, "")
    scope = "".join(directions) or raw_scope
    return base, scope, directions
