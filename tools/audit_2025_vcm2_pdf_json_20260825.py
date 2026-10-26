from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

from finalize_2025_vcm1_json_from_pdf_20260825 import q2
from finalize_2025_vcm2_json_from_pdf_20260825 import parse_front_summary


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2025_1P_VCM2.pdf"
TARGET = ROOT / "data" / "2025VCM2_IRIS2_all_tube_results.json"
ROW_ID = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+")


def compact(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def main() -> None:
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    findings: dict[str, list] = {
        "source_row_identity_mismatches": [],
        "source_row_text_mismatches": [],
        "individual_report_field_mismatches": [],
        "analysis_header_mismatches": [],
        "summary_detail_mismatches": [],
        "front_reference_mismatches": [],
    }
    source_count = 0
    json_count = 0
    with pdfplumber.open(PDF) as pdf:
        fronts = parse_front_summary(pdf)
        for obj, front in zip(data["inspection_reports"], fronts):
            report = obj["report"]
            seq = int(report["report_sequence"])
            details = report["iris_report_details"]
            records = obj["tube_results_table"]["records"]
            report_page = int(details["source_report_page"])
            report_text = pdf.pages[report_page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""

            def match(pattern: str):
                return re.search(pattern, report_text, flags=re.IGNORECASE)

            values = {
                "outer_diameter_mm": match(r"O\.D\s+([\d.]+)\s*mm"),
                "design_thickness_mm": match(r"Design Th'k\s+([\d.]+)\s*mm"),
                "length_mm": match(r"Length\s+([\d,]+)\s*mm"),
                "total_tube_count": match(r"Total Q'ty\s+([^\r\n]+?)\s+Tubes"),
                "inspected_tube_count": match(r"Exam Q'ty\s+([^\r\n]+?)\s+Tubes"),
            }
            if not all(values.values()):
                findings["individual_report_field_mismatches"].append({"sequence": seq, "reason": "field_not_parsed"})
            else:
                expected = {
                    "outer_diameter_mm": float(values["outer_diameter_mm"].group(1)),
                    "design_thickness_mm": float(values["design_thickness_mm"].group(1)),
                    "length_mm": float(values["length_mm"].group(1).replace(",", "")),
                    "total_tube_count": int(re.sub(r"\D", "", values["total_tube_count"].group(1))),
                    "inspected_tube_count": int(re.sub(r"\D", "", values["inspected_tube_count"].group(1))),
                }
                actual = {
                    "outer_diameter_mm": report["tube_spec"]["outer_diameter_mm"],
                    "design_thickness_mm": report["tube_spec"]["design_thickness_mm"],
                    "length_mm": report["tube_spec"]["length_mm"],
                    "total_tube_count": report["inspection_summary"]["total_tube_count"],
                    "inspected_tube_count": report["inspection_summary"]["inspected_tube_count"],
                }
                if expected != actual:
                    findings["individual_report_field_mismatches"].append({
                        "sequence": seq, "equipment_id": report["equipment_id"], "pdf": expected, "json": actual,
                    })

            parsed = []
            analysis_texts = []
            for page in obj["tube_results_table"]["source_pages"]:
                text = pdf.pages[page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
                analysis_texts.append(text)
                for line in text.splitlines():
                    found = ROW_ID.match(line)
                    if found:
                        parsed.append((int(found.group(2)), int(found.group(3)), page, line.strip()))
            source_count += len(parsed)
            json_count += len(records)
            json_rows = [(
                int(row["row"]), int(row["column"]), int(row["source_page"]), row.get("source_row_text")
            ) for row in records]
            if [x[:3] for x in parsed] != [x[:3] for x in json_rows]:
                findings["source_row_identity_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                    "pdf_rows": len(parsed), "json_rows": len(json_rows),
                })
            if [x[3] for x in parsed] != [x[3] for x in json_rows]:
                findings["source_row_text_mismatches"].append({"sequence": seq, "equipment_id": report["equipment_id"]})

            analysis_text = "\n".join(analysis_texts)
            operator = re.search(r"Operator\s*:\s*([^\r\n]+)", analysis_text)
            analyst = re.search(r"Analyst\s*:\s*([^\r\n]+)", analysis_text)
            system = re.search(r"System\s*:\s*([^\r\n]+)", analysis_text)
            probe = re.search(r"Probe\s*:\s*(\d+(?:\.\d+)?)\s*MHz", analysis_text)
            personnel = details["signatures_and_personnel"]
            equipment = details["inspection_equipment"]
            if (
                not operator or compact(operator.group(1)) != compact(personnel.get("examiner"))
                or not analyst or compact(analyst.group(1)) != compact(personnel.get("interpreter"))
                or not system or system.group(1).strip() != equipment.get("equipment_model")
                or not probe or float(probe.group(1)) != float(equipment.get("frequency_mhz"))
            ):
                findings["analysis_header_mismatches"].append({"sequence": seq, "equipment_id": report["equipment_id"]})

            no_defect = all((row.get("defect_code") or "").upper() == "NDD" for row in records)
            defect_rows = [
                row for row in records
                if row.get("minimum_wall_thickness_mm") is not None
                and ((row.get("defect_code") or "").upper() != "NDD" or float(row.get("wall_loss_percent") or 0) > 0)
            ]
            wall = [float(row.get("wall_loss_percent") or 0) for row in records]
            expected_summary = {
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": None if no_defect else min(float(row["minimum_wall_thickness_mm"]) for row in defect_rows),
                "maximum_wall_loss_percent": None if no_defect else max(float(row.get("wall_loss_percent") or 0) for row in defect_rows),
                "average_wall_loss_percent": q2(sum(wall) / len(records)),
            }
            summary = report["inspection_summary"]
            if any(summary.get(key) != value for key, value in expected_summary.items()):
                findings["summary_detail_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                    "json": {key: summary.get(key) for key in expected_summary}, "expected": expected_summary,
                })

            reference = obj["summary_reference"]
            expected_front = {
                "source_page": front["source_page"],
                "source_item": front["source_item"],
                "total_tube_count": front["total_tube_count"],
                "inspected_tube_count": front["inspected_tube_count"],
                "length_mm": front["length_mm"],
            }
            actual_front = {
                "source_page": reference.get("source_page"),
                "source_item": reference.get("source_item"),
                "total_tube_count": reference.get("total_tube_count"),
                "inspected_tube_count": reference.get("inspected_tube_count"),
                "length_mm": reference.get("tube_spec_reference", {}).get("length_mm"),
            }
            if expected_front != actual_front:
                findings["front_reference_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"], "pdf": expected_front, "json": actual_front,
                })

    result = {
        "pdf_pages": 227,
        "front_summary_rows": len(fronts),
        "reports": len(data["inspection_reports"]),
        "pdf_analysis_rows": source_count,
        "json_analysis_rows": json_count,
        "target_json_mismatch_count": sum(len(items) for items in findings.values()),
        "findings": findings,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["target_json_mismatch_count"] or len(fronts) != 53 or source_count != 856 or json_count != 856:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
