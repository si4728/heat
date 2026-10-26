import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

try:
    from .master_heat_exchanger_import import (
        load_csv,
        parse_pressure_mpa,
        parse_temperature_c,
        parse_tube_count,
        upsert_equipment_and_exchanger,
    )
except ImportError:  # Allows direct execution from the iris directory.
    from master_heat_exchanger_import import (
        load_csv,
        parse_pressure_mpa,
        parse_temperature_c,
        parse_tube_count,
        upsert_equipment_and_exchanger,
    )


class MasterHeatExchangerImportTest(unittest.TestCase):
    def test_pressure_parses_mpa_and_parenthesized_kgf_equivalents(self):
        self.assertEqual(parse_pressure_mpa("0.76 (7.8) MPa", ""), 0.76)
        self.assertEqual(
            parse_pressure_mpa("0.04 1.03\n(0.45 10.5) MPa", ""),
            1.03,
        )
        self.assertAlmostEqual(parse_pressure_mpa("7", "Kg/cm2g"), 0.6864655)
        self.assertAlmostEqual(parse_pressure_mpa("600 ㎜AQ", ""), 0.00588399)
        self.assertAlmostEqual(parse_pressure_mpa("200㎜Hg", ""), 0.0266644736)
        self.assertEqual(parse_pressure_mpa(".049 (71psi) MPa", ""), 0.049)
        self.assertIsNone(parse_pressure_mpa("1.475.88 MPa", ""))

    def test_temperature_uses_conservative_max_and_rejects_misplaced_pressure(self):
        self.assertEqual(parse_temperature_c("65/52"), 65.0)
        self.assertEqual(parse_temperature_c("-40.5/16.0\n25.4/23.7"), 25.4)
        self.assertIsNone(parse_temperature_c("1.2/FV (12.2/FV)"))
        self.assertIsNone(parse_temperature_c("10월 04일"))

    def test_tube_count_only_calculates_supported_source_patterns(self):
        self.assertEqual(parse_tube_count("208\n(3710)"), 208)
        self.assertEqual(parse_tube_count("TOTAL : 1128\n(도면:286개*3SET)"), 1128)
        self.assertEqual(parse_tube_count("(도면:249개*3SET)"), 747)
        self.assertIsNone(parse_tube_count("1076/386"))

    def test_original_two_row_header_is_canonicalized_without_counting_unit_row(self):
        headers = [
            "공정", "설비코드", "설비명", "설비번호", "설비Tag", "설비등급",
            "설비상태", "Type", "Tube 개수", "Shell 유체", "Tube 유체",
        ]
        roles = ["", "", "", "", "", "", "", "값", "값", "값", "값"]
        values = [
            "VCM1", "E-201B", "FURNACE FAN COOLER", "1102127", "US-VC-E-201B",
            "B", "현장설비", "SHELL&TUBE", "208", "CTW", "VCM",
        ]
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "master.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                csv.writer(handle).writerows([headers, roles, values])
            canonical_headers, rows, first_source_row = load_csv(csv_path)

        self.assertEqual(first_source_row, 3)
        self.assertEqual(len(rows), 1)
        self.assertIn("Tube 개수_val", canonical_headers)
        self.assertEqual(rows[0]["설비코드"], "E-201B")

    def test_master_reimport_keeps_numeric_asset_code_and_matches_exchanger_code(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE equipment (
                equipment_id INTEGER PRIMARY KEY, unit_id INTEGER,
                equipment_code TEXT, equipment_name TEXT, equipment_number TEXT,
                equipment_tag TEXT, equipment_type TEXT, status TEXT,
                criticality_grade TEXT, updated_at TEXT
            );
            CREATE TABLE heat_exchanger (
                heat_exchanger_id INTEGER PRIMARY KEY, equipment_id INTEGER,
                exchanger_type TEXT, exchanger_type_code TEXT,
                exchanger_type_name TEXT, exchanger_type_raw TEXT,
                type_mapping_status TEXT, service_name TEXT
            );
            CREATE TABLE heat_exchanger_spec_revision (
                spec_revision_id INTEGER PRIMARY KEY, heat_exchanger_id INTEGER,
                exchanger_code TEXT, is_current INTEGER
            );
            INSERT INTO equipment VALUES
                (1, 10, '1102127', 'OLD', '1102127', 'TAG',
                 'HEAT_EXCHANGER', 'UNKNOWN', NULL, '2026-01-01');
            INSERT INTO heat_exchanger VALUES
                (1, 1, NULL, NULL, NULL, NULL, 'UNMAPPED', 'OLD');
            INSERT INTO heat_exchanger_spec_revision VALUES
                (1, 1, 'E-201B', 1);
        """)
        row = {
            "설비코드": "E-201B", "설비번호": "1102127",
            "설비명": "FURNACE FAN COOLER", "설비Tag": "US-VC-E-201B",
            "설비상태": "현장설비", "설비등급": "B", "Type_val": "SHELL&TUBE",
        }
        equipment_id, exchanger_id, inserted = upsert_equipment_and_exchanger(
            connection, row, 10, "2026-08-20"
        )
        saved = connection.execute(
            "SELECT equipment_code, equipment_name FROM equipment WHERE equipment_id=1"
        ).fetchone()
        self.assertEqual((equipment_id, exchanger_id, inserted), (1, 1, False))
        self.assertEqual(tuple(saved), ("1102127", "FURNACE FAN COOLER"))
        connection.close()


if __name__ == "__main__":
    unittest.main()
