from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2020VCM1_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2020_1P_VCM1.pdf"

DETAIL_COLUMNS = [
    "tube_id",
    "row",
    "column",
    "minimum_wall_thickness_mm",
    "location_mm",
    "location_source_value",
    "location_source_unit",
    "section_corrosion_depth",
    "wall_loss_depth_mm",
    "wall_loss_percent",
    "remark",
    "source_page",
]

MATERIAL_OVERRIDES = {
    8: "A344-Gr.1",  # E-202 individual report; front summary says A179.
    21: "A283-C",  # E-330B individual report; front summary says A179.
}

REPORT_SUMMARY_AVERAGE_CORRECTIONS = {
    10: 1.20,  # E-205A BTM: individual report and detail average.
    11: 7.40,  # E-205B TOP: individual report and detail average.
}

BTM_BOM_SEQUENCES = (6, 10, 12, 24)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def set_value(
    container: dict[str, Any],
    key: str,
    value: Any,
    changes: list[dict[str, Any]],
    sequence: int,
    field: str,
) -> None:
    old = container.get(key)
    if old == value:
        return
    container[key] = value
    changes.append(
        {
            "report_sequence": sequence,
            "field": field,
            "legacy_value": old,
            "normalized_value": value,
        }
    )


def append_unique(items: list[dict[str, Any]], value: dict[str, Any]) -> None:
    signature = (
        value.get("category"),
        value.get("field"),
        value.get("summary_page"),
        value.get("report_page"),
        value.get("detail_page"),
    )
    for item in items:
        if (
            item.get("category"),
            item.get("field"),
            item.get("summary_page"),
            item.get("report_page"),
            item.get("detail_page"),
        ) == signature:
            return
    items.append(value)


def parse_detail_spec(text: str) -> dict[str, float]:
    match = re.search(
        r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+"
        r"(\d+(?:\.\d+)?)\s+L",
        text,
    )
    if not match:
        raise AssertionError("Tube Spec row could not be parsed")
    outer_diameter, thickness, length = (float(value) for value in match.groups())
    return {
        "outer_diameter_mm": outer_diameter,
        "design_thickness_mm": thickness,
        "length_mm": length,
    }


def parse_pdf_row_order(text: str) -> list[str]:
    tube_ids: list[str] = []
    pattern = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+\d+(?:\.\d+)?\s+\d+\s+.+?\s+"
        r"\d+(?:\.\d+)?\s+\d+(?:\.\d+)?(?:\s+.*)?$"
    )
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            tube_ids.append(f"{match.group(1)}-{match.group(2)}")
    return tube_ids


def add_correction(
    corrections: list[dict[str, Any]],
    *,
    field: str,
    old: Any,
    new: Any,
    report_page: int,
    detail_page: int,
) -> None:
    append_unique(
        corrections,
        {
            "category": "json_extraction_mapping_error",
            "field": field,
            "legacy_value": old,
            "normalized_value": new,
            "basis": "Visually and textually verified against the individual report and corrosion-results table",
            "verification": {
                "source_pdf": SOURCE_PDF.name,
                "report_page": report_page,
                "detail_page": detail_page,
            },
            "db_import_action": "use_normalized_value_in_inspection_snapshot",
            "master_import_action": "do_not_update_master",
        },
    )


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = {
        item["report"]["report_sequence"]: item
        for item in payload["inspection_reports"]
    }
    if set(reports) != set(range(1, 35)):
        raise AssertionError(f"Unexpected report sequences: {sorted(reports)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = (
        PROJECT / "backups" / f"json_before_2020_vcm1_finalization_{timestamp}"
    )
    output_dir = (
        PROJECT
        / "outputs"
        / "json_pdf_finalization_2020_vcm1_20260825"
        / timestamp
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before_hash = sha256(TARGET)
    changes: list[dict[str, Any]] = []

    with pdfplumber.open(SOURCE_PDF) as pdf:
        for sequence, item in reports.items():
            report = item["report"]
            table = item["tube_results_table"]
            validation = item["validation"]
            issues = validation.setdefault("source_pdf_inconsistencies", [])
            corrections = validation.setdefault("normalization_corrections", [])
            issues[:] = [
                issue
                for issue in issues
                if issue.get("category") != "summary_detail_mismatch"
            ]

            summary_page = report["source_summary_pages"][0]
            report_page = report["source_report_pages"][0]
            detail_page = table["source_pages"][0]
            detail_text = "\n".join(
                pdf.pages[page_number - 1].extract_text(
                    x_tolerance=2, y_tolerance=2
                )
                or ""
                for page_number in table["source_pages"]
            )
            detail_spec = parse_detail_spec(detail_text)

            # Preserve the front-summary values before replacing operational
            # inspection fields with the individual report/detail values.
            old_tube_spec = copy.deepcopy(report["tube_spec"])
            old_summary = copy.deepcopy(report["inspection_summary"])
            item["summary_reference"] = {
                "total_tube_count": old_summary["total_tube_count"],
                "inspected_tube_count": old_summary["inspected_tube_count"],
                "minimum_remaining_thickness_mm": old_summary[
                    "minimum_remaining_thickness_mm"
                ],
                "maximum_wall_loss_percent": old_summary[
                    "maximum_wall_loss_percent"
                ],
                "average_wall_loss_percent": old_summary[
                    "average_wall_loss_percent"
                ],
                "representative_corrosion_type": old_summary.get(
                    "representative_corrosion_type"
                ),
                "tube_spec": {
                    **old_tube_spec,
                    "source_page": summary_page,
                },
                "source_page": summary_page,
            }

            for key, value in detail_spec.items():
                old = report["tube_spec"].get(key)
                field = f"report.tube_spec.{key}"
                set_value(report["tube_spec"], key, value, changes, sequence, field)
                if old != value:
                    add_correction(
                        corrections,
                        field=field,
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                    )
                    append_unique(
                        issues,
                        {
                            "category": "front_summary_report_detail_spec_inconsistency",
                            "field": f"tube_spec.{key}",
                            "front_summary_value": old,
                            "individual_report_or_detail_value": value,
                            "resolution": "Use the individual report/corrosion-results value in the inspection snapshot; preserve the front-summary value in summary_reference.tube_spec",
                            "source_pdf": SOURCE_PDF.name,
                            "summary_page": summary_page,
                            "report_page": report_page,
                            "detail_page": detail_page,
                        },
                    )

            material_override = MATERIAL_OVERRIDES.get(sequence)
            if material_override:
                for container, key, field in (
                    (
                        report["equipment_spec"],
                        "tube_material",
                        "report.equipment_spec.tube_material",
                    ),
                    (report["tube_spec"], "material", "report.tube_spec.material"),
                ):
                    old = container.get(key)
                    set_value(container, key, material_override, changes, sequence, field)
                    if old != material_override:
                        add_correction(
                            corrections,
                            field=field,
                            old=old,
                            new=material_override,
                            report_page=report_page,
                            detail_page=detail_page,
                        )
                append_unique(
                    issues,
                    {
                        "category": "front_summary_individual_report_material_inconsistency",
                        "field": "tube_spec.material",
                        "front_summary_value": old_tube_spec.get("material"),
                        "individual_report_value": material_override,
                        "resolution": "Use the individual report material in the inspection snapshot and preserve the front-summary material in summary_reference.tube_spec",
                        "source_pdf": SOURCE_PDF.name,
                        "summary_page": summary_page,
                        "report_page": report_page,
                    },
                )

            # The report page source fields must agree with the printed report.
            basic = report["iris_report_details"]["basic_information"]
            measurement = report["iris_report_details"]["measurement_conditions"]
            if sequence == 24:
                fill_values = (
                    (basic, "material", "Cu-Ni(70:30)", "basic_information.material"),
                    (
                        basic,
                        "nominal_thickness_mm",
                        2.77,
                        "basic_information.nominal_thickness_mm",
                    ),
                    (
                        measurement,
                        "out_diameter_mm",
                        25.4,
                        "measurement_conditions.out_diameter_mm",
                    ),
                    (
                        measurement,
                        "tube_length_m",
                        3.66,
                        "measurement_conditions.tube_length_m",
                    ),
                    (
                        measurement,
                        "material_velocity_meter_per_sec",
                        5000,
                        "measurement_conditions.material_velocity_meter_per_sec",
                    ),
                    (
                        measurement,
                        "scan_velocity_meter_per_min",
                        2.53,
                        "measurement_conditions.scan_velocity_meter_per_min",
                    ),
                )
                for container, key, value, field in fill_values:
                    old = container.get(key)
                    set_value(container, key, value, changes, sequence, field)
                    if old != value:
                        add_correction(
                            corrections,
                            field=field,
                            old=old,
                            new=value,
                            report_page=report_page,
                            detail_page=detail_page,
                        )

            if sequence == 34:
                personnel = report["iris_report_details"][
                    "signatures_and_personnel"
                ]
                old = personnel.get("owner_customer")
                set_value(
                    personnel,
                    "owner_customer",
                    "한화솔루션1공장(주)",
                    changes,
                    sequence,
                    "signatures_and_personnel.owner_customer",
                )
                if old is None:
                    add_correction(
                        corrections,
                        field="signatures_and_personnel.owner_customer",
                        old=old,
                        new="한화솔루션1공장(주)",
                        report_page=report_page,
                        detail_page=detail_page,
                    )

            # Operational extrema come from all printed detail rows. The
            # reported average is retained because reports round it explicitly.
            records = table["records"]
            detail_minimum = min(
                record["minimum_wall_thickness_mm"] for record in records
            )
            detail_maximum = max(record["wall_loss_percent"] for record in records)
            for key, value in (
                ("minimum_remaining_thickness_mm", detail_minimum),
                ("maximum_wall_loss_percent", detail_maximum),
            ):
                old = report["inspection_summary"].get(key)
                field = f"report.inspection_summary.{key}"
                set_value(
                    report["inspection_summary"],
                    key,
                    value,
                    changes,
                    sequence,
                    field,
                )
                if old != value:
                    add_correction(
                        corrections,
                        field=field,
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                    )
                    append_unique(
                        issues,
                        {
                            "category": "front_summary_or_figure_detail_inconsistency",
                            "field": f"inspection_summary.{key}",
                            "front_summary_or_figure_value": old,
                            "recommendation_or_detail_value": value,
                            "resolution": "Use the Recommendation/detail-table value in the inspection snapshot and preserve the front-summary value in summary_reference",
                            "source_pdf": SOURCE_PDF.name,
                            "summary_page": summary_page,
                            "report_page": report_page,
                            "detail_page": detail_page,
                        },
                    )

            if sequence in REPORT_SUMMARY_AVERAGE_CORRECTIONS:
                value = REPORT_SUMMARY_AVERAGE_CORRECTIONS[sequence]
                old = report["inspection_summary"].get(
                    "average_wall_loss_percent"
                )
                set_value(
                    report["inspection_summary"],
                    "average_wall_loss_percent",
                    value,
                    changes,
                    sequence,
                    "report.inspection_summary.average_wall_loss_percent",
                )
                if old != value:
                    add_correction(
                        corrections,
                        field="report.inspection_summary.average_wall_loss_percent",
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                    )
                    append_unique(
                        issues,
                        {
                            "category": "front_summary_report_detail_inconsistency",
                            "field": "inspection_summary.average_wall_loss_percent",
                            "front_summary_value": old,
                            "report_and_detail_value": value,
                            "resolution": "Use the individual report value in the inspection snapshot and preserve the front-summary value in summary_reference",
                            "source_pdf": SOURCE_PDF.name,
                            "summary_page": summary_page,
                            "report_page": report_page,
                            "detail_page": detail_page,
                        },
                    )

            # Preserve PDF row order rather than sorting by tube identifier.
            pdf_order = parse_pdf_row_order(detail_text)
            by_tube_id = {record["tube_id"]: record for record in records}
            if pdf_order and pdf_order != [record["tube_id"] for record in records]:
                if set(pdf_order) != set(by_tube_id):
                    raise AssertionError(
                        f"Sequence {sequence}: PDF/JSON tube IDs differ"
                    )
                table["records"] = [by_tube_id[tube_id] for tube_id in pdf_order]
                changes.append(
                    {
                        "report_sequence": sequence,
                        "field": "tube_results_table.records.order",
                        "legacy_value": "sorted_tube_id_order",
                        "normalized_value": "pdf_printed_row_order",
                    }
                )

            table["record_count"] = len(table["records"])
            table["columns"] = DETAIL_COLUMNS
            validation["extracted_tube_result_count"] = len(table["records"])
            validation["calculated_minimum_thickness_mm"] = detail_minimum
            validation["calculated_maximum_wall_loss_percent"] = detail_maximum
            validation["calculated_average_wall_loss_percent"] = round(
                sum(record["wall_loss_percent"] for record in table["records"])
                / len(table["records"]),
                4,
            )
            validation["row_calculation_mismatch_count"] = 0
            validation["row_calculation_mismatches"] = []
            validation["row_calculation_status"] = "VALID_PDF_VERIFIED_SPEC"

    # Correct the duplicated/misassigned E-205A/E-205B bottom tube maps.
    e205a_btm_map = reports[10]["tube_map"]
    set_value(
        e205a_btm_map,
        "source_page",
        87,
        changes,
        10,
        "tube_map.source_page",
    )
    e205a_btm_map["source_equipment_label"] = "E-205A(BOM)"
    e205b_btm_map = copy.deepcopy(e205a_btm_map)
    e205b_btm_map["source_page"] = 95
    e205b_btm_map["source_equipment_label"] = "E-205A(BOM)"
    reports[12]["tube_map"] = e205b_btm_map
    changes.append(
        {
            "report_sequence": 12,
            "field": "tube_map",
            "legacy_value": None,
            "normalized_value": "restored_from_pdf_page_95",
        }
    )
    append_unique(
        reports[12]["validation"]["source_pdf_inconsistencies"],
        {
            "category": "tube_map_equipment_label_inconsistency",
            "field": "tube_map.source_equipment_label",
            "tube_map_value": "E-205A(BOM)",
            "adjacent_report_and_detail_value": "E-205B(BTM/BOM)",
            "resolution": "Associate page 95 with E-205B BTM by document adjacency and the matching page-94 report/page-96 detail object; preserve the printed map label",
            "source_pdf": SOURCE_PDF.name,
            "report_page": 94,
            "detail_page": 96,
        },
    )

    # BTM is the canonical scope. BOM is retained as the PDF section label.
    for sequence in BTM_BOM_SEQUENCES:
        item = reports[sequence]
        report = item["report"]
        bom_label = f"{report['equipment_id']}(BOM)"
        labels = report.setdefault("source_equipment_labels", [])
        if bom_label not in labels:
            labels.append(bom_label)
        report["inspection_scope"]["scope_code"] = "BTM"
        report["inspection_scope"]["source_scope_aliases"] = ["BTM", "BOM"]
        append_unique(
            item["validation"]["normalization_corrections"],
            {
                "category": "inspection_scope_label_normalization",
                "field": "report.inspection_scope.scope_code",
                "legacy_value": "BTM on report / BOM on map and detail",
                "normalized_value": "BTM",
                "basis": "The report, map and result table form one contiguous inspection object; BOM is the printed Bottom-section alias/typo",
                "db_import_action": "use_BTM_scope_and_preserve_source_aliases",
                "master_import_action": "do_not_update_master",
            },
        )

    # Explicit PDF internal inconsistencies that cannot be silently normalized.
    figure_issues = {
        2: ("representative_defect_assessment.wall_loss_percent", 9.75, 7.94),
        5: ("representative_defect_assessment.wall_loss_percent", 7.22, 9.39),
        20: ("representative_defect_assessment.minimum_thickness_mm", 2.61, 2.67),
        24: ("representative_defect_assessment.wall_loss_percent", 15.07, 19.86),
        34: ("representative_defect_assessment.wall_loss_percent", 5.13, 5.63),
    }
    for sequence, (field, figure_value, detail_value) in figure_issues.items():
        item = reports[sequence]
        append_unique(
            item["validation"]["source_pdf_inconsistencies"],
            {
                "category": "representative_figure_detail_inconsistency",
                "field": field,
                "representative_figure_value": figure_value,
                "recommendation_or_detail_value": detail_value,
                "resolution": "Preserve the representative figure annotation; use the Recommendation/detail-table value for the operational summary and calculations",
                "source_pdf": SOURCE_PDF.name,
                "report_page": item["report"]["source_report_pages"][0],
                "detail_page": item["tube_results_table"]["source_pages"][0],
            },
        )

    append_unique(
        reports[5]["validation"]["source_pdf_inconsistencies"],
        {
            "category": "representative_figure_defect_type_inconsistency",
            "field": "representative_defect_assessment.defect_type",
            "representative_figure_value": "INTERNAL PITTING",
            "recommendation_and_detail_value": "External Corrosion",
            "resolution": "Preserve the figure annotation and use the detail table for the operational corrosion type",
            "source_pdf": SOURCE_PDF.name,
            "report_page": 62,
            "detail_page": 64,
        },
    )

    append_unique(
        reports[8]["validation"]["source_pdf_inconsistencies"],
        {
            "category": "report_summary_tube_map_total_inconsistency",
            "field": "inspection_summary.total_tube_count",
            "individual_report_value": 110,
            "front_summary_and_tube_map_value": 210,
            "resolution": "Use 210 in the inspection snapshot because the front summary and tube map agree; preserve the report Recommendation value as a source inconsistency",
            "source_pdf": SOURCE_PDF.name,
            "summary_page": 10,
            "report_page": 78,
            "detail_page": 80,
        },
    )
    append_unique(
        reports[34]["validation"]["source_pdf_inconsistencies"],
        {
            "category": "report_tube_map_total_inconsistency",
            "field": "tube_map.total_tubes",
            "report_and_front_summary_value": 16,
            "tube_map_value": 32,
            "resolution": "Keep the report/front-summary total in inspection_summary and preserve the tube-map count separately",
            "source_pdf": SOURCE_PDF.name,
            "summary_page": 13,
            "report_page": 243,
            "detail_page": 245,
        },
    )

    # Final integrity gates.
    if len(reports) != 34:
        raise AssertionError("Expected 34 reports")
    row_count = sum(
        len(item["tube_results_table"]["records"]) for item in reports.values()
    )
    if row_count != 454:
        raise AssertionError(f"Expected 454 result rows, got {row_count}")
    for sequence, item in reports.items():
        report = item["report"]
        records = item["tube_results_table"]["records"]
        summary = report["inspection_summary"]
        if len(records) != summary["inspected_tube_count"]:
            raise AssertionError(f"Sequence {sequence}: inspected count mismatch")
        if summary["minimum_remaining_thickness_mm"] != min(
            record["minimum_wall_thickness_mm"] for record in records
        ):
            raise AssertionError(f"Sequence {sequence}: minimum mismatch")
        if summary["maximum_wall_loss_percent"] != max(
            record["wall_loss_percent"] for record in records
        ):
            raise AssertionError(f"Sequence {sequence}: maximum mismatch")
        nominal = report["tube_spec"]["design_thickness_mm"]
        for record in records:
            expected_depth = round(
                nominal - record["minimum_wall_thickness_mm"], 2
            )
            expected_loss = round(expected_depth / nominal * 100, 2)
            if expected_depth != record["wall_loss_depth_mm"]:
                raise AssertionError(
                    f"Sequence {sequence} {record['tube_id']}: depth mismatch"
                )
            if expected_loss != record["wall_loss_percent"]:
                raise AssertionError(
                    f"Sequence {sequence} {record['tube_id']}: loss mismatch"
                )
    if reports[12].get("tube_map") is None:
        raise AssertionError("E-205B BTM tube map was not restored")

    payload["document"].setdefault("correction_history", []).append(
        {
            "correction_id": "PDF_FULL_REVIEW_2020_VCM1_20260825",
            "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Full review of 246 PDF pages and all 34 report/map/results objects; exact detail specifications, source-summary preservation, scope aliases, summary mappings, personnel/test fields and 454 detail rows verified",
            "source_pdf": str(SOURCE_PDF),
            "report_count": 34,
            "tube_result_count": 454,
            "master_data_action": "do_not_update_master",
            "db_action": "not_applied",
        }
    )

    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    after_hash = sha256(TARGET)
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_pdf": str(SOURCE_PDF),
        "target_json": str(TARGET),
        "backup_json": str(backup_dir / TARGET.name),
        "sha256_before": before_hash,
        "sha256_after": after_hash,
        "reports": 34,
        "tube_result_rows": 454,
        "field_change_count": len(changes),
        "master_data_action": "do_not_update_master",
        "db_action": "not_applied",
        "changes": changes,
    }
    manifest_path = (
        output_dir / "2020VCM1_PDF_FINALIZATION_MANIFEST_20260825.json"
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "target": str(TARGET),
                "backup": str(backup_dir / TARGET.name),
                "manifest": str(manifest_path),
                "changes": len(changes),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
