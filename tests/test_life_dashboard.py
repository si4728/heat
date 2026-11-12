import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application.life_dashboard import life_band, group_life_rows, first_tube_threshold, forecast_display, annual_team_rows
from datetime import date


class LifeDashboardTests(unittest.TestCase):
    def projection(self, tube_id, forecast_date, **extra):
        return dict(basis='CALCULATED', tube_id=tube_id, tube_no=str(tube_id),
                    measurement_date='2025-10-29', plugging_date=forecast_date, **extra)

    def test_first_tube_uses_date_instead_of_input_order_or_allowable_count(self):
        rows = [self.projection(1, '2046-01-01'), self.projection(2, '2032-12-01'),
                self.projection(3, '2032-02-01')]
        self.assertEqual(first_tube_threshold(rows)['tube_id'], 3)
        self.assertEqual(first_tube_threshold(rows)['date'], '2032-02-01')
        self.assertEqual(first_tube_threshold(rows)['status'], 'FORECAST')

    def test_first_tube_excludes_actual_plugging_and_invalid_or_unmeasured_rows(self):
        rows = [dict(self.projection(1, '2020-01-01'), basis='ALREADY_PLUGGED'),
                self.projection(2, 'invalid'),
                dict(self.projection(3, '2021-01-01'), measurement_date=None),
                self.projection(4, '2032-01-01')]
        self.assertEqual(first_tube_threshold(rows)['tube_id'], 4)
        self.assertIsNone(first_tube_threshold(rows[:3]))
        self.assertIsNone(first_tube_threshold([]))

    def test_measured_reached_does_not_claim_unknown_first_crossing_date(self):
        rows = [self.projection(1, '2032-01-01'),
                self.projection(2, '2026-11-12', plugging_threshold_reached=True)]
        first = first_tube_threshold(rows)
        self.assertEqual(first['tube_id'], 2)
        self.assertEqual(first['status'], 'MEASURED_REACHED')
        self.assertIsNone(first['date'])
        self.assertEqual(first['measurement_date'], '2025-10-29')

    def test_same_date_selection_is_stable_and_does_not_change_input(self):
        rows = [self.projection(2, '2032-01-01'), self.projection(1, '2032-01-01')]
        self.assertEqual(first_tube_threshold(rows)['tube_id'], 1)
        self.assertNotIn('_sort_date', rows[0])

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
        self.assertEqual(len(report['rows']), 1)
        self.assertEqual(report['groups'][0]['counts']['short'], 2)
        self.assertEqual(report['groups'][0]['label'], 'VCM 생산팀')
        self.assertEqual(len(report['groups']), 1)
        self.assertEqual(sum(report['totals'].values()), len(rows))
        self.assertEqual(report['totals']['unknown'], 1)
        self.assertEqual(len(group_life_rows(rows, '', 'short')['rows']), 2)
        self.assertEqual(len(group_life_rows(rows, 'invalid', 'invalid')['rows']), 4)

    def test_strict_thirty_year_display_boundary_does_not_mutate_forecast(self):
        for when, expected in [('2056-11-11','2056-11-11'),('2056-11-12','2056-11-12'),
                               ('2056-11-13','30년 이상'),('2100-01-01','30년 이상')]:
            first=dict(status='FORECAST',date=when)
            self.assertEqual(forecast_display(first,date(2026,11,12)),expected)
            self.assertEqual(first['date'],when)
        self.assertIsNone(forecast_display(dict(status='FORECAST',date='invalid'),date(2026,11,12)))
        self.assertIsNone(forecast_display(dict(status='MEASURED_REACHED'),date(2026,11,12)))
        self.assertEqual(forecast_display(dict(status='FORECAST',date='2054-03-01'),date(2024,2,29)),'30년 이상')

    def test_annual_team_totals_keep_process_sources(self):
        rows=[('VCM1',2025,3,2,10,True),('VCM2',2025,4,3,20,False),('VCM1',2024,1,1,0,False)]
        result=annual_team_rows(rows)
        self.assertEqual([r['year'] for r in result],[2025,2024])
        self.assertEqual(result[0]['inspection_count'],7)
        self.assertEqual(result[0]['result_count'],30)
        self.assertEqual([p['unit'] for p in result[0]['processes']],['VCM1','VCM2'])
        self.assertTrue(result[0]['processes'][0]['pdf_available'])
