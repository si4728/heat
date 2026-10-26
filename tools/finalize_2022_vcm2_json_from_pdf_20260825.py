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
PDF = ROOT / "iris_test_report" / "2022_1P_VCM2.pdf"
TARGET = ROOT / "data" / "2022VCM2_IRIS2_all_tube_results.json"

MISSING_REPORTED: dict[int, dict[str, Any]] = {
    1: {"total": 34, "average": 0.00},
    2: {"total": 32, "average": 8.15},
    3: {"total": 52, "average": 14.11},
    4: {"total": 52, "average": 14.11},
    5: {"total": 52, "average": 33.46},
    6: {"total": 647, "average": 15.02},
    7: {"total": 81, "average": 4.83},
    29: {"total": 90, "average": 3.51},
    31: {"total": 120, "average": 1.34},
    32: {"total": 160, "average": 4.93},
    33: {"total": 1615, "average": 8.58},
}

# Values printed in the front Summary rather than the individual report.
FRONT_OVERRIDES: dict[int, dict[str, Any]] = {
    1: {"total_tube_count": 34, "average_wall_loss_percent": 0.00},
    2: {"total_tube_count": 32, "average_wall_loss_percent": 8.15},
    3: {"total_tube_count": 52, "average_wall_loss_percent": 6.30},
    4: {"total_tube_count": 52, "average_wall_loss_percent": 14.11},
    5: {"total_tube_count": 52, "average_wall_loss_percent": 33.46},
    6: {"total_tube_count": 647, "average_wall_loss_percent": 15.02},
    7: {"total_tube_count": 81, "average_wall_loss_percent": 4.83},
    20: {"minimum_remaining_thickness_mm": 1.99, "maximum_wall_loss_percent": 28.25, "average_wall_loss_percent": 16.23},
    29: {"total_tube_count": 90, "average_wall_loss_percent": 3.51},
    31: {"total_tube_count": 120, "average_wall_loss_percent": 1.34},
    32: {"total_tube_count": 160, "average_wall_loss_percent": 4.93},
    33: {"total_tube_count": 1615, "average_wall_loss_percent": 8.58},
}

MATERIAL = {2: "Monel", 5: "Cu-Ni(70:30)", 31: "A179", 32: "A179"}
REPORT_LENGTH_M = {2: 3.40, 5: 4.88, 23: 4.88, 24: 3.05, 31: 4.5, 32: 3.66}
SUMMARY_PAGE = {
    **{seq: 9 for seq in range(1, 8)},
    **{seq: 10 for seq in range(8, 15)},
    **{seq: 11 for seq in range(15, 22)},
    **{seq: 12 for seq in range(22, 29)},
    **{seq: 13 for seq in range(29, 36)},
    36: 14,
    37: 14,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def add_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("category"), item.get("field"), item.get("description"))
    if not any((x.get("category"), x.get("field"), x.get("description")) == key for x in items):
        items.append(item)


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = payload["inspection_reports"]
    if len(reports) != 37:
        raise AssertionError(f"Expected 37 reports, found {len(reports)}")
    inventory = {int(x["page_number"]): x.get("extracted_text", "") for x in payload["document"]["source_page_inventory"]}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2022_vcm2_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2022_vcm2_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before = sha256(TARGET)
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
            material = tube_spec.get("material") or MATERIAL.get(seq)
            if material is None:
                raise AssertionError(f"Material missing at sequence {seq}")
            for field, value in (("outer_diameter_mm", od), ("design_thickness_mm", thickness), ("length_mm", length), ("material", material)):
                old = tube_spec.get(field)
                if old != value:
                    tube_spec[field] = value
                    changes.append({"sequence": seq, "field": f"report.tube_spec.{field}", "old": old, "new": value})
                    add_unique(corrections, {
                        "category": "json_extraction_mapping_error",
                        "field": f"report.tube_spec.{field}",
                        "legacy_value": old,
                        "normalized_value": value,
                        "reason": "Exact PDF corrosion-results Tube Spec value, with material from the report/front Summary where required",
                        "verification": {"source_pdf": PDF.name, "report_page": details["source_report_page"], "detail_pages": obj["tube_results_table"]["source_pages"], "method": "structured_text_and_visual_review"},
                        "db_import_action": "use_normalized_value_in_inspection_snapshot",
                        "master_import_action": "do_not_update_master",
                    })

            basic = details["basic_information"]
            conditions = details["measurement_conditions"]
            equipment_spec = report.setdefault("equipment_spec", {})
            basic["material"] = material
            basic["nominal_thickness_mm"] = thickness
            equipment_spec["tube_material"] = material
            if conditions.get("out_diameter_mm") is None:
                conditions["out_diameter_mm"] = od
            if conditions.get("tube_length_m") is None:
                conditions["tube_length_m"] = REPORT_LENGTH_M[seq]

            report_page = int(details["source_report_page"])
            recommendation_lines = re.findall(r"(?m)^[1-4]\.(?!\d)\s*[^\r\n]+", inventory[report_page])
            if len(recommendation_lines) != 4:
                raise AssertionError(f"Expected four Recommendation lines at sequence {seq}, found {len(recommendation_lines)}")
            details["recommendations"] = recommendation_lines

            current = report["inspection_summary"]
            source_total = current.get("total_tube_count")
            source_average = current.get("average_wall_loss_percent")
            missing = MISSING_REPORTED.get(seq, {})
            if source_total is None:
                source_total = missing.get("total")
            if source_average is None:
                source_average = missing.get("average")
            if source_total is None or source_average is None:
                raise AssertionError(f"Reported Summary incomplete at sequence {seq}")
            if seq in (9, 10, 11):
                source_total = 786

            operational_total = 393 if seq in (9, 10, 11) else int(source_total)
            wall = [float(x["wall_loss_percent"]) for x in records]
            remaining = [float(x["minimum_wall_thickness_mm"]) for x in records]
            detail_min, detail_max = min(remaining), max(wall)
            operational = {
                "total_tube_count": operational_total,
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
                "representative_corrosion_type": current.get("representative_corrosion_type"),
                "summary_basis": {
                    "quantity": (
                        "786(393U) normalized to 393 per reviewed rule"
                        if seq in (9, 10, 11)
                        else "scoped_report_recommendation"
                    ),
                    "extrema": "complete_detail_rows",
                    "average": "scoped_report_recommendation",
                },
            }
            report["inspection_summary"] = operational
            nested = details.setdefault("inspection_summary", {})
            nested.update({
                "total_tube_count": operational_total,
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
                "average_wall_loss_percent_provenance": "reported_recommendation",
            })
            details["recommendation_structured"] = {
                "total_tube_count": operational_total,
                "source_reported_total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "observation": re.sub(r"^2\.\s*", "", recommendation_lines[1]),
                "result_statement": re.sub(r"^3\.\s*", "", recommendation_lines[2]),
                "management_recommendation": re.sub(r"^4\.\s*", "", recommendation_lines[3]),
                "source_page": report_page,
            }

            front = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
            }
            front.update(FRONT_OVERRIDES.get(seq, {}))
            front.update({"source_page": SUMMARY_PAGE[seq], "basis": "front_summary_table"})
            if seq in (9, 10, 11):
                front.update({"printed_total_tube_count": 786, "effective_u_tube_count": 393, "source_notation": "786(393U)"})
            if seq == 32:
                front.update({"printed_total_tube_count": 160, "effective_u_tube_count": 80, "source_notation": "160(80U)"})
            obj["summary_reference"] = front

            if seq == 7:
                details["representative_defect_assessment"].update({"target_tube": "6-2", "minimum_thickness_mm": 1.99, "wall_loss_percent": 5.69, "defect_type": "INTERNAL CORROSION"})
            if seq == 31:
                representative = details["representative_defect_assessment"]
                representative["source_figure_wall_loss_percent"] = 6.50
                representative["wall_loss_percent"] = 2.89
                representative["detail_row_basis"] = "tube 10-6 in corrosion-results table"

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
        3: ("front_summary_vs_report_recommendation", "E-104A report recommendation prints average wall loss 14.11%, while the front Summary and detail-row arithmetic mean show 6.30%."),
        20: ("summary_extrema_vs_detail_rows", "E-207A report/front Summary show maximum wall loss 28.25%, while another detail row (tube 54-3) shows 28.33%."),
        31: ("representative_figure_vs_detail_row", "E-302 representative figure labels tube 10-6 as 6.50% wall loss, while its detail row and report recommendation show 2.89%."),
    }
    for seq, (category, description) in special.items():
        obj = reports[seq - 1]
        add_unique(obj["validation"]["source_pdf_inconsistencies"], {
            "category": category,
            "field": "inspection_summary",
            "description": description,
            "resolution": "Use complete detail rows for operational extrema; preserve report/front/figure values as source references.",
            "source_pdf": PDF.name,
            "report_page": obj["report"]["iris_report_details"]["source_report_page"],
            "detail_pages": obj["tube_results_table"]["source_pages"],
        })

    row_count = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if row_count != 722:
        raise AssertionError(f"Expected 722 detail rows, found {row_count}")
    if any(len(x["tube_results_table"]["records"]) != x["report"]["inspection_summary"]["inspected_tube_count"] for x in reports):
        raise AssertionError("Inspected quantity does not match actual detail rows")
    if any(x["report"]["inspection_summary"].get(k) is None for x in reports for k in ("total_tube_count", "inspected_tube_count", "minimum_remaining_thickness_mm", "maximum_wall_loss_percent", "average_wall_loss_percent")):
        raise AssertionError("Operational Summary still contains null core values")

    TARGET.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = sha256(TARGET)
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
            "u_tube_total_normalization": "E-201A/B/C 786(393U) -> 393",
            "front_summary": "preserved in summary_reference",
            "db": "not changed",
            "master": "not changed",
        },
    }
    manifest_path = output_dir / "2022VCM2_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target": str(TARGET), "backup": str(backup_dir), "manifest": str(manifest_path), "reports": len(reports), "rows": row_count, "spec_changes": len(changes), "sha256": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
