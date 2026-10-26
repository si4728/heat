from __future__ import annotations

import math
from typing import Any


ASME_CALCULATION_VERSION = "1.0.0"
SUPPORTED_COMPONENT_TYPES = {
    "CYLINDRICAL_SHELL",
    "SPHERICAL_SHELL",
    "ELLIPSOIDAL_HEAD_2_1",
    "HEMISPHERICAL_HEAD",
}


def calculate_asme_viii_internal_pressure(
    *,
    component_type: str,
    inside_diameter_mm: float,
    design_pressure_mpa: float,
    allowable_stress_mpa: float,
    joint_efficiency: float,
    actual_thickness_mm: float,
    static_head_mpa: float = 0.0,
    supplemental_thickness_mm: float = 0.0,
) -> dict[str, Any]:
    """ASME VIII-1 internal-pressure screening calculation.

    This supports standard geometries only. Material allowable stress and joint
    efficiency must come from an approved design basis; they are never inferred.
    """
    kind = str(component_type or "").strip().upper()
    if kind not in SUPPORTED_COMPONENT_TYPES:
        raise ValueError("지원 형상은 원통 Shell, 구형 Shell, 2:1 타원형 Head, 반구형 Head입니다.")
    values = {
        "inside_diameter_mm": inside_diameter_mm,
        "design_pressure_mpa": design_pressure_mpa,
        "allowable_stress_mpa": allowable_stress_mpa,
        "joint_efficiency": joint_efficiency,
        "actual_thickness_mm": actual_thickness_mm,
        "static_head_mpa": static_head_mpa,
        "supplemental_thickness_mm": supplemental_thickness_mm,
    }
    try:
        values = {key: float(value) for key, value in values.items()}
    except (TypeError, ValueError) as exc:
        raise ValueError("ASME VIII 계산 입력은 숫자여야 합니다.") from exc
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("ASME VIII 계산 입력은 유한한 숫자여야 합니다.")
    diameter = values["inside_diameter_mm"]
    design_pressure = values["design_pressure_mpa"]
    static_head = values["static_head_mpa"]
    pressure = design_pressure + static_head
    stress = values["allowable_stress_mpa"]
    efficiency = values["joint_efficiency"]
    actual = values["actual_thickness_mm"]
    supplemental = values["supplemental_thickness_mm"]
    if diameter <= 0 or design_pressure <= 0 or static_head < 0 or pressure <= 0 or stress <= 0 or actual <= 0:
        raise ValueError("직경·총압력·허용응력·실제두께는 0보다 커야 합니다.")
    if not 0 < efficiency <= 1:
        raise ValueError("용접효율은 0보다 크고 1 이하여야 합니다.")
    if supplemental < 0 or supplemental >= actual:
        raise ValueError("추가 필요두께는 0 이상이며 실제두께보다 작아야 합니다.")

    effective_actual = actual - supplemental
    if kind == "CYLINDRICAL_SHELL":
        radius = diameter / 2.0
        denominator = stress * efficiency - 0.6 * pressure
        if denominator <= 0:
            raise ValueError("원통 Shell 필요두께 식의 분모가 0 이하입니다.")
        pressure_thickness = pressure * radius / denominator
        mawp = stress * efficiency * effective_actual / (radius + 0.6 * effective_actual)
        formula_reference = "ASME VIII-1 UG-27(c)(1), inside-radius basis"
    elif kind == "SPHERICAL_SHELL":
        radius = diameter / 2.0
        denominator = 2.0 * stress * efficiency - 0.2 * pressure
        if denominator <= 0:
            raise ValueError("구형 Shell 필요두께 식의 분모가 0 이하입니다.")
        pressure_thickness = pressure * radius / denominator
        mawp = 2.0 * stress * efficiency * effective_actual / (radius + 0.2 * effective_actual)
        formula_reference = "ASME VIII-1 UG-27(d), inside-radius basis"
    elif kind == "ELLIPSOIDAL_HEAD_2_1":
        denominator = 2.0 * stress * efficiency - 0.2 * pressure
        if denominator <= 0:
            raise ValueError("2:1 타원형 Head 필요두께 식의 분모가 0 이하입니다.")
        pressure_thickness = pressure * diameter / denominator
        mawp = 2.0 * stress * efficiency * effective_actual / (diameter + 0.2 * effective_actual)
        formula_reference = "ASME VIII-1 UG-32(d), standard 2:1 ellipsoidal head"
    else:
        denominator = 4.0 * stress * efficiency - 0.4 * pressure
        if denominator <= 0:
            raise ValueError("반구형 Head 필요두께 식의 분모가 0 이하입니다.")
        pressure_thickness = pressure * diameter / denominator
        mawp = 4.0 * stress * efficiency * effective_actual / (diameter + 0.4 * effective_actual)
        formula_reference = "ASME VIII-1 UG-32(f), hemispherical head"

    required = pressure_thickness + supplemental
    return {
        "algorithm_version": ASME_CALCULATION_VERSION,
        "component_type": kind,
        "total_pressure_mpa": pressure,
        "pressure_required_thickness_mm": pressure_thickness,
        "supplemental_thickness_mm": supplemental,
        "required_thickness_mm": required,
        "effective_actual_thickness_mm": effective_actual,
        "mawp_mpa": mawp,
        "formula_reference": formula_reference,
        "status": "BELOW_REQUIRED" if actual <= required else "CALCULATED",
    }
