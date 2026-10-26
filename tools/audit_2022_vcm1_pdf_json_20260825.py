from __future__ import annotations

import json
import re
from pathlib import Path

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2022_1P_VCM1.pdf"
TARGET = ROOT / "data" / "2022VCM1_IRIS2_all_tube_results.json"

ROW = re.compile(
    r"^\s*(\d+)\s+(\d+)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?m?)\s+"
    r"(.+?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)(?:\s+(.*))?$"
)


def parse(text: str, page: int) -> list[tuple]:
    result = []
    for line in text.splitlines():
        match = ROW.match(line)
        if not match:
            continue
        location = match.group(4)
        location_mm = round(float(location[:-1]) * 1000) if location.endswith("m") else round(float(location))
        result.append((
            int(match.group(1)), int(match.group(2)), float(match.group(3)),
            location_mm, float(match.group(6)), float(match.group(7)), page,
        ))
    return result


def main() -> None:
    data = json.loads(TARGET.read_text(encoding="utf-8"))
    findings = {"row_mismatches": [], "quantity_mismatches": [], "spec_mismatches": [], "summary_mismatches": []}
    parsed_count = 0
    with pdfplumber.open(PDF) as pdf:
        for obj in data["inspection_reports"]:
            report = obj["report"]
            pages = obj["tube_results_table"]["source_pages"]
            texts = {p: pdf.pages[p - 1].extract_text(x_tolerance=2, y_tolerance=2) or "" for p in pages}
            pdf_rows = [row for p, text in texts.items() for row in parse(text, p)]
            json_rows = [(
                int(row["row"]), int(row["column"]), float(row["minimum_wall_thickness_mm"]),
                int(row["location_mm"]), float(row["wall_loss_depth_mm"]),
                float(row["wall_loss_percent"]), int(row["source_page"]),
            ) for row in obj["tube_results_table"]["records"]]
            parsed_count += len(pdf_rows)
            # Some PDF tables have one row out of tube-number order; compare the
            # complete row set so harmless JSON normalization of row order is not
            # reported as a data mismatch.
            if sorted(pdf_rows) != sorted(json_rows):
                findings["row_mismatches"].append({"sequence": report["report_sequence"], "equipment_id": report["equipment_id"], "pdf_rows": len(pdf_rows), "json_rows": len(json_rows), "different": sum(a != b for a, b in zip(pdf_rows, json_rows)) + abs(len(pdf_rows) - len(json_rows))})
            combined = "\n".join(texts.values())
            quantity = re.search(r"Tube ID Q'ty:?\s*(\d+)", combined)
            if not quantity or int(quantity.group(1)) != len(json_rows):
                findings["quantity_mismatches"].append({"sequence": report["report_sequence"], "printed": int(quantity.group(1)) if quantity else None, "actual": len(json_rows)})
            spec = re.search(r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+(\d+(?:\.\d+)?)\s+L", combined)
            expected = tuple(float(report["tube_spec"][key]) for key in ("outer_diameter_mm", "design_thickness_mm", "length_mm"))
            if not spec or tuple(float(x) for x in spec.groups()) != expected:
                findings["spec_mismatches"].append({"sequence": report["report_sequence"], "pdf": tuple(float(x) for x in spec.groups()) if spec else None, "json": expected})
            summary = report["inspection_summary"]
            if summary["inspected_tube_count"] != len(json_rows) or summary["minimum_remaining_thickness_mm"] != min(x[2] for x in json_rows) or summary["maximum_wall_loss_percent"] != max(x[5] for x in json_rows):
                findings["summary_mismatches"].append({"sequence": report["report_sequence"]})
    print(json.dumps({"pdf_pages": len(pdf.pages), "reports": len(data["inspection_reports"]), "pdf_detail_rows": parsed_count, "json_detail_rows": sum(len(x["tube_results_table"]["records"]) for x in data["inspection_reports"]), "findings": findings}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
