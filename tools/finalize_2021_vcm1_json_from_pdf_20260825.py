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

from audit_2020_vcm1_pdf_json_20260825 import parse_result_rows


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2021VCM1_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2021_1P_VCM1.pdf"

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

# The legacy extractor could not associate front-Summary rows that omit the
# repeated equipment name.  These values are transcribed from pages 9 and 11.
FRONT_REFERENCE_OVERRIDES = {
    2: (4, "E-121B(BTM)", 25.4, 2.77, 3657.0, "70/30-CU/NI", 104, 5, 9),
    3: (3, "E-121B(TOP)", 25.4, 2.77, 3657.0, "70/30-CU/NI", 104, 5, 9),
    5: (7, "E-205B(BTM)", 25.4, 2.77, 2438.0, "70/30-CU/NI", 18, 3, 9),
    6: (6, "E-205B(TOP)", 25.4, 2.77, 2438.0, "70/30-CU/NI", 18, 4, 9),
    15: (20, "E-331B(BTM)", 25.4, 2.77, 3657.0, "70/30-CU/NI", 20, 5, 11),
    16: (19, "E-331B(TOP)", 25.4, 2.77, 3657.0, "70/30-CU/NI", 20, 5, 11),
    28: (21, "E-332-1", 25.4, 2.11, 5000.0, "MONEL", 151, 5, 11),
    29: (22, "E-332-2", 25.4, 2.11, 5000.0, "MONEL", 151, 5, 11),
}


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


def parse_detail_spec(text: str) -> dict[str, float]:
    match = re.search(
        r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+"
        r"(\d+(?:\.\d+)?)\s+L",
        text,
    )
    if not match:
        raise AssertionError("Tube Spec row could not be parsed")
    od, thickness, length = (float(value) for value in match.groups())
    return {
        "outer_diameter_mm": od,
        "design_thickness_mm": thickness,
        "length_mm": length,
    }


def parse_recommendation(text: str) -> tuple[int, int, float, float, float]:
    lines = text.splitlines()
    line1 = next(line for line in lines if line.strip().startswith("1."))
    line3 = next(line for line in lines if line.strip().startswith("3."))
    numbers1 = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", line1)]
    numbers3 = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", line3)]
    if len(numbers1) < 3 or len(numbers3) < 4:
        raise AssertionError(f"Recommendation could not be parsed: {line1} / {line3}")
    return (
        int(numbers1[-2]),
        int(numbers1[-1]),
        numbers3[-3],
        numbers3[-2],
        numbers3[-1],
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
            "legacy_reference": legacy,
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
        "legacy_reference": None,
    }


def map_total(tube_map: dict[str, Any]) -> int | None:
    value = tube_map.get("total_tubes")
    if value is None:
        value = (tube_map.get("legend_counts") or {}).get("Total Tubes")
    return value


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = {
        item["report"]["report_sequence"]: item
        for item in payload["inspection_reports"]
    }
    if set(reports) != set(range(1, 31)):
        raise AssertionError(f"Unexpected report sequences: {sorted(reports)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = (
        PROJECT / "backups" / f"json_before_2021_vcm1_finalization_{timestamp}"
    )
    output_dir = (
        PROJECT
        / "outputs"
        / "json_pdf_finalization_2021_vcm1_20260825"
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
            rebuilt_categories = {
                "summary_detail_mismatch",
                "front_summary_individual_report_total_inconsistency",
                "report_tube_map_total_inconsistency",
                "front_summary_report_detail_spec_inconsistency",
                "recommendation_detail_extrema_inconsistency",
                "pdf_reported_row_calculation_variance",
                "detail_equipment_label_inconsistency",
            }
            issues[:] = [
                issue
                for issue in issues
                if issue.get("category") not in rebuilt_categories
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

            # Restore the exact PDF row order and corrosion classification.
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

            quantity = re.search(r"Tube ID Q'ty:\s*(\d+)", detail_text)
            if not quantity or int(quantity.group(1)) != len(records):
                raise AssertionError(f"Sequence {sequence}: Tube ID Q'ty mismatch")

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

            total, tested, reported_min, reported_max, average = parse_recommendation(
                report_text
            )
            if tested != len(records):
                raise AssertionError(f"Sequence {sequence}: Recommendation count mismatch")
            detail_minimum = min(
                record["minimum_wall_thickness_mm"] for record in records
            )
            detail_maximum = max(record["wall_loss_percent"] for record in records)
            representative = next(
                record["section_corrosion_depth"]
                for record in records
                if record["wall_loss_percent"] == detail_maximum
            )
            summary_values = {
                "total_tube_count": total,
                "inspected_tube_count": tested,
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
                "average_wall_loss_percent_provenance": "reported_recommendation",
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
            if reported_min != detail_minimum or reported_max != detail_maximum:
                append_unique(
                    issues,
                    {
                        "category": "recommendation_detail_extrema_inconsistency",
                        "field": "inspection_summary.minimum_or_maximum",
                        "recommendation_minimum": reported_min,
                        "detail_minimum": detail_minimum,
                        "recommendation_maximum": reported_max,
                        "detail_maximum": detail_maximum,
                        "resolution": "Use extrema from all printed detail rows; preserve the Recommendation values as source evidence",
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

            if sequence == 5 and "E- 205(BOTTOM)" in detail_text:
                append_unique(
                    issues,
                    {
                        "category": "detail_equipment_label_inconsistency",
                        "field": "source_equipment_label",
                        "individual_report_value": "E-205B(BTM)",
                        "detail_table_value": "E-205(BOTTOM)",
                        "resolution": "Associate the contiguous report/map/detail object with E-205B BTM and preserve the printed detail label",
                        "source_pdf": SOURCE_PDF.name,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )

            table["record_count"] = len(records)
            table["columns"] = DETAIL_COLUMNS
            validation["extracted_tube_result_count"] = len(records)
            validation["reported_inspected_tube_count"] = tested
            validation["reported_vs_extracted_count_match"] = True
            validation["calculated_minimum_thickness_mm"] = detail_minimum
            validation["calculated_maximum_wall_loss_percent"] = detail_maximum
            validation["calculated_average_wall_loss_percent"] = round(
                sum(record["wall_loss_percent"] for record in records)
                / len(records),
                4,
            )

    if len(reports) != 30:
        raise AssertionError("Expected 30 reports")
    row_count = sum(
        len(item["tube_results_table"]["records"]) for item in reports.values()
    )
    if row_count != 419:
        raise AssertionError(f"Expected 419 result rows, got {row_count}")
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
        if entry.get("correction_id") != "PDF_FULL_REVIEW_2021_VCM1_20260825"
    ]
    history.append(
        {
            "correction_id": "PDF_FULL_REVIEW_2021_VCM1_20260825",
            "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Full review of 157 PDF pages, 30 report/map/results objects and all 419 detail rows; Summary, exact Tube Specs, corrosion classification, equipment/test conditions, personnel and Recommendations verified",
            "source_pdf": str(SOURCE_PDF),
            "report_count": 30,
            "tube_result_count": 419,
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
        "reports": 30,
        "tube_result_rows": 419,
        "field_change_count": len(changes),
        "master_data_action": "do_not_update_master",
        "db_action": "not_applied",
        "changes": changes,
    }
    manifest_path = (
        output_dir / "2021VCM1_PDF_FINALIZATION_MANIFEST_20260825.json"
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
