"""Real MariaDB and application-shell checks; authenticated requests, no writes."""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from iris2 import services
from iris2.app import create_app
from iris2.database import get_engine
from iris2.llm_integration.tests.test_text_to_sql import SUMMARY


class TextToSqlMariaDBTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
        with get_engine().connect() as connection:
            cls.uid=connection.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
        assert cls.uid, 'Active administrator required'
        cls.profile=services.user_access_profile(cls.uid)

    def client(self):
        client=self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=self.uid,last_activity_at=time.time(),csrf_token='integration-csrf')
        return client

    def test_viewer_permission_renders_menu_and_executes_real_read(self):
        profile=dict(self.profile,is_admin=False,permissions={
            key:{'can_view':True,'can_edit':False} for key in ('TEXT_TO_SQL','INSPECTIONS')})
        with patch('iris2.services.user_access_profile',return_value=profile), patch(
                'iris2.web.routes.text_to_sql.analysis.generate_in_worker',return_value=SUMMARY):
            client=self.client()
            page=client.get('/inspections/text-to-sql')
            self.assertEqual(page.status_code,200)
            # The common LLM shortcut is administrator-only; existing explicit
            # Text-to-SQL read permissions still authorize this direct endpoint.
            self.assertNotIn('llm-shortcut',page.get_data(as_text=True))
            generated=client.post('/inspections/text-to-sql/generate',json={
                'exchanger_id':151,'inspection_id':389,'question':'검사 결과 요약'},
                headers={'X-CSRF-Token':'integration-csrf'})
            self.assertEqual(generated.status_code,200)
            response=client.post('/inspections/text-to-sql/execute',json={'token':generated.json['token']},
                headers={'X-CSRF-Token':'integration-csrf'})
            self.assertEqual(response.status_code,200)
            row=response.json['result']['rows'][0]
            self.assertEqual(row['inspected_tubes'],82)
            self.assertAlmostEqual(row['minimum_mm'],0.12)
            self.assertIn('minimum_mm',response.json['result']['columns'])

    def test_missing_feature_permission_hides_menu_and_denies_direct_access(self):
        profile=dict(self.profile,is_admin=False,permissions={
            'INSPECTIONS':{'can_view':True,'can_edit':False}})
        with patch('iris2.services.user_access_profile',return_value=profile):
            response=self.client().get('/inspections/text-to-sql')
            self.assertEqual(response.status_code,403)
            self.assertNotIn('href="/inspections/text-to-sql"',response.get_data(as_text=True))

    def test_invalid_equipment_or_inspection_never_calls_model(self):
        with patch('iris2.web.routes.text_to_sql.analysis.generate_in_worker') as model:
            client=self.client()
            for exchanger,inspection in ((999999999,389),(151,999999999)):
                response=client.post('/inspections/text-to-sql/generate',json={
                    'exchanger_id':exchanger,'inspection_id':inspection,'question':'검사 요약'},
                    headers={'X-CSRF-Token':'integration-csrf'})
                self.assertIn(response.status_code,(400,403))
            model.assert_not_called()

    def test_process_and_multiple_equipment_aggregate_match_source_counts(self):
        from iris2.application import text_to_sql_service as analysis
        from iris2.llm_integration.text_to_sql import execute_proposal
        scopes, excluded, allowed = analysis.select_scopes(unit_codes=['VCM1','VCM2'])
        self.assertGreater(len(scopes),1)
        pairs=[(s['equipment']['heat_exchanger_id'],s['inspection']['iris_inspection_id']) for s in scopes]
        with get_engine().connect() as conn:
            expected=sum(conn.scalar(text('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=:id'),
                                     {'id':inspection}) for _,inspection in pairs)
        result=execute_proposal(SUMMARY,exchanger_id=pairs[0][0],scopes=pairs,authorized_exchanger_ids=allowed)
        self.assertEqual(result['rows'][0]['inspected_tubes'],expected)
        self.assertEqual(len(result['scopes']),len(pairs))
        selected=[s['equipment']['heat_exchanger_id'] for s in scopes[:2]]
        with patch.object(analysis,'generate_in_worker',return_value=SUMMARY):
            for scope in (dict(exchanger_ids=selected),dict(unit_codes=['VCM1'])):
                preview=self.client().post('/inspections/text-to-sql/generate',json=dict(question='검사 요약',**scope),
                    headers={'X-CSRF-Token':'integration-csrf'})
                self.assertEqual(preview.status_code,200,preview.json)
                executed=self.client().post('/inspections/text-to-sql/execute',json={'token':preview.json['token']},
                    headers={'X-CSRF-Token':'integration-csrf'})
                self.assertEqual(executed.status_code,200,executed.json)

    def test_inspection_frequency_question_matches_real_history(self):
        from iris2.application import inspection_frequency as frequency
        question='최근 iris 검사를 제일 많이 수행한 열교환기를 리스트해줘'
        client=self.client()
        with patch('iris2.application.text_to_sql_service.generate_in_worker') as worker:
            preview=client.post('/inspections/text-to-sql/generate',json=dict(question=question,unit_codes=['VCM1','VCM2']),
                headers={'X-CSRF-Token':'integration-csrf'})
            self.assertEqual(preview.status_code,200,preview.json)
            worker.assert_not_called()
        result=client.post('/inspections/text-to-sql/execute',json={'token':preview.json['token']},
            headers={'X-CSRF-Token':'integration-csrf'})
        self.assertEqual(result.status_code,200,result.json)
        period=preview.json['period']
        with get_engine().connect() as conn:
            history=conn.execute(text('''SELECT i.iris_inspection_id,i.heat_exchanger_id,
                COALESCE(i.inspection_date,i.report_date) AS effective_date
                FROM iris_inspection i JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
                JOIN equipment e ON e.equipment_id=h.equipment_id
                JOIN process_unit u ON u.unit_id=e.unit_id
                WHERE u.unit_code IN ('VCM1','VCM2') AND i.superseded_by_inspection_id IS NULL
                AND UPPER(TRIM(i.inspection_method))='IRIS' ''')).mappings().all()
        from collections import defaultdict
        groups=defaultdict(list)
        for row in history:
            day=str(row['effective_date'])[:10]
            if row['effective_date'] and period['start']<=day<=period['end']:
                groups[row['heat_exchanger_id']].append((row['iris_inspection_id'],day))
        expected=sorted(groups,key=lambda hx:(-len(set(i for i,_ in groups[hx])),
                            -int(max(day for _,day in groups[hx]).replace('-','')),hx))[:period['limit']]
        rows=result.json['result']['rows']
        self.assertEqual([r['heat_exchanger_id'] for r in rows],expected)
        for row in rows:
            self.assertEqual(row['inspection_count'],len(set(i for i,_ in groups[row['heat_exchanger_id']])))


if __name__=='__main__':
    unittest.main()
