from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber

from audit_2020_vcm1_pdf_json_20260825 import parse_result_rows


ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "iris_test_report" / "2021_1P_VCM1.pdf"
JSON_PATH = ROOT / "data" / "2021VCM1_IRIS2_all_tube_results.json"


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    findings = {
        "detail_row_mismatches": [],
        "quantity_mismatches": [],
        "detail_spec_mismatches": [],
        "summary_extrema_mismatches": [],
        "row_calculation_mismatches": [],
        "map_assignment_mismatches": [],
    }
    parsed_count = 0

    with pdfplumber.open(PDF_PATH) as pdf:
        for item in data["inspection_reports"]:
            report = item["report"]
            sequence = report["report_sequence"]
            equipment_id = report["equipment_id"]
            table = item["tube_results_table"]
            texts = {
                page: pdf.pages[page - 1].extract_text(
                    x_tolerance=2, y_tolerance=2
                )
                or ""
                for page in table["source_pages"]
            }
            pdf_rows = []
            for page, text in texts.items():
                pdf_rows.extend(parse_result_rows(text, page))
            parsed_count += len(pdf_rows)
            json_rows = [
                (
                    row["row"],
                    row["column"],
                    float(row["minimum_wall_thickness_mm"]),
                    int(row["location_mm"]),
                    row["section_corrosion_depth"],
                    float(row["wall_loss_depth_mm"]),
                    float(row["wall_loss_percent"]),
                    row["source_page"],
                )
                for row in table["records"]
            ]
            if pdf_rows != json_rows:
                changed = sum(
                    left != right
                    for left, right in zip(pdf_rows, json_rows)
                ) + abs(len(pdf_rows) - len(json_rows))
                findings["detail_row_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "differing_rows": changed,
                        "pdf_rows": len(pdf_rows),
                        "json_rows": len(json_rows),
                    }
                )

            combined = "\n".join(texts.values())
            quantity = re.search(r"Tube ID Q'ty:\s*(\d+)", combined)
            if quantity and int(quantity.group(1)) != len(json_rows):
                findings["quantity_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "pdf_quantity": int(quantity.group(1)),
                        "json_quantity": len(json_rows),
                    }
                )

            spec = re.search(
                r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+"
                r"(\d+(?:\.\d+)?)\s+L",
                combined,
            )
            if spec:
                pdf_spec = tuple(float(value) for value in spec.groups())
                json_spec = tuple(
                    float(report["tube_spec"][key])
                    for key in (
                        "outer_diameter_mm",
                        "design_thickness_mm",
                        "length_mm",
                    )
                )
                if pdf_spec != json_spec:
                    findings["detail_spec_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "pdf_spec": pdf_spec,
                            "json_spec": json_spec,
                        }
                    )

            if json_rows:
                minimum = min(row[2] for row in json_rows)
                maximum = max(row[6] for row in json_rows)
                summary = report["inspection_summary"]
                if (
                    summary.get("minimum_remaining_thickness_mm") != minimum
                    or summary.get("maximum_wall_loss_percent") != maximum
                ):
                    findings["summary_extrema_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "summary_minimum": summary.get(
                                "minimum_remaining_thickness_mm"
                            ),
                            "detail_minimum": minimum,
                            "summary_maximum": summary.get(
                                "maximum_wall_loss_percent"
                            ),
                            "detail_maximum": maximum,
                        }
                    )

                nominal = float(report["tube_spec"]["design_thickness_mm"])
                bad_rows = []
                for row in json_rows:
                    expected_depth = round(nominal - row[2], 2)
                    expected_loss = round(expected_depth / nominal * 100, 2)
                    if expected_depth != row[5] or expected_loss != row[6]:
                        bad_rows.append(f"{row[0]}-{row[1]}")
                if bad_rows:
                    findings["row_calculation_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "row_count": len(bad_rows),
                            "tube_ids": bad_rows,
                        }
                    )

            if item.get("tube_map") is None:
                findings["map_assignment_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "issue": "missing_tube_map",
                    }
                )

    print(
        json.dumps(
            {
                "source_pdf": str(PDF_PATH),
                "target_json": str(JSON_PATH),
                "pdf_page_count": len(pdf.pages),
                "report_count": len(data["inspection_reports"]),
                "pdf_parsed_result_row_count": parsed_count,
                "json_result_row_count": sum(
                    len(item["tube_results_table"]["records"])
                    for item in data["inspection_reports"]
                ),
                "findings": findings,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
