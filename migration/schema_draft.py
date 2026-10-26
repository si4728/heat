"""Compile a MariaDB schema draft only. Never connects or applies DDL."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import Computed, Column, Integer, String, Index, MetaData, Text
from sqlalchemy.dialects.mysql import mariadb, LONGTEXT
from sqlalchemy.schema import CreateTable, CreateIndex
from iris2.iris_v2_models import BaseV2


def build_metadata():
    metadata = MetaData()
    for source in BaseV2.metadata.tables.values():
        source.to_metadata(metadata)
    replacements = []
    for table in metadata.tables.values():
        table.dialect_options["mysql"]["engine"] = "InnoDB"
        table.dialect_options["mysql"]["charset"] = "utf8mb4"
        table.dialect_options["mysql"]["collate"] = "utf8mb4_bin"
        for column in table.columns:
            if isinstance(column.type, Text):
                column.type = LONGTEXT()
        for index in list(table.indexes):
            predicate = index.dialect_options["sqlite"].get("where")
            if predicate is None:
                continue
            table.indexes.remove(index)
            if index.name == "uq_organization_plant_code":
                table.append_column(Column("plant_code_unique", String(100),
                    Computed("CASE WHEN kind = 'PLANT' THEN code ELSE NULL END", persisted=True)))
                Index(index.name, table.c.plant_code_unique, unique=True)
            elif index.name == "uq_current_spec_revision":
                table.append_column(Column("current_exchanger_unique", Integer,
                    Computed("CASE WHEN is_current = 1 THEN heat_exchanger_id ELSE NULL END", persisted=True)))
                Index(index.name, table.c.current_exchanger_unique, unique=True)
            else:
                raise ValueError(f"Unmapped partial index: {index.name}")
            replacements.append(index.name)
    return metadata, replacements


def main():
    metadata, replacements = build_metadata()
    dialect = mariadb.MariaDBDialect()
    statements = ["-- DRAFT ONLY: needs live MariaDB validation and revision-overlap rules."]
    # All FK references may be forward references during draft generation.
    for table in metadata.tables.values():
        statements.append(str(CreateTable(table).compile(dialect=dialect)) + ";")
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            statements.append(str(CreateIndex(index).compile(dialect=dialect)) + ";")
    output = Path(__file__).resolve().parent / "schema_mariadb_draft.sql"
    output.write_text("\n\n".join(statements), encoding="utf-8")
    report = {"table_count": len(metadata.tables), "partial_indexes_converted": replacements,
        "applied": False, "production_ready": False,
        "pending": ["LIVE_DDL_VALIDATION", "REVISION_OVERLAP_CONCURRENCY_RULES", "ACTUAL_DB_SCHEMA_PARITY"]}
    output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
