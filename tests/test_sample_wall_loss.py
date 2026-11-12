import json
import math
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.domain.sample_wall_loss import estimate_sample_wall_loss
from iris2.application.sample_wall_loss import build_sample_estimate
from jinja2 import Environment, FileSystemLoader


class SampleWallLossTests(unittest.TestCase):
    def calculate(self, values=None, **kwargs):
        return estimate_sample_wall_loss(values if values is not None else range(10, 20),
            **(dict(total_tube_count=52, installation_date='2013-10-31',
                    measurement_date='2023-11-10') | kwargs))

    def test_figure_5_e104b_measured_input_reproduces_values_and_years(self):
        result = self.calculate([9.48, 13.27, 13.27, 13.27, 17.06, 20.38, 21.33, 22.75, 22.75, 23.22])
        self.assertEqual(result['status'], 'ESTIMATED')
        self.assertAlmostEqual(result['beta'], 4.12, delta=.01)
        self.assertAlmostEqual(result['mu'], 15.53, delta=.01)
        self.assertAlmostEqual(result['estimated_max_wall_loss_percent'], 31.7, delta=.1)
        self.assertAlmostEqual(result['upper_20_wall_loss_percent'], 21.7, delta=.1)
        self.assertEqual(result['measured_max_threshold']['year'], 2031)
        self.assertEqual(result['first_threshold']['year'], 2026)
        self.assertEqual(result['twenty_percent_threshold']['year'], 2032)

    def test_recovers_independently_constructed_line(self):
        values = [20 + 3 * -math.log(-math.log((i - .3) / 10.4)) for i in range(1, 11)]
        result = self.calculate(list(reversed(values)))
        self.assertAlmostEqual(result['mu'], 20)
        self.assertAlmostEqual(result['beta'], 3)
        self.assertAlmostEqual(result['r_squared'], 1)
        self.assertAlmostEqual(result['estimated_max_wall_loss_percent'],
                               20 + 3 * -math.log(-math.log(51 / 52)))
        self.assertAlmostEqual(result['upper_20_wall_loss_percent'],
                               20 + 3 * -math.log(-math.log(.8)))

    def test_minimum_sample_boundary_and_invalid_values(self):
        for count in [1, 9]:
            r = self.calculate(range(count))
            self.assertEqual(r['status'], 'SAMPLE_INSUFFICIENT')
            self.assertIsNone(r['estimated_max_wall_loss_percent'])
            self.assertEqual(r['measured_max_wall_loss_percent'], count - 1)
        r = self.calculate([None, True, float('nan'), float('inf'), -1, 101] + list(range(9)))
        self.assertEqual(r['sample_count'], 9)
        self.assertEqual(r['status'], 'SAMPLE_INSUFFICIENT')
        self.assertEqual(self.calculate(range(10))['status'], 'ESTIMATED')
        self.assertEqual(self.calculate([])['status'], 'NO_VALID_SAMPLE')

    def test_invalid_population_and_constant_sample(self):
        for count in [None, 0, 9, True, 52.0]:
            self.assertEqual(self.calculate(total_tube_count=count)['status'], 'INVALID_TOTAL_COUNT')
        self.assertEqual(self.calculate([20] * 10)['status'], 'DEGENERATE_SAMPLE')
        self.assertEqual(self.calculate([i * 1e-200 for i in range(10)])['status'], 'DEGENERATE_SAMPLE')

    def test_loss_cap_and_measured_maximum_floor(self):
        r = self.calculate(range(0, 100, 10), total_tube_count=100000)
        self.assertEqual(r['estimated_max_wall_loss_percent'], 100)
        self.assertTrue(r['maximum_capped'])
        self.assertEqual(r['first_threshold']['status'], 'ESTIMATED_REACHED')
        self.assertIsNone(r['first_threshold']['date'])
        r = self.calculate([1] * 9 + [99], total_tube_count=10)
        self.assertGreaterEqual(r['estimated_max_wall_loss_percent'], 99)

    def test_invalid_age_keeps_fit_but_does_not_invent_year(self):
        for installed in [None, '2024-01-01', '2023-11-10']:
            r = self.calculate(installation_date=installed)
            self.assertEqual(r['status'], 'ESTIMATED')
            self.assertEqual(r['first_threshold']['status'], 'INVALID_INSTALLATION_DATE')
            self.assertIsNone(r['first_threshold']['year'])

    def test_dates_are_anchored_to_inspection_and_serialization_is_finite(self):
        r = self.calculate()
        self.assertGreater(r['first_threshold']['date'], '2023-11-10')
        json.dumps(r, allow_nan=False)

    def test_estimated_reached_is_not_presented_as_measured_reached(self):
        r = self.calculate(range(30, 40), total_tube_count=100000)
        self.assertLess(r['measured_max_wall_loss_percent'], 40)
        self.assertEqual(r['first_threshold']['status'], 'ESTIMATED_REACHED')
        self.assertEqual(r['measured_max_threshold']['status'], 'FORECAST')


class SampleCohortTests(unittest.TestCase):
    def cohort(self, number=1, measured=datetime(2023, 11, 10), losses=range(10, 20), **extra):
        inspection = SimpleNamespace(iris_inspection_id=number, inspection_date=measured,
            report_date=measured, superseded_by_inspection_id=None, report_number='report',
            installation_or_replacement_date=None, installation_or_replacement_year=None,
            installation_or_replacement_date_precision=None, total_tube_count_reported=52)
        for key, value in extra.items():
            setattr(inspection, key, value)
        return [(SimpleNamespace(tube_id=i, wall_loss_percent=value, result_status='VALID', quality_status='VALID'), inspection)
                for i, value in enumerate(losses, 1)]

    def build(self, rows, **overrides):
        tubes = {i: SimpleNamespace(installed_at=datetime(2013, 10, 31)) for i in range(1, 11)}
        inputs = dict(result_rows=rows, tubes_by_id=tubes,
            equipment=SimpleNamespace(install_date=datetime(2013, 10, 31)),
            master_spec=SimpleNamespace(tube_count=52), threshold_percent=40)
        return build_sample_estimate(**(inputs | overrides))

    def test_latest_single_cohort_without_pooling_old_measurements(self):
        rows = self.cohort(losses=[90] * 10) + self.cohort(2, datetime(2025, 1, 1), range(10, 20))
        r = self.build(rows)
        self.assertEqual(r['sample_count'], 10)
        self.assertEqual(r['inspection_id'], 2)
        self.assertEqual(r['measured_max_wall_loss_percent'], 19)

    def test_newest_report_without_valid_measurements_does_not_reuse_old_sample(self):
        old = self.cohort()
        new_inspection = self.cohort(2, datetime(2025, 1, 1))[0][1]
        r = self.build(old, inspections=[old[0][1], new_inspection])
        self.assertEqual(r['inspection_id'], 2)
        self.assertEqual(r['status'], 'NO_VALID_SAMPLE')
        self.assertIsNone(r['estimated_max_wall_loss_percent'])

    def test_superseded_invalid_and_replacement_history_excluded(self):
        rows = self.cohort() + self.cohort(2, datetime(2025, 1, 1), [90] * 10, superseded_by_inspection_id=3)
        self.assertEqual(self.build(rows)['inspection_id'], 1)
        rows = self.cohort()
        rows[0][0].quality_status = 'NOT_IN_LATEST_JSON'
        self.assertEqual(self.build(rows)['status'], 'SAMPLE_INSUFFICIENT')
        self.assertEqual(self.build(self.cohort(measured=datetime(2010, 1, 1)))['status'], 'NO_VALID_SAMPLE')

    def test_same_date_reports_and_mixed_installation_are_not_pooled(self):
        self.assertEqual(self.build(self.cohort() + self.cohort(2))['status'], 'AMBIGUOUS_INSPECTION')
        r = self.build(self.cohort(losses=range(5)) + self.cohort(2, losses=range(5)))
        self.assertEqual(r['status'], 'SAMPLE_INSUFFICIENT')
        self.assertEqual(r['cohort_issue'], 'AMBIGUOUS_INSPECTION')
        tubes = {i: SimpleNamespace(installed_at=date(2015 if i == 1 else 2013, 1, 1)) for i in range(1, 11)}
        r = self.build(self.cohort(), tubes_by_id=tubes)
        self.assertEqual(r['status'], 'MIXED_INSTALLATION_DATES')
        self.assertIsNone(r['estimated_max_wall_loss_percent'])

    def test_population_source_and_mismatch_are_explicit(self):
        r = self.build(self.cohort(total_tube_count_reported=26))
        self.assertEqual(r['total_tube_count'], 52)
        self.assertTrue(r['population_count_mismatch'])

    def test_year_only_installation_uses_july_and_is_marked(self):
        r = self.build(self.cohort(installation_or_replacement_year=2020,
                                  installation_or_replacement_date_precision='YEAR'))
        self.assertEqual(r['installation_date'], '2020-07-01')
        self.assertEqual(r['installation_precision'], 'YEAR')

    def test_template_shows_both_values_and_sample_shortfall(self):
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates'), autoescape=True)
        template = env.get_template('sample_wall_loss_estimate.html')
        for losses in [range(10, 20), range(9), []]:
            estimate = self.build(self.cohort(losses=losses))
            html = template.render(life={'sample_wall_loss_estimate': estimate})
            self.assertIn('실제 측정 최대 감육률', html)
            self.assertIn('전체 튜브 추정 최대 감육률', html)
            if 0 < len(losses) < 10:
                self.assertIn('표본 부족', html)
        estimate = self.build(self.cohort())
        estimate['report_number'] = '<script>alert(1)</script>'
        self.assertNotIn('<script>', template.render(life={'sample_wall_loss_estimate': estimate}))
