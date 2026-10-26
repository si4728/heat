from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median
from typing import Any

from sqlalchemy import Integer, and_, func, or_, select, text
from sqlalchemy.orm import joinedload

from .hx_configuration import (
    APP_DIR,
    DB_PATH,
    ML_REVIEW_DB_PATH,
    PDF_REPORT_DIR,
    REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS,
    REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT,
    REMAINING_LIFE_FORECAST_END_YEAR,
    REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT,
    API510_CODE_EDITION,
    DEGRADATION_POSITION_TOLERANCE_MM,
)
from .ml.inspection_priority import confirmed_hotspot_priorities
from .life_prediction import (
    calculate_api510_inspection_interval,
    calculate_tube_plugging_year,
    calculate_latest_installation_projection,
    remaining_life_as_of_date,
    summarize_remaining_life,
    summarize_corrosion_rates,
)
from .iris_v2_history import DEGRADATION_ALGORITHM_VERSION
from .iris_v2_database import init_v2_db, session_scope
from .iris_v2_importer import import_file
from .exchanger_type import TYPE_NAMES, standardize_exchanger_type
from .inspection_plan_rules import (
    inspection_plan_application_date,
    inspection_plan_approval_date,
)
from .iris_v2_models import (
    DEFAULT_SYSTEM_THEME_PRESETS,
    DEFAULT_WALL_LOSS_COLOR_SETTINGS,
    AppUser,
    Api510Calculation,
    DataQualityIssue,
    Equipment,
    EquipmentAlias,
    HeatExchanger,
    HeatExchangerManagementCriteria,
    HeatExchangerSpecRevision,
    HeatExchangerSideSpec,
    HeatExchangerTube,
    ImportBatch,
    InspectionCampaign,
    InspectionExecutionSnapshot,
    InspectionPersonnel,
    InspectionPlan,
    InspectionPlanEvent,
    InspectionPlanTubeTarget,
    InspectionProvider,
    InspectionScope,
    IrisInspection,
    IrisInspectionSpecSnapshot,
    IrisIndication,
    IrisRepresentativeAssessment,
    IrisSetupSnapshot,
    IrisTubeMap,
    IrisTubeResult,
    Plant,
    PressureBoundaryComponent,
    ProcessUnit,
    OrganizationCode,
    SourceDocument,
    SourceDocumentPage,
    SystemThemePreset,
    TubeBundle,
    TubeDegradationAssessment,
    TubeLifecycleEvent,
    TubeLayoutPoint,
    TubeLayoutRevision,
    TubeSheetGeometryRevision,
    TubePositionEvent,
    WallLossColorSetting,
)
from .pressure_vessel_calculations import (
    SUPPORTED_COMPONENT_TYPES,
)

from .application.api510_service import (
    create_api510_calculation,
    save_pressure_boundary_component,
    transition_api510_calculation,
)
from .application.auth_service import (
    SCREEN_DEFINITIONS,
    SCREEN_KEYS,
    authenticate_user,
    create_initial_admin,
    save_user,
    save_user_preferences,
    user_access_profile,
    user_can,
    user_count,
    users_management_data,
)
from .application.maintenance_service import (
    add_maintenance_record,
    maintenance_data,
    save_work_order,
    update_work_order,
    work_order_detail_data,
)
from .application.system_service import (
    backup_management_data,
    database_health,
    database_monitor_data,
    load_json as _load_json,
    restore_database,
    run_backup_now,
    save_backup_schedule,
)
from .domain.tube_status import TUBE_OPERATION_STATUSES, normalize_tube_status
from .domain.inspection_lifecycle import current_installation_date, is_current_installation_inspection


def load_json(path: Path, dry_run: bool = False, plant_code: str | None = None,
              unit_code: str | None = None) -> dict[str, Any]:
    """Compatibility facade preserving the existing import_file patch seam."""
    return _load_json(
        path,
        dry_run=dry_run,
        plant_code=plant_code,
        unit_code=unit_code,
        importer=import_file,
    )


HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def _tube_map_initial_rotation_degrees(orientation: str | None) -> int:
    """Convert the documented viewing direction into a clockwise screen rotation."""
    normalized = re.sub(r"[^A-Z]+", " ", (orientation or "").upper()).strip()
    tokens = set(normalized.split())
    for token, degrees in (("NORTH", 0), ("EAST", 90), ("SOUTH", 180), ("WEST", 270)):
        if token in tokens:
            return degrees
    if "REAR" in tokens or "BOTTOM" in tokens:
        return 180
    return 0


def _effective_inspection_date(inspection: IrisInspection) -> datetime | None:
    """Use the physical inspection date; report date is a documented fallback."""
    return inspection.inspection_date or inspection.report_date


def tube_layout_revision_management_data(
    status: str = "", equipment_search: str = "",
) -> dict[str, Any]:
    """Return the read-only review queue for source-backed layout revisions."""
    normalized_status = (status or "").strip().upper()
    allowed_statuses = {"DRAFT", "REVIEWED", "APPROVED", "REJECTED"}
    if normalized_status and normalized_status not in allowed_statuses:
        normalized_status = ""
    search_value = (equipment_search or "").strip()
    with session_scope(DB_PATH) as session:
        point_counts = (
            select(
                TubeLayoutPoint.layout_revision_id.label("revision_id"),
                func.count(TubeLayoutPoint.layout_point_id).label("point_count"),
                func.sum(TubeLayoutPoint.tube_id.is_not(None).cast(Integer)).label("linked_count"),
                func.sum((TubeLayoutPoint.verification_status == "VERIFIED").cast(Integer)).label("verified_count"),
                func.sum((TubeLayoutPoint.verification_status == "PENDING").cast(Integer)).label("pending_count"),
                func.sum((TubeLayoutPoint.verification_status == "REJECTED").cast(Integer)).label("rejected_count"),
            )
            .group_by(TubeLayoutPoint.layout_revision_id)
            .subquery()
        )
        statement = (
            select(
                TubeLayoutRevision, TubeBundle.bundle_code, Equipment.equipment_code,
                Equipment.equipment_tag,
                ProcessUnit.unit_code, point_counts.c.point_count,
                point_counts.c.linked_count, point_counts.c.verified_count,
                point_counts.c.pending_count, point_counts.c.rejected_count,
            )
            .join(TubeBundle, TubeBundle.bundle_id == TubeLayoutRevision.bundle_id)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == TubeBundle.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .outerjoin(point_counts, point_counts.c.revision_id == TubeLayoutRevision.layout_revision_id)
            .order_by(ProcessUnit.unit_code, Equipment.equipment_code, TubeLayoutRevision.layout_revision_id.desc())
        )
        if normalized_status:
            statement = statement.where(TubeLayoutRevision.revision_status == normalized_status)
        if search_value:
            statement = statement.where(or_(
                Equipment.equipment_code.ilike(f"%{search_value}%"),
                Equipment.equipment_tag.ilike(f"%{search_value}%"),
            ))
        rows = []
        for record in session.execute(statement):
            revision, bundle_code, equipment_code, equipment_tag, unit_code, point_count, linked_count, verified_count, pending_count, rejected_count = record
            rows.append({
                "revision": revision, "bundle_code": bundle_code,
                "equipment_code": equipment_code, "equipment_tag": equipment_tag,
                "unit_code": unit_code,
                "point_count": int(point_count or 0), "linked_count": int(linked_count or 0),
                "verified_count": int(verified_count or 0), "pending_count": int(pending_count or 0),
                "rejected_count": int(rejected_count or 0),
            })
        status_counts = dict(session.execute(
            select(TubeLayoutRevision.revision_status, func.count(TubeLayoutRevision.layout_revision_id))
            .group_by(TubeLayoutRevision.revision_status)
        ).all())
        return {
            "rows": rows, "status_counts": status_counts,
            "status_filter": normalized_status, "equipment_search": search_value,
            "allowed_statuses": sorted(allowed_statuses),
        }


def _wall_loss_color_map(session) -> dict[str, str]:
    defaults = {key: color for key, _label, color, _description, _order in DEFAULT_WALL_LOSS_COLOR_SETTINGS}
    rows = session.scalars(select(WallLossColorSetting)).all()
    for row in rows:
        if HEX_COLOR_PATTERN.fullmatch(row.current_color or ""):
            defaults[row.color_key] = row.current_color.lower()
    return defaults


def wall_loss_color_settings_data() -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        rows = session.scalars(
            select(WallLossColorSetting).order_by(WallLossColorSetting.display_order)
        ).all()
        return {
            "settings": [{
                "color_key": row.color_key,
                "label": row.label,
                "default_color": row.default_color.lower(),
                "current_color": row.current_color.lower(),
                "description": row.description,
                "is_default": row.current_color.lower() == row.default_color.lower(),
            } for row in rows],
            "colors": _wall_loss_color_map(session),
        }


def save_wall_loss_colors(data: dict[str, Any]) -> int:
    updated = 0
    with session_scope(DB_PATH) as session:
        rows = session.scalars(
            select(WallLossColorSetting).order_by(WallLossColorSetting.display_order)
        ).all()
        for row in rows:
            value = str(data.get(row.color_key, "")).strip()
            if not HEX_COLOR_PATTERN.fullmatch(value):
                raise ValueError(f"{row.label} 색상은 #RRGGBB 형식이어야 합니다.")
            normalized = value.lower()
            if row.current_color.lower() != normalized:
                row.current_color = normalized
                updated += 1
    return updated


def reset_wall_loss_colors() -> int:
    updated = 0
    with session_scope(DB_PATH) as session:
        rows = session.scalars(select(WallLossColorSetting)).all()
        for row in rows:
            if row.current_color.lower() != row.default_color.lower():
                row.current_color = row.default_color.lower()
                updated += 1
    return updated


def _theme_preset_dict(row: SystemThemePreset) -> dict[str, Any]:
    return {
        "preset_key": row.preset_key,
        "preset_name": row.preset_name,
        "default_background_color": row.default_background_color.lower(),
        "default_label_color": row.default_label_color.lower(),
        "background_color": row.background_color.lower(),
        "label_color": row.label_color.lower(),
        "is_active": bool(row.is_active),
        "is_system": bool(row.is_system),
    }


def active_theme_data() -> dict[str, Any]:
    fallback = DEFAULT_SYSTEM_THEME_PRESETS[0]
    with session_scope(DB_PATH) as session:
        row = session.scalars(
            select(SystemThemePreset)
            .where(SystemThemePreset.is_active.is_(True))
            .order_by(SystemThemePreset.display_order)
        ).first()
        if row and HEX_COLOR_PATTERN.fullmatch(row.background_color or "") and HEX_COLOR_PATTERN.fullmatch(row.label_color or ""):
            return _theme_preset_dict(row)
    return {
        "preset_key": fallback[0],
        "preset_name": fallback[1],
        "default_background_color": fallback[2],
        "default_label_color": fallback[3],
        "background_color": fallback[2],
        "label_color": fallback[3],
        "is_active": True,
        "is_system": True,
    }


def system_theme_settings_data() -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        rows = session.scalars(
            select(SystemThemePreset).order_by(SystemThemePreset.display_order)
        ).all()
        return {
            "theme_presets": [_theme_preset_dict(row) for row in rows],
            "active_theme": next(
                (_theme_preset_dict(row) for row in rows if row.is_active),
                _theme_preset_dict(rows[0]) if rows else active_theme_data(),
            ),
        }


def save_system_theme_settings(data: dict[str, Any]) -> int:
    active_key = str(data.get("active_preset", "")).strip().upper()
    updated = 0
    with session_scope(DB_PATH) as session:
        rows = session.scalars(
            select(SystemThemePreset).order_by(SystemThemePreset.display_order)
        ).all()
        known_keys = {row.preset_key for row in rows}
        if active_key not in known_keys:
            raise ValueError("적용할 화면 테마를 선택해 주세요.")
        for row in rows:
            background_color = str(data.get(f"background_color_{row.preset_key}", "")).strip()
            label_color = str(data.get(f"label_color_{row.preset_key}", "")).strip()
            if not HEX_COLOR_PATTERN.fullmatch(background_color):
                raise ValueError(f"{row.preset_name} 배경색은 #RRGGBB 형식이어야 합니다.")
            if not HEX_COLOR_PATTERN.fullmatch(label_color):
                raise ValueError(f"{row.preset_name} 라벨 글자색은 #RRGGBB 형식이어야 합니다.")
            background_color = background_color.lower()
            label_color = label_color.lower()
            is_active = row.preset_key == active_key
            if row.background_color.lower() != background_color:
                row.background_color = background_color
                updated += 1
            if row.label_color.lower() != label_color:
                row.label_color = label_color
                updated += 1
            if bool(row.is_active) != is_active:
                row.is_active = is_active
                updated += 1
    return updated


def reset_system_theme_settings() -> int:
    updated = 0
    with session_scope(DB_PATH) as session:
        rows = session.scalars(select(SystemThemePreset)).all()
        for row in rows:
            default_active = row.preset_key == "DARK"
            if row.background_color.lower() != row.default_background_color.lower():
                row.background_color = row.default_background_color.lower()
                updated += 1
            if row.label_color.lower() != row.default_label_color.lower():
                row.label_color = row.default_label_color.lower()
                updated += 1
            if bool(row.is_active) != default_active:
                row.is_active = default_active
                updated += 1
    return updated


def _estimated_circular_layout(
    tubes: list[dict[str, Any]],
    total_count: int,
    *,
    shape_code: str = "CIRCULAR",
    width_height_ratio: float | None = None,
) -> list[dict[str, Any]]:
    """Create an exact-count display layout while preserving measured tubes as managed records.

    Reports provide the total count but usually only sample tube coordinates. In that case a
    deterministic circular Vogel layout is used strictly for visualization. Known tube positions
    are mapped to the nearest available display slot; source row/column values remain in the item.
    """
    display_count = max(int(total_count or 0), len(tubes))
    if display_count == 0:
        return []
    if display_count == len(tubes) and all(
        tube.get("x") is not None and tube.get("y") is not None for tube in tubes
    ):
        return [dict(tube, source_x=tube.get("x"), source_y=tube.get("y"),
                     position_source="SOURCE", display_slot=index + 1, managed=True)
                for index, tube in enumerate(tubes)]
    normalized_shape = str(shape_code or "CIRCULAR").upper()
    ratio = float(width_height_ratio or 1.0)
    ratio = max(0.4, min(2.5, ratio))
    radius = max(math.sqrt(display_count) / 2.0, 1.0)
    slots: list[dict[str, float]] = []
    if normalized_shape in {"RECTANGULAR", "ROUNDED_RECTANGLE", "OBROUND"}:
        columns = max(1, math.ceil(math.sqrt(display_count * ratio)))
        rows = max(1, math.ceil(display_count / columns))
        candidates = [
            {"x": float(column - (columns - 1) / 2), "y": float(row - (rows - 1) / 2)}
            for row in range(rows)
            for column in range(columns)
        ]
        if normalized_shape == "RECTANGULAR":
            candidates.sort(key=lambda point: (point["y"], point["x"]))
        elif normalized_shape == "ROUNDED_RECTANGLE":
            half_x, half_y = max((columns - 1) / 2, 1), max((rows - 1) / 2, 1)
            candidates.sort(key=lambda point: (
                (abs(point["x"]) / half_x) ** 4 + (abs(point["y"]) / half_y) ** 4,
                point["y"], point["x"],
            ))
        else:
            half_y = max((rows - 1) / 2, 1)
            straight = max((columns - rows) / 2, 0)
            candidates.sort(key=lambda point: (
                math.hypot(max(abs(point["x"]) - straight, 0), point["y"]) / half_y,
                point["y"], point["x"],
            ))
        slots = candidates[:display_count]
        slots.sort(key=lambda point: (point["y"], point["x"]))
    else:
        golden_angle = math.pi * (3.0 - math.sqrt(5.0))
        x_scale = math.sqrt(ratio) if normalized_shape == "ELLIPTICAL" else 1.0
        y_scale = 1 / math.sqrt(ratio) if normalized_shape == "ELLIPTICAL" else 1.0
        for index in range(display_count):
            distance = radius * math.sqrt((index + 0.5) / display_count)
            angle = index * golden_angle
            slots.append({
                "x": distance * math.cos(angle) * x_scale,
                "y": distance * math.sin(angle) * y_scale,
            })

    available = set(range(display_count))
    known = []
    for index, tube in enumerate(tubes):
        x = tube.get("x")
        y = tube.get("y")
        known.append((index, float(x) if x is not None else float(index),
                      float(y) if y is not None else 0.0))
    if known:
        xs = [item[1] for item in known]
        ys = [item[2] for item in known]
        center_x = (min(xs) + max(xs)) / 2.0
        center_y = (min(ys) + max(ys)) / 2.0
        source_span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
        slot_span = max(
            max(slot["x"] for slot in slots) - min(slot["x"] for slot in slots),
            max(slot["y"] for slot in slots) - min(slot["y"] for slot in slots),
            1.0,
        )
        for tube_index, source_x, source_y in known:
            target_x = (source_x - center_x) / source_span * slot_span * .9
            target_y = (source_y - center_y) / source_span * slot_span * .9
            slot_index = min(available, key=lambda candidate: (
                (slots[candidate]["x"] - target_x) ** 2 +
                (slots[candidate]["y"] - target_y) ** 2
            ))
            available.remove(slot_index)
            item = dict(tubes[tube_index])
            item.update(
                source_x=item.get("x"), source_y=item.get("y"),
                x=slots[slot_index]["x"], y=slots[slot_index]["y"],
                position_source="ESTIMATED_FROM_REPORT_COORDINATE", display_slot=slot_index + 1,
                managed=True,
            )
            slots[slot_index]["tube"] = item

    for slot_index in sorted(available):
        slots[slot_index]["tube"] = {
            "tube_id": None, "tube_no": f"예상-{slot_index + 1:04d}",
            "row": None, "column": None, "source_x": None, "source_y": None,
            "x": slots[slot_index]["x"], "y": slots[slot_index]["y"], "z": 0,
            "coordinate_quality": "UNKNOWN", "coordinate_source": "ESTIMATED",
            "coordinate_is_verified": False,
            "lifecycle_no": None, "current_status": "UNKNOWN",
            "operational_status": "UNKNOWN", "inspection_status": "NOT_INSPECTED",
            "category": "NOT_INSPECTED", "inspected": False,
            "wall_loss_percent": None, "minimum_wall_thickness_mm": None,
            "wall_loss_depth_mm": None, "corrosion_type": None, "location_mm": None,
            "inspection_date": None, "scopes": [], "position_source": "ESTIMATED",
            "indication_count": 0, "measured_indication_count": 0, "indications": [],
            "display_slot": slot_index + 1, "managed": False,
        }
    return [slot["tube"] for slot in slots]


def initialize() -> None:
    init_v2_db(DB_PATH)


def plugging_unavailable_guide() -> str:
    guide_path = APP_DIR / "docs" / "PLUGGING_UNCALCULABLE_GUIDE_20260807.md"
    try:
        return guide_path.read_text(encoding="utf-8")
    except OSError:
        return "# Plugging 예상 산정 불가\n\n안내 문서를 불러올 수 없습니다. 관리자에게 문의해 주세요."


def find_pdf_report(year: int | str, unit_code: str) -> Path | None:
    """Resolve an approved year/unit report without accepting arbitrary paths."""
    year_text = str(year).strip()
    unit = str(unit_code).strip().upper()
    if not (year_text.isdigit() and len(year_text) == 4):
        return None
    if not re.fullmatch(r"[A-Z0-9_-]+", unit):
        return None
    candidate = (PDF_REPORT_DIR / f"{year_text}_1P_{unit}.pdf").resolve()
    if candidate.parent != PDF_REPORT_DIR.resolve() or not candidate.is_file():
        return None
    return candidate


def find_inspection_pdf(inspection_id: int) -> dict[str, Any] | None:
    """Return the report PDF and first mapped sheet page for an inspection."""
    with session_scope(DB_PATH) as session:
        row = session.execute(
            select(
                InspectionCampaign.campaign_year,
                ProcessUnit.unit_code,
                func.min(SourceDocumentPage.page_number),
            )
            .join(
                IrisInspection,
                IrisInspection.campaign_id == InspectionCampaign.campaign_id,
            )
            .join(ProcessUnit, ProcessUnit.unit_id == InspectionCampaign.unit_id)
            .outerjoin(
                SourceDocumentPage,
                SourceDocumentPage.iris_inspection_id
                == IrisInspection.iris_inspection_id,
            )
            .where(IrisInspection.iris_inspection_id == inspection_id)
            .group_by(InspectionCampaign.campaign_year, ProcessUnit.unit_code)
        ).first()
        if not row:
            return None
        report_path = find_pdf_report(row.campaign_year, row.unit_code)
        if not report_path:
            return None
        return {
            "path": report_path,
            "page": int(row[2]) if row[2] is not None else None,
        }


def _data_entry_group(label: str, rows: list[dict[str, Any]],
                      fields: tuple[str, ...], *, note: str = "",
                      total_count_override: int | None = None) -> dict[str, Any]:
    """Summarize populated field slots and fully populated records."""
    total_count = max(len(rows), int(total_count_override or 0))
    possible_count = total_count * len(fields)

    def populated(value: Any) -> bool:
        return value is not None and (not isinstance(value, str) or bool(value.strip()))

    populated_count = sum(
        populated(row.get(field)) for row in rows for field in fields
    )
    complete_count = sum(
        all(populated(row.get(field)) for field in fields) for row in rows
    )
    rate = round(populated_count * 100 / possible_count, 1) if possible_count else 0.0
    return {
        "label": label,
        "field_count": len(fields),
        "populated_count": populated_count,
        "possible_count": possible_count,
        "complete_count": complete_count,
        "total_count": total_count,
        "rate": rate,
        "note": note,
    }


def _same_position_reinspection_coverage(
    calculation_bases: list[str | None],
) -> dict[str, Any]:
    """Count adjacent-date comparisons with at least one matched measurement position."""
    matched_count = 0
    for raw_basis in calculation_bases:
        try:
            basis = json.loads(raw_basis or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            basis = {}
        position_checks = (
            basis.get("thickness_position_comparison") or {},
            basis.get("wall_loss_position_comparison") or {},
        )
        if any(check.get("matched") is True for check in position_checks):
            matched_count += 1
    total_count = len(calculation_bases)
    return {
        "label": "동일 위치 재검사",
        "field_count": 1,
        "populated_count": matched_count,
        "possible_count": total_count,
        "complete_count": matched_count,
        "total_count": total_count,
        "rate": round(matched_count * 100 / total_count, 1) if total_count else 0.0,
        "note": (
            "연속 검사일 비교쌍 중 방향 보정 후 측정 위치가 "
            f"{DEGRADATION_POSITION_TOLERANCE_MM:g}mm 이내인 비율"
        ),
    }


def _current_installation_result_ids():
    measured = func.date(func.coalesce(IrisInspection.inspection_date, IrisInspection.report_date))
    return (select(IrisTubeResult.iris_tube_result_id)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .join(HeatExchangerTube, HeatExchangerTube.tube_id == IrisTubeResult.tube_id)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == IrisInspection.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .where(measured.is_not(None),
                   or_(Equipment.install_date.is_(None), measured >= func.date(Equipment.install_date)),
                   or_(HeatExchangerTube.installed_at.is_(None), measured >= func.date(HeatExchangerTube.installed_at))))


def _dashboard_data_entry_coverage(session) -> dict[str, Any]:
    exchanger_rows = [dict(row) for row in session.execute(text("""
        WITH current_spec AS (
            SELECT *
              FROM heat_exchanger_spec_revision
             WHERE is_current = 1
        ),
        latest_bundle AS (
            SELECT tb.*
              FROM tube_bundle tb
             WHERE tb.bundle_id = (
                 SELECT candidate.bundle_id
                   FROM tube_bundle candidate
                  WHERE candidate.heat_exchanger_id = tb.heat_exchanger_id
                    AND candidate.bundle_code = 'MAIN'
                  ORDER BY candidate.lifecycle_no DESC, candidate.bundle_id DESC
                  LIMIT 1
             )
        ),
        side_values AS (
            SELECT spec_revision_id,
                   MAX(CASE WHEN side_code='HEAD' THEN fluid END) AS head_fluid,
                   MAX(CASE WHEN side_code='HEAD' THEN material END) AS head_material,
                   MAX(CASE WHEN gasket_material IS NOT NULL AND TRIM(gasket_material) <> '' THEN 1 ELSE 0 END) AS gasket_present,
                   MAX(CASE WHEN concentration_wt_percent IS NOT NULL THEN 1 ELSE 0 END) AS concentration_present,
                   MAX(CASE WHEN material_state IS NOT NULL AND TRIM(material_state) <> '' THEN 1 ELSE 0 END) AS material_state_present
              FROM heat_exchanger_side_spec
             GROUP BY spec_revision_id
        )
        SELECT hx.heat_exchanger_id,
               e.unit_id, u.unit_code, e.equipment_code, e.equipment_tag, e.equipment_name,
               e.status, e.manufacturing_date, e.install_date, e.commissioning_date,
               hx.service_name, hx.exchanger_type_code,
               cs.exchanger_code, cs.shell_material, sv.head_material, cs.tube_material,
               cs.tube_count, cs.tube_outer_diameter_mm,
               cs.tube_nominal_thickness_mm, cs.tube_length_mm,
               cs.tube_pitch_mm, cs.pass_count,
               cs.shell_fluid, sv.head_fluid, cs.tube_fluid,
               CASE WHEN sv.gasket_present = 1 THEN 1 END AS gasket_present,
               CASE WHEN sv.concentration_present = 1 THEN 1 END AS concentration_present,
               CASE WHEN sv.material_state_present = 1 THEN 1 END AS material_state_present,
               mc.minimum_wall_thickness_mm, mc.inspection_cycle_months
          FROM heat_exchanger hx
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
          LEFT JOIN current_spec cs ON cs.heat_exchanger_id = hx.heat_exchanger_id
          LEFT JOIN side_values sv ON sv.spec_revision_id = cs.spec_revision_id
          LEFT JOIN latest_bundle lb ON lb.heat_exchanger_id = hx.heat_exchanger_id
          LEFT JOIN heat_exchanger_management_criteria mc
                 ON mc.heat_exchanger_id = hx.heat_exchanger_id
         ORDER BY hx.heat_exchanger_id
    """)).mappings().all()]

    exchanger_groups = [
        _data_entry_group(
            "기본 식별·분류", exchanger_rows,
            ("unit_id", "equipment_code", "equipment_tag", "exchanger_code",
             "equipment_name", "service_name", "exchanger_type_code", "status"),
            note="공장·생산라인, 자산/설비/열교환기 식별정보",
        ),
        _data_entry_group(
            "주요 일자", exchanger_rows,
            ("manufacturing_date", "install_date", "commissioning_date"),
            note="설치일 기준: 제작일 -3일, 운전개시일 +0일",
        ),
        _data_entry_group(
            "Tube 핵심 사양", exchanger_rows,
            ("tube_count", "tube_outer_diameter_mm", "tube_nominal_thickness_mm",
             "tube_length_mm", "tube_pitch_mm", "pass_count"),
            note="수량, 외경, 공칭두께, 길이, Pitch, Pass",
        ),
        _data_entry_group(
            "유체·재질", exchanger_rows,
            ("shell_material", "head_material", "tube_material",
             "shell_fluid", "head_fluid", "tube_fluid"),
            note="Shell·Head·Tube 측별 유체와 재질",
        ),
        _data_entry_group(
            "조건부 필수", exchanger_rows,
            ("gasket_present", "concentration_present", "material_state_present"),
            note="Gasket·농도·유체 상태는 측별 값 중 1개 이상",
        ),
    ]
    exchanger_required_fields = tuple(
        field
        for fields in (
            ("unit_id", "equipment_code", "equipment_tag", "exchanger_code",
             "equipment_name", "service_name", "exchanger_type_code", "status"),
            ("manufacturing_date", "install_date", "commissioning_date"),
            ("tube_count", "tube_outer_diameter_mm", "tube_nominal_thickness_mm",
             "tube_length_mm", "tube_pitch_mm", "pass_count"),
            ("shell_material", "head_material", "tube_material",
             "shell_fluid", "head_fluid", "tube_fluid"),
            ("gasket_present", "concentration_present", "material_state_present"),
        )
        for field in fields
    )
    exchanger_summary = _data_entry_group(
        "열교환기 주요정보", exchanger_rows, exchanger_required_fields,
        note="등록·수정 화면 필수 항목과 설치일 파생 일자 기준",
    )
    exchanger_management = _data_entry_group(
        "관리 기준", exchanger_rows,
        ("minimum_wall_thickness_mm", "inspection_cycle_months"),
        note="최소허용두께와 검사 주기 기준",
    )

    tube_rows = [dict(row) for row in session.execute(text("""
        SELECT t.tube_id, t.tube_no, t.current_status,
               CASE WHEN t.pass_no > 0 THEN t.pass_no END AS valid_pass_no,
               CASE WHEN t.row_no <= 0 OR t.column_no <= 0 THEN 1 ELSE 0 END AS grid_needs_review,
               CASE WHEN t.installed_at > CURRENT_TIMESTAMP THEN 1 ELSE 0 END AS future_installation,
               CASE WHEN EXISTS (
                   SELECT 1 FROM iris_tube_result r JOIN iris_inspection i
                     ON i.iris_inspection_id=r.iris_inspection_id
                    WHERE r.tube_id=t.tube_id AND COALESCE(i.inspection_date,i.report_date)<t.installed_at
               ) THEN 1 ELSE 0 END AS inspection_before_installation,
               CASE WHEN EXISTS (
                   SELECT 1 FROM iris_tube_result r WHERE r.tube_id=t.tube_id
                     AND r.minimum_wall_thickness_mm<=0
               ) THEN 1 ELSE 0 END AS thickness_needs_review,
               CASE WHEN t.row_no IS NOT NULL AND t.column_no IS NOT NULL THEN 1 END AS grid_position_present,
               CASE WHEN t.position_x IS NOT NULL AND t.position_y IS NOT NULL
                          OR EXISTS (
                              SELECT 1
                                FROM tube_layout_point lp
                                JOIN tube_layout_revision lr
                                  ON lr.layout_revision_id = lp.layout_revision_id
                               WHERE lp.tube_id = t.tube_id
                                 AND lp.verification_status = 'VERIFIED'
                                 AND lr.revision_status = 'APPROVED'
                                 AND lp.source_x IS NOT NULL AND lp.source_y IS NOT NULL
                          )
                    THEN 1 END AS spatial_position_present,
               t.pass_no, t.installed_at,
               CASE WHEN EXISTS (
                   SELECT 1 FROM iris_tube_result r WHERE r.tube_id = t.tube_id AND r.result_status='VALID'
               ) THEN 1 END AS inspection_result_present,
               CASE WHEN EXISTS (
                   SELECT 1 FROM iris_tube_result r
                    WHERE r.tube_id = t.tube_id
                      AND r.minimum_wall_thickness_mm > 0 AND r.result_status='VALID'
               ) THEN 1 END AS measured_thickness_present
          FROM heat_exchanger_tube t
          JOIN tube_bundle b ON b.bundle_id=t.bundle_id
          JOIN heat_exchanger registered_hx ON registered_hx.heat_exchanger_id=b.heat_exchanger_id
         ORDER BY t.tube_id
    """)).mappings().all()]
    specified_exchanger_count = sum(row.get("tube_count") is not None for row in exchanger_rows)
    total_expected_tube_count = sum(
        max(int(row.get("tube_count") or 0), 0) for row in exchanger_rows
    )
    tube_population_count = max(total_expected_tube_count, len(tube_rows))
    unspecified_exchanger_count = len(exchanger_rows) - specified_exchanger_count
    tube_groups = [
        _data_entry_group(
            "Tube 식별·상태", tube_rows, ("tube_no", "current_status"),
            note="전체 Tube 수 대비 개별 등록된 Tube 번호와 현재 운전상태",
            total_count_override=tube_population_count,
        ),
        _data_entry_group(
            "행·열 좌표", tube_rows, ("grid_position_present",),
            note="row/column이 모두 등록된 Tube",
            total_count_override=tube_population_count,
        ),
        _data_entry_group(
            "2D·3D 위치", tube_rows, ("spatial_position_present",),
            note="직접 X/Y 또는 승인·검증 Layout 좌표가 등록된 Tube",
            total_count_override=tube_population_count,
        ),
        _data_entry_group(
            "설치일자", tube_rows, ("installed_at",),
            note="Tube lifecycle 설치일",
            total_count_override=tube_population_count,
        ),
        _data_entry_group(
            "검사이력 보유 Tube", tube_rows, ("inspection_result_present",),
            note="사양상 전체 Tube 수 대비 연도와 관계없이 검사결과가 1건 이상 연결된 Tube",
            total_count_override=tube_population_count,
        ),
        _data_entry_group(
            "최소두께 측정이력 보유 Tube", tube_rows, ("measured_thickness_present",),
            note="사양상 전체 Tube 수 대비 최소 잔존두께가 1건 이상 등록된 Tube",
            total_count_override=tube_population_count,
        ),
    ]
    comparison_bases = list(session.scalars(
        select(TubeDegradationAssessment.calculation_basis).where(
            TubeDegradationAssessment.algorithm_version
            == DEGRADATION_ALGORITHM_VERSION,
            TubeDegradationAssessment.current_result_id.in_(_current_installation_result_ids()),
            TubeDegradationAssessment.previous_result_id.in_(_current_installation_result_ids()),
            TubeDegradationAssessment.tube_id.in_(
                select(HeatExchangerTube.tube_id)
                .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
                .join(HeatExchanger, HeatExchanger.heat_exchanger_id == TubeBundle.heat_exchanger_id)
            ),
        )
    ).all())
    tube_groups.append(_same_position_reinspection_coverage(comparison_bases))
    tube_summary = _data_entry_group(
        "Tube 주요정보", tube_rows,
        ("tube_no", "current_status", "grid_position_present", "spatial_position_present"),
        note=(f"사양상 전체 Tube {tube_population_count:,}개 기준 · "
              f"Tube 수 확인 열교환기 {specified_exchanger_count:,}개 · "
              f"미확인 {unspecified_exchanger_count:,}개"),
        total_count_override=tube_population_count,
    )
    registered_coverage = _registered_tube_coverage(tube_rows)
    missing_tube_count = sorted(
        [row for row in exchanger_rows if row.get("tube_count") is None],
        key=lambda row: (row["unit_code"], row["equipment_code"]),
    )
    missing_by_unit: dict[str, int] = {}
    for row in missing_tube_count:
        missing_by_unit[row["unit_code"]] = missing_by_unit.get(row["unit_code"], 0) + 1
    return {
        "exchanger": exchanger_summary,
        "exchanger_groups": exchanger_groups,
        "exchanger_management": exchanger_management,
        "tube": tube_summary,
        "tube_groups": tube_groups,
        "registered_tube": registered_coverage,
        "registered_exchanger_count": len(exchanger_rows),
        "missing_tube_count_exchangers": missing_tube_count,
        "missing_tube_count_by_unit": missing_by_unit,
        "tube_population": {
            "total_count": tube_population_count,
            "registered_count": len(tube_rows),
            "specified_exchanger_count": specified_exchanger_count,
            "unspecified_exchanger_count": unspecified_exchanger_count,
        },
    }


def _registered_tube_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate registered-record completeness from specification population coverage."""
    definitions = [
        ("Tube 번호·상태", ("tube_no", "current_status"), "등록된 Tube 번호와 운전상태"),
        ("행·열 좌표", ("grid_position_present",), "행·열 모두 등록; 번호 체계의 정확성은 별도 확인"),
        ("2D·3D 위치", ("spatial_position_present",), "직접 X/Y 또는 Tube에 연결된 승인·검증 Layout 좌표"),
        ("설치일자", ("installed_at",), "등록 여부; 장비 설치일 대입 값과 실제 교체일은 구분 필요"),
        ("검사이력 보유", ("inspection_result_present",), "VALID 검사결과가 1건 이상 연결된 Tube"),
        ("최소두께 측정이력", ("measured_thickness_present",), "VALID 검사결과에 0보다 큰 최소잔여두께가 1건 이상 존재"),
    ]
    groups = [_data_entry_group(label, rows, fields, note=note) for label, fields, note in definitions]
    fields = tuple(field for _, names, _ in definitions for field in names)
    summary = _data_entry_group("등록 Tube 정보 완성도", rows, fields,
                                note="번호·상태·행열·위치·설치일·검사이력·최소두께의 7개 입력 항목 기준 (Tube별 Pass 제외)")
    summary["groups"] = groups
    summary["quality"] = {
        key: sum(bool(row.get(key)) for row in rows)
        for key in ("grid_needs_review", "future_installation", "thickness_needs_review")
    }
    summary["historical_only_tubes"] = sum(bool(row.get("inspection_before_installation")) for row in rows)
    return summary


def dashboard_data() -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        registered_exchangers = select(HeatExchanger.heat_exchanger_id)
        registered_inspections = select(IrisInspection.iris_inspection_id).where(
            IrisInspection.heat_exchanger_id.in_(registered_exchangers))
        registered_documents = select(IrisInspection.source_document_id).where(
            IrisInspection.heat_exchanger_id.in_(registered_exchangers))
        data_entry_coverage = _dashboard_data_entry_coverage(session)
        tube_population = data_entry_coverage["tube_population"]
        counts = {
            "exchangers": data_entry_coverage["registered_exchanger_count"],
            "exchangers_with_registered_tubes": session.scalar(text("""
                SELECT COUNT(DISTINCT b.heat_exchanger_id)
                  FROM tube_bundle b
                  JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
                  JOIN heat_exchanger hx ON hx.heat_exchanger_id=b.heat_exchanger_id
            """)) or 0,
            "exchangers_without_registered_tubes": session.scalar(text("""
                SELECT COUNT(1)
                  FROM heat_exchanger hx
                 WHERE NOT EXISTS (
                     SELECT 1
                       FROM tube_bundle b
                       JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
                      WHERE b.heat_exchanger_id=hx.heat_exchanger_id
                 )
            """)) or 0,
            "tube_specified_without_registered_tubes": session.scalar(text("""
                SELECT COUNT(1)
                  FROM heat_exchanger hx
                 WHERE EXISTS (
                     SELECT 1 FROM heat_exchanger_spec_revision s
                      WHERE s.heat_exchanger_id=hx.heat_exchanger_id
                        AND s.is_current=1
                        AND s.tube_count IS NOT NULL
                 )
                   AND NOT EXISTS (
                     SELECT 1
                       FROM tube_bundle b
                       JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
                      WHERE b.heat_exchanger_id=hx.heat_exchanger_id
                 )
            """)) or 0,
            "tube_unspecified_without_registered_tubes": session.scalar(text("""
                SELECT COUNT(1)
                  FROM heat_exchanger hx
                 WHERE NOT EXISTS (
                     SELECT 1 FROM heat_exchanger_spec_revision s
                      WHERE s.heat_exchanger_id=hx.heat_exchanger_id
                        AND s.is_current=1
                        AND s.tube_count IS NOT NULL
                 )
                   AND NOT EXISTS (
                     SELECT 1
                       FROM tube_bundle b
                       JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
                      WHERE b.heat_exchanger_id=hx.heat_exchanger_id
                 )
            """)) or 0,
            "inspections": session.scalar(select(func.count()).select_from(IrisInspection).where(
                IrisInspection.heat_exchanger_id.in_(registered_exchangers))) or 0,
            "tubes": tube_population["total_count"],
            "registered_tubes": tube_population["registered_count"],
            "tube_count_specified_exchangers": tube_population["specified_exchanger_count"],
            "tube_count_unspecified_exchangers": tube_population["unspecified_exchanger_count"],
            "results": session.scalar(select(func.count()).select_from(IrisTubeResult).where(
                IrisTubeResult.iris_inspection_id.in_(registered_inspections))) or 0,
            "open_issues": session.scalar(select(func.count()).select_from(DataQualityIssue).where(
                DataQualityIssue.status == "OPEN",
                DataQualityIssue.source_document_id.in_(registered_documents))) or 0,
            "never_inspected": session.scalar(select(func.count()).select_from(HeatExchanger).where(HeatExchanger.inspection_lifecycle_status == "NEVER_INSPECTED")) or 0,
            "planned": session.scalar(select(func.count()).select_from(InspectionPlan).where(
                InspectionPlan.heat_exchanger_id.in_(registered_exchangers),
                InspectionPlan.status.in_(["SCHEDULED", "APPROVED", "IN_PROGRESS"]))) or 0,
            "overdue_plans": session.scalar(select(func.count()).select_from(InspectionPlan).where(
                InspectionPlan.heat_exchanger_id.in_(registered_exchangers),
                InspectionPlan.planned_date < datetime.now(),
                InspectionPlan.status.in_(["SCHEDULED", "APPROVED", "IN_PROGRESS"]))) or 0,
        }
        units = session.execute(
            select(ProcessUnit.unit_code, func.count(HeatExchanger.heat_exchanger_id))
            .join(Equipment, Equipment.unit_id == ProcessUnit.unit_id)
            .join(HeatExchanger, HeatExchanger.equipment_id == Equipment.equipment_id)
            .group_by(ProcessUnit.unit_code).order_by(ProcessUnit.unit_code)
        ).all()
        yearly_query_rows = session.execute(
            select(
                ProcessUnit.unit_code,
                InspectionCampaign.campaign_year.label("inspection_year"),
                func.count(IrisInspection.iris_inspection_id).label("inspection_count"),
                func.count(func.distinct(IrisInspection.heat_exchanger_id)).label("exchanger_count"),
                func.coalesce(func.sum(IrisInspection.extracted_tube_result_count), 0).label("tube_result_count"),
            )
            .join(InspectionCampaign, InspectionCampaign.unit_id == ProcessUnit.unit_id)
            .join(IrisInspection, IrisInspection.campaign_id == InspectionCampaign.campaign_id)
            .where(IrisInspection.heat_exchanger_id.in_(registered_exchangers))
            .group_by(ProcessUnit.unit_code, InspectionCampaign.campaign_year)
            .order_by(InspectionCampaign.campaign_year.desc(), ProcessUnit.unit_code)
        ).all()
        yearly_rows = [
            (*row, find_pdf_report(row.inspection_year, row.unit_code) is not None)
            for row in yearly_query_rows
        ]
        recent = session.execute(
            select(IrisInspection, Equipment, InspectionScope)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == IrisInspection.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
            .order_by(IrisInspection.report_date.desc(), IrisInspection.iris_inspection_id.desc()).limit(10)
        ).all()
        batches = session.scalars(select(ImportBatch).order_by(ImportBatch.import_batch_id.desc()).limit(5)).all()
        upcoming_plans = session.execute(
            select(InspectionPlan, Equipment)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == InspectionPlan.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .where(InspectionPlan.status.in_(["SCHEDULED", "APPROVED", "IN_PROGRESS"]))
            .order_by(InspectionPlan.planned_date).limit(5)
        ).all()
        return {"counts": counts, "units": units, "yearly_rows": yearly_rows,
                "recent": recent, "batches": batches, "upcoming_plans": upcoming_plans,
                "data_entry_coverage": data_entry_coverage}


def list_exchangers(search: str = "", plant_code: str = "", unit_code: str = "",
                    status: str = "", criticality: str = "",
                    sort_by: str = "plant", sort_dir: str = "asc",
                    team_code: str = "", process_code: str = "") -> dict[str, Any]:
    sort_by = str(sort_by or "plant").strip().lower()
    sort_dir = str(sort_dir or "asc").strip().lower()
    sort_columns = {
        "plant": (Plant.plant_code, ProcessUnit.unit_code, Equipment.equipment_code),
        "unit": (ProcessUnit.unit_code, Plant.plant_code, Equipment.equipment_code),
        "equipment": (Equipment.equipment_code, Plant.plant_code, ProcessUnit.unit_code),
    }
    if sort_by not in sort_columns:
        sort_by = "plant"
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "asc"
    primary_order = getattr(sort_columns[sort_by][0], sort_dir)()
    tie_breakers = [column.asc() for column in sort_columns[sort_by][1:]]

    with session_scope(DB_PATH) as session:
        stmt = (
            select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .outerjoin(
                HeatExchangerSpecRevision,
                and_(
                    HeatExchangerSpecRevision.heat_exchanger_id
                    == HeatExchanger.heat_exchanger_id,
                    HeatExchangerSpecRevision.is_current.is_(True),
                ),
            )
            .order_by(primary_order, *tie_breakers)
        )
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(or_(
                ProcessUnit.unit_code.ilike(term),
                Equipment.equipment_code.ilike(term),
                HeatExchangerSpecRevision.exchanger_code.ilike(term),
                Equipment.equipment_name.ilike(term),
            ))
        if unit_code:
            stmt = stmt.where(ProcessUnit.unit_code == unit_code)
        if plant_code:
            stmt = stmt.where(Plant.plant_code == plant_code)
        if team_code:
            stmt = stmt.where(Equipment.production_team_code == team_code)
        if process_code:
            stmt = stmt.where(Equipment.process_code == process_code)
        if status:
            stmt = stmt.where(HeatExchanger.inspection_lifecycle_status == status)
        if criticality == "CRITICAL":
            stmt = stmt.where(Equipment.is_critical.is_(True))
        elif criticality == "NORMAL":
            stmt = stmt.where(Equipment.is_critical.is_(False))
        rows = session.execute(stmt).all()
        inspection_counts = dict(session.execute(
            select(IrisInspection.heat_exchanger_id, func.count(IrisInspection.iris_inspection_id))
            .group_by(IrisInspection.heat_exchanger_id)
        ).all())
        inspection_pdf_links: dict[int, dict[str, int | None]] = {}
        pdf_candidates = session.execute(
            select(
                IrisInspection.heat_exchanger_id,
                IrisInspection.iris_inspection_id,
                InspectionCampaign.campaign_year,
                ProcessUnit.unit_code,
                func.min(SourceDocumentPage.page_number).label("first_page"),
            )
            .join(
                InspectionCampaign,
                InspectionCampaign.campaign_id == IrisInspection.campaign_id,
            )
            .join(ProcessUnit, ProcessUnit.unit_id == InspectionCampaign.unit_id)
            .outerjoin(
                SourceDocumentPage,
                SourceDocumentPage.iris_inspection_id
                == IrisInspection.iris_inspection_id,
            )
            .where(
                IrisInspection.heat_exchanger_id.in_(
                    [row[0].heat_exchanger_id for row in rows]
                )
            )
            .group_by(
                IrisInspection.heat_exchanger_id,
                IrisInspection.iris_inspection_id,
                InspectionCampaign.campaign_year,
                ProcessUnit.unit_code,
                IrisInspection.inspection_date,
                IrisInspection.report_date,
            )
            .order_by(
                func.coalesce(
                    IrisInspection.inspection_date, IrisInspection.report_date
                ).desc(),
                IrisInspection.iris_inspection_id.desc(),
            )
        ).all()
        for candidate in pdf_candidates:
            exchanger_id = candidate.heat_exchanger_id
            if exchanger_id in inspection_pdf_links:
                continue
            if find_pdf_report(candidate.campaign_year, candidate.unit_code):
                inspection_pdf_links[exchanger_id] = {
                    "inspection_id": candidate.iris_inspection_id,
                    "page": (
                        int(candidate.first_page)
                        if candidate.first_page is not None else None
                    ),
                }
        units = session.scalars(select(ProcessUnit.unit_code).distinct().order_by(ProcessUnit.unit_code)).all()
        plants = session.scalars(select(Plant.plant_code).order_by(Plant.plant_code)).all()
        exchanger_codes = dict(session.execute(
            select(
                HeatExchangerSpecRevision.heat_exchanger_id,
                HeatExchangerSpecRevision.exchanger_code,
            ).where(HeatExchangerSpecRevision.is_current.is_(True))
        ).all())
        return {
            "rows": rows, "inspection_counts": inspection_counts,
            "inspection_pdf_links": inspection_pdf_links,
            "units": units, "plants": plants,
            "exchanger_codes": exchanger_codes,
            "sort_by": sort_by, "sort_dir": sort_dir,
        }


def exchanger_wall_loss_ranking(
    search: str = "", plant_code: str = "", unit_code: str = "",
) -> dict[str, Any]:
    """Rank exchangers by their highest valid Tube wall-loss result."""
    search = str(search or "").strip()
    plant_code = str(plant_code or "").strip()
    unit_code = str(unit_code or "").strip()
    with session_scope(DB_PATH) as session:
        rows = [dict(row) for row in session.execute(text("""
            WITH current_spec AS (
                SELECT heat_exchanger_id, exchanger_code
                  FROM heat_exchanger_spec_revision
                 WHERE is_current=1
            ),
            ranked_result AS (
                SELECT i.heat_exchanger_id,
                       i.iris_inspection_id,
                       i.report_number,
                       COALESCE(i.inspection_date, i.report_date) AS inspection_date,
                       r.iris_tube_result_id,
                       r.tube_id,
                       t.tube_no,
                       r.wall_loss_percent,
                       r.minimum_wall_thickness_mm,
                       ROW_NUMBER() OVER (
                           PARTITION BY i.heat_exchanger_id
                           ORDER BY r.wall_loss_percent DESC,
                                    COALESCE(i.inspection_date, i.report_date) DESC,
                                    r.iris_tube_result_id DESC
                       ) AS ranking_no
                  FROM iris_tube_result r
                  JOIN iris_inspection i
                    ON i.iris_inspection_id=r.iris_inspection_id
                  JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id
                  JOIN heat_exchanger lifecycle_hx ON lifecycle_hx.heat_exchanger_id=i.heat_exchanger_id
                  JOIN equipment lifecycle_e ON lifecycle_e.equipment_id=lifecycle_hx.equipment_id
                 WHERE r.wall_loss_percent IS NOT NULL
                   AND r.result_status='VALID'
                   AND r.quality_status='VALID'
                   AND (lifecycle_e.install_date IS NULL OR DATE(COALESCE(i.inspection_date,i.report_date))>=DATE(lifecycle_e.install_date))
                   AND (t.installed_at IS NULL OR DATE(COALESCE(i.inspection_date,i.report_date))>=DATE(t.installed_at))
            ),
            measurement_count AS (
                SELECT i.heat_exchanger_id,
                       COUNT(1) AS result_count,
                       COUNT(DISTINCT r.tube_id) AS measured_tube_count
                  FROM iris_tube_result r
                  JOIN iris_inspection i
                    ON i.iris_inspection_id=r.iris_inspection_id
                  JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id
                  JOIN heat_exchanger lifecycle_hx ON lifecycle_hx.heat_exchanger_id=i.heat_exchanger_id
                  JOIN equipment lifecycle_e ON lifecycle_e.equipment_id=lifecycle_hx.equipment_id
                 WHERE r.wall_loss_percent IS NOT NULL
                   AND r.result_status='VALID'
                   AND r.quality_status='VALID'
                   AND (lifecycle_e.install_date IS NULL OR DATE(COALESCE(i.inspection_date,i.report_date))>=DATE(lifecycle_e.install_date))
                   AND (t.installed_at IS NULL OR DATE(COALESCE(i.inspection_date,i.report_date))>=DATE(t.installed_at))
                 GROUP BY i.heat_exchanger_id
            )
            SELECT hx.heat_exchanger_id,
                   p.plant_code, u.unit_code,
                   e.equipment_code, e.equipment_name,
                   cs.exchanger_code,
                   rr.tube_id, rr.tube_no, rr.wall_loss_percent,
                   rr.minimum_wall_thickness_mm,
                   rr.inspection_date, rr.iris_inspection_id, rr.report_number,
                   COALESCE(mc.result_count, 0) AS result_count,
                   COALESCE(mc.measured_tube_count, 0) AS measured_tube_count,
                   COALESCE(criteria.warning_wall_loss_percent, 20.0) AS warning_threshold,
                   COALESCE(criteria.critical_wall_loss_percent, 40.0) AS critical_threshold,
                   CASE
                     WHEN rr.wall_loss_percent IS NULL THEN 'NO_DATA'
                     WHEN rr.wall_loss_percent >= COALESCE(criteria.critical_wall_loss_percent, 40.0)
                       THEN 'CRITICAL'
                     WHEN rr.wall_loss_percent >= COALESCE(criteria.warning_wall_loss_percent, 20.0)
                       THEN 'WARNING'
                     ELSE 'NORMAL'
                   END AS wall_loss_status
              FROM heat_exchanger hx
              JOIN equipment e ON e.equipment_id=hx.equipment_id
              JOIN process_unit u ON u.unit_id=e.unit_id
              JOIN plant p ON p.plant_id=u.plant_id
              LEFT JOIN current_spec cs ON cs.heat_exchanger_id=hx.heat_exchanger_id
              LEFT JOIN ranked_result rr
                ON rr.heat_exchanger_id=hx.heat_exchanger_id
               AND rr.ranking_no=1
              LEFT JOIN measurement_count mc
                ON mc.heat_exchanger_id=hx.heat_exchanger_id
              LEFT JOIN heat_exchanger_management_criteria criteria
                ON criteria.heat_exchanger_id=hx.heat_exchanger_id
             WHERE (:search='' OR e.equipment_code LIKE :search_like
                    OR e.equipment_name LIKE :search_like
                    OR COALESCE(cs.exchanger_code, '') LIKE :search_like
                    OR COALESCE(rr.tube_no, '') LIKE :search_like)
               AND (:plant_code='' OR p.plant_code=:plant_code)
               AND (:unit_code='' OR u.unit_code=:unit_code)
             ORDER BY CASE WHEN rr.wall_loss_percent IS NULL THEN 1 ELSE 0 END,
                      rr.wall_loss_percent DESC,
                      p.plant_code, u.unit_code, e.equipment_code
        """), {
            "search": search,
            "search_like": f"%{search}%",
            "plant_code": plant_code,
            "unit_code": unit_code,
        }).mappings().all()]
        status_counts = {
            key: sum(row["wall_loss_status"] == key for row in rows)
            for key in ("CRITICAL", "WARNING", "NORMAL", "NO_DATA")
        }
        return {
            "rows": rows,
            "status_counts": status_counts,
            "search": search,
            "plant_code": plant_code,
            "unit_code": unit_code,
            "plants": list(session.scalars(
                select(Plant.plant_code).order_by(Plant.plant_code)
            ).all()),
            "units": list(session.scalars(
                select(ProcessUnit.unit_code).distinct().order_by(ProcessUnit.unit_code)
            ).all()),
        }


def precision_analysis_data(
    exchanger_id: int | None = None,
    *,
    unit_code: str = "",
    search: str = "",
    corrosion_rate_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Compose the approved 2D map and remaining-life data for one analysis screen."""
    corrosion_rate_multiplier = float(corrosion_rate_multiplier)
    if not 0.1 <= corrosion_rate_multiplier <= 2.0:
        corrosion_rate_multiplier = 1.0
    ranking = exchanger_wall_loss_ranking(search=search, unit_code=unit_code)
    analysis_rows = [row for row in ranking["rows"] if row.get("iris_inspection_id")]
    available_ids = {int(row["heat_exchanger_id"]) for row in analysis_rows}
    selected_id = int(exchanger_id) if exchanger_id in available_ids else (
        int(analysis_rows[0]["heat_exchanger_id"]) if analysis_rows else None
    )
    detail = exchanger_detail(selected_id) if selected_id is not None else None
    if detail and corrosion_rate_multiplier != 1.0:
        detail = exchanger_detail(
            selected_id,
            simulation_allowable_plugging_percent=detail["remaining_life"]["limit_percent"],
            simulation_corrosion_rate_multiplier=corrosion_rate_multiplier,
        )
        detail["remaining_life"] = detail["remaining_life_simulation"]
    tube_map = tube_map_data(selected_id) if selected_id is not None else None
    return {
        "analysis_rows": analysis_rows,
        "selected_exchanger_id": selected_id,
        "selected_detail": detail,
        "tube_map": tube_map,
        "units": ranking["units"],
        "unit_code": str(unit_code or ""),
        "search": str(search or ""),
        "corrosion_rate_multiplier": corrosion_rate_multiplier,
    }


def _resolve_tube_length(session, exchanger_id: int,
                         campaign_id: int | None = None) -> dict[str, Any]:
    def valid_length(value: Any) -> float | None:
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    master_specs = session.scalars(
        select(HeatExchangerSpecRevision)
        .where(HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id)
        .order_by(HeatExchangerSpecRevision.is_current.desc(),
                  HeatExchangerSpecRevision.revision_no.desc())
    ).all()
    master_length = next((
        valid_length(spec.tube_length_mm) for spec in master_specs
        if valid_length(spec.tube_length_mm) is not None
    ), None)
    if master_length is not None:
        return {"length_mm": master_length, "source": "MASTER",
                "source_label": "기본 사양", "is_estimated": False,
                "sample_count": 1}

    snapshot_rows = session.execute(
        select(IrisInspectionSpecSnapshot, IrisInspection.campaign_id)
        .join(IrisInspection,
              IrisInspection.iris_inspection_id == IrisInspectionSpecSnapshot.iris_inspection_id)
        .where(IrisInspection.heat_exchanger_id == exchanger_id)
        .order_by(IrisInspection.report_date.desc(), IrisInspection.iris_inspection_id.desc())
    ).all()

    def snapshot_length(snapshot: IrisInspectionSpecSnapshot) -> float | None:
        return next((value for value in (
            valid_length(snapshot.report_tube_length_mm),
            valid_length(snapshot.summary_length_mm),
        ) if value is not None), None)

    if campaign_id is not None:
        campaign_lengths = [
            length for snapshot, row_campaign_id in snapshot_rows
            if row_campaign_id == campaign_id
            for length in [snapshot_length(snapshot)] if length is not None
        ]
        if campaign_lengths:
            return {"length_mm": round(mean(campaign_lengths), 2),
                    "source": "INSPECTION_SNAPSHOT",
                    "source_label": "선택 검사 보고서", "is_estimated": False,
                    "sample_count": len(campaign_lengths)}
    elif snapshot_rows:
        latest_length = next((
            length for snapshot, _campaign_id in snapshot_rows
            for length in [snapshot_length(snapshot)] if length is not None
        ), None)
        if latest_length is not None:
            return {"length_mm": latest_length, "source": "INSPECTION_SNAPSHOT",
                    "source_label": "최근 검사 보고서", "is_estimated": False,
                    "sample_count": 1}

    exchanger_lengths = [
        length for snapshot, _campaign_id in snapshot_rows
        for length in [snapshot_length(snapshot)] if length is not None
    ]
    if exchanger_lengths:
        return {"length_mm": round(mean(exchanger_lengths), 2),
                "source": "EXCHANGER_AVERAGE",
                "source_label": "해당 열교환기 평균", "is_estimated": True,
                "sample_count": len(exchanger_lengths)}

    master_by_exchanger: dict[int, float] = {}
    for other_exchanger_id, length, is_current, revision_no in session.execute(
        select(HeatExchangerSpecRevision.heat_exchanger_id,
               HeatExchangerSpecRevision.tube_length_mm,
               HeatExchangerSpecRevision.is_current,
               HeatExchangerSpecRevision.revision_no)
        .where(HeatExchangerSpecRevision.tube_length_mm > 0)
        .order_by(HeatExchangerSpecRevision.heat_exchanger_id,
                  HeatExchangerSpecRevision.is_current.desc(),
                  HeatExchangerSpecRevision.revision_no.desc())
    ):
        normalized = valid_length(length)
        if normalized is not None:
            master_by_exchanger.setdefault(other_exchanger_id, normalized)

    snapshot_averages = dict(session.execute(
        select(
            IrisInspection.heat_exchanger_id,
            func.avg(func.coalesce(
                IrisInspectionSpecSnapshot.report_tube_length_mm,
                IrisInspectionSpecSnapshot.summary_length_mm,
            )),
        )
        .join(IrisInspectionSpecSnapshot,
              IrisInspectionSpecSnapshot.iris_inspection_id == IrisInspection.iris_inspection_id)
        .where(func.coalesce(
            IrisInspectionSpecSnapshot.report_tube_length_mm,
            IrisInspectionSpecSnapshot.summary_length_mm,
        ) > 0)
        .group_by(IrisInspection.heat_exchanger_id)
    ).all())
    representative_lengths = [
        master_by_exchanger.get(other_exchanger_id, valid_length(average))
        for other_exchanger_id, average in snapshot_averages.items()
    ]
    representative_lengths.extend(
        length for other_exchanger_id, length in master_by_exchanger.items()
        if other_exchanger_id not in snapshot_averages
    )
    representative_lengths = [value for value in representative_lengths if value is not None]
    if representative_lengths:
        return {"length_mm": round(mean(representative_lengths), 2),
                "source": "GLOBAL_AVERAGE",
                "source_label": "전체 열교환기 평균", "is_estimated": True,
                "sample_count": len(representative_lengths)}
    return {"length_mm": None, "source": "UNREGISTERED",
            "source_label": "길이 정보 없음", "is_estimated": True,
            "sample_count": 0}


def exchanger_detail(exchanger_id: int, *, simulation_allowable_plugging_percent: float | None = None,
                     simulation_corrosion_rate_multiplier: float = 1.0,
                     simulation_plugging_wall_loss_percent: float | None = None,
                     simulation_forecast_end_year: int | None = None) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        row = session.execute(
            select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .where(HeatExchanger.heat_exchanger_id == exchanger_id)
        ).first()
        if not row:
            return None
        bundles = session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id == exchanger_id)).all()
        scopes = session.scalars(select(InspectionScope).where(InspectionScope.heat_exchanger_id == exchanger_id).order_by(InspectionScope.scope_code)).all()
        inspections = session.execute(
            select(IrisInspection, InspectionScope)
            .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
            .where(IrisInspection.heat_exchanger_id == exchanger_id)
            .order_by(IrisInspection.report_date.desc(), IrisInspection.report_sequence)
        ).all()
        inspection_ids = [item.iris_inspection_id for item, _scope in inspections]
        inspection_setups = {
            item.iris_inspection_id: item for item in session.scalars(
                select(IrisSetupSnapshot).where(
                    IrisSetupSnapshot.iris_inspection_id.in_(inspection_ids)
                )
            )
        } if inspection_ids else {}
        inspection_executions = {
            item.iris_inspection_id: item for item in session.scalars(
                select(InspectionExecutionSnapshot).where(
                    InspectionExecutionSnapshot.iris_inspection_id.in_(inspection_ids)
                )
            )
        } if inspection_ids else {}
        provider_ids = {
            item.inspection_provider_id for item in inspection_executions.values()
            if item.inspection_provider_id is not None
        }
        inspection_providers = {
            item.inspection_provider_id: item for item in session.scalars(
                select(InspectionProvider).where(
                    InspectionProvider.inspection_provider_id.in_(provider_ids)
                )
            )
        } if provider_ids else {}
        tube_count = session.scalar(
            select(func.count()).select_from(HeatExchangerTube)
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .where(TubeBundle.heat_exchanger_id == exchanger_id)
        ) or 0
        spec = session.scalar(select(HeatExchangerSpecRevision).where(
            HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id,
            HeatExchangerSpecRevision.is_current.is_(True),
        ).order_by(HeatExchangerSpecRevision.revision_no.desc()).limit(1))
        spec_summary = session.execute(text("""
            SELECT * FROM v_heat_exchanger_spec_summary
             WHERE heat_exchanger_id=:exchanger_id AND is_current=1
        """), {"exchanger_id": exchanger_id}).mappings().first()
        criteria = session.scalar(select(HeatExchangerManagementCriteria).where(
            HeatExchangerManagementCriteria.heat_exchanger_id == exchanger_id
        ))
        remaining_life = _remaining_life_projection(
            session, exchanger_id, row[1], bundles, criteria,
            forecast_end_year=simulation_forecast_end_year,
        )
        tube_side_spec = session.scalar(
            select(HeatExchangerSideSpec)
            .join(
                HeatExchangerSpecRevision,
                HeatExchangerSpecRevision.spec_revision_id == HeatExchangerSideSpec.spec_revision_id,
            )
            .where(
                HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id,
                HeatExchangerSpecRevision.is_current.is_(True),
                HeatExchangerSideSpec.side_code == "TUBE",
            )
            .order_by(HeatExchangerSpecRevision.revision_no.desc())
            .limit(1)
        )
        api510_defaults = {
            "actual_thickness_mm": remaining_life["equipment_summary"].get(
                "minimum_actual_thickness_mm"
            ),
            "actual_thickness_source": "최근 IRIS 결과의 최소 잔존두께",
            "required_thickness_mm": (
                float(tube_side_spec.calculated_thickness_mm)
                if tube_side_spec and tube_side_spec.calculated_thickness_mm is not None
                else None
            ),
            "required_thickness_source": "현재 TUBE 측 사양의 계산두께(엔지니어 확인 필요)",
            "corrosion_rate_mm_per_year": remaining_life["equipment_summary"].get(
                "representative_corrosion_rate_mm_per_year"
            ),
            "corrosion_rate_source": "튜브별 양의 부식속도 중앙값",
            "last_inspection_date": remaining_life["equipment_summary"].get(
                "latest_inspection_date"
            ),
            "code_edition": API510_CODE_EDITION,
        }
        remaining_life_simulation = None
        if simulation_allowable_plugging_percent is not None:
            remaining_life_simulation = _remaining_life_projection(
                session,
                exchanger_id,
                row[1],
                bundles,
                criteria,
                allowable_plugging_percent=simulation_allowable_plugging_percent,
                corrosion_rate_multiplier=simulation_corrosion_rate_multiplier,
                plugging_wall_loss_percent=simulation_plugging_wall_loss_percent,
                forecast_end_year=simulation_forecast_end_year,
            )
        return {"master": row, "bundles": bundles, "scopes": scopes,
                "inspections": inspections, "tube_count": tube_count,
                "inspection_setups": inspection_setups,
                "inspection_executions": inspection_executions,
                "inspection_providers": inspection_providers,
                "spec": spec, "spec_summary": spec_summary,
                "criteria": criteria, "remaining_life": remaining_life,
                "remaining_life_simulation": remaining_life_simulation,
                "api510_defaults": api510_defaults,
                "tube_length_resolution": _resolve_tube_length(session, exchanger_id)}


def _remaining_life_projection(session, exchanger_id: int, equipment: Equipment,
                               bundles: list[TubeBundle],
                               criteria: HeatExchangerManagementCriteria | None,
                               as_of_date: date | None = None,
                               allowable_plugging_percent: float | None = None,
                               corrosion_rate_multiplier: float = 1.0,
                               plugging_wall_loss_percent: float | None = None,
                               forecast_end_year: int | None = None) -> dict[str, Any]:
    if allowable_plugging_percent is not None:
        allowable_plugging_percent = float(allowable_plugging_percent)
        if allowable_plugging_percent not in REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS:
            raise ValueError("시뮬레이션 허용 Plugging 한도는 1%부터 20%까지 선택할 수 있습니다.")
    corrosion_rate_multiplier = float(corrosion_rate_multiplier)
    if not 0.1 <= corrosion_rate_multiplier <= 3.0:
        raise ValueError("시뮬레이션 부식속도 배율은 10%에서 300% 사이여야 합니다.")
    plugging_wall_loss_percent = float(
        (criteria.critical_wall_loss_percent
         if criteria and criteria.critical_wall_loss_percent is not None
         else REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT)
        if plugging_wall_loss_percent is None else plugging_wall_loss_percent
    )
    if not 0 < plugging_wall_loss_percent <= 100:
        raise ValueError("Plugging 판정 감육률은 0%보다 크고 100% 이하여야 합니다.")
    as_of_date = as_of_date or remaining_life_as_of_date()
    current_year = as_of_date.year
    active_bundles = [bundle for bundle in bundles if bundle.retired_at is None] or bundles
    bundle_ids = [bundle.bundle_id for bundle in active_bundles]
    tubes = session.scalars(
        select(HeatExchangerTube)
        .where(HeatExchangerTube.bundle_id.in_(bundle_ids))
        .order_by(HeatExchangerTube.tube_no)
    ).all() if bundle_ids else []
    tube_ids = [tube.tube_id for tube in tubes]
    expected_count = max(
        [bundle.expected_tube_count or 0 for bundle in active_bundles] + [len(tubes)]
    )

    latest_results: dict[int, tuple[IrisTubeResult, IrisInspection]] = {}
    tubes_by_id = {tube.tube_id: tube for tube in tubes}
    historical_result_count = 0
    if tube_ids:
        result_rows = session.execute(
            select(IrisTubeResult, IrisInspection)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .where(
                IrisTubeResult.tube_id.in_(tube_ids),
                or_(IrisTubeResult.quality_status.is_(None),
                    IrisTubeResult.quality_status != "NOT_IN_LATEST_JSON"),
                or_(
                    IrisInspection.inspection_date.is_not(None),
                    IrisInspection.report_date.is_not(None),
                ),
            )
            .order_by(
                func.coalesce(IrisInspection.inspection_date, IrisInspection.report_date).desc(),
                IrisTubeResult.iris_tube_result_id.desc(),
            )
        ).all()
        for result, inspection in result_rows:
            if not is_current_installation_inspection(
                _effective_inspection_date(inspection), equipment.install_date,
                tubes_by_id[result.tube_id].installed_at,
            ):
                historical_result_count += 1
                continue
            existing = latest_results.get(result.tube_id)
            if existing is None:
                latest_results[result.tube_id] = (result, inspection)
            elif _effective_inspection_date(inspection) == _effective_inspection_date(existing[1]):
                old_loss = existing[0].wall_loss_percent
                new_loss = result.wall_loss_percent
                if new_loss is not None and (old_loss is None or new_loss > old_loss):
                    latest_results[result.tube_id] = (result, inspection)

    # This forecast uses the current measurement and installation age;
    # previous-result assessments remain available in the inspection history.
    rate_profiles: dict[int, dict[str, Any]] = {}

    snapshots = {}
    inspection_ids = [inspection.iris_inspection_id for _result, inspection in latest_results.values()]
    if inspection_ids:
        snapshots = {
            snapshot.iris_inspection_id: snapshot
            for snapshot in session.scalars(
                select(IrisInspectionSpecSnapshot)
                .where(IrisInspectionSpecSnapshot.iris_inspection_id.in_(inspection_ids))
            )
        }
    master_spec = session.scalar(
        select(HeatExchangerSpecRevision)
        .where(HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id)
        .order_by(HeatExchangerSpecRevision.is_current.desc(),
                  HeatExchangerSpecRevision.revision_no.desc())
    )
    latest_inspection = max(
        (inspection for _result, inspection in latest_results.values()),
        key=lambda inspection: _effective_inspection_date(inspection),
        default=None,
    )
    latest_snapshot = (
        snapshots.get(latest_inspection.iris_inspection_id)
        if latest_inspection is not None else None
    )
    positive_corrosion_rates = [
        float(profile["selected_rate_mm_per_year"])
        for profile in rate_profiles.values()
        if profile["selected_rate_mm_per_year"] is not None
    ]
    equipment_summary = {
        "latest_inspection_date": (
            _effective_inspection_date(latest_inspection).date().isoformat()
            if latest_inspection is not None and _effective_inspection_date(latest_inspection) is not None
            else None
        ),
        "inspected_tube_count": (
            latest_snapshot.summary_inspected_tubes
            if latest_snapshot is not None and latest_snapshot.summary_inspected_tubes is not None
            else len(latest_results)
        ),
        "total_tube_count": (
            latest_snapshot.summary_total_tubes
            if latest_snapshot is not None and latest_snapshot.summary_total_tubes is not None
            else expected_count
        ),
        "shell_fluid": master_spec.shell_fluid if master_spec else None,
        "tube_fluid": master_spec.tube_fluid if master_spec else None,
        "tube_material": (
            (master_spec.tube_material if master_spec else None)
            or (latest_snapshot.report_material if latest_snapshot else None)
            or (latest_snapshot.summary_material if latest_snapshot else None)
        ),
        "representative_corrosion_rate_mm_per_year": (
            median(positive_corrosion_rates) if positive_corrosion_rates else None
        ),
        "minimum_actual_thickness_mm": min(
            (
                float(result.minimum_wall_thickness_mm)
                for result, _inspection in latest_results.values()
                if result.minimum_wall_thickness_mm is not None
                and result.minimum_wall_thickness_mm > 0
            ),
            default=None,
        ),
    }

    projections = []
    reason_counts = {"NO_INSPECTION": 0, "NO_NOMINAL_THICKNESS": 0,
                     "NO_POSITIVE_CORROSION_RATE": 0,
                     "INVALID_INSTALLATION_DATE": 0}
    for tube in tubes:
        latest = latest_results.get(tube.tube_id)
        if normalize_tube_status(tube.current_status) == "PLUGGED":
            plugged_result, plugged_inspection = latest if latest else (None, None)
            plugged_date = (
                _effective_inspection_date(plugged_inspection).date()
                if plugged_inspection and _effective_inspection_date(plugged_inspection)
                else as_of_date
            )
            projections.append({
                "tube_id": tube.tube_id, "tube_no": tube.tube_no,
                "row_no": tube.row_no, "column_no": tube.column_no,
                "measurement_date": (
                    _effective_inspection_date(plugged_inspection).date().isoformat()
                    if plugged_inspection and _effective_inspection_date(plugged_inspection) else None
                ),
                "wall_loss_percent": (
                    float(plugged_result.wall_loss_percent)
                    if plugged_result and plugged_result.wall_loss_percent is not None else None
                ),
                "minimum_wall_thickness_mm": (
                    plugged_result.minimum_wall_thickness_mm if plugged_result else None
                ),
                "nominal_thickness_mm": None,
                "current_wall_loss_mm": None, "corrosion_rate_mm_per_year": None,
                "plugging_loss_mm": None, "remaining_loss_mm": 0.0,
                "projection_origin_date": plugged_date.isoformat(),
                "years_from_measurement": 0.0,
                "plugging_date": plugged_date.isoformat(),
                "exact_year": float(plugged_date.year),
                "plugging_year": plugged_date.year,
                "basis": "ALREADY_PLUGGED",
            })
            continue
        if latest is None:
            reason_counts["NO_INSPECTION"] += 1
            continue
        result, inspection = latest
        snapshot = snapshots.get(inspection.iris_inspection_id)
        nominal = next((float(value) for value in (
            snapshot.report_nominal_thickness_mm if snapshot else None,
            master_spec.tube_nominal_thickness_mm if master_spec else None,
            snapshot.summary_design_thickness_mm if snapshot else None,
        ) if value is not None and value > 0), None)
        loss_percent = result.wall_loss_percent
        if nominal is None and result.wall_loss_depth_mm is not None and loss_percent not in (None, 0):
            nominal = result.wall_loss_depth_mm / (loss_percent / 100.0)
        if nominal is None and result.minimum_wall_thickness_mm is not None and loss_percent is not None and loss_percent < 100:
            nominal = result.minimum_wall_thickness_mm / (1.0 - loss_percent / 100.0)
        if nominal is None or nominal <= 0:
            reason_counts["NO_NOMINAL_THICKNESS"] += 1
            continue
        current_loss = result.wall_loss_depth_mm
        if current_loss is None and result.minimum_wall_thickness_mm is not None:
            current_loss = max(nominal - result.minimum_wall_thickness_mm, 0.0)
        if current_loss is None and loss_percent is not None:
            current_loss = nominal * loss_percent / 100.0
        if current_loss is None:
            reason_counts["NO_NOMINAL_THICKNESS"] += 1
            continue
        installed = current_installation_date(equipment.install_date, tube.installed_at,
                                               inspection.installation_or_replacement_date)
        precision = inspection.installation_or_replacement_date_precision or "DAY"
        if inspection.installation_or_replacement_year is not None and precision == "YEAR":
            installed = current_installation_date(installed, date(inspection.installation_or_replacement_year, 7, 1))
        calculation = calculate_latest_installation_projection(
            installation_date=installed,
            measurement_date=_effective_inspection_date(inspection),
            nominal_thickness_mm=nominal,
            wall_loss_percent=loss_percent,
            plugging_wall_loss_percent=plugging_wall_loss_percent,
            rate_multiplier=corrosion_rate_multiplier,
            installation_precision=precision,
        )
        if "plugging_date" not in calculation:
            reason_counts["NO_POSITIVE_CORROSION_RATE" if calculation["status"] == "NO_POSITIVE_WALL_LOSS"
                          else "INVALID_INSTALLATION_DATE"] += 1
            continue
        corrosion_rate = calculation["corrosion_rate_mm_per_year"]
        current_loss = nominal * float(loss_percent) / 100.0
        rate_profile = {
            "selected_rate_mm_per_year": corrosion_rate,
            "long_term_rate_mm_per_year": corrosion_rate / corrosion_rate_multiplier,
            "selection_basis": "LATEST_INSPECTION_INSTALLATION_AVERAGE",
        }
        rate_profiles[tube.tube_id] = rate_profile
        projections.append({
            "tube_id": tube.tube_id, "tube_no": tube.tube_no,
            "row_no": tube.row_no, "column_no": tube.column_no,
            "measurement_date": _effective_inspection_date(inspection).date().isoformat(),
            "wall_loss_percent": float(loss_percent) if loss_percent is not None else None,
            "minimum_wall_thickness_mm": result.minimum_wall_thickness_mm,
            "nominal_thickness_mm": nominal,
            "current_wall_loss_mm": max(float(current_loss), 0.0),
            "corrosion_rate_mm_per_year": corrosion_rate,
            "short_term_corrosion_rate_mm_per_year": rate_profile.get("short_term_rate_mm_per_year"),
            "long_term_corrosion_rate_mm_per_year": rate_profile.get("long_term_rate_mm_per_year"),
            "corrosion_rate_selection_basis": rate_profile.get("selection_basis"),
            **calculation,
            "basis": "CALCULATED",
        })

    projections.sort(key=lambda item: (item["plugging_year"], item["tube_no"]))
    installation_rates = [p["corrosion_rate_mm_per_year"] for p in projections
                          if p.get("calculation_method") == "LATEST_INSPECTION_INSTALLATION_AVERAGE"
                          and p["corrosion_rate_mm_per_year"] > 0]
    equipment_summary["representative_corrosion_rate_mm_per_year"] = (
        median(installation_rates) if installation_rates else None
    )
    current_plugging_count = sum(
        1 for item in projections
        if date.fromisoformat(item["plugging_date"]) <= as_of_date
    )
    summary = summarize_remaining_life(
        plugging_years=[item["plugging_year"] for item in projections],
        total_tube_count=expected_count,
        is_critical=bool(equipment.is_critical),
        current_year=current_year,
        base_year=current_year,
        allowable_plugging_percent=(
            allowable_plugging_percent
            if allowable_plugging_percent is not None
            else (
                criteria.allowable_plugging_percent
                if criteria and criteria.allowable_plugging_percent in REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS
                else REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT
            )
        ),
    )
    summary.update({
        "total_tube_count": expected_count,
        "managed_tube_count": len(tubes),
        "projected_tube_count": len(projections),
        "unprojectable_tube_count": max(len(tubes) - len(projections), 0),
        "projection_coverage_percent": round(len(projections) / len(tubes) * 100, 2) if tubes else 0.0,
        "reason_counts": reason_counts,
        "current_plugging_count": current_plugging_count,
        "plugging_wall_loss_percent": plugging_wall_loss_percent,
        "tube_projections": projections,
        "equipment_summary": equipment_summary,
        "status": "CALCULATED" if summary["life_reached_year"] is not None else (
            "LIMIT_NOT_REACHED" if projections else "INSUFFICIENT_DATA"
        ),
        "as_of_date": as_of_date.isoformat(),
        "corrosion_rate_multiplier": corrosion_rate_multiplier,
        "formula": "최근 검사일 + (기준 감육률 − 최근 감육률) ÷ (최근 감육률 / 설치 후 검사일까지의 사용연수 × 속도 배율)",
        "calculation_method": "LATEST_INSPECTION_INSTALLATION_AVERAGE",
    })
    projection_by_tube = {item["tube_id"]: item for item in projections}
    defect_rows = []
    for tube in tubes:
        latest = latest_results.get(tube.tube_id)
        if latest is None:
            continue
        result, inspection = latest
        wall_loss_percent = result.wall_loss_percent
        if wall_loss_percent is None or wall_loss_percent <= 0:
            continue
        rate_profile = rate_profiles.get(tube.tube_id, {})
        corrosion_rate = rate_profile.get("selected_rate_mm_per_year")
        projection = projection_by_tube.get(tube.tube_id)
        plugging_complete = normalize_tube_status(tube.current_status) == "PLUGGED"
        plugging_threshold_reached = wall_loss_percent >= plugging_wall_loss_percent
        defect_rows.append({
            "tube_id": tube.tube_id,
            "tube_no": tube.tube_no,
            "row_no": tube.row_no,
            "column_no": tube.column_no,
            "measurement_date": _effective_inspection_date(inspection).date().isoformat(),
            "wall_loss_percent": float(wall_loss_percent),
            "minimum_wall_thickness_mm": result.minimum_wall_thickness_mm,
            "corrosion_rate_mm_per_year": corrosion_rate,
            "location_mm": result.location_mm,
            "corrosion_type": result.corrosion_type,
            "wall_loss_depth_mm": result.wall_loss_depth_mm,
            "report_number": inspection.report_number,
            "short_term_corrosion_rate_mm_per_year": rate_profile.get("short_term_rate_mm_per_year"),
            "long_term_corrosion_rate_mm_per_year": rate_profile.get("long_term_rate_mm_per_year"),
            "corrosion_rate_selection_basis": rate_profile.get("selection_basis"),
            "plugging_complete": plugging_complete,
            "plugging_threshold_reached": plugging_threshold_reached,
            "plugging_year": current_year if plugging_complete or plugging_threshold_reached else (
                projection["plugging_year"] if projection else None
            ),
        })
    defect_rows.sort(key=lambda item: (-item["wall_loss_percent"], item["tube_no"]))
    summary["historical_result_count"] = historical_result_count
    summary["defect_rows"] = defect_rows
    summary["defect_count"] = len(defect_rows)
    annual_counts = {row["year"]: row["new_plugging_count"] for row in summary["yearly"]}
    cumulative = sum(count for year, count in annual_counts.items()
                     if year < current_year)
    chart_series = []
    chart_end_year = int(
        REMAINING_LIFE_FORECAST_END_YEAR if forecast_end_year is None else forecast_end_year
    )
    if not current_year <= chart_end_year <= 2200:
        raise ValueError(f"예측 종료 연도는 {current_year}년부터 2200년 사이여야 합니다.")
    for year in range(current_year, chart_end_year + 1):
        cumulative += annual_counts.get(year, 0)
        chart_series.append({
            "year": year,
            "cumulative_plugging_count": cumulative,
            "limit_exceeded": cumulative > summary["allowable_plugging_count"],
            "life_reached": year == summary["life_reached_year"],
        })
    summary["chart_series"] = chart_series
    return summary


def remaining_life_tube_search(target_year: int, unit_code: str = "",
                               search: str = "") -> dict[str, Any]:
    as_of_date = remaining_life_as_of_date()
    base_year = as_of_date.year
    if target_year < base_year or target_year > 2200:
        raise ValueError(f"예상 연도는 {base_year}~2200 사이로 입력해 주세요.")
    unit_code = str(unit_code or "").strip().upper()
    search = str(search or "").strip()
    with session_scope(DB_PATH) as session:
        stmt = (
            select(HeatExchanger, Equipment, ProcessUnit, Plant,
                   HeatExchangerSpecRevision)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .outerjoin(
                HeatExchangerSpecRevision,
                and_(
                    HeatExchangerSpecRevision.heat_exchanger_id
                    == HeatExchanger.heat_exchanger_id,
                    HeatExchangerSpecRevision.is_current.is_(True),
                ),
            )
            .order_by(Plant.plant_code, ProcessUnit.unit_code, Equipment.equipment_code)
        )
        if unit_code:
            stmt = stmt.where(ProcessUnit.unit_code == unit_code)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(or_(
                Equipment.equipment_code.ilike(term),
                HeatExchangerSpecRevision.exchanger_code.ilike(term),
                Equipment.equipment_name.ilike(term),
            ))
        masters = session.execute(stmt).all()
        rows = []
        searched_exchanger_count = 0
        for exchanger, equipment, unit, plant, current_spec in masters:
            exchanger_code = current_spec.exchanger_code if current_spec else None
            bundles = session.scalars(
                select(TubeBundle).where(
                    TubeBundle.heat_exchanger_id == exchanger.heat_exchanger_id
                )
            ).all()
            if not bundles:
                continue
            searched_exchanger_count += 1
            criteria = session.scalar(
                select(HeatExchangerManagementCriteria).where(
                    HeatExchangerManagementCriteria.heat_exchanger_id
                    == exchanger.heat_exchanger_id
                )
            )
            projection = _remaining_life_projection(
                session, exchanger.heat_exchanger_id, equipment, bundles, criteria
            )
            for tube in projection["tube_projections"]:
                if tube["plugging_year"] != target_year:
                    continue
                rows.append({
                    "plant_code": plant.plant_code,
                    "unit_code": unit.unit_code,
                    "heat_exchanger_id": exchanger.heat_exchanger_id,
                    "equipment_code": equipment.equipment_code,
                    "exchanger_code": exchanger_code,
                    "equipment_name": equipment.equipment_name,
                    "is_critical": bool(equipment.is_critical),
                    "limit_percent": projection["limit_percent"],
                    "remaining_life_years": target_year - base_year,
                    **tube,
                })
        rows.sort(key=lambda row: (
            row["plant_code"], row["unit_code"], row["equipment_code"], row["tube_no"]
        ))
        units = list(session.scalars(
            select(ProcessUnit.unit_code).distinct().order_by(ProcessUnit.unit_code)
        ).all())
        return {
            "rows": rows,
            "target_year": target_year,
            "base_year": base_year,
            "as_of_date": as_of_date.isoformat(),
            "plugging_wall_loss_percent": REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT,
            "unit_code": unit_code,
            "search": search,
            "units": units,
            "searched_exchanger_count": searched_exchanger_count,
            "matched_exchanger_count": len({row["heat_exchanger_id"] for row in rows}),
        }


def inspection_detail(inspection_id: int) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        row = session.execute(
            select(IrisInspection, Equipment, InspectionScope, SourceDocument,
                   HeatExchangerSpecRevision)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == IrisInspection.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
            .join(SourceDocument, SourceDocument.source_document_id == IrisInspection.source_document_id)
            .outerjoin(
                HeatExchangerSpecRevision,
                and_(
                    HeatExchangerSpecRevision.heat_exchanger_id
                    == HeatExchanger.heat_exchanger_id,
                    HeatExchangerSpecRevision.is_current.is_(True),
                ),
            )
            .where(IrisInspection.iris_inspection_id == inspection_id)
        ).first()
        if not row:
            return None
        results = session.execute(
            select(IrisTubeResult, HeatExchangerTube)
            .join(HeatExchangerTube, HeatExchangerTube.tube_id == IrisTubeResult.tube_id)
            .where(IrisTubeResult.iris_inspection_id == inspection_id)
            .order_by(HeatExchangerTube.row_no, HeatExchangerTube.column_no)
        ).all()
        issues = session.scalars(select(DataQualityIssue).where(DataQualityIssue.iris_inspection_id == inspection_id)).all()
        setup = session.scalar(select(IrisSetupSnapshot).where(
            IrisSetupSnapshot.iris_inspection_id == inspection_id
        ))
        execution = session.scalar(select(InspectionExecutionSnapshot).where(
            InspectionExecutionSnapshot.iris_inspection_id == inspection_id
        ))
        provider = (
            session.get(InspectionProvider, execution.inspection_provider_id)
            if execution and execution.inspection_provider_id else None
        )
        personnel = session.scalars(select(InspectionPersonnel).where(
            InspectionPersonnel.iris_inspection_id == inspection_id
        ).order_by(InspectionPersonnel.role)).all()
        providers = session.scalars(select(InspectionProvider).where(
            InspectionProvider.is_active.is_(True)
        ).order_by(InspectionProvider.provider_name)).all()
        return {
            "master": row, "results": results, "issues": issues,
            "setup": setup, "execution": execution, "provider": provider,
            "personnel": personnel, "providers": providers,
        }


def save_inspection_execution(inspection_id: int, data: dict[str, Any]) -> bool:
    """Save governed provider, software, procedure, equipment, and personnel metadata."""
    with session_scope(DB_PATH) as session:
        inspection = session.get(IrisInspection, inspection_id)
        if inspection is None:
            return False

        provider_id = int(data["inspection_provider_id"]) if (
            str(data.get("inspection_provider_id") or "").strip()
        ) else None
        provider_name = str(data.get("new_provider_name") or "").strip()
        provider_code = str(data.get("new_provider_code") or "").strip().upper()
        if provider_id is not None and session.get(InspectionProvider, provider_id) is None:
            raise ValueError("선택한 검사 수행업체가 존재하지 않습니다.")
        if provider_name:
            provider_code = provider_code or re.sub(
                r"[^A-Z0-9]+", "_", provider_name.upper()
            ).strip("_")[:50]
            if not provider_code:
                raise ValueError("신규 수행업체 코드를 입력해 주세요.")
            provider = session.scalar(select(InspectionProvider).where(
                InspectionProvider.provider_code == provider_code
            ))
            if provider is None:
                provider = InspectionProvider(
                    provider_code=provider_code, provider_name=provider_name
                )
                session.add(provider)
                session.flush()
            provider_id = provider.inspection_provider_id

        execution = session.scalar(select(InspectionExecutionSnapshot).where(
            InspectionExecutionSnapshot.iris_inspection_id == inspection_id
        ))
        if execution is None:
            execution = InspectionExecutionSnapshot(iris_inspection_id=inspection_id)
            session.add(execution)
        execution.inspection_provider_id = provider_id
        field_names = (
            "inspection_company_raw", "contract_no", "work_order_no",
            "procedure_no", "procedure_revision", "acquisition_software_name",
            "acquisition_software_version", "analysis_software_name",
            "analysis_software_version", "remarks",
        )
        for field_name in field_names:
            setattr(execution, field_name, str(data.get(field_name) or "").strip() or None)
        execution.equipment_calibration_date = _date(
            data.get("equipment_calibration_date")
        )
        execution.equipment_calibration_valid_until = _date(
            data.get("equipment_calibration_valid_until")
        )

        setup = session.scalar(select(IrisSetupSnapshot).where(
            IrisSetupSnapshot.iris_inspection_id == inspection_id
        ))
        if setup is None:
            setup = IrisSetupSnapshot(iris_inspection_id=inspection_id)
            session.add(setup)
        for field_name in (
            "equipment_maker", "equipment_model", "equipment_serial_number",
            "search_unit_maker", "search_unit_model", "search_unit_serial_number",
        ):
            if field_name in data:
                setattr(setup, field_name, str(data.get(field_name) or "").strip() or None)

        for role in ("EXAMINER", "INTERPRETER", "PREPARED_BY"):
            if f"organization_{role.lower()}" not in data:
                continue
            organization = str(data.get(f"organization_{role.lower()}") or "").strip()
            person = session.scalar(select(InspectionPersonnel).where(
                InspectionPersonnel.iris_inspection_id == inspection_id,
                InspectionPersonnel.role == role,
            ))
            if person is None and organization:
                person = InspectionPersonnel(
                    iris_inspection_id=inspection_id, role=role
                )
                session.add(person)
            if person is not None:
                person.organization = organization or None
        return True


def tube_detail(tube_id: int) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        row = session.execute(
            select(HeatExchangerTube, TubeBundle, HeatExchanger, Equipment)
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == TubeBundle.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .where(HeatExchangerTube.tube_id == tube_id)
        ).first()
        if not row:
            return None
        history = session.execute(
            select(IrisTubeResult, IrisInspection, InspectionScope)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
            .where(IrisTubeResult.tube_id == tube_id)
            .order_by(IrisInspection.report_date, IrisInspection.report_sequence)
        ).all()
        degradation = session.scalars(
            select(TubeDegradationAssessment)
            .where(
                TubeDegradationAssessment.tube_id == tube_id,
                TubeDegradationAssessment.algorithm_version
                == DEGRADATION_ALGORITHM_VERSION,
            )
            .order_by(TubeDegradationAssessment.current_result_id)
        ).all()
        if not degradation:
            degradation = session.scalars(
                select(TubeDegradationAssessment)
                .where(TubeDegradationAssessment.tube_id == tube_id)
                .order_by(TubeDegradationAssessment.current_result_id)
            ).all()
        historical_result_ids = {
            result.iris_tube_result_id for result, inspection, _scope in history
            if not is_current_installation_inspection(_effective_inspection_date(inspection), row[3].install_date, row[0].installed_at)
        }
        degradation = [item for item in degradation if item.current_result_id not in historical_result_ids
                       and item.previous_result_id not in historical_result_ids]
        events = session.scalars(
            select(TubeLifecycleEvent)
            .where(TubeLifecycleEvent.tube_id == tube_id)
            .order_by(TubeLifecycleEvent.lifecycle_event_id.desc())
        ).all()
        return {"master": row, "history": history, "degradation": degradation,
                "historical_result_ids": historical_result_ids,
                "events": events, "tube_statuses": TUBE_OPERATION_STATUSES,
                "normalized_status": normalize_tube_status(row[0].current_status)}


def update_tube_status(tube_id: int, status: str, reason: str = "") -> dict[str, Any] | None:
    new_status = normalize_tube_status(status)
    if new_status not in TUBE_OPERATION_STATUSES:
        raise ValueError("지원하지 않는 튜브 상태입니다.")
    with session_scope(DB_PATH) as session:
        tube = session.get(HeatExchangerTube, tube_id)
        if tube is None:
            return None
        old_status = normalize_tube_status(tube.current_status)
        tube.current_status = new_status
        if old_status != new_status:
            session.add(TubeLifecycleEvent(
                tube_id=tube_id,
                event_type=f"STATUS_{old_status}_TO_{new_status}",
                reason=(reason or "").strip() or None,
            ))
        return {"tube_id": tube_id, "old_status": old_status,
                "new_status": new_status, "changed": old_status != new_status}


def _indication_surface_side(indication: IrisIndication) -> str:
    """Return INNER/OUTER only when the source explicitly identifies the surface."""
    candidates: list[Any] = [indication.defect_type, indication.judgement]
    try:
        payload = json.loads(indication.raw_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    for container in (payload, payload.get("data") if isinstance(payload, dict) else None):
        if not isinstance(container, dict):
            continue
        for key in (
            "surface_side", "surface", "corrosion_side", "defect_side",
            "wall_side", "id_od", "ID_OD", "inside_outside",
        ):
            if key in container:
                candidates.append(container[key])

    for candidate in candidates:
        value = re.sub(r"[\s._/-]+", "", str(candidate or "").upper())
        if value in {"INNER", "INTERNAL", "INSIDE", "ID", "TUBEID", "내면", "내부"}:
            return "INNER"
        if value in {"OUTER", "EXTERNAL", "OUTSIDE", "OD", "TUBEOD", "외면", "외부"}:
            return "OUTER"
    return "UNKNOWN"


def tube_map_data(exchanger_id: int, campaign_id: int | None = None) -> dict[str, Any] | None:
    """Build a year-level tube map using the worst result across inspection scopes."""
    with session_scope(DB_PATH) as session:
        master = session.execute(
            select(HeatExchanger, Equipment, ProcessUnit)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .where(HeatExchanger.heat_exchanger_id == exchanger_id)
        ).first()
        if not master:
            return None
        hx, equipment, unit = master
        campaign_rows = session.execute(
            select(
                InspectionCampaign.campaign_id,
                InspectionCampaign.campaign_year,
                InspectionCampaign.campaign_name,
                func.count(IrisInspection.iris_inspection_id).label("report_count"),
                func.min(IrisInspection.report_date).label("start_date"),
                func.max(IrisInspection.report_date).label("end_date"),
            )
            .join(IrisInspection, IrisInspection.campaign_id == InspectionCampaign.campaign_id)
            .where(IrisInspection.heat_exchanger_id == exchanger_id)
            .group_by(InspectionCampaign.campaign_id)
            .order_by(InspectionCampaign.campaign_year.desc(), InspectionCampaign.campaign_id.desc())
        ).all()
        campaigns = [{
            "campaign_id": row.campaign_id, "year": row.campaign_year,
            "name": row.campaign_name, "report_count": row.report_count,
            "start_date": row.start_date.date().isoformat() if row.start_date else None,
            "end_date": row.end_date.date().isoformat() if row.end_date else None,
        } for row in campaign_rows]
        available_ids = {row["campaign_id"] for row in campaigns}
        selected_campaign_id = campaign_id if campaign_id is not None else (
            campaigns[0]["campaign_id"] if campaigns else None
        )
        if selected_campaign_id is not None and selected_campaign_id not in available_ids:
            raise ValueError("Selected inspection campaign does not belong to this exchanger.")

        map_orientation = None
        if selected_campaign_id is not None:
            map_orientation = session.scalar(
                select(IrisTubeMap.orientation)
                .join(
                    IrisInspection,
                    IrisInspection.iris_inspection_id == IrisTubeMap.iris_inspection_id,
                )
                .where(
                    IrisInspection.heat_exchanger_id == exchanger_id,
                    IrisInspection.campaign_id == selected_campaign_id,
                    IrisTubeMap.orientation.is_not(None),
                    func.trim(IrisTubeMap.orientation) != "",
                )
                .order_by(
                    IrisInspection.report_date.desc(),
                    IrisInspection.iris_inspection_id.desc(),
                )
                .limit(1)
            )

        geometry_rows = session.execute(
            select(TubeSheetGeometryRevision, IrisInspection.campaign_id, IrisInspection.report_date)
            .join(
                IrisInspection,
                IrisInspection.iris_inspection_id == TubeSheetGeometryRevision.iris_inspection_id,
            )
            .where(TubeSheetGeometryRevision.heat_exchanger_id == exchanger_id)
        ).all()
        geometry_rows.sort(key=lambda row: (
            0 if selected_campaign_id is not None and row.campaign_id == selected_campaign_id else 1,
            {"APPROVED": 0, "REVIEWED": 1, "CONFLICT": 2, "DRAFT": 3, "REJECTED": 4}.get(
                row[0].review_status, 5
            ),
            -(row.report_date.timestamp() if row.report_date else 0),
            -row[0].geometry_revision_id,
        ))
        selected_geometry = geometry_rows[0][0] if geometry_rows else None
        pdf_geometry = None
        if selected_geometry:
            try:
                boundary_geometry = json.loads(selected_geometry.boundary_geometry_json)
            except (TypeError, ValueError):
                boundary_geometry = None
            pdf_geometry = {
                "geometry_revision_id": selected_geometry.geometry_revision_id,
                "shape_code": selected_geometry.shape_code,
                "geometry_source": selected_geometry.geometry_source,
                "shape_confidence": selected_geometry.shape_confidence,
                "explicit_boundary_detected": bool(selected_geometry.explicit_boundary_detected),
                "mechanical_boundary_confirmed": bool(selected_geometry.explicit_boundary_detected),
                "review_status": selected_geometry.review_status,
                "verification_status": selected_geometry.verification_status,
                "source_pdf_path": selected_geometry.source_pdf_path,
                "source_page": selected_geometry.source_page,
                "source_orientation": selected_geometry.source_orientation,
                "expected_tube_count": selected_geometry.expected_tube_count,
                "extracted_tube_count": selected_geometry.extracted_tube_count,
                "tube_count_match": bool(selected_geometry.tube_count_match),
                "consensus_shape_code": selected_geometry.consensus_shape_code,
                "consensus_confidence": selected_geometry.consensus_confidence,
                "consensus_sample_count": selected_geometry.consensus_sample_count,
                "cross_year_consistent": selected_geometry.cross_year_consistent,
                "boundary_geometry": boundary_geometry,
                "analysis_note": selected_geometry.analysis_note,
            }
        effective_shape_code = "CIRCULAR"
        effective_width_height_ratio = 1.0
        if selected_geometry and selected_geometry.review_status != "REJECTED":
            if (
                selected_geometry.consensus_shape_code
                and float(selected_geometry.consensus_confidence or 0) >= 0.60
            ):
                effective_shape_code = selected_geometry.consensus_shape_code
            else:
                effective_shape_code = selected_geometry.shape_code or "CIRCULAR"
            if selected_geometry.width and selected_geometry.height:
                effective_width_height_ratio = float(selected_geometry.width) / max(
                    float(selected_geometry.height), 1e-9
                )

        bundles = session.scalars(
            select(TubeBundle).where(TubeBundle.heat_exchanger_id == exchanger_id)
            .order_by(TubeBundle.lifecycle_no.desc(), TubeBundle.bundle_code)
        ).all()
        bundle_ids = [bundle.bundle_id for bundle in bundles]
        tubes = session.scalars(
            select(HeatExchangerTube).where(HeatExchangerTube.bundle_id.in_(bundle_ids))
            .order_by(HeatExchangerTube.row_no, HeatExchangerTube.column_no, HeatExchangerTube.tube_no)
        ).all() if bundle_ids else []
        approved_layout_rows = session.execute(
            select(TubeLayoutRevision, TubeLayoutPoint)
            .join(
                TubeLayoutPoint,
                TubeLayoutPoint.layout_revision_id == TubeLayoutRevision.layout_revision_id,
            )
            .where(
                TubeLayoutRevision.bundle_id.in_(bundle_ids),
                TubeLayoutRevision.revision_status == "APPROVED",
            )
            .order_by(
                TubeLayoutRevision.bundle_id,
                TubeLayoutPoint.source_row,
                TubeLayoutPoint.source_column,
            )
        ).all() if bundle_ids else []
        criteria = session.scalar(select(HeatExchangerManagementCriteria).where(
            HeatExchangerManagementCriteria.heat_exchanger_id == exchanger_id
        ))
        spec = session.scalar(
            select(HeatExchangerSpecRevision)
            .where(HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id)
            .order_by(HeatExchangerSpecRevision.is_current.desc(),
                      HeatExchangerSpecRevision.revision_no.desc())
        )
        snapshot_rows = session.execute(
            select(IrisInspectionSpecSnapshot, IrisInspection.campaign_id)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisInspectionSpecSnapshot.iris_inspection_id)
            .where(IrisInspection.heat_exchanger_id == exchanger_id)
            .order_by(IrisInspection.report_date.desc(), IrisInspection.iris_inspection_id.desc())
        ).all()
        if selected_campaign_id is not None:
            snapshot_rows.sort(key=lambda row: 0 if row.campaign_id == selected_campaign_id else 1)

        def first_number(*values):
            return next((float(value) for value in values if value is not None), None)

        def first_snapshot_number(*field_names):
            return first_number(*(
                getattr(snapshot, field_name)
                for snapshot, _campaign_id in snapshot_rows
                for field_name in field_names
            ))

        tube_length_info = _resolve_tube_length(session, exchanger_id, selected_campaign_id)
        tube_length_mm = tube_length_info["length_mm"]
        tube_outer_diameter_mm = first_number(
            spec.tube_outer_diameter_mm if spec else None,
            first_snapshot_number("report_outer_diameter_mm", "summary_outer_diameter_mm"),
        )
        tube_nominal_thickness_mm = first_number(
            spec.tube_nominal_thickness_mm if spec else None,
            first_snapshot_number("report_nominal_thickness_mm", "summary_design_thickness_mm"),
        )
        warning_threshold = criteria.warning_wall_loss_percent if (
            criteria and criteria.warning_wall_loss_percent is not None
        ) else 20.0
        critical_threshold = criteria.critical_wall_loss_percent if (
            criteria and criteria.critical_wall_loss_percent is not None
        ) else 40.0

        aggregated: dict[int, dict[str, Any]] = {}
        if selected_campaign_id is not None:
            result_rows = session.execute(
                select(IrisTubeResult, IrisInspection, InspectionScope)
                .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
                .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
                .where(IrisInspection.heat_exchanger_id == exchanger_id,
                       IrisInspection.campaign_id == selected_campaign_id)
            ).all()
            result_ids = [result.iris_tube_result_id for result, _inspection, _scope in result_rows]
            inspection_ids = {
                inspection.iris_inspection_id for _result, inspection, _scope in result_rows
            }
            indication_rows = session.scalars(
                select(IrisIndication)
                .where(IrisIndication.iris_tube_result_id.in_(result_ids))
                .order_by(
                    IrisIndication.iris_tube_result_id,
                    IrisIndication.sequence_no,
                )
            ).all() if result_ids else []
            indications_by_result: dict[int, list[IrisIndication]] = {}
            for indication in indication_rows:
                indications_by_result.setdefault(indication.iris_tube_result_id, []).append(indication)
            assessment_by_inspection = {
                assessment.iris_inspection_id: assessment
                for assessment in session.scalars(
                    select(IrisRepresentativeAssessment).where(
                        IrisRepresentativeAssessment.iris_inspection_id.in_(inspection_ids)
                    )
                ).all()
            } if inspection_ids else {}

            for result, inspection, scope in result_rows:
                assessment = assessment_by_inspection.get(inspection.iris_inspection_id)
                try:
                    direction_labels = json.loads(assessment.direction_labels_json or "[]") \
                        if assessment else []
                except (TypeError, json.JSONDecodeError):
                    direction_labels = []
                position_reference = {
                    "start_point": assessment.start_point if assessment else None,
                    "end_point": assessment.end_point if assessment else None,
                    "direction_labels": direction_labels if isinstance(direction_labels, list) else [],
                }
                entry = aggregated.get(result.tube_id)
                loss = result.wall_loss_percent
                if entry is None:
                    entry = {
                        "wall_loss_percent": loss,
                        "minimum_wall_thickness_mm": result.minimum_wall_thickness_mm,
                        "wall_loss_depth_mm": result.wall_loss_depth_mm,
                        "corrosion_type": result.corrosion_type,
                        "location_mm": result.location_mm,
                        "inspection_date": inspection.report_date.date().isoformat() if inspection.report_date else None,
                        "scopes": set(),
                        "indications": [],
                    }
                    aggregated[result.tube_id] = entry
                else:
                    old_loss = entry["wall_loss_percent"]
                    if loss is not None and (old_loss is None or loss > old_loss):
                        entry.update(
                            wall_loss_percent=loss,
                            wall_loss_depth_mm=result.wall_loss_depth_mm,
                            corrosion_type=result.corrosion_type,
                            location_mm=result.location_mm,
                            inspection_date=inspection.report_date.date().isoformat() if inspection.report_date else None,
                        )
                    thickness = result.minimum_wall_thickness_mm
                    if thickness is not None and (
                        entry["minimum_wall_thickness_mm"] is None
                        or thickness < entry["minimum_wall_thickness_mm"]
                    ):
                        entry["minimum_wall_thickness_mm"] = thickness
                if scope:
                    entry["scopes"].add(scope.scope_code)

                detailed_indications = indications_by_result.get(result.iris_tube_result_id, [])
                if detailed_indications:
                    for indication in detailed_indications:
                        has_measured_axial_position = indication.axial_position_mm is not None
                        effective_axial_position = (
                            indication.axial_position_mm
                            if has_measured_axial_position
                            else result.location_mm
                        )
                        entry["indications"].append({
                            "indication_id": indication.iris_indication_id,
                            "sequence_no": indication.sequence_no,
                            "inspection_id": inspection.iris_inspection_id,
                            "report_number": inspection.report_number,
                            "inspection_date": inspection.report_date.date().isoformat()
                            if inspection.report_date else None,
                            "scope_code": scope.scope_code if scope else None,
                            "source_page": indication.source_page or result.source_page,
                            "visual_page_role": indication.visual_page_role,
                            "axial_position_mm": effective_axial_position,
                            "circumferential_angle_deg": indication.circumferential_angle_deg,
                            "measured_thickness_mm": indication.measured_thickness_mm,
                            "wall_loss_depth_mm": indication.wall_loss_depth_mm,
                            "wall_loss_percent": indication.wall_loss_percent,
                            "remaining_percent": indication.remaining_percent,
                            "defect_type": indication.defect_type,
                            "surface_side": _indication_surface_side(indication),
                            "defect_length_mm": indication.defect_length_mm,
                            "judgement": indication.judgement,
                            "position_quality": "MEASURED" if has_measured_axial_position else (
                                "RESULT_REPRESENTATIVE" if result.location_mm is not None else "UNKNOWN"
                            ),
                            "position_source": "INDICATION" if has_measured_axial_position else (
                                "TUBE_RESULT" if result.location_mm is not None else "UNKNOWN"
                            ),
                            "circumferential_position_known": indication.circumferential_angle_deg is not None,
                            "source_location_raw": result.source_location_raw,
                            "location_source_unit": result.location_source_unit,
                            "is_representative": not has_measured_axial_position and result.location_mm is not None,
                            "position_reference": position_reference,
                        })
                else:
                    entry["indications"].append({
                        "indication_id": None,
                        "sequence_no": None,
                        "inspection_id": inspection.iris_inspection_id,
                        "report_number": inspection.report_number,
                        "inspection_date": inspection.report_date.date().isoformat()
                        if inspection.report_date else None,
                        "scope_code": scope.scope_code if scope else None,
                        "source_page": result.source_page,
                        "visual_page_role": None,
                        "axial_position_mm": result.location_mm,
                        "circumferential_angle_deg": None,
                        "circumferential_position_known": False,
                        "measured_thickness_mm": result.minimum_wall_thickness_mm,
                        "wall_loss_depth_mm": result.wall_loss_depth_mm,
                        "wall_loss_percent": result.wall_loss_percent,
                        "remaining_percent": None,
                        "defect_type": result.corrosion_type or result.defect_code,
                        "surface_side": "UNKNOWN",
                        "defect_length_mm": None,
                        "judgement": result.result_status,
                        "position_quality": "RESULT_REPRESENTATIVE"
                        if result.location_mm is not None else "UNKNOWN",
                        "position_source": "TUBE_RESULT",
                        "source_location_raw": result.source_location_raw,
                        "location_source_unit": result.location_source_unit,
                        "is_representative": True,
                        "position_reference": position_reference,
                    })

            for entry in aggregated.values():
                entry["indications"].sort(key=lambda item: (
                    item["axial_position_mm"] is None,
                    item["axial_position_mm"] or 0,
                    item["circumferential_angle_deg"] is None,
                    item["circumferential_angle_deg"] or 0,
                    item["inspection_id"],
                ))

        counts = {"NOT_INSPECTED": 0, "NORMAL": 0, "WARNING": 0,
                  "CRITICAL": 0, "PLUGGED": 0}
        operational_counts = {key: 0 for key in TUBE_OPERATION_STATUSES}
        inspection_counts = {"INSPECTED": 0, "NOT_INSPECTED": 0}
        tube_items = []
        for tube in tubes:
            result = aggregated.get(tube.tube_id)
            loss = result["wall_loss_percent"] if result else None
            operational_status = normalize_tube_status(tube.current_status)
            operational_counts.setdefault(operational_status, 0)
            operational_counts[operational_status] += 1
            inspection_status = "INSPECTED" if result is not None else "NOT_INSPECTED"
            inspection_counts[inspection_status] += 1
            if operational_status == "PLUGGED":
                category = "PLUGGED"
            elif result is None:
                category = "NOT_INSPECTED"
            elif loss is not None and loss >= critical_threshold:
                category = "CRITICAL"
            elif loss is not None and loss >= warning_threshold:
                category = "WARNING"
            else:
                category = "NORMAL"
            counts[category] += 1
            has_registered_xy = tube.position_x is not None and tube.position_y is not None
            has_report_grid = tube.row_no is not None and tube.column_no is not None
            if has_registered_xy and tube.position_locked:
                coordinate_quality = "VERIFIED"
            elif has_registered_xy:
                coordinate_quality = "REGISTERED"
            elif has_report_grid:
                coordinate_quality = "REPORT_GRID"
            else:
                coordinate_quality = "UNKNOWN"
            tube_items.append({
                "tube_id": tube.tube_id, "tube_no": tube.tube_no,
                "row": tube.row_no, "column": tube.column_no,
                "x": tube.position_x if tube.position_x is not None else tube.column_no,
                "y": tube.position_y if tube.position_y is not None else tube.row_no,
                "z": tube.position_z or 0, "lifecycle_no": tube.lifecycle_no,
                "coordinate_quality": coordinate_quality,
                "coordinate_source": "REGISTERED_XY" if has_registered_xy else (
                    "REPORT_ROW_COLUMN" if has_report_grid else "UNKNOWN"
                ),
                "coordinate_is_verified": coordinate_quality == "VERIFIED",
                "current_status": operational_status,
                "position_locked": bool(tube.position_locked),
                "operational_status": operational_status,
                "inspection_status": inspection_status,
                "category": category, "inspected": result is not None,
                "wall_loss_percent": loss,
                "minimum_wall_thickness_mm": result["minimum_wall_thickness_mm"] if result else None,
                "wall_loss_depth_mm": result["wall_loss_depth_mm"] if result else None,
                "corrosion_type": result["corrosion_type"] if result else None,
                "location_mm": result["location_mm"] if result else None,
                "inspection_date": result["inspection_date"] if result else None,
                "scopes": sorted(result["scopes"]) if result else [],
                "indication_count": len(result["indications"]) if result else 0,
                "measured_indication_count": sum(
                    1 for indication in result["indications"]
                    if indication["position_quality"] == "MEASURED"
                ) if result else 0,
                "circumferential_indication_count": sum(
                    1 for indication in result["indications"]
                    if indication["circumferential_angle_deg"] is not None
                ) if result else 0,
                "indications": result["indications"] if result else [],
            })
        approved_layout_revision = approved_layout_rows[0][0] if approved_layout_rows else None
        approved_layout_revisions = {
            revision.layout_revision_id: revision
            for revision, _point in approved_layout_rows
        }
        approved_layout_point_count = len(approved_layout_rows)
        unlinked_layout_count = 0
        if approved_layout_rows:
            tubes_by_id = {item["tube_id"]: item for item in tube_items}
            display_items = []
            for display_slot, (revision, point) in enumerate(approved_layout_rows, 1):
                source_x = point.canonical_x if point.canonical_x is not None else point.source_x
                source_y = point.canonical_y if point.canonical_y is not None else point.source_y
                linked = tubes_by_id.get(point.tube_id)
                if linked:
                    item = dict(linked)
                    item.update({
                        "x": source_x, "y": source_y,
                        "source_x": point.source_x, "source_y": point.source_y,
                        "position_source": "APPROVED_LAYOUT",
                        "coordinate_quality": "APPROVED_LAYOUT",
                        "coordinate_source": "APPROVED_LAYOUT",
                        "coordinate_is_verified": True,
                        "position_locked": True,
                        "managed": True,
                        "layout_revision_id": revision.layout_revision_id,
                        "display_slot": display_slot,
                    })
                else:
                    unlinked_layout_count += 1
                    item = {
                        "tube_id": None,
                        "tube_no": point.source_tube_id or f"{point.source_row}-{point.source_column}",
                        "row": point.source_row, "column": point.source_column,
                        "source_x": point.source_x, "source_y": point.source_y,
                        "x": source_x, "y": source_y, "z": 0,
                        "coordinate_quality": "APPROVED_LAYOUT",
                        "coordinate_source": "APPROVED_LAYOUT",
                        "coordinate_is_verified": True,
                        "position_locked": True,
                        "lifecycle_no": None, "current_status": "UNKNOWN",
                        "operational_status": "UNKNOWN",
                        "inspection_status": "NOT_INSPECTED",
                        "category": "NOT_INSPECTED", "inspected": False,
                        "wall_loss_percent": None,
                        "minimum_wall_thickness_mm": None,
                        "wall_loss_depth_mm": None,
                        "corrosion_type": None, "location_mm": None,
                        "inspection_date": None, "scopes": [],
                        "position_source": "APPROVED_LAYOUT",
                        "indication_count": 0,
                        "measured_indication_count": 0,
                        "circumferential_indication_count": 0,
                        "indications": [],
                        "layout_revision_id": revision.layout_revision_id,
                        "display_slot": display_slot, "managed": False,
                    }
                display_items.append(item)
            approved_bundle_ids = {
                revision.bundle_id for revision in approved_layout_revisions.values()
            }
            configured_physical_counts = [
                revision.physical_tube_count
                for revision in approved_layout_revisions.values()
            ]
            if configured_physical_counts and all(
                value is not None for value in configured_physical_counts
            ):
                expected_count = sum(int(value) for value in configured_physical_counts)
            else:
                expected_count = sum(
                    int(bundle.expected_tube_count or 0)
                    for bundle in bundles if bundle.bundle_id in approved_bundle_ids
                ) or len(display_items)
        else:
            expected_count = max([bundle.expected_tube_count or 0 for bundle in bundles] or [0])
            if expected_count == 0:
                expected_count = session.scalar(
                    select(func.max(IrisInspection.total_tube_count_reported))
                    .where(IrisInspection.heat_exchanger_id == exchanger_id)
                ) or 0
            display_items = _estimated_circular_layout(
                tube_items,
                expected_count,
                shape_code=effective_shape_code,
                width_height_ratio=effective_width_height_ratio,
            )
        selected_campaign = next(
            (row for row in campaigns if row["campaign_id"] == selected_campaign_id), None
        )
        display_counts = {key: 0 for key in counts}
        for item in display_items:
            display_counts[item["category"]] += 1
        virtual_count = 0 if approved_layout_rows else max(len(display_items) - len(tube_items), 0)
        display_operational_counts = {**operational_counts, "UNKNOWN": virtual_count}
        if approved_layout_rows:
            display_operational_counts["UNKNOWN"] = unlinked_layout_count
        display_inspection_counts = dict(inspection_counts)
        display_inspection_counts["NOT_INSPECTED"] += (
            unlinked_layout_count if approved_layout_rows else virtual_count
        )
        detailed_indications = [
            indication
            for item in tube_items
            for indication in item["indications"]
        ]
        registered_xy_count = sum(
            item["coordinate_source"] == "REGISTERED_XY" for item in tube_items
        )
        verified_xy_count = sum(item["coordinate_is_verified"] for item in tube_items)
        return {
            "heat_exchanger_id": exchanger_id,
            "equipment_code": equipment.equipment_code,
            "equipment_name": equipment.equipment_name,
            "unit_code": unit.unit_code,
            "campaigns": campaigns, "selected_campaign": selected_campaign,
            "thresholds": {"warning": warning_threshold, "critical": critical_threshold},
            "colors": _wall_loss_color_map(session),
            "tube_spec": {
                "length_mm": tube_length_mm,
                "outer_diameter_mm": tube_outer_diameter_mm,
                "nominal_thickness_mm": tube_nominal_thickness_mm,
                "source": tube_length_info["source"],
                "source_label": tube_length_info["source_label"],
                "length_is_estimated": tube_length_info["is_estimated"],
                "length_sample_count": tube_length_info["sample_count"],
            },
            "summary": {
                "expected_tube_count": expected_count,
                "mapped_tube_count": len(tube_items),
                "display_tube_count": len(display_items),
                "display_position_count": len(display_items),
                "unmapped_expected_count": 0 if approved_layout_rows else max(expected_count - len(tube_items), 0),
                "unlinked_layout_count": unlinked_layout_count,
                "inspected_count": len(aggregated),
                "inspection_coverage_percent": round(len(aggregated) / expected_count * 100, 2)
                if expected_count else None,
                "operational": display_operational_counts,
                "inspection": display_inspection_counts,
                **display_counts,
            },
            "data_quality": {
                "registered_xy_count": registered_xy_count,
                "verified_xy_count": (
                    approved_layout_point_count if approved_layout_rows else verified_xy_count
                ),
                "approved_layout_coordinate_count": approved_layout_point_count,
                "report_grid_count": sum(
                    item["coordinate_source"] == "REPORT_ROW_COLUMN" for item in tube_items
                ),
                "estimated_display_count": virtual_count,
                "indication_count": len(detailed_indications),
                "measured_axial_position_count": sum(
                    item["position_quality"] == "MEASURED"
                    for item in detailed_indications
                ),
                "representative_axial_position_count": sum(
                    item["position_quality"] == "RESULT_REPRESENTATIVE"
                    for item in detailed_indications
                ),
                "circumferential_angle_count": sum(
                    item["circumferential_angle_deg"] is not None
                    for item in detailed_indications
                ),
                "defect_length_count": sum(
                    item["defect_length_mm"] is not None
                    for item in detailed_indications
                ),
                "individual_wall_loss_count": sum(
                    item["wall_loss_percent"] is not None
                    for item in detailed_indications
                ),
                "individual_depth_count": sum(
                    item["wall_loss_depth_mm"] is not None
                    for item in detailed_indications
                ),
                "inner_surface_count": sum(
                    item["surface_side"] == "INNER" for item in detailed_indications
                ),
                "outer_surface_count": sum(
                    item["surface_side"] == "OUTER" for item in detailed_indications
                ),
                "unknown_surface_count": sum(
                    item["surface_side"] == "UNKNOWN" for item in detailed_indications
                ),
                "orientation_is_registered": map_orientation is not None,
                "physical_coordinates_complete": bool(tube_items)
                and verified_xy_count == len(tube_items),
                "layout_coordinates_complete": bool(approved_layout_rows),
            },
            "layout": {
                "shape": "SOURCE_LAYOUT_GRID" if approved_layout_rows else (
                    f"{effective_shape_code}_ESTIMATE" if selected_geometry else "CIRCULAR_ESTIMATE"
                ),
                "arrangement_basis": (
                    "APPROVED_LAYOUT_COORDINATES" if approved_layout_rows
                    else "PDF_GEOMETRY_SHAPE" if selected_geometry
                    else "CIRCULAR_FALLBACK"
                ),
                "pdf_geometry": pdf_geometry,
                "is_estimated": False if approved_layout_rows else virtual_count > 0,
                "estimated_position_count": virtual_count,
                "orientation": (
                    approved_layout_revision.source_section_name
                    if approved_layout_revision else map_orientation
                ),
                "initial_rotation_degrees": (
                    float(approved_layout_revision.rotation_degrees or 0)
                    if approved_layout_revision
                    else _tube_map_initial_rotation_degrees(map_orientation)
                ),
                "orientation_is_registered": (
                    True if approved_layout_revision else map_orientation is not None
                ),
                "approved_layout_applied": bool(approved_layout_rows),
                "layout_revision_id": (
                    approved_layout_revision.layout_revision_id
                    if approved_layout_revision else None
                ),
                "coordinate_unit": (
                    approved_layout_revision.source_coordinate_unit
                    if approved_layout_revision else None
                ),
                "physical_tube_count": expected_count,
                "layout_point_count": approved_layout_point_count,
                "count_basis": (
                    next(iter({
                        revision.layout_count_basis
                        for revision in approved_layout_revisions.values()
                    }))
                    if approved_layout_revisions and len({
                        revision.layout_count_basis
                        for revision in approved_layout_revisions.values()
                    }) == 1 else "MIXED"
                ),
                "coverage_status": (
                    next(iter({
                        revision.coverage_status
                        for revision in approved_layout_revisions.values()
                    }))
                    if approved_layout_revisions and len({
                        revision.coverage_status
                        for revision in approved_layout_revisions.values()
                    }) == 1 else "MIXED"
                ),
                "unresolved_count": sum(
                    int(revision.unresolved_count or 0)
                    for revision in approved_layout_revisions.values()
                ),
                "count_discrepancy_notes": [
                    revision.count_discrepancy_note
                    for revision in approved_layout_revisions.values()
                    if revision.count_discrepancy_note
                ],
            },
            "tubes": display_items,
        }


def list_issues(severity: str = "", status: str = "OPEN") -> list[tuple]:
    with session_scope(DB_PATH) as session:
        stmt = (
            select(DataQualityIssue, SourceDocument, IrisInspection)
            .join(SourceDocument, SourceDocument.source_document_id == DataQualityIssue.source_document_id)
            .outerjoin(IrisInspection, IrisInspection.iris_inspection_id == DataQualityIssue.iris_inspection_id)
            .order_by(DataQualityIssue.data_quality_issue_id.desc())
        )
        if severity:
            stmt = stmt.where(DataQualityIssue.severity == severity)
        if status:
            stmt = stmt.where(DataQualityIssue.status == status)
        return session.execute(stmt).all()


def resolve_quality_issue(issue_id: int, reviewer: str, note: str) -> bool:
    reviewer = str(reviewer or "").strip()
    note = str(note or "").strip()
    if not reviewer:
        raise ValueError("검토자 정보가 필요합니다.")
    if len(note) < 5:
        raise ValueError("처리 근거를 5자 이상 입력해 주세요.")
    with session_scope(DB_PATH) as session:
        issue = session.get(DataQualityIssue, int(issue_id))
        if not issue:
            return False
        if issue.status != "OPEN":
            raise ValueError("OPEN 상태의 품질 이슈만 종결할 수 있습니다.")
        issue.status = "RESOLVED"
        issue.reviewer = reviewer
        issue.reviewed_at = datetime.now()
        issue.resolution_note = note
        return True


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d")


EXCHANGER_MASTER_MANDATORY_FIELDS = (
    ("equipment_code", "자산번호"),
    ("equipment_tag", "설비태그"),
    ("exchanger_code", "열교환기번호"),
    ("equipment_name", "열교환기명"),
    ("service_name", "서비스명"),
    ("exchanger_type_code", "열교환기형식"),
    ("status", "현재 운전상태"),
    ("install_date", "열교환기 설치일자"),
    ("shell_material", "Shell 재질"),
    ("head_material", "Head 재질"),
    ("tube_material", "Tube 재질"),
    ("tube_outer_diameter_mm", "Tube 외경"),
    ("tube_nominal_thickness_mm", "Tube 공칭두께"),
    ("tube_length_mm", "Tube 길이"),
    ("tube_pitch_mm", "Tube Pitch"),
    ("pass_count", "Pass 수"),
    ("shell_fluid", "Shell측 유체"),
    ("head_fluid", "Head측 유체"),
    ("tube_fluid", "Tube측 유체"),
    ("tube_count", "총튜브수량"),
)

EXCHANGER_MASTER_MANDATORY_GROUPS = (
    (("shell_gasket_material", "head_gasket_material", "tube_gasket_material"), "Gasket 재질"),
    (("shell_concentration_wt_percent", "head_concentration_wt_percent", "tube_concentration_wt_percent"), "유체 농도"),
    (("shell_material_state", "head_material_state", "tube_material_state"), "유체 상태"),
)


def _validate_exchanger_master_mandatory(data: dict[str, Any]) -> None:
    has_unit = bool(data.get("unit_id")) or bool(data.get("plant_code") and data.get("unit_code"))
    missing = [] if has_unit else ["공장·공정"]
    missing.extend(
        label for key, label in EXCHANGER_MASTER_MANDATORY_FIELDS
        if str(data.get(key) or "").strip() == ""
    )
    missing.extend(
        label for keys, label in EXCHANGER_MASTER_MANDATORY_GROUPS
        if not any(str(data.get(key) or "").strip() for key in keys)
    )
    if missing:
        raise ValueError("마스터 필수 항목을 입력해 주세요: " + ", ".join(missing))

    for key, label in (
        ("tube_outer_diameter_mm", "Tube 외경"),
        ("tube_nominal_thickness_mm", "Tube 공칭두께"),
        ("tube_length_mm", "Tube 길이"),
        ("tube_pitch_mm", "Tube Pitch"),
        ("pass_count", "Pass 수"),
        ("tube_count", "총튜브수량"),
    ):
        if float(data[key]) <= 0:
            raise ValueError(f"{label}는 0보다 커야 합니다.")


def exchanger_form_data(exchanger_id: int | None = None) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        plants = session.scalars(select(Plant).order_by(Plant.plant_code)).all()
        units = session.execute(
            select(ProcessUnit, Plant)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .order_by(Plant.plant_code, ProcessUnit.unit_code)
        ).all()
        if exchanger_id is None:
            return {"plants": plants, "units": units, "editing": False,
                    "hx": None, "equipment": None, "unit": None, "plant": None,
                    "spec": None, "criteria": None, "bundle": None,
                    "shell_side": None, "head_side": None, "tube_side": None,
                    "tube_status_counts": {"db": 0, "in_service": 0, "plugged": 0}}
        master = session.execute(
            select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .where(HeatExchanger.heat_exchanger_id == exchanger_id)
        ).first()
        if not master:
            return None
        hx, equipment, unit, plant = master
        spec = session.scalar(
            select(HeatExchangerSpecRevision)
            .where(HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id,
                   HeatExchangerSpecRevision.is_current.is_(True))
            .order_by(HeatExchangerSpecRevision.revision_no.desc()).limit(1)
        )
        criteria = session.scalar(select(HeatExchangerManagementCriteria).where(
            HeatExchangerManagementCriteria.heat_exchanger_id == exchanger_id
        ))
        bundle = session.scalar(select(TubeBundle).where(
            TubeBundle.heat_exchanger_id == exchanger_id,
            TubeBundle.bundle_code == "MAIN",
        ).order_by(TubeBundle.lifecycle_no.desc()).limit(1))
        side_specs = {}
        if spec:
            side_specs = {
                item.side_code: item for item in session.scalars(
                    select(HeatExchangerSideSpec).where(
                        HeatExchangerSideSpec.spec_revision_id == spec.spec_revision_id
                    )
                ).all()
            }
        tube_counts = {"db": 0, "in_service": 0, "plugged": 0}
        if bundle:
            status_rows = session.execute(
                select(HeatExchangerTube.current_status, func.count(HeatExchangerTube.tube_id))
                .where(HeatExchangerTube.bundle_id == bundle.bundle_id)
                .group_by(HeatExchangerTube.current_status)
            ).all()
            for status, count in status_rows:
                tube_counts["db"] += count
                normalized = normalize_tube_status(status)
                if normalized in {"ACTIVE", "IN_SERVICE"}:
                    tube_counts["in_service"] += count
                elif normalized == "PLUGGED":
                    tube_counts["plugged"] += count
        return {"plants": plants, "units": units, "editing": True, "hx": hx,
                "equipment": equipment, "unit": unit, "plant": plant,
                "spec": spec, "criteria": criteria, "bundle": bundle,
                "shell_side": side_specs.get("SHELL"),
                "head_side": side_specs.get("HEAD"),
                "tube_side": side_specs.get("TUBE"),
                "tube_status_counts": tube_counts}


def _normalize_master_code(value: Any, label: str) -> str:
    code = str(value or "").strip().upper()
    if not code:
        raise ValueError(f"{label}는 필수입니다.")
    if len(code) > 50 or not re.fullmatch(r"[A-Z0-9][A-Z0-9_-]*", code):
        raise ValueError(f"{label}는 영문, 숫자, 하이픈(-), 밑줄(_)만 사용할 수 있습니다.")
    return code


def plant_line_master_data(plant_id: int | None = None,
                           unit_id: int | None = None) -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        plants = session.scalars(select(Plant).order_by(Plant.plant_code)).all()
        unit_rows = session.execute(
            select(ProcessUnit, Plant, func.count(HeatExchanger.heat_exchanger_id))
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .outerjoin(Equipment, Equipment.unit_id == ProcessUnit.unit_id)
            .outerjoin(HeatExchanger, HeatExchanger.equipment_id == Equipment.equipment_id)
            .group_by(ProcessUnit.unit_id, Plant.plant_id)
            .order_by(Plant.plant_code, ProcessUnit.unit_code)
        ).all()
        editing_plant = session.get(Plant, plant_id) if plant_id else None
        editing_unit = session.get(ProcessUnit, unit_id) if unit_id else None
        return {
            "plants": plants,
            "unit_rows": unit_rows,
            "editing_plant": editing_plant,
            "editing_unit": editing_unit,
        }


def plant_choices() -> list[Plant]:
    with session_scope(DB_PATH) as session:
        return list(session.scalars(select(Plant).order_by(Plant.plant_code)).all())


def production_line_choices() -> list[dict[str, Any]]:
    with session_scope(DB_PATH) as session:
        rows = session.execute(
            select(ProcessUnit, Plant)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .order_by(Plant.plant_code, ProcessUnit.unit_code)
        ).all()
        return [
            {
                "unit_id": unit.unit_id,
                "unit_code": unit.unit_code,
                "unit_name": unit.unit_name,
                "plant_code": plant.plant_code,
            }
            for unit, plant in rows
        ]


def save_plant(data: dict[str, Any], plant_id: int | None = None) -> dict[str, Any]:
    plant_code = _normalize_master_code(data.get("plant_code"), "공장 코드")
    if not re.fullmatch(r"P[1-9][0-9]*", plant_code):
        raise ValueError("생산공장 코드는 P1, P2, P3 … 형식으로 입력해 주세요.")
    plant_name = str(data.get("plant_name") or "").strip()
    if not plant_name:
        raise ValueError("공장명은 필수입니다.")
    with session_scope(DB_PATH) as session:
        conflict = session.scalar(select(Plant).where(
            Plant.plant_code == plant_code,
            Plant.plant_id != (plant_id or 0),
        ))
        if conflict:
            raise ValueError(f"공장 코드 {plant_code}가 이미 존재합니다.")
        plant = session.get(Plant, plant_id) if plant_id else Plant()
        if not plant:
            raise ValueError("수정할 공장을 찾을 수 없습니다.")
        if plant_id and plant.plant_code != plant_code:
            raise ValueError("공장 코드는 변경할 수 없습니다. Label(공장명)을 수정해 주세요.")
        if plant_id is None:
            session.add(plant)
        plant.plant_code = plant_code
        plant.plant_name = plant_name
        org = session.scalar(select(OrganizationCode).where(
            OrganizationCode.kind == "PLANT", OrganizationCode.code == plant_code))
        if org is None:
            org = OrganizationCode(kind="PLANT", code=plant_code, label=plant_name)
            session.add(org)
        org.label = plant_name
        plant.location = str(data.get("location") or "").strip() or None
        plant.description = str(data.get("description") or "").strip() or None
        session.flush()
        return {"plant_id": plant.plant_id, "plant_code": plant.plant_code,
                "created": plant_id is None}


def save_production_line(data: dict[str, Any], unit_id: int | None = None) -> dict[str, Any]:
    plant_id = _int(data.get("plant_id"))
    unit_code = _normalize_master_code(data.get("unit_code"), "생산라인 코드")
    unit_name = str(data.get("unit_name") or "").strip()
    if not plant_id:
        raise ValueError("소속 공장을 선택해 주세요.")
    if not unit_name:
        raise ValueError("생산라인명은 필수입니다.")
    with session_scope(DB_PATH) as session:
        plant = session.get(Plant, plant_id)
        if not plant:
            raise ValueError("선택한 공장을 찾을 수 없습니다.")
        unit = session.get(ProcessUnit, unit_id) if unit_id else ProcessUnit()
        if not unit:
            raise ValueError("수정할 생산라인을 찾을 수 없습니다.")
        if unit_id and unit.plant_id != plant_id:
            equipment_count = session.scalar(select(func.count()).select_from(Equipment).where(
                Equipment.unit_id == unit_id
            ))
            if equipment_count:
                raise ValueError("설비가 연결된 생산라인은 소속 공장을 변경할 수 없습니다.")
        conflict = session.scalar(select(ProcessUnit).where(
            ProcessUnit.plant_id == plant_id,
            ProcessUnit.unit_code == unit_code,
            ProcessUnit.unit_id != (unit_id or 0),
        ))
        if conflict:
            raise ValueError(f"{plant.plant_code} 공장에 생산라인 코드 {unit_code}가 이미 존재합니다.")
        if unit_id is None:
            session.add(unit)
        unit.plant_id = plant_id
        unit.unit_code = unit_code
        unit.unit_name = unit_name
        unit.description = str(data.get("description") or "").strip() or None
        session.flush()
        return {"unit_id": unit.unit_id, "unit_code": unit.unit_code,
                "plant_code": plant.plant_code, "created": unit_id is None}


def save_exchanger(data: dict[str, Any], exchanger_id: int | None = None,
                   *, enforce_master_mandatory: bool = False) -> dict[str, Any]:
    equipment_code = re.sub(r"\s+", "", str(data.get("equipment_code") or "").upper())
    requested_exchanger_code = re.sub(
        r"\s+", "", str(data.get("exchanger_code") or "").upper()
    )
    equipment_name = str(data.get("equipment_name") or equipment_code).strip()
    if not all((equipment_code, equipment_name)):
        raise ValueError("생산라인, 설비번호, 설비명은 필수입니다.")
    warning_loss = _float(data.get("warning_wall_loss_percent"))
    critical_loss = _float(data.get("critical_wall_loss_percent"))
    allowable_plugging = _float(data.get("allowable_plugging_percent"))
    if allowable_plugging is None:
        allowable_plugging = REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT
    if allowable_plugging not in REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS:
        raise ValueError("허용 Plugging 한도는 1%부터 20%까지 선택해 주세요.")
    if warning_loss is not None and critical_loss is not None and warning_loss > critical_loss:
        raise ValueError("주의 감육률은 위험 감육률보다 클 수 없습니다.")
    media_material_values = {
        "shell_fluid": str(data.get("shell_fluid") or "").strip() or None,
        "tube_fluid": str(data.get("tube_fluid") or "").strip() or None,
        "tube_material": str(data.get("tube_material") or "").strip() or None,
    }
    for key, limit, label in (
        ("shell_fluid", 200, "Shell 유체"),
        ("tube_fluid", 200, "Tube 유체"),
        ("tube_material", 100, "Tube 재질"),
    ):
        value = media_material_values[key]
        if value and len(value) > limit:
            raise ValueError(f"{label}는 {limit}자 이내로 입력해 주세요.")

    with session_scope(DB_PATH) as session:
        unit_id = _int(data.get("unit_id"))
        if unit_id:
            unit = session.get(ProcessUnit, unit_id)
            if not unit:
                raise ValueError("선택한 생산라인을 찾을 수 없습니다.")
            plant = session.get(Plant, unit.plant_id)
        else:
            # 기존 API/테스트 호환: 코드 조합으로 이미 등록된 생산라인만 조회한다.
            plant_code = str(data.get("plant_code") or "").strip().upper()
            unit_code_input = str(data.get("unit_code") or "").strip().upper()
            plant = session.scalar(select(Plant).where(Plant.plant_code == plant_code))
            unit = session.scalar(select(ProcessUnit).where(
                ProcessUnit.plant_id == plant.plant_id,
                ProcessUnit.unit_code == unit_code_input,
            )) if plant else None
            if not unit:
                raise ValueError("등록된 공장·생산라인을 선택해 주세요. 기준정보에서 먼저 등록할 수 있습니다.")
        unit_code = unit.unit_code
        alias_scope = f"{plant.plant_code}/{unit_code}"

        if enforce_master_mandatory:
            _validate_exchanger_master_mandatory(data)

        created = exchanger_id is None
        if created:
            duplicate = session.scalar(select(Equipment).where(
                Equipment.unit_id == unit.unit_id, Equipment.equipment_code == equipment_code
            ))
            if duplicate:
                raise ValueError(f"{unit_code} 생산라인에 {equipment_code} 설비가 이미 존재합니다.")
            equipment = Equipment(unit_id=unit.unit_id, equipment_code=equipment_code,
                                  equipment_name=equipment_name, equipment_type="HEAT_EXCHANGER")
            session.add(equipment); session.flush()
            hx = HeatExchanger(equipment_id=equipment.equipment_id)
            session.add(hx); session.flush()
        else:
            hx = session.get(HeatExchanger, exchanger_id)
            if not hx:
                raise ValueError("수정할 열교환기를 찾을 수 없습니다.")
            equipment = session.scalar(select(Equipment).where(Equipment.equipment_id == hx.equipment_id).with_for_update())
            expected_update = data.get("expected_updated_at")
            if enforce_master_mandatory and expected_update is None:
                raise ValueError("The edit form is stale. Reload before saving.")
            actual_update = equipment.updated_at.isoformat() if equipment.updated_at else ""
            if expected_update is not None and str(expected_update) != actual_update:
                raise ValueError("Another user changed this equipment. Reload before saving.")
            duplicate = session.scalar(select(Equipment).where(
                Equipment.unit_id == unit.unit_id,
                Equipment.equipment_code == equipment_code,
                Equipment.equipment_id != equipment.equipment_id,
            ))
            if duplicate:
                raise ValueError(f"{unit_code} 생산라인에 {equipment_code} 설비가 이미 존재합니다.")
            old_code = equipment.equipment_code
            if old_code != equipment_code:
                normalized = re.sub(r"\s+", "", old_code.upper())
                alias = session.scalar(select(EquipmentAlias).where(
                    EquipmentAlias.source_system == "MANUAL_HISTORY",
                    EquipmentAlias.source_unit == alias_scope,
                    EquipmentAlias.normalized_alias_code == normalized,
                ))
                if not alias:
                    session.add(EquipmentAlias(
                        heat_exchanger_id=hx.heat_exchanger_id,
                        source_system="MANUAL_HISTORY", source_unit=alias_scope,
                        alias_code=old_code, normalized_alias_code=normalized, is_approved=True,
                    ))

        equipment.unit_id = unit.unit_id
        if "organization_process_id" in data:
            raw_org_id = str(data.get("organization_process_id") or "").strip()
            if raw_org_id:
                try:
                    org_process = session.get(OrganizationCode, int(raw_org_id))
                except ValueError:
                    raise ValueError("등록된 조직 공정을 선택해 주세요.")
                org_team = session.get(OrganizationCode, org_process.parent_id) if org_process and org_process.kind == "PROCESS" else None
                org_plant = session.get(OrganizationCode, org_team.parent_id) if org_team and org_team.kind == "TEAM" else None
                if not org_plant or org_plant.code != plant.plant_code:
                    raise ValueError("선택한 공정이 열교환기의 소속 공장과 일치하지 않습니다.")
                equipment.production_team_code = org_team.code
                equipment.process_code = org_process.code
            elif equipment.production_team_code or equipment.process_code:
                raise ValueError("등록된 조직 공정을 선택해 주세요.")
        equipment.equipment_code = equipment_code
        if created or "equipment_tag" in data:
            equipment.equipment_tag = str(data.get("equipment_tag") or "").strip() or None
        equipment.equipment_name = equipment_name
        equipment.equipment_type = "HEAT_EXCHANGER"
        equipment.status = data.get("status") or "OPERATING"
        equipment.criticality_grade = data.get("criticality_grade") or None
        if "process_criticality" in data:
            process_criticality = str(data.get("process_criticality") or "").upper()
            if process_criticality not in {"NORMAL", "CRITICAL"}:
                raise ValueError("공정 중요도는 일반 또는 Critical 중에서 선택해 주세요.")
            equipment.is_critical = process_criticality == "CRITICAL"
        elif "is_critical" in data:
            equipment.is_critical = str(data.get("is_critical", "")).lower() in {
                "1", "true", "on", "yes"
            }
        elif created:
            equipment.is_critical = False
        equipment.owner_department = data.get("owner_department") or None
        equipment.owner_name = data.get("owner_name") or None
        equipment.location_desc = data.get("location_desc") or None
        equipment.manufacturer = data.get("manufacturer") or None
        equipment.model_no = data.get("model_no") or None
        equipment.serial_no = data.get("serial_no") or None
        install_date = _date(data.get("install_date"))
        equipment.install_date = install_date
        equipment.manufacturing_date = install_date - timedelta(days=3) if install_date else None
        equipment.commissioning_date = install_date
        equipment.remarks = data.get("remarks") or None
        supplied_type_code = str(data.get("exchanger_type_code") or "").strip().upper()
        raw_type = data.get("exchanger_type_raw") or data.get("exchanger_type")
        if supplied_type_code in TYPE_NAMES and supplied_type_code != "ETC" and not raw_type:
            raw_type = TYPE_NAMES[supplied_type_code]
        type_mapping = standardize_exchanger_type(raw_type)
        if supplied_type_code in TYPE_NAMES and supplied_type_code != "ETC":
            type_mapping = type_mapping._replace(
                code=supplied_type_code,
                name=TYPE_NAMES[supplied_type_code],
                status="MAPPED",
            )
        hx.exchanger_type = type_mapping.raw
        hx.exchanger_type_code = type_mapping.code
        hx.exchanger_type_name = type_mapping.name
        hx.exchanger_type_raw = type_mapping.raw
        hx.type_mapping_status = type_mapping.status
        hx.service_name = data.get("service_name") or None
        hx.iris_applicability = data.get("iris_applicability") or "UNKNOWN"
        hx.inspection_lifecycle_status = data.get("inspection_lifecycle_status") or hx.inspection_lifecycle_status or "NEVER_INSPECTED"
        hx.remarks = data.get("hx_remarks") or None

        bundle = session.scalar(select(TubeBundle).where(
            TubeBundle.heat_exchanger_id == hx.heat_exchanger_id,
            TubeBundle.bundle_code == "MAIN",
        ).order_by(TubeBundle.lifecycle_no.desc()).limit(1))
        if not bundle:
            bundle = TubeBundle(heat_exchanger_id=hx.heat_exchanger_id,
                                bundle_code="MAIN", lifecycle_no=1, status="ACTIVE")
            session.add(bundle)
        bundle.expected_tube_count = _int(data.get("tube_count"))
        bundle.orientation = data.get("bundle_orientation") or None
        bundle.pass_no = _int(data.get("pass_count"))

        spec_values = {
            "design_pressure": _float(data.get("design_pressure")),
            "design_temperature": _float(data.get("design_temperature")),
            "operation_pressure": _float(data.get("operation_pressure")),
            "operation_temperature": _float(data.get("operation_temperature")),
            "shell_material": data.get("shell_material") or None,
            "tube_material": media_material_values["tube_material"],
            "tube_count": _int(data.get("tube_count")),
            "tube_outer_diameter_mm": _float(data.get("tube_outer_diameter_mm")),
            "tube_nominal_thickness_mm": _float(data.get("tube_nominal_thickness_mm")),
            "tube_length_mm": _float(data.get("tube_length_mm")),
            "bundle_type": data.get("bundle_type") or None,
            "pass_count": _int(data.get("pass_count")),
            "tube_pitch_mm": _float(data.get("tube_pitch_mm")),
            "heat_transfer_area_m2": _float(data.get("heat_transfer_area_m2")),
            "shell_fluid": media_material_values["shell_fluid"],
            "tube_fluid": media_material_values["tube_fluid"],
            "drawing_no": data.get("drawing_no") or None,
            "datasheet_no": data.get("datasheet_no") or None,
        }
        current_spec = session.scalar(select(HeatExchangerSpecRevision).where(
            HeatExchangerSpecRevision.heat_exchanger_id == hx.heat_exchanger_id,
            HeatExchangerSpecRevision.is_current.is_(True),
        ).order_by(HeatExchangerSpecRevision.revision_no.desc()).limit(1))
        spec_values["exchanger_code"] = (
            requested_exchanger_code
            or (current_spec.exchanger_code if current_spec else equipment.equipment_code)
        )
        current_sides = {}
        if current_spec:
            current_sides = {
                item.side_code: item for item in session.scalars(
                    select(HeatExchangerSideSpec).where(
                        HeatExchangerSideSpec.spec_revision_id == current_spec.spec_revision_id
                    )
                ).all()
            }

        def side_value(side_code: str, field: str, form_key: str,
                       fallback: Any = None) -> Any:
            if form_key in data:
                raw = data.get(form_key)
                if field == "concentration_wt_percent":
                    return _float(raw)
                return str(raw or "").strip() or None
            current_side = current_sides.get(side_code)
            return getattr(current_side, field) if current_side else fallback

        side_values = {
            "SHELL": {
                "fluid": media_material_values["shell_fluid"],
                "material": spec_values["shell_material"],
                "gasket_material": side_value("SHELL", "gasket_material", "shell_gasket_material"),
                "concentration_wt_percent": side_value("SHELL", "concentration_wt_percent", "shell_concentration_wt_percent"),
                "material_state": side_value("SHELL", "material_state", "shell_material_state"),
            },
            "HEAD": {
                "fluid": side_value("HEAD", "fluid", "head_fluid"),
                "material": side_value("HEAD", "material", "head_material"),
                "gasket_material": side_value("HEAD", "gasket_material", "head_gasket_material"),
                "concentration_wt_percent": side_value("HEAD", "concentration_wt_percent", "head_concentration_wt_percent"),
                "material_state": side_value("HEAD", "material_state", "head_material_state"),
            },
            "TUBE": {
                "fluid": media_material_values["tube_fluid"],
                "material": spec_values["tube_material"],
                "gasket_material": side_value("TUBE", "gasket_material", "tube_gasket_material"),
                "concentration_wt_percent": side_value("TUBE", "concentration_wt_percent", "tube_concentration_wt_percent"),
                "material_state": side_value("TUBE", "material_state", "tube_material_state"),
            },
        }
        side_changed = current_spec is None or any(
            current_sides.get(side_code) is None
            or any(getattr(current_sides[side_code], key) != value for key, value in values.items())
            for side_code, values in side_values.items()
        )
        changed = current_spec is None or side_changed or any(
            getattr(current_spec, key) != value for key, value in spec_values.items()
        )
        if changed:
            revision_no = 1
            if current_spec:
                current_spec.is_current = False
                current_spec.effective_to = datetime.now()
                revision_no = current_spec.revision_no + 1
            new_spec = HeatExchangerSpecRevision(
                heat_exchanger_id=hx.heat_exchanger_id, revision_no=revision_no,
                revision_code=str(revision_no),
                effective_from=datetime.now(), is_current=True,
                raw_json=json.dumps({"source": "manual_form"}, ensure_ascii=False),
                **spec_values,
            )
            session.add(new_spec)
            session.flush()
            for side_code, values in side_values.items():
                session.add(HeatExchangerSideSpec(
                    spec_revision_id=new_spec.spec_revision_id,
                    side_code=side_code,
                    raw_json=json.dumps({"source": "manual_form"}, ensure_ascii=False),
                    **values,
                ))

        criteria = session.scalar(select(HeatExchangerManagementCriteria).where(
            HeatExchangerManagementCriteria.heat_exchanger_id == hx.heat_exchanger_id
        ))
        if not criteria:
            criteria = HeatExchangerManagementCriteria(heat_exchanger_id=hx.heat_exchanger_id)
            session.add(criteria)
        criteria.allowable_plugging_percent = allowable_plugging
        criteria.warning_wall_loss_percent = warning_loss
        criteria.critical_wall_loss_percent = critical_loss
        criteria.minimum_wall_thickness_mm = _float(data.get("minimum_wall_thickness_mm"))
        criteria.inspection_cycle_months = _int(data.get("inspection_cycle_months"))
        criteria.turnaround_cycle_years = _int(data.get("turnaround_cycle_years"))
        criteria.last_turnaround_year = _int(data.get("last_turnaround_year"))
        criteria.next_turnaround_year = _int(data.get("next_turnaround_year"))
        criteria.criteria_note = data.get("criteria_note") or None
        session.flush()
        return {"created": created, "heat_exchanger_id": hx.heat_exchanger_id,
                "equipment_code": equipment.equipment_code,
                "exchanger_code": spec_values["exchanger_code"],
                "specification_revision_created": changed}


def save_exchanger_media_material(exchanger_id: int,
                                   data: dict[str, Any]) -> dict[str, Any]:
    values = {
        "shell_fluid": str(data.get("shell_fluid") or "").strip() or None,
        "tube_fluid": str(data.get("tube_fluid") or "").strip() or None,
        "tube_material": str(data.get("tube_material") or "").strip() or None,
    }
    limits = {"shell_fluid": 200, "tube_fluid": 200, "tube_material": 100}
    labels = {"shell_fluid": "Shell 유체", "tube_fluid": "Tube 유체",
              "tube_material": "Tube 재질"}
    for key, value in values.items():
        if value and len(value) > limits[key]:
            raise ValueError(f"{labels[key]}는 {limits[key]}자 이내로 입력해 주세요.")

    copy_fields = (
        "exchanger_code", "design_pressure", "design_temperature", "operation_pressure",
        "operation_temperature", "shell_material", "tube_material", "tube_count",
        "tube_outer_diameter_mm", "tube_nominal_thickness_mm", "tube_length_mm",
        "bundle_type", "pass_count", "tube_pitch_mm", "heat_transfer_area_m2",
        "shell_fluid", "tube_fluid", "drawing_no", "datasheet_no",
    )
    with session_scope(DB_PATH) as session:
        exchanger = session.get(HeatExchanger, exchanger_id)
        if not exchanger:
            raise ValueError("수정할 열교환기를 찾을 수 없습니다.")
        current = session.scalar(
            select(HeatExchangerSpecRevision)
            .where(HeatExchangerSpecRevision.heat_exchanger_id == exchanger_id,
                   HeatExchangerSpecRevision.is_current.is_(True))
            .order_by(HeatExchangerSpecRevision.revision_no.desc()).limit(1)
        )
        if current and all(getattr(current, key) == value for key, value in values.items()):
            return {"heat_exchanger_id": exchanger_id, "changed": False,
                    "revision_no": current.revision_no}

        spec_values = {
            key: getattr(current, key) if current else None
            for key in copy_fields
        }
        spec_values.update(values)
        revision_no = 1
        if current:
            current.is_current = False
            current.effective_to = datetime.now()
            revision_no = current.revision_no + 1
        session.add(HeatExchangerSpecRevision(
            heat_exchanger_id=exchanger_id,
            revision_no=revision_no,
            revision_code=str(revision_no),
            effective_from=datetime.now(),
            is_current=True,
            raw_json=json.dumps({"source": "media_material_quick_edit"}, ensure_ascii=False),
            **spec_values,
        ))
        return {"heat_exchanger_id": exchanger_id, "changed": True,
                "revision_no": revision_no}


def create_exchanger(data: dict[str, Any]) -> dict[str, Any]:
    return save_exchanger(data)


def _system_grade(max_loss: float | None, warning: float = 20.0,
                  critical: float = 40.0) -> str:
    if max_loss is None:
        return "N/A"
    if max_loss >= critical:
        return "D"
    if max_loss >= warning:
        return "C"
    if max_loss >= warning / 2:
        return "B"
    return "A"


def inspections_data(search: str = "", grade: str = "") -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        stmt = (select(IrisInspection, Equipment, ProcessUnit, Plant,
                       HeatExchangerManagementCriteria, HeatExchangerSpecRevision)
                .join(HeatExchanger, HeatExchanger.heat_exchanger_id == IrisInspection.heat_exchanger_id)
                .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
                .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
                .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
                .outerjoin(
                    HeatExchangerSpecRevision,
                    and_(
                        HeatExchangerSpecRevision.heat_exchanger_id
                        == HeatExchanger.heat_exchanger_id,
                        HeatExchangerSpecRevision.is_current.is_(True),
                    ),
                )
                .outerjoin(HeatExchangerManagementCriteria,
                           HeatExchangerManagementCriteria.heat_exchanger_id == HeatExchanger.heat_exchanger_id)
                .order_by(IrisInspection.report_date.desc(), IrisInspection.iris_inspection_id.desc()))
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(or_(Equipment.equipment_code.ilike(term),
                                  HeatExchangerSpecRevision.exchanger_code.ilike(term),
                                  Equipment.equipment_name.ilike(term),
                                  IrisInspection.report_number.ilike(term)))
        rows = []
        exchanger_codes: dict[int, str | None] = {}
        for inspection, equipment, unit, plant, criteria, current_spec in session.execute(stmt):
            warning = criteria.warning_wall_loss_percent if criteria and criteria.warning_wall_loss_percent is not None else 20.0
            critical = criteria.critical_wall_loss_percent if criteria and criteria.critical_wall_loss_percent is not None else 40.0
            item_grade = _system_grade(inspection.reported_maximum_wall_loss_percent, warning, critical)
            if not grade or item_grade == grade:
                rows.append({"inspection": inspection, "equipment": equipment, "unit": unit,
                             "plant": plant, "grade": item_grade})
                if inspection.heat_exchanger_id not in exchanger_codes:
                    exchanger_codes[inspection.heat_exchanger_id] = (
                        current_spec.exchanger_code if current_spec else None
                    )
        return {"rows": rows, "search": search, "grade": grade,
                "exchanger_codes": exchanger_codes}


def tube_inspection_history_data(exchanger_id: Any = None, year: Any = None,
                                 tube_no: str = "", page: Any = 1,
                                 per_page: int = 100, sort_by: str = "exchanger",
                                 sort_dir: str = "asc") -> dict[str, Any]:
    """List tube results by exchanger, inspection year, and tube number."""
    try:
        selected_exchanger_id = int(exchanger_id) if str(exchanger_id or "").strip() else None
    except (TypeError, ValueError):
        selected_exchanger_id = None
    try:
        selected_year = int(year) if str(year or "").strip() else None
    except (TypeError, ValueError):
        selected_year = None
    try:
        selected_page = max(1, int(page))
    except (TypeError, ValueError):
        selected_page = 1
    tube_search = str(tube_no or "").strip()
    page_size = max(20, min(int(per_page), 200))
    selected_sort = str(sort_by or "exchanger").strip().lower()
    if selected_sort not in {"exchanger", "tube"}:
        selected_sort = "exchanger"
    selected_direction = str(sort_dir or "asc").strip().lower()
    if selected_direction not in {"asc", "desc"}:
        selected_direction = "asc"

    with session_scope(DB_PATH) as session:
        stmt = (
            select(
                IrisTubeResult, IrisInspection, InspectionCampaign,
                HeatExchangerTube, TubeBundle, InspectionScope,
                HeatExchanger, Equipment, ProcessUnit, Plant,
                HeatExchangerSpecRevision,
            )
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .join(InspectionCampaign, InspectionCampaign.campaign_id == IrisInspection.campaign_id)
            .join(HeatExchangerTube, HeatExchangerTube.tube_id == IrisTubeResult.tube_id)
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == TubeBundle.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .outerjoin(InspectionScope, InspectionScope.inspection_scope_id == IrisInspection.inspection_scope_id)
            .outerjoin(
                HeatExchangerSpecRevision,
                and_(
                    HeatExchangerSpecRevision.heat_exchanger_id == HeatExchanger.heat_exchanger_id,
                    HeatExchangerSpecRevision.is_current.is_(True),
                ),
            )
        )
        if selected_exchanger_id is not None:
            stmt = stmt.where(HeatExchanger.heat_exchanger_id == selected_exchanger_id)
        if selected_year is not None:
            stmt = stmt.where(InspectionCampaign.campaign_year == selected_year)
        if tube_search:
            stmt = stmt.where(or_(
                HeatExchangerTube.tube_no.ilike(f"%{tube_search}%"),
                IrisTubeResult.source_tube_id.ilike(f"%{tube_search}%"),
            ))

        total_count = session.scalar(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        ) or 0
        page_count = max(1, math.ceil(total_count / page_size))
        selected_page = min(selected_page, page_count)
        exchanger_sort = func.coalesce(
            HeatExchangerSpecRevision.exchanger_code,
            Equipment.equipment_tag,
            Equipment.equipment_code,
        )
        missing_number = 999999 if selected_direction == "asc" else -1
        tube_row_sort = func.coalesce(
            HeatExchangerTube.row_no, IrisTubeResult.source_row, missing_number
        )
        tube_column_sort = func.coalesce(
            HeatExchangerTube.column_no, IrisTubeResult.source_column, missing_number
        )
        direction = (lambda expression: expression.desc()) if selected_direction == "desc" else (lambda expression: expression.asc())
        if selected_sort == "tube":
            ordering = (
                direction(tube_row_sort), direction(tube_column_sort),
                direction(HeatExchangerTube.tube_no), exchanger_sort.asc(),
                InspectionCampaign.campaign_year.desc(),
            )
        else:
            ordering = (
                direction(exchanger_sort), InspectionCampaign.campaign_year.desc(),
                tube_row_sort.asc(), tube_column_sort.asc(),
                HeatExchangerTube.tube_no.asc(),
            )
        stmt = stmt.order_by(
            *ordering, IrisInspection.report_sequence, IrisTubeResult.iris_tube_result_id
        ).offset((selected_page - 1) * page_size).limit(page_size)

        rows = []
        for (result, inspection, campaign, tube, bundle, scope, exchanger,
             equipment, unit, plant, current_spec) in session.execute(stmt):
            inspection_date = _effective_inspection_date(inspection)
            rows.append({
                "result": result,
                "inspection": inspection,
                "inspection_year": campaign.campaign_year,
                "inspection_date": inspection_date,
                "tube": tube,
                "bundle_code": bundle.bundle_code,
                "scope_code": scope.scope_code if scope else (inspection.source_scope_code or "ALL"),
                "heat_exchanger_id": exchanger.heat_exchanger_id,
                "equipment_code": equipment.equipment_code,
                "equipment_name": equipment.equipment_name,
                "exchanger_code": (
                    current_spec.exchanger_code if current_spec and current_spec.exchanger_code
                    else equipment.equipment_tag or equipment.equipment_code
                ),
                "unit_code": unit.unit_code,
                "plant_code": plant.plant_code,
            })

        exchanger_rows = session.execute(
            select(HeatExchanger, Equipment, HeatExchangerSpecRevision)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(TubeBundle, TubeBundle.heat_exchanger_id == HeatExchanger.heat_exchanger_id)
            .join(HeatExchangerTube, HeatExchangerTube.bundle_id == TubeBundle.bundle_id)
            .join(IrisTubeResult, IrisTubeResult.tube_id == HeatExchangerTube.tube_id)
            .outerjoin(
                HeatExchangerSpecRevision,
                and_(
                    HeatExchangerSpecRevision.heat_exchanger_id == HeatExchanger.heat_exchanger_id,
                    HeatExchangerSpecRevision.is_current.is_(True),
                ),
            )
            .distinct()
        ).all()
        exchangers = sorted(({
            "heat_exchanger_id": exchanger.heat_exchanger_id,
            "label": (
                current_spec.exchanger_code if current_spec and current_spec.exchanger_code
                else equipment.equipment_tag or equipment.equipment_code
            ),
            "equipment_name": equipment.equipment_name,
        } for exchanger, equipment, current_spec in exchanger_rows), key=lambda item: item["label"])
        selected_exchanger = next(
            (
                item for item in exchangers
                if item["heat_exchanger_id"] == selected_exchanger_id
            ),
            None,
        )
        wall_loss_values = [
            float(row["result"].wall_loss_percent)
            for row in rows
            if row["result"].wall_loss_percent is not None
        ]
        history_summary = {
            "visible_tube_count": len({row["tube"].tube_id for row in rows}),
            "visible_year_count": len({row["inspection_year"] for row in rows}),
            "valid_result_count": sum(
                row["result"].quality_status == "VALID" for row in rows
            ),
            "maximum_wall_loss_percent": max(wall_loss_values, default=None),
        }
        years = list(session.scalars(
            select(InspectionCampaign.campaign_year)
            .join(IrisInspection, IrisInspection.campaign_id == InspectionCampaign.campaign_id)
            .join(IrisTubeResult, IrisTubeResult.iris_inspection_id == IrisInspection.iris_inspection_id)
            .distinct().order_by(InspectionCampaign.campaign_year.desc())
        ).all())
        return {
            "rows": rows,
            "exchangers": exchangers,
            "selected_exchanger": selected_exchanger,
            "history_summary": history_summary,
            "years": years,
            "selected_exchanger_id": selected_exchanger_id,
            "selected_year": selected_year,
            "tube_no": tube_search,
            "sort_by": selected_sort,
            "sort_dir": selected_direction,
            "page": selected_page,
            "page_count": page_count,
            "per_page": page_size,
            "total_count": total_count,
        }


def inspection_plans_data(
    status: str = "",
    selected_exchanger_id: Any = None,
    priority_source: str = "",
) -> dict[str, Any]:
    try:
        selected_id = int(selected_exchanger_id or 0)
    except (TypeError, ValueError):
        selected_id = 0
    priority_source = str(priority_source or "").strip().lower()
    priority_review = (
        confirmed_hotspot_priorities(DB_PATH, ML_REVIEW_DB_PATH, heat_exchanger_id=selected_id)
        if selected_id else {
            "enabled": False, "rows": [], "priority": "NORMAL", "run_id": None,
            "confirmed_count": 0, "candidate_tube_count": 0, "in_service_count": 0,
        }
    )
    priority_tube_ids = {
        int(row["tube_id"]) for row in priority_review["rows"]
        if row["is_in_service"]
    } if priority_source == "confirmed_hotspot" else set()
    with session_scope(DB_PATH) as session:
        stmt = (select(InspectionPlan, HeatExchanger, Equipment, ProcessUnit, Plant)
                .join(HeatExchanger, HeatExchanger.heat_exchanger_id == InspectionPlan.heat_exchanger_id)
                .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
                .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
                .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
                .order_by(InspectionPlan.planned_date, InspectionPlan.inspection_plan_id))
        if status:
            stmt = stmt.where(InspectionPlan.status == status)
        exchangers = session.execute(
            select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .order_by(Plant.plant_code, ProcessUnit.unit_code, Equipment.equipment_code)
        ).all()
        plans = session.execute(stmt).all()
        plan_ids = [plan.inspection_plan_id for plan, *_ in plans]
        target_rows = session.scalars(
            select(InspectionPlanTubeTarget)
            .where(InspectionPlanTubeTarget.inspection_plan_id.in_(plan_ids))
            .order_by(
                InspectionPlanTubeTarget.inspection_plan_id,
                InspectionPlanTubeTarget.row_no_at_selection,
                InspectionPlanTubeTarget.column_no_at_selection,
                InspectionPlanTubeTarget.tube_no_at_selection,
            )
        ).all() if plan_ids else []
        targets_by_plan: dict[int, list[InspectionPlanTubeTarget]] = {}
        for target in target_rows:
            targets_by_plan.setdefault(target.inspection_plan_id, []).append(target)
        target_summary = {}
        for plan_id in plan_ids:
            plan_targets = targets_by_plan.get(plan_id, [])
            target_summary[plan_id] = {
                "total": len(plan_targets),
                "inspected": sum(row.target_status == "INSPECTED" for row in plan_targets),
                "excluded": sum(row.target_status == "EXCLUDED" for row in plan_targets),
                "pending": sum(row.target_status == "TARGETED" for row in plan_targets),
            }
        users_by_id = {
            user.user_id: user for user in session.scalars(select(AppUser)).all()
        }
        selected_tubes = []
        tube_status_counts = {"IN_SERVICE": 0, "PLUGGED": 0}
        if selected_id:
            selected_tubes = session.execute(
                select(HeatExchangerTube, TubeBundle)
                .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
                .where(TubeBundle.heat_exchanger_id == selected_id)
                .order_by(
                    TubeBundle.bundle_code,
                    HeatExchangerTube.row_no,
                    HeatExchangerTube.column_no,
                    HeatExchangerTube.tube_no,
                )
            ).all()
            for tube, _bundle in selected_tubes:
                normalized = normalize_tube_status(tube.current_status)
                tube_status_counts[normalized] = tube_status_counts.get(normalized, 0) + 1
        return {
            "plans": plans,
            "exchangers": exchangers,
            "status_filter": status,
            "today": datetime.now(),
            "selected_exchanger_id": selected_id,
            "selected_tubes": selected_tubes,
            "tube_status_counts": tube_status_counts,
            "targets_by_plan": targets_by_plan,
            "target_summary": target_summary,
            "users_by_id": users_by_id,
            "priority_source": priority_source,
            "priority_review": priority_review,
            "priority_tube_ids": priority_tube_ids,
        }


def inspection_priority_for_exchanger(exchanger_id: int) -> dict[str, Any]:
    return confirmed_hotspot_priorities(
        DB_PATH,
        ML_REVIEW_DB_PATH,
        heat_exchanger_id=int(exchanger_id),
    )


def save_inspection_plan(data: dict[str, Any], requested_by_user_id: int | None = None) -> int:
    exchanger_id = _int(data.get("heat_exchanger_id"))
    planned_date = _date(data.get("planned_date"))
    if not exchanger_id or not planned_date:
        raise ValueError("열교환기와 예정일은 필수입니다.")
    raw_tube_ids = data.get("tube_ids") or []
    if isinstance(raw_tube_ids, (str, int)):
        raw_tube_ids = [raw_tube_ids]
    try:
        tube_ids = sorted({int(value) for value in raw_tube_ids if str(value).strip()})
    except (TypeError, ValueError) as exc:
        raise ValueError("검사 대상 Tube 값이 올바르지 않습니다.") from exc
    if not tube_ids:
        raise ValueError("사용 중인 검사 대상 Tube를 1개 이상 선택해 주세요.")
    with session_scope(DB_PATH) as session:
        hx = session.get(HeatExchanger, exchanger_id)
        if not hx:
            raise ValueError("열교환기를 찾을 수 없습니다.")
        if requested_by_user_id:
            requester = session.get(AppUser, requested_by_user_id)
            if not requester or not requester.is_active:
                raise ValueError("활성 신청자 계정을 확인할 수 없습니다.")
        tubes = session.execute(
            select(HeatExchangerTube, TubeBundle)
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .where(
                TubeBundle.heat_exchanger_id == exchanger_id,
                HeatExchangerTube.tube_id.in_(tube_ids),
            )
        ).all()
        if len(tubes) != len(tube_ids):
            raise ValueError("선택한 Tube 중 대상 열교환기에 속하지 않는 항목이 있습니다.")
        unavailable = [
            tube.tube_no for tube, _bundle in tubes
            if normalize_tube_status(tube.current_status) != "IN_SERVICE"
        ]
        if unavailable:
            raise ValueError(
                "사용 중(IN_SERVICE) Tube만 선택할 수 있습니다: "
                + ", ".join(unavailable[:10])
            )
        plan = InspectionPlan(
            heat_exchanger_id=exchanger_id, planned_date=planned_date,
            application_date=datetime.now(),
            application_due_date=inspection_plan_application_date(planned_date),
            inspection_method=str(data.get("inspection_method") or "IRIS").strip().upper(),
            scope_code=str(data.get("scope_code") or "ALL").strip().upper(),
            status="SCHEDULED", priority=data.get("priority") or "NORMAL",
            notes=str(data.get("notes") or "").strip() or None,
            requested_by_user_id=requested_by_user_id,
        )
        session.add(plan); session.flush()
        for tube, bundle in tubes:
            session.add(InspectionPlanTubeTarget(
                inspection_plan_id=plan.inspection_plan_id,
                tube_id=tube.tube_id,
                bundle_id_at_selection=bundle.bundle_id,
                tube_no_at_selection=tube.tube_no,
                row_no_at_selection=tube.row_no,
                column_no_at_selection=tube.column_no,
                tube_status_at_selection=normalize_tube_status(tube.current_status),
                selected_by_user_id=requested_by_user_id,
            ))
        session.add(InspectionPlanEvent(
            inspection_plan_id=plan.inspection_plan_id,
            previous_status=None,
            new_status="SCHEDULED",
            actor_user_id=requested_by_user_id,
            actor_role="APPLICANT",
            reason="검사일정 및 대상 Tube 등록",
            target_tube_count=len(tubes),
        ))
        if hx.inspection_lifecycle_status in {"NEVER_INSPECTED", "UNKNOWN"}:
            hx.inspection_lifecycle_status = "PLANNED"
        return plan.inspection_plan_id


def update_inspection_plan_status(
    plan_id: int,
    status: str,
    *,
    actor_user_id: int | None = None,
    actor_is_admin: bool = False,
    reason: str = "",
) -> bool:
    allowed = {"SCHEDULED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
    transitions = {
        "SCHEDULED": {"APPROVED", "CANCELLED"},
        "APPROVED": {"IN_PROGRESS", "CANCELLED"},
        "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
    }
    status = str(status).upper()
    if status not in allowed:
        raise ValueError("지원하지 않는 검사계획 상태입니다.")
    with session_scope(DB_PATH) as session:
        plan = session.get(InspectionPlan, plan_id)
        if not plan:
            return False
        previous_status = str(plan.status or "SCHEDULED").upper()
        if status == previous_status:
            return True
        if status not in transitions.get(previous_status, set()):
            raise ValueError(f"검사계획 상태는 {previous_status}에서 {status}(으)로 변경할 수 없습니다.")
        targets = session.scalars(select(InspectionPlanTubeTarget).where(
            InspectionPlanTubeTarget.inspection_plan_id == plan_id
        )).all()
        if status == "APPROVED":
            if not actor_is_admin:
                raise ValueError("검사계획 승인은 관리자만 처리할 수 있습니다.")
            if not targets:
                raise ValueError("검사 대상 Tube가 없는 계획은 승인할 수 없습니다.")
            invalid = [row.tube_no_at_selection for row in targets if row.tube_status_at_selection != "IN_SERVICE"]
            if invalid:
                raise ValueError("사용 중이 아닌 Tube가 포함되어 계획을 승인할 수 없습니다.")
            # 신청 후 승인 전까지 튜브 상태가 바뀔 수 있으므로 현재 상태를 다시 검증한다.
            current_tubes = session.scalars(select(HeatExchangerTube).where(
                HeatExchangerTube.tube_id.in_([row.tube_id for row in targets])
            )).all()
            current_by_id = {tube.tube_id: tube for tube in current_tubes}
            unavailable = [
                row.tube_no_at_selection
                for row in targets
                if row.tube_id not in current_by_id
                or normalize_tube_status(current_by_id[row.tube_id].current_status) != "IN_SERVICE"
            ]
            if unavailable:
                tube_labels = ", ".join(unavailable[:10])
                suffix = " 외" if len(unavailable) > 10 else ""
                raise ValueError(
                    f"현재 사용 중이 아닌 대상 튜브({tube_labels}{suffix})가 있어 승인할 수 없습니다."
                )
            plan.approved_by_user_id = actor_user_id
            plan.target_locked_at = datetime.now()
            plan.decision_note = str(reason or "").strip() or None
        if status == "IN_PROGRESS":
            plan.inspection_started_at = datetime.now()
        if status == "COMPLETED":
            pending_count = sum(row.target_status == "TARGETED" for row in targets)
            if pending_count:
                raise ValueError(f"미검사 대상 Tube {pending_count}건을 먼저 처리해 주세요.")
            plan.inspection_completed_at = datetime.now()
        if status == "CANCELLED":
            cancellation_reason = str(reason or "").strip()
            if len(cancellation_reason) < 5:
                raise ValueError("취소 사유를 5자 이상 입력해 주세요.")
            plan.cancellation_reason = cancellation_reason
        plan.status = status
        if status in {"APPROVED", "IN_PROGRESS", "COMPLETED"} and plan.approval_date is None:
            application_date = plan.application_date or inspection_plan_application_date(plan.planned_date)
            plan.application_date = application_date
            plan.approval_date = datetime.now()
        session.add(InspectionPlanEvent(
            inspection_plan_id=plan_id,
            previous_status=previous_status,
            new_status=status,
            actor_user_id=actor_user_id,
            actor_role="ADMINISTRATOR" if actor_is_admin else "APPLICANT",
            reason=str(reason or "").strip() or None,
            target_tube_count=len(targets),
        ))
        return True


def update_inspection_plan_tube_target(
    plan_id: int,
    target_id: int,
    status: str,
    *,
    actor_user_id: int | None = None,
    reason: str = "",
) -> bool:
    selected_status = str(status or "").strip().upper()
    if selected_status not in {"TARGETED", "INSPECTED", "EXCLUDED"}:
        raise ValueError("지원하지 않는 Tube 검사 상태입니다.")
    note = str(reason or "").strip()
    if selected_status == "EXCLUDED" and len(note) < 5:
        raise ValueError("검사 제외 사유를 5자 이상 입력해 주세요.")
    with session_scope(DB_PATH) as session:
        plan = session.get(InspectionPlan, plan_id)
        target = session.get(InspectionPlanTubeTarget, target_id)
        if not plan or not target or target.inspection_plan_id != plan_id:
            return False
        if plan.status not in {"APPROVED", "IN_PROGRESS"}:
            raise ValueError("승인 또는 검사 진행 중인 계획의 Tube만 처리할 수 있습니다.")
        target.target_status = selected_status
        target.excluded_reason = note if selected_status == "EXCLUDED" else None
        target.inspected_at = datetime.now() if selected_status == "INSPECTED" else None
        session.add(InspectionPlanEvent(
            inspection_plan_id=plan_id,
            previous_status=plan.status,
            new_status=plan.status,
            actor_user_id=actor_user_id,
            actor_role="INSPECTOR",
            reason=f"Tube {target.tube_no_at_selection}: {selected_status}"
                   + (f" - {note}" if note else ""),
            target_tube_count=session.scalar(select(func.count()).select_from(
                InspectionPlanTubeTarget
            ).where(InspectionPlanTubeTarget.inspection_plan_id == plan_id)) or 0,
        ))
        return True


def tube_management_data(exchanger_id: int, search: str = "", status: str = "") -> dict[str, Any] | None:
    detail = exchanger_detail(exchanger_id)
    if not detail:
        return None
    with session_scope(DB_PATH) as session:
        stmt = (select(HeatExchangerTube)
                .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
                .where(TubeBundle.heat_exchanger_id == exchanger_id)
                .order_by(HeatExchangerTube.row_no, HeatExchangerTube.column_no, HeatExchangerTube.tube_no))
        if search:
            stmt = stmt.where(HeatExchangerTube.tube_no.ilike(f"%{search.strip()}%"))
        if status:
            stmt = stmt.where(HeatExchangerTube.current_status == status)
        tubes = session.scalars(stmt).all()
        latest = {}
        for result, inspection in session.execute(
            select(IrisTubeResult, IrisInspection)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .where(IrisTubeResult.tube_id.in_([t.tube_id for t in tubes]))
            .order_by(IrisInspection.report_date.desc())
        ) if tubes else []:
            latest.setdefault(result.tube_id, (result, inspection))
        counts = dict(session.execute(
            select(HeatExchangerTube.current_status, func.count())
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .where(TubeBundle.heat_exchanger_id == exchanger_id)
            .group_by(HeatExchangerTube.current_status)
        ).all())
        return {**detail, "tubes": tubes, "latest": latest, "status_counts": counts,
                "search": search, "status_filter": status, "tube_statuses": TUBE_OPERATION_STATUSES}


def batch_update_tube_status(exchanger_id: int, tube_ids: list[int], status: str, reason: str) -> int:
    new_status = normalize_tube_status(status)
    if new_status not in TUBE_OPERATION_STATUSES:
        raise ValueError("지원하지 않는 튜브 상태입니다.")
    if not reason.strip():
        raise ValueError("일괄 상태 변경 사유는 필수입니다.")
    with session_scope(DB_PATH) as session:
        tubes = session.scalars(
            select(HeatExchangerTube).join(TubeBundle)
            .where(TubeBundle.heat_exchanger_id == exchanger_id,
                   HeatExchangerTube.tube_id.in_(tube_ids))
        ).all()
        if len(tubes) != len(set(tube_ids)):
            raise ValueError("선택한 튜브 중 해당 열교환기에 속하지 않는 항목이 있습니다.")
        changed = 0
        for tube in tubes:
            old = normalize_tube_status(tube.current_status)
            if old == new_status:
                continue
            tube.current_status = new_status
            session.add(TubeLifecycleEvent(tube_id=tube.tube_id,
                        event_type=f"STATUS_{old}_TO_{new_status}", reason=reason.strip()))
            changed += 1
        return changed


def update_tube_position(tube_id: int, data: dict[str, Any]) -> dict[str, Any] | None:
    reason = str(data.get("reason") or "").strip()
    if not reason:
        raise ValueError("위치 변경 사유는 필수입니다.")
    with session_scope(DB_PATH) as session:
        tube = session.get(HeatExchangerTube, tube_id)
        if not tube:
            return None
        new_locked = str(data.get("position_locked", "")).lower() in {"1", "true", "on", "yes"}
        new_pos = tuple(_float(data.get(key)) for key in ("position_x", "position_y", "position_z"))
        old_pos = (tube.position_x, tube.position_y, tube.position_z)
        position_changed = new_pos != old_pos
        if tube.position_locked and position_changed:
            raise ValueError("잠긴 튜브는 먼저 잠금을 해제한 뒤 위치를 변경할 수 있습니다.")
        session.add(TubePositionEvent(tube_id=tube_id, old_x=old_pos[0], old_y=old_pos[1], old_z=old_pos[2],
                    new_x=new_pos[0], new_y=new_pos[1], new_z=new_pos[2],
                    old_locked=bool(tube.position_locked), new_locked=new_locked, reason=reason))
        tube.position_x, tube.position_y, tube.position_z = new_pos
        tube.position_locked = new_locked
        return {"tube_id": tube_id, "position_locked": new_locked}


def api510_management_data(exchanger_id: int) -> dict[str, Any] | None:
    data = exchanger_detail(exchanger_id)
    if not data:
        return None
    with session_scope(DB_PATH) as session:
        components = session.scalars(
            select(PressureBoundaryComponent)
            .where(PressureBoundaryComponent.heat_exchanger_id == exchanger_id)
            .order_by(PressureBoundaryComponent.component_code)
        ).all()
        component_ids = [item.pressure_component_id for item in components]
        calculations = session.execute(
            select(Api510Calculation, PressureBoundaryComponent)
            .join(
                PressureBoundaryComponent,
                PressureBoundaryComponent.pressure_component_id == Api510Calculation.pressure_component_id,
            )
            .where(Api510Calculation.pressure_component_id.in_(component_ids))
            .order_by(Api510Calculation.created_at.desc())
        ).all() if component_ids else []
        data.update(
            pressure_components=components,
            api510_calculations=calculations,
            supported_component_types=sorted(SUPPORTED_COMPONENT_TYPES),
        )
        return data


def exchanger_report_data(exchanger_id: int) -> dict[str, Any] | None:
    data = exchanger_detail(exchanger_id)
    if not data:
        return None
    with session_scope(DB_PATH) as session:
        bundles = [b.bundle_id for b in data["bundles"]]
        status_counts = dict(session.execute(select(HeatExchangerTube.current_status, func.count())
            .where(HeatExchangerTube.bundle_id.in_(bundles)).group_by(HeatExchangerTube.current_status)).all()) if bundles else {}
        max_loss = session.scalar(select(func.max(IrisTubeResult.wall_loss_percent))
            .join(IrisInspection).where(IrisInspection.heat_exchanger_id == exchanger_id))
        approved_api510 = session.execute(
            select(Api510Calculation, PressureBoundaryComponent)
            .join(PressureBoundaryComponent)
            .where(
                PressureBoundaryComponent.heat_exchanger_id == exchanger_id,
                Api510Calculation.status == "APPROVED",
            )
            .order_by(Api510Calculation.reviewed_at.desc())
        ).all()
        data.update(status_counts=status_counts, maximum_wall_loss=max_loss,
                    approved_api510=approved_api510, generated_at=datetime.now())
        return data
