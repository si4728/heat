from __future__ import annotations

import unittest

from iris2.llm_integration.natural_query import parse_query


class NaturalLanguageQueryTest(unittest.TestCase):
    def test_wall_loss_threshold_is_parsed(self):
        parsed = parse_query("감육률 30% 이상 교환기")
        self.assertEqual(parsed["filters"]["wall_loss_percent"], 30.0)
        self.assertEqual(parsed["filters"]["comparison"], "이상")

    def test_equipment_code_and_recent_sort_are_parsed(self):
        parsed = parse_query("1104421 최근 검사")
        self.assertEqual(parsed["filters"]["equipment_code"], "1104421")
        self.assertTrue(parsed["filters"]["latest_first"])

    def test_never_inspected_is_parsed(self):
        self.assertTrue(parse_query("검사 없는 교환기")["filters"]["never_inspected"])

    def test_out_of_range_wall_loss_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_query("감육률 101% 이상")


if __name__ == "__main__":
    unittest.main()
