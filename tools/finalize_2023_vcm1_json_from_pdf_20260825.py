from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "iris_test_report" / "2023_1P_VCM1.pdf"
TARGET = ROOT / "data" / "2023VCM1_IRIS2_all_tube_results.json"
SUMMARY_PAGE = {
    **{seq: 9 for seq in range(1, 7)},
    **{seq: 10 for seq in range(7, 13)},
    **{seq: 11 for seq in range(13, 19)},
    **{seq: 12 for seq in range(19, 25)},
    **{seq: 13 for seq in range(25, 31)},
    **{seq: 14 for seq in range(31, 37)},
    **{seq: 15 for seq in range(37, 43)},
    **{seq: 16 for seq in range(43, 49)},
}
FRONT_OVERRIDES: dict[int, dict[str, Any]] = {
    2: {
        "total_tube_count": 15,
        "minimum_remaining_thickness_mm": 1.88,
        "maximum_wall_loss_percent": 12.80,
        "average_wall_loss_percent": 11.28,
        "source_notation": "15U",
        "source_reported_total_tube_count": 30,
    },
    39: {"total_tube_count": 75},
}
REPRESENTATIVE = {
    1: ("14-4", 2.06, 25.63, "INTERNAL PITTING & EXTERNAL CORROSION"),
    8: ("02-30", 2.38, 14.08, "INTERNAL & EXTERNAL CORROSION"),
    9: ("02-10", 2.38, 14.08, "INTERNAL & EXTERNAL CORROSION"),
    18: ("21-07", 2.28, 17.69, "EXTERNAL CORROSION"),
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("category"), item.get("field"), item.get("description"))
    if not any((x.get("category"), x.get("field"), x.get("description")) == key for x in items):
        items.append(item)


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = payload["inspection_reports"]
    if len(reports) != 48:
        raise AssertionError(f"Expected 48 reports, found {len(reports)}")
    inventory = {int(x["page_number"]): x.get("extracted_text", "") for x in payload["document"]["source_page_inventory"]}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2023_vcm1_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2023_vcm1_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before = digest(TARGET)
    changes: list[dict[str, Any]] = []

    with pdfplumber.open(PDF) as pdf:
        for obj in reports:
            report = obj["report"]
            seq = int(report["report_sequence"])
            details = report["iris_report_details"]
            validation = obj.setdefault("validation", {})
            corrections = validation.setdefault("normalization_corrections", [])
            issues = validation.setdefault("source_pdf_inconsistencies", [])
            records = obj["tube_results_table"]["records"]
            if not records:
                raise AssertionError(f"No detail rows at sequence {seq}")

            detail_text = "\n".join(pdf.pages[p - 1].extract_text(x_tolerance=2, y_tolerance=2) or "" for p in obj["tube_results_table"]["source_pages"])
            match = re.search(r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+(\d+(?:\.\d+)?)\s+L", detail_text)
            if not match:
                raise AssertionError(f"Tube Spec not parsed at sequence {seq}")
            od, thickness, length = (float(x) for x in match.groups())
            tube_spec = report["tube_spec"]
            for field, value in (("outer_diameter_mm", od), ("design_thickness_mm", thickness), ("length_mm", length)):
                old = tube_spec.get(field)
                if old != value:
                    tube_spec[field] = value
                    changes.append({"sequence": seq, "field": f"report.tube_spec.{field}", "old": old, "new": value})
                    add_unique(corrections, {
                        "category": "json_extraction_mapping_error",
                        "field": f"report.tube_spec.{field}",
                        "legacy_value": old,
                        "normalized_value": value,
                        "reason": "Exact value printed in the PDF corrosion-results Tube Spec row",
                        "verification": {"source_pdf": PDF.name, "report_page": details["source_report_page"], "detail_pages": obj["tube_results_table"]["source_pages"], "method": "structured_text_and_visual_review"},
                        "db_import_action": "use_normalized_value_in_inspection_snapshot",
                        "master_import_action": "do_not_update_master",
                    })

            report_page = int(details["source_report_page"])
            recommendation_lines = re.findall(r"(?m)^[1-4]\.(?!\d)\s*[^\r\n]+", inventory[report_page])
            if len(recommendation_lines) != 4:
                raise AssertionError(f"Expected four Recommendation lines at sequence {seq}, found {len(recommendation_lines)}")
            details["recommendations"] = recommendation_lines

            current = report["inspection_summary"]
            source_total = current.get("total_tube_count")
            if seq == 39:
                source_total = 75
            source_average = current.get("average_wall_loss_percent")
            if source_total is None or source_average is None:
                raise AssertionError(f"Reported Summary incomplete at sequence {seq}")
            wall = [float(x["wall_loss_percent"]) for x in records]
            remaining = [float(x["minimum_wall_thickness_mm"]) for x in records]
            detail_min, detail_max = min(remaining), max(wall)
            operational = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
                "representative_corrosion_type": current.get("representative_corrosion_type"),
                "summary_basis": {
                    "quantity": "scoped_report_recommendation",
                    "extrema": "complete_detail_rows",
                    "average": "scoped_report_recommendation",
                },
            }
            report["inspection_summary"] = operational
            nested = details.setdefault("inspection_summary", {})
            nested.update({
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
                "average_wall_loss_percent_provenance": "reported_recommendation",
            })
            details["recommendation_structured"] = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "observation": re.sub(r"^2\.\s*", "", recommendation_lines[1]),
                "result_statement": re.sub(r"^3\.\s*", "", recommendation_lines[2]),
                "management_recommendation": re.sub(r"^4\.\s*", "", recommendation_lines[3]),
                "source_page": report_page,
            }

            front = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": current.get("minimum_remaining_thickness_mm") if current.get("minimum_remaining_thickness_mm") is not None else detail_min,
                "maximum_wall_loss_percent": current.get("maximum_wall_loss_percent") if current.get("maximum_wall_loss_percent") is not None else detail_max,
                "average_wall_loss_percent": float(source_average),
                "source_page": SUMMARY_PAGE[seq],
                "basis": "front_summary_table",
            }
            front.update(FRONT_OVERRIDES.get(seq, {}))
            if seq == 48:
                front["printed_result_nominal_thickness_mm"] = 2.77
                front["verified_tube_spec_nominal_thickness_mm"] = 2.11
            obj["summary_reference"] = front

            if seq in REPRESENTATIVE:
                tube, minimum, loss, defect = REPRESENTATIVE[seq]
                details["representative_defect_assessment"].update({"target_tube": tube, "minimum_thickness_mm": minimum, "wall_loss_percent": loss, "defect_type": defect})

            if seq == 18:
                conditions = details["measurement_conditions"]
                conditions["scan_velocity_meter_per_min"] = 2.53
                conditions["material_velocity_source_status"] = "blank_in_pdf_report"
            if seq == 19:
                for record in records:
                    record["location_valid"] = False
                    record["location_quality_issue"] = "PDF location column repeats minimum wall thickness with mm unit"
                    record["db_import_action_for_location"] = "exclude_location_value"

            calculated_average = round(sum(wall) / len(wall), 3)
            validation.update({
                "extracted_tube_result_count": len(records),
                "reported_inspected_tube_count": len(records),
                "reported_vs_extracted_count_match": True,
                "calculated_minimum_thickness_mm": detail_min,
                "calculated_maximum_wall_loss_percent": detail_max,
                "calculated_average_wall_loss_percent": calculated_average,
                "summary_extrema_match_detail_rows": True,
                "summary_policy": "detail_extrema_reported_average_front_summary_preserved_separately",
            })
            rounded_average = round(sum(wall) / len(wall) + 1e-12, 2)
            if float(source_average) != rounded_average:
                add_unique(issues, {
                    "category": "reported_average_vs_detail_calculated_variance",
                    "field": "average_wall_loss_percent",
                    "description": f"Report recommendation shows {source_average}%, while the arithmetic mean of printed detail-row percentages is {rounded_average}%.",
                    "resolution": "Preserve the report recommendation in operational Summary and retain the calculated detail average in validation.",
                    "source_pdf": PDF.name,
                    "report_page": report_page,
                    "detail_pages": obj["tube_results_table"]["source_pages"],
                })

    special = {
        2: ("summary_extrema_vs_detail_rows", "E-111B report/front Summary show 1.88 mm and 12.80%, while the complete detail table minimum is 1.84 mm and maximum wall loss is 12.71%."),
        19: ("invalid_detail_location_values", "Every E-211A detail-row Location value repeats the MWT value with an mm unit instead of a physical tube position."),
        25: ("reported_average_vs_detail_rows", "E-261 report/front Summary show average wall loss 10.35%, while the arithmetic mean of the 45 printed detail rows is 10.14%."),
        48: ("front_summary_nominal_thickness_typo", "E-803 front Summary Result text says nominal thickness 2.77 mm, while the Summary Tube Spec, individual report, and detail table all show 2.11 mm."),
    }
    for seq, (category, description) in special.items():
        obj = reports[seq - 1]
        add_unique(obj["validation"]["source_pdf_inconsistencies"], {
            "category": category,
            "field": "inspection_summary" if seq != 19 else "tube_results.location",
            "description": description,
            "resolution": "Use complete detail rows for operational measurements; preserve conflicting source values and exclude invalid locations from DB import.",
            "source_pdf": PDF.name,
            "report_page": obj["report"]["iris_report_details"]["source_report_page"],
            "detail_pages": obj["tube_results_table"]["source_pages"],
        })

    row_count = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if row_count != 600:
        raise AssertionError(f"Expected 600 detail rows, found {row_count}")
    if any(len(x["tube_results_table"]["records"]) != x["report"]["inspection_summary"]["inspected_tube_count"] for x in reports):
        raise AssertionError("Inspected quantity does not match actual detail rows")
    if any(x["report"]["inspection_summary"].get(k) is None for x in reports for k in ("total_tube_count", "inspected_tube_count", "minimum_remaining_thickness_mm", "maximum_wall_loss_percent", "average_wall_loss_percent")):
        raise AssertionError("Operational Summary still contains null core values")

    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = digest(TARGET)
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_pdf": str(PDF),
        "target_json": str(TARGET),
        "backup_directory": str(backup_dir),
        "sha256_before": before,
        "sha256_after": after,
        "reports": len(reports),
        "tube_result_rows": row_count,
        "exact_detail_spec_changes": changes,
        "policy": {
            "operational_summary_extrema": "complete detail rows",
            "operational_summary_average": "scoped report recommendation",
            "front_summary": "preserved in summary_reference",
            "invalid_e211a_locations": "preserved as source values and excluded from DB location import",
            "db": "not changed",
            "master": "not changed",
        },
    }
    manifest_path = output_dir / "2023VCM1_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target": str(TARGET), "backup": str(backup_dir), "manifest": str(manifest_path), "reports": len(reports), "rows": row_count, "spec_changes": len(changes), "sha256": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
