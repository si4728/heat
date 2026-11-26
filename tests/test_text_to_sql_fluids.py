import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_fluids as fluids
from iris2.llm_integration.text_to_sql import QueryRejected


class FluidGroupingTests(unittest.TestCase):
    def test_default_and_explicit_sides_and_unit_grouping(self):
        self.assertEqual(fluids.options('유체명별 교환기 목록')['sides'], ['SHELL','TUBE'])
        self.assertEqual(fluids.options('공정별 Shell 유체명별 목록'), dict(sides=['SHELL'], by_unit=True, fluid=None))
        self.assertEqual(fluids.options('Tube 유체별 목록')['sides'], ['TUBE'])
        self.assertEqual(fluids.options('헤드 유체별 목록')['sides'], ['HEAD'])

    def test_exact_fluid_filter_is_bound_as_parameter(self):
        settings = fluids.options('Shell 유체명이 steam인 열교환기 목록')
        self.assertEqual(settings['fluid'], 'STEAM')
        proposal = fluids.proposal([1,2],settings)
        self.assertIn('WHERE fluid_name=?', proposal['sql'])
        self.assertEqual(proposal['parameters'], [1,2,'STEAM'])
        self.assertIn('COUNT(DISTINCT heat_exchanger_id)', proposal['sql'])

    def test_authorized_steam_alias_is_used_in_filters_without_merging_other_fluids(self):
        for name in ('STEAM', 'S:STEAM', ' s:steam '):
            with self.subTest(name=name):
                self.assertEqual(fluids.normalized_fluid(name), 'STEAM')
                self.assertEqual(fluids.options(f'유체명이 {name}인 열교환기 목록')['fluid'], 'STEAM')
        for name in ('HP STEAM', 'H.P. STEAM', 'LOW STEAM', 'MEDIUM STEAM', 'STEAM CONDENSATE', 'S:WATER', 'T:STEAM'):
            with self.subTest(name=name):
                self.assertEqual(fluids.normalized_fluid(name), name)
                settings = fluids.options(f'유체명이 {name}인 열교환기 목록')
                self.assertEqual(settings['fluid'], name)
                self.assertEqual(fluids.proposal([1], settings)['parameters'][-1], name)

    def test_unsupported_analyses_are_not_silently_ignored(self):
        for question in ['2025년 유체별 목록', '유체별 감육률', '최근 유체별 교환기', '유체별 운전압력']:
            with self.subTest(question=question), self.assertRaises(QueryRejected):
                fluids.options(question)

    def test_scope_and_named_equipment_intersect(self):
        catalog = [dict(heat_exchanger_id=1, unit_code='VCM1', equipment_tag='US-VC-E-111'),
                   dict(heat_exchanger_id=2, unit_code='VCM2', equipment_tag='US-EV-E-111A')]
        with patch.object(fluids.analysis, 'catalog', return_value=catalog):
            self.assertEqual(fluids.select_equipment({}, 'E-111 유체명별'), catalog[:1])
            self.assertEqual(fluids.select_equipment({}, 'VCM2 유체명별'), catalog[1:])
            for data,question in [(dict(unit_codes=['VCM2']),'E-111 유체별'),
                    (dict(exchanger_ids=[True]),'유체별'), ({},'VCM3 유체별'), ({},'E-999 유체별')]:
                with self.subTest(data=data,question=question), self.assertRaises(QueryRejected):
                    fluids.select_equipment(data,question)
            with self.assertRaises(PermissionError):
                fluids.select_equipment(dict(exchanger_ids=[999]), '유체별')

    def test_tampered_proposal_and_revoked_scope_never_connect(self):
        settings = fluids.options('유체별')
        proposal = fluids.proposal([1], settings)
        with patch.object(fluids.dbapi, 'connect') as connect:
            with self.assertRaises(QueryRejected):
                fluids.execute([1], settings, dict(sql='DELETE FROM equipment',parameters=[]), {1})
            with self.assertRaises(PermissionError):
                fluids.execute([1], settings, proposal, set())
            connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
