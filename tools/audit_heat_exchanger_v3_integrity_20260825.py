from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = ROOT / "iris" / "outputs" / "heat_exchanger_v3_integrity_audit_20260825"


def configured_database() -> Path:
    config_path = ROOT / "iris" / "hx_configuration.conf"
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(config_path, encoding="utf-8")
    value = Path(parser.get("database", "name", fallback="data/heat_exchanger_db3.db"))
    return value if value.is_absolute() else config_path.parent / value


def scalar(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> int | float | str | None:
    return connection.execute(sql, parameters).fetchone()[0]


def count(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> int:
    return int(scalar(connection, sql, parameters) or 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only integrity audit for the configured IRIS database.")
    parser.add_argument("--database", type=Path, default=configured_database())
    args = parser.parse_args()
    db_path = args.database.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / stamp
    output_dir.mkdir(parents=True, exist_ok=False)

    before = {"size": db_path.stat().st_size, "mtime_ns": db_path.stat().st_mtime_ns, "sha256": sha256(db_path)}
    uri = f"file:{db_path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        objects = Counter(row[0] for row in connection.execute(
            "SELECT type FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ))
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        table_counts = {table: count(connection, f'SELECT COUNT(*) FROM "{table}"') for table in tables}
        schema_versions = [row[0] for row in connection.execute("SELECT version FROM schema_version ORDER BY version_id")]

        checks = {
            "foreign_key_issues": count(connection, "SELECT COUNT(*) FROM pragma_foreign_key_check"),
            "duplicate_campaign_report_sequence": count(connection, """
                SELECT COUNT(*) FROM (
                    SELECT campaign_id, report_sequence FROM iris_inspection
                    GROUP BY campaign_id, report_sequence HAVING COUNT(*) > 1
                )
            """),
            "duplicate_source_report_sequence": count(connection, """
                SELECT COUNT(*) FROM (
                    SELECT source_document_id, report_sequence FROM iris_inspection
                    GROUP BY source_document_id, report_sequence HAVING COUNT(*) > 1
                )
            """),
            "missing_inspection_report_date": count(connection, "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NULL"),
            "missing_inspection_heat_exchanger": count(connection, "SELECT COUNT(*) FROM iris_inspection WHERE heat_exchanger_id IS NULL"),
            "missing_inspection_bundle": count(connection, "SELECT COUNT(*) FROM iris_inspection WHERE bundle_id IS NULL"),
            "missing_spec_snapshot": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN iris_inspection_spec_snapshot s
                  ON s.iris_inspection_id=i.iris_inspection_id WHERE s.spec_snapshot_id IS NULL
            """),
            "missing_setup_snapshot": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN iris_setup_snapshot s
                  ON s.iris_inspection_id=i.iris_inspection_id WHERE s.setup_snapshot_id IS NULL
            """),
            "missing_validation": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN inspection_validation v
                  ON v.iris_inspection_id=i.iris_inspection_id WHERE v.inspection_validation_id IS NULL
            """),
            "inspection_extracted_count_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN (
                    SELECT iris_inspection_id, COUNT(*) n FROM iris_tube_result GROUP BY iris_inspection_id
                ) r ON r.iris_inspection_id=i.iris_inspection_id
                WHERE i.extracted_tube_result_count <> COALESCE(r.n,0)
            """),
            "validation_extracted_count_mismatch": count(connection, """
                SELECT COUNT(*) FROM inspection_validation v LEFT JOIN (
                    SELECT iris_inspection_id, COUNT(*) n FROM iris_tube_result GROUP BY iris_inspection_id
                ) r ON r.iris_inspection_id=v.iris_inspection_id
                WHERE v.extracted_tube_result_count <> COALESCE(r.n,0)
            """),
            "summary_inspected_vs_detail_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_inspection_spec_snapshot s JOIN (
                    SELECT iris_inspection_id, COUNT(*) n FROM iris_tube_result GROUP BY iris_inspection_id
                ) r ON r.iris_inspection_id=s.iris_inspection_id
                WHERE s.summary_inspected_tubes IS NOT NULL AND s.summary_inspected_tubes <> r.n
            """),
            "reported_inspected_vs_detail_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN (
                    SELECT iris_inspection_id, COUNT(*) n FROM iris_tube_result GROUP BY iris_inspection_id
                ) r ON r.iris_inspection_id=i.iris_inspection_id
                WHERE i.inspected_tube_count_reported IS NOT NULL
                  AND i.inspected_tube_count_reported <> COALESCE(r.n,0)
            """),
            "inspection_bundle_exchanger_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i JOIN tube_bundle b ON b.bundle_id=i.bundle_id
                WHERE i.heat_exchanger_id <> b.heat_exchanger_id
            """),
            "inspection_scope_exchanger_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i JOIN inspection_scope s ON s.inspection_scope_id=i.inspection_scope_id
                WHERE i.heat_exchanger_id <> s.heat_exchanger_id OR i.bundle_id <> s.bundle_id
            """),
            "tube_result_exchanger_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_tube_result r
                JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
                JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id
                JOIN tube_bundle b ON b.bundle_id=t.bundle_id
                WHERE i.heat_exchanger_id <> b.heat_exchanger_id
            """),
            "tube_source_id_master_no_mismatch": count(connection, """
                SELECT COUNT(*) FROM iris_tube_result r JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id
                WHERE TRIM(r.source_tube_id) <> TRIM(t.tube_no)
            """),
            "degradation_current_result_tube_mismatch": count(connection, """
                SELECT COUNT(*) FROM tube_degradation_assessment d
                JOIN iris_tube_result r ON r.iris_tube_result_id=d.current_result_id
                WHERE d.tube_id <> r.tube_id
            """),
            "degradation_previous_result_tube_mismatch": count(connection, """
                SELECT COUNT(*) FROM tube_degradation_assessment d
                JOIN iris_tube_result r ON r.iris_tube_result_id=d.previous_result_id
                WHERE d.previous_result_id IS NOT NULL AND d.tube_id <> r.tube_id
            """),
            "plan_completed_inspection_exchanger_mismatch": count(connection, """
                SELECT COUNT(*) FROM inspection_plan_v2 p JOIN iris_inspection i
                  ON i.iris_inspection_id=p.completed_inspection_id
                WHERE p.heat_exchanger_id <> i.heat_exchanger_id
            """),
            "inspection_without_completed_plan": count(connection, """
                SELECT COUNT(*) FROM iris_inspection i LEFT JOIN inspection_plan_v2 p
                  ON p.completed_inspection_id=i.iris_inspection_id
                WHERE p.inspection_plan_id IS NULL
            """),
            "source_document_load_count_mismatch": count(connection, """
                SELECT COUNT(*) FROM source_document d LEFT JOIN (
                    SELECT source_document_id, COUNT(*) n FROM iris_inspection GROUP BY source_document_id
                ) i ON i.source_document_id=d.source_document_id
                WHERE d.loaded_report_count <> COALESCE(i.n,0)
                   OR d.missing_report_count <> MAX(d.expected_report_count-COALESCE(i.n,0),0)
            """),
            "multiple_current_spec_revisions": count(connection, """
                SELECT COUNT(*) FROM (
                    SELECT heat_exchanger_id FROM heat_exchanger_spec_revision
                    WHERE is_current=1 GROUP BY heat_exchanger_id HAVING COUNT(*) > 1
                )
            """),
            "current_spec_with_effective_to": count(connection, """
                SELECT COUNT(*) FROM heat_exchanger_spec_revision WHERE is_current=1 AND effective_to IS NOT NULL
            """),
            "invalid_report_nominal_thickness_9000": count(connection, """
                SELECT COUNT(*) FROM iris_inspection_spec_snapshot WHERE report_nominal_thickness_mm=9000.0
            """),
            "invalid_setup_outer_diameter_2_34": count(connection, """
                SELECT COUNT(*) FROM iris_setup_snapshot WHERE out_diameter_mm=2.34
            """),
            "invalid_master_nominal_thickness_9000": count(connection, """
                SELECT COUNT(*) FROM heat_exchanger_spec_revision WHERE tube_nominal_thickness_mm=9000.0
            """),
            "invalid_master_outer_diameter_2_34": count(connection, """
                SELECT COUNT(*) FROM heat_exchanger_spec_revision WHERE tube_outer_diameter_mm=2.34
            """),
            "summary_total_null": count(connection, "SELECT COUNT(*) FROM iris_inspection_spec_snapshot WHERE summary_total_tubes IS NULL"),
            "summary_inspected_null": count(connection, "SELECT COUNT(*) FROM iris_inspection_spec_snapshot WHERE summary_inspected_tubes IS NULL"),
            "summary_page_null": count(connection, "SELECT COUNT(*) FROM iris_inspection_spec_snapshot WHERE summary_page IS NULL"),
            "summary_all_spec_null": count(connection, """
                SELECT COUNT(*) FROM iris_inspection_spec_snapshot
                WHERE summary_material IS NULL AND summary_outer_diameter_mm IS NULL
                  AND summary_design_thickness_mm IS NULL AND summary_length_mm IS NULL
            """),
        }

        integrity_rows = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        quick_rows = [row[0] for row in connection.execute("PRAGMA quick_check")]
        quality_by_code = {row[0]: row[1] for row in connection.execute(
            "SELECT issue_code, COUNT(*) FROM data_quality_issue GROUP BY issue_code ORDER BY issue_code"
        )}
        quality_by_severity_status = [dict(row) for row in connection.execute(
            "SELECT severity,status,COUNT(*) AS count FROM data_quality_issue GROUP BY severity,status ORDER BY severity,status"
        )]
        source_loads = [dict(row) for row in connection.execute("""
            SELECT source_file,load_status,expected_report_count,loaded_report_count,missing_report_count,postprocess_status
            FROM source_document ORDER BY source_file
        """)]
        count_mismatch_details = [dict(row) for row in connection.execute("""
            SELECT d.source_file,i.report_sequence,i.canonical_equipment_code,
                   i.inspected_tube_count_reported,s.summary_inspected_tubes,
                   COUNT(r.iris_tube_result_id) AS actual_detail_rows
            FROM iris_inspection i
            JOIN source_document d ON d.source_document_id=i.source_document_id
            JOIN iris_inspection_spec_snapshot s ON s.iris_inspection_id=i.iris_inspection_id
            LEFT JOIN iris_tube_result r ON r.iris_inspection_id=i.iris_inspection_id
            GROUP BY i.iris_inspection_id
            HAVING (i.inspected_tube_count_reported IS NOT NULL
                    AND i.inspected_tube_count_reported<>COUNT(r.iris_tube_result_id))
                OR (s.summary_inspected_tubes IS NOT NULL
                    AND s.summary_inspected_tubes<>COUNT(r.iris_tube_result_id))
            ORDER BY d.source_file,i.report_sequence
        """)]
        invalid_spec_details = [dict(row) for row in connection.execute("""
            SELECT d.source_file,i.report_sequence,i.canonical_equipment_code,
                   s.report_nominal_thickness_mm,u.out_diameter_mm
            FROM iris_inspection i
            JOIN source_document d ON d.source_document_id=i.source_document_id
            JOIN iris_inspection_spec_snapshot s ON s.iris_inspection_id=i.iris_inspection_id
            JOIN iris_setup_snapshot u ON u.iris_inspection_id=i.iris_inspection_id
            WHERE s.report_nominal_thickness_mm=9000.0 OR u.out_diameter_mm=2.34
            ORDER BY d.source_file,i.report_sequence
        """)]
        summary_nulls_by_source = [dict(row) for row in connection.execute("""
            SELECT d.source_file,
                   SUM(s.summary_total_tubes IS NULL) AS total_null,
                   SUM(s.summary_inspected_tubes IS NULL) AS inspected_null,
                   SUM(s.summary_page IS NULL) AS page_null,
                   SUM(s.summary_material IS NULL AND s.summary_outer_diameter_mm IS NULL
                       AND s.summary_design_thickness_mm IS NULL AND s.summary_length_mm IS NULL) AS all_spec_null
            FROM iris_inspection i
            JOIN source_document d ON d.source_document_id=i.source_document_id
            JOIN iris_inspection_spec_snapshot s ON s.iris_inspection_id=i.iris_inspection_id
            GROUP BY d.source_document_id ORDER BY d.source_file
        """)]
    finally:
        connection.close()

    after = {"size": db_path.stat().st_size, "mtime_ns": db_path.stat().st_mtime_ns, "sha256": sha256(db_path)}
    result = {
        "audit_mode": "READ_ONLY",
        "database": str(db_path),
        "database_before": before,
        "database_after": after,
        "database_unchanged": before == after,
        "sqlite_integrity_check": integrity_rows,
        "sqlite_quick_check": quick_rows,
        "schema_versions": schema_versions,
        "schema_object_counts": dict(objects),
        "table_counts": table_counts,
        "business_rule_checks": checks,
        "quality_issue_counts_by_code": quality_by_code,
        "quality_issue_counts_by_severity_status": quality_by_severity_status,
        "source_document_loads": source_loads,
        "count_mismatch_details": count_mismatch_details,
        "invalid_spec_details": invalid_spec_details,
        "summary_nulls_by_source": summary_nulls_by_source,
    }
    json_path = output_dir / "heat_exchanger_v3_integrity_audit.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    nonzero = {key: value for key, value in checks.items() if value}
    lines = [
        f"# {db_path.name} 정합성 재점검",
        "",
        f"- 점검 모드: `{result['audit_mode']}`",
        f"- SQLite integrity_check: `{integrity_rows}`",
        f"- 외래키 위반: `{checks['foreign_key_issues']}`",
        f"- 검사 중 DB 변경: `{not result['database_unchanged']}`",
        f"- SHA-256: `{after['sha256']}`",
        f"- 스키마 버전: `{', '.join(schema_versions)}`",
        "",
        "## 주요 레코드 수",
        "",
    ]
    for table in ("source_document", "inspection_campaign", "iris_inspection", "iris_tube_result", "iris_recommendation", "inspection_personnel", "data_quality_issue", "inspection_plan_v2", "tube_degradation_assessment"):
        lines.append(f"- `{table}`: {table_counts.get(table, 0)}")
    lines.extend(["", "## 0이 아닌 업무 규칙 점검 결과", ""])
    for key, value in nonzero.items():
        lines.append(f"- `{key}`: {value}")
    if not nonzero:
        lines.append("- 없음")
    lines.extend(["", "## 품질 이슈 코드", ""])
    for key, value in quality_by_code.items():
        lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## 검사 수량과 상세행 불일치", ""])
    for row in count_mismatch_details:
        lines.append(
            f"- `{row['source_file']}` seq {row['report_sequence']} "
            f"`{row['canonical_equipment_code']}`: report={row['inspected_tube_count_reported']}, "
            f"summary={row['summary_inspected_tubes']}, detail={row['actual_detail_rows']}"
        )
    lines.extend(["", "## 비정상 보고 제원", ""])
    for row in invalid_spec_details:
        lines.append(
            f"- `{row['source_file']}` seq {row['report_sequence']} "
            f"`{row['canonical_equipment_code']}`: thickness={row['report_nominal_thickness_mm']}, "
            f"OD={row['out_diameter_mm']}"
        )
    md_path = output_dir / "heat_exchanger_v3_integrity_audit.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"output_dir": str(output_dir), "json": str(json_path), "markdown": str(md_path), "summary": {"integrity": integrity_rows, "database_unchanged": before == after, "nonzero_checks": nonzero}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
