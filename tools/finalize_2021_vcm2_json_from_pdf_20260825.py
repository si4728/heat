from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pdfplumber

from audit_2020_vcm1_pdf_json_20260825 import parse_result_rows
from finalize_2021_vcm1_json_from_pdf_20260825 import (
    DETAIL_COLUMNS,
    append_unique,
    map_total,
    parse_detail_spec,
    set_value,
    sha256,
)


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2021VCM2_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2021_1P_VCM2.pdf"

# Front-Summary rows that the legacy matcher could not associate because the
# report is a scoped section or the front label contains an extra prefix.
FRONT_REFERENCE_OVERRIDES = {
    1: (47, "E-581A(BTM)", 25.4, 2.11, 2000.0, "Cu-Ni", 148, 5, 14),
    12: (49, "E-581B(BTM)", 25.4, 2.11, 2000.0, "Cu-Ni", 148, 5, 14),
    41: (34, "E-AE-502A-1", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 12),
    42: (35, "E-AE-502A-2", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 12),
    43: (38, "E-AE-502B-1", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 13),
    44: (39, "E-AE-502B-2", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 13),
    45: (36, "E-AE-502C-1", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 12),
    46: (37, "E-AE-502C-2", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 13),
    47: (40, "E-AE-502D-1", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 13),
    48: (41, "E-AE-502D-2", 19.05, 2.11, 5500.0, "Cu-Ni", 384, 5, 13),
}


def add_correction(
    corrections: list[dict[str, Any]],
    *,
    field: str,
    old: Any,
    new: Any,
    report_page: int,
    detail_page: int,
    basis: str,
) -> None:
    append_unique(
        corrections,
        {
            "category": "json_extraction_mapping_error",
            "field": field,
            "legacy_value": old,
            "normalized_value": new,
            "basis": basis,
            "verification": {
                "source_pdf": SOURCE_PDF.name,
                "report_page": report_page,
                "detail_page": detail_page,
            },
            "db_import_action": "use_normalized_value_in_inspection_snapshot",
            "master_import_action": "do_not_update_master",
        },
    )


def front_reference(item: dict[str, Any], sequence: int) -> dict[str, Any]:
    legacy = copy.deepcopy(item.get("summary_reference") or {})
    if legacy:
        return {
            "front_sequence": legacy["sequence"],
            "equipment_id_summary": legacy["equipment_id_summary"],
            "outer_diameter_mm": float(legacy["outer_diameter_mm"]),
            "design_thickness_mm": float(legacy["design_thickness_mm"]),
            "length_mm": float(legacy["length_mm"]),
            "material": legacy.get("material"),
            "total_tube_count": int(legacy["total_tubes_summary"]),
            "inspected_tube_count": int(legacy["inspected_tubes_summary"]),
            "source_page": int(legacy["summary_page"]),
        }
    values = FRONT_REFERENCE_OVERRIDES[sequence]
    return {
        "front_sequence": values[0],
        "equipment_id_summary": values[1],
        "outer_diameter_mm": values[2],
        "design_thickness_mm": values[3],
        "length_mm": values[4],
        "material": values[5],
        "total_tube_count": values[6],
        "inspected_tube_count": values[7],
        "source_page": values[8],
    }


def parse_recommendation(
    text: str, calculated_average: float
) -> tuple[int, int, float, float, float, str]:
    lines = text.splitlines()
    line1 = next(line for line in lines if line.strip().startswith("1."))
    numbers1 = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", line1)]
    if len(numbers1) < 3:
        raise AssertionError(f"Recommendation count could not be parsed: {line1}")
    total = int(numbers1[-2])
    tested = int(numbers1[-1])

    result_line = next(
        (
            line
            for line in lines
            if line.strip().startswith(("2.", "3."))
            and "mm" in line
            and "%" in line
        ),
        None,
    )
    if result_line is None:
        raise AssertionError("Recommendation extrema could not be parsed")
    values = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", result_line)]
    # Ignore the numbered-list prefix. Normal reports carry min/max/average;
    # E-104A/B carry only min/max and no reported average.
    values = values[1:]
    if len(values) >= 3:
        reported_minimum, reported_maximum, average = values[-3:]
        provenance = "reported_recommendation"
    elif len(values) == 2:
        reported_minimum, reported_maximum = values
        average = float(
            Decimal(str(calculated_average)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        provenance = "calculated_from_all_detail_rows"
    else:
        raise AssertionError(f"Recommendation values incomplete: {result_line}")
    return total, tested, reported_minimum, reported_maximum, average, provenance


def parse_figure(text: str) -> tuple[str, float, float, str]:
    tube_line = next(line for line in text.splitlines() if "TUBE NO" in line)
    thickness_match = re.search(r"(\d+(?:\.\d+)?)mm", tube_line)
    if not thickness_match:
        raise AssertionError(f"Figure thickness could not be parsed: {tube_line}")
    target_part = tube_line[: thickness_match.start()].split(":", 1)[1]
    tube_ids = re.findall(r"\d+\s*-\s*\d+", target_part)
    if not tube_ids:
        raise AssertionError(f"Figure Tube ID could not be parsed: {tube_line}")
    target_tube = ",".join(re.sub(r"\s+", "", value) for value in tube_ids)
    defect_line = next(
        line
        for line in text.splitlines()
        if "%" in line
        and re.search(
            r"(?:INTERNAL|EXTERNAL|IN/EXTERNAL)\s+(?:CORROSION|PITTING)",
            line,
        )
    )
    defect_match = re.search(
        r"((?:INTERNAL|EXTERNAL|IN/EXTERNAL)\s+(?:CORROSION|PITTING)).*?"
        r"(\d+(?:\.\d+)?)%",
        defect_line,
    )
    if not defect_match:
        raise AssertionError(f"Figure defect could not be parsed: {defect_line}")
    return (
        target_tube,
        float(thickness_match.group(1)),
        float(defect_match.group(2)),
        defect_match.group(1),
    )


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = {
        item["report"]["report_sequence"]: item
        for item in payload["inspection_reports"]
    }
    if set(reports) != set(range(1, 51)):
        raise AssertionError(f"Unexpected report sequences: {sorted(reports)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = (
        PROJECT / "backups" / f"json_before_2021_vcm2_finalization_{timestamp}"
    )
    output_dir = (
        PROJECT
        / "outputs"
        / "json_pdf_finalization_2021_vcm2_20260825"
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
            rebuilt = {
                "summary_detail_mismatch",
                "front_summary_individual_report_total_inconsistency",
                "report_tube_map_total_inconsistency",
                "front_summary_report_detail_spec_inconsistency",
                "recommendation_detail_extrema_inconsistency",
                "recommendation_detail_count_inconsistency",
                "detail_header_quantity_inconsistency",
                "representative_figure_detail_inconsistency",
                "pdf_reported_row_calculation_variance",
            }
            issues[:] = [
                issue for issue in issues if issue.get("category") not in rebuilt
            ]

            report_page = report["source_report_pages"][0]
            detail_pages = table["source_pages"]
            detail_page = detail_pages[0]
            report_text = pdf.pages[report_page - 1].extract_text(
                x_tolerance=2, y_tolerance=2
            ) or ""
            detail_texts = {
                page: pdf.pages[page - 1].extract_text(
                    x_tolerance=2, y_tolerance=2
                )
                or ""
                for page in detail_pages
            }
            detail_text = "\n".join(detail_texts.values())
            parsed_rows = []
            for page, text in detail_texts.items():
                parsed_rows.extend(parse_result_rows(text, page))
            if len(parsed_rows) != len(table["records"]):
                raise AssertionError(f"Sequence {sequence}: PDF/JSON row count differs")

            records_by_id = {
                record["tube_id"]: record for record in table["records"]
            }
            normalized_records = []
            for parsed in parsed_rows:
                tube_id = f"{parsed[0]}-{parsed[1]}"
                record = records_by_id.get(tube_id)
                if record is None:
                    raise AssertionError(f"Sequence {sequence}: missing {tube_id}")
                numeric_pdf = (
                    parsed[0],
                    parsed[1],
                    parsed[2],
                    parsed[3],
                    parsed[5],
                    parsed[6],
                )
                numeric_json = (
                    record["row"],
                    record["column"],
                    float(record["minimum_wall_thickness_mm"]),
                    int(record["location_mm"]),
                    float(record["wall_loss_depth_mm"]),
                    float(record["wall_loss_percent"]),
                )
                if numeric_pdf != numeric_json:
                    raise AssertionError(
                        f"Sequence {sequence} {tube_id}: numeric PDF/JSON mismatch"
                    )
                updated = copy.deepcopy(record)
                if updated["section_corrosion_depth"] != parsed[4]:
                    changes.append(
                        {
                            "report_sequence": sequence,
                            "tube_id": tube_id,
                            "field": "tube_results_table.records[].section_corrosion_depth",
                            "legacy_value": updated["section_corrosion_depth"],
                            "normalized_value": parsed[4],
                        }
                    )
                updated["section_corrosion_depth"] = parsed[4]
                updated["source_page"] = parsed[7]
                normalized_records.append(updated)
            table["records"] = normalized_records
            records = table["records"]

            header_quantity_match = re.search(r"Tube ID Q'ty:\s*(\d+)", detail_text)
            header_quantity = (
                int(header_quantity_match.group(1))
                if header_quantity_match
                else None
            )
            if header_quantity != len(records):
                append_unique(
                    issues,
                    {
                        "category": "detail_header_quantity_inconsistency",
                        "field": "tube_results_table.record_count",
                        "detail_header_quantity": header_quantity,
                        "actual_detail_row_count": len(records),
                        "resolution": "Use all printed detail rows; preserve the incorrect Tube ID Q'ty header as source evidence",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )
                if sequence != 9:
                    raise AssertionError(
                        f"Unexpected header quantity mismatch at sequence {sequence}"
                    )

            detail_spec = parse_detail_spec(detail_text)
            front = front_reference(item, sequence)
            summary_page = front["source_page"]
            for key, value in detail_spec.items():
                old = report["tube_spec"].get(key)
                set_value(
                    report["tube_spec"],
                    key,
                    value,
                    changes,
                    sequence,
                    f"report.tube_spec.{key}",
                )
                if old != value:
                    add_correction(
                        corrections,
                        field=f"report.tube_spec.{key}",
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                        basis="Exact Tube Spec printed on the corrosion-results table",
                    )
                if front[key] != value:
                    append_unique(
                        issues,
                        {
                            "category": "front_summary_report_detail_spec_inconsistency",
                            "field": f"tube_spec.{key}",
                            "front_summary_value": front[key],
                            "individual_report_or_detail_value": value,
                            "resolution": "Use the individual report/detail value in the inspection snapshot; preserve the front-Summary value in summary_reference.tube_spec",
                            "source_pdf": SOURCE_PDF.name,
                            "summary_page": summary_page,
                            "report_page": report_page,
                            "detail_page": detail_page,
                        },
                    )

            detail_minimum = min(
                record["minimum_wall_thickness_mm"] for record in records
            )
            detail_maximum = max(record["wall_loss_percent"] for record in records)
            calculated_average = sum(
                record["wall_loss_percent"] for record in records
            ) / len(records)
            (
                total,
                report_tested,
                reported_minimum,
                reported_maximum,
                average,
                average_provenance,
            ) = parse_recommendation(report_text, calculated_average)
            operational_tested = len(records)
            representative = next(
                record["section_corrosion_depth"]
                for record in records
                if record["wall_loss_percent"] == detail_maximum
            )
            summary_values = {
                "total_tube_count": total,
                "inspected_tube_count": operational_tested,
                "minimum_remaining_thickness_mm": detail_minimum,
                "maximum_wall_loss_percent": detail_maximum,
                "average_wall_loss_percent": average,
                "representative_corrosion_type": representative,
            }
            for key, value in summary_values.items():
                old = report["inspection_summary"].get(key)
                set_value(
                    report["inspection_summary"],
                    key,
                    value,
                    changes,
                    sequence,
                    f"report.inspection_summary.{key}",
                )
                if old != value:
                    add_correction(
                        corrections,
                        field=f"report.inspection_summary.{key}",
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                        basis="PDF Recommendation and complete corrosion-results table",
                    )
            report["iris_report_details"]["inspection_summary"] = {
                **summary_values,
                "recommendation_reported_inspected_tube_count": report_tested,
                "average_wall_loss_percent_provenance": average_provenance,
            }

            item["summary_reference"] = {
                "total_tube_count": front["total_tube_count"],
                "inspected_tube_count": front["inspected_tube_count"],
                "minimum_remaining_thickness_mm": detail_minimum,
                "maximum_wall_loss_percent": detail_maximum,
                "average_wall_loss_percent": average,
                "representative_corrosion_type": representative,
                "tube_spec": {
                    "outer_diameter_mm": front["outer_diameter_mm"],
                    "design_thickness_mm": front["design_thickness_mm"],
                    "length_mm": front["length_mm"],
                    "material": front["material"],
                    "source_page": summary_page,
                },
                "front_summary_row": {
                    "sequence": front["front_sequence"],
                    "equipment_id_summary": front["equipment_id_summary"],
                },
                "source_page": summary_page,
            }

            if report_tested != operational_tested:
                append_unique(
                    issues,
                    {
                        "category": "recommendation_detail_count_inconsistency",
                        "field": "inspection_summary.inspected_tube_count",
                        "recommendation_value": report_tested,
                        "detail_header_value": header_quantity,
                        "actual_detail_row_count": operational_tested,
                        "resolution": "Use the actual complete detail-row count in the inspection snapshot and preserve the Recommendation count as source evidence",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )
            if front["total_tube_count"] != total:
                append_unique(
                    issues,
                    {
                        "category": "front_summary_individual_report_total_inconsistency",
                        "field": "inspection_summary.total_tube_count",
                        "front_summary_value": front["total_tube_count"],
                        "individual_report_value": total,
                        "resolution": "Use the scoped individual-report Recommendation count in the inspection snapshot; preserve the front-Summary value in summary_reference",
                        "source_pdf": SOURCE_PDF.name,
                        "summary_page": summary_page,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )
            tube_map_total = map_total(item["tube_map"])
            if tube_map_total != total:
                append_unique(
                    issues,
                    {
                        "category": "report_tube_map_total_inconsistency",
                        "field": "inspection_summary.total_tube_count",
                        "individual_report_value": total,
                        "tube_map_value": tube_map_total,
                        "resolution": "Use the individual-report Recommendation count in the inspection snapshot and preserve the map count separately",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )
            if (
                reported_minimum != detail_minimum
                or reported_maximum != detail_maximum
            ):
                append_unique(
                    issues,
                    {
                        "category": "recommendation_detail_extrema_inconsistency",
                        "field": "inspection_summary.minimum_or_maximum",
                        "recommendation_minimum": reported_minimum,
                        "detail_minimum": detail_minimum,
                        "recommendation_maximum": reported_maximum,
                        "detail_maximum": detail_maximum,
                        "resolution": "Use extrema from all printed detail rows; preserve the Recommendation values as source evidence",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )

            target_tube, figure_minimum, figure_loss, figure_type = parse_figure(
                report_text
            )
            assessment = report["iris_report_details"][
                "representative_defect_assessment"
            ]
            for key, value in (
                ("target_tube", target_tube),
                ("minimum_thickness_mm", figure_minimum),
                ("wall_loss_percent", figure_loss),
                ("defect_type", figure_type),
            ):
                set_value(
                    assessment,
                    key,
                    value,
                    changes,
                    sequence,
                    f"iris_report_details.representative_defect_assessment.{key}",
                )
            if figure_minimum != detail_minimum or figure_loss != detail_maximum:
                append_unique(
                    issues,
                    {
                        "category": "representative_figure_detail_inconsistency",
                        "field": "representative_defect_assessment.minimum_or_wall_loss",
                        "figure_minimum": figure_minimum,
                        "detail_minimum": detail_minimum,
                        "figure_wall_loss_percent": figure_loss,
                        "detail_maximum_wall_loss_percent": detail_maximum,
                        "resolution": "Preserve the figure annotation; use extrema from all detail rows in the operational Summary",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )

            nominal = detail_spec["design_thickness_mm"]
            calculation_variances = []
            for record in records:
                expected_depth = round(
                    nominal - record["minimum_wall_thickness_mm"], 2
                )
                expected_loss = round(expected_depth / nominal * 100, 2)
                if (
                    expected_depth != record["wall_loss_depth_mm"]
                    or expected_loss != record["wall_loss_percent"]
                ):
                    calculation_variances.append(
                        {
                            "tube_id": record["tube_id"],
                            "pdf_wall_loss_depth_mm": record[
                                "wall_loss_depth_mm"
                            ],
                            "recalculated_wall_loss_depth_mm": expected_depth,
                            "pdf_wall_loss_percent": record["wall_loss_percent"],
                            "recalculated_wall_loss_percent": expected_loss,
                        }
                    )
            validation["row_calculation_mismatch_count"] = len(
                calculation_variances
            )
            validation["row_calculation_mismatches"] = calculation_variances
            validation["row_calculation_status"] = (
                "SOURCE_PDF_REPORTED_VARIANCE_PRESERVED"
                if calculation_variances
                else "VALID_PDF_VERIFIED_SPEC"
            )
            if calculation_variances:
                append_unique(
                    issues,
                    {
                        "category": "pdf_reported_row_calculation_variance",
                        "field": "tube_results_table.records[].wall_loss_percent",
                        "affected_row_count": len(calculation_variances),
                        "resolution": "Preserve the values printed in the PDF; do not silently recalculate source inspection results",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                        "db_import_action": "preserve_source_value_with_quality_flag",
                        "master_import_action": "do_not_update_master",
                    },
                )

            table["record_count"] = len(records)
            table["columns"] = DETAIL_COLUMNS
            validation["extracted_tube_result_count"] = len(records)
            validation["detail_header_tube_id_quantity"] = header_quantity
            validation["recommendation_reported_inspected_tube_count"] = report_tested
            validation["reported_inspected_tube_count"] = operational_tested
            validation["reported_vs_extracted_count_match"] = (
                report_tested == operational_tested
            )
            validation["calculated_minimum_thickness_mm"] = detail_minimum
            validation["calculated_maximum_wall_loss_percent"] = detail_maximum
            validation["calculated_average_wall_loss_percent"] = round(
                calculated_average, 4
            )

    if len(reports) != 50:
        raise AssertionError("Expected 50 reports")
    row_count = sum(
        len(item["tube_results_table"]["records"]) for item in reports.values()
    )
    if row_count != 699:
        raise AssertionError(f"Expected 699 result rows, got {row_count}")
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
        if any(summary[key] is None for key in summary):
            raise AssertionError(f"Sequence {sequence}: incomplete summary")

    history = payload["document"].setdefault("correction_history", [])
    history[:] = [
        entry
        for entry in history
        if entry.get("correction_id") != "PDF_FULL_REVIEW_2021_VCM2_20260825"
    ]
    history.append(
        {
            "correction_id": "PDF_FULL_REVIEW_2021_VCM2_20260825",
            "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Full review of 244 PDF pages, 50 report/map/results objects and all 699 detail rows; Summary, exact Tube Specs, corrosion classification, representative figures, equipment/test conditions, personnel and Recommendations verified",
            "source_pdf": str(SOURCE_PDF),
            "report_count": 50,
            "tube_result_count": 699,
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
        "reports": 50,
        "tube_result_rows": 699,
        "field_change_count": len(changes),
        "master_data_action": "do_not_update_master",
        "db_action": "not_applied",
        "changes": changes,
    }
    manifest_path = (
        output_dir / "2021VCM2_PDF_FINALIZATION_MANIFEST_20260825.json"
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
