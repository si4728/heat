import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from customer_clone import customer_clone
from iris2 import services


class ReviewFollowupsMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = customer_clone()
        cls.engine, cls.schema = cls.context.__enter__()
        cls.addClassCleanup(cls.context.__exit__, None, None, None)

    def test_ranking_uses_the_analysis_maximum_for_every_scoped_equipment(self):
        report = services.exchanger_wall_loss_ranking()
        self.assertTrue(report['rows'])
        self.assertEqual({r['unit_code'] for r in report['rows']}, {'PE', 'VCM1', 'VCM2'})
        for row in report['rows']:
            with self.subTest(identifier=row['heat_exchanger_id']):
                life = services.exchanger_detail(row['heat_exchanger_id'])['remaining_life']
                expected = max((t['wall_loss_percent'] for t in life['analysis_tube_rows']
                                if t['wall_loss_percent'] is not None), default=None)
                self.assertEqual(row['wall_loss_percent'], expected)
        e111 = next(r for r in report['rows'] if r['heat_exchanger_id'] == 100)
        self.assertAlmostEqual(e111['wall_loss_percent'], 27.44)
        self.assertNotEqual(e111['iris_inspection_id'], 87)
        self.assertEqual(services.exchanger_wall_loss_ranking(unit_code='VCM3')['rows'], [])
        self.assertTrue(all(r['unit_code'] == 'PE' for r in services.exchanger_wall_loss_ranking(unit_code='PE')['rows']))
        self.assertEqual(services.exchanger_wall_loss_ranking(search='E-111')['rows'][0]['heat_exchanger_id'], 100)


if __name__ == '__main__':
    unittest.main()
