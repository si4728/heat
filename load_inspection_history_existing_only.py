from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

APP_DIR = Path(__file__).resolve().parent
if __package__ in {None, ""}:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.import_normalization import normalize_equipment_code


DEFAULT_DB = APP_DIR / "data" / "heat_exchanger_db3.db"
DEFAULT_OUTPUT_ROOT = APP_DIR / "outputs" / "v3_inspection_import"
FILE_PATTERN = re.compile(r"^(20\d{2})(PE|VCM1|VCM2)_IRIS2_all_tube_results\.json$", re.I)
EMPTY_TEXT = {"", "-", "N/A", "NA", "NONE", "NULL", "해당없음"}


def normalized_code(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").upper())


def clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().upper() in EMPTY_TEXT:
        return None
    return value


def numeric(value: Any) -> float | None:
    value = clean(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def comparable_text(value: Any) -> str | None:
    value = clean(value)
    if value is None:
        return None
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def first(*values: Any) -> Any:
    return next((value for value in values if clean(value) is not None), None)


def collect_files(input_dir: Path) -> list[Path]:
    files = [path for path in input_dir.iterdir() if path.is_file() and FILE_PATTERN.match(path.name)]
    return sorted(files, key=lambda path: path.name.upper())


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_before_inspection_history_{stamp}{db_path.suffix}"
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("검사이력 적재 전 백업 DB 무결성 검사 실패")
    finally:
        destination.close()
        source.close()
    return backup_path


def load_master(db_path: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT p.plant_code, u.unit_code, e.equipment_code, e.equipment_name, e.equipment_number,
                   h.heat_exchanger_id, s.exchanger_code, s.tube_material, s.tube_count,
                   s.tube_outer_diameter_mm, s.tube_nominal_thickness_mm,
                   s.tube_length_mm
              FROM equipment e
              JOIN process_unit u ON u.unit_id=e.unit_id
              JOIN plant p ON p.plant_id=u.plant_id
              JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
              LEFT JOIN heat_exchanger_spec_revision s
                ON s.heat_exchanger_id=h.heat_exchanger_id AND s.is_current=1
            """
        ).fetchall()
        master = {
            (
                normalized_code(row["plant_code"]),
                normalized_code(row["unit_code"]),
                normalized_code(row["exchanger_code"] or row["equipment_code"]),
            ): dict(row)
            for row in rows
        }
        by_exchanger_id = {int(row["heat_exchanger_id"]): dict(row) for row in rows}
        aliases = connection.execute("""
            SELECT p.plant_code, u.unit_code, a.heat_exchanger_id, a.alias_code
              FROM equipment_alias a
              JOIN heat_exchanger h ON h.heat_exchanger_id=a.heat_exchanger_id
              JOIN equipment e ON e.equipment_id=h.equipment_id
              JOIN process_unit u ON u.unit_id=e.unit_id
              JOIN plant p ON p.plant_id=u.plant_id
             WHERE a.is_approved=1
        """).fetchall()
        for alias in aliases:
            canonical_code = normalize_equipment_code(alias["alias_code"])[0]
            row = by_exchanger_id.get(int(alias["heat_exchanger_id"]))
            if row is not None:
                master.setdefault((
                    normalized_code(alias["plant_code"]),
                    normalized_code(alias["unit_code"]),
                    normalized_code(canonical_code),
                ), row)
        return master
    finally:
        connection.close()


def comparison_values(parts: dict[str, Any]) -> dict[str, Any]:
    basic = parts["basic"]
    tube_spec = parts["tube_spec"]
    summary_ref = parts["summary_reference"]
    summary_spec = (
        summary_ref.get("tube_spec_reference")
        or summary_ref.get("tube_spec")
        or summary_ref
    )
    summary = parts["summary"]
    conditions = parts["conditions"]
    tube_length_from_m = numeric(conditions.get("tube_length_m"))
    if tube_length_from_m is not None:
        tube_length_from_m *= 1000
    return {
        "equipment_name": clean(basic.get("equipment_name")),
        "tube_material": first(
            tube_spec.get("material"), summary_spec.get("material"),
            summary_ref.get("material"), basic.get("material")
        ),
        "tube_count": first(
            summary.get("total_tube_count"), summary_ref.get("total_tubes_summary"),
            summary_ref.get("total_tubes_summary_raw")
        ),
        "tube_outer_diameter_mm": first(
            tube_spec.get("outer_diameter_mm"), conditions.get("out_diameter_mm"),
            summary_spec.get("outer_diameter_mm"), summary_ref.get("outer_diameter_mm")
        ),
        "tube_nominal_thickness_mm": first(
            tube_spec.get("design_thickness_mm"), basic.get("nominal_thickness_mm"),
            summary_spec.get("design_thickness_mm"),
            summary_ref.get("design_thickness_mm")
        ),
        "tube_length_mm": first(
            tube_spec.get("length_mm"), summary_spec.get("length_mm"),
            summary_ref.get("length_mm"), tube_length_from_m
        ),
    }


NUMERIC_FIELDS = {
    "tube_count", "tube_outer_diameter_mm", "tube_nominal_thickness_mm", "tube_length_mm"
}


def values_equal(field: str, db_value: Any, json_value: Any) -> bool:
    if field in NUMERIC_FIELDS:
        left, right = numeric(db_value), numeric(json_value)
        return left is not None and right is not None and abs(left - right) <= 0.01
    return comparable_text(db_value) == comparable_text(json_value)


def precheck(db_path: Path, files: list[Path], *, plant_code: str = "P1") -> dict[str, Any]:
    from iris2.iris_json_validator import parse_date, report_parts, tube_map_values, validate_file

    plant_code = normalized_code(plant_code)
    master = load_master(db_path)
    missing: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    file_rows: list[dict[str, Any]] = []
    validation_issue_rows: list[dict[str, Any]] = []
    matched_count = 0
    report_count = 0
    tube_result_count = 0
    for file_order, path in enumerate(files, 1):
        match = FILE_PATTERN.match(path.name)
        if not match:
            continue
        year, unit = int(match.group(1)), normalized_code(match.group(2))
        result = validate_file(path)
        file_matched = 0
        file_missing = 0
        for issue in result.issues:
            validation_issue_rows.append({
                "file_order": file_order,
                "source_file": path.name,
                "plant_code": plant_code,
                "unit_code": unit,
                "severity": issue.severity,
                "issue_code": issue.code,
                "report_sequence": issue.report_sequence,
                "equipment_id": issue.equipment_id,
                "field_path": issue.field_path,
                "description": issue.description,
            })
        for report_index, obj in enumerate(result.payload.get("inspection_reports", [])):
            parts = report_parts(obj)
            code = normalized_code(parts["equipment_code"])
            key = (plant_code, unit, code)
            report_date = (
                parse_date(parts["basic"].get("report_date"))
                or parse_date(tube_map_values(parts["tube_map"])["map_date"])
            )
            common = {
                "file_order": file_order,
                "source_file": path.name,
                "campaign_year": year,
                "plant_code": plant_code,
                "unit_code": unit,
                "report_index": report_index,
                "report_sequence": parts["report"].get("report_sequence"),
                "equipment_raw": str(parts["equipment_raw"]),
                "equipment_code": code,
                "report_date": report_date.date().isoformat() if report_date else "",
            }
            db_row = master.get(key)
            if db_row is None:
                missing.append(common)
                file_missing += 1
                continue
            matched_count += 1
            file_matched += 1
            for field, json_value in comparison_values(parts).items():
                db_value = clean(db_row.get(field))
                json_value = clean(json_value)
                if db_value is None and json_value is None:
                    continue
                if db_value is None:
                    mismatch_type = "DB_MISSING_JSON_PRESENT"
                elif json_value is None:
                    continue
                elif not values_equal(field, db_value, json_value):
                    mismatch_type = "VALUE_MISMATCH"
                else:
                    continue
                mismatches.append({
                    **common,
                    "field_name": field,
                    "mismatch_type": mismatch_type,
                    "db_value": db_value,
                    "json_value": json_value,
                })
        file_rows.append({
            "file_order": file_order,
            "source_file": path.name,
            "campaign_year": year,
            "plant_code": plant_code,
            "unit_code": unit,
            "report_count": result.report_count,
            "matched_report_count": file_matched,
            "missing_report_count": file_missing,
            "tube_result_count": result.tube_result_count,
            "validation_error_count": result.error_count,
            "validation_warning_count": result.warning_count,
            "sha256": result.sha256,
        })
        report_count += result.report_count
        tube_result_count += result.tube_result_count
    return {
        "files": file_rows,
        "missing": missing,
        "mismatches": mismatches,
        "validation_issues": validation_issue_rows,
        "summary": {
            "file_count": len(files),
            "report_count": report_count,
            "matched_report_count": matched_count,
            "missing_report_count": len(missing),
            "unique_missing_equipment_count": len({
                (row["plant_code"], row["unit_code"], row["equipment_code"])
                for row in missing
            }),
            "tube_result_count_in_source": tube_result_count,
            "mismatch_count": len(mismatches),
            "mismatch_type_counts": dict(Counter(
                row["mismatch_type"] for row in mismatches
            )),
            "mismatch_field_counts": dict(Counter(
                row["field_name"] for row in mismatches
            )),
            "validation_error_count": sum(
                row["validation_error_count"] for row in file_rows
            ),
            "validation_warning_count": sum(
                row["validation_warning_count"] for row in file_rows
            ),
        },
    }


def write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_precheck_reports(output_dir: Path, result: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    missing_path = output_dir / "missing_exchangers.csv"
    mismatch_path = output_dir / "master_json_value_mismatches.csv"
    validation_path = output_dir / "json_validation_issues.csv"
    summary_json = output_dir / "inspection_import_summary.json"
    summary_md = output_dir / "inspection_import_summary.md"
    write_csv(missing_path, result["missing"], [
        "file_order", "source_file", "campaign_year", "plant_code", "unit_code", "report_index",
        "report_sequence", "equipment_raw", "equipment_code", "report_date",
    ])
    write_csv(mismatch_path, result["mismatches"], [
        "file_order", "source_file", "campaign_year", "plant_code", "unit_code", "report_index",
        "report_sequence", "equipment_raw", "equipment_code", "report_date",
        "field_name", "mismatch_type", "db_value", "json_value",
    ])
    write_csv(validation_path, result["validation_issues"], [
        "file_order", "source_file", "plant_code", "unit_code", "severity", "issue_code",
        "report_sequence", "equipment_id", "field_path", "description",
    ])
    summary_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = result["summary"]
    lines = [
        "# v3 검사 JSON 사전 대조 및 적재 요약", "",
        f"- JSON 파일: {summary['file_count']}개",
        f"- 검사 객체: {summary['report_count']}건",
        f"- Master 일치: {summary['matched_report_count']}건",
        f"- Master 미존재: {summary['missing_report_count']}건 "
        f"(고유 교환기 {summary['unique_missing_equipment_count']}개)",
        f"- DB·JSON 비교 차이: {summary['mismatch_count']}건",
        f"- JSON 검증 오류/경고: {summary['validation_error_count']}/"
        f"{summary['validation_warning_count']}", "",
        "## 파일 처리 순서", "",
        "|순서|파일|공장|공정|검사|일치|미존재|검증 경고|",
        "|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for row in result["files"]:
        lines.append(
            f"|{row['file_order']}|{row['source_file']}|{row['plant_code']}|"
            f"{row['unit_code']}|"
            f"{row['report_count']}|{row['matched_report_count']}|"
            f"{row['missing_report_count']}|{row['validation_warning_count']}|"
        )
    lines.extend(["", "## 비교 차이 유형", ""])
    for key, count in summary["mismatch_type_counts"].items():
        lines.append(f"- {key}: {count}건")
    lines.extend(["", "상세 내용은 CSV 파일을 확인한다.", ""])
    summary_md.write_text("\n".join(lines), encoding="utf-8")
    return {
        "missing_csv": str(missing_path),
        "mismatch_csv": str(mismatch_path),
        "validation_csv": str(validation_path),
        "summary_json": str(summary_json),
        "summary_md": str(summary_md),
    }


def add_comparison_quality_issues(db_path: Path, result: dict[str, Any]) -> int:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    inserted = 0
    try:
        documents = {
            row["source_file"]: row
            for row in connection.execute(
                "SELECT source_document_id, source_file, sha256 FROM source_document"
            )
        }
        for row in result["mismatches"]:
            if row["mismatch_type"] != "VALUE_MISMATCH":
                continue
            document = documents.get(row["source_file"])
            if document is None:
                continue
            inspection = connection.execute(
                """
                SELECT iris_inspection_id FROM iris_inspection
                 WHERE source_document_id=? AND report_sequence=?
                """,
                (document["source_document_id"], row["report_sequence"]),
            ).fetchone()
            fingerprint = hashlib.sha256(
                f"{document['sha256']}|{row['report_index']}|{row['field_name']}|"
                f"{row['mismatch_type']}".encode("utf-8")
            ).hexdigest()
            issue_code = {
                "VALUE_MISMATCH": "MASTER_JSON_VALUE_MISMATCH",
                "DB_MISSING_JSON_PRESENT": "MASTER_VALUE_MISSING_JSON_PRESENT",
            }[row["mismatch_type"]]
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO data_quality_issue (
                    source_document_id, iris_inspection_id, issue_fingerprint,
                    issue_code, severity, field_path, source_value_json,
                    calculated_value_json, description, status, created_at
                ) VALUES (?, ?, ?, ?, 'WARNING', ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    document["source_document_id"],
                    inspection["iris_inspection_id"] if inspection else None,
                    fingerprint, issue_code, f"master_vs_json.{row['field_name']}",
                    json.dumps(row["json_value"], ensure_ascii=False),
                    json.dumps(row["db_value"], ensure_ascii=False),
                    f"{row['plant_code']}+{row['unit_code']}+{row['equipment_code']}의 "
                    "Master와 검사 JSON 값 비교 필요",
                    datetime.now().isoformat(sep=" "),
                ),
            )
            inserted += cursor.rowcount
        connection.commit()
        return inserted
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_files(
    db_path: Path, files: list[Path], output_dir: Path, *, plant_code: str = "P1"
) -> list[dict[str, Any]]:
    os.environ["IRIS2_LEGACY_DB_PATH"] = str(db_path)
    os.environ["IRIS2_LEGACY_V2_DB_PATH"] = str(db_path)  # legacy importer compatibility
    from iris2.iris_v2_importer import import_file

    import_reports = output_dir / "per_file_reports"
    cumulative = output_dir / "cumulative_checking_report.md"
    outcomes = []
    for path in files:
        match = FILE_PATTERN.match(path.name)
        unit = normalized_code(match.group(2)) if match else None
        outcomes.append(import_file(
            path, plant_code=plant_code, unit_code=unit, dry_run=False,
            allow_errors=False, report_dir=import_reports,
            cumulative_path=cumulative,
        ))
    return outcomes


def verify_database(db_path: Path, expected_equipment_count: int) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in (
                "equipment", "heat_exchanger", "source_document", "inspection_campaign",
                "iris_inspection", "iris_inspection_spec_snapshot", "iris_setup_snapshot",
                "iris_tube_result", "data_quality_issue", "inspection_plan_v2",
                "tube_degradation_assessment",
            )
        }
        if counts["equipment"] != expected_equipment_count:
            raise RuntimeError(
                f"미존재 설비 자동 생성 감지: expected={expected_equipment_count}, "
                f"actual={counts['equipment']}"
            )
        return {
            "counts": counts,
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_issue_count": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "missing_report_date_count": connection.execute(
                "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NULL"
            ).fetchone()[0],
            "plan_weekend_violation_count": connection.execute(
                """
                SELECT COUNT(*) FROM inspection_plan_v2
                 WHERE strftime('%w', application_date) IN ('0','6')
                    OR strftime('%w', approval_date) IN ('0','6')
                """
            ).fetchone()[0],
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Master에 존재하는 공장+공정+교환기만 검사 JSON을 순차 적재"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--input-dir", type=Path, default=APP_DIR / "data")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--backup-dir", type=Path, default=APP_DIR / "backups")
    parser.add_argument("--plant-code", default="P1")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db_path = args.db.resolve()
    files = collect_files(args.input_dir.resolve())
    if not files:
        raise RuntimeError("검사 JSON 파일을 찾지 못했습니다.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_root.resolve() / stamp
    plant_code = normalized_code(args.plant_code)
    result = precheck(db_path, files, plant_code=plant_code)
    paths = write_precheck_reports(output_dir, result)
    response: dict[str, Any] = {
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "db_path": str(db_path),
        "plant_code": plant_code,
        "output_dir": str(output_dir),
        "precheck": result["summary"],
        "reports": paths,
    }
    if result["summary"]["validation_error_count"]:
        response["status"] = "BLOCKED_VALIDATION_ERRORS"
    elif not args.apply:
        response["status"] = "VALIDATED"
    else:
        equipment_before = len(load_master(db_path))
        backup_path = create_backup(db_path, args.backup_dir.resolve())
        outcomes = load_files(db_path, files, output_dir, plant_code=plant_code)
        inserted_quality_issues = add_comparison_quality_issues(db_path, result)
        from iris2.backfill_inspection_plans import backfill
        plan_result = backfill(
            db_path, apply=True, backup_dir=args.backup_dir.resolve()
        )
        verification = verify_database(db_path, equipment_before)
        response.update(
            status="COMPLETED",
            backup_path=str(backup_path),
            file_outcomes=outcomes,
            comparison_quality_issue_inserted=inserted_quality_issues,
            inspection_plan_result=plan_result,
            verification=verification,
        )
    final_path = output_dir / "run_result.json"
    final_path.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
