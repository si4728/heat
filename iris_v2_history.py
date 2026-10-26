"""Asset registration and multi-year IRIS tube history services."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select, or_
from sqlalchemy.orm import joinedload

from iris2.iris_v2_database import init_v2_db, session_scope
from iris2.hx_configuration import DEGRADATION_POSITION_TOLERANCE_MM
from iris2.iris_v2_models import (
    Equipment,
    HeatExchanger,
    HeatExchangerTube,
    IrisInspection,
    IrisSetupSnapshot,
    IrisTubeResult,
    Plant,
    ProcessUnit,
    TubeBundle,
    TubeDegradationAssessment,
)


DEGRADATION_ALGORITHM_VERSION = "1.3.0"
REPLACED_DEGRADATION_ALGORITHM_VERSIONS = (
    "1.0.0", "1.1.0", "1.2.0", DEGRADATION_ALGORITHM_VERSION,
)


def compare_measurement_locations(
    previous_location_mm: float | None,
    current_location_mm: float | None,
    *,
    previous_tube_length_mm: float | None = None,
    current_tube_length_mm: float | None = None,
    tolerance_mm: float = DEGRADATION_POSITION_TOLERANCE_MM,
) -> dict[str, Any]:
    """Compare positions after selecting the best valid scan-direction mapping."""
    values = (previous_location_mm, current_location_mm, tolerance_mm)
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return {
            "matched": False, "reason": "MISSING_LOCATION",
            "direction_mapping": "UNKNOWN", "distance_mm": None,
        }
    previous = float(previous_location_mm)
    current = float(current_location_mm)
    tolerance = float(tolerance_mm)
    if previous < 0 or current < 0 or tolerance <= 0:
        return {
            "matched": False, "reason": "INVALID_LOCATION",
            "direction_mapping": "UNKNOWN", "distance_mm": None,
        }

    candidates = [("SAME_DIRECTION", abs(previous - current), previous, current)]
    for mapping, length, reverse_previous in (
        ("REVERSE_PREVIOUS", previous_tube_length_mm, True),
        ("REVERSE_CURRENT", current_tube_length_mm, False),
    ):
        if length is None or not math.isfinite(float(length)) or float(length) <= 0:
            continue
        length = float(length)
        source_location = previous if reverse_previous else current
        if source_location > length:
            continue
        normalized_previous = length - previous if reverse_previous else previous
        normalized_current = current if reverse_previous else length - current
        candidates.append((
            mapping,
            abs(normalized_previous - normalized_current),
            normalized_previous,
            normalized_current,
        ))

    mapping, distance, normalized_previous, normalized_current = min(
        candidates, key=lambda candidate: candidate[1]
    )
    matched = distance <= tolerance
    return {
        "matched": matched,
        "reason": "POSITION_MATCHED" if matched else "POSITION_OUTSIDE_TOLERANCE",
        "direction_mapping": mapping,
        "distance_mm": distance,
        "tolerance_mm": tolerance,
        "previous_location_mm": previous,
        "current_location_mm": current,
        "normalized_previous_location_mm": normalized_previous,
        "normalized_current_location_mm": normalized_current,
    }


def inspection_tube_length_mm(
    inspection: IrisInspection,
    setup: IrisSetupSnapshot | None = None,
) -> float | None:
    """Resolve tube length from the structured setup, then the immutable raw report."""
    if setup is not None and setup.tube_length_m is not None:
        length = float(setup.tube_length_m) * 1000.0
        if math.isfinite(length) and length > 0:
            return length
    try:
        raw = json.loads(inspection.raw_report_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    report = raw.get("report") or {}
    details = (
        report.get("iris_report_details")
        or report.get("iris_9000_report_details")
        or {}
    )
    value = (details.get("measurement_conditions") or {}).get("tube_length_m")
    try:
        length = float(value) * 1000.0
    except (TypeError, ValueError):
        return None
    return length if math.isfinite(length) and length > 0 else None


def conservative_daily_snapshot(
    readings: list[tuple[IrisTubeResult, IrisInspection]],
) -> dict[str, Any]:
    """Aggregate one tube/day using independent conservative measurements."""
    if not readings:
        raise ValueError("At least one same-day reading is required")

    def result_id(pair: tuple[IrisTubeResult, IrisInspection]) -> int:
        return int(pair[0].iris_tube_result_id)

    thickness_candidates = [
        pair for pair in readings if pair[0].minimum_wall_thickness_mm is not None
    ]
    loss_candidates = [
        pair for pair in readings if pair[0].wall_loss_percent is not None
    ]
    thickness_pair = min(
        thickness_candidates,
        key=lambda pair: (
            float(pair[0].minimum_wall_thickness_mm),
            -float(pair[0].wall_loss_percent)
            if pair[0].wall_loss_percent is not None
            else float("inf"),
            result_id(pair),
        ),
        default=None,
    )
    loss_pair = min(
        loss_candidates,
        key=lambda pair: (
            -float(pair[0].wall_loss_percent),
            float(pair[0].minimum_wall_thickness_mm)
            if pair[0].minimum_wall_thickness_mm is not None
            else float("inf"),
            result_id(pair),
        ),
        default=None,
    )
    representative_pair = thickness_pair or loss_pair or min(readings, key=result_id)
    inspection = representative_pair[1]
    measurement_date = getattr(inspection, "inspection_date", None) or inspection.report_date
    if measurement_date is None:
        raise ValueError("A daily snapshot requires an inspection or report date")
    day = measurement_date.date() if isinstance(measurement_date, datetime) else measurement_date
    return {
        "date": day,
        "representative_result_id": result_id(representative_pair),
        "minimum_wall_thickness_mm": (
            float(thickness_pair[0].minimum_wall_thickness_mm)
            if thickness_pair is not None
            else None
        ),
        "maximum_wall_loss_percent": (
            float(loss_pair[0].wall_loss_percent) if loss_pair is not None else None
        ),
        "thickness_result_id": result_id(thickness_pair) if thickness_pair else None,
        "wall_loss_result_id": result_id(loss_pair) if loss_pair else None,
        "thickness_inspection_id": (
            int(thickness_pair[1].iris_inspection_id)
            if thickness_pair is not None
            and getattr(thickness_pair[1], "iris_inspection_id", None) is not None
            else None
        ),
        "wall_loss_inspection_id": (
            int(loss_pair[1].iris_inspection_id)
            if loss_pair is not None
            and getattr(loss_pair[1], "iris_inspection_id", None) is not None
            else None
        ),
        "thickness_location_mm": (
            float(thickness_pair[0].location_mm)
            if thickness_pair is not None
            and getattr(thickness_pair[0], "location_mm", None) is not None
            else None
        ),
        "wall_loss_location_mm": (
            float(loss_pair[0].location_mm)
            if loss_pair is not None
            and getattr(loss_pair[0], "location_mm", None) is not None
            else None
        ),
        "source_result_ids": sorted(result_id(pair) for pair in readings),
    }


def register_heat_exchanger(*, plant_code: str, unit_code: str, equipment_code: str,
                            equipment_name: str | None = None,
                            iris_applicability: str = "UNKNOWN",
                            expected_tube_count: int | None = None,
                            remarks: str | None = None) -> dict[str, Any]:
    """Register an exchanger independently of whether it has an IRIS inspection."""
    init_v2_db()
    plant_code, unit_code, equipment_code = (
        plant_code.strip().upper(), unit_code.strip().upper(), equipment_code.strip().upper()
    )
    with session_scope() as session:
        plant = session.scalar(select(Plant).where(Plant.plant_code == plant_code))
        if not plant:
            plant = Plant(plant_code=plant_code, plant_name=plant_code)
            session.add(plant)
            session.flush()
        unit = session.scalar(select(ProcessUnit).where(
            ProcessUnit.plant_id == plant.plant_id, ProcessUnit.unit_code == unit_code
        ))
        if not unit:
            unit = ProcessUnit(plant_id=plant.plant_id, unit_code=unit_code, unit_name=unit_code)
            session.add(unit)
            session.flush()
        equipment = session.scalar(select(Equipment).where(
            Equipment.unit_id == unit.unit_id, Equipment.equipment_code == equipment_code
        ))
        created = equipment is None
        if not equipment:
            equipment = Equipment(unit_id=unit.unit_id, equipment_code=equipment_code,
                                  equipment_name=equipment_name or equipment_code,
                                  equipment_type="HEAT_EXCHANGER", remarks=remarks)
            session.add(equipment)
            session.flush()
        exchanger = session.scalar(select(HeatExchanger).where(HeatExchanger.equipment_id == equipment.equipment_id))
        if not exchanger:
            exchanger = HeatExchanger(
                equipment_id=equipment.equipment_id,
                iris_applicability=iris_applicability,
                inspection_lifecycle_status="NEVER_INSPECTED",
                tube_master_status="PARTIAL" if expected_tube_count else "NOT_AVAILABLE",
                remarks=remarks,
            )
            session.add(exchanger)
            session.flush()
        bundle = session.scalar(select(TubeBundle).where(
            TubeBundle.heat_exchanger_id == exchanger.heat_exchanger_id,
            TubeBundle.bundle_code == "MAIN", TubeBundle.lifecycle_no == 1,
        ))
        if not bundle:
            bundle = TubeBundle(heat_exchanger_id=exchanger.heat_exchanger_id,
                                bundle_code="MAIN", lifecycle_no=1,
                                expected_tube_count=expected_tube_count)
            session.add(bundle)
        elif expected_tube_count is not None:
            bundle.expected_tube_count = expected_tube_count
        return {"created": created, "heat_exchanger_id": exchanger.heat_exchanger_id,
                "equipment_code": equipment.equipment_code,
                "inspection_lifecycle_status": exchanger.inspection_lifecycle_status}


def rebuild_degradation_assessments(db_path: str | None = None) -> int:
    """Recalculate trends using one conservative result per tube and date.

    If a tube is present in multiple scopes on one day, the lowest remaining
    thickness (and highest wall loss) is used. Same-day scope readings are not
    treated as elapsed-time degradation.
    """
    init_v2_db(db_path)
    created = 0
    with session_scope(db_path) as session:
        session.execute(delete(TubeDegradationAssessment).where(
            TubeDegradationAssessment.algorithm_version.in_(
                REPLACED_DEGRADATION_ALGORITHM_VERSIONS
            )
        ))
        rows = session.execute(
            select(IrisTubeResult, IrisInspection)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .join(HeatExchangerTube, HeatExchangerTube.tube_id == IrisTubeResult.tube_id)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == IrisInspection.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .where(
                or_(Equipment.install_date.is_(None), func.date(func.coalesce(IrisInspection.inspection_date, IrisInspection.report_date)) >= func.date(Equipment.install_date)),
                or_(HeatExchangerTube.installed_at.is_(None), func.date(func.coalesce(IrisInspection.inspection_date, IrisInspection.report_date)) >= func.date(HeatExchangerTube.installed_at)),
            )
            .where(func.coalesce(
                IrisInspection.inspection_date, IrisInspection.report_date
            ).is_not(None))
            .order_by(
                IrisTubeResult.tube_id,
                func.coalesce(IrisInspection.inspection_date, IrisInspection.report_date),
            )
        ).all()
        by_tube_date: dict[
            int, dict[date, list[tuple[IrisTubeResult, IrisInspection]]]
        ] = defaultdict(lambda: defaultdict(list))
        for tube_result, inspection in rows:
            measurement_date = inspection.inspection_date or inspection.report_date
            report_day = (
                measurement_date.date()
                if isinstance(measurement_date, datetime)
                else measurement_date
            )
            by_tube_date[tube_result.tube_id][report_day].append(
                (tube_result, inspection)
            )
        inspection_ids = {
            inspection.iris_inspection_id for _result, inspection in rows
        }
        setups = {
            setup.iris_inspection_id: setup
            for setup in session.scalars(
                select(IrisSetupSnapshot).where(
                    IrisSetupSnapshot.iris_inspection_id.in_(inspection_ids)
                )
            )
        } if inspection_ids else {}
        inspections = {
            inspection.iris_inspection_id: inspection
            for _result, inspection in rows
        }
        setup_lengths = {
            inspection_id: length
            for inspection_id, inspection in inspections.items()
            if (length := inspection_tube_length_mm(
                inspection, setups.get(inspection_id)
            )) is not None
        }
        for tube_id, dated in by_tube_date.items():
            selected = [
                conservative_daily_snapshot(dated[report_day])
                for report_day in sorted(dated)
            ]
            for previous, current in zip(selected, selected[1:]):
                days = (current["date"] - previous["date"]).days
                years = days / 365.2425
                if years <= 0:
                    continue
                thickness_change = None
                corrosion_rate = None
                thickness_position = compare_measurement_locations(
                    previous["thickness_location_mm"],
                    current["thickness_location_mm"],
                    previous_tube_length_mm=setup_lengths.get(
                        previous["thickness_inspection_id"]
                    ),
                    current_tube_length_mm=setup_lengths.get(
                        current["thickness_inspection_id"]
                    ),
                )
                if (
                    previous["minimum_wall_thickness_mm"] is not None
                    and current["minimum_wall_thickness_mm"] is not None
                    and thickness_position["matched"]
                ):
                    thickness_change = (
                        previous["minimum_wall_thickness_mm"]
                        - current["minimum_wall_thickness_mm"]
                    )
                    corrosion_rate = thickness_change / years
                loss_rate = None
                loss_position = compare_measurement_locations(
                    previous["wall_loss_location_mm"],
                    current["wall_loss_location_mm"],
                    previous_tube_length_mm=setup_lengths.get(
                        previous["wall_loss_inspection_id"]
                    ),
                    current_tube_length_mm=setup_lengths.get(
                        current["wall_loss_inspection_id"]
                    ),
                )
                if (
                    previous["maximum_wall_loss_percent"] is not None
                    and current["maximum_wall_loss_percent"] is not None
                    and loss_position["matched"]
                ):
                    loss_rate = (
                        current["maximum_wall_loss_percent"]
                        - previous["maximum_wall_loss_percent"]
                    ) / years
                calculated_count = sum(
                    value is not None for value in (corrosion_rate, loss_rate)
                )
                status = (
                    "CALCULATED" if calculated_count == 2
                    else "PARTIAL" if calculated_count == 1
                    else "EXCLUDED_LOCATION_MISMATCH"
                )
                confidence = (
                    "POSITION_MATCHED" if calculated_count == 2
                    else "PARTIAL_POSITION_MATCH" if calculated_count == 1
                    else "NOT_COMPARABLE"
                )
                session.add(TubeDegradationAssessment(
                    tube_id=tube_id,
                    previous_result_id=previous["representative_result_id"],
                    current_result_id=current["representative_result_id"],
                    elapsed_years=years,
                    thickness_change_mm=thickness_change, corrosion_rate_mm_per_year=corrosion_rate,
                    wall_loss_rate_percent_per_year=loss_rate,
                    confidence=confidence, status=status,
                    algorithm_version=DEGRADATION_ALGORITHM_VERSION,
                    calculation_basis=json.dumps(
                        {
                            "method": "DAILY_CONSERVATIVE_AGGREGATION",
                            "previous": previous,
                            "current": current,
                            "minimum_thickness": "daily minimum",
                            "wall_loss": "daily maximum",
                            "position_tolerance_mm": DEGRADATION_POSITION_TOLERANCE_MM,
                            "thickness_position_comparison": thickness_position,
                            "wall_loss_position_comparison": loss_position,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                ))
                created += 1
    return created


def heat_exchanger_history(heat_exchanger_id: int) -> dict[str, Any] | None:
    init_v2_db()
    with session_scope() as session:
        exchanger = session.scalar(
            select(HeatExchanger)
            .options(joinedload(HeatExchanger.equipment))
            .where(HeatExchanger.heat_exchanger_id == heat_exchanger_id)
        )
        if not exchanger:
            return None
        inspections = session.scalars(
            select(IrisInspection).where(IrisInspection.heat_exchanger_id == heat_exchanger_id)
            .order_by(IrisInspection.report_date, IrisInspection.report_sequence)
        ).all()
        return {
            "heat_exchanger_id": exchanger.heat_exchanger_id,
            "equipment_code": exchanger.equipment.equipment_code,
            "iris_applicability": exchanger.iris_applicability,
            "inspection_lifecycle_status": exchanger.inspection_lifecycle_status,
            "inspection_count": len(inspections),
            "inspections": [{
                "iris_inspection_id": row.iris_inspection_id,
                "report_date": row.report_date.date().isoformat() if row.report_date else None,
                "inspection_date": row.inspection_date.date().isoformat() if row.inspection_date else None,
                "installation_or_replacement_date_raw": row.installation_or_replacement_date_raw,
                "installation_or_replacement_date_precision": row.installation_or_replacement_date_precision,
                "bundle_code": row.source_bundle_code,
                "scope_code": row.source_scope_code,
                "scope_id": row.inspection_scope_id,
                "original_equipment_id": row.original_equipment_id,
                "extracted_tube_result_count": row.extracted_tube_result_count,
                "status": row.report_status,
            } for row in inspections],
        }


def tube_history(tube_id: int) -> dict[str, Any] | None:
    init_v2_db()
    with session_scope() as session:
        tube = session.get(HeatExchangerTube, tube_id)
        if not tube:
            return None
        rows = session.execute(
            select(IrisTubeResult, IrisInspection)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .where(IrisTubeResult.tube_id == tube_id)
            .order_by(IrisInspection.report_date, IrisInspection.report_sequence)
        ).all()
        assessments = session.scalars(
            select(TubeDegradationAssessment)
            .where(
                TubeDegradationAssessment.tube_id == tube_id,
                TubeDegradationAssessment.algorithm_version
                == DEGRADATION_ALGORITHM_VERSION,
            )
            .order_by(TubeDegradationAssessment.assessed_at)
        ).all()
        if not assessments:
            assessments = session.scalars(
                select(TubeDegradationAssessment)
                .where(TubeDegradationAssessment.tube_id == tube_id)
                .order_by(TubeDegradationAssessment.assessed_at)
            ).all()
        return {
            "tube_id": tube_id, "tube_no": tube.tube_no, "lifecycle_no": tube.lifecycle_no,
            "inspection_results": [{
                "result_id": result.iris_tube_result_id,
                "inspection_id": inspection.iris_inspection_id,
                "report_date": inspection.report_date.date().isoformat() if inspection.report_date else None,
                "source_scope_id": inspection.inspection_scope_id,
                "minimum_wall_thickness_mm": result.minimum_wall_thickness_mm,
                "wall_loss_percent": result.wall_loss_percent,
                "wall_loss_depth_mm": result.wall_loss_depth_mm,
                "corrosion_type": result.corrosion_type,
                "design_wall_thickness_mm": result.design_wall_thickness_mm,
                "defect_code": result.defect_code,
                "reported_depth_percent": result.reported_depth_percent,
                "location_mm": result.location_mm,
                "location_source_unit": result.location_source_unit,
                "remark": result.remark,
            } for result, inspection in rows],
            "degradation": [{
                "previous_result_id": item.previous_result_id,
                "current_result_id": item.current_result_id,
                "elapsed_years": item.elapsed_years,
                "thickness_change_mm": item.thickness_change_mm,
                "corrosion_rate_mm_per_year": item.corrosion_rate_mm_per_year,
                "wall_loss_rate_percent_per_year": item.wall_loss_rate_percent_per_year,
                "confidence": item.confidence,
            } for item in assessments],
        }


def coverage_summary() -> dict[str, int]:
    init_v2_db()
    with session_scope() as session:
        total = session.scalar(select(func.count()).select_from(HeatExchanger)) or 0
        inspected = session.scalar(select(func.count(func.distinct(IrisInspection.heat_exchanger_id)))) or 0
        never = session.scalar(select(func.count()).select_from(HeatExchanger).where(
            HeatExchanger.inspection_lifecycle_status == "NEVER_INSPECTED"
        )) or 0
        return {"heat_exchanger_count": total, "inspected_heat_exchanger_count": inspected,
                "never_inspected_heat_exchanger_count": never,
                "inspection_count": session.scalar(select(func.count()).select_from(IrisInspection)) or 0,
                "tube_count": session.scalar(select(func.count()).select_from(HeatExchangerTube)) or 0,
                "tube_result_count": session.scalar(select(func.count()).select_from(IrisTubeResult)) or 0}
