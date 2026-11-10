from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.web.security import register_security
from iris2.web.routes import text_to_sql as routes
from iris2.application import text_to_sql_service as service
from iris2.llm_integration.tests.test_text_to_sql import SUMMARY
from iris2.llm_integration.text_to_sql import QueryRejected


class TextToSqlWebTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SECRET_KEY='test-only', AUTH_DISABLED=False,
            SESSION_IDLE_TIMEOUT_SECONDS=1800, CSRF_ENABLED=True, TESTING=True)
        register_security(self.app)
        self.app.register_error_handler(403, lambda exc: ('Forbidden', 403))
        routes.register_routes(self.app)
        self.profile = dict(user_id=1, username='reader', is_admin=False, is_active=True,
            permissions={key:dict(can_view=True,can_edit=False) for key in ('TEXT_TO_SQL','INSPECTIONS')})
        self.equipment = dict(heat_exchanger_id=151, unit_code='VCM2',equipment_tag='E-106')
        self.inspection = dict(iris_inspection_id=389,effective_date='2025-11-05',report_number='IRIS')
        self.start_patch('iris2.services.user_count',return_value=1)
        self.access = self.start_patch('iris2.services.user_access_profile',side_effect=lambda uid: dict(self.profile,user_id=uid) if uid else None)
        self.catalog = self.start_patch('iris2.web.routes.text_to_sql.analysis.catalog',return_value=[self.equipment])
        self.rounds = self.start_patch('iris2.web.routes.text_to_sql.analysis.inspections',return_value=[self.inspection])
        self.scope = self.start_patch('iris2.web.routes.text_to_sql.analysis.select_scope',return_value=(self.equipment,self.inspection,frozenset({151})))
        self.worker = self.start_patch('iris2.web.routes.text_to_sql.analysis.generate_in_worker',return_value=SUMMARY)
        self.execute = self.start_patch('iris2.web.routes.text_to_sql.execute_proposal',return_value={
            'columns':['inspected_tubes'], 'rows':[{'inspected_tubes':82}], 'result_count':1, 'query_sha256':'abc'})
        self.render = self.start_patch('iris2.web.routes.text_to_sql.render_template',return_value='Text-to-SQL page')
        self.client = self.make_client()

    def start_patch(self,*args,**kwargs):
        p=patch(*args,**kwargs);self.addCleanup(p.stop);return p.start()

    def make_client(self,uid=1):
        client=self.app.test_client()
        with client.session_transaction() as s:
            s.update(user_id=uid,last_activity_at=time.time(),csrf_token='csrf')
        return client

    def post(self,action,data,client=None):
        return (client or self.client).post('/inspections/text-to-sql/'+action,
            json=data,headers={'X-CSRF-Token':'csrf'})

    def generate(self):
        return self.post('generate',dict(exchanger_id=151,inspection_id=389,question='검사 결과 요약'))

    def test_read_only_permission_can_generate_and_execute(self):
        page=self.client.get('/inspections/text-to-sql')
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.headers['Cache-Control'],'no-store')
        preview=self.generate()
        self.assertEqual(preview.status_code,200)
        self.execute.assert_not_called()
        self.assertIn('COUNT(*)',preview.json['proposal']['sql'])
        result=self.post('execute',{'token':preview.json['token'],'sql':'DELETE FROM equipment'})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['result']['rows'],[{'inspected_tubes':82}])
        self.assertNotIn('DELETE',self.execute.call_args.args[0]['sql'])
        self.assertEqual(self.execute.call_args.kwargs['authorized_exchanger_ids'],frozenset({151}))

    def test_anonymous_and_missing_permissions_do_not_reach_database(self):
        anonymous=self.app.test_client()
        self.assertEqual(anonymous.get('/inspections/text-to-sql').status_code,302)
        self.profile['permissions'].pop('TEXT_TO_SQL')
        self.assertEqual(self.client.get('/inspections/text-to-sql').status_code,403)
        self.assertEqual(self.generate().status_code,403)
        self.catalog.assert_not_called();self.worker.assert_not_called()

    def test_inspection_permission_is_required_and_auth_disabled_is_closed(self):
        self.profile['permissions'].pop('INSPECTIONS')
        self.assertEqual(self.generate().status_code,403)
        self.app.config['AUTH_DISABLED']=True
        self.assertEqual(self.client.get('/inspections/text-to-sql').status_code,403)

    def test_csrf_required_for_both_posts(self):
        for action in ('generate','execute'):
            response=self.client.post('/inspections/text-to-sql/'+action,json={})
            self.assertEqual(response.status_code,400)
        self.worker.assert_not_called();self.execute.assert_not_called()

    def test_forged_expired_and_other_user_tokens_rejected(self):
        token=self.generate().json['token']
        self.assertEqual(self.post('execute',{'token':token+'x'}).status_code,400)
        self.assertEqual(self.post('execute',{'token':token},self.make_client(2)).status_code,403)
        from itsdangerous import URLSafeTimedSerializer
        signing=URLSafeTimedSerializer(self.app.secret_key,salt='iris2-text-to-sql-v1')
        payload=signing.loads(token)
        with patch('itsdangerous.timed.TimestampSigner.get_timestamp',return_value=1):
            expired=signing.dumps(payload)
        self.assertEqual(self.post('execute',{'token':expired}).status_code,400)
        self.execute.assert_not_called()

    def test_execution_rechecks_current_scope(self):
        token=self.generate().json['token']
        self.scope.side_effect=PermissionError('범위 제외')
        self.assertEqual(self.post('execute',{'token':token}).status_code,403)
        self.execute.assert_not_called()

    def test_bad_model_sql_never_produces_execution_token(self):
        self.worker.return_value={'sql':'DELETE FROM equipment','parameters':[]}
        response=self.generate()
        self.assertEqual(response.status_code,400)
        self.assertNotIn('token',response.json)
        self.execute.assert_not_called()

    def test_errors_hide_raw_database_details(self):
        self.scope.side_effect=RuntimeError('password=secret internal server')
        response=self.generate()
        self.assertEqual(response.status_code,503)
        self.assertNotIn('secret',response.get_data(as_text=True))

    def test_scope_and_request_validation(self):
        self.assertEqual(self.post('generate',{'question':'x','exchanger_id':'151'}).status_code,400)
        self.assertEqual(self.post('generate',{'question':'x'*501,'exchanger_id':151}).status_code,400)
        self.assertEqual(self.client.get('/inspections/text-to-sql/inspections?exchanger_id=999').status_code,403)
        self.assertEqual(self.client.get('/inspections/text-to-sql/inspections?exchanger_id=151').status_code,200)

    def test_only_one_inference_process_at_a_time(self):
        entered,released=threading.Event(),threading.Event()
        def wait_worker(question):
            entered.set();released.wait(5);return SUMMARY
        self.worker.side_effect=wait_worker
        responses=[]
        first_client=self.make_client()
        thread=threading.Thread(target=lambda:responses.append(self.post('generate',
            dict(exchanger_id=151,inspection_id=389,question='검사 결과 요약'),first_client)))
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(self.generate().status_code,429)
        finally:
            released.set();thread.join(5)
        self.assertEqual(responses[0].status_code,200)


class WorkerTests(unittest.TestCase):
    @patch.object(service.subprocess,'run')
    def test_worker_timeout_and_independent_runtime(self,run):
        run.side_effect=service.subprocess.TimeoutExpired('python',120)
        with self.assertRaises(QueryRejected):
            service.generate_in_worker('요약')
        kwargs=run.call_args.kwargs
        self.assertEqual(kwargs['timeout'],120)
        self.assertNotIn('PYTHONPATH',kwargs['env'])
        self.assertNotIn('LLAMA_CPP_LIB_PATH',kwargs['env'])
        self.assertEqual(Path(run.call_args.args[0][0]).resolve(),Path(sys.executable).resolve())


if __name__ == '__main__':
    unittest.main()
