from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2025_1P_VCM1.pdf"
TARGET = ROOT / "data" / "2025VCM1_IRIS2_all_tube_results.json"
EXPECTED_PDF_SHA256 = "d9cadb6c3bd1147467e3cce6e75945910ae9b43df956845ff0f98b6e6f507af5"
ROW_ID = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def compact(value: str) -> str:
    return re.sub(r"[\s()]+", "", value).upper()


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def add_issue(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("category"), item.get("field"), item.get("description"))
    if not any(
        (x.get("category"), x.get("field"), x.get("description")) == key
        for x in items
    ):
        items.append(item)


def result_segments(raw: str) -> list[dict[str, Any]]:
    if "No Defect" in raw:
        return []
    starts: list[tuple[int, str]] = []
    for label in ("Inside Defect", "Outside Defect"):
        starts.extend((match.start(), label) for match in re.finditer(label, raw))
    starts.sort()
    parsed: list[dict[str, Any]] = []
    for index, (start, label) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(raw)
        numbers = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", raw[start:end])]
        if len(numbers) < 2:
            raise AssertionError(f"Could not parse front Summary result: {raw!r}")
        parsed.append(
            {
                "defect_side": "internal" if label.startswith("Inside") else "external",
                "source_label": label,
                "minimum_remaining_thickness_mm": numbers[0],
                "corrosion_depth_mm": numbers[1],
            }
        )
    return parsed


def parse_front_summary(pdf: pdfplumber.PDF) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_number in (4, 5, 6):
        tables = pdf.pages[page_number - 1].extract_tables()
        if len(tables) != 1:
            raise AssertionError(f"Expected one Summary table on page {page_number}")
        for row in tables[0][2:]:
            if not row[1]:
                continue
            total_raw = re.sub(r"\s+", "", row[6] or "")
            total_match = re.search(r"\d+", total_raw)
            if not total_match:
                raise AssertionError(f"Invalid total quantity on page {page_number}: {row}")
            result_raw = (row[8] or "").strip()
            results = result_segments(result_raw)
            rows.append(
                {
                    "source_page": page_number,
                    "source_item": re.sub(r"\s+", " ", row[1]).strip(),
                    "process_code": row[0],
                    "material": re.sub(r"\s+", "", row[2] or ""),
                    "outer_diameter_mm": float(row[3]),
                    "design_thickness_mm": float(row[4]),
                    "length_mm": float(row[5]),
                    "total_tube_source_notation": total_raw,
                    "total_tube_count": int(total_match.group()),
                    "u_tube_count": int(total_match.group()) if "U" in total_raw.upper() else None,
                    "inspected_tube_count": int(re.sub(r"\s+", "", row[7] or "0")),
                    "result_raw": result_raw,
                    "inspection_results": results,
                }
            )
    return rows


def parse_report_page(text: str) -> dict[str, Any]:
    def one(pattern: str) -> str:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            raise AssertionError(f"Report field not found: {pattern}")
        return match.group(1).strip()

    total_raw = one(r"Total Q'ty\s+([^\r\n]+?)\s+Tubes")
    examined_raw = one(r"Exam Q'ty\s+([^\r\n]+?)\s+Tubes")
    return {
        "outer_diameter_mm": float(one(r"O\.D\s+([\d.]+)\s*mm")),
        "design_thickness_mm": float(one(r"Design Th'k\s+([\d.]+)\s*mm")),
        "length_mm": float(one(r"Length\s+([\d,]+)\s*mm").replace(",", "")),
        "total_tube_count": int(re.sub(r"\D", "", total_raw)),
        "total_tube_count_raw": re.sub(r"\s+", "", total_raw),
        "inspected_tube_count": int(re.sub(r"\D", "", examined_raw)),
    }


def source_rows(pdf: pdfplumber.PDF, pages: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_number in pages:
        text = pdf.pages[page_number - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
        for line in text.splitlines():
            match = ROW_ID.match(line)
            if match:
                rows.append(
                    {
                        "source_page": page_number,
                        "source_sequence": int(match.group(1)),
                        "row": int(match.group(2)),
                        "column": int(match.group(3)),
                        "source_row_text": line.strip(),
                    }
                )
    return rows


SOURCE_ISSUES: dict[int, list[dict[str, Any]]] = {
    6: [{
        "category": "source_detail_layout_error",
        "field": "analysis_report.design_thickness_and_code_columns",
        "description": "Analysis Report의 Dsign Th'k 열에 PIT가, Code 열에 2.77이 인쇄되어 두 열이 뒤바뀜",
        "db_import_action": "use report/header nominal thickness; preserve source row; do not import swapped source cells",
    }],
    15: [{
        "category": "source_missing_detail_value",
        "field": "analysis_report.location_mm",
        "description": "Analysis Report 결함 3행의 Location 값이 모두 비어 있음",
        "db_import_action": "keep location null",
    }],
    16: [{
        "category": "source_detail_spec_error",
        "field": "analysis_report.design_thickness_mm",
        "description": "E-210B 상세표 다수 행의 Dsign Th'k가 0.00이거나 행 구조가 불완전함",
        "db_import_action": "use report/header nominal thickness 2.77; preserve invalid 0.00 in source_row_text",
    }, {
        "category": "source_missing_detail_value",
        "field": "analysis_report.side",
        "description": "E-210B 10-16 행의 Side 값이 비어 있음",
        "db_import_action": "do not infer source side",
    }],
    19: [{
        "category": "source_code_result_contradiction",
        "field": "analysis_report.defect_code",
        "description": "E-220A 3-4 행은 감육 측정값이 있으나 Code가 NDD로 인쇄됨",
        "db_import_action": "preserve source code and measured values; record quality issue",
    }],
    25: [{
        "category": "source_detail_layout_error",
        "field": "analysis_report.design_thickness_mm",
        "description": "E-330A 상세 4행의 Dsign Th'k 열에 PIT가 인쇄되어 수치가 누락됨",
        "db_import_action": "use report/header nominal thickness 2.77; preserve source row",
    }],
    27: [{
        "category": "source_code_result_contradiction",
        "field": "analysis_report.defect_code",
        "description": "E-330C 4-2 행은 감육 측정값이 있으나 Code가 NDD로 인쇄됨",
        "db_import_action": "preserve source code and measured values; record quality issue",
    }],
    33: [{
        "category": "source_no_defect_row_variant",
        "field": "analysis_report.no_defect_rows",
        "description": "E-341 NDD 행은 Thickness와 Dsign Th'k 모두 2.77로 인쇄된 2025년형 희소행 형식임",
        "db_import_action": "retain no-defect semantics; do not create a defect assessment",
    }],
}


FRONT_LENGTH_DISCREPANCIES = {
    10: (3048.0, 1260.0, "E-123"),
    29: (3657.0, 3675.0, "E-331A BTM"),
    40: (2438.0, 1800.0, "E-803"),
}


def main() -> None:
    if digest(PDF) != EXPECTED_PDF_SHA256:
        raise AssertionError("Source PDF SHA-256 does not match the reviewed PDF")
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = data["inspection_reports"]
    if len(reports) != 40:
        raise AssertionError(f"Expected 40 reports, found {len(reports)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2025_vcm1_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2025_vcm1_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    before = digest(TARGET)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    changes: list[dict[str, Any]] = []

    with pdfplumber.open(PDF) as pdf:
        if len(pdf.pages) != 171:
            raise AssertionError(f"Expected 171 pages, found {len(pdf.pages)}")
        front_rows = parse_front_summary(pdf)
        if len(front_rows) != 40:
            raise AssertionError(f"Expected 40 front Summary rows, found {len(front_rows)}")

        for obj, front in zip(reports, front_rows):
            report = obj["report"]
            seq = int(report["report_sequence"])
            details = report["iris_report_details"]
            records = obj["tube_results_table"]["records"]
            validation = obj.setdefault("validation", {})
            issues = validation.setdefault("source_pdf_inconsistencies", [])
            report_page = int(details["source_report_page"])
            report_text = pdf.pages[report_page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
            parsed_report = parse_report_page(report_text)

            labels = report.get("source_equipment_labels") or [report["equipment_id"]]
            if compact(front["source_item"]) not in {compact(label) for label in labels}:
                raise AssertionError(
                    f"Front Summary identity mismatch at sequence {seq}: {front['source_item']} vs {labels}"
                )
            if parsed_report["inspected_tube_count"] != len(records):
                raise AssertionError(
                    f"Inspected/detail count mismatch at sequence {seq}: "
                    f"{parsed_report['inspected_tube_count']} vs {len(records)}"
                )

            tube_spec = report["tube_spec"]
            for field in ("outer_diameter_mm", "design_thickness_mm", "length_mm"):
                old = tube_spec.get(field)
                new = parsed_report[field]
                if old != new:
                    changes.append({
                        "sequence": seq,
                        "equipment_id": report["equipment_id"],
                        "field": f"report.tube_spec.{field}",
                        "old": old,
                        "new": new,
                    })
                tube_spec[field] = new

            pdf_rows = source_rows(pdf, obj["tube_results_table"]["source_pages"])
            if len(pdf_rows) != len(records):
                raise AssertionError(
                    f"Source/JSON row count mismatch at sequence {seq}: {len(pdf_rows)} vs {len(records)}"
                )
            for position, (record, source) in enumerate(zip(records, pdf_rows), start=1):
                identity = (int(record["row"]), int(record["column"]), int(record["source_page"]))
                source_identity = (source["row"], source["column"], source["source_page"])
                if identity != source_identity:
                    raise AssertionError(
                        f"Source row identity mismatch at sequence {seq}, position {position}: "
                        f"{identity} vs {source_identity}"
                    )
                record["source_row_sequence"] = source["source_sequence"]
                record["source_row_text"] = source["source_row_text"]
                record["source_row_verified"] = True
                record["source_value_quality"] = "source_layout_issue" if seq in SOURCE_ISSUES else "verified"

            non_null_thickness = [
                float(row["minimum_wall_thickness_mm"])
                for row in records
                if row.get("minimum_wall_thickness_mm") is not None
            ]
            wall_loss = [float(row.get("wall_loss_percent") or 0) for row in records]
            minimum = min(non_null_thickness) if non_null_thickness else None
            maximum = max(wall_loss) if non_null_thickness else None
            average_precise = sum(wall_loss) / len(records)
            average = q2(average_precise)
            old_average = report["inspection_summary"].get("average_wall_loss_percent")
            if old_average != average:
                changes.append({
                    "sequence": seq,
                    "equipment_id": report["equipment_id"],
                    "field": "report.inspection_summary.average_wall_loss_percent",
                    "old": old_average,
                    "new": average,
                })

            no_defect = not non_null_thickness
            operational = report["inspection_summary"]
            operational.update({
                "total_tube_count": parsed_report["total_tube_count"],
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": minimum,
                "maximum_wall_loss_percent": maximum,
                "average_wall_loss_percent": average,
                "result_status": "no_defect_detected" if no_defect else "measured_results_present",
                "summary_basis": {
                    "total_tube_count": "individual_examination_report",
                    "inspected_tube_count": "complete_analysis_rows",
                    "extrema": "complete_non_null_analysis_measurements",
                    "average": "all_analysis_rows; missing/NDD wall loss treated as 0 percent; ROUND_HALF_UP 2 decimals",
                },
            })
            nested = details.setdefault("inspection_summary", {})
            nested.update({
                "total_tube_count": parsed_report["total_tube_count"],
                "total_tube_count_raw": parsed_report["total_tube_count_raw"],
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": minimum,
                "maximum_wall_loss_percent": maximum,
                "average_wall_loss_percent": average,
                "average_wall_loss_calculation_basis": "all analysis rows; missing/NDD wall loss treated as 0 percent; ROUND_HALF_UP 2 decimals",
            })

            if no_defect:
                details["representative_defect_assessment"] = None
                details["representative_defect_assessment_status"] = "no_defect_detected"
            else:
                representative = max(records, key=lambda row: float(row.get("wall_loss_percent") or 0))
                details["representative_defect_assessment"] = {
                    "target_tube": representative["tube_id"],
                    "minimum_thickness_mm": representative.get("minimum_wall_thickness_mm"),
                    "wall_loss_percent": representative.get("wall_loss_percent"),
                    "defect_type": representative.get("section_corrosion_depth"),
                    "defect_code": representative.get("defect_code"),
                    "basis": "maximum_wall_loss_analysis_row",
                }
                details["representative_defect_assessment_status"] = "measured_result_selected"

            front_results = front["inspection_results"]
            front_reference = {
                "source_page": front["source_page"],
                "source_item": front["source_item"],
                "process_code": front["process_code"],
                "basis": "front_summary_table",
                "total_tube_count": front["total_tube_count"],
                "total_tube_source_notation": front["total_tube_source_notation"],
                "u_tube_count": front["u_tube_count"],
                "inspected_tube_count": front["inspected_tube_count"],
                "tube_spec_reference": {
                    "material": front["material"],
                    "outer_diameter_mm": front["outer_diameter_mm"],
                    "design_thickness_mm": front["design_thickness_mm"],
                    "length_mm": front["length_mm"],
                },
                "inspection_results": front_results,
                "result_status": "no_defect_detected" if not front_results else "defect_measurements_listed",
                "minimum_remaining_thickness_mm": min(
                    (x["minimum_remaining_thickness_mm"] for x in front_results), default=None
                ),
                "maximum_corrosion_depth_mm": max(
                    (x["corrosion_depth_mm"] for x in front_results), default=None
                ),
                "maximum_wall_loss_percent": None,
                "average_wall_loss_percent": None,
                "percent_fields_source_status": "not_present_in_2025_front_summary",
                "source_result_raw": front["result_raw"],
            }
            obj["summary_reference"] = front_reference

            details["recommendations"] = (
                ["Equipment list length is 3048 mm; field measured length is 1260 mm."]
                if seq == 10 else ["No special remarks."]
            )
            details["recommendation_source_status"] = "not_present_in_2025_form; mapped from Special Remarks"
            equipment = details["inspection_equipment"]
            equipment.update({
                "equipment_maker_provenance": "inferred_from_model" if equipment.get("equipment_maker") else None,
                "equipment_serial_number_source_status": "not_present_in_2025_form",
                "search_unit_maker_source_status": "not_present_in_2025_form",
                "search_unit_model_source_status": "not_present_in_2025_form",
                "frequency_source_status": "present_in_analysis_report",
            })
            conditions = details["measurement_conditions"]
            conditions["source_field_status"] = {
                "out_diameter_mm": "present_in_examination_report",
                "tube_length_m": "present_in_examination_report",
                "material_velocity_meter_per_sec": "not_present_in_2025_form",
                "scan_velocity_meter_per_min": "not_present_in_2025_form",
                "water_pressure_kg_per_cm2": "not_present_in_2025_form",
                "water_temperature_celsius": "not_present_in_2025_form",
            }
            personnel = details["signatures_and_personnel"]
            personnel["witnesser_source_status"] = "not_present_in_2025_form"
            personnel["reviewed_by_source_status"] = "field_present_but_blank"

            validation.update({
                "extracted_tube_result_count": len(records),
                "reported_inspected_tube_count": parsed_report["inspected_tube_count"],
                "reported_vs_extracted_count_match": True,
                "source_row_identity_verified_count": len(records),
                "source_row_identity_mismatch_count": 0,
                "calculated_minimum_thickness_mm": minimum,
                "calculated_maximum_wall_loss_percent": maximum,
                "calculated_average_wall_loss_percent_precise": round(average_precise, 6),
                "calculated_average_wall_loss_percent_rounded": average,
                "front_summary_reference_verified": True,
                "individual_report_fields_verified": True,
            })
            for issue in SOURCE_ISSUES.get(seq, []):
                add_issue(issues, issue)
            if seq in FRONT_LENGTH_DISCREPANCIES:
                front_length, report_length, label = FRONT_LENGTH_DISCREPANCIES[seq]
                add_issue(issues, {
                    "category": "source_summary_report_discrepancy",
                    "field": "tube_length_mm",
                    "description": f"{label}: 앞 Summary {front_length:g} mm와 개별 Examination Report {report_length:g} mm가 불일치",
                    "operational_value_mm": report_length,
                    "front_summary_value_mm": front_length,
                    "db_import_action": "use individual examination report value for inspection snapshot; preserve front value as reference",
                    "master_import_action": "do_not_update_master",
                })

    document = data["document"]
    document["source_pdf_sha256"] = EXPECTED_PDF_SHA256
    document["inspection_report_object_count"] = 40
    document["total_extracted_tube_result_records"] = 470
    document["form_variant"] = "2025 front Summary + Examination Report + tube map + Analysis Report"
    document["form_variant_note"] = "2025 form uses Special Remarks and sparse/variant NDD analysis rows; it does not use the earlier four-line Recommendation layout"
    document["pdf_json_finalization"] = {
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_pdf": PDF.name,
        "front_summary_pages": [4, 5, 6],
        "report_count": 40,
        "analysis_row_count": 470,
        "source_row_identity_verified_count": 470,
        "source_row_identity_mismatch_count": 0,
        "master_file_modified": False,
        "database_modified": False,
    }
    history = document.setdefault("correction_history", [])
    history.append({
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": "2025 VCM1 PDF re-verification and JSON finalization",
        "source_pdf": PDF.name,
        "changes": len(changes),
        "notes": [
            "All 40 report objects and 470 Analysis rows were re-verified by row, column, and page.",
            "Front Summary values are preserved separately from operational individual-report/detail values.",
            "Known source layout errors and NDD variants are preserved as quality issues, not silently rewritten.",
            "No master file or database was modified.",
        ],
    })

    total_rows = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if total_rows != 470:
        raise AssertionError(f"Expected 470 JSON rows, found {total_rows}")
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = digest(TARGET)
    manifest = {
        "source_pdf": str(PDF),
        "target_json": str(TARGET),
        "backup_json": str(backup_dir / TARGET.name),
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "json_sha256_before": before,
        "json_sha256_after": after,
        "reports": 40,
        "analysis_rows": 470,
        "changes": changes,
        "master_modified": False,
        "database_modified": False,
    }
    manifest_path = output_dir / "2025VCM1_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target": str(TARGET),
        "backup": str(backup_dir / TARGET.name),
        "manifest": str(manifest_path),
        "before_sha256": before,
        "after_sha256": after,
        "reports": 40,
        "rows": 470,
        "changes": changes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
