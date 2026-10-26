"""Canonical JSON 3.x mapping helpers shared by validation and import paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


DIRECTION_CODES = ("TOP", "BTM", "NORTH", "SOUTH", "EAST", "WEST", "FRONT", "REAR")
APPROVED_EQUIPMENT_ALIASES = {"AE-332": "E-332"}
ALLOWED_PERSONNEL_ROLES = {
    "examiner", "interpreter", "approver", "witnesser",
    "owner_customer_contact", "owner_customer", "prepared_by",
}


@dataclass(frozen=True)
class ReportIdentity:
    equipment_code: str
    bundle_code: str
    scope_code: str
    source_label: str
    directions: tuple[str, ...]


def report_details(report: dict[str, Any]) -> dict[str, Any]:
    return (
        report.get("iris_report_details")
        or report.get("iris_9000_report_details")
        or {}
    )


def source_equipment_label(report: dict[str, Any]) -> str:
    bundle = report.get("inspection_bundle") or {}
    scope = report.get("inspection_scope") or {}
    labels = report.get("source_equipment_labels") or []
    return str(
        bundle.get("source_equipment_label")
        or scope.get("source_equipment_label")
        or (labels[0] if labels else None)
        or report.get("equipment_id")
        or ""
    ).strip()


def _directions(scope_code: str) -> tuple[str, ...]:
    scope = scope_code.replace("BOTTOM", "BTM")
    return tuple(code for code in DIRECTION_CODES if code in scope)


def resolve_report_identity(report: dict[str, Any]) -> ReportIdentity:
    """Resolve Master equipment, physical bundle, inspection scope and source label."""
    raw = source_equipment_label(report)
    equipment_text = re.sub(
        r"\s+", " ", str(report.get("equipment_id") or "").strip().upper()
    )
    inferred_scope = ""
    direction_suffix = re.fullmatch(
        rf"(.+?)(?:\s*\+\s*|\s+)({'|'.join(DIRECTION_CODES)})", equipment_text
    )
    if direction_suffix:
        equipment_text = direction_suffix.group(1)
        inferred_scope = direction_suffix.group(2)
    equipment = re.sub(r"\s+", "", equipment_text)
    explicit_bundle = str(
        (report.get("inspection_bundle") or {}).get("bundle_code")
        or report.get("bundle_code")
        or ""
    ).strip().upper()
    explicit_scope = str(
        (report.get("inspection_scope") or {}).get("scope_code")
        or report.get("scope_code")
        or ""
    ).strip().upper().replace("BOTTOM", "BTM") or inferred_scope

    parenthetical = re.search(r"\(([^()]*)\)\s*$", equipment)
    if parenthetical:
        equipment = equipment[:parenthetical.start()]
        explicit_scope = explicit_scope or parenthetical.group(1).strip().upper()

    plus_scope = re.fullmatch(
        rf"(.+?)\+({'|'.join(DIRECTION_CODES)})",
        equipment,
    )
    if plus_scope:
        equipment = plus_scope.group(1)
        explicit_scope = explicit_scope or plus_scope.group(2)

    trailing_bundle = re.fullmatch(r"(.+-\d+[A-Z]?)-(1|2)", equipment)
    if trailing_bundle:
        equipment = trailing_bundle.group(1)
        explicit_bundle = explicit_bundle or trailing_bundle.group(2)

    equipment = APPROVED_EQUIPMENT_ALIASES.get(equipment, equipment)
    raw_core = re.sub(r"\([^()]*\)\s*$", "", re.sub(r"\s+", "", raw.upper()))
    raw_bundle = re.fullmatch(r"(.+-\d+[A-Z]?)-(1|2)", raw_core)
    if raw_bundle and (explicit_scope in {"", "1", "2"} or explicit_bundle):
        explicit_bundle = explicit_bundle or raw_bundle.group(2)
        explicit_scope = "ALL" if explicit_scope in {"", "1", "2"} else explicit_scope

    scope_code = explicit_scope or "ALL"
    return ReportIdentity(
        equipment_code=equipment,
        bundle_code=explicit_bundle or "MAIN",
        scope_code=scope_code,
        source_label=raw,
        directions=_directions(scope_code),
    )
