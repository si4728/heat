"""Transactional JSON importer for the normalized IRIS v2 database."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from iris2.iris_json_validator import (
    VALIDATOR_VERSION,
    Issue,
    ValidationResult,
    integer,
    normalize_equipment_code,
    number,
    parse_date,
    report_parts,
    tube_map_values,
    validate_file,
)
from iris2.iris_v2_database import SCHEMA_VERSION, init_v2_db, resolve_v2_db_path, session_scope
from iris2.iris_v2_models import (
    DataQualityIssue,
    Equipment,
    EquipmentAlias,
    HeatExchanger,
    HeatExchangerSpecRevision,
    HeatExchangerTube,
    ImportBatch,
    InspectionCampaign,
    InspectionAttachment,
    InspectionExecutionSnapshot,
    InspectionPersonnel,
    InspectionProvider,
    InspectionScope,
    InspectionScopeDirection,
    InspectionSourcePage,
    InspectionValidation,
    IrisInspection,
    IrisInspectionSummaryHistory,
    IrisInspectionSpecSnapshot,
    IrisRecommendation,
    IrisRepresentativeAssessment,
    IrisSetupSnapshot,
    IrisTubeMap,
    IrisTubeMapLegend,
    IrisTubeResult,
    Plant,
    ProcessUnit,
    SourceDocument,
    SourceDocumentPage,
    TubeBundle,
)


IMPORTER_VERSION = "3.7.1"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _first(*values: Any) -> Any:
    return next((value for value in values if value is not None and value != ""), None)


def reported_total_tube_count(parts: dict[str, Any]) -> int | None:
    """Return the report-level tube total using summary data before tube-map data."""
    summary = parts["summary"]
    detail_summary = parts["details"].get("inspection_summary") or {}
    summary_ref = parts["summary_reference"]
    return integer(_first(
        summary.get("total_tube_count"),
        detail_summary.get("total_tube_count"),
        summary_ref.get("total_tube_count"),
        summary_ref.get("total_tubes_summary"),
        summary_ref.get("total_tubes_summary_raw"),
        tube_map_values(parts["tube_map"])["total_tubes"],
    ))


def _partial_date(value: Any) -> tuple[datetime | None, str | None, int | None, str | None]:
    """Preserve partial dates without inventing a month or day."""
    if value is None or str(value).strip() in {"", "-", "N/A"}:
        return None, None, None, None
    raw = str(value).strip()
    full = re.match(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})$", raw)
    if full:
        return parse_date(raw), raw, int(full.group(1)), "DAY"
    month = re.match(r"^(\d{4})[.\-/](\d{1,2})$", raw)
    if month:
        return parse_date(raw), raw, int(month.group(1)), "MONTH"
    year = re.match(r"^(\d{4})$", raw)
    if year:
        return None, raw, int(year.group(1)), "YEAR"
    return None, raw, None, "UNPARSED"


def _get_or_create(session, model, defaults: dict[str, Any] | None = None, **where):
    obj = session.scalar(select(model).filter_by(**where))
    if obj is None:
        obj = model(**where, **(defaults or {}))
        session.add(obj)
        session.flush()
    return obj


def _campaign_year(result: ValidationResult) -> int:
    for obj in result.payload.get("inspection_reports", []):
        parts = report_parts(obj)
        date = (
            parse_date(parts["basic"].get("report_date"))
            or parse_date(tube_map_values(parts["tube_map"])["map_date"])
        )
        if date:
            return date.year
    document_name = str((result.payload.get("document") or {}).get("source_file") or "")
    candidates = re.findall(r"20\d{2}", f"{document_name} {result.path.name}")
    return min(map(int, candidates)) if candidates else result.modified_at.year


def _canonical_unit(result: ValidationResult, supplied: str | None) -> str:
    if supplied:
        return re.sub(r"[^A-Z0-9]", "", supplied.strip().upper())
    value = (result.payload.get("document") or {}).get("object_unit")
    if value:
        match = re.search(r"(?:VCM[-_ ]?\d+|\bPE\b)", str(value).upper())
        if match:
            return re.sub(r"[^A-Z0-9]", "", match.group(0))
    match = re.search(r"(?:VCM\d+|(?<=_)PE(?=_))", result.path.name.upper())
    return match.group(0) if match else "UNKNOWN"


def _existing_equipment_codes(result: ValidationResult, plant_code: str,
                              unit_code: str, db_path: str | Path | None = None) -> set[str]:
    equipment_codes = {
        report_parts(obj)["equipment_code"]
        for obj in result.payload.get("inspection_reports", [])
        if isinstance(obj, dict) and report_parts(obj)["equipment_code"]
    }
    existing_codes: set[str] = set()
    if equipment_codes:
        with session_scope(db_path) as session:
            existing_codes = set(session.scalars(
                select(Equipment.equipment_code)
                .join(HeatExchanger, HeatExchanger.equipment_id == Equipment.equipment_id)
                .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
                .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
                .where(
                    Plant.plant_code == plant_code,
                    ProcessUnit.unit_code == unit_code,
                    Equipment.equipment_code.in_(equipment_codes),
                )
            ).all())
            existing_codes.update(session.scalars(
                select(HeatExchangerSpecRevision.exchanger_code)
                .join(
                    HeatExchanger,
                    HeatExchanger.heat_exchanger_id
                    == HeatExchangerSpecRevision.heat_exchanger_id,
                )
                .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
                .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
                .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
                .where(
                    Plant.plant_code == plant_code,
                    ProcessUnit.unit_code == unit_code,
                    HeatExchangerSpecRevision.is_current.is_(True),
                    HeatExchangerSpecRevision.exchanger_code.in_(equipment_codes),
                )
            ).all())
            alias_to_equipment_code = {
                re.sub(r"\s+", "", str(report_parts(obj)["equipment_raw"]).upper()):
                report_parts(obj)["equipment_code"]
                for obj in result.payload.get("inspection_reports", [])
                if isinstance(obj, dict) and report_parts(obj)["equipment_code"]
            }
            if alias_to_equipment_code:
                matched_aliases = session.scalars(
                    select(EquipmentAlias.normalized_alias_code).where(
                        EquipmentAlias.source_unit == f"{plant_code}/{unit_code}",
                        EquipmentAlias.normalized_alias_code.in_(alias_to_equipment_code),
                        EquipmentAlias.is_approved.is_(True),
                    )
                ).all()
                existing_codes.update(
                    alias_to_equipment_code[alias] for alias in matched_aliases
                )
    return existing_codes


def _classify_exchangers(result: ValidationResult, plant_code: str,
                         unit_code: str, db_path: str | Path | None = None) -> tuple[int, int, int]:
    equipment_codes = {
        report_parts(obj)["equipment_code"]
        for obj in result.payload.get("inspection_reports", [])
        if isinstance(obj, dict) and report_parts(obj)["equipment_code"]
    }
    existing_codes = _existing_equipment_codes(result, plant_code, unit_code, db_path)
    existing_count = len(equipment_codes & existing_codes)
    total_count = len(equipment_codes)
    return total_count - existing_count, existing_count, total_count


def _ensure_asset(session, plant_code: str, unit_code: str, equipment_code: str,
                  raw_equipment_id: str, source_name: str,
                  bundle_code: str = "MAIN"):
    """Return an existing Master exchanger; JSON imports must never create assets."""
    unit = session.scalar(
        select(ProcessUnit)
        .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
        .where(Plant.plant_code == plant_code, ProcessUnit.unit_code == unit_code)
    )
    equipment = session.scalar(select(Equipment).where(
        Equipment.unit_id == unit.unit_id,
        Equipment.equipment_code == equipment_code,
    )) if unit else None
    if unit is not None and equipment is None:
        equipment = session.scalar(
            select(Equipment)
            .join(HeatExchanger, HeatExchanger.equipment_id == Equipment.equipment_id)
            .join(
                HeatExchangerSpecRevision,
                HeatExchangerSpecRevision.heat_exchanger_id
                == HeatExchanger.heat_exchanger_id,
            )
            .where(
                Equipment.unit_id == unit.unit_id,
                HeatExchangerSpecRevision.is_current.is_(True),
                HeatExchangerSpecRevision.exchanger_code == equipment_code,
            )
        )
    if unit is not None and equipment is None:
        normalized = re.sub(r"\s+", "", raw_equipment_id.upper())
        equipment = session.scalar(
            select(Equipment)
            .join(HeatExchanger, HeatExchanger.equipment_id == Equipment.equipment_id)
            .join(
                EquipmentAlias,
                EquipmentAlias.heat_exchanger_id == HeatExchanger.heat_exchanger_id,
            )
            .where(
                Equipment.unit_id == unit.unit_id,
                EquipmentAlias.source_unit == f"{plant_code}/{unit_code}",
                EquipmentAlias.normalized_alias_code == normalized,
                EquipmentAlias.is_approved.is_(True),
            )
        )
    exchanger = session.scalar(select(HeatExchanger).where(
        HeatExchanger.equipment_id == equipment.equipment_id
    )) if equipment else None
    if unit is None or equipment is None or exchanger is None:
        raise ValueError(
            f"Master 설비 미존재: {plant_code}+{unit_code}+{equipment_code}"
        )
    exchanger.iris_applicability = "REQUIRED"
    exchanger.inspection_lifecycle_status = "INSPECTED"
    normalized_alias = re.sub(r"\s+", "", raw_equipment_id.upper())
    _get_or_create(
        session, EquipmentAlias,
        source_system="IRIS2_JSON", source_unit=f"{plant_code}/{unit_code}",
        normalized_alias_code=normalized_alias,
        defaults={"heat_exchanger_id": exchanger.heat_exchanger_id,
                  "alias_code": raw_equipment_id, "is_approved": True},
    )
    bundle = _get_or_create(
        session, TubeBundle, heat_exchanger_id=exchanger.heat_exchanger_id,
        bundle_code=bundle_code, lifecycle_no=1,
        defaults={"status": "ACTIVE"},
    )
    return unit, exchanger, bundle


def _ensure_scope(session, exchanger, bundle, scope_code: str, raw_scope: str,
                  directions: list[str]):
    scope = _get_or_create(
        session, InspectionScope,
        heat_exchanger_id=exchanger.heat_exchanger_id,
        bundle_id=bundle.bundle_id,
        scope_code=scope_code,
        defaults={"raw_scope_code": raw_scope, "orientation": " / ".join(directions) or None},
    )
    for sequence, direction in enumerate(directions, 1):
        _get_or_create(
            session, InspectionScopeDirection,
            inspection_scope_id=scope.inspection_scope_id,
            direction_code=direction,
            defaults={"sequence_no": sequence},
        )
    return scope


def _add_pages(session, inspection_id: int, role: str, pages: Any) -> None:
    if pages is None:
        return
    if not isinstance(pages, list):
        pages = [pages]
    for page in pages:
        value = integer(page)
        if value is not None:
            _get_or_create(session, InspectionSourcePage,
                           iris_inspection_id=inspection_id, page_role=role,
                           page_number=value)


def _load_document_pages(
    session, source: SourceDocument, payload: dict[str, Any],
    inspections: dict[int, IrisInspection],
) -> None:
    inventory = (payload.get("document") or {}).get("source_page_inventory") or []
    for page in inventory:
        association = page.get("associated_report") or {}
        inspection = inspections.get(integer(association.get("report_sequence")) or -1)
        classification = str(page.get("classification") or "other")
        page_number = integer(page.get("page_number")) or 0
        row = _get_or_create(
            session, SourceDocumentPage,
            source_document_id=source.source_document_id,
            page_number=page_number,
            defaults={"classification": classification},
        )
        row.iris_inspection_id = inspection.iris_inspection_id if inspection else None
        row.page_role = classification.upper()
        row.classification = classification
        row.extracted_text = _text(page.get("extracted_text"))
        row.text_character_count = integer(page.get("text_character_count")) or 0
        row.image_count = integer(page.get("image_count")) or 0
        row.images_json = _json(page.get("images") or [])
        row.visual_content_semantically_structured = page.get(
            "visual_content_semantically_structured"
        )
        row.raw_json = _json(page)


def _legend_bounds(label: str) -> tuple[float | None, float | None, str]:
    match = re.search(r"(\d+)%\s*to\s*(\d+)%", label, flags=re.I)
    if match:
        return float(match.group(1)), float(match.group(2)), "WALL_LOSS_RANGE"
    return None, None, "STATUS" if label not in ("Tube", "Total Tubes") else "TOTAL"


def _load_report(session, source: SourceDocument, campaign: InspectionCampaign,
                 result: ValidationResult, obj: dict[str, Any], plant_code: str,
                 unit_code: str) -> IrisInspection:
    p = report_parts(obj)
    report, details, basic = p["report"], p["details"], p["basic"]
    summary, summary_ref = p["summary"], p["summary_reference"]
    equipment_code, scope_code, directions = (
        p["equipment_code"], p["scope_code"], p["directions"]
    )
    unit, exchanger, bundle = _ensure_asset(
        session, plant_code, unit_code, equipment_code,
        str(p["equipment_raw"]), result.path.name, p["bundle_code"],
    )
    raw_scope_match = re.search(r"\((.*)\)", str(p["equipment_raw"]))
    scope = _ensure_scope(session, exchanger, bundle, scope_code,
                          raw_scope_match.group(1) if raw_scope_match else "ALL", directions)
    extraction = p["extraction_status"]
    report_date = parse_date(basic.get("report_date")) or parse_date(tube_map_values(p["tube_map"])["map_date"])
    dates = report.get("date_information") or {}
    installation = _partial_date(_first(
        dates.get("installation_or_replacement_date"),
        basic.get("installation_or_replacement_date"),
    ))
    inspection = IrisInspection(
        campaign_id=campaign.campaign_id,
        source_document_id=source.source_document_id,
        heat_exchanger_id=exchanger.heat_exchanger_id,
        bundle_id=bundle.bundle_id,
        inspection_scope_id=scope.inspection_scope_id,
        report_sequence=integer(report.get("report_sequence")) or 0,
        report_number=_text(basic.get("report_number")),
        report_date=report_date,
        inspection_date=parse_date(_first(dates.get("inspection_date"), basic.get("report_date"))),
        installation_or_replacement_date=installation[0],
        installation_or_replacement_date_raw=installation[1],
        installation_or_replacement_year=installation[2],
        installation_or_replacement_date_precision=installation[3],
        commissioning_date=parse_date(dates.get("commissioning_date")),
        manufacturing_date=parse_date(dates.get("manufacturing_date")),
        report_type=_text(report.get("report_type")),
        inspection_method=_text(report.get("inspection_method")) or "IRIS",
        original_equipment_id=str(p["equipment_raw"]),
        canonical_equipment_code=equipment_code,
        source_equipment_label=str(p["equipment_raw"]),
        source_bundle_code=p["bundle_code"],
        source_scope_code=scope_code,
        report_status="LOADED_WITH_WARNINGS" if any(
            i.report_sequence == integer(report.get("report_sequence")) for i in result.issues
        ) else "LOADED",
        extraction_status=_text(extraction.get("status")),
        report_available=extraction.get("report_available"),
        tube_map_available=extraction.get("tube_map_available"),
        tube_results_table_available=extraction.get("tube_results_table_available"),
        extraction_reason=_text(extraction.get("reason")),
        total_tube_count_reported=reported_total_tube_count(p),
        inspected_tube_count_reported=integer(_first(summary.get("inspected_tube_count"), summary_ref.get("inspected_tubes_summary"))),
        extracted_tube_result_count=len(p["records"]),
        reported_minimum_thickness_mm=number(summary.get("minimum_remaining_thickness_mm")),
        reported_maximum_wall_loss_percent=number(summary.get("maximum_wall_loss_percent")),
        reported_average_wall_loss_percent=number(summary.get("average_wall_loss_percent")),
        representative_corrosion_type=_text(summary.get("representative_corrosion_type")),
        raw_report_json=_json(obj),
    )
    session.add(inspection)
    session.flush()

    conditions = p["conditions"]
    tube_spec = p["tube_spec"]
    summary_spec = (
        summary_ref.get("tube_spec_reference")
        or summary_ref.get("tube_spec")
        or summary_ref
    )
    session.add(IrisInspectionSpecSnapshot(
        iris_inspection_id=inspection.iris_inspection_id,
        report_material=_first(tube_spec.get("material"), basic.get("material")),
        report_outer_diameter_mm=number(_first(tube_spec.get("outer_diameter_mm"), conditions.get("out_diameter_mm"))),
        report_nominal_thickness_mm=number(_first(tube_spec.get("design_thickness_mm"), basic.get("nominal_thickness_mm"))),
        report_tube_length_mm=number(_first(tube_spec.get("length_mm"), number(conditions.get("tube_length_m")) * 1000 if number(conditions.get("tube_length_m")) is not None else None)),
        summary_material=_text(_first(
            summary_spec.get("material"), summary_ref.get("material")
        )),
        summary_outer_diameter_mm=number(_first(
            summary_spec.get("outer_diameter_mm"), summary_ref.get("outer_diameter_mm")
        )),
        summary_design_thickness_mm=number(_first(
            summary_spec.get("design_thickness_mm"), summary_ref.get("design_thickness_mm")
        )),
        summary_length_mm=number(_first(
            summary_spec.get("length_mm"), summary_ref.get("length_mm")
        )),
        summary_total_tubes=integer(_first(
            summary_ref.get("total_tube_count"), summary_ref.get("total_tubes_summary"),
            summary_ref.get("total_tubes_summary_raw")
        )),
        summary_inspected_tubes=integer(_first(
            summary_ref.get("inspected_tube_count"),
            summary_ref.get("inspected_tubes_summary")
        )),
        summary_page=integer(_first(
            summary_ref.get("source_page"), summary_ref.get("summary_page")
        )),
        raw_json=_json({"tube_spec": tube_spec, "summary_reference": summary_ref}),
    ))
    eq = details.get("inspection_equipment") or {}
    session.add(IrisSetupSnapshot(
        iris_inspection_id=inspection.iris_inspection_id,
        customer=_text(basic.get("customer")), project_name=_text(basic.get("project_name")),
        equipment_name=_text(basic.get("equipment_name")), equipment_number=_text(basic.get("equipment_number")),
        process_code=_text(_first(basic.get("process_code"), report.get("process_code"))),
        production_line=_text(_first(basic.get("production_line"), report.get("production_line"))),
        shell_fluid=_text(basic.get("shell_fluid")), tube_fluid=_text(basic.get("tube_fluid")),
        tube_type=_text(basic.get("tube_type")),
        equipment_maker=_text(eq.get("equipment_maker")), equipment_model=_text(eq.get("equipment_model")),
        equipment_serial_number=_text(eq.get("equipment_serial_number")), search_unit_maker=_text(eq.get("search_unit_maker")),
        search_unit_model=_text(eq.get("search_unit_model")), frequency_mhz=number(eq.get("frequency_mhz")),
        search_unit_serial_number=_text(eq.get("search_unit_serial_number")),
        out_diameter_mm=number(conditions.get("out_diameter_mm")), tube_length_m=number(conditions.get("tube_length_m")),
        material_velocity_meter_per_sec=number(conditions.get("material_velocity_meter_per_sec")),
        scan_velocity_meter_per_min=number(conditions.get("scan_velocity_meter_per_min")),
        water_pressure_kg_per_cm2=number(conditions.get("water_pressure_kg_per_cm2")),
        water_temperature_celsius=number(conditions.get("water_temperature_celsius")), raw_json=_json({"basic_information": basic, "inspection_equipment": eq, "measurement_conditions": conditions}),
    ))
    execution = details.get("inspection_execution") or {}
    software = details.get("inspection_software") or {}
    provider_name = _text(_first(
        execution.get("inspection_company"), execution.get("provider_name")
    ))
    provider = None
    if provider_name:
        provider_code = re.sub(r"[^A-Z0-9]+", "_", provider_name.upper()).strip("_")[:50]
        provider_code = provider_code or f"PROVIDER_{inspection.iris_inspection_id}"
        provider = _get_or_create(
            session, InspectionProvider, provider_code=provider_code,
            defaults={"provider_name": provider_name},
        )
        provider.provider_name = provider_name
        provider.provider_local_name = _text(execution.get("inspection_company_local_name")) or provider.provider_local_name
        provider.contact_phone = _text(execution.get("telephone")) or provider.contact_phone
        provider.address = _text(execution.get("address")) or provider.address
        provider.fax = _text(execution.get("fax")) or provider.fax
    session.add(InspectionExecutionSnapshot(
        iris_inspection_id=inspection.iris_inspection_id,
        inspection_provider_id=(provider.inspection_provider_id if provider else None),
        inspection_company_raw=provider_name,
        inspection_company_source_text=_text(execution.get("inspection_company_source_text")),
        inspection_company_brand=_text(execution.get("inspection_company_brand")),
        source_page=integer(execution.get("source_page")),
        contract_no=_text(execution.get("contract_no")),
        work_order_no=_text(execution.get("work_order_no")),
        procedure_no=_text(execution.get("procedure_no")),
        procedure_revision=_text(execution.get("procedure_revision")),
        acquisition_software_name=_text(software.get("acquisition_software_name")),
        acquisition_software_version=_text(software.get("acquisition_software_version")),
        analysis_software_name=_text(software.get("analysis_software_name")),
        analysis_software_version=_text(software.get("analysis_software_version")),
        equipment_calibration_date=parse_date(execution.get("equipment_calibration_date")),
        equipment_calibration_valid_until=parse_date(
            execution.get("equipment_calibration_valid_until")
        ),
        remarks=_text(execution.get("remarks")),
        raw_json=_json({"inspection_execution": execution, "inspection_software": software}),
    ))
    representative = details.get("representative_defect_assessment") or {}
    annotations = representative.get("figure_annotations") or {}
    session.add(IrisRepresentativeAssessment(
        iris_inspection_id=inspection.iris_inspection_id,
        target_tube=_text(representative.get("target_tube")), minimum_thickness_mm=number(representative.get("minimum_thickness_mm")),
        wall_loss_percent=number(representative.get("wall_loss_percent")), defect_type=_text(representative.get("defect_type")),
        start_point=_text(annotations.get("start_point")), end_point=_text(annotations.get("end_point")),
        direction_labels_json=_json(annotations.get("direction_labels") or []), raw_json=_json(representative),
    ))
    for index, recommendation in enumerate(details.get("recommendations") or [], 1):
        session.add(IrisRecommendation(iris_inspection_id=inspection.iris_inspection_id,
                                       sequence_no=index, recommendation_text=str(recommendation)))
    from iris2.iris_json_mapping import ALLOWED_PERSONNEL_ROLES
    personnel_data = details.get("signatures_and_personnel") or {}
    for role in ALLOWED_PERSONNEL_ROLES:
        person = personnel_data.get(role)
        if person in (None, "", {}):
            continue
        if isinstance(person, dict):
            person_name = _text(_first(person.get("name"), person.get("person_name")))
            organization = _text(_first(person.get("organization"), person.get("company")))
        else:
            person_name, organization = _text(person), None
        provenance = personnel_data.get(role + "_extraction") or {}
        session.add(InspectionPersonnel(
            iris_inspection_id=inspection.iris_inspection_id,
            role=str(role).upper(), person_name=person_name,
            organization=organization, source_page=integer(provenance.get("source_page")),
            extraction_method=_text(provenance.get("method")),
            review_required=bool(provenance.get("review_required")),
            raw_json=_json({"value": person, "extraction": provenance}),
        ))
    _add_pages(session, inspection.iris_inspection_id, "REPORT", report.get("source_report_pages"))
    _add_pages(session, inspection.iris_inspection_id, "SUMMARY", report.get("source_summary_pages"))
    _add_pages(session, inspection.iris_inspection_id, "TUBE_RESULTS", p["table"].get("source_pages"))
    _add_pages(session, inspection.iris_inspection_id, "TUBE_MAP", p["tube_map"].get("source_page"))
    _add_pages(session, inspection.iris_inspection_id, "VISUAL_EVIDENCE",
               (obj.get("source_content") or {}).get("visual_evidence_pages"))

    attachment = details.get("attachment_information") or {}
    if attachment:
        inferred = attachment.get("selected_value_inferred")
        session.add(InspectionAttachment(
            iris_inspection_id=inspection.iris_inspection_id,
            attachment_present=(True if str(inferred).upper() == "YES" else
                                False if str(inferred).upper() == "NO" else None),
            selected_value_raw=_text(inferred),
            attachment_types_json=_json(attachment.get("raw_attachment_terms") or []),
            source_page=integer(attachment.get("source_page")),
            inference_confidence=_text(attachment.get("inference_confidence")),
            raw_json=_json(attachment),
        ))
    session.add(IrisInspectionSummaryHistory(
        iris_inspection_id=inspection.iris_inspection_id,
        previous_inspection_date=parse_date(summary_ref.get("previous_inspection_date")),
        previous_maximum_wall_loss_percent=number(summary_ref.get("previous_maximum_wall_loss_percent")),
        plugged_tube_count_before=integer(summary_ref.get("plugged_tube_count_before")),
        plugged_tube_count_after=integer(summary_ref.get("plugged_tube_count_after")),
        summary_remarks=_text(summary_ref.get("remarks")), raw_json=_json(summary_ref),
    ))

    map_raw = p["tube_map"]
    if map_raw:
        values = tube_map_values(map_raw)
        tube_map = IrisTubeMap(
            iris_inspection_id=inspection.iris_inspection_id,
            source_page=integer(map_raw.get("source_page")), map_date=parse_date(values["map_date"]),
            mode=_text(map_raw.get("mode")), raw_equipment_id=_text(map_raw.get("map_equipment_id")),
            orientation=_text(map_raw.get("orientation")), vertical_spacing=number(values["vertical_spacing"]),
            horizontal_spacing=number(values["horizontal_spacing"]), total_tubes=integer(values["total_tubes"]),
            unmarked_or_untested_tubes=integer(values["untested_tubes"]), raw_json=_json(map_raw),
        )
        session.add(tube_map)
        session.flush()
        for label, count in (map_raw.get("legend_counts") or {}).items():
            low, high, value_type = _legend_bounds(label)
            session.add(IrisTubeMapLegend(tube_map_id=tube_map.tube_map_id,
                                          legend_label=str(label), legend_code=re.sub(r"\W+", "_", str(label).upper()).strip("_"),
                                          value_type=value_type, lower_bound_percent=low,
                                          upper_bound_percent=high, tube_count=integer(count) or 0))

    for record in p["records"]:
        source_tube_id = str(record.get("tube_id") or "").strip()
        tube = _get_or_create(
            session, HeatExchangerTube, bundle_id=bundle.bundle_id,
            tube_no=source_tube_id, lifecycle_no=1,
            defaults={"row_no": integer(record.get("row")), "column_no": integer(record.get("column")),
                      "source_tube_label": source_tube_id, "current_status": "IN_SERVICE"},
        )
        session.add(IrisTubeResult(
            iris_inspection_id=inspection.iris_inspection_id, tube_id=tube.tube_id,
            source_tube_id=source_tube_id, source_row=integer(record.get("row")),
            source_column=integer(record.get("column")), minimum_wall_thickness_mm=number(record.get("minimum_wall_thickness_mm")),
            location_mm=number(record.get("location_mm")), corrosion_type=_text(record.get("section_corrosion_depth")),
            wall_loss_depth_mm=number(record.get("wall_loss_depth_mm")), wall_loss_percent=number(record.get("wall_loss_percent")),
            raw_side=_text(_first(record.get("raw_side"), record.get("side"))),
            analysis_v=number(_first(record.get("analysis_v"), record.get("v"))),
            source_location_raw=_text(record.get("location_source_value")),
            location_source_unit=_text(record.get("location_source_unit")),
            remark=_text(record.get("remark")),
            design_wall_thickness_mm=number(record.get("design_wall_thickness_mm")),
            defect_code=_text(record.get("defect_code")),
            reported_depth_percent=number(record.get("reported_depth_percent")),
            source_page=integer(record.get("source_page")), raw_json=_json(record),
        ))
    exchanger.tube_master_status = "PARTIAL" if p["records"] else exchanger.tube_master_status

    validation = p["validation"]
    loss_values = [number(r.get("wall_loss_percent")) for r in p["records"] if number(r.get("wall_loss_percent")) is not None]
    thickness_values = [number(r.get("minimum_wall_thickness_mm")) for r in p["records"] if number(r.get("minimum_wall_thickness_mm")) is not None]
    range_raw = p["table"].get("corrosion_depth_range_percent") or {}
    report_issues = [i for i in result.issues if i.report_sequence == inspection.report_sequence]
    session.add(InspectionValidation(
        iris_inspection_id=inspection.iris_inspection_id, extracted_tube_result_count=len(p["records"]),
        reported_vs_extracted_match=validation.get("reported_vs_extracted_count_match"),
        calculated_minimum_thickness_mm=min(thickness_values) if thickness_values else None,
        calculated_maximum_wall_loss_percent=max(loss_values) if loss_values else None,
        calculated_average_wall_loss_percent=(sum(loss_values) / len(loss_values)) if loss_values else None,
        wall_loss_range_min_percent=number(range_raw.get("min")), wall_loss_range_max_percent=number(range_raw.get("max")),
        formula_check_passed=not any(i.code.endswith("MISMATCH") for i in report_issues),
        validation_status="WARNING" if report_issues else "VALID",
        validator_version=VALIDATOR_VERSION, raw_json=_json(validation),
    ))
    return inspection


def _report_paths(source: Path, report_dir: Path, timestamp: str) -> tuple[Path, Path, Path]:
    stem = source.stem
    return (report_dir / f"{stem}_{timestamp}_checking_report.md",
            report_dir / f"{stem}_{timestamp}_issues.json",
            report_dir / f"{stem}_{timestamp}_load_summary.json")


def _write_reports(result: ValidationResult, outcome: dict[str, Any], report_dir: Path,
                   cumulative_path: Path) -> tuple[Path, Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    md_path, issue_path, summary_path = _report_paths(result.path, report_dir, stamp)
    lines = [
        f"# IRIS JSON 검사 및 적재 보고서: {result.path.name}", "",
        f"- 실행시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- SHA-256: `{result.sha256}`", f"- 검증상태: **{result.status}**",
        f"- 적재상태: **{outcome['status']}**", f"- 보고서 객체: {result.report_count}",
        f"- 튜브 결과: {result.tube_result_count}", f"- 오류: {result.error_count}",
        f"- 경고: {result.warning_count}", "", "## 발견 사항", "",
    ]
    if not result.issues:
        lines.append("발견된 문제가 없습니다.")
    else:
        lines.extend(["|등급|코드|검사 객체|설비|필드|내용|", "|---|---|---:|---|---|---|"])
        for issue in result.issues:
            lines.append(f"|{issue.severity}|{issue.code}|{issue.report_sequence or ''}|{issue.equipment_id or ''}|{issue.field_path}|{issue.description}|")
    lines.extend(["", "## Master 미존재 교환기", ""])
    missing_messages = outcome.get("missing_equipment_messages", [])
    if missing_messages:
        lines.extend(f"- {message}" for message in missing_messages)
    else:
        lines.append("없음")
    lines.extend(["", "## 적재 결과", "", "```json", json.dumps(outcome, ensure_ascii=False, indent=2), "```", ""])
    md_text = "\n".join(lines)
    md_path.write_text(md_text, encoding="utf-8")
    issue_path.write_text(json.dumps(result.summary(), ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    with cumulative_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n\n---\n\n## 자동 검사 기록: {result.path.name} ({datetime.now().isoformat(timespec='seconds')})\n\n")
        handle.write(f"- 검증: {result.status}, 적재: {outcome['status']}, 보고서: {result.report_count}, 튜브 결과: {result.tube_result_count}, 오류: {result.error_count}, 경고: {result.warning_count}\n")
        handle.write(f"- 상세 보고서: `{md_path}`\n")
        for issue in result.issues:
            handle.write(f"- [{issue.severity}] `{issue.code}` / {issue.equipment_id or '-'} / {issue.description}\n")
    return md_path, issue_path, summary_path


def import_file(path: str | Path, *, plant_code: str = "P1", unit_code: str | None = None,
                dry_run: bool = False, allow_errors: bool = False,
                report_dir: str | Path | None = None,
                cumulative_path: str | Path | None = None,
                db_path: str | Path | None = None) -> dict[str, Any]:
    plant_code = str(plant_code or "").strip().upper()
    if not plant_code:
        raise ValueError("plant_code is required")
    result = validate_file(path)
    reports_dir = Path(report_dir or result.path.parent / "import_reports").resolve()
    cumulative = Path(cumulative_path or result.path.parent / "cheking_report.md").resolve()
    unit = _canonical_unit(result, unit_code)
    target_db = resolve_v2_db_path(db_path)
    new_exchanger_count, existing_exchanger_count, total_exchanger_count = (
        _classify_exchangers(result, plant_code, unit, target_db)
    )
    existing_codes = _existing_equipment_codes(result, plant_code, unit, target_db)
    missing_reports = []
    for index, obj in enumerate(result.payload.get("inspection_reports", [])):
        parts = report_parts(obj)
        if parts["equipment_code"] not in existing_codes:
            missing_reports.append({
                "report_index": index,
                "report_sequence": integer(parts["report"].get("report_sequence")),
                "equipment_raw": str(parts["equipment_raw"]),
                "equipment_code": parts["equipment_code"],
                "plant_code": plant_code,
                "unit_code": unit,
            })
    missing_messages = [
        f"미존재 교환기: {row['plant_code']}+{row['unit_code']}+{row['equipment_code']} "
        f"(JSON 값: {row['equipment_raw']}) - Master DB에 없어 적재 제외"
        for row in missing_reports
    ]
    outcome: dict[str, Any] = {
        "source_file": result.path.name, "sha256": result.sha256,
        "mode": "dry-run-master-check" if dry_run else "load-master-existing-only",
        "status": "VALIDATED" if dry_run else "PENDING",
        "schema_version": SCHEMA_VERSION, "importer_version": IMPORTER_VERSION,
        "plant_code": plant_code, "unit_code": unit,
        "new_exchanger_count": new_exchanger_count,
        "existing_exchanger_count": existing_exchanger_count,
        "total_exchanger_count": total_exchanger_count,
        "report_count": result.report_count, "loaded_report_count": 0,
        "tube_result_count": result.tube_result_count,
        "error_count": result.error_count,
        "validation_warning_count": result.warning_count,
        "warning_count": result.warning_count + len(missing_reports),
        "master_check_required": True,
        "missing_master_exchanger_count": len({
            row["equipment_code"] for row in missing_reports
        }),
        "skipped_missing_report_count": len(missing_reports),
        "missing_equipment_reports": missing_reports,
        "missing_equipment_messages": missing_messages,
    }
    logical_duplicate_id = None
    if not dry_run:
        with session_scope(target_db) as check_session:
            same_name = check_session.scalar(select(SourceDocument).where(
                SourceDocument.source_file == result.path.name,
                SourceDocument.sha256 != result.sha256,
            ))
            logical_duplicate_id = same_name.source_document_id if same_name else None
    if result.error_count and not allow_errors:
        outcome["status"] = "REJECTED_VALIDATION_ERROR"
    elif logical_duplicate_id is not None:
        outcome.update(
            status="REJECTED_LOGICAL_DUPLICATE",
            source_document_id=logical_duplicate_id,
            error=(
                "같은 파일명의 기존 문서가 있습니다. 검사 ID를 보존하는 "
                "관리자 Upsert 절차를 사용해 주세요."
            ),
        )
    elif not dry_run:
        init_v2_db(target_db)
        with session_scope(target_db) as session:
            existing = session.scalar(select(SourceDocument).where(SourceDocument.sha256 == result.sha256))
            if (
                existing
                and existing.load_status == "LOADED"
                and existing.loaded_report_count >= existing.expected_report_count
                and existing.postprocess_status == "COMPLETED"
            ):
                outcome.update(status="SKIPPED_DUPLICATE", source_document_id=existing.source_document_id)
            else:
                batch = ImportBatch(
                    status="RUNNING", mode="load-master-existing-only",
                    importer_version=IMPORTER_VERSION,
                    source_path=str(result.path), report_count=result.report_count,
                    warning_count=result.warning_count + len(missing_reports),
                    error_count=result.error_count,
                    skipped_count=len(missing_reports),
                )
                session.add(batch)
                session.flush()
                document = result.payload.get("document") or {}
                schema = result.payload.get("schema") or {}
                source = existing
                if source is None:
                    source = SourceDocument(
                        import_batch_id=batch.import_batch_id, source_file=result.path.name,
                        source_path=str(result.path), title=_text(document.get("title")),
                        page_count=integer(document.get("page_count")), file_size=result.size,
                        sha256=result.sha256, source_modified_at=result.modified_at,
                        schema_name=_text(schema.get("name")) or "iris-inspection-report",
                        schema_version=_text(schema.get("version")) or "1.0.0",
                        document_json=_json(document), schema_json=_json(schema),
                        load_status="RECEIVED", expected_report_count=result.report_count,
                        loaded_report_count=0, missing_report_count=len(missing_reports),
                        postprocess_status="PENDING",
                    )
                    session.add(source)
                    session.flush()
                else:
                    source.import_batch_id = batch.import_batch_id
                    source.source_path = str(result.path)
                    source.source_modified_at = result.modified_at
                    source.expected_report_count = result.report_count
                    source.postprocess_status = "PENDING"
                    source.postprocess_message = None
                year = _campaign_year(result)
                plant = _get_or_create(session, Plant, plant_code=plant_code, defaults={"plant_name": plant_code})
                process_unit = _get_or_create(session, ProcessUnit, plant_id=plant.plant_id, unit_code=unit, defaults={"unit_name": unit})
                campaign = _get_or_create(
                    session, InspectionCampaign, unit_id=process_unit.unit_id,
                    campaign_year=year, campaign_name=f"{year} {unit} IRIS",
                    defaults={"project_name": _text(document.get("title"))},
                )
                inspection_by_sequence = {
                    inspection.report_sequence: inspection
                    for inspection in session.scalars(select(IrisInspection).where(
                        IrisInspection.source_document_id == source.source_document_id
                    ))
                }
                newly_loaded = 0
                for obj in result.payload.get("inspection_reports", []):
                    parts = report_parts(obj)
                    if parts["equipment_code"] not in existing_codes:
                        continue
                    sequence = integer(parts["report"].get("report_sequence"))
                    if sequence in inspection_by_sequence:
                        continue
                    inspection = _load_report(
                        session, source, campaign, result, obj, plant_code, unit,
                    )
                    inspection_by_sequence[inspection.report_sequence] = inspection
                    newly_loaded += 1
                session.flush()
                _load_document_pages(session, source, result.payload, inspection_by_sequence)
                for old_issue in session.scalars(select(DataQualityIssue).where(
                    DataQualityIssue.source_document_id == source.source_document_id,
                    DataQualityIssue.issue_code == "MASTER_EQUIPMENT_NOT_FOUND",
                )):
                    old_issue.status = "RESOLVED"
                    old_issue.resolution_note = "Importer retry re-evaluated Master linkage."
                for missing in missing_reports:
                    fingerprint = hashlib.sha256(
                        f"{result.sha256}|MASTER_EQUIPMENT_NOT_FOUND|{plant_code}|"
                        f"{missing['report_index']}|{unit}|{missing['equipment_code']}".encode("utf-8")
                    ).hexdigest()
                    issue_row = _get_or_create(
                        session, DataQualityIssue,
                        source_document_id=source.source_document_id,
                        issue_fingerprint=fingerprint,
                        defaults={
                            "issue_code": "MASTER_EQUIPMENT_NOT_FOUND",
                            "severity": "WARNING",
                            "description": "공장+공정+교환기 코드가 Master DB에 없어 검사 적재에서 제외됨",
                        },
                    )
                    issue_row.status = "OPEN"
                    issue_row.resolution_note = None
                    issue_row.field_path = (
                        f"$.inspection_reports[{missing['report_index']}]"
                        ".report.equipment_id"
                    )
                    issue_row.source_value_json = _json(missing["equipment_raw"])
                    issue_row.calculated_value_json = _json({
                        "plant_code": plant_code, "unit_code": unit,
                        "equipment_code": missing["equipment_code"],
                    })
                for issue in result.issues:
                    inspection = inspection_by_sequence.get(issue.report_sequence or -1)
                    issue_row = _get_or_create(
                        session, DataQualityIssue,
                        source_document_id=source.source_document_id,
                        issue_fingerprint=issue.fingerprint,
                        defaults={
                            "issue_code": issue.code, "severity": issue.severity,
                            "description": issue.description,
                        },
                    )
                    if inspection and issue_row.iris_inspection_id is None:
                        issue_row.iris_inspection_id = inspection.iris_inspection_id
                    issue_row.field_path = issue.field_path
                    issue_row.source_value_json = _json(issue.source_value)
                    issue_row.calculated_value_json = _json(issue.calculated_value)
                total_warnings = result.warning_count + len(missing_reports)
                source.loaded_report_count = len(inspection_by_sequence)
                source.missing_report_count = len(missing_reports)
                source.load_status = "PARTIAL" if missing_reports else "LOADED"
                batch.status = (
                    "PARTIAL" if missing_reports else
                    "COMPLETED_WITH_WARNINGS" if total_warnings else "COMPLETED"
                )
                batch.finished_at = datetime.now()
                batch.loaded_report_count = len(inspection_by_sequence)
                outcome.update(status=batch.status, import_batch_id=batch.import_batch_id,
                               source_document_id=source.source_document_id,
                               loaded_report_count=len(inspection_by_sequence),
                               newly_loaded_report_count=newly_loaded)
    md_path = issue_path = summary_path = None
    try:
        md_path, issue_path, summary_path = _write_reports(result, outcome, reports_dir, cumulative)
        outcome.update(markdown_report=str(md_path), issue_report=str(issue_path), load_summary=str(summary_path))
        if not dry_run and outcome["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "PARTIAL"}:
            from iris2.iris_v2_history import rebuild_degradation_assessments
            outcome["degradation_assessment_count"] = rebuild_degradation_assessments(str(target_db))
        if not dry_run and outcome.get("source_document_id") and outcome["status"] != "SKIPPED_DUPLICATE":
            with session_scope(target_db) as session:
                source = session.get(SourceDocument, outcome["source_document_id"])
                source.postprocess_status = "COMPLETED"
                source.postprocess_message = None
                if outcome.get("import_batch_id"):
                    batch = session.get(ImportBatch, outcome["import_batch_id"])
                    batch.markdown_report_path = str(md_path)
                    batch.json_report_path = str(issue_path)
                    batch.load_summary_path = str(summary_path)
    except Exception as exc:
        outcome["status"] = "POSTPROCESS_FAILED"
        outcome["postprocess_error"] = str(exc)
        if not dry_run and outcome.get("source_document_id"):
            with session_scope(target_db) as session:
                source = session.get(SourceDocument, outcome["source_document_id"])
                source.postprocess_status = "FAILED"
                source.postprocess_message = str(exc)
                if outcome.get("import_batch_id"):
                    batch = session.get(ImportBatch, outcome["import_batch_id"])
                    batch.status = "POSTPROCESS_FAILED"
                    batch.message = str(exc)
    if summary_path is not None:
        summary_path.write_text(json.dumps(outcome, ensure_ascii=False, indent=2), encoding="utf-8")
    return outcome


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and load IRIS JSON into the v2 database.")
    parser.add_argument("json_files", nargs="+", type=Path)
    parser.add_argument("--plant", default="P1", help="Production plant code (default: P1)")
    parser.add_argument("--unit")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-errors", action="store_true")
    parser.add_argument("--report-dir", type=Path)
    parser.add_argument("--checking-report", type=Path)
    args = parser.parse_args()
    exit_code = 0
    for source in args.json_files:
        outcome = import_file(source, plant_code=args.plant, unit_code=args.unit,
                              dry_run=args.dry_run, allow_errors=args.allow_errors,
                              report_dir=args.report_dir, cumulative_path=args.checking_report)
        for message in outcome.get("missing_equipment_messages", []):
            print(message)
        print(json.dumps(outcome, ensure_ascii=False, indent=2))
        if outcome["status"].startswith("REJECTED"):
            exit_code = 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
