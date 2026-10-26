from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber

from finalize_2025_vcm1_json_from_pdf_20260825 import (
    add_issue,
    compact,
    digest,
    parse_report_page,
    q2,
    result_segments,
    source_rows,
)


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2025_1P_VCM2.pdf"
TARGET = ROOT / "data" / "2025VCM2_IRIS2_all_tube_results.json"
EXPECTED_PDF_SHA256 = "761d86ad0d17ec418eff4464703b7bb601a4d3408ddf828188ec6928322b4ac3"


def parse_front_summary(pdf: pdfplumber.PDF) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page_number in (4, 5, 6, 7):
        tables = pdf.pages[page_number - 1].extract_tables()
        if len(tables) != 1:
            raise AssertionError(f"Expected one Summary table on page {page_number}")
        for row in tables[0][2:]:
            if not row[1]:
                continue
            total_raw = re.sub(r"\s+", "", row[6] or "")
            total_digits = re.sub(r"\D", "", total_raw)
            if not total_digits:
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
                    "total_tube_count": int(total_digits),
                    "u_tube_count": int(total_digits) if "U" in total_raw.upper() else None,
                    "inspected_tube_count": int(re.sub(r"\D", "", row[7] or "0")),
                    "result_raw": result_raw,
                    "inspection_results": results,
                }
            )
    return rows


SOURCE_ISSUES: dict[int, list[dict[str, Any]]] = {
    22: [{
        "category": "source_detail_spec_error",
        "field": "analysis_report.design_thickness_mm",
        "description": "E-210 Analysis Report 11~40번 행의 Dsign Th'k가 0.00으로 인쇄됨",
        "affected_source_row_count": 30,
        "db_import_action": "use report/header nominal thickness 2.11; preserve source 0.00 in source_row_text",
        "master_import_action": "do_not_update_master",
    }],
    24: [{
        "category": "source_detail_spec_error",
        "field": "analysis_report.design_thickness_mm",
        "description": "E-206B Analysis Report 4~40번 행의 Dsign Th'k가 0.00으로 인쇄됨",
        "affected_source_row_count": 37,
        "db_import_action": "use report/header nominal thickness 2.11; preserve source 0.00 in source_row_text",
        "master_import_action": "do_not_update_master",
    }],
    27: [{
        "category": "source_no_defect_row_variant",
        "field": "analysis_report.no_defect_rows",
        "description": "E-222 NDD 10행은 Dsign Th'k 2.77만 인쇄된 희소행 형식임",
        "db_import_action": "retain no-defect semantics; do not create defect measurements",
    }],
    30: [{
        "category": "source_no_defect_row_variant",
        "field": "analysis_report.no_defect_rows",
        "description": "E-223A NDD 50행은 Thickness와 Dsign Th'k가 모두 2.11로 인쇄됨",
        "db_import_action": "retain no-defect semantics; do not treat repeated nominal thickness as a defect minimum",
    }],
    31: [{
        "category": "source_no_defect_row_variant",
        "field": "analysis_report.no_defect_rows",
        "description": "E-223B NDD 50행은 Dsign Th'k 2.11만 인쇄된 희소행 형식임",
        "db_import_action": "retain no-defect semantics; do not create defect measurements",
    }],
    38: [{
        "category": "source_no_defect_row_variant",
        "field": "analysis_report.no_defect_rows",
        "description": "E-303 NDD 10행은 Thickness와 Dsign Th'k가 모두 2.11로 인쇄됨",
        "db_import_action": "retain no-defect semantics; do not treat repeated nominal thickness as a defect minimum",
    }],
    44: [{
        "category": "source_detail_spec_error",
        "field": "analysis_report.design_thickness_mm",
        "description": "AE-502D-1 Analysis Report 5-22 행의 Dsign Th'k가 0.00으로 인쇄됨",
        "affected_source_row_count": 1,
        "db_import_action": "use report/header nominal thickness 1.00; preserve source 0.00 in source_row_text",
        "master_import_action": "do_not_update_master",
    }],
}


FRONT_DISCREPANCIES: dict[int, list[dict[str, Any]]] = {
    27: [{
        "category": "source_summary_report_discrepancy",
        "field": "tube_material_and_length",
        "description": "E-222: 앞 Summary는 C.S·4,880 mm, 개별 Examination Report는 A266-4·4,877 mm",
        "operational_value": {"material": "A266-4", "length_mm": 4877.0},
        "front_summary_value": {"material": "C.S", "length_mm": 4880.0},
    }],
    49: [{
        "category": "source_summary_report_discrepancy",
        "field": "tube_length_mm",
        "description": "E-511A: 앞 Summary 3,658 mm와 개별 보고서·현장 실측 약 4,850 mm가 불일치",
        "operational_value_mm": 4850.0,
        "front_summary_value_mm": 3658.0,
    }],
    50: [{
        "category": "source_summary_report_discrepancy",
        "field": "tube_length_mm",
        "description": "E-511B: 앞 Summary 3,658 mm와 개별 보고서·현장 실측 약 4,850 mm가 불일치",
        "operational_value_mm": 4850.0,
        "front_summary_value_mm": 3658.0,
    }],
    51: [{
        "category": "source_summary_report_discrepancy",
        "field": "total_tube_count",
        "description": "E-581A: 앞 Summary 296본과 개별 보고서·튜브 배열도 74본이 불일치",
        "operational_value": 74,
        "front_summary_value": 296,
    }],
    52: [{
        "category": "source_summary_report_discrepancy",
        "field": "total_tube_count",
        "description": "E-581B: 앞 Summary 296본과 개별 보고서·튜브 배열도 74본이 불일치",
        "operational_value": 74,
        "front_summary_value": 296,
    }],
}


def main() -> None:
    if digest(PDF) != EXPECTED_PDF_SHA256:
        raise AssertionError("Source PDF SHA-256 does not match the reviewed PDF")
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = data["inspection_reports"]
    if len(reports) != 53:
        raise AssertionError(f"Expected 53 reports, found {len(reports)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2025_vcm2_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2025_vcm2_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    before = digest(TARGET)
    backup = backup_dir / TARGET.name
    shutil.copy2(TARGET, backup)
    changes: list[dict[str, Any]] = []

    with pdfplumber.open(PDF) as pdf:
        if len(pdf.pages) != 227:
            raise AssertionError(f"Expected 227 pages, found {len(pdf.pages)}")
        front_rows = parse_front_summary(pdf)
        if len(front_rows) != 53:
            raise AssertionError(f"Expected 53 front Summary rows, found {len(front_rows)}")

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
                if seq in (27, 30, 31, 38):
                    record["source_value_quality"] = "source_no_defect_variant"
                elif seq in (22, 24, 44):
                    record["source_value_quality"] = "reviewed_with_detail_spec_source_issue"
                else:
                    record["source_value_quality"] = "verified"

            no_defect = all((row.get("defect_code") or "").upper() == "NDD" for row in records)
            defect_rows = [
                row for row in records
                if row.get("minimum_wall_thickness_mm") is not None
                and ((row.get("defect_code") or "").upper() != "NDD" or float(row.get("wall_loss_percent") or 0) > 0)
            ]
            wall_loss = [float(row.get("wall_loss_percent") or 0) for row in records]
            minimum = min((float(row["minimum_wall_thickness_mm"]) for row in defect_rows), default=None)
            maximum = max((float(row.get("wall_loss_percent") or 0) for row in defect_rows), default=None)
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

            operational = report["inspection_summary"]
            operational.update({
                "total_tube_count": parsed_report["total_tube_count"],
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": None if no_defect else minimum,
                "maximum_wall_loss_percent": None if no_defect else maximum,
                "average_wall_loss_percent": average,
                "result_status": "no_defect_detected" if no_defect else "measured_results_present",
                "summary_basis": {
                    "total_tube_count": "individual_examination_report",
                    "inspected_tube_count": "complete_analysis_rows",
                    "extrema": "complete_non-NDD_analysis_measurements",
                    "average": "all analysis rows; NDD/missing wall loss treated as 0 percent; ROUND_HALF_UP 2 decimals",
                },
            })
            nested = details.setdefault("inspection_summary", {})
            nested.update({
                "total_tube_count": parsed_report["total_tube_count"],
                "total_tube_count_raw": parsed_report["total_tube_count_raw"],
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": None if no_defect else minimum,
                "maximum_wall_loss_percent": None if no_defect else maximum,
                "average_wall_loss_percent": average,
                "average_wall_loss_calculation_basis": "all analysis rows; NDD/missing wall loss treated as 0 percent; ROUND_HALF_UP 2 decimals",
            })

            if no_defect:
                details["representative_defect_assessment"] = None
                details["representative_defect_assessment_status"] = "no_defect_detected"
            else:
                representative = max(defect_rows, key=lambda row: float(row.get("wall_loss_percent") or 0))
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
            obj["summary_reference"] = {
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

            details["recommendation_source_status"] = "not_present_in_2025_form; recommendations contain Special Remarks source text"
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
                "calculated_minimum_thickness_mm": None if no_defect else minimum,
                "calculated_maximum_wall_loss_percent": None if no_defect else maximum,
                "calculated_average_wall_loss_percent_precise": round(average_precise, 6),
                "calculated_average_wall_loss_percent_rounded": average,
                "front_summary_reference_verified": True,
                "individual_report_fields_verified": True,
            })
            for issue in SOURCE_ISSUES.get(seq, []):
                add_issue(issues, issue)
            for issue in FRONT_DISCREPANCIES.get(seq, []):
                issue = dict(issue)
                issue.update({
                    "db_import_action": "use individual examination report value for inspection snapshot; preserve front value as reference",
                    "master_import_action": "do_not_update_master",
                })
                add_issue(issues, issue)

    document = data["document"]
    document["source_pdf_sha256"] = EXPECTED_PDF_SHA256
    document["inspection_report_object_count"] = 53
    document["total_extracted_tube_result_records"] = 856
    document["form_variant"] = "2025 front Summary + Examination Report + tube map + Analysis Report"
    document["form_variant_note"] = "2025 form uses Special Remarks and multiple sparse/variant NDD row layouts; it does not use the earlier four-line Recommendation layout"
    document["pdf_json_finalization"] = {
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_pdf": PDF.name,
        "front_summary_pages": [4, 5, 6, 7],
        "report_count": 53,
        "analysis_row_count": 856,
        "source_row_identity_verified_count": 856,
        "source_row_identity_mismatch_count": 0,
        "master_file_modified": False,
        "database_modified": False,
    }
    document.setdefault("correction_history", []).append({
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": "2025 VCM2 PDF re-verification and JSON finalization",
        "source_pdf": PDF.name,
        "changes": len(changes),
        "notes": [
            "All 53 report objects and 856 Analysis rows were re-verified by row, column, and page.",
            "Front Summary values are preserved separately from operational individual-report/detail values.",
            "Known 0.00 design-thickness source errors and NDD row variants are preserved as quality issues.",
            "No master file or database was modified.",
        ],
    })

    total_rows = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if total_rows != 856:
        raise AssertionError(f"Expected 856 JSON rows, found {total_rows}")
    TARGET.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = digest(TARGET)
    manifest = {
        "source_pdf": str(PDF),
        "target_json": str(TARGET),
        "backup_json": str(backup),
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "json_sha256_before": before,
        "json_sha256_after": after,
        "reports": 53,
        "analysis_rows": 856,
        "changes": changes,
        "master_modified": False,
        "database_modified": False,
    }
    manifest_path = output_dir / "2025VCM2_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target": str(TARGET),
        "backup": str(backup),
        "manifest": str(manifest_path),
        "before_sha256": before,
        "after_sha256": after,
        "reports": 53,
        "rows": 856,
        "changes": changes,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
