import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as Obj
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.domain.current_measurements import select_current_measurements


class CurrentMeasurementTests(unittest.TestCase):
    def row(self, identifier, when, loss, **changes):
        result = Obj(tube_id=1, iris_tube_result_id=identifier, wall_loss_percent=loss,
                     quality_status=None, result_status='VALID')
        inspection = Obj(inspection_date=when, report_date=None, heat_exchanger_id=100,
                         original_equipment_id='E-111', source_scope_code='ALL', superseded_by_inspection_id=None)
        for field, value in changes.items():
            setattr(result if hasattr(result, field) else inspection, field, value)
        return result, inspection

    def select(self, rows, installed=None):
        return select_current_measurements(rows, {1: Obj(installed_at=installed)},
            Obj(install_date=None), as_of=date(2026, 11, 26))

    def test_latest_measurement_replaces_higher_historical_loss(self):
        rows = [self.row(1, date(2023, 1, 1), 80), self.row(2, date(2025, 1, 1), 20)]
        latest, eligible, old = self.select(rows)
        self.assertEqual(latest[1][0].wall_loss_percent, 20)
        self.assertEqual(len(eligible), 2)
        self.assertEqual(old, 0)
        self.assertEqual(self.select(list(reversed(rows)))[0][1][0].wall_loss_percent, 20)

    def test_partial_superseded_invalid_future_and_undated_are_excluded(self):
        rows = [self.row(1, date(2021, 1, 1), 90, source_scope_code='TOPSOUTH'),
                self.row(2, date(2025, 1, 1), 90, superseded_by_inspection_id=3),
                self.row(3, date(2025, 1, 1), 90, quality_status='INVALID'),
                self.row(4, date(2027, 1, 1), 90), self.row(5, None, 90),
                self.row(6, date(2025, 1, 1), 90, result_status='INVALID'),
                self.row(7, date(2025, 1, 1), 27.44)]
        latest, eligible, _ = self.select(rows)
        self.assertEqual(latest[1][0].wall_loss_percent, 27.44)
        self.assertEqual(len(eligible), 1)

    def test_installation_report_fallback_and_same_day_tie(self):
        rows = [self.row(1, date(2023, 1, 1), 99),
                self.row(2, None, 20, report_date=datetime(2025, 1, 1)),
                self.row(3, date(2025, 1, 1), 30), self.row(4, date(2025, 1, 1), 30)]
        latest, eligible, historical = self.select(rows, date(2024, 1, 1))
        self.assertEqual(latest[1][0].iris_tube_result_id, 4)
        self.assertEqual(historical, 1)
        self.assertEqual(len(eligible), 3)

    def test_latest_missing_loss_does_not_revive_an_old_measurement(self):
        latest, _, _ = self.select([self.row(1, date(2023, 1, 1), 80), self.row(2, date(2025, 1, 1), None)])
        self.assertIsNone(latest[1][0].wall_loss_percent)


if __name__ == '__main__':
    unittest.main()
