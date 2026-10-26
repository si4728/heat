"""Return PDF/C-Scan database linkage counts for the weekly report."""

from __future__ import annotations

import argparse
import configparser
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def scalar(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> int:
    value = connection.execute(sql, parameters).fetchone()[0]
    return int(value or 0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    config = configparser.ConfigParser()
    config.read(project_root / "hx_configuration.conf", encoding="utf-8")
    configured_name = config.get("database", "name", fallback="data/heat_exchanger_db3.db")
    database_path = Path(configured_name)
    if not database_path.is_absolute():
        database_path = project_root / database_path

    result = {
        "available": database_path.is_file(),
        "database_name": database_path.name,
        "database_path": str(database_path),
        "database_modified_at": None,
        "database_modified_in_period": False,
    }
    if not database_path.is_file():
        print(json.dumps(result, ensure_ascii=False))
        return

    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    modified_at = datetime.fromtimestamp(database_path.stat().st_mtime)
    result.update(
        database_modified_at=modified_at.isoformat(timespec="minutes"),
        database_modified_in_period=start <= modified_at <= end,
    )

    connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
    try:
        period_parameters = (start.isoformat(sep=" "), end.isoformat(sep=" "))
        result.update(
            period_import_batches=scalar(
                connection,
                "SELECT COUNT(*) FROM import_batch WHERE started_at BETWEEN ? AND ?",
                period_parameters,
            ),
            period_loaded_reports=scalar(
                connection,
                "SELECT COALESCE(SUM(loaded_report_count), 0) FROM import_batch "
                "WHERE started_at BETWEEN ? AND ?",
                period_parameters,
            ),
            period_import_warnings=scalar(
                connection,
                "SELECT COALESCE(SUM(warning_count), 0) FROM import_batch "
                "WHERE started_at BETWEEN ? AND ?",
                period_parameters,
            ),
            period_import_errors=scalar(
                connection,
                "SELECT COALESCE(SUM(error_count), 0) FROM import_batch "
                "WHERE started_at BETWEEN ? AND ?",
                period_parameters,
            ),
            pdf_result_page_links=scalar(
                connection, "SELECT COUNT(*) FROM iris_tube_result WHERE source_page IS NOT NULL"
            ),
            pdf_inspection_page_links=scalar(
                connection, "SELECT COUNT(*) FROM inspection_source_page"
            ),
            pdf_linked_inspections=scalar(
                connection,
                "SELECT COUNT(DISTINCT iris_inspection_id) FROM inspection_source_page",
            ),
            pdf_pages_with_images=scalar(
                connection, "SELECT COUNT(*) FROM source_document_page WHERE image_count > 0"
            ),
            attachment_records=scalar(
                connection, "SELECT COUNT(*) FROM inspection_attachment WHERE attachment_present = 1"
            ),
            indication_records=scalar(connection, "SELECT COUNT(*) FROM iris_indication"),
            raw_data_path_links=scalar(
                connection,
                "SELECT COUNT(*) FROM iris_indication "
                "WHERE source_data_path IS NOT NULL AND TRIM(source_data_path) <> ''",
            ),
            acquisition_time_links=scalar(
                connection, "SELECT COUNT(*) FROM iris_indication WHERE acquired_at IS NOT NULL"
            ),
            cscan_image_links=scalar(
                connection,
                "SELECT COUNT(*) FROM iris_indication WHERE source_image_xref IS NOT NULL "
                "OR visual_page_role IS NOT NULL",
            ),
            cscan_thickness_values=scalar(
                connection,
                "SELECT COUNT(*) FROM iris_indication "
                "WHERE cscan_min_wall_thickness_mm IS NOT NULL",
            ),
        )
    finally:
        connection.close()

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
