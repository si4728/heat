from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF_PATH = ROOT / "iris_test_report" / "2020_1P_VCM1.pdf"
JSON_PATH = ROOT / "data" / "2020VCM1_IRIS2_all_tube_results.json"


def parse_result_rows(text: str, page_number: int) -> list[tuple]:
    rows: list[tuple] = []
    pattern = re.compile(
        r"^\s*(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+(.+?)\s+"
        r"(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?:\s+(.*))?$"
    )
    for line in text.splitlines():
        if not re.match(r"^\s*\d+\s+\d+\s+\d+(?:\.\d+)?\s+\d+\s+", line):
            continue
        match = pattern.match(line)
        if not match:
            continue
        rows.append(
            (
                int(match.group(1)),
                int(match.group(2)),
                float(match.group(3)),
                int(match.group(4)),
                match.group(5).strip(),
                float(match.group(6)),
                float(match.group(7)),
                page_number,
            )
        )
    return rows


def main() -> None:
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    reports = data["inspection_reports"]
    findings: dict[str, list] = {
        "detail_row_mismatches": [],
        "quantity_mismatches": [],
        "detail_spec_mismatches": [],
        "summary_extrema_mismatches": [],
        "row_calculation_mismatches": [],
        "map_assignment_mismatches": [],
    }
    parsed_row_count = 0

    with pdfplumber.open(PDF_PATH) as pdf:
        for item in reports:
            report = item["report"]
            sequence = report["report_sequence"]
            equipment_id = report["equipment_id"]
            table = item["tube_results_table"]
            source_pages = table["source_pages"]
            texts = {
                page_number: pdf.pages[page_number - 1].extract_text(
                    x_tolerance=2, y_tolerance=2
                )
                or ""
                for page_number in source_pages
            }

            pdf_rows: list[tuple] = []
            for page_number, text in texts.items():
                pdf_rows.extend(parse_result_rows(text, page_number))
            parsed_row_count += len(pdf_rows)

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
                findings["detail_row_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "pdf_rows": pdf_rows,
                        "json_rows": json_rows,
                    }
                )

            combined_text = "\n".join(texts.values())
            quantity_match = re.search(r"Tube ID Q'ty:\s*(\d+)", combined_text)
            if quantity_match and int(quantity_match.group(1)) != len(json_rows):
                findings["quantity_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "pdf_quantity": int(quantity_match.group(1)),
                        "json_quantity": len(json_rows),
                    }
                )

            spec_match = re.search(
                r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+"
                r"(\d+(?:\.\d+)?)\s+L",
                combined_text,
            )
            if spec_match:
                pdf_spec = tuple(float(value) for value in spec_match.groups())
                tube_spec = report["tube_spec"]
                json_spec = (
                    float(tube_spec["outer_diameter_mm"]),
                    float(tube_spec["design_thickness_mm"]),
                    float(tube_spec["length_mm"]),
                )
                if pdf_spec != json_spec:
                    findings["detail_spec_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "detail_page": source_pages[0],
                            "pdf_spec": pdf_spec,
                            "json_spec": json_spec,
                        }
                    )

            if json_rows:
                summary = report["inspection_summary"]
                calculated_minimum = min(row[2] for row in json_rows)
                calculated_maximum = max(row[6] for row in json_rows)
                if (
                    summary["minimum_remaining_thickness_mm"] != calculated_minimum
                    or summary["maximum_wall_loss_percent"] != calculated_maximum
                ):
                    findings["summary_extrema_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "summary_minimum": summary[
                                "minimum_remaining_thickness_mm"
                            ],
                            "detail_minimum": calculated_minimum,
                            "summary_maximum": summary[
                                "maximum_wall_loss_percent"
                            ],
                            "detail_maximum": calculated_maximum,
                        }
                    )

                nominal = float(report["tube_spec"]["design_thickness_mm"])
                bad_rows = []
                for row in json_rows:
                    expected_depth = round(nominal - row[2], 2)
                    expected_loss = round(expected_depth / nominal * 100, 2)
                    if expected_depth != row[5] or expected_loss != row[6]:
                        bad_rows.append(
                            {
                                "tube_id": f"{row[0]}-{row[1]}",
                                "pdf_depth": row[5],
                                "expected_depth": expected_depth,
                                "pdf_loss": row[6],
                                "expected_loss": expected_loss,
                            }
                        )
                if bad_rows:
                    findings["row_calculation_mismatches"].append(
                        {
                            "sequence": sequence,
                            "equipment_id": equipment_id,
                            "nominal_thickness_mm": nominal,
                            "rows": bad_rows,
                        }
                    )

            tube_map = item.get("tube_map")
            if tube_map is None:
                findings["map_assignment_mismatches"].append(
                    {
                        "sequence": sequence,
                        "equipment_id": equipment_id,
                        "issue": "missing_tube_map",
                    }
                )

    output = {
        "source_pdf": str(PDF_PATH),
        "target_json": str(JSON_PATH),
        "pdf_page_count": data["document"]["page_count"],
        "report_count": len(reports),
        "pdf_parsed_result_row_count": parsed_row_count,
        "json_result_row_count": sum(
            len(item["tube_results_table"]["records"]) for item in reports
        ),
        "findings": findings,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
