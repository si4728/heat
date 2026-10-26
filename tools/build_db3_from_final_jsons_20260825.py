from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))

from iris2.backfill_inspection_plans import backfill
from iris2.iris_v2_importer import import_file
from iris2.load_inspection_history_existing_only import (
    add_comparison_quality_issues,
    collect_files,
    precheck,
)


SOURCE_DB = APP_DIR / "data" / "heat_exchanger_v3.db"
TARGET_DB = APP_DIR / "data" / "heat_exchanger_db3.db"
DATA_DIR = APP_DIR / "data"
OUTPUT_ROOT = APP_DIR / "outputs" / "db3_final_json_update_20260825"

MASTER_TABLES = (
    "plant",
    "process_unit",
    "equipment",
    "equipment_alias",
    "heat_exchanger",
    "heat_exchanger_spec_revision",
    "heat_exchanger_side_spec",
    "heat_exchanger_capacity",
    "heat_exchanger_compliance",
    "heat_exchanger_management_criteria",
    "pressure_boundary_component",
    "tube_bundle",
)


def file_digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def table_digest(connection: sqlite3.Connection, table: str) -> str:
    columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
    order = ",".join(f'"{column}"' for column in columns)
    rows = connection.execute(f'SELECT {order} FROM "{table}" ORDER BY {order}').fetchall()
    payload = json.dumps([list(row) for row in rows], ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def master_digests(db_path: Path) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return {table: table_digest(connection, table) for table in MASTER_TABLES}
    finally:
        connection.close()


def maximum_alias_id(db_path: Path) -> int:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COALESCE(MAX(alias_id),0) FROM equipment_alias").fetchone()[0])
    finally:
        connection.close()


def remove_import_created_aliases(db_path: Path, original_max_alias_id: int) -> int:
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        cursor = connection.execute(
            "DELETE FROM equipment_alias WHERE alias_id>?",
            (original_max_alias_id,),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def copy_database(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"Target db3 already exists: {target}")
    source_connection = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
        if target_connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Copied db3 failed integrity_check")
    finally:
        target_connection.close()
        source_connection.close()


def source_mapping(connection: sqlite3.Connection) -> dict[tuple[int, str], int]:
    rows = connection.execute(
        """
        SELECT DISTINCT c.campaign_year, u.unit_code, i.source_document_id
          FROM iris_inspection i
          JOIN inspection_campaign c ON c.campaign_id=i.campaign_id
          JOIN process_unit u ON u.unit_id=c.unit_id
        """
    ).fetchall()
    result: dict[tuple[int, str], int] = {}
    for year, unit, document_id in rows:
        key = (int(year), str(unit).upper())
        if key in result and result[key] != int(document_id):
            raise RuntimeError(f"Multiple source documents for campaign {key}")
        result[key] = int(document_id)
    return result


def refresh_source_documents(
    connection: sqlite3.Connection,
    files: list[Path],
    mapping: dict[tuple[int, str], int],
) -> None:
    for path in files:
        match = __import__("re").match(
            r"^(20\d{2})(PE|VCM1|VCM2)_IRIS2_all_tube_results\.json$",
            path.name,
            flags=__import__("re").IGNORECASE,
        )
        if not match:
            raise RuntimeError(f"Unexpected JSON filename: {path.name}")
        key = (int(match.group(1)), match.group(2).upper())
        document_id = mapping.get(key)
        if document_id is None:
            raise RuntimeError(f"Existing source_document mapping not found: {key}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        document = payload.get("document") or {}
        schema = payload.get("schema") or {}
        stat = path.stat()
        connection.execute(
            """
            UPDATE source_document
               SET source_file=?, source_path=?, title=?, page_count=?, file_size=?,
                   sha256=?, schema_name=?, schema_version=?, source_modified_at=?,
                   document_json=?, schema_json=?, load_status='RECEIVED',
                   expected_report_count=?, loaded_report_count=0, missing_report_count=0,
                   postprocess_status='PENDING', postprocess_message=NULL
             WHERE source_document_id=?
            """,
            (
                path.name,
                str(path.resolve()),
                document.get("title"),
                document.get("page_count"),
                stat.st_size,
                file_digest(path),
                schema.get("name") or "iris-inspection-report",
                schema.get("version") or "1.0.0",
                datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" "),
                json.dumps(document, ensure_ascii=False, separators=(",", ":")),
                json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
                len(payload.get("inspection_reports") or []),
                document_id,
            ),
        )


def purge_old_inspection_history(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table in (
            "tube_degradation_assessment",
            "iris_indication",
            "data_quality_issue",
            "inspection_plan_v2",
            "iris_tube_map_legend",
            "iris_tube_map",
            "inspection_attachment",
            "inspection_execution_snapshot",
            "inspection_personnel",
            "inspection_source_page",
            "inspection_validation",
            "iris_inspection_spec_snapshot",
            "iris_inspection_summary_history",
            "iris_recommendation",
            "iris_representative_assessment",
            "iris_setup_snapshot",
            "iris_tube_result",
            "source_document_page",
        ):
            connection.execute(f'DELETE FROM "{table}"')
        connection.execute("DELETE FROM iris_inspection")
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def verify(db_path: Path, source_master: dict[str, str]) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        counts = {
            table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table in (
                "source_document",
                "inspection_campaign",
                "iris_inspection",
                "iris_inspection_spec_snapshot",
                "iris_setup_snapshot",
                "iris_tube_result",
                "iris_recommendation",
                "inspection_personnel",
                "data_quality_issue",
                "inspection_plan_v2",
                "tube_degradation_assessment",
            )
        }
        current_master = {table: table_digest(connection, table) for table in MASTER_TABLES}
        master_changes = {
            table: {"before": source_master[table], "after": current_master[table]}
            for table in MASTER_TABLES
            if source_master[table] != current_master[table]
        }
        summary_null_counts = connection.execute(
            """
            SELECT
              SUM(CASE WHEN summary_total_tubes IS NULL THEN 1 ELSE 0 END),
              SUM(CASE WHEN summary_inspected_tubes IS NULL THEN 1 ELSE 0 END),
              SUM(CASE WHEN summary_page IS NULL THEN 1 ELSE 0 END),
              SUM(CASE WHEN summary_material IS NULL AND summary_outer_diameter_mm IS NULL
                        AND summary_design_thickness_mm IS NULL AND summary_length_mm IS NULL
                       THEN 1 ELSE 0 END)
            FROM iris_inspection_spec_snapshot
            """
        ).fetchone()
        summary_nulls = {
            "summary_total_tubes_null": summary_null_counts[0],
            "summary_inspected_tubes_null": summary_null_counts[1],
            "summary_page_null": summary_null_counts[2],
            "summary_all_spec_fields_null": summary_null_counts[3],
        }
        result = {
            "counts": counts,
            "summary_null_counts": summary_nulls,
            "master_table_changes": master_changes,
            "integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "foreign_key_issue_count": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
            "missing_report_date_count": connection.execute(
                "SELECT COUNT(*) FROM iris_inspection WHERE report_date IS NULL"
            ).fetchone()[0],
            "duplicate_campaign_sequence_count": connection.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT campaign_id,report_sequence,COUNT(*) n
                      FROM iris_inspection GROUP BY campaign_id,report_sequence HAVING n>1
                )
                """
            ).fetchone()[0],
            "db_sha256": file_digest(db_path),
        }
        if counts["source_document"] != 11:
            raise RuntimeError(f"Expected 11 source documents, found {counts['source_document']}")
        if counts["iris_inspection"] != 435:
            raise RuntimeError(f"Expected 435 inspections, found {counts['iris_inspection']}")
        if counts["iris_tube_result"] != 6084:
            raise RuntimeError(f"Expected 6084 tube results, found {counts['iris_tube_result']}")
        if result["integrity_check"] != "ok" or result["foreign_key_issue_count"]:
            raise RuntimeError(f"DB integrity verification failed: {result}")
        if result["duplicate_campaign_sequence_count"]:
            raise RuntimeError(f"Duplicate campaign sequences found: {result}")
        if master_changes:
            raise RuntimeError(f"Protected master tables changed: {master_changes}")
        return result
    finally:
        connection.close()


def main() -> None:
    files = collect_files(DATA_DIR)
    if len(files) != 11:
        raise RuntimeError(f"Expected 11 final JSON files, found {len(files)}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_ROOT / stamp
    output_dir.mkdir(parents=True)
    report_dir = output_dir / "per_file_reports"
    cumulative = output_dir / "cumulative_checking_report.md"

    source_db_sha256 = file_digest(SOURCE_DB)
    source_master = master_digests(SOURCE_DB)
    source_max_alias_id = maximum_alias_id(SOURCE_DB)
    copy_database(SOURCE_DB, TARGET_DB)

    connection = sqlite3.connect(TARGET_DB)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        mapping = source_mapping(connection)
        if len(mapping) != 11:
            raise RuntimeError(f"Expected 11 campaign/source mappings, found {len(mapping)}")
        purge_old_inspection_history(connection)
        refresh_source_documents(connection, files, mapping)
        connection.commit()
    finally:
        connection.close()

    outcomes = []
    for path in files:
        unit = __import__("re").match(r"^20\d{2}(PE|VCM1|VCM2)_", path.name, flags=__import__("re").IGNORECASE).group(1)
        outcome = import_file(
            path,
            plant_code="P1",
            unit_code=unit,
            dry_run=False,
            allow_errors=False,
            report_dir=report_dir,
            cumulative_path=cumulative,
            db_path=TARGET_DB,
        )
        outcomes.append(outcome)
        if outcome["status"] not in {"COMPLETED", "COMPLETED_WITH_WARNINGS"}:
            raise RuntimeError(f"Import failed for {path.name}: {outcome}")

    removed_import_alias_count = remove_import_created_aliases(
        TARGET_DB, source_max_alias_id
    )
    comparison = precheck(TARGET_DB, files, plant_code="P1")
    comparison_issue_count = add_comparison_quality_issues(TARGET_DB, comparison)
    plan_result = backfill(
        TARGET_DB,
        apply=True,
        backup_dir=output_dir / "internal_backups",
    )
    verification = verify(TARGET_DB, source_master)
    manifest = {
        "operation": "create_db3_and_replace_inspection_history_from_final_11_jsons",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_db": str(SOURCE_DB),
        "source_db_sha256": source_db_sha256,
        "target_db": str(TARGET_DB),
        "target_db_sha256": verification["db_sha256"],
        "json_files": [str(path) for path in files],
        "file_outcomes": outcomes,
        "comparison_quality_issue_inserted": comparison_issue_count,
        "removed_import_created_alias_count": removed_import_alias_count,
        "inspection_plan_result": plan_result,
        "verification": verification,
        "master_protected": True,
        "source_db_modified": False,
    }
    manifest_path = output_dir / "DB3_UPDATE_MANIFEST_20260825.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_db": str(TARGET_DB),
        "manifest": str(manifest_path),
        "source_db_sha256": source_db_sha256,
        "target_db_sha256": verification["db_sha256"],
        "comparison_quality_issue_inserted": comparison_issue_count,
        "verification": verification,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
