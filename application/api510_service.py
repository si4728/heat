from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from sqlalchemy import select

from ..hx_configuration import API510_CODE_EDITION, DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import (
    Api510Calculation,
    HeatExchanger,
    PressureBoundaryComponent,
)
from ..life_prediction import calculate_api510_inspection_interval
from ..pressure_vessel_calculations import (
    ASME_CALCULATION_VERSION,
    SUPPORTED_COMPONENT_TYPES,
    calculate_asme_viii_internal_pressure,
)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        raise ValueError("계산 입력값은 단위와 분리된 유한한 숫자여야 합니다.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("계산 입력값은 단위와 분리된 유한한 숫자여야 합니다.") from exc
    if not math.isfinite(number):
        raise ValueError("계산 입력값은 단위와 분리된 유한한 숫자여야 합니다.")
    return number


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d")


def save_pressure_boundary_component(exchanger_id: int, data: dict[str, Any]) -> int:
    component_id = _int(data.get("pressure_component_id"))
    component_code = str(data.get("component_code") or "").strip().upper()
    component_type = str(data.get("component_type") or "").strip().upper()
    design_source = str(data.get("design_basis_source") or "").strip()
    code_edition = str(data.get("code_edition") or API510_CODE_EDITION).strip()
    if not component_code or component_type not in SUPPORTED_COMPONENT_TYPES:
        raise ValueError("부품코드와 지원되는 압력경계 형상은 필수입니다.")
    if not design_source:
        raise ValueError("승인된 설계근거 출처는 필수입니다.")
    required_numbers = {
        "inside_diameter_mm": _float(data.get("inside_diameter_mm")),
        "design_pressure_mpa": _float(data.get("design_pressure_mpa")),
        "allowable_stress_mpa": _float(data.get("allowable_stress_mpa")),
        "joint_efficiency": _float(data.get("joint_efficiency")),
    }
    if any(value is None for value in required_numbers.values()):
        raise ValueError("내경, 설계압력, 허용응력 및 용접효율은 필수입니다.")
    actual = _float(data.get("actual_thickness_mm"))
    actual_date = _date(data.get("actual_thickness_date"))
    thickness_source = str(data.get("thickness_source") or "").strip()
    if actual is not None and (actual_date is None or not thickness_source):
        raise ValueError("실제두께 입력 시 측정일과 두께 데이터 출처가 모두 필요합니다.")
    static_head = _float(data.get("static_head_mpa")) or 0.0
    supplemental = _float(data.get("supplemental_thickness_mm")) or 0.0
    validation_actual = actual if actual is not None else max(supplemental + 1.0, 1.0)
    calculate_asme_viii_internal_pressure(
        component_type=component_type,
        inside_diameter_mm=required_numbers["inside_diameter_mm"],
        design_pressure_mpa=required_numbers["design_pressure_mpa"],
        static_head_mpa=static_head,
        allowable_stress_mpa=required_numbers["allowable_stress_mpa"],
        joint_efficiency=required_numbers["joint_efficiency"],
        actual_thickness_mm=validation_actual,
        supplemental_thickness_mm=supplemental,
    )
    with session_scope(DB_PATH) as session:
        if not session.get(HeatExchanger, exchanger_id):
            raise ValueError("열교환기를 찾을 수 없습니다.")
        component = session.get(PressureBoundaryComponent, component_id) if component_id else None
        if component is None:
            component = PressureBoundaryComponent(
                heat_exchanger_id=exchanger_id,
                component_code=component_code,
                component_type=component_type,
                inside_diameter_mm=required_numbers["inside_diameter_mm"],
                design_pressure_mpa=required_numbers["design_pressure_mpa"],
                allowable_stress_mpa=required_numbers["allowable_stress_mpa"],
                joint_efficiency=required_numbers["joint_efficiency"],
                design_basis_source=design_source,
                code_edition=code_edition,
            )
            session.add(component)
        elif component.heat_exchanger_id != exchanger_id:
            raise ValueError("다른 열교환기의 압력경계 부품은 수정할 수 없습니다.")
        for key, value in required_numbers.items():
            setattr(component, key, value)
        component.component_code = component_code
        component.component_type = component_type
        component.side_code = str(data.get("side_code") or "SHELL").strip().upper()
        component.description = str(data.get("description") or "").strip() or None
        component.static_head_mpa = static_head
        component.design_temperature_c = _float(data.get("design_temperature_c"))
        component.material = str(data.get("material") or "").strip() or None
        component.supplemental_thickness_mm = supplemental
        component.original_corrosion_allowance_mm = _float(data.get("original_corrosion_allowance_mm"))
        component.actual_thickness_mm = actual
        component.actual_thickness_date = actual_date
        component.design_basis_source = design_source
        component.thickness_source = thickness_source or None
        component.code_edition = code_edition
        component.is_active = str(data.get("is_active") or "1").lower() not in {"0", "false", "off", "no"}
        session.flush()
        return component.pressure_component_id


def create_api510_calculation(component_id: int, data: dict[str, Any], actor: str | None = None) -> int:
    with session_scope(DB_PATH) as session:
        component = session.get(PressureBoundaryComponent, component_id)
        if not component or not component.is_active:
            raise ValueError("사용 가능한 압력경계 부품을 찾을 수 없습니다.")
        actual = _float(data.get("actual_thickness_mm"))
        if actual is None:
            actual = component.actual_thickness_mm
        last_date = _date(data.get("last_inspection_date")) or component.actual_thickness_date
        submitted_source = str(data.get("thickness_source") or "").strip()
        actual_is_override = (
            actual is not None
            and (
                component.actual_thickness_mm is None
                or not math.isclose(actual, component.actual_thickness_mm, rel_tol=0, abs_tol=1e-12)
            )
        )
        thickness_source = submitted_source or component.thickness_source
        if actual_is_override and not submitted_source:
            raise ValueError("실제두께를 변경해 계산할 때는 해당 두께 데이터 출처가 필요합니다.")
        short_rate = _float(data.get("short_term_corrosion_rate_mm_per_year"))
        long_rate = _float(data.get("long_term_corrosion_rate_mm_per_year"))
        selected_rate = _float(data.get("selected_corrosion_rate_mm_per_year"))
        if any(value is not None and value < 0 for value in (short_rate, long_rate)):
            raise ValueError("단기·장기 부식속도는 0 이상이어야 합니다.")
        if selected_rate is None:
            candidates = [value for value in (short_rate, long_rate) if value is not None and value > 0]
            selected_rate = max(candidates) if candidates else None
        selection_basis = str(data.get("corrosion_rate_selection_basis") or "").strip()
        if actual is None or last_date is None or selected_rate is None or selected_rate <= 0:
            raise ValueError("실제두께, 최근 검사일 및 양의 적용 부식속도는 필수입니다.")
        if not selection_basis:
            raise ValueError("적용 부식속도 선정 근거는 필수입니다.")
        asme = calculate_asme_viii_internal_pressure(
            component_type=component.component_type,
            inside_diameter_mm=component.inside_diameter_mm,
            design_pressure_mpa=component.design_pressure_mpa,
            static_head_mpa=component.static_head_mpa,
            allowable_stress_mpa=component.allowable_stress_mpa,
            joint_efficiency=component.joint_efficiency,
            actual_thickness_mm=actual,
            supplemental_thickness_mm=component.supplemental_thickness_mm,
        )
        api = calculate_api510_inspection_interval(
            actual_thickness_mm=actual,
            required_thickness_mm=asme["required_thickness_mm"],
            corrosion_rate_mm_per_year=selected_rate,
            last_inspection_date=last_date,
            inspection_type=data.get("inspection_type") or "INTERNAL_ON_STREAM",
        )
        inputs = {
            "component": {
                column: getattr(component, column)
                for column in (
                    "component_code", "component_type", "inside_diameter_mm",
                    "design_pressure_mpa", "static_head_mpa", "allowable_stress_mpa",
                    "joint_efficiency", "supplemental_thickness_mm",
                    "design_basis_source", "thickness_source", "code_edition",
                )
            },
            "actual_thickness_mm": actual,
            "actual_thickness_source": thickness_source,
            "short_term_corrosion_rate_mm_per_year": short_rate,
            "long_term_corrosion_rate_mm_per_year": long_rate,
            "selected_corrosion_rate_mm_per_year": selected_rate,
            "corrosion_rate_selection_basis": selection_basis,
            "last_inspection_date": last_date.isoformat(),
            "units": {
                "inside_diameter": "mm",
                "pressure_and_allowable_stress": "MPa",
                "thickness": "mm",
                "corrosion_rate": "mm/year",
                "dates": "ISO-8601 date",
            },
        }
        row = Api510Calculation(
            pressure_component_id=component_id,
            calculation_date=datetime.now(),
            inspection_type=api["inspection_type"],
            actual_thickness_mm=actual,
            required_thickness_mm=asme["required_thickness_mm"],
            remaining_corrosion_allowance_mm=api["remaining_corrosion_allowance_mm"],
            short_term_corrosion_rate_mm_per_year=short_rate,
            long_term_corrosion_rate_mm_per_year=long_rate,
            selected_corrosion_rate_mm_per_year=selected_rate,
            corrosion_rate_selection_basis=selection_basis,
            remaining_life_years=api["remaining_life_years"],
            mawp_mpa=asme["mawp_mpa"],
            inspection_interval_years=api["inspection_interval_years"],
            last_inspection_date=last_date,
            next_inspection_date=datetime.fromisoformat(api["next_inspection_date"]),
            status="DRAFT",
            algorithm_version=f"ASME-{ASME_CALCULATION_VERSION}/API510-1.0.0",
            code_edition=component.code_edition,
            input_snapshot_json=json.dumps(inputs, ensure_ascii=False, default=str),
            result_snapshot_json=json.dumps({"asme": asme, "api510": api}, ensure_ascii=False, default=str),
            created_by=actor,
        )
        session.add(row)
        session.flush()
        return row.api510_calculation_id


def transition_api510_calculation(
    calculation_id: int, status: str, reviewer: str | None, note: str | None = None
) -> bool:
    requested = str(status or "").strip().upper()
    transitions = {
        "DRAFT": {"SUBMITTED"},
        "SUBMITTED": {"APPROVED", "REJECTED"},
        "REJECTED": {"SUBMITTED"},
        "APPROVED": set(),
    }
    with session_scope(DB_PATH) as session:
        row = session.get(Api510Calculation, calculation_id)
        if not row:
            return False
        if requested not in transitions.get(row.status, set()):
            raise ValueError(f"{row.status} 상태에서 {requested}(으)로 변경할 수 없습니다.")
        now = datetime.now()
        row.status = requested
        if requested == "SUBMITTED":
            row.submitted_at = now
        else:
            if not reviewer:
                raise ValueError("승인 또는 반려 처리자는 필수입니다.")
            row.reviewed_by = reviewer
            row.reviewed_at = now
            row.review_note = str(note or "").strip() or None
        return True
