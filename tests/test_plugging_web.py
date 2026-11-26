import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2 import services
from iris2.web.security import register_security
from iris2.web.routes.exchangers import register_routes


class PluggingWebTests(unittest.TestCase):
    def setUp(self):
        self.profile=dict(user_id=7,username='editor',is_active=True,is_admin=False,auth_stamp='test-auth-stamp',
            permissions={key:dict(can_view=True,can_edit=True) for key in ('EXCHANGERS','MAINTENANCE')})
        self.app=Flask(__name__)
        self.app.config.update(TESTING=True,SECRET_KEY='test',AUTH_DISABLED=False,CSRF_ENABLED=True,SESSION_IDLE_TIMEOUT_SECONDS=1800)
        register_security(self.app);register_routes(self.app)
        self.app.register_error_handler(403,lambda exc:('Forbidden',403))
        for name,value in [('user_count',1),('user_access_profile',self.profile)]:
            p=patch('iris2.services.'+name,return_value=value);p.start();self.addCleanup(p.stop)
        self.client=self.app.test_client()
        with self.client.session_transaction() as s:s.update(user_id=7,auth_stamp=services.user_access_profile(7)['auth_stamp'],last_activity_at=time.time(),csrf_token='csrf')

    def test_write_requires_both_edit_permissions_and_csrf(self):
        for denied in ('EXCHANGERS','MAINTENANCE'):
            self.profile['permissions'][denied]['can_edit']=False
            self.assertEqual(self.client.post('/analysis/100/plugging',json={},headers={'X-CSRF-Token':'csrf'}).status_code,403)
            self.profile['permissions'][denied]['can_edit']=True
        self.assertEqual(self.client.post('/analysis/100/plugging',json={}).status_code,400)

    def test_actor_is_authenticated_server_user_and_reads_are_no_store(self):
        with patch('iris2.application.plugging_operations.apply',return_value=dict(changed=1)) as apply:
            result=self.client.post('/analysis/100/plugging',json=dict(actor_id=99),headers={'X-CSRF-Token':'csrf'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(apply.call_args.args[2]['user_id'],7)
        with patch('iris2.application.plugging_operations.state',return_value=dict(history=[],versions={})):
            result=self.client.get('/analysis/100/plugging')
            self.assertEqual(result.headers['Cache-Control'],'no-store')
            self.profile['permissions'].pop('MAINTENANCE')
            self.assertEqual(self.client.get('/analysis/100/plugging').status_code,403)

    def test_anonymous_and_auth_disabled_fail_closed(self):
        self.assertEqual(self.app.test_client().get('/analysis/100/plugging').status_code,302)
        self.app.config['AUTH_DISABLED']=True
        self.app.config['CSRF_ENABLED']=False
        self.assertEqual(self.app.test_client().post('/analysis/100/plugging',json={}).status_code,403)


if __name__=='__main__':unittest.main()
