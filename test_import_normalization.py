from __future__ import annotations

import unittest

from iris2.import_normalization import normalize_equipment_code
from iris2.iris_json_mapping import report_details, resolve_report_identity


class ImportNormalizationTest(unittest.TestCase):
    def test_plain_equipment_code_is_unchanged(self):
        self.assertEqual(normalize_equipment_code("E-111"), ("E-111", "ALL", []))

    def test_parenthesized_direction_is_a_scope(self):
        self.assertEqual(
            normalize_equipment_code("E-121A(TOP)"),
            ("E-121A", "TOP", ["TOP"]),
        )

    def test_space_separated_direction_is_a_scope(self):
        self.assertEqual(
            normalize_equipment_code("E-205B BTM"),
            ("E-205B", "BTM", ["BTM"]),
        )

    def test_numbered_section_is_a_scope(self):
        self.assertEqual(normalize_equipment_code("E-332-2"), ("E-332", "2", []))

    def test_explicit_bundle_and_scope_take_precedence(self):
        identity = resolve_report_identity({
            "equipment_id": "AE-332",
            "bundle_code": "2",
            "scope_code": "FRONT",
        })
        self.assertEqual(identity.equipment_code, "E-332")
        self.assertEqual(identity.bundle_code, "2")
        self.assertEqual(identity.scope_code, "FRONT")

    def test_direction_suffix_is_stored_as_scope(self):
        north = resolve_report_identity({"equipment_id": "E-241B(NORTH)"})
        front = resolve_report_identity({"equipment_id": "E-201B + FRONT"})
        btm = resolve_report_identity({"equipment_id": "E-331A(BTM)"})
        spaced = resolve_report_identity({"equipment_id": "E-121A TOP"})
        self.assertEqual((north.equipment_code, north.scope_code), ("E-241B", "NORTH"))
        self.assertEqual((front.equipment_code, front.scope_code), ("E-201B", "FRONT"))
        self.assertEqual((btm.equipment_code, btm.scope_code), ("E-331A", "BTM"))
        self.assertEqual((spaced.equipment_code, spaced.scope_code), ("E-121A", "TOP"))

    def test_both_supported_report_detail_keys(self):
        legacy = {"iris_9000_report_details": {"inspection_reports": [1]}}
        current = {"iris_report_details": {"inspection_reports": [2]}}
        self.assertEqual(report_details(legacy)["inspection_reports"], [1])
        self.assertEqual(report_details(current)["inspection_reports"], [2])


if __name__ == "__main__":
    unittest.main()
