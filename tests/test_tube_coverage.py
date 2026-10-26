import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.services import _registered_tube_coverage


class RegisteredTubeCoverageTests(unittest.TestCase):
    def tube(self, **overrides):
        return dict(tube_no='1-1', current_status='IN_SERVICE', grid_position_present=1,
                    spatial_position_present=1, valid_pass_no=1, installed_at='2000-01-01',
                    inspection_result_present=1, measured_thickness_present=1) | overrides

    def test_six_groups_cover_seven_slots(self):
        report = _registered_tube_coverage([self.tube()])
        self.assertEqual(len(report['groups']), 6)
        self.assertEqual(report['possible_count'], 7)
        self.assertEqual(report['rate'], 100)
        self.assertEqual(report['complete_count'], 1)

    def test_pass_gap_is_excluded_but_measurement_gap_counts(self):
        report = _registered_tube_coverage([self.tube(valid_pass_no=None, measured_thickness_present=None)])
        self.assertEqual(report['rate'], 85.7)
        self.assertEqual(report['complete_count'], 0)
        self.assertEqual(report['groups'][3]['rate'], 100)
        self.assertEqual(report['groups'][5]['rate'], 0)
        without_pass = _registered_tube_coverage([self.tube(valid_pass_no=None)])
        self.assertEqual(without_pass['rate'], 100)
        self.assertEqual(without_pass['complete_count'], 1)

    def test_quality_flags_do_not_claim_validity_or_inflate_field_slots(self):
        report = _registered_tube_coverage([self.tube(inspection_before_installation=1), self.tube()])
        self.assertEqual(report['historical_only_tubes'], 1)
        self.assertNotIn('inspection_before_installation', report['quality'])
        self.assertEqual(report['possible_count'], 14)
        self.assertEqual(report['total_count'], 2)

    def test_missing_number_and_status_count_separately(self):
        report = _registered_tube_coverage([self.tube(tube_no=' ', current_status=None)])
        self.assertEqual(report['groups'][0]['rate'], 0)
        self.assertEqual(report['groups'][0]['complete_count'], 0)

    def test_empty_population(self):
        report = _registered_tube_coverage([])
        self.assertEqual(report['rate'], 0)
        self.assertEqual(report['possible_count'], 0)
        self.assertTrue(all(group['rate'] == 0 for group in report['groups']))


if __name__ == '__main__':
    unittest.main()
