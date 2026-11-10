import unittest
from iris2.application.life_dashboard import life_band, group_life_rows


class LifeDashboardTests(unittest.TestCase):
    def test_band_boundaries_and_unknown(self):
        for years, expected in [(16, 'long'), (15, 'medium'), (6, 'medium'), (5, 'short'), (0, 'short'), (-2, 'short')]:
            with self.subTest(years=years):
                self.assertEqual(life_band(dict(status='CALCULATED', total_tube_count=100, remaining_life_years=years)), expected)
        for status, expected in [('LIMIT_NOT_REACHED','not_reached'), ('INSUFFICIENT_DATA','unknown')]:
            self.assertEqual(life_band(dict(status=status, total_tube_count=100, remaining_life_years=None)), expected)
        self.assertEqual(life_band(dict(status='CALCULATED', total_tube_count=0, remaining_life_years=2)), 'unknown')

    def test_counts_and_click_filter_use_same_records(self):
        rows = [dict(unit_code='VCM1', band='short'), dict(unit_code='VCM1', band='unknown'),
                dict(unit_code='VCM2', band='long'), dict(unit_code='VCM2', band='short')]
        report = group_life_rows(rows, 'VCM1', 'short')
        self.assertEqual(len(report['rows']), report['groups'][0]['counts']['short'])
        self.assertEqual(sum(report['totals'].values()), len(rows))
        self.assertEqual(report['totals']['unknown'], 1)
        self.assertEqual(len(group_life_rows(rows, '', 'short')['rows']), 2)
        self.assertEqual(len(group_life_rows(rows, 'invalid', 'invalid')['rows']), 4)
