"""Audit request coverage, secret exclusion and manager authorization without live writes."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from flask import abort, g, session
from iris2 import services
from iris2.app import create_app
from iris2.application.access_audit import clean_text, csv_cell, parse_filters


class AccessAuditTests(unittest.TestCase):
    def setUp(self):
        self.events=[]
        self.patches=[
            patch('iris2.services.initialize'),
            patch('iris2.services.user_count',return_value=2),
            patch('iris2.services.active_theme_data',return_value=dict(preset_key='DEFAULT',background_color='#f4f7f7',label_color='#52616a')),
            patch('iris2.web.security.organization_catalog',return_value=dict(entries=[],labels={})),
            patch('iris2.web.access_audit.append_events',side_effect=lambda rows:self.events.extend(rows)),
            patch('iris2.services.user_access_profile',side_effect=self.profile),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True,ACCESS_AUDIT_ENABLED=True))
        # Exercise real permission checks while avoiding unrelated business DB queries.
        self.app.view_functions['dashboard']=lambda:'dashboard'
        self.app.view_functions['user_preferences']=lambda:'preferences'
        self.app.add_url_rule('/audit-boom',endpoint='inspection_detail')
        self.app.view_functions['inspection_detail']=lambda **kwargs:abort(500)
        self.client=self.app.test_client()

    @staticmethod
    def profile(uid):
        if uid not in (1,2):return None
        return dict(user_id=uid,username=f'user{uid}@example.com',is_admin=uid==1,is_active=True,auth_stamp='test-auth-stamp',
                    permissions={'DASHBOARD':{'can_view':True,'can_edit':False},'INSPECTIONS':{'can_view':True}})

    def logged_in(self,uid=1,*,last_activity=None):
        with self.client.session_transaction() as s:
            s.update(user_id=uid,auth_stamp=(services.user_access_profile(uid) or {}).get('auth_stamp','invalid-test-stamp'),last_activity_at=last_activity or time.time(),csrf_token='CSRF-SECRET',
                     audit_session_id='a'*32,audit_username=f'user{uid}@example.com')

    def login(self,success=True):
        with self.client.session_transaction() as s:s['csrf_token']='CSRF-SECRET'
        with patch('iris2.services.authenticate_user',return_value=self.profile(1) if success else None):
            return self.client.post('/login?token=QUERY-SECRET',data=dict(username='user1@example.com',
                password='PASSWORD-SECRET',csrf_token='CSRF-SECRET',next='/'),headers={'User-Agent':'Audit browser'})

    def test_success_failure_logout_and_correlation(self):
        self.assertEqual(self.login().status_code,302)
        success=next(e for e in self.events if e['event_type']=='LOGIN_SUCCESS')
        self.assertEqual(success['user_id'],1)
        self.assertEqual(len(success['audit_session_id']),32)
        self.client.get('/')
        self.assertEqual(self.events[-1]['audit_session_id'],success['audit_session_id'])
        with self.client.session_transaction() as s:s['csrf_token']='FRESH-CSRF'
        self.assertEqual(self.client.post('/logout',data={'csrf_token':self.client.get_cookie('iris2_session') and 'bad'}).status_code,400)
        with self.client.session_transaction() as s:token=s['csrf_token']
        self.assertEqual(self.client.post('/logout',data={'csrf_token':token}).status_code,302)
        logout=next(e for e in self.events if e['event_type']=='LOGOUT')
        self.assertEqual(logout['audit_session_id'],success['audit_session_id'])
        self.assertEqual(self.login(False).status_code,200)
        failure=next(e for e in self.events if e['event_type']=='LOGIN_FAILURE' and e['reason']=='INVALID_CREDENTIALS')
        self.assertIsNone(failure['user_id'])
        combined=repr(self.events)
        for secret in ['PASSWORD-SECRET','CSRF-SECRET','QUERY-SECRET']:
            self.assertNotIn(secret,combined)

    def test_anonymous_denied_and_admin_only_history_and_csv(self):
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.events[-1]['reason'],'AUTH_REQUIRED')
        self.logged_in(2)
        for path in ['/settings/access-logs','/settings/access-logs/export.csv']:
            self.assertEqual(self.client.get(path).status_code,403)
            self.assertEqual(self.events[-1]['result'],'DENIED')
        self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(self.events[-1]['result'],'ALLOWED')

    def test_expired_and_invalid_session_keep_old_identity_before_clear(self):
        self.logged_in(last_activity=time.time()-1900)
        self.assertEqual(self.client.get('/').status_code,302)
        event=next(e for e in self.events if e['event_type']=='SESSION_EXPIRED')
        self.assertEqual(event['user_id'],1)
        self.assertEqual(event['audit_session_id'],'a'*32)
        self.assertEqual(self.events[-2]['result'],'DENIED')
        self.logged_in(999)
        self.client.get('/')
        self.assertEqual(self.events[-1]['event_type'],'SESSION_INVALID')
        self.assertEqual(self.events[-1]['user_id'],999)

    def test_csrf_unknown_paths_and_server_errors_are_audited(self):
        self.assertEqual(self.client.post('/login',data={'username':'attempt@example.com','password':'secret'}).status_code,400)
        self.assertEqual(self.events[-1]['reason'],'CSRF_REJECTED')
        self.assertEqual(self.events[-1]['event_type'],'LOGIN_FAILURE')
        self.assertEqual(self.client.get('/missing-screen?password=secret').status_code,404)
        self.assertEqual(self.events[-1]['status_code'],404)
        self.assertEqual(self.events[-1]['path'],'/missing-screen')
        self.logged_in()
        self.assertEqual(self.client.get('/audit-boom').status_code,500)
        self.assertEqual(self.events[-1]['result'],'ERROR')

    def test_static_health_are_excluded_and_ip_does_not_trust_forwarded_header(self):
        self.client.get('/static/no-such-file.css')
        with patch.dict(self.app.view_functions,api_health=lambda:'health'):
            self.client.get('/api/health')
        self.assertEqual(self.events,[])
        self.logged_in()
        self.client.get('/',headers={'X-Forwarded-For':'198.51.100.9'})
        self.assertEqual(self.events[-1]['client_ip'],'127.0.0.1')

    def test_audit_outage_is_reported_without_changing_business_response(self):
        self.logged_in()
        with patch('iris2.web.access_audit.append_events',side_effect=RuntimeError('SECRET-DETAIL')):
            with self.assertLogs(self.app.logger,level='ERROR') as log:
                response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['X-Audit-Recorded'],'0')
        self.assertEqual(self.app.extensions['access_audit']['failures'],1)
        self.assertNotIn('SECRET-DETAIL',' '.join(log.output))

    def test_disabling_authentication_never_exposes_audit_data(self):
        self.app.config['AUTH_DISABLED']=True
        for path in ['/settings/access-logs','/settings/access-logs/export.csv']:
            self.assertEqual(self.client.get(path).status_code,403)
            self.assertEqual(self.events[-1]['result'],'DENIED')

    def test_filters_time_boundaries_validation_and_csv_formula_protection(self):
        filters,conditions=parse_filters(dict(start='2026-11-19',end='2026-11-19'))
        self.assertEqual(conditions[0].right.value,datetime(2026,11,18,15))
        self.assertEqual(conditions[1].right.value,datetime(2026,11,19,15))
        for values in [dict(start='bad'),dict(event='SQL'),dict(result='bad'),dict(ip='not-an-ip'),dict(session='bad'),dict(start='2026-12-01',end='2026-01-01')]:
            with self.subTest(values=values),self.assertRaises(ValueError):parse_filters(values)
        self.assertEqual(csv_cell('=HYPERLINK("x")'),'\'=HYPERLINK("x")')
        self.assertEqual(csv_cell(' @evil'),"' @evil")
        self.assertEqual(clean_text('x\n\r\x00y',10),'xy')

if __name__=='__main__':unittest.main()
