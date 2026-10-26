import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from iris2.iris_json_validator import normalize_equipment_code, number, report_parts, validate_file
from iris2.iris_v2_history import coverage_summary, register_heat_exchanger, tube_history
from iris2.iris_v2_importer import _canonical_unit, _ensure_asset, _partial_date, import_file
from iris2.iris_v2_database import init_v2_db, session_scope
from iris2.iris_v2_models import EquipmentAlias
from iris2.load_inspection_history_existing_only import load_master
from iris2.inspection_plan_rules import (
    inspection_plan_application_date,
    inspection_plan_approval_date,
)
from iris2.exchanger_type import standardize_exchanger_type


PROJECT_DIR = Path(__file__).resolve().parent / "data"


class IrisV3Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "test_v3.db"
        self.previous_db_v3 = os.environ.get("IRIS2_LEGACY_DB_PATH")
        self.previous_db_v2 = os.environ.get("IRIS2_LEGACY_V2_DB_PATH")
        os.environ["IRIS2_LEGACY_DB_PATH"] = str(self.db_path)
        os.environ["IRIS2_LEGACY_V2_DB_PATH"] = str(self.db_path)

    def tearDown(self):
        if self.previous_db_v3 is None:
            os.environ.pop("IRIS2_LEGACY_DB_PATH", None)
        else:
            os.environ["IRIS2_LEGACY_DB_PATH"] = self.previous_db_v3
        if self.previous_db_v2 is None:
            os.environ.pop("IRIS2_LEGACY_V2_DB_PATH", None)
        else:
            os.environ["IRIS2_LEGACY_V2_DB_PATH"] = self.previous_db_v2
        self.temp.cleanup()

    def test_normalization_preserves_zero_and_separates_scope(self):
        self.assertEqual(number(0), 0.0)
        self.assertEqual(number("0"), 0.0)
        self.assertEqual(normalize_equipment_code("E-111(TOP SOUTH)"),
                         ("E-111", "TOPSOUTH", ["TOP", "SOUTH"]))

    def test_partial_installation_date_preserves_source_precision(self):
        full = _partial_date("1992.07.23")
        self.assertEqual(full[0], datetime(1992, 7, 23))
        self.assertEqual(full[1:], ("1992.07.23", 1992, "DAY"))
        self.assertEqual(_partial_date("2021"), (None, "2021", 2021, "YEAR"))

    def test_pe_unit_is_inferred_from_current_json_filename(self):
        class Result:
            payload = {"document": {}}
            path = Path("2020_1P_PE_IRIS2_all_tube_results.json")

        self.assertEqual(_canonical_unit(Result(), None), "PE")

    def test_v35_report_context_and_provider_provenance_columns(self):
        init_v2_db(self.db_path)
        connection = sqlite3.connect(self.db_path)
        try:
            setup = {row[1] for row in connection.execute("PRAGMA table_info(iris_setup_snapshot)")}
            execution = {
                row[1] for row in connection.execute(
                    "PRAGMA table_info(inspection_execution_snapshot)"
                )
            }
        finally:
            connection.close()
        self.assertTrue({
            "process_code", "production_line", "shell_fluid", "tube_fluid", "tube_type",
        }.issubset(setup))
        self.assertTrue({
            "inspection_company_source_text", "inspection_company_brand", "source_page",
        }.issubset(execution))

    def test_exchanger_type_mapping_preserves_raw_and_holds_fts_for_review(self):
        self.assertEqual(
            standardize_exchanger_type("SHELL&TUBE"),
            ("ST", "Shell & Tube", "SHELL&TUBE", "MAPPED"),
        )
        self.assertEqual(
            standardize_exchanger_type("PHE"),
            ("PL", "Plate", "PHE", "MAPPED"),
        )
        self.assertEqual(
            standardize_exchanger_type("FIN TUBE"),
            ("FT", "Finned Tube", "FIN TUBE", "MAPPED"),
        )
        self.assertEqual(
            standardize_exchanger_type("FTS"),
            (None, None, "FTS", "REVIEW"),
        )
        self.assertEqual(
            standardize_exchanger_type("BEM"),
            ("ETC", "기타", "BEM", "UNMAPPED"),
        )

    def test_inspection_plan_dates_follow_weekday_business_rules(self):
        inspection_date = datetime(2023, 10, 8)  # Three months earlier is Saturday.
        application_date = inspection_plan_application_date(inspection_date)
        approval_date = inspection_plan_approval_date(application_date)
        self.assertEqual(application_date, datetime(2023, 7, 7))
        self.assertEqual(approval_date, datetime(2023, 7, 12))
        self.assertLess(application_date.weekday(), 5)
        self.assertLess(approval_date.weekday(), 5)
        self.assertLessEqual((approval_date - application_date).days, 7)

    def test_all_source_files_validate_without_fatal_errors(self):
        expected = {
            "2020VCM1_IRIS2_all_tube_results.json": (34, 454),
            "2020VCM2_IRIS2_all_tube_results.json": (42, 500),
            "2021VCM1_IRIS2_all_tube_results.json": (30, 419),
            "2021VCM2_IRIS2_all_tube_results.json": (50, 699),
        }
        for name, counts in expected.items():
            result = validate_file(PROJECT_DIR / name)
            self.assertEqual(result.error_count, 0, name)
            self.assertEqual((result.report_count, result.tube_result_count), counts, name)

    def test_dry_run_writes_reports_but_not_database(self):
        outcome = import_file(
            PROJECT_DIR / "2020VCM1_IRIS2_all_tube_results.json",
            dry_run=True, report_dir=self.root / "reports",
            cumulative_path=self.root / "cheking_report.md",
        )
        self.assertEqual(outcome["status"], "VALIDATED")
        self.assertGreater(outcome["total_exchanger_count"], 0)
        self.assertEqual(outcome["new_exchanger_count"], outcome["total_exchanger_count"])
        self.assertEqual(outcome["existing_exchanger_count"], 0)
        self.assertTrue(outcome["master_check_required"])
        self.assertEqual(outcome["missing_master_exchanger_count"],
                         outcome["total_exchanger_count"])
        self.assertEqual(outcome["skipped_missing_report_count"], outcome["report_count"])
        self.assertTrue(all(message.startswith("미존재 교환기:")
                            for message in outcome["missing_equipment_messages"]))
        self.assertFalse(self.db_path.exists())
        self.assertTrue(Path(outcome["markdown_report"]).exists())
        self.assertTrue(Path(outcome["issue_report"]).exists())
        self.assertTrue((self.root / "cheking_report.md").exists())

    def test_load_skips_json_equipment_missing_from_master(self):
        outcome = import_file(
            PROJECT_DIR / "2020VCM1_IRIS2_all_tube_results.json",
            report_dir=self.root / "reports",
            cumulative_path=self.root / "cheking_report.md",
        )
        self.assertEqual(outcome["status"], "PARTIAL")
        self.assertEqual(outcome["loaded_report_count"], 0)
        self.assertEqual(outcome["skipped_missing_report_count"], outcome["report_count"])
        self.assertGreater(outcome["missing_master_exchanger_count"], 0)
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("select count(*) from equipment")), 0)
            self.assertEqual(connection.scalar(text("select count(*) from heat_exchanger")), 0)
            self.assertEqual(connection.scalar(text("select count(*) from iris_inspection")), 0)
            self.assertEqual(connection.scalar(text(
                "select count(*) from data_quality_issue "
                "where issue_code='MASTER_EQUIPMENT_NOT_FOUND'"
            )), outcome["report_count"])
        engine.dispose()

        validation = validate_file(PROJECT_DIR / "2020VCM1_IRIS2_all_tube_results.json")
        for obj in validation.payload.get("inspection_reports", []):
            register_heat_exchanger(
                plant_code="P1", unit_code="VCM1",
                equipment_code=report_parts(obj)["equipment_code"],
            )
        retried = import_file(
            PROJECT_DIR / "2020VCM1_IRIS2_all_tube_results.json",
            report_dir=self.root / "reports",
            cumulative_path=self.root / "cheking_report.md",
        )
        self.assertEqual(retried["loaded_report_count"], validation.report_count)
        self.assertEqual(retried["skipped_missing_report_count"], 0)
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("select count(*) from source_document")), 1)
            self.assertEqual(connection.scalar(text(
                "select count(*) from data_quality_issue "
                "where issue_code='MASTER_EQUIPMENT_NOT_FOUND' and status='OPEN'"
            )), 0)
        engine.dispose()

    def test_multi_year_load_history_idempotence_and_integrity(self):
        files = sorted(PROJECT_DIR.glob("*VCM*_IRIS2_all_tube_results.json"))
        validations = [validate_file(path) for path in files]
        expected_reports = sum(result.report_count for result in validations)
        expected_tube_results = sum(result.tube_result_count for result in validations)
        registered: set[tuple[str, str]] = set()
        for path, validation in zip(files, validations):
            unit = "VCM1" if "VCM1" in path.name.upper() else "VCM2"
            for obj in validation.payload.get("inspection_reports", []):
                equipment_code = report_parts(obj)["equipment_code"]
                key = (unit, equipment_code)
                if key not in registered:
                    register_heat_exchanger(
                        plant_code="P1", unit_code=unit,
                        equipment_code=equipment_code,
                    )
                    registered.add(key)
        outcomes = [import_file(path, report_dir=self.root / "reports",
                                cumulative_path=self.root / "cheking_report.md") for path in files]
        self.assertEqual(sum(row["loaded_report_count"] for row in outcomes), expected_reports)
        self.assertTrue(all(
            row["new_exchanger_count"] + row["existing_exchanger_count"]
            == row["total_exchanger_count"] for row in outcomes
        ))
        self.assertTrue(all(row["skipped_missing_report_count"] == 0 for row in outcomes))
        self.assertEqual(coverage_summary()["tube_result_count"], expected_tube_results)
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        with engine.connect() as connection:
            self.assertEqual(connection.scalar(text("select count(*) from process_unit")), 2)
            self.assertEqual(connection.scalar(text("select count(*) from iris_inspection")), expected_reports)
            self.assertEqual(connection.scalar(text("select count(*) from iris_tube_result")), expected_tube_results)
            multi_year = connection.scalar(text("""
                select count(*) from (
                    select r.tube_id
                    from iris_tube_result r
                    join iris_inspection i on i.iris_inspection_id=r.iris_inspection_id
                    group by r.tube_id
                    having count(distinct strftime('%Y', i.report_date)) > 1
                )
            """))
            self.assertGreater(multi_year, 0)
            self.assertEqual(list(connection.execute(text("pragma foreign_key_check"))), [])
            tube_id = connection.scalar(text("select tube_id from tube_degradation_assessment limit 1"))
        engine.dispose()
        history = tube_history(tube_id)
        self.assertGreaterEqual(len(history["inspection_results"]), 2)
        self.assertGreaterEqual(len(history["degradation"]), 1)
        duplicate = import_file(files[0], report_dir=self.root / "reports",
                                cumulative_path=self.root / "cheking_report.md")
        self.assertEqual(duplicate["status"], "SKIPPED_DUPLICATE")
        self.assertEqual(duplicate["new_exchanger_count"], 0)
        self.assertEqual(
            duplicate["existing_exchanger_count"], duplicate["total_exchanger_count"]
        )

    def test_asset_without_iris_is_managed_separately(self):
        created = register_heat_exchanger(
            plant_code="P1", unit_code="VCM1", equipment_code="E-NO-IRIS",
            iris_applicability="OPTIONAL", expected_tube_count=100,
        )
        self.assertTrue(created["created"])
        summary = coverage_summary()
        self.assertEqual(summary["heat_exchanger_count"], 1)
        self.assertEqual(summary["inspection_count"], 0)
        self.assertEqual(summary["never_inspected_heat_exchanger_count"], 1)

    def test_spec_revision_constraints_and_side_summary_view(self):
        asset = register_heat_exchanger(
            plant_code="P1", unit_code="VCM1", equipment_code="E-REVISION"
        )
        exchanger_id = asset["heat_exchanger_id"]
        connection = sqlite3.connect(self.db_path)
        try:
            first_id = connection.execute("""
                INSERT INTO heat_exchanger_spec_revision (
                    heat_exchanger_id, revision_no, revision_code,
                    effective_from, is_current, design_pressure
                ) VALUES (?, 1, 'A', '2024-01-01', 1, 1.0)
            """, (exchanger_id,)).lastrowid
            connection.commit()

            with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
                connection.execute(
                    "UPDATE heat_exchanger_spec_revision SET design_pressure=2.0 "
                    "WHERE spec_revision_id=?", (first_id,),
                )
            connection.rollback()

            connection.execute("""
                UPDATE heat_exchanger_spec_revision
                   SET is_current=0, effective_to='2025-01-01'
                 WHERE spec_revision_id=?
            """, (first_id,))
            second_id = connection.execute("""
                INSERT INTO heat_exchanger_spec_revision (
                    heat_exchanger_id, revision_no, revision_code,
                    effective_from, is_current
                ) VALUES (?, 2, 'B', '2025-01-01', 1)
            """, (exchanger_id,)).lastrowid
            connection.commit()

            with self.assertRaisesRegex(sqlite3.IntegrityError, "overlap"):
                connection.execute("""
                    INSERT INTO heat_exchanger_spec_revision (
                        heat_exchanger_id, revision_no, revision_code,
                        effective_from, effective_to, is_current
                    ) VALUES (?, 3, 'C', '2024-06-01', '2024-07-01', 0)
                """, (exchanger_id,))
            connection.rollback()

            connection.executemany("""
                INSERT INTO heat_exchanger_side_spec (
                    spec_revision_id, side_code, design_pressure_mpa,
                    design_temperature_c, material, fluid
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, [
                (second_id, "SHELL", 1.0, 100.0, "CS", "STEAM"),
                (second_id, "TUBE", 2.0, 80.0, "STS304", "WATER"),
            ])
            summary = connection.execute("""
                SELECT numeric_summary_policy, design_pressure_mpa,
                       design_temperature_c, shell_material, tube_material
                  FROM v_heat_exchanger_spec_summary
                 WHERE spec_revision_id=?
            """, (second_id,)).fetchone()
            self.assertEqual(summary, ("MAX_ACROSS_SIDES", 2.0, 100.0, "CS", "STS304"))
        finally:
            connection.close()

    def test_spec_revision_exchanger_code_is_copied_then_kept_stable(self):
        asset = register_heat_exchanger(
            plant_code="P1", unit_code="VCM1", equipment_code="E-CODE-COPY"
        )
        connection = sqlite3.connect(self.db_path)
        try:
            spec_id = connection.execute("""
                INSERT INTO heat_exchanger_spec_revision (
                    heat_exchanger_id, revision_no, revision_code,
                    effective_from, is_current
                ) VALUES (?, 1, '1', '2026-01-01', 1)
            """, (asset["heat_exchanger_id"],)).lastrowid
            copied = connection.execute(
                "SELECT exchanger_code FROM heat_exchanger_spec_revision "
                "WHERE spec_revision_id=?", (spec_id,),
            ).fetchone()[0]
            self.assertEqual(copied, "E-CODE-COPY")

            connection.execute("""
                UPDATE equipment
                   SET equipment_code='E-CODE-UPDATED'
                 WHERE equipment_id=(
                     SELECT equipment_id FROM heat_exchanger WHERE heat_exchanger_id=?
                 )
            """, (asset["heat_exchanger_id"],))
            stable = connection.execute(
                "SELECT exchanger_code FROM heat_exchanger_spec_revision "
                "WHERE spec_revision_id=?", (spec_id,),
            ).fetchone()[0]
            self.assertEqual(stable, "E-CODE-COPY")
            connection.commit()
        finally:
            connection.close()

        with session_scope(self.db_path) as session:
            _unit, exchanger, _bundle = _ensure_asset(
                session, "P1", "VCM1", "E-CODE-COPY", "E-CODE-COPY",
                "test.json",
            )
            self.assertEqual(exchanger.heat_exchanger_id, asset["heat_exchanger_id"])

    def test_asset_natural_key_includes_plant_code(self):
        first_asset = register_heat_exchanger(
            plant_code="P1", unit_code="VCM1", equipment_code="E-SAME",
            equipment_name="Plant 1 exchanger",
        )
        second_asset = register_heat_exchanger(
            plant_code="P2", unit_code="VCM1", equipment_code="E-SAME",
            equipment_name="Plant 2 exchanger",
        )
        self.assertNotEqual(
            first_asset["heat_exchanger_id"], second_asset["heat_exchanger_id"]
        )

        master = load_master(self.db_path)
        self.assertIn(("P1", "VCM1", "E-SAME"), master)
        self.assertIn(("P2", "VCM1", "E-SAME"), master)
        self.assertNotEqual(
            master[("P1", "VCM1", "E-SAME")]["heat_exchanger_id"],
            master[("P2", "VCM1", "E-SAME")]["heat_exchanger_id"],
        )

        with session_scope() as session:
            _ensure_asset(session, "P1", "VCM1", "E-SAME", "E-SAME", "test.json")
            _ensure_asset(session, "P2", "VCM1", "E-SAME", "E-SAME", "test.json")
        with session_scope() as session:
            alias_scopes = {
                alias.source_unit for alias in session.query(EquipmentAlias).all()
            }
        self.assertEqual(alias_scopes, {"P1/VCM1", "P2/VCM1"})

    def test_master_csv_schema_and_field_remarks_are_seeded(self):
        init_v2_db(self.db_path)
        engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        expected_tables = {
            "heat_exchanger_side_spec",
            "heat_exchanger_capacity",
            "heat_exchanger_compliance",
            "master_heat_exchanger_staging",
            "schema_table_dictionary",
            "schema_field_dictionary",
        }
        with engine.connect() as connection:
            tables = {
                row[0] for row in connection.execute(text(
                    "select name from sqlite_master where type='table'"
                ))
            }
            self.assertTrue(expected_tables.issubset(tables))
            heat_exchanger_columns = {
                row[1] for row in connection.execute(text("pragma table_info(heat_exchanger)"))
            }
            self.assertTrue({
                "exchanger_type_code", "exchanger_type_name",
                "exchanger_type_raw", "type_mapping_status",
            }.issubset(heat_exchanger_columns))
            self.assertGreaterEqual(
                connection.scalar(text("select count(*) from schema_table_dictionary")), 9
            )
            self.assertGreaterEqual(
                connection.scalar(text("select count(*) from schema_field_dictionary")), 200
            )
            self.assertEqual(
                connection.scalar(text(
                    "select count(*) from schema_field_dictionary "
                    "where mapping_key='side.SHELL.design_pressure_mpa' "
                    "and csv_value_column='Shell 설계압력_*설계압력 Mpa(㎏/㎠g)-SHELL'"
                )),
                1,
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
