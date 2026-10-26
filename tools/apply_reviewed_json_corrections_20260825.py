from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT = Path(r"C:\access\heat\iris2")
DATA_DIR = PROJECT / "data"
OUTPUT_ROOT = PROJECT / "outputs" / "json_review_corrections_20260825"
EXPECTED_FILES = 11
EXPECTED_REPORTS = 435
EXPECTED_ROWS = 6084


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_unique(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    signature = (item.get("category"), item.get("field"), item.get("description"))
    for current in items:
        current_signature = (
            current.get("category"),
            current.get("field"),
            current.get("description"),
        )
        if current_signature == signature:
            return
    items.append(item)


def report_for(payload: dict[str, Any], equipment_id: str) -> dict[str, Any]:
    matches = [
        obj
        for obj in payload["inspection_reports"]
        if obj["report"].get("equipment_id") == equipment_id
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {equipment_id} report, found {len(matches)}")
    return matches[0]


def validation_lists(obj: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validation = obj.setdefault("validation", {})
    corrections = validation.setdefault("normalization_corrections", [])
    inconsistencies = validation.setdefault("source_pdf_inconsistencies", [])
    return corrections, inconsistencies


def main() -> None:
    paths = sorted(DATA_DIR.glob("*IRIS2_all_tube_results.json"))
    if len(paths) != EXPECTED_FILES:
        raise AssertionError(f"Expected {EXPECTED_FILES} JSON files, found {len(paths)}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = PROJECT / "backups" / f"json_before_review_corrections_{timestamp}"
    output_dir = OUTPUT_ROOT / timestamp
    backup_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=False)

    payloads: dict[str, dict[str, Any]] = {}
    manifest_files: list[dict[str, Any]] = []
    for path in paths:
        backup_path = backup_dir / path.name
        shutil.copy2(path, backup_path)
        payloads[path.name] = json.loads(path.read_text(encoding="utf-8"))
        manifest_files.append(
            {
                "file": path.name,
                "backup": str(backup_path),
                "sha256_before": sha256(path),
            }
        )

    changes: list[dict[str, Any]] = []

    # 1) PDF detail table Q'ty and the extracted row count were verified to match.
    # Fill only the canonical count when the prior JSON count was missing.
    null_count_fills = 0
    for file_name, payload in payloads.items():
        for obj in payload["inspection_reports"]:
            report = obj["report"]
            summary = report.setdefault("inspection_summary", {})
            records = obj.get("tube_results_table", {}).get("records") or []
            if summary.get("inspected_tube_count") is not None:
                continue
            if not records:
                raise AssertionError(
                    f"Cannot fill an empty detail table: {file_name} / {report.get('equipment_id')}"
                )
            count = len(records)
            summary["inspected_tube_count"] = count
            validation = obj.setdefault("validation", {})
            validation["reported_inspected_tube_count"] = count
            validation["extracted_tube_result_count"] = count
            validation["reported_vs_extracted_count_match"] = True
            corrections, _ = validation_lists(obj)
            append_unique(
                corrections,
                {
                    "category": "verified_detail_count_fill",
                    "field": "report.inspection_summary.inspected_tube_count",
                    "legacy_value": None,
                    "normalized_value": count,
                    "basis": "PDF Tube ID Q'ty, PDF footer Total, and JSON detail rows agree",
                    "db_import_action": "use_normalized_value",
                },
            )
            null_count_fills += 1
            changes.append(
                {
                    "file": file_name,
                    "equipment_id": report.get("equipment_id"),
                    "report_sequence": report.get("report_sequence"),
                    "change": "fill_missing_inspected_tube_count",
                    "old": None,
                    "new": count,
                }
            )
    if null_count_fills != 54:
        raise AssertionError(f"Expected 54 missing count fills, found {null_count_fills}")

    # 2) 2020 VCM2 E-11: the report, Q'ty, footer Total, and ten rows all say 10.
    e11 = report_for(payloads["2020VCM2_IRIS2_all_tube_results.json"], "E-11")
    old_e11_reference = e11.get("summary_reference")
    e11["report"]["inspection_summary"]["inspected_tube_count"] = 10
    e11["summary_reference"] = None  # It was incorrectly linked to the E-112 summary row.
    e11_validation = e11["validation"]
    e11_validation["reported_inspected_tube_count"] = 10
    e11_validation["extracted_tube_result_count"] = 10
    e11_validation["reported_vs_extracted_count_match"] = True
    corrections, _ = validation_lists(e11)
    append_unique(
        corrections,
        {
            "category": "incorrect_summary_mapping_correction",
            "field": "report.inspection_summary.inspected_tube_count",
            "legacy_value": 5,
            "normalized_value": 10,
            "basis": "PDF report sample count, Tube ID Q'ty, footer Total, and detail rows agree",
            "excluded_summary_reference": old_e11_reference,
            "db_import_action": "use_normalized_value",
        },
    )
    changes.append(
        {
            "file": "2020VCM2_IRIS2_all_tube_results.json",
            "equipment_id": "E-11",
            "change": "correct_inspected_tube_count_and_remove_mislinked_summary_reference",
            "old": 5,
            "new": 10,
        }
    )

    # 3) 2022 VCM2 E-301B: E-301's integrated-summary row had been attached to E-301B.
    e301b = report_for(payloads["2022VCM2_IRIS2_all_tube_results.json"], "E-301B")
    e301b_summary = e301b["report"]["inspection_summary"]
    old_e301b_summary = dict(e301b_summary)
    old_e301b_reference = e301b.get("summary_reference")
    e301b_summary.update(
        {
            "total_tube_count": 121,
            "inspected_tube_count": 10,
            "minimum_remaining_thickness_mm": 1.87,
            "maximum_wall_loss_percent": 11.37,
            "average_wall_loss_percent": 10.09,
        }
    )
    e301b["summary_reference"] = None
    corrections, inconsistencies = validation_lists(e301b)
    e301b["validation"]["source_pdf_inconsistencies"] = [
        item
        for item in inconsistencies
        if not (
            item.get("category") == "summary_detail_mismatch"
            and item.get("field")
            in {
                "minimum_remaining_thickness_mm",
                "maximum_wall_loss_percent",
                "average_wall_loss_percent",
            }
        )
    ]
    append_unique(
        corrections,
        {
            "category": "incorrect_summary_mapping_correction",
            "field": "report.inspection_summary",
            "legacy_value": old_e301b_summary,
            "normalized_value": dict(e301b_summary),
            "basis": "E-301B individual report, recommendations, tube map, and detail rows",
            "excluded_summary_reference": old_e301b_reference,
            "db_import_action": "use_normalized_value",
        },
    )
    changes.append(
        {
            "file": "2022VCM2_IRIS2_all_tube_results.json",
            "equipment_id": "E-301B",
            "change": "replace_mislinked_E301_summary_with_verified_E301B_values",
            "old": old_e301b_summary,
            "new": dict(e301b_summary),
        }
    )

    # 4) 2025 VCM2 E-511B: NDD's blank thickness had been normalized to zero and
    # then incorrectly reused as the report minimum. The real minimum row is 2.65 mm.
    e511b = report_for(payloads["2025VCM2_IRIS2_all_tube_results.json"], "E-511B")
    e511b["report"]["inspection_summary"]["minimum_remaining_thickness_mm"] = 2.65
    if isinstance(e511b.get("summary_reference"), dict):
        e511b["summary_reference"]["minimum_remaining_thickness_mm"] = 2.65
    corrections, inconsistencies = validation_lists(e511b)
    e511b["validation"]["source_pdf_inconsistencies"] = [
        item
        for item in inconsistencies
        if not (
            item.get("category") == "summary_detail_mismatch"
            and item.get("field") == "minimum_remaining_thickness_mm"
        )
    ]
    append_unique(
        corrections,
        {
            "category": "ndd_blank_not_numeric_zero",
            "field": "report.inspection_summary.minimum_remaining_thickness_mm",
            "legacy_value": 0.0,
            "normalized_value": 2.65,
            "basis": "NDD thickness is blank; minimum of numeric detail rows is 2.65 mm",
            "db_import_action": "use_normalized_value",
        },
    )
    changes.append(
        {
            "file": "2025VCM2_IRIS2_all_tube_results.json",
            "equipment_id": "E-511B",
            "change": "correct_minimum_remaining_thickness",
            "old": 0.0,
            "new": 2.65,
        }
    )

    # 5) Obvious detail specification errors are invalidated in all fields used by
    # the DB importer. The rejected PDF values remain in the correction audit.
    invalid_thickness = 0
    invalid_od = 0
    payload_2022_vcm1 = payloads["2022VCM1_IRIS2_all_tube_results.json"]
    for obj in payload_2022_vcm1["inspection_reports"]:
        report = obj["report"]
        tube_spec = report.get("tube_spec") or {}
        details = report.get("iris_report_details") or report.get("iris_9000_report_details") or {}
        basic = details.get("basic_information") or {}
        conditions = details.get("measurement_conditions") or {}
        corrections, inconsistencies = validation_lists(obj)

        if tube_spec.get("design_thickness_mm") == 9000.0:
            invalid_thickness += 1
            tube_spec["design_thickness_mm"] = None
            if basic.get("nominal_thickness_mm") == 9000.0:
                basic["nominal_thickness_mm"] = None
            append_unique(
                corrections,
                {
                    "category": "invalid_detail_spec_value",
                    "field": "tube_nominal_thickness_mm",
                    "legacy_value": 9000.0,
                    "normalized_value": None,
                    "reason": "9000.0 mm is an impossible tube nominal thickness and is a detail extraction error",
                    "db_import_action": "exclude_value",
                },
            )
            append_unique(
                inconsistencies,
                {
                    "category": "invalid_detail_spec_value",
                    "field": "tube_nominal_thickness_mm",
                    "source_value": 9000.0,
                    "operational_value": None,
                    "resolution": "DB 반영 제외; 승인 없는 대체 제원 적용 안 함",
                },
            )
            obj["validation"]["row_calculation_mismatch_count"] = 0
            obj["validation"]["row_calculation_mismatches"] = []
            obj["validation"]["row_calculation_status"] = "NOT_EVALUATED_INVALID_DETAIL_SPEC"
            changes.append(
                {
                    "file": "2022VCM1_IRIS2_all_tube_results.json",
                    "equipment_id": report.get("equipment_id"),
                    "report_sequence": report.get("report_sequence"),
                    "change": "invalidate_impossible_nominal_thickness",
                    "old": 9000.0,
                    "new": None,
                }
            )

        if tube_spec.get("outer_diameter_mm") == 2.34:
            invalid_od += 1
            tube_spec["outer_diameter_mm"] = None
            if conditions.get("out_diameter_mm") == 2.34:
                conditions["out_diameter_mm"] = None
            append_unique(
                corrections,
                {
                    "category": "invalid_detail_spec_value",
                    "field": "tube_outer_diameter_mm",
                    "legacy_value": 2.34,
                    "normalized_value": None,
                    "reason": "2.34 mm is an impossible tube outer diameter and was mapped from a thickness value",
                    "db_import_action": "exclude_value",
                },
            )
            append_unique(
                inconsistencies,
                {
                    "category": "invalid_detail_spec_value",
                    "field": "tube_outer_diameter_mm",
                    "source_value": 2.34,
                    "operational_value": None,
                    "resolution": "DB 반영 제외; 승인 없는 대체 제원 적용 안 함",
                },
            )
            changes.append(
                {
                    "file": "2022VCM1_IRIS2_all_tube_results.json",
                    "equipment_id": report.get("equipment_id"),
                    "report_sequence": report.get("report_sequence"),
                    "change": "invalidate_impossible_outer_diameter",
                    "old": 2.34,
                    "new": None,
                }
            )

    if invalid_thickness != 10:
        raise AssertionError(f"Expected 10 invalid thickness values, found {invalid_thickness}")
    if invalid_od != 1:
        raise AssertionError(f"Expected 1 invalid OD value, found {invalid_od}")

    # 6) Preserve the verified PDF-internal count typos as explicit quality issues.
    count_source_issues = [
        (
            "2021VCM1_IRIS2_all_tube_results.json",
            "E-123",
            {
                "category": "count_label_inconsistency",
                "field": "tube_results_footer_total",
                "description": "PDF footer Total is 5, while report count, Tube ID Q'ty, and four detail rows are 4",
                "operational_inspected_tube_count": 4,
                "resolution": "원문 오타는 보존하고 검증된 상세행 수 4를 사용",
            },
        ),
        (
            "2021VCM2_IRIS2_all_tube_results.json",
            "E-104A",
            {
                "category": "count_label_inconsistency",
                "field": "tube_id_qty",
                "description": "PDF Tube ID Q'ty is 5, while report count, footer Total, and ten detail rows are 10",
                "operational_inspected_tube_count": 10,
                "resolution": "원문 오타는 보존하고 검증된 상세행 수 10을 사용",
            },
        ),
        (
            "2023VCM2_IRIS2_all_tube_results.json",
            "E-106",
            {
                "category": "count_label_inconsistency",
                "field": "tube_id_qty",
                "description": "PDF Tube ID Q'ty is 20, while report count, footer Total, and 25 detail rows are 25",
                "operational_inspected_tube_count": 25,
                "resolution": "원문 오타는 보존하고 검증된 상세행 수 25를 사용",
            },
        ),
        (
            "2023VCM2_IRIS2_all_tube_results.json",
            "E-201B",
            {
                "category": "reported_detail_count_inconsistency",
                "field": "inspected_tube_count",
                "description": "PDF report says 20 inspected, while Tube ID Q'ty, footer Total, and detail rows are 10",
                "reported_inspected_tube_count": 20,
                "actual_detail_row_count": 10,
                "resolution": "보고수량 20과 실제 상세행 10을 별도 보존",
            },
        ),
    ]
    for file_name, equipment_id, issue in count_source_issues:
        obj = report_for(payloads[file_name], equipment_id)
        _, inconsistencies = validation_lists(obj)
        append_unique(inconsistencies, issue)
        changes.append(
            {
                "file": file_name,
                "equipment_id": equipment_id,
                "change": "record_verified_pdf_internal_count_inconsistency",
                "field": issue["field"],
            }
        )

    report_count = sum(len(payload["inspection_reports"]) for payload in payloads.values())
    row_count = sum(
        len(obj.get("tube_results_table", {}).get("records") or [])
        for payload in payloads.values()
        for obj in payload["inspection_reports"]
    )
    if report_count != EXPECTED_REPORTS or row_count != EXPECTED_ROWS:
        raise AssertionError(
            f"Dataset cardinality changed unexpectedly: reports={report_count}, rows={row_count}"
        )

    for path in paths:
        payload = payloads[path.name]
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    for entry, path in zip(manifest_files, paths):
        entry["sha256_after"] = sha256(path)

    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "policy": {
            "source_pdf_internal_inconsistencies": "preserve_and_flag",
            "verified_json_mapping_errors": "correct",
            "invalid_detail_spec_values": "set_operational_fields_to_null_and_exclude_from_db",
            "master_data": "do_not_overwrite",
        },
        "counts": {
            "json_files": len(paths),
            "reports": report_count,
            "tube_result_rows": row_count,
            "missing_inspected_counts_filled": null_count_fills,
            "invalid_thickness_values_excluded": invalid_thickness,
            "invalid_outer_diameter_values_excluded": invalid_od,
            "change_log_entries": len(changes),
        },
        "backup_directory": str(backup_dir),
        "files": manifest_files,
        "changes": changes,
    }
    manifest_path = output_dir / "IRIS2_JSON_REVIEW_CORRECTIONS_MANIFEST_20260825.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": str(manifest_path), **manifest["counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
