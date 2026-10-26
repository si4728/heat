"""G1-G7 thickness-trend data quality rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any


GATE_VERSION = "thickness-trend-g1-g7-1.0"
IDENTITY_FIELDS = ("plant_id", "unit_id", "heat_exchanger_id", "bundle_id", "bundle_lifecycle_no", "tube_id")


def _date(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _nominal(row: dict[str, Any]) -> float | None:
    explicit = _number(row.get("calculated_nominal_thickness_mm"))
    if explicit is not None:
        return explicit
    minimum, depth = _number(row.get("minimum_wall_thickness_mm")), _number(row.get("wall_loss_depth_mm"))
    return minimum + depth if minimum is not None and depth is not None else None


def evaluate_pair(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    if any(previous.get(field) != current.get(field) for field in IDENTITY_FIELDS):
        failures.append({"gate": "G1", "code": "TUBE_MAPPING_MISMATCH", "disposition": "DQ-BLOCK"})

    previous_date, current_date = _date(previous.get("inspection_date")), _date(current.get("inspection_date"))
    elapsed_years = None
    if previous_date is None or current_date is None or current_date <= previous_date:
        failures.append({"gate": "G2", "code": "INVALID_INSPECTION_DATE", "disposition": "DQ-BLOCK"})
    else:
        elapsed_years = (current_date - previous_date).total_seconds() / (365.2425 * 86400)

    previous_thickness = _number(previous.get("minimum_wall_thickness_mm"))
    current_thickness = _number(current.get("minimum_wall_thickness_mm"))
    if previous_thickness is None or current_thickness is None:
        failures.append({"gate": "G3", "code": "MISSING_THICKNESS", "disposition": "DQ-HOLD"})

    previous_nominal, current_nominal = _nominal(previous), _nominal(current)
    if previous_nominal is None or current_nominal is None:
        failures.append({"gate": "G4", "code": "MISSING_NOMINAL_BASIS", "disposition": "DQ-HOLD"})
    elif abs(current_nominal - previous_nominal) > max(0.05, previous_nominal * 0.02) + 1e-12:
        failures.append({"gate": "G4", "code": "NOMINAL_CHANGED", "disposition": "DQ-BLOCK"})

    for label, row, nominal in (("previous", previous, previous_nominal), ("current", current, current_nominal)):
        stored, depth = _number(row.get("wall_loss_percent")), _number(row.get("wall_loss_depth_mm"))
        if stored is None or depth is None or nominal in (None, 0):
            failures.append({"gate": "G5", "code": f"FORMULA_INPUT_MISSING_{label.upper()}", "disposition": "DQ-HOLD"})
        elif abs(stored - depth / nominal * 100.0) > 1.0 + 1e-12:
            failures.append({"gate": "G5", "code": "FORMULA_MISMATCH", "disposition": "DQ-BLOCK"})

    thickness_change = None
    wall_loss_change = None
    if previous_thickness is not None and current_thickness is not None:
        thickness_change = current_thickness - previous_thickness
    previous_loss, current_loss = _number(previous.get("wall_loss_percent")), _number(current.get("wall_loss_percent"))
    if previous_loss is not None and current_loss is not None:
        wall_loss_change = current_loss - previous_loss
    if thickness_change is not None and wall_loss_change is not None and thickness_change > 0 and wall_loss_change > 1.0 + 1e-12:
        failures.append({"gate": "G6", "code": "THICKNESS_WALLLOSS_CONFLICT", "disposition": "DQ-BLOCK"})

    if elapsed_years is not None and elapsed_years < 0.5:
        failures.append({"gate": "G7", "code": "SHORT_INTERVAL", "disposition": "DQ-HOLD"})

    disposition = "PASS"
    if any(item["disposition"] == "DQ-BLOCK" for item in failures):
        disposition = "DQ-BLOCK"
    elif failures:
        disposition = "DQ-HOLD"
    return {
        "passed": not failures,
        "disposition": disposition,
        "failed_gates": failures,
        "elapsed_years": elapsed_years,
        "thickness_change_mm": thickness_change,
        "wall_loss_change_pp": wall_loss_change,
        "gate_version": GATE_VERSION,
    }
