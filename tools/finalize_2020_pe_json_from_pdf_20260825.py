from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2020PE_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2020_1P_PE.pdf"

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

# Operational inspection-snapshot specifications come from the individual report
# page and its corrosion-results Tube Spec row. The front summary values are kept
# separately in summary_reference.tube_spec.
REPORT_SPECS: dict[int, dict[str, Any]] = {
    1: {"equipment": "E-131D", "material": "A179", "thickness": 2.77, "length": 2900.0, "summary_thickness": 2.77, "summary_length": 2900.0, "summary_page": 9},
    2: {"equipment": "E-241B", "material": "A179", "thickness": 2.77, "length": 4648.0, "summary_thickness": 1.65, "summary_length": 4648.0, "summary_page": 9},
    3: {"equipment": "E-331B", "material": "A179", "thickness": 2.11, "length": 2300.0, "summary_thickness": 2.11, "summary_length": 3800.0, "summary_page": 9},
    4: {"equipment": "E-331C", "material": "A179", "thickness": 2.11, "length": 1900.0, "summary_thickness": 2.11, "summary_length": 3400.0, "summary_page": 9},
    5: {"equipment": "E-331D", "material": "A179", "thickness": 2.11, "length": 2900.0, "summary_thickness": 2.11, "summary_length": 4169.0, "summary_page": 9},
    6: {"equipment": "E-341A", "material": "A179", "thickness": 2.11, "length": 3000.0, "summary_thickness": 2.11, "summary_length": 3400.0, "summary_page": 9},
    7: {"equipment": "E-341C", "material": "A179", "thickness": 2.11, "length": 3048.0, "summary_thickness": 2.11, "summary_length": 3048.0, "summary_page": 9},
    8: {"equipment": "ER-201", "material": "A179", "thickness": 2.77, "length": 3660.0, "summary_thickness": 2.77, "summary_length": 3660.0, "summary_page": 10},
    9: {"equipment": "ER-301A", "material": "A179", "thickness": 2.77, "length": 3660.0, "summary_thickness": 2.77, "summary_length": 3658.0, "summary_page": 10},
    10: {"equipment": "ER-301B", "material": "A179", "thickness": 2.77, "length": 3660.0, "summary_thickness": 2.77, "summary_length": 3658.0, "summary_page": 10},
}

SUMMARY_CORRECTIONS = {
    3: {"minimum_remaining_thickness_mm": 0.91, "maximum_wall_loss_percent": 56.87},
    8: {"maximum_wall_loss_percent": 23.47},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_unique(items: list[dict[str, Any]], value: dict[str, Any]) -> None:
    signature = (value.get("category"), value.get("field"), value.get("normalized_value"))
    for item in items:
        if (item.get("category"), item.get("field"), item.get("normalized_value")) == signature:
            return
    items.append(value)


def set_value(container: dict[str, Any], key: str, value: Any, changes: list[dict[str, Any]], sequence: int, field: str) -> None:
    old = container.get(key)
    if old == value:
        return
    container[key] = value
    changes.append({"report_sequence": sequence, "field": field, "legacy_value": old, "normalized_value": value})


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT / "backups" / f"json_before_2020_pe_finalization_{timestamp}"
    output_dir = PROJECT / "outputs" / "json_pdf_finalization_2020_pe_20260825" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup_dir / TARGET.name)

    before_hash = sha256(TARGET)
    reports = {obj["report"]["report_sequence"]: obj for obj in payload["inspection_reports"]}
    if set(reports) != set(REPORT_SPECS):
        raise AssertionError(f"Unexpected report sequences: {sorted(reports)}")

    changes: list[dict[str, Any]] = []
    for sequence, spec in REPORT_SPECS.items():
        obj = reports[sequence]
        report = obj["report"]
        if sequence != 8 and report["equipment_id"] != spec["equipment"]:
            raise AssertionError(f"Sequence {sequence} equipment mismatch: {report['equipment_id']}")

        tube_spec = report["tube_spec"]
        equipment_spec = report["equipment_spec"]
        details = report["iris_report_details"]
        basic = details["basic_information"]
        validation = obj["validation"]
        corrections = validation.setdefault("normalization_corrections", [])
        issues = validation.setdefault("source_pdf_inconsistencies", [])

        fields = [
            (equipment_spec, "tube_material", spec["material"], "report.equipment_spec.tube_material"),
            (tube_spec, "outer_diameter_mm", 19.05, "report.tube_spec.outer_diameter_mm"),
            (tube_spec, "design_thickness_mm", spec["thickness"], "report.tube_spec.design_thickness_mm"),
            (tube_spec, "length_mm", spec["length"], "report.tube_spec.length_mm"),
            (tube_spec, "material", spec["material"], "report.tube_spec.material"),
            (basic, "material", spec["material"], "basic_information.material"),
            (basic, "nominal_thickness_mm", spec["thickness"], "basic_information.nominal_thickness_mm"),
        ]
        for container, key, value, field in fields:
            old = container.get(key)
            set_value(container, key, value, changes, sequence, field)
            if old != value:
                append_unique(
                    corrections,
                    {
                        "category": "json_extraction_mapping_error",
                        "field": field,
                        "legacy_value": old,
                        "normalized_value": value,
                        "basis": "Visually verified on the individual PDF report page and corrosion-results Tube Spec row",
                        "verification": {
                            "source_pdf": SOURCE_PDF.name,
                            "report_page": report["source_report_pages"][0],
                            "detail_page": obj["tube_results_table"]["source_pages"][0],
                            "method": "visual_review_report_map_and_corrosion_results_pages",
                        },
                        "db_import_action": "use_normalized_value_in_inspection_snapshot",
                        "master_import_action": "do_not_update_master",
                    },
                )

        obj["summary_reference"]["tube_spec"] = {
            "outer_diameter_mm": 19.05,
            "design_thickness_mm": spec["summary_thickness"],
            "length_mm": spec["summary_length"],
            "material": spec["material"],
            "source_page": spec["summary_page"],
        }

        if spec["summary_thickness"] != spec["thickness"]:
            append_unique(
                issues,
                {
                    "category": "summary_report_spec_inconsistency",
                    "field": "tube_spec.design_thickness_mm",
                    "summary_value": spec["summary_thickness"],
                    "report_and_detail_value": spec["thickness"],
                    "resolution": "Use the individual report and corrosion-results Tube Spec value in the inspection snapshot; preserve the front-summary value in summary_reference.tube_spec",
                    "source_pdf": SOURCE_PDF.name,
                    "summary_page": spec["summary_page"],
                    "report_page": report["source_report_pages"][0],
                    "detail_page": obj["tube_results_table"]["source_pages"][0],
                },
            )
        if spec["summary_length"] != spec["length"]:
            append_unique(
                issues,
                {
                    "category": "summary_report_spec_inconsistency",
                    "field": "tube_spec.length_mm",
                    "summary_value": spec["summary_length"],
                    "report_and_detail_value": spec["length"],
                    "resolution": "Use the corrosion-results Tube Spec value in the inspection snapshot; preserve the front-summary value in summary_reference.tube_spec",
                    "source_pdf": SOURCE_PDF.name,
                    "summary_page": spec["summary_page"],
                    "report_page": report["source_report_pages"][0],
                    "detail_page": obj["tube_results_table"]["source_pages"][0],
                },
            )

        report["inspection_summary"]["representative_corrosion_type"] = "External Pitting"
        obj["tube_results_table"]["columns"] = DETAIL_COLUMNS
        validation["row_calculation_status"] = "VALID_PDF_VERIFIED_SPEC"

    # Correct values that had been mapped from the representative figure rather
    # than from the report Recommendation/front summary/detail-table extrema.
    for sequence, values in SUMMARY_CORRECTIONS.items():
        obj = reports[sequence]
        validation = obj["validation"]
        validation["source_pdf_inconsistencies"] = [
            issue
            for issue in validation.get("source_pdf_inconsistencies", [])
            if issue.get("category") != "summary_detail_mismatch"
        ]
        for field, value in values.items():
            old = obj["report"]["inspection_summary"].get(field)
            set_value(obj["report"]["inspection_summary"], field, value, changes, sequence, f"report.inspection_summary.{field}")
            set_value(obj["summary_reference"], field, value, changes, sequence, f"summary_reference.{field}")
            append_unique(
                validation["normalization_corrections"],
                {
                    "category": "representative_figure_to_summary_mapping_error",
                    "field": f"report.inspection_summary.{field}",
                    "legacy_value": old,
                    "normalized_value": value,
                    "basis": "Recommendation, front summary, and corrosion-results detail extrema agree; the legacy value came from a representative figure",
                    "db_import_action": "use_normalized_value_in_inspection_snapshot",
                    "master_import_action": "do_not_update_master",
                },
            )

    # The ER-201(ER-01) source label represents equipment ER-201 and the ER-01
    # inspection section/alias in the existing DB mapping audit.
    obj = reports[8]
    report = obj["report"]
    set_value(report, "equipment_id", "ER-201", changes, 8, "report.equipment_id")
    report["inspection_scope"] = {
        "scope_code": "ER-01",
        "source_equipment_label": "ER-201(ER-01)",
    }
    report["equipment_aliases"] = ["ER-01"]
    set_value(report["iris_report_details"]["basic_information"], "equipment_number", "ER-201", changes, 8, "basic_information.equipment_number")
    for page in payload["document"]["source_page_inventory"]:
        associated = page.get("associated_report")
        if associated and associated.get("report_sequence") == 8:
            associated["equipment_id"] = "ER-201"
            associated["scope_code"] = "ER-01"
    obj["validation"]["source_pdf_inconsistencies"] = [
        issue
        for issue in obj["validation"].get("source_pdf_inconsistencies", [])
        if issue.get("category") != "unrecognized_parenthetical_suffix"
    ]
    append_unique(
        obj["validation"]["normalization_corrections"],
        {
            "category": "equipment_identity_normalization",
            "field": "report.equipment_id+report.inspection_scope.scope_code",
            "legacy_value": "ER-201(ER-01)",
            "normalized_value": "ER-201|ER-01",
            "basis": "Source report label, front summary equipment ER-201, and existing DB JSON mapping audit",
            "db_import_action": "use_normalized_value_in_inspection_snapshot",
            "master_import_action": "do_not_update_master",
        },
    )
    append_unique(
        obj["validation"]["source_pdf_inconsistencies"],
        {
            "category": "representative_figure_wall_loss_inconsistency",
            "field": "representative_defect_assessment.wall_loss_percent",
            "representative_figure_value": 42.65,
            "recommendation_and_detail_value": 23.47,
            "resolution": "Preserve 42.65 as the PDF figure annotation; use 23.47 for report summary and calculations because 2.77-2.12=0.65 mm and the detail rows agree",
            "source_pdf": SOURCE_PDF.name,
            "report_page": 78,
            "detail_page": 80,
        },
    )

    normalization = payload["document"]["inspection_scope_normalization"]
    normalization["applied_count"] = 10
    normalization["scope_codes"] = ["ER-01", "NORTH", "REAR"]
    normalization["source_equipment_labels"] = [
        "E-131D(NORTH)", "E-241B(NORTH)", "E-331B(NORTH)",
        "E-331C(NORTH)", "E-331D(NORTH)", "E-341A(NORTH)",
        "E-341C(NORTH)", "ER-201(ER-01)", "ER-301A(REAR)",
        "ER-301B(REAR)",
    ]

    # Dataset and integrity gates.
    if len(payload["inspection_reports"]) != 10:
        raise AssertionError("Expected 10 reports")
    row_count = sum(len(obj["tube_results_table"]["records"]) for obj in payload["inspection_reports"])
    if row_count != 79:
        raise AssertionError(f"Expected 79 detail rows, got {row_count}")
    for sequence, obj in reports.items():
        rows = obj["tube_results_table"]["records"]
        summary = obj["report"]["inspection_summary"]
        validation = obj["validation"]
        if len(rows) != summary["inspected_tube_count"]:
            raise AssertionError(f"Sequence {sequence}: inspected count mismatch")
        calc_min = min(row["minimum_wall_thickness_mm"] for row in rows)
        calc_max = max(row["wall_loss_percent"] for row in rows)
        if calc_min != validation["calculated_minimum_thickness_mm"]:
            raise AssertionError(f"Sequence {sequence}: validation minimum mismatch")
        if calc_max != validation["calculated_maximum_wall_loss_percent"]:
            raise AssertionError(f"Sequence {sequence}: validation maximum mismatch")
        if summary["minimum_remaining_thickness_mm"] != calc_min:
            raise AssertionError(f"Sequence {sequence}: summary minimum mismatch")
        if summary["maximum_wall_loss_percent"] != calc_max:
            raise AssertionError(f"Sequence {sequence}: summary maximum mismatch")

    payload["document"].setdefault("correction_history", []).append(
        {
            "correction_id": "PDF_FULL_REVIEW_2020_PE_20260825",
            "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Full visual review of front summary and every report/map/results object; tube specifications, summary mappings, identity scope, and detail schema normalized",
            "source_pdf": str(SOURCE_PDF),
            "report_count": 10,
            "tube_result_count": 79,
            "master_data_action": "do_not_update_master",
            "db_action": "not_applied",
        }
    )

    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after_hash = sha256(TARGET)
    manifest = {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_pdf": str(SOURCE_PDF),
        "target_json": str(TARGET),
        "backup_json": str(backup_dir / TARGET.name),
        "sha256_before": before_hash,
        "sha256_after": after_hash,
        "reports": 10,
        "tube_result_rows": 79,
        "field_change_count": len(changes),
        "master_data_action": "do_not_update_master",
        "db_action": "not_applied",
        "changes": changes,
    }
    manifest_path = output_dir / "2020PE_PDF_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target": str(TARGET), "backup": str(backup_dir / TARGET.name), "manifest": str(manifest_path), "changes": len(changes)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
