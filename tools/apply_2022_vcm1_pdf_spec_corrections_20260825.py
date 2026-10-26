from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT = Path(r"C:\access\heat\iris2")
DATA_DIR = PROJECT / "data"
TARGET_FILE = DATA_DIR / "2022VCM1_IRIS2_all_tube_results.json"
PDF_FILE = PROJECT / "iris_test_report" / "2022_1P_VCM1.pdf"

# Values visually verified on each report page and corrosion-results page.
# report_page/detail_page are one-based PDF physical page numbers.
CORRECTIONS: dict[int, dict[str, Any]] = {
    6: {
        "equipment_id": "E-121A", "label": "E-121A(BTM)",
        "report_page": 51, "detail_page": 53,
        "material": "Cu-Ni(70:30)", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 3657.0, "report_length_m": 3.66,
    },
    7: {
        "equipment_id": "E-123", "report_page": 57, "detail_page": 59,
        "material": "Cu-Ni(70:30)", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 1260.0, "report_length_m": 1.3,
    },
    10: {
        "equipment_id": "E-201A", "report_page": 72, "detail_page": 74,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 4876.0, "report_length_m": 4.9,
    },
    11: {
        "equipment_id": "E-201B", "report_page": 78, "detail_page": 80,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 4876.0, "report_length_m": 4.9,
    },
    13: {
        "equipment_id": "E-211A", "report_page": 91, "detail_page": 93,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 2438.0, "report_length_m": 2.4,
    },
    14: {
        "equipment_id": "E-211B", "report_page": 97, "detail_page": 99,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 2438.0, "report_length_m": 2.4,
    },
    22: {
        "equipment_id": "E-330B", "report_page": 161, "detail_page": 163,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 2438.0, "report_length_m": 2.4,
    },
    23: {
        "equipment_id": "E-330C", "report_page": 166, "detail_page": 168,
        "material": "Cu-Ni(70:30)", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 3640.0, "report_length_m": 3.64,
    },
    34: {
        "equipment_id": "E-801", "report_page": 239, "detail_page": 241,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 2438.0, "report_length_m": 2.4,
    },
    35: {
        "equipment_id": "E-802", "report_page": 244, "detail_page": 246,
        "material": "A179", "od_mm": 25.4, "thickness_mm": 2.77,
        "length_mm": 2438.0, "report_length_m": 2.4,
    },
    36: {
        "equipment_id": "E-803", "report_page": 251, "detail_page": 253,
        "material": "SUSTP304", "od_mm": 19.05, "thickness_mm": 2.11,
        "length_mm": 1829.0, "report_length_m": 1.8,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    key = (item.get("category"), item.get("field"), item.get("description"))
    for current in items:
        current_key = (
            current.get("category"), current.get("field"), current.get("description")
        )
        if current_key == key:
            return
    items.append(item)


def correction_entry(
    field: str, old: Any, new: Any, config: dict[str, Any], reason: str
) -> dict[str, Any]:
    return {
        "category": "json_extraction_mapping_error",
        "field": field,
        "legacy_value": old,
        "normalized_value": new,
        "reason": reason,
        "verification": {
            "source_pdf": PDF_FILE.name,
            "report_page": config["report_page"],
            "detail_page": config["detail_page"],
            "method": "visual_review_report_and_corrosion_results_pages",
        },
        "db_import_action": "use_normalized_value_in_inspection_snapshot",
        "master_import_action": "do_not_update_master",
    }


def main() -> None:
    if not TARGET_FILE.exists() or not PDF_FILE.exists():
        raise FileNotFoundError("Required JSON or PDF file is missing")

    all_json_paths = sorted(DATA_DIR.glob("*IRIS2_all_tube_results.json"))
    if len(all_json_paths) != 11:
        raise AssertionError(f"Expected 11 JSON files, found {len(all_json_paths)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT / "backups" / f"json_before_pdf_spec_corrections_{timestamp}"
    output_dir = PROJECT / "outputs" / "json_pdf_spec_corrections_20260825" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    for path in all_json_paths:
        shutil.copy2(path, backup_dir / path.name)

    before_hash = sha256(TARGET_FILE)
    payload = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    reports = {
        int(obj["report"]["report_sequence"]): obj
        for obj in payload["inspection_reports"]
    }
    missing = sorted(set(CORRECTIONS) - set(reports))
    if missing:
        raise AssertionError(f"Missing report sequences: {missing}")

    changes: list[dict[str, Any]] = []
    for sequence, config in CORRECTIONS.items():
        obj = reports[sequence]
        report = obj["report"]
        if report.get("equipment_id") != config["equipment_id"]:
            raise AssertionError(
                f"Sequence {sequence} expected {config['equipment_id']}, "
                f"found {report.get('equipment_id')}"
            )
        details = report.get("iris_report_details") or report.get("iris_9000_report_details")
        if not isinstance(details, dict):
            raise AssertionError(f"Report details missing at sequence {sequence}")
        basic = details.setdefault("basic_information", {})
        conditions = details.setdefault("measurement_conditions", {})
        tube_spec = report.setdefault("tube_spec", {})
        equipment_spec = report.setdefault("equipment_spec", {})
        validation = obj.setdefault("validation", {})
        corrections = validation.setdefault("normalization_corrections", [])
        inconsistencies = validation.setdefault("source_pdf_inconsistencies", [])

        # Remove the earlier provisional classification. The PDF itself is correct.
        validation["source_pdf_inconsistencies"] = [
            item for item in inconsistencies
            if item.get("category") != "invalid_detail_spec_value"
        ]
        validation["normalization_corrections"] = [
            item for item in corrections
            if item.get("category") != "invalid_detail_spec_value"
        ]
        corrections = validation["normalization_corrections"]

        fields = [
            ("report.tube_spec.material", tube_spec.get("material"), config["material"],
             "Material read from the PDF report page"),
            ("report.tube_spec.outer_diameter_mm", tube_spec.get("outer_diameter_mm"), config["od_mm"],
             "Out Diameter read from the PDF report and Tube Spec rows"),
            ("report.tube_spec.design_thickness_mm", tube_spec.get("design_thickness_mm"), config["thickness_mm"],
             "Original Thickness read from the PDF report and Tube Spec rows; 9000 belongs to the IRIS model title"),
            ("report.tube_spec.length_mm", tube_spec.get("length_mm"), config["length_mm"],
             "Exact millimetre length read from the corrosion-results Tube Spec row"),
            ("report.equipment_spec.tube_material", equipment_spec.get("tube_material"), config["material"],
             "Tube material read from the PDF report page"),
            ("basic_information.material", basic.get("material"), config["material"],
             "Material read from the PDF report page"),
            ("basic_information.nominal_thickness_mm", basic.get("nominal_thickness_mm"), config["thickness_mm"],
             "Original Thickness read from the PDF report page"),
            ("measurement_conditions.out_diameter_mm", conditions.get("out_diameter_mm"), config["od_mm"],
             "Out Diameter read from the PDF report page"),
            ("measurement_conditions.tube_length_m", conditions.get("tube_length_m"), config["report_length_m"],
             "Rounded metre length read from the PDF report page"),
        ]
        for field, old, new, reason in fields:
            if old != new:
                append_unique(corrections, correction_entry(field, old, new, config, reason))
                changes.append(
                    {
                        "report_sequence": sequence,
                        "equipment_id": config["equipment_id"],
                        "field": field,
                        "old": old,
                        "new": new,
                    }
                )

        tube_spec.update(
            {
                "material": config["material"],
                "outer_diameter_mm": config["od_mm"],
                "design_thickness_mm": config["thickness_mm"],
                "length_mm": config["length_mm"],
            }
        )
        equipment_spec["tube_material"] = config["material"]
        basic["material"] = config["material"]
        basic["nominal_thickness_mm"] = config["thickness_mm"]
        conditions["out_diameter_mm"] = config["od_mm"]
        conditions["tube_length_m"] = config["report_length_m"]
        if sequence == 6:
            basic["equipment_name"] = "T-120 Reboiler"

        # Revalidate every detail row against the verified PDF nominal thickness.
        mismatches: list[dict[str, Any]] = []
        for record in obj.get("tube_results_table", {}).get("records") or []:
            minimum = record.get("minimum_wall_thickness_mm")
            depth = record.get("wall_loss_depth_mm")
            percent = record.get("wall_loss_percent")
            if minimum is None or depth is None or percent is None:
                continue
            expected_depth = round(config["thickness_mm"] - float(minimum), 2)
            expected_percent = round(expected_depth / config["thickness_mm"] * 100, 2)
            if abs(float(depth) - expected_depth) > 0.011 or abs(float(percent) - expected_percent) > 0.011:
                mismatches.append(
                    {
                        "tube_id": record.get("tube_id"),
                        "source_page": record.get("source_page"),
                        "pdf_wall_loss_depth_mm": depth,
                        "calculated_wall_loss_depth_mm": expected_depth,
                        "pdf_wall_loss_percent": percent,
                        "calculated_wall_loss_percent": expected_percent,
                    }
                )
        if mismatches:
            raise AssertionError(
                f"Verified nominal thickness still produces mismatches for "
                f"{config['equipment_id']}: {mismatches}"
            )
        validation["row_calculation_mismatch_count"] = 0
        validation["row_calculation_mismatches"] = []
        validation["row_calculation_status"] = "VALID_PDF_VERIFIED_SPEC"

    # E-330B summary and representative assessment are clearly printed on page 161.
    e330b = reports[22]
    summary = e330b["report"]["inspection_summary"]
    summary_ref = e330b.get("summary_reference") or {}
    details = e330b["report"]["iris_report_details"]
    representative = details.setdefault("representative_defect_assessment", {})
    for target in (summary, summary_ref):
        target["minimum_remaining_thickness_mm"] = 2.66
        target["maximum_wall_loss_percent"] = 3.97
    representative.update(
        {
            "target_tube": "1-2",
            "minimum_thickness_mm": 2.66,
            "wall_loss_percent": 3.97,
            "defect_type": "INTERNAL & EXTERNAL CORROSION",
        }
    )
    e330b["summary_reference"] = summary_ref
    e330b_corrections = e330b["validation"]["normalization_corrections"]
    append_unique(
        e330b_corrections,
        correction_entry(
            "report.inspection_summary.minimum_remaining_thickness_mm",
            None, 2.66, CORRECTIONS[22],
            "Minimum thickness printed in the PDF recommendation and highlighted result rows",
        ),
    )
    append_unique(
        e330b_corrections,
        correction_entry(
            "report.inspection_summary.maximum_wall_loss_percent",
            None, 3.97, CORRECTIONS[22],
            "Maximum wall loss printed in the PDF recommendation and highlighted result rows",
        ),
    )
    changes.extend(
        [
            {"report_sequence": 22, "equipment_id": "E-330B", "field": "minimum_remaining_thickness_mm", "old": None, "new": 2.66},
            {"report_sequence": 22, "equipment_id": "E-330B", "field": "maximum_wall_loss_percent", "old": None, "new": 3.97},
            {"report_sequence": 22, "equipment_id": "E-330B", "field": "representative_defect_assessment", "old": None, "new": representative},
        ]
    )

    # Preserve genuine PDF-internal typos separately from JSON extraction errors.
    verified_source_issues = {
        6: {
            "category": "equipment_label_inconsistency",
            "field": "corrosion_results_project_name",
            "description": (
                "The same source PDF contains E-121A(TOP) on pages 45-47 and "
                "E-121A(BTM/BOTTOM) on pages 51-53. Both records use the IRIS "
                "inspection method. Only the corrosion-results Project Name on "
                "page 53 says E-121A(BOM)."
            ),
            "resolution": (
                "Normalize BOM to BTM (BOTTOM) as the inspection scope of E-121A, "
                "not as a different inspection method. Preserve BOM only as a "
                "source-PDF typo; keep the master total tube count unchanged and "
                "manage TOP/BTM as separate inspection-history scopes."
            ),
        },
        35: {
            "category": "corrosion_depth_range_header_inconsistency",
            "field": "corrosion_depth_range_mm",
            "description": "PDF header says 0.18-0.36 mm, while detail rows range from 0.27 to 0.39 mm",
            "resolution": "Use detail-row values for calculations; preserve the PDF header as source text",
        },
        36: {
            "category": "corrosion_depth_range_header_inconsistency",
            "field": "corrosion_depth_range_mm",
            "description": "PDF header says 0.18-0.36 mm, while detail rows range from 0.14 to 0.17 mm",
            "resolution": "Use detail-row values for calculations; preserve the PDF header as source text",
        },
    }
    for sequence, issue in verified_source_issues.items():
        issue = {
            **issue,
            "source_pdf": PDF_FILE.name,
            "report_page": CORRECTIONS[sequence]["report_page"],
            "detail_page": CORRECTIONS[sequence]["detail_page"],
        }
        append_unique(
            reports[sequence]["validation"]["source_pdf_inconsistencies"], issue
        )

    # Dataset cardinality and corrected-value guards.
    report_count = len(payload["inspection_reports"])
    row_count = sum(
        len(obj.get("tube_results_table", {}).get("records") or [])
        for obj in payload["inspection_reports"]
    )
    if report_count != 36 or row_count != 455:
        raise AssertionError(f"Unexpected 2022 VCM1 cardinality: {report_count}/{row_count}")
    raw_text = json.dumps(payload, ensure_ascii=False)
    if '"category": "invalid_detail_spec_value"' in raw_text:
        raise AssertionError("Provisional invalid-detail classification remains")

    TARGET_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    after_hash = sha256(TARGET_FILE)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_pdf": str(PDF_FILE),
        "target_json": str(TARGET_FILE),
        "backup_directory": str(backup_dir),
        "sha256_before": before_hash,
        "sha256_after": after_hash,
        "corrected_report_count": len(CORRECTIONS),
        "field_change_count": len(changes),
        "reports": report_count,
        "tube_result_rows": row_count,
        "policy": {
            "inspection_snapshot": "use visually verified PDF specifications",
            "master_data": "do not update",
            "legacy_9000_and_2_34": "retain in correction audit only, not operational fields",
        },
        "changes": changes,
    }
    manifest_path = output_dir / "2022VCM1_PDF_SPEC_CORRECTIONS_MANIFEST_20260825.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "target": str(TARGET_FILE),
                "manifest": str(manifest_path),
                "backup": str(backup_dir),
                "corrected_reports": len(CORRECTIONS),
                "field_changes": len(changes),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
