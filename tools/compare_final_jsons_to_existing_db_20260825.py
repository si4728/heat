from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))

from iris2.iris_json_mapping import ALLOWED_PERSONNEL_ROLES
from iris2.iris_json_validator import report_parts
from iris2.load_inspection_history_existing_only import collect_files, precheck


ROOT = APP_DIR
DB = Path(os.environ.get("IRIS2_COMPARE_DB_PATH", ROOT / "data" / "heat_exchanger_db3.db"))
DATA = ROOT / "data"
OUTPUT_ROOT = ROOT / "outputs" / "final_json_vs_existing_db_20260825"
FILE_RE = re.compile(r"^(20\d{2})(PE|VCM1|VCM2)_IRIS2_all_tube_results\.json$", re.I)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return None if value in {"", "-"} else value
    return value


def number(value: Any) -> float | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, str):
        digits = re.sub(r"[^0-9-]", "", value)
        return int(digits) if digits not in {"", "-"} else None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def text_key(value: Any) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return re.sub(r"\s+", "", str(value)).upper()


def equal(left: Any, right: Any, numeric: bool = False) -> bool:
    left, right = clean(left), clean(right)
    if left is None and right is None:
        return True
    if numeric:
        a, b = number(left), number(right)
        return a is not None and b is not None and abs(a - b) <= 0.01
    return text_key(left) == text_key(right)


def difference_type(db_value: Any, json_value: Any) -> str:
    if clean(db_value) is None and clean(json_value) is not None:
        return "JSON_ADDED"
    if clean(db_value) is not None and clean(json_value) is None:
        return "JSON_CLEARED"
    return "VALUE_CHANGED"


def normalized_front(reference: dict[str, Any]) -> dict[str, Any]:
    spec = reference.get("tube_spec_reference") or reference.get("tube_spec") or reference
    return {
        "summary_material": spec.get("material"),
        "summary_outer_diameter_mm": spec.get("outer_diameter_mm"),
        "summary_design_thickness_mm": spec.get("design_thickness_mm"),
        "summary_length_mm": spec.get("length_mm"),
        "summary_total_tubes": next((reference.get(key) for key in (
            "total_tube_count", "total_tubes_summary", "total_tubes_summary_raw"
        ) if reference.get(key) is not None), None),
        "summary_inspected_tubes": next((reference.get(key) for key in (
            "inspected_tube_count", "inspected_tubes_summary"
        ) if reference.get(key) is not None), None),
        "summary_page": reference.get("source_page", reference.get("summary_page")),
    }


def json_report_values(parts: dict[str, Any]) -> dict[str, Any]:
    report = parts["report"]
    details = parts["details"]
    basic = parts["basic"]
    summary = parts["summary"]
    spec = parts["tube_spec"]
    conditions = parts["conditions"]
    equipment = details.get("inspection_equipment") or {}
    front = normalized_front(parts["summary_reference"])
    length_m = number(conditions.get("tube_length_m"))
    values = {
        "report_number": basic.get("report_number"),
        "inspection_method": report.get("inspection_method") or "IRIS",
        "total_tube_count_reported": summary.get("total_tube_count"),
        "inspected_tube_count_reported": summary.get("inspected_tube_count"),
        "extracted_tube_result_count": len(parts["records"]),
        "reported_minimum_thickness_mm": summary.get("minimum_remaining_thickness_mm"),
        "reported_maximum_wall_loss_percent": summary.get("maximum_wall_loss_percent"),
        "reported_average_wall_loss_percent": summary.get("average_wall_loss_percent"),
        "report_material": spec.get("material", basic.get("material")),
        "report_outer_diameter_mm": spec.get("outer_diameter_mm", conditions.get("out_diameter_mm")),
        "report_nominal_thickness_mm": spec.get("design_thickness_mm", basic.get("nominal_thickness_mm")),
        "report_tube_length_mm": spec.get("length_mm", length_m * 1000 if length_m is not None else None),
        "customer": basic.get("customer"),
        "project_name": basic.get("project_name"),
        "equipment_name": basic.get("equipment_name"),
        "equipment_number": basic.get("equipment_number"),
        "equipment_maker": equipment.get("equipment_maker"),
        "equipment_model": equipment.get("equipment_model"),
        "equipment_serial_number": equipment.get("equipment_serial_number"),
        "search_unit_maker": equipment.get("search_unit_maker"),
        "search_unit_model": equipment.get("search_unit_model"),
        "frequency_mhz": equipment.get("frequency_mhz"),
        "out_diameter_mm": conditions.get("out_diameter_mm"),
        "tube_length_m": conditions.get("tube_length_m"),
        "material_velocity_meter_per_sec": conditions.get("material_velocity_meter_per_sec"),
        "scan_velocity_meter_per_min": conditions.get("scan_velocity_meter_per_min"),
        "water_pressure_kg_per_cm2": conditions.get("water_pressure_kg_per_cm2"),
        "water_temperature_celsius": conditions.get("water_temperature_celsius"),
    }
    values.update(front)
    return values


NUMERIC_REPORT_FIELDS = {
    "total_tube_count_reported", "inspected_tube_count_reported", "extracted_tube_result_count",
    "reported_minimum_thickness_mm", "reported_maximum_wall_loss_percent",
    "reported_average_wall_loss_percent", "report_outer_diameter_mm",
    "report_nominal_thickness_mm", "report_tube_length_mm", "summary_outer_diameter_mm",
    "summary_design_thickness_mm", "summary_length_mm", "summary_total_tubes",
    "summary_inspected_tubes", "summary_page", "frequency_mhz", "out_diameter_mm",
    "tube_length_m", "material_velocity_meter_per_sec", "scan_velocity_meter_per_min",
    "water_pressure_kg_per_cm2", "water_temperature_celsius",
}


TUBE_FIELDS = {
    "source_row": ("row", True),
    "source_column": ("column", True),
    "minimum_wall_thickness_mm": ("minimum_wall_thickness_mm", True),
    "location_mm": ("location_mm", True),
    "corrosion_type": ("section_corrosion_depth", False),
    "wall_loss_depth_mm": ("wall_loss_depth_mm", True),
    "wall_loss_percent": ("wall_loss_percent", True),
    "source_page": ("source_page", True),
    "raw_side": ("raw_side", False),
    "analysis_v": ("analysis_v", True),
    "source_location_raw": ("location_source_value", True),
    "location_source_unit": ("location_source_unit", False),
    "remark": ("remark", False),
    "design_wall_thickness_mm": ("design_wall_thickness_mm", True),
    "defect_code": ("defect_code", False),
    "reported_depth_percent": ("reported_depth_percent", True),
}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    headers = list(rows[0]) if rows else ["no_rows"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        if rows:
            writer.writerows(rows)


def main() -> None:
    files = collect_files(DATA)
    if len(files) != 11:
        raise AssertionError(f"Expected 11 final JSON files, found {len(files)}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = OUTPUT_ROOT / stamp
    output.mkdir(parents=True)

    connection = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    inspection_rows = connection.execute(
        """
        SELECT i.*, c.campaign_year, u.unit_code, d.source_file AS db_source_file,
               d.sha256 AS db_document_sha256,
               s.*, x.*
          FROM iris_inspection i
          JOIN inspection_campaign c ON c.campaign_id=i.campaign_id
          JOIN process_unit u ON u.unit_id=c.unit_id
          JOIN source_document d ON d.source_document_id=i.source_document_id
          LEFT JOIN iris_inspection_spec_snapshot s ON s.iris_inspection_id=i.iris_inspection_id
          LEFT JOIN iris_setup_snapshot x ON x.iris_inspection_id=i.iris_inspection_id
        """
    ).fetchall()
    inspections = {
        (int(row["campaign_year"]), str(row["unit_code"]).upper(), int(row["report_sequence"])): dict(row)
        for row in inspection_rows
    }

    report_differences: list[dict[str, Any]] = []
    tube_differences: list[dict[str, Any]] = []
    document_differences: list[dict[str, Any]] = []
    report_status: list[dict[str, Any]] = []
    file_status: list[dict[str, Any]] = []
    recommendation_difference_count = 0
    personnel_difference_count = 0
    representative_difference_count = 0
    matched_reports = 0
    json_tubes = 0
    db_tubes = 0

    for file_path in files:
        matched = FILE_RE.match(file_path.name)
        assert matched
        year, unit = int(matched.group(1)), matched.group(2).upper()
        payload = json.loads(file_path.read_text(encoding="utf-8"))
        file_reports = payload["inspection_reports"]
        db_source_rows = [row for key, row in inspections.items() if key[0] == year and key[1] == unit]
        db_sha_values = sorted({row["db_document_sha256"] for row in db_source_rows})
        json_sha = digest(file_path)
        db_sha = db_sha_values[0] if len(db_sha_values) == 1 else None
        if json_sha != db_sha:
            document_differences.append({
                "json_file": file_path.name,
                "year": year,
                "unit": unit,
                "db_source_file": db_source_rows[0]["db_source_file"] if db_source_rows else None,
                "db_sha256": db_sha,
                "json_sha256": json_sha,
                "difference_type": "DOCUMENT_CHANGED" if db_sha else "DB_DOCUMENT_MISSING",
            })

        file_report_diff_start = len(report_differences)
        file_tube_diff_start = len(tube_differences)
        file_json_tubes = 0
        file_db_tubes = 0
        for obj in file_reports:
            parts = report_parts(obj)
            report = parts["report"]
            sequence = int(report["report_sequence"])
            equipment = str(parts["equipment_raw"])
            key = (year, unit, sequence)
            db = inspections.get(key)
            if db is None:
                report_differences.append({
                    "json_file": file_path.name, "year": year, "unit": unit,
                    "report_sequence": sequence, "equipment_id": equipment,
                    "field_group": "inspection", "field_name": "report",
                    "difference_type": "REPORT_ADDED", "db_value": None, "json_value": "present",
                })
                continue
            matched_reports += 1
            values = json_report_values(parts)
            report_diff_count = 0
            for field, json_value in values.items():
                db_value = db.get(field)
                if equal(db_value, json_value, field in NUMERIC_REPORT_FIELDS):
                    continue
                group = (
                    "inspection_summary" if field in {
                        "total_tube_count_reported", "inspected_tube_count_reported",
                        "extracted_tube_result_count", "reported_minimum_thickness_mm",
                        "reported_maximum_wall_loss_percent", "reported_average_wall_loss_percent"
                    } else "report_spec" if field.startswith("report_")
                    else "front_summary_reference" if field.startswith("summary_")
                    else "setup_snapshot"
                )
                report_differences.append({
                    "json_file": file_path.name, "year": year, "unit": unit,
                    "report_sequence": sequence, "equipment_id": equipment,
                    "field_group": group, "field_name": field,
                    "difference_type": difference_type(db_value, json_value),
                    "db_value": db_value, "json_value": json_value,
                })
                report_diff_count += 1

            inspection_id = int(db["iris_inspection_id"])
            db_recommendations = [row[0] for row in connection.execute(
                "SELECT recommendation_text FROM iris_recommendation WHERE iris_inspection_id=? ORDER BY sequence_no",
                (inspection_id,),
            )]
            json_recommendations = [str(x) for x in (parts["details"].get("recommendations") or [])]
            if db_recommendations != json_recommendations:
                recommendation_difference_count += 1
                report_diff_count += 1

            db_personnel = {
                str(row["role"]).lower(): (row["person_name"], row["organization"])
                for row in connection.execute(
                    "SELECT role,person_name,organization FROM inspection_personnel WHERE iris_inspection_id=?",
                    (inspection_id,),
                )
                if clean(row["person_name"]) is not None
                or clean(row["organization"]) is not None
            }
            personnel = parts["details"].get("signatures_and_personnel") or {}
            json_personnel = {}
            for role in ALLOWED_PERSONNEL_ROLES:
                value = personnel.get(role)
                if value in (None, "", {}):
                    continue
                if isinstance(value, dict):
                    json_personnel[role.lower()] = (
                        clean(value.get("name") or value.get("person_name")),
                        clean(value.get("organization") or value.get("company")),
                    )
                else:
                    json_personnel[role.lower()] = (clean(value), None)
            normalized_db_personnel = {key: (clean(v[0]), clean(v[1])) for key, v in db_personnel.items()}
            if normalized_db_personnel != json_personnel:
                personnel_difference_count += 1
                report_diff_count += 1

            representative = parts["details"].get("representative_defect_assessment") or {}
            db_rep = connection.execute(
                "SELECT target_tube,minimum_thickness_mm,wall_loss_percent,defect_type FROM iris_representative_assessment WHERE iris_inspection_id=?",
                (inspection_id,),
            ).fetchone()
            json_rep = {
                "target_tube": representative.get("target_tube"),
                "minimum_thickness_mm": representative.get("minimum_thickness_mm"),
                "wall_loss_percent": representative.get("wall_loss_percent"),
                "defect_type": representative.get("defect_type"),
            }
            if db_rep and any(
                not equal(db_rep[field], json_rep[field], field in {"minimum_thickness_mm", "wall_loss_percent"})
                for field in json_rep
            ):
                representative_difference_count += 1
                report_diff_count += 1

            db_records = {
                str(row["source_tube_id"]): dict(row)
                for row in connection.execute(
                    "SELECT * FROM iris_tube_result WHERE iris_inspection_id=?",
                    (inspection_id,),
                )
            }
            json_records = {str(row.get("tube_id") or "").strip(): row for row in parts["records"]}
            file_json_tubes += len(json_records)
            file_db_tubes += len(db_records)
            tube_diff_count = 0
            for tube_id in sorted(set(db_records) | set(json_records)):
                db_record, json_record = db_records.get(tube_id), json_records.get(tube_id)
                if db_record is None:
                    tube_differences.append({
                        "json_file": file_path.name, "year": year, "unit": unit,
                        "report_sequence": sequence, "equipment_id": equipment,
                        "tube_id": tube_id, "field_name": "row",
                        "difference_type": "TUBE_ROW_ADDED", "db_value": None, "json_value": "present",
                    })
                    tube_diff_count += 1
                    continue
                if json_record is None:
                    tube_differences.append({
                        "json_file": file_path.name, "year": year, "unit": unit,
                        "report_sequence": sequence, "equipment_id": equipment,
                        "tube_id": tube_id, "field_name": "row",
                        "difference_type": "TUBE_ROW_REMOVED", "db_value": "present", "json_value": None,
                    })
                    tube_diff_count += 1
                    continue
                for db_field, (json_field, numeric_field) in TUBE_FIELDS.items():
                    db_value = db_record.get(db_field)
                    json_value = json_record.get(json_field)
                    if equal(db_value, json_value, numeric_field):
                        continue
                    tube_differences.append({
                        "json_file": file_path.name, "year": year, "unit": unit,
                        "report_sequence": sequence, "equipment_id": equipment,
                        "tube_id": tube_id, "field_name": db_field,
                        "difference_type": difference_type(db_value, json_value),
                        "db_value": db_value, "json_value": json_value,
                    })
                    tube_diff_count += 1
            report_status.append({
                "json_file": file_path.name, "year": year, "unit": unit,
                "report_sequence": sequence, "equipment_id": equipment,
                "report_value_difference_count": report_diff_count,
                "tube_value_difference_count": tube_diff_count,
                "json_tube_count": len(json_records), "db_tube_count": len(db_records),
            })
        json_tubes += file_json_tubes
        db_tubes += file_db_tubes
        file_status.append({
            "json_file": file_path.name, "year": year, "unit": unit,
            "report_count": len(file_reports),
            "json_tube_count": file_json_tubes,
            "db_tube_count": file_db_tubes,
            "report_field_difference_count": len(report_differences) - file_report_diff_start,
            "tube_difference_count": len(tube_differences) - file_tube_diff_start,
            "json_sha256": json_sha, "db_sha256": db_sha,
        })

    master_result = precheck(DB, files, plant_code="P1")
    report_type_counts = Counter(row["difference_type"] for row in report_differences)
    report_field_counts = Counter(row["field_name"] for row in report_differences)
    tube_type_counts = Counter(row["difference_type"] for row in tube_differences)
    tube_field_counts = Counter(row["field_name"] for row in tube_differences)
    changed_reports = sum(
        1 for row in report_status
        if row["report_value_difference_count"] or row["tube_value_difference_count"]
    )
    unchanged_reports = len(report_status) - changed_reports
    summary = {
        "mode": "READ_ONLY_COMPARISON",
        "db_path": str(DB),
        "json_file_count": len(files),
        "json_report_count": sum(row["report_count"] for row in file_status),
        "db_matched_report_count": matched_reports,
        "changed_report_count": changed_reports,
        "unchanged_report_count": unchanged_reports,
        "json_tube_result_count": json_tubes,
        "db_tube_result_count_for_matched_reports": db_tubes,
        "tube_result_count_delta": json_tubes - db_tubes,
        "document_hash_difference_count": len(document_differences),
        "inspection_report_field_difference_count": len(report_differences),
        "inspection_report_difference_type_counts": dict(report_type_counts),
        "inspection_report_difference_field_counts": dict(report_field_counts),
        "tube_difference_count": len(tube_differences),
        "tube_difference_type_counts": dict(tube_type_counts),
        "tube_difference_field_counts": dict(tube_field_counts),
        "recommendation_changed_report_count": recommendation_difference_count,
        "personnel_changed_report_count": personnel_difference_count,
        "representative_assessment_changed_report_count": representative_difference_count,
        "master_precheck": master_result["summary"],
        "database_modified": False,
    }

    write_csv(output / "file_comparison.csv", file_status)
    write_csv(output / "inspection_value_differences.csv", report_differences)
    write_csv(output / "tube_result_differences.csv", tube_differences)
    write_csv(output / "report_comparison_status.csv", report_status)
    write_csv(output / "document_hash_differences.csv", document_differences)
    write_csv(output / "master_json_value_mismatches.csv", master_result["mismatches"])
    write_csv(output / "json_validation_issues.csv", master_result["validation_issues"])
    (output / "comparison_summary.json").write_text(
        json.dumps({"summary": summary, "files": file_status}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 최종 11개 JSON과 기존 DB 비교 분석", "",
        "- 비교 모드: 읽기 전용(DB 미변경)",
        f"- JSON/검사 객체/상세행: {len(files)}개 / {summary['json_report_count']}건 / {json_tubes}행",
        f"- DB 검사 객체/상세행: {matched_reports}건 / {db_tubes}행",
        f"- 변경/동일 검사 객체: {changed_reports}건 / {unchanged_reports}건",
        f"- 상세행 증감: +{summary['tube_result_count_delta']}행",
        f"- 검사·제원·환경 필드 차이: {len(report_differences)}건",
        f"- 튜브 행/필드 차이: {len(tube_differences)}건",
        f"- 마스터 제원 차이: {master_result['summary']['mismatch_count']}건",
        f"- JSON 검증 오류/경고: {master_result['summary']['validation_error_count']}/{master_result['summary']['validation_warning_count']}",
        "", "## 파일별", "",
        "|파일|검사|JSON행|DB행|검사필드 차이|튜브 차이|", "|---|---:|---:|---:|---:|---:|",
    ]
    for row in file_status:
        lines.append(
            f"|{row['json_file']}|{row['report_count']}|{row['json_tube_count']}|{row['db_tube_count']}|"
            f"{row['report_field_difference_count']}|{row['tube_difference_count']}|"
        )
    lines.extend(["", "## 마스터 비교 차이 필드", ""])
    for field, count in master_result["summary"]["mismatch_field_counts"].items():
        lines.append(f"- {field}: {count}건")
    (output / "comparison_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.close()
    print(json.dumps({"output_dir": str(output), "summary": summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
