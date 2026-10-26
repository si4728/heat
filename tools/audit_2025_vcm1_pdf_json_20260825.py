from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2025_1P_VCM1.pdf"
TARGET = ROOT / "data" / "2025VCM1_IRIS2_all_tube_results.json"
ROW_ID = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+")


def q2(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main() -> None:
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    findings = {
        "source_row_identity_mismatches": [],
        "source_row_text_mismatches": [],
        "quantity_mismatches": [],
        "individual_report_field_mismatches": [],
        "analysis_header_mismatches": [],
        "summary_detail_mismatches": [],
        "front_reference_mismatches": [],
    }
    source_count = 0
    json_count = 0
    with pdfplumber.open(PDF) as pdf:
        front_count = sum(
            len([row for row in pdf.pages[page - 1].extract_tables()[0][2:] if row[1]])
            for page in (4, 5, 6)
        )
        for obj in data["inspection_reports"]:
            report = obj["report"]
            seq = int(report["report_sequence"])
            records = obj["tube_results_table"]["records"]
            details = report["iris_report_details"]
            report_page = int(details["source_report_page"])
            report_text = pdf.pages[report_page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
            report_values = {
                "outer_diameter_mm": re.search(r"O\.D\s+([\d.]+)\s*mm", report_text),
                "design_thickness_mm": re.search(r"Design Th'k\s+([\d.]+)\s*mm", report_text),
                "length_mm": re.search(r"Length\s+([\d,]+)\s*mm", report_text),
                "total_tube_count": re.search(r"Total Q'ty\s+([^\r\n]+?)\s+Tubes", report_text),
                "inspected_tube_count": re.search(r"Exam Q'ty\s+([^\r\n]+?)\s+Tubes", report_text),
            }
            if not all(report_values.values()):
                findings["individual_report_field_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"], "reason": "field_not_parsed",
                })
            else:
                expected_report = {
                    "outer_diameter_mm": float(report_values["outer_diameter_mm"].group(1)),
                    "design_thickness_mm": float(report_values["design_thickness_mm"].group(1)),
                    "length_mm": float(report_values["length_mm"].group(1).replace(",", "")),
                    "total_tube_count": int(re.sub(r"\D", "", report_values["total_tube_count"].group(1))),
                    "inspected_tube_count": int(re.sub(r"\D", "", report_values["inspected_tube_count"].group(1))),
                }
                actual_report = {
                    "outer_diameter_mm": report["tube_spec"]["outer_diameter_mm"],
                    "design_thickness_mm": report["tube_spec"]["design_thickness_mm"],
                    "length_mm": report["tube_spec"]["length_mm"],
                    "total_tube_count": report["inspection_summary"]["total_tube_count"],
                    "inspected_tube_count": report["inspection_summary"]["inspected_tube_count"],
                }
                if expected_report != actual_report:
                    findings["individual_report_field_mismatches"].append({
                        "sequence": seq, "equipment_id": report["equipment_id"],
                        "pdf": expected_report, "json": actual_report,
                    })
            parsed = []
            analysis_texts = []
            for page in obj["tube_results_table"]["source_pages"]:
                text = pdf.pages[page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
                analysis_texts.append(text)
                for line in text.splitlines():
                    match = ROW_ID.match(line)
                    if match:
                        parsed.append((
                            int(match.group(2)), int(match.group(3)), page, line.strip()
                        ))
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
                findings["source_row_text_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                })
            analysis_text = "\n".join(analysis_texts)
            operator = re.search(r"Operator\s*:\s*([^\r\n]+)", analysis_text)
            analyst = re.search(r"Analyst\s*:\s*([^\r\n]+)", analysis_text)
            system = re.search(r"System\s*:\s*([^\r\n]+)", analysis_text)
            probe = re.search(r"Probe\s*:\s*(\d+(?:\.\d+)?)\s*MHz", analysis_text)
            normalize_name = lambda value: re.sub(r"\s+", "", value or "")
            personnel = details["signatures_and_personnel"]
            equipment = details["inspection_equipment"]
            if (
                not operator or normalize_name(operator.group(1)) != normalize_name(personnel.get("examiner"))
                or not analyst or normalize_name(analyst.group(1)) != normalize_name(personnel.get("interpreter"))
                or not system or system.group(1).strip() != equipment.get("equipment_model")
                or not probe or float(probe.group(1)) != float(equipment.get("frequency_mhz"))
            ):
                findings["analysis_header_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                    "pdf_operator": operator.group(1).strip() if operator else None,
                    "json_examiner": personnel.get("examiner"),
                    "pdf_analyst": analyst.group(1).strip() if analyst else None,
                    "json_interpreter": personnel.get("interpreter"),
                    "pdf_system": system.group(1).strip() if system else None,
                    "json_system": equipment.get("equipment_model"),
                    "pdf_probe_mhz": float(probe.group(1)) if probe else None,
                    "json_frequency_mhz": equipment.get("frequency_mhz"),
                })
            summary = report["inspection_summary"]
            if summary["inspected_tube_count"] != len(records):
                findings["quantity_mismatches"].append({
                    "sequence": seq, "reported": summary["inspected_tube_count"], "detail": len(records),
                })
            remaining = [float(x["minimum_wall_thickness_mm"]) for x in records if x.get("minimum_wall_thickness_mm") is not None]
            wall = [float(x.get("wall_loss_percent") or 0) for x in records]
            expected = {
                "minimum_remaining_thickness_mm": min(remaining) if remaining else None,
                "maximum_wall_loss_percent": max(wall) if remaining else None,
                "average_wall_loss_percent": q2(sum(wall) / len(records)),
            }
            if any(summary.get(key) != value for key, value in expected.items()):
                findings["summary_detail_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                    "json": {key: summary.get(key) for key in expected}, "expected": expected,
                })
            reference = obj["summary_reference"]
            if reference.get("basis") != "front_summary_table" or not reference.get("source_page"):
                findings["front_reference_mismatches"].append({
                    "sequence": seq, "equipment_id": report["equipment_id"],
                })

    result = {
        "pdf_pages": 171,
        "front_summary_rows": front_count,
        "reports": len(data["inspection_reports"]),
        "pdf_analysis_rows": source_count,
        "json_analysis_rows": json_count,
        "target_json_mismatch_count": sum(len(items) for items in findings.values()),
        "findings": findings,
        "source_quality_issue_reports": [
            {
                "sequence": x["report"]["report_sequence"],
                "equipment_id": x["report"]["equipment_id"],
                "issues": x.get("validation", {}).get("source_pdf_inconsistencies", []),
            }
            for x in data["inspection_reports"]
            if x.get("validation", {}).get("source_pdf_inconsistencies")
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["target_json_mismatch_count"] or source_count != 470 or json_count != 470 or front_count != 40:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
