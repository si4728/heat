"""Multi-equipment scope authorization, latest-round selection and SQL bindings."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_service as service
from iris2.llm_integration import text_to_sql as sql
from iris2.llm_integration.tests.test_text_to_sql import SUMMARY
from iris2.tests.test_text_to_sql_web import TextToSqlWebTests


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [dict(heat_exchanger_id=1,unit_code='VCM1',equipment_tag='A'),
                        dict(heat_exchanger_id=2,unit_code='VCM2',equipment_tag='B'),
                        dict(heat_exchanger_id=3,unit_code='VCM1',equipment_tag='C')]
        self.rounds = {1:[dict(iris_inspection_id=10,effective_date='2026-01-01')],
                       2:[dict(iris_inspection_id=20,effective_date='2025-01-01')],3:[]}
        p=patch.object(service,'catalog',return_value=self.catalog);p.start();self.addCleanup(p.stop)
        p=patch.object(service,'inspections',side_effect=lambda hx:self.rounds[hx]);p.start();self.addCleanup(p.stop)

    def test_unit_selection_excludes_uninspected_and_deduplicates(self):
        scopes,excluded,allowed=service.select_scopes(unit_codes=['VCM1','VCM1'])
        self.assertEqual([s['equipment']['heat_exchanger_id'] for s in scopes],[1])
        self.assertEqual(excluded[0]['equipment']['heat_exchanger_id'],3)
        self.assertEqual(allowed,{1,2,3})
        scopes,_,_=service.select_scopes(exchanger_ids=[1,2,1])
        self.assertEqual([s['inspection']['iris_inspection_id'] for s in scopes],[10,20])

    def test_invalid_and_out_of_scope_requests(self):
        for kwargs in [dict(exchanger_ids=[]),dict(exchanger_ids=[True]),dict(unit_codes=['VCM3']),
                       dict(unit_codes=['VCM1'],exchanger_ids=[1]),
                       dict(exchanger_ids=[1,2],inspection_id=10),dict(exchanger_ids=[3])]:
            with self.subTest(kwargs=kwargs), self.assertRaises(sql.QueryRejected):service.select_scopes(**kwargs)
        with self.assertRaises(PermissionError):service.select_scopes(exchanger_ids=[1,999])

    def test_ambiguous_and_missing_date_fail_closed(self):
        self.rounds[1].append(dict(iris_inspection_id=11,effective_date='2026-01-01'))
        with self.assertRaises(sql.QueryRejected):service.select_scopes(exchanger_ids=[1])
        scopes,excluded,_=service.select_scopes(unit_codes=['VCM1','VCM2'])
        self.assertEqual([s['equipment']['heat_exchanger_id'] for s in scopes],[2])
        self.assertEqual(len(excluded),2)
        scopes,_,_=service.select_scopes(exchanger_ids=[1],inspection_id=11)
        self.assertEqual(scopes[0]['inspection']['iris_inspection_id'],11)
        self.rounds[1][0]['effective_date']=None
        with self.assertRaises(sql.QueryRejected):service.select_scopes(exchanger_ids=[1])

    @patch.object(sql.dbapi,'connect')
    def test_multiple_pairs_are_one_aggregate_query_with_bound_scope(self,connect):
        conn=connect.return_value
        conn.execute.return_value.fetchone.return_value={'unit_code':'VCM1','equipment_tag':'A'}
        conn.execute.return_value.fetchall.side_effect=[
            [('GRANT SELECT ON `iris2`.* TO reader',)],
            [dict(iris_inspection_id=10,effective_date='2026-01-01')],
            [dict(iris_inspection_id=20,effective_date='2025-01-01')]]
        conn.execute.return_value.description=[('inspected_tubes',)]
        conn.execute.return_value.fetchmany.return_value=[{'inspected_tubes':123}]
        result=sql.execute_proposal(SUMMARY,exchanger_id=1,authorized_exchanger_ids={1,2},scopes=[(1,10),(2,20)])
        executable,bindings=conn.execute.call_args.args
        self.assertEqual(bindings,(1,10,2,20))
        self.assertIn(' OR ',executable)
        self.assertEqual(len(result['scopes']),2)
        self.assertEqual(result['rows'],[{'inspected_tubes':123}])
        conn.close.assert_called_once()
        connect.reset_mock()
        with self.assertRaises(PermissionError):
            sql.execute_proposal(SUMMARY,exchanger_id=1,authorized_exchanger_ids={1},scopes=[(1,10),(2,20)])
        connect.assert_not_called()


class MultiScopeWebTests(TextToSqlWebTests):
    def test_multi_token_pins_inspection_ids_and_ignores_execute_scope(self):
        scopes=[dict(equipment=self.equipment,inspection=self.inspection),
                dict(equipment=dict(heat_exchanger_id=152,unit_code='VCM2'),inspection=dict(iris_inspection_id=390))]
        with patch.object(service,'select_scopes',return_value=(scopes,[],{151,152})):
            response=self.post('generate',dict(exchanger_ids=[151,152],question='검사 요약'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.json['scopes']),2)
        result=self.post('execute',dict(token=response.json['token'],exchanger_ids=[999]))
        self.assertEqual(result.status_code,200)
        self.assertEqual(self.execute.call_args.kwargs['scopes'],[[151,389],[152,390]])

    def test_bad_new_scope_never_calls_model(self):
        for scope in [dict(exchanger_ids=[]),dict(unit_codes=['VCM4']),dict(exchanger_ids=[999])]:
            response=self.post('generate',dict(question='검사 요약',**scope))
            self.assertIn(response.status_code,(400,403))
        self.worker.assert_not_called()
