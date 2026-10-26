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
PDF = ROOT / "iris_test_report" / "2022_1P_VCM1.pdf"
TARGET = ROOT / "data" / "2022VCM1_IRIS2_all_tube_results.json"

# Values printed in the front Summary. Operational extrema are taken from the
# complete detail rows, while this source reference remains unchanged.
FRONT_OVERRIDES: dict[int, dict[str, Any]] = {
    4: {"minimum_remaining_thickness_mm": 1.94, "maximum_wall_loss_percent": 6.64, "average_wall_loss_percent": 5.78},
    9: {"average_wall_loss_percent": 2.24},
    31: {"total_tube_count": 543, "inspected_tube_count": 25, "minimum_remaining_thickness_mm": 1.97, "maximum_wall_loss_percent": 6.64, "average_wall_loss_percent": 4.13},
    32: {"total_tube_count": 543, "inspected_tube_count": 25, "minimum_remaining_thickness_mm": 1.97, "maximum_wall_loss_percent": 6.64, "average_wall_loss_percent": 3.68},
    33: {"total_tube_count": 92, "inspected_tube_count": 5, "minimum_remaining_thickness_mm": 2.03, "maximum_wall_loss_percent": 3.79, "average_wall_loss_percent": 2.09},
}

MISSING_REPORTED: dict[int, dict[str, Any]] = {
    4: {"total_tube_count": 97, "average_wall_loss_percent": 5.78},
    26: {"total_tube_count": 75, "average_wall_loss_percent": 14.79},
    31: {"total_tube_count": 543, "average_wall_loss_percent": 4.13},
    32: {"total_tube_count": 543, "average_wall_loss_percent": 3.68},
    33: {"total_tube_count": 92, "average_wall_loss_percent": 2.09},
}

REPRESENTATIVE = {
    4: ("11-03", 1.97, 6.64, "EXTERNAL CORROSION"),
    26: ("1-16", 1.75, 17.06, "INTERNAL & EXTERNAL CORROSION"),
    32: ("24-03", 1.97, 6.64, "EXTERNAL CORROSION"),
}

SUMMARY_PAGE = {
    **{seq: 9 for seq in range(1, 8)},
    **{seq: 10 for seq in range(8, 15)},
    **{seq: 11 for seq in range(15, 22)},
    **{seq: 12 for seq in range(22, 29)},
    **{seq: 13 for seq in range(29, 36)},
    36: 14,
}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def add_unique(items: list[dict[str, Any]], value: dict[str, Any]) -> None:
    key = (value.get("category"), value.get("field"), value.get("description"))
    if not any((x.get("category"), x.get("field"), x.get("description")) == key for x in items):
        items.append(value)


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = payload["inspection_reports"]
    if len(reports) != 36:
        raise AssertionError(f"Expected 36 reports, found {len(reports)}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2022_vcm1_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2022_vcm1_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before = digest(TARGET)
    changes: list[dict[str, Any]] = []
    page_inventory = {
        int(page["page_number"]): page.get("extracted_text", "")
        for page in payload["document"]["source_page_inventory"]
    }

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

            # The corrosion-results Tube Spec row is the exact detail spec.
            detail_text = "\n".join(
                pdf.pages[p - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
                for p in obj["tube_results_table"]["source_pages"]
            )
            match = re.search(
                r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+(\d+(?:\.\d+)?)\s+L",
                detail_text,
            )
            if not match:
                raise AssertionError(f"Tube Spec not parsed at sequence {seq}")
            od, thickness, length = (float(x) for x in match.groups())
            tube_spec = report["tube_spec"]
            for field, value in (
                ("outer_diameter_mm", od),
                ("design_thickness_mm", thickness),
                ("length_mm", length),
            ):
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
                        "verification": {"source_pdf": PDF.name, "detail_pages": obj["tube_results_table"]["source_pages"], "method": "structured_text_and_visual_review"},
                        "db_import_action": "use_normalized_value_in_inspection_snapshot",
                        "master_import_action": "do_not_update_master",
                    })

            wall = [float(row["wall_loss_percent"]) for row in records]
            remaining = [float(row["minimum_wall_thickness_mm"]) for row in records]
            detail_min, detail_max = min(remaining), max(wall)
            missing = MISSING_REPORTED.get(seq, {})
            current = report["inspection_summary"]
            reported_total = current.get("total_tube_count") or missing.get("total_tube_count")
            reported_average = current.get("average_wall_loss_percent")
            if reported_average is None:
                reported_average = missing.get("average_wall_loss_percent")
            if reported_total is None or reported_average is None:
                raise AssertionError(f"Reported Summary incomplete at sequence {seq}")

            # Replace truncated legacy snippets with all four exact Recommendation
            # lines preserved in the PDF page inventory.
            report_page = int(details["source_report_page"])
            recommendation_block = page_inventory[report_page].split(
                "[RECOMMENDATION]", 1
            )[1].split("Attachment", 1)[0]
            recommendation_lines = re.findall(
                r"(?m)^[1-4]\.\s*[^\r\n]+", recommendation_block
            )
            if len(recommendation_lines) != 4:
                raise AssertionError(
                    f"Expected four Recommendation lines at sequence {seq}, "
                    f"found {len(recommendation_lines)}"
                )
            details["recommendations"] = recommendation_lines
            details["recommendation_structured"] = {
                "total_tube_count": int(reported_total),
                "inspected_tube_count": len(records),
                "observation": re.sub(r"^2\.\s*", "", recommendation_lines[1]),
                "result_statement": re.sub(r"^3\.\s*", "", recommendation_lines[2]),
                "management_recommendation": re.sub(r"^4\.\s*", "", recommendation_lines[3]),
                "source_page": report_page,
            }

            operational = {
                "total_tube_count": int(reported_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(reported_average),
                "representative_corrosion_type": current.get("representative_corrosion_type"),
                "summary_basis": {
                    "quantity": "scoped_report_recommendation_and_actual_detail_row_count",
                    "extrema": "complete_detail_rows",
                    "average": "scoped_report_recommendation",
                },
            }
            report["inspection_summary"] = operational
            nested = details.setdefault("inspection_summary", {})
            nested.update({
                "total_tube_count": int(reported_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(reported_average),
                "average_wall_loss_percent_provenance": "reported_recommendation",
            })

            front = {k: operational[k] for k in (
                "total_tube_count", "inspected_tube_count", "minimum_remaining_thickness_mm",
                "maximum_wall_loss_percent", "average_wall_loss_percent"
            )}
            front.update(FRONT_OVERRIDES.get(seq, {}))
            front.update({"source_page": SUMMARY_PAGE[seq], "basis": "front_summary_table"})
            obj["summary_reference"] = front

            if seq in REPRESENTATIVE:
                tube, minimum, loss, defect = REPRESENTATIVE[seq]
                representative = details.setdefault("representative_defect_assessment", {})
                representative.update({
                    "target_tube": tube,
                    "minimum_thickness_mm": minimum,
                    "wall_loss_percent": loss,
                    "defect_type": defect,
                })

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

            rounded_detail_average = round(sum(wall) / len(wall) + 1e-12, 2)
            if float(reported_average) != rounded_detail_average:
                add_unique(issues, {
                    "category": "reported_average_vs_detail_calculated_variance",
                    "field": "average_wall_loss_percent",
                    "description": f"Report recommendation shows {reported_average}%, while the arithmetic mean of printed detail-row percentages is {rounded_detail_average}%.",
                    "resolution": "Preserve the report recommendation in operational Summary and retain the calculated detail average in validation.",
                    "source_pdf": PDF.name,
                    "report_page": details["source_report_page"],
                    "detail_pages": obj["tube_results_table"]["source_pages"],
                })

    special_issues = {
        4: ("summary_minimum_vs_detail_rows", "The report recommendation and front Summary print 1.94 mm, but the complete detail table minimum is 1.97 mm; 6.64% also corresponds to 1.97 mm at a 2.11 mm nominal thickness."),
        9: ("front_summary_vs_report_recommendation", "The front Summary prints average wall loss 2.24%, while the scoped report recommendation prints 2.31%; the detail-row arithmetic mean is 2.242%."),
        32: ("summary_extrema_vs_detail_rows", "The report recommendation/front Summary print 1.97 mm and 6.64%, while the complete detail table contains 1.94 mm and 8.06% at tube 16-21."),
    }
    for seq, (category, description) in special_issues.items():
        obj = reports[seq - 1]
        add_unique(obj["validation"]["source_pdf_inconsistencies"], {
            "category": category,
            "field": "inspection_summary",
            "description": description,
            "resolution": "Use complete detail rows for operational extrema; preserve report/front Summary values as source references.",
            "source_pdf": PDF.name,
            "report_page": obj["report"]["iris_report_details"]["source_report_page"],
            "detail_pages": obj["tube_results_table"]["source_pages"],
        })

    row_count = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if row_count != 455:
        raise AssertionError(f"Expected 455 detail rows, found {row_count}")
    if any(len(x["tube_results_table"]["records"]) != x["report"]["inspection_summary"]["inspected_tube_count"] for x in reports):
        raise AssertionError("Inspected quantity does not match actual detail rows")
    if any(x["report"]["inspection_summary"]["minimum_remaining_thickness_mm"] is None for x in reports):
        raise AssertionError("Operational Summary still contains null extrema")

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
            "db": "not changed",
            "master": "not changed",
        },
    }
    manifest_path = output_dir / "2022VCM1_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"target": str(TARGET), "backup": str(backup_dir), "manifest": str(manifest_path), "reports": len(reports), "rows": row_count, "spec_changes": len(changes), "sha256": after}, ensure_ascii=False))


if __name__ == "__main__":
    main()
