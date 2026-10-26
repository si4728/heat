from __future__ import annotations

import copy
import hashlib
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pdfplumber

from audit_2020_vcm1_pdf_json_20260825 import parse_result_rows


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2020VCM2_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2020_1P_VCM2.pdf"

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

FRONT_TOTAL_OVERRIDES = {
    2: 34,  # E-13 front Summary/Tube Map covers 34; SOUTH report covers 17.
}

BTM_BOM_SEQUENCES = (34, 36)


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
    outer_diameter, thickness, length = (float(value) for value in match.groups())
    return {
        "outer_diameter_mm": outer_diameter,
        "design_thickness_mm": thickness,
        "length_mm": length,
    }


def parse_front_specs(pdf: pdfplumber.PDF) -> dict[int, dict[str, float]]:
    result: dict[int, dict[str, float]] = {}
    pattern = re.compile(
        r"^\s*(\d+)\s+.*?(50\.80|25\.40|19\.05|16\.00)\s+"
        r"(\d+\.\d+)\s+(\d+)\b"
    )
    for page_number in range(9, 15):
        text = pdf.pages[page_number - 1].extract_text(
            x_tolerance=2, y_tolerance=2
        ) or ""
        for line in text.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            sequence = int(match.group(1))
            result[sequence] = {
                "outer_diameter_mm": float(match.group(2)),
                "design_thickness_mm": float(match.group(3)),
                "length_mm": float(match.group(4)),
                "source_page": page_number,
            }
    if set(result) != set(range(1, 43)):
        raise AssertionError(
            f"Front Summary specifications incomplete: {sorted(result)}"
        )
    return result


def parse_report_total_and_average(
    text: str, calculated_average: float
) -> tuple[int, int, float, str]:
    lines = text.splitlines()
    line1 = next(line for line in lines if line.strip().startswith("1."))
    numbers1 = re.findall(r"\d+(?:\.\d+)?", line1)
    if len(numbers1) < 3:
        raise AssertionError(f"Recommendation total/sample not parsed: {line1}")
    total = int(float(numbers1[-2]))
    tested = int(float(numbers1[-1]))

    line3 = next(
        (line for line in lines if line.strip().startswith("3.")), ""
    )
    numbers3 = re.findall(r"\d+(?:\.\d+)?", line3)
    if len(numbers3) >= 4:
        average = float(numbers3[-1])
        provenance = "reported_recommendation"
    else:
        average = float(
            Decimal(str(calculated_average)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        provenance = "calculated_from_all_detail_rows"
    return total, tested, average, provenance


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
    if set(reports) != set(range(1, 43)):
        raise AssertionError(f"Unexpected report sequences: {sorted(reports)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = (
        PROJECT / "backups" / f"json_before_2020_vcm2_finalization_{timestamp}"
    )
    output_dir = (
        PROJECT
        / "outputs"
        / "json_pdf_finalization_2020_vcm2_20260825"
        / timestamp
    )
    backup_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before_hash = sha256(TARGET)
    changes: list[dict[str, Any]] = []
    report_totals: dict[int, int] = {}

    with pdfplumber.open(SOURCE_PDF) as pdf:
        front_specs = parse_front_specs(pdf)
        for sequence, item in reports.items():
            report = item["report"]
            table = item["tube_results_table"]
            validation = item["validation"]
            issues = validation.setdefault("source_pdf_inconsistencies", [])
            corrections = validation.setdefault("normalization_corrections", [])
            # Legacy VCM2 objects do not carry source_summary_pages on the
            # report itself.  The front-summary parser is authoritative for
            # the sequence-to-page mapping and covers all 42 reports.
            summary_page = front_specs[sequence]["source_page"]
            report_page = report["source_report_pages"][0]
            detail_page = table["source_pages"][0]
            report_text = pdf.pages[report_page - 1].extract_text(
                x_tolerance=2, y_tolerance=2
            ) or ""
            detail_texts = {
                page_number: pdf.pages[page_number - 1].extract_text(
                    x_tolerance=2, y_tolerance=2
                )
                or ""
                for page_number in table["source_pages"]
            }
            detail_text = "\n".join(detail_texts.values())
            parsed_rows = []
            for page_number, text in detail_texts.items():
                parsed_rows.extend(parse_result_rows(text, page_number))
            if len(parsed_rows) != len(table["records"]):
                raise AssertionError(
                    f"Sequence {sequence}: PDF/JSON row count differs"
                )

            # Restore exact printed row order and corrosion type. Numeric fields
            # are asserted equal before updating the text classification.
            by_tube_id = {record["tube_id"]: record for record in table["records"]}
            normalized_records = []
            for parsed in parsed_rows:
                tube_id = f"{parsed[0]}-{parsed[1]}"
                record = by_tube_id.get(tube_id)
                if record is None:
                    raise AssertionError(
                        f"Sequence {sequence}: missing JSON tube {tube_id}"
                    )
                numeric_json = (
                    record["row"],
                    record["column"],
                    float(record["minimum_wall_thickness_mm"]),
                    int(record["location_mm"]),
                    float(record["wall_loss_depth_mm"]),
                    float(record["wall_loss_percent"]),
                    record["source_page"],
                )
                numeric_pdf = (
                    parsed[0],
                    parsed[1],
                    parsed[2],
                    parsed[3],
                    parsed[5],
                    parsed[6],
                    parsed[7],
                )
                if numeric_json != numeric_pdf:
                    raise AssertionError(
                        f"Sequence {sequence} {tube_id}: numeric value differs"
                    )
                old_type = record["section_corrosion_depth"]
                if old_type != parsed[4]:
                    set_value(
                        record,
                        "section_corrosion_depth",
                        parsed[4],
                        changes,
                        sequence,
                        f"tube_results_table.records[{tube_id}].section_corrosion_depth",
                    )
                    add_correction(
                        corrections,
                        field=f"tube_results_table.records[{tube_id}].section_corrosion_depth",
                        old=old_type,
                        new=parsed[4],
                        report_page=report_page,
                        detail_page=parsed[7],
                        basis="Exact PDF corrosion-results row classification",
                    )
                normalized_records.append(record)
            if [record["tube_id"] for record in normalized_records] != [
                record["tube_id"] for record in table["records"]
            ]:
                changes.append(
                    {
                        "report_sequence": sequence,
                        "field": "tube_results_table.records.order",
                        "legacy_value": "json_order",
                        "normalized_value": "pdf_printed_row_order",
                    }
                )
            table["records"] = normalized_records
            table["record_count"] = len(normalized_records)
            table["columns"] = DETAIL_COLUMNS

            old_tube_spec = copy.deepcopy(report["tube_spec"])
            detail_spec = parse_detail_spec(detail_text)
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
                        basis="Exact corrosion-results Tube Spec value",
                    )

            records = table["records"]
            detail_minimum = min(
                record["minimum_wall_thickness_mm"] for record in records
            )
            detail_maximum = max(record["wall_loss_percent"] for record in records)
            calculated_average = sum(
                record["wall_loss_percent"] for record in records
            ) / len(records)
            total, tested, average, average_provenance = (
                parse_report_total_and_average(report_text, calculated_average)
            )
            report_totals[sequence] = total
            if tested != len(records):
                raise AssertionError(
                    f"Sequence {sequence}: Recommendation/sample row count differs"
                )
            maximum_rows = [
                record
                for record in records
                if record["wall_loss_percent"] == detail_maximum
            ]
            corrosion_type = maximum_rows[0]["section_corrosion_depth"]

            summary = report["inspection_summary"]
            summary_values = {
                "total_tube_count": total,
                "inspected_tube_count": tested,
                "minimum_remaining_thickness_mm": detail_minimum,
                "maximum_wall_loss_percent": detail_maximum,
                "average_wall_loss_percent": average,
                "representative_corrosion_type": corrosion_type,
            }
            for key, value in summary_values.items():
                old = summary.get(key)
                field = f"report.inspection_summary.{key}"
                set_value(summary, key, value, changes, sequence, field)
                if old != value:
                    add_correction(
                        corrections,
                        field=field,
                        old=old,
                        new=value,
                        report_page=report_page,
                        detail_page=detail_page,
                        basis=(
                            "PDF Recommendation and all corrosion-results rows"
                            if key != "average_wall_loss_percent"
                            else f"PDF summary basis: {average_provenance}"
                        ),
                    )

            report["iris_report_details"]["inspection_summary"] = {
                **summary_values,
                "average_wall_loss_percent_provenance": average_provenance,
            }

            front_spec = front_specs[sequence]
            item["summary_reference"] = {
                "total_tube_count": FRONT_TOTAL_OVERRIDES.get(sequence, total),
                "inspected_tube_count": tested,
                "minimum_remaining_thickness_mm": detail_minimum,
                "maximum_wall_loss_percent": detail_maximum,
                "average_wall_loss_percent": average,
                "representative_corrosion_type": corrosion_type,
                "tube_spec": {
                    "outer_diameter_mm": front_spec["outer_diameter_mm"],
                    "design_thickness_mm": front_spec["design_thickness_mm"],
                    "length_mm": front_spec["length_mm"],
                    "material": old_tube_spec.get("material"),
                    "source_page": front_spec["source_page"],
                },
                "source_page": summary_page,
            }

            for key in (
                "outer_diameter_mm",
                "design_thickness_mm",
                "length_mm",
            ):
                if front_spec[key] != detail_spec[key]:
                    append_unique(
                        issues,
                        {
                            "category": "front_summary_report_detail_spec_inconsistency",
                            "field": f"tube_spec.{key}",
                            "front_summary_value": front_spec[key],
                            "individual_report_or_detail_value": detail_spec[key],
                            "resolution": "Use the individual report/corrosion-results value in the inspection snapshot; preserve the front-summary value in summary_reference.tube_spec",
                            "source_pdf": SOURCE_PDF.name,
                            "summary_page": summary_page,
                            "report_page": report_page,
                            "detail_page": detail_page,
                        },
                    )
            if FRONT_TOTAL_OVERRIDES.get(sequence, total) != total:
                append_unique(
                    issues,
                    {
                        "category": "front_summary_report_scope_total_inconsistency",
                        "field": "inspection_summary.total_tube_count",
                        "front_summary_value": FRONT_TOTAL_OVERRIDES[sequence],
                        "scoped_individual_report_value": total,
                        "resolution": "Use the scoped individual-report count in the inspection snapshot; preserve the equipment-wide front-summary value in summary_reference",
                        "source_pdf": SOURCE_PDF.name,
                        "summary_page": summary_page,
                        "report_page": report_page,
                        "detail_page": detail_page,
                    },
                )

            validation["extracted_tube_result_count"] = len(records)
            validation["reported_inspected_tube_count"] = tested
            validation["reported_vs_extracted_count_match"] = tested == len(records)
            validation["calculated_minimum_thickness_mm"] = detail_minimum
            validation["calculated_maximum_wall_loss_percent"] = detail_maximum
            validation["calculated_average_wall_loss_percent"] = round(
                calculated_average, 4
            )
            validation["row_calculation_mismatch_count"] = 0
            validation["row_calculation_mismatches"] = []
            validation["row_calculation_status"] = "VALID_PDF_VERIFIED_SPEC"

    # Preserve map totals independently when the map covers a different scope
    # or contains a source-PDF total inconsistency.
    for sequence, item in reports.items():
        total = report_totals[sequence]
        tube_map_total = map_total(item["tube_map"])
        if tube_map_total != total:
            append_unique(
                item["validation"]["source_pdf_inconsistencies"],
                {
                    "category": "report_tube_map_total_inconsistency",
                    "field": "tube_map.total_tubes",
                    "individual_report_value": total,
                    "tube_map_value": tube_map_total,
                    "resolution": "Use the individual-report scoped total in inspection_summary and preserve the printed Tube Map count separately",
                    "source_pdf": SOURCE_PDF.name,
                    "report_page": item["report"]["source_report_pages"][0],
                    "detail_page": item["tube_results_table"]["source_pages"][0],
                },
            )

    # BOM is the printed Bottom-section spelling; BTM remains canonical.
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
                "legacy_value": "BOM",
                "normalized_value": "BTM",
                "basis": "User-confirmed Bottom inspection-scope interpretation; preserve the PDF BOM spelling as a source alias",
                "db_import_action": "use_BTM_scope_and_preserve_source_aliases",
                "master_import_action": "do_not_update_master",
            },
        )

    # E-213's representative figure is copied from another result, while its
    # Recommendation and detail rows agree with one another.
    append_unique(
        reports[21]["validation"]["source_pdf_inconsistencies"],
        {
            "category": "representative_figure_detail_inconsistency",
            "field": "representative_defect_assessment",
            "representative_figure_value": {
                "target_tube": "5-3",
                "minimum_thickness_mm": 1.53,
                "wall_loss_percent": 44.77,
                "defect_type": "EXTERNAL PITTING",
            },
            "recommendation_and_detail_value": {
                "minimum_thickness_mm": 1.78,
                "wall_loss_percent": 15.64,
                "defect_type": "External Corrosion",
            },
            "resolution": "Preserve the figure annotation; use Recommendation/detail values for operational summary and calculations",
            "source_pdf": SOURCE_PDF.name,
            "report_page": 168,
            "detail_page": 170,
        },
    )

    # Final integrity gates.
    if len(reports) != 42:
        raise AssertionError("Expected 42 reports")
    row_count = sum(
        len(item["tube_results_table"]["records"]) for item in reports.values()
    )
    if row_count != 500:
        raise AssertionError(f"Expected 500 result rows, got {row_count}")
    for sequence, item in reports.items():
        report = item["report"]
        summary = report["inspection_summary"]
        records = item["tube_results_table"]["records"]
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

    payload["document"].setdefault("correction_history", []).append(
        {
            "correction_id": "PDF_FULL_REVIEW_2020_VCM2_20260825",
            "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "basis": "Full review of 343 PDF pages and all 42 report/map/results objects; 500 detail rows, exact Tube Specs, Summary fields, source-scope aliases, equipment identity and test/personnel fields verified",
            "source_pdf": str(SOURCE_PDF),
            "report_count": 42,
            "tube_result_count": 500,
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
        "reports": 42,
        "tube_result_rows": 500,
        "field_change_count": len(changes),
        "master_data_action": "do_not_update_master",
        "db_action": "not_applied",
        "changes": changes,
    }
    manifest_path = (
        output_dir / "2020VCM2_PDF_FINALIZATION_MANIFEST_20260825.json"
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
