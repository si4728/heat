"""Read-only classification queries on a disposable copy; source names stay intact."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from customer_clone import customer_clone
from iris2.application import text_to_sql_fluids as fluids, text_to_sql_service as service


class SteamClassificationMariaDBTests(unittest.TestCase):
    def test_alias_filter_and_grouping_share_the_same_classification(self):
        with customer_clone() as (engine, schema):
            ids = [r['heat_exchanger_id'] for r in service.catalog()]

            def query(question):
                settings = fluids.options(question)
                return fluids.execute(ids, settings, fluids.proposal(ids, settings), ids)['rows']

            with engine.connect() as c:
                before = list(c.execute(text('SELECT spec_revision_id,shell_fluid,tube_fluid FROM heat_exchanger_spec_revision ORDER BY spec_revision_id')))
            plain = query('유체명이 STEAM인 열교환기 목록')
            alias = query('유체명이 S:STEAM인 열교환기 목록')
            self.assertEqual(plain, alias)
            self.assertEqual({r['side_code']: r['exchanger_count'] for r in plain}, {'SHELL': 37, 'TUBE': 2})
            grouping = query('공정별 유체명별 열교환기 목록')
            self.assertFalse(any(r['fluid_name'] == 'S:STEAM' for r in grouping))
            vcm1 = next(r for r in grouping if r['unit_code'] == 'VCM1' and r['side_code'] == 'SHELL' and r['fluid_name'] == 'STEAM')
            self.assertEqual(vcm1['exchanger_count'], 22)
            self.assertTrue(all(sum(r['exchanger_count'] for r in grouping if r['unit_code'] == unit and r['side_code'] == side) == total
                for unit, total in (('PE', 191), ('VCM1', 81), ('VCM2', 131)) for side in ('SHELL', 'TUBE')))
            for name, count in (('HP STEAM', 10), ('H.P. STEAM', 1), ('MEDIUM STEAM', 3), ('LOW STEAM', 1), ('STEAM CONDENSATE', 1)):
                self.assertEqual(sum(r['exchanger_count'] for r in query(f'유체명이 {name}인 열교환기 목록')), count)
            with engine.connect() as c:
                after = list(c.execute(text('SELECT spec_revision_id,shell_fluid,tube_fluid FROM heat_exchanger_spec_revision ORDER BY spec_revision_id')))
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
