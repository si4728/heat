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
PDF = ROOT / "iris_test_report" / "2023_1P_VCM2.pdf"
TARGET = ROOT / "data" / "2023VCM2_IRIS2_all_tube_results.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def add_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("category"), item.get("field"), item.get("description"))
    if not any(
        (x.get("category"), x.get("field"), x.get("description")) == key
        for x in items
    ):
        items.append(item)


def normalized_label(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def parse_front_summary(pdf: pdfplumber.PDF) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for page_number in range(9, 19):
        tables = pdf.pages[page_number - 1].extract_tables()
        if len(tables) != 1:
            raise AssertionError(f"Expected one Summary table on page {page_number}")
        for row in tables[0][2:]:
            if not row[1]:
                continue
            text = row[8] or ""
            numbers = re.findall(r"\d+(?:\.\d+)?", text)
            if len(numbers) < 4:
                raise AssertionError(
                    f"Could not parse Summary result on page {page_number}: {text}"
                )
            total_raw = (row[6] or "").replace("\n", " ").strip()
            total_match = re.search(r"\d+", total_raw)
            u_match = re.search(r"\((\d+)U\)", total_raw, flags=re.IGNORECASE)
            if not total_match:
                raise AssertionError(
                    f"Could not parse Summary total on page {page_number}: {total_raw}"
                )
            result.append(
                {
                    "source_page": page_number,
                    "source_item": row[1].replace("\n", " ").strip(),
                    "outer_diameter_mm": float(row[2]),
                    "design_thickness_mm": float(row[3]),
                    "length_mm": float(row[4]),
                    "material": row[5],
                    "total_tube_source_notation": total_raw,
                    "total_tube_count": int(total_match.group()),
                    "u_tube_count": int(u_match.group(1)) if u_match else None,
                    "inspected_tube_count": int(row[7]),
                    "minimum_remaining_thickness_mm": float(numbers[1]),
                    "maximum_wall_loss_percent": float(numbers[2]),
                    "average_wall_loss_percent": float(numbers[3]),
                }
            )
    return result


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    reports = payload["inspection_reports"]
    if len(reports) != 55:
        raise AssertionError(f"Expected 55 reports, found {len(reports)}")
    inventory = {
        int(item["page_number"]): item.get("extracted_text", "")
        for item in payload["document"]["source_page_inventory"]
    }

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "backups" / f"json_before_2023_vcm2_finalization_{stamp}"
    output_dir = ROOT / "outputs" / "json_2023_vcm2_finalization_20260825" / stamp
    backup_dir.mkdir(parents=True)
    output_dir.mkdir(parents=True)
    shutil.copy2(TARGET, backup_dir / TARGET.name)
    before = digest(TARGET)
    changes: list[dict[str, Any]] = []

    with pdfplumber.open(PDF) as pdf:
        front_rows = parse_front_summary(pdf)
        if len(front_rows) != 55:
            raise AssertionError(f"Expected 55 front Summary rows, found {len(front_rows)}")

        for obj, front in zip(reports, front_rows):
            report = obj["report"]
            seq = int(report["report_sequence"])
            details = report["iris_report_details"]
            records = obj["tube_results_table"]["records"]
            validation = obj.setdefault("validation", {})
            corrections = validation.setdefault("normalization_corrections", [])
            issues = validation.setdefault("source_pdf_inconsistencies", [])
            if not records:
                raise AssertionError(f"No detail rows at sequence {seq}")

            labels = report.get("source_equipment_labels") or [report["equipment_id"]]
            if normalized_label(front["source_item"]) not in {
                normalized_label(label) for label in labels
            }:
                raise AssertionError(
                    f"Front Summary identity mismatch at sequence {seq}: "
                    f"{front['source_item']} vs {labels}"
                )

            detail_pages = obj["tube_results_table"]["source_pages"]
            detail_text = "\n".join(
                pdf.pages[page - 1].extract_text(x_tolerance=2, y_tolerance=2) or ""
                for page in detail_pages
            )
            spec_match = re.search(
                r"O\.D\s+(\d+(?:\.\d+)?)\s+x\s+(\d+(?:\.\d+)?)\s+T\s+x\s+(\d+(?:\.\d+)?)\s+L",
                detail_text,
            )
            if not spec_match:
                raise AssertionError(f"Tube Spec not parsed at sequence {seq}")
            od, thickness, length = (float(x) for x in spec_match.groups())
            tube_spec = report["tube_spec"]
            for field, value in (
                ("outer_diameter_mm", od),
                ("design_thickness_mm", thickness),
                ("length_mm", length),
            ):
                old = tube_spec.get(field)
                if old != value:
                    tube_spec[field] = value
                    changes.append(
                        {
                            "sequence": seq,
                            "equipment_id": report["equipment_id"],
                            "field": f"report.tube_spec.{field}",
                            "old": old,
                            "new": value,
                        }
                    )
                    add_unique(
                        corrections,
                        {
                            "category": "json_extraction_mapping_error",
                            "field": f"report.tube_spec.{field}",
                            "legacy_value": old,
                            "normalized_value": value,
                            "reason": "Exact value printed in the PDF corrosion-results Tube Spec row",
                            "verification": {
                                "source_pdf": PDF.name,
                                "report_page": details["source_report_page"],
                                "detail_pages": detail_pages,
                                "method": "structured_text_and_visual_review",
                            },
                            "db_import_action": "use_normalized_value_in_inspection_snapshot",
                            "master_import_action": "do_not_update_master",
                        },
                    )

            report_page = int(details["source_report_page"])
            recommendation_lines = re.findall(
                r"(?m)^[1-4]\.(?!\d)\s*[^\r\n]+", inventory[report_page]
            )
            if len(recommendation_lines) != 4:
                raise AssertionError(
                    f"Expected four Recommendation lines at sequence {seq}, "
                    f"found {len(recommendation_lines)}"
                )
            details["recommendations"] = recommendation_lines

            source_summary = report["inspection_summary"]
            source_total = source_summary.get("total_tube_count")
            source_inspected = validation.get(
                "reported_inspected_tube_count",
                source_summary.get("inspected_tube_count"),
            )
            source_average = source_summary.get("average_wall_loss_percent")
            if source_total is None or source_inspected is None or source_average is None:
                raise AssertionError(f"Reported Summary incomplete at sequence {seq}")

            wall = [float(record["wall_loss_percent"]) for record in records]
            remaining = [float(record["minimum_wall_thickness_mm"]) for record in records]
            detail_min = min(remaining)
            detail_max = max(wall)
            calculated_average = round(sum(wall) / len(wall), 3)
            operational = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "minimum_remaining_thickness_mm": detail_min,
                "maximum_wall_loss_percent": detail_max,
                "average_wall_loss_percent": float(source_average),
                "representative_corrosion_type": source_summary.get(
                    "representative_corrosion_type"
                ),
                "summary_basis": {
                    "quantity": "complete_detail_rows",
                    "extrema": "complete_detail_rows",
                    "average": "scoped_report_recommendation",
                    "total_tube_count": "scoped_report_recommendation",
                },
            }
            report["inspection_summary"] = operational

            nested = details.setdefault("inspection_summary", {})
            nested.update(
                {
                    "total_tube_count": int(source_total),
                    "inspected_tube_count": len(records),
                    "minimum_remaining_thickness_mm": detail_min,
                    "maximum_wall_loss_percent": detail_max,
                    "average_wall_loss_percent": float(source_average),
                    "average_wall_loss_percent_provenance": "reported_recommendation",
                    "reported_recommendation_inspected_tube_count": int(
                        source_inspected
                    ),
                }
            )
            details["recommendation_structured"] = {
                "total_tube_count": int(source_total),
                "inspected_tube_count": len(records),
                "reported_inspected_tube_count": int(source_inspected),
                "observation": re.sub(r"^2\.\s*", "", recommendation_lines[1]),
                "result_statement": re.sub(r"^3\.\s*", "", recommendation_lines[2]),
                "management_recommendation": re.sub(
                    r"^4\.\s*", "", recommendation_lines[3]
                ),
                "source_page": report_page,
            }

            front_reference = {
                "total_tube_count": front["total_tube_count"],
                "inspected_tube_count": front["inspected_tube_count"],
                "minimum_remaining_thickness_mm": front[
                    "minimum_remaining_thickness_mm"
                ],
                "maximum_wall_loss_percent": front["maximum_wall_loss_percent"],
                "average_wall_loss_percent": front["average_wall_loss_percent"],
                "source_page": front["source_page"],
                "source_item": front["source_item"],
                "basis": "front_summary_table",
                "total_tube_source_notation": front[
                    "total_tube_source_notation"
                ],
                "tube_spec_reference": {
                    "outer_diameter_mm": front["outer_diameter_mm"],
                    "design_thickness_mm": front["design_thickness_mm"],
                    "length_mm": front["length_mm"],
                    "material": front["material"],
                },
            }
            if front["u_tube_count"] is not None:
                front_reference["u_tube_count"] = front["u_tube_count"]
                front_reference["u_tube_count_normalization"] = (
                    "Numeric value inside the source U-tube notation"
                )
            obj["summary_reference"] = front_reference

            header_match = re.search(r"Tube ID Q'ty:?\s*(\d+)", detail_text)
            footer_match = re.search(r"Total\s*:\s*(\d+)", detail_text)
            header_count = int(header_match.group(1)) if header_match else None
            footer_count = int(footer_match.group(1)) if footer_match else None
            validation.update(
                {
                    "extracted_tube_result_count": len(records),
                    "reported_inspected_tube_count": int(source_inspected),
                    "front_summary_inspected_tube_count": front[
                        "inspected_tube_count"
                    ],
                    "detail_header_tube_id_qty": header_count,
                    "detail_footer_total": footer_count,
                    "reported_vs_extracted_count_match": int(source_inspected)
                    == len(records),
                    "front_summary_vs_extracted_count_match": front[
                        "inspected_tube_count"
                    ]
                    == len(records),
                    "detail_footer_vs_extracted_count_match": footer_count
                    == len(records),
                    "calculated_minimum_thickness_mm": detail_min,
                    "calculated_maximum_wall_loss_percent": detail_max,
                    "calculated_average_wall_loss_percent": calculated_average,
                    "summary_extrema_match_detail_rows": True,
                    "summary_policy": "detail_count_and_extrema_reported_average_front_summary_preserved_separately",
                }
            )

            rounded_average = round(sum(wall) / len(wall) + 1e-12, 2)
            if float(source_average) != rounded_average:
                add_unique(
                    issues,
                    {
                        "category": "reported_average_vs_detail_calculated_variance",
                        "field": "average_wall_loss_percent",
                        "description": (
                            f"Report recommendation shows {source_average}%, while the "
                            f"arithmetic mean of printed detail-row percentages is "
                            f"{rounded_average}%."
                        ),
                        "resolution": "Preserve the report recommendation in operational Summary and retain the calculated detail average in validation.",
                        "source_pdf": PDF.name,
                        "report_page": report_page,
                        "detail_pages": detail_pages,
                    },
                )

            if seq == 6:
                assessment = details["representative_defect_assessment"]
                assessment.update(
                    {
                        "wall_loss_percent": 7.58,
                        "source_reported_wall_loss_percent": 13.0,
                        "wall_loss_percent_provenance": "detail_row_and_nominal_thickness_calculation",
                    }
                )
            if seq == 32:
                assessment = details["representative_defect_assessment"]
                assessment.update(
                    {
                        "wall_loss_percent": 12.80,
                        "source_reported_wall_loss_percent": 12.08,
                        "wall_loss_percent_provenance": "detail_row_and_nominal_thickness_calculation",
                    }
                )

    special = {
        1: {
            "category": "front_summary_vs_report_average_variance",
            "field": "average_wall_loss_percent",
            "description": "Front Summary shows 7.97%, while the individual report Recommendation shows 7.91% and the printed detail-row arithmetic mean is 7.92% at two decimals.",
            "resolution": "Use the individual report Recommendation average operationally and preserve the front Summary value separately.",
        },
        5: {
            "category": "count_label_inconsistency",
            "field": "tube_id_qty",
            "description": "PDF detail header Tube ID Q'ty is 20, while the front Summary, report Recommendation, footer Total, and 25 detail rows are 25.",
            "resolution": "Preserve the source header typo and use the verified 25 detail rows operationally.",
        },
        6: {
            "category": "representative_result_wall_loss_typo",
            "field": "maximum_wall_loss_percent",
            "description": "The individual report image caption shows 13.0%, while the front Summary, Recommendation, detail row, and calculation from 2.11 mm nominal and 1.95 mm remaining thickness show 7.58%.",
            "resolution": "Use 7.58% operationally and preserve 13.0% as the source report typo.",
        },
        11: {
            "category": "reported_detail_count_inconsistency",
            "field": "inspected_tube_count",
            "description": "The individual report Recommendation says 20 inspected, while the front Summary, Tube ID Q'ty, footer Total, and complete detail table contain 10.",
            "resolution": "Use 10 actual detail rows operationally and preserve the reported 20 separately.",
        },
        32: {
            "category": "reported_wall_loss_digit_transposition",
            "field": "maximum_wall_loss_percent",
            "description": "The front Summary and individual report show 12.08%, while the highlighted detail row and calculation from 2.11 mm nominal and 1.84 mm remaining thickness show 12.80%.",
            "resolution": "Use the complete detail-table value 12.80% operationally and preserve 12.08% as source text.",
        },
        34: {
            "category": "front_summary_vs_report_average_variance",
            "field": "average_wall_loss_percent",
            "description": "Front Summary shows 6.64%, while the individual report Recommendation and printed detail-row arithmetic mean show 9.81%.",
            "resolution": "Use 9.81% operationally and preserve the front Summary value separately.",
        },
    }
    for seq, issue in special.items():
        obj = reports[seq - 1]
        issue = dict(issue)
        issue.update(
            {
                "source_pdf": PDF.name,
                "report_page": obj["report"]["iris_report_details"][
                    "source_report_page"
                ],
                "detail_pages": obj["tube_results_table"]["source_pages"],
            }
        )
        add_unique(obj["validation"]["source_pdf_inconsistencies"], issue)

    row_count = sum(len(x["tube_results_table"]["records"]) for x in reports)
    if row_count != 830:
        raise AssertionError(f"Expected 830 detail rows, found {row_count}")
    if any(
        len(x["tube_results_table"]["records"])
        != x["report"]["inspection_summary"]["inspected_tube_count"]
        for x in reports
    ):
        raise AssertionError("Inspected quantity does not match actual detail rows")
    core = (
        "total_tube_count",
        "inspected_tube_count",
        "minimum_remaining_thickness_mm",
        "maximum_wall_loss_percent",
        "average_wall_loss_percent",
    )
    if any(
        x["report"]["inspection_summary"].get(key) is None
        for x in reports
        for key in core
    ):
        raise AssertionError("Operational Summary still contains null core values")

    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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
        "verified_source_inconsistencies": [
            {"sequence": seq, **value} for seq, value in special.items()
        ],
        "policy": {
            "operational_inspected_count": "complete detail rows",
            "operational_summary_extrema": "complete detail rows",
            "operational_summary_average": "scoped report Recommendation",
            "front_summary": "preserved in summary_reference",
            "u_tube_notation": "preserve total notation and expose numeric U-tube count separately",
            "db": "not changed",
            "master": "not changed",
        },
    }
    manifest_path = output_dir / "2023VCM2_FINALIZATION_MANIFEST_20260825.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "target": str(TARGET),
                "backup": str(backup_dir),
                "manifest": str(manifest_path),
                "reports": len(reports),
                "rows": row_count,
                "spec_changes": len(changes),
                "sha256": after,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
