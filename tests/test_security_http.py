from pathlib import Path
import sys
import unittest
import json
import threading
from urllib.request import build_opener, ProxyHandler, Request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.web.safe_urls import local_redirect_path
import test_access_audit as audit_tests


class HttpSecurityTests(unittest.TestCase):
    setUp = audit_tests.AccessAuditTests.setUp
    profile = staticmethod(audit_tests.AccessAuditTests.profile)

    def test_redirects_reject_external_backslash_and_encoded_authorities(self):
        for target in ('https://outside.example/path', '//outside.example', '/\\outside.example', '/%5coutside.example',
                       '/%2foutside.example', '/%252foutside.example', '/\r\nLocation: outside', 'javascript:alert(1)'):
            with self.subTest(target=target):
                self.assertEqual(local_redirect_path(target, '/safe'), '/safe')
        self.assertEqual(local_redirect_path('/analysis?exchanger_id=100#map', '/safe'), '/analysis?exchanger_id=100#map')
        self.assertEqual(local_redirect_path('https://local.test/analysis?exchanger_id=100', '/safe', origin='https://local.test/'), '/analysis?exchanger_id=100')
        self.assertEqual(local_redirect_path('https://outside.example/analysis', '/safe', origin='https://local.test/'), '/safe')

    def test_login_uses_the_safe_local_redirect(self):
        with self.client.session_transaction() as s:
            s['csrf_token'] = 'csrf'
        with patch('iris2.services.authenticate_user', return_value=self.profile(1)):
            response = self.client.post('/login', data=dict(username='user@example.test', password='valid', csrf_token='csrf', next='/\\outside.example'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/')

    def test_headers_cache_controls_and_https_only_hsts(self):
        response = self.client.get('/login')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn("frame-ancestors 'self'", response.headers['Content-Security-Policy'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertNotIn('Strict-Transport-Security', response.headers)
        secure = self.client.get('/login', base_url='https://localhost')
        self.assertEqual(secure.headers['Strict-Transport-Security'], 'max-age=31536000')

    def test_production_rejects_disabled_authentication_or_debug(self):
        for config in ({'AUTH_DISABLED': True}, {'DEBUG': True}):
            with self.subTest(config=config), patch('iris2.services.initialize') as initialize:
                with self.assertRaises(RuntimeError):
                    create_app(config)
                initialize.assert_not_called()

    def test_https_host_policy_rejects_spoofed_headers_and_invalid_cookie_settings(self):
        from iris2.server import proxy_options
        secure = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True,
            REQUIRE_HTTPS=True, SESSION_COOKIE_SECURE=True, TRUSTED_HOSTS=['localhost']))
        client = secure.test_client()
        self.assertEqual(client.get('/login', headers={'X-Forwarded-Proto': 'https'}).status_code, 400)
        self.assertEqual(client.get('/login', base_url='https://outside.example').status_code, 400)
        self.assertEqual(client.get('/login', base_url='https://localhost').status_code, 200)
        self.assertEqual(proxy_options(None), {'clear_untrusted_proxy_headers': True})
        self.assertEqual(proxy_options('127.0.0.1')['trusted_proxy_count'], 1)
        with self.assertRaises(ValueError):
            proxy_options('*')
        with self.assertRaises(RuntimeError):
            create_app(dict(TESTING=True, REQUIRE_HTTPS=True, SESSION_COOKIE_SECURE=False))

    def test_write_api_rejects_invalid_tokens_without_changing_data(self):
        with patch('iris2.app.API_WRITE_TOKEN', 'isolated-token'), patch('iris2.services.save_exchanger') as save:
            for token in ('', 'wrong', '\u00e9'):
                response = self.client.post('/api/v1/exchangers', json={}, headers={'X-IRIS-API-Token': token})
                self.assertEqual(response.status_code, 401)
            save.assert_not_called()


class WaitressProxySecurityTests(unittest.TestCase):
    def test_real_listener_only_accepts_forwarded_identity_from_configured_peer(self):
        from flask import Flask, jsonify, request
        from waitress.server import create_server
        from iris2.server import proxy_options
        app = Flask(__name__)
        @app.get('/')
        def identity():
            return jsonify(ip=request.remote_addr, secure=request.is_secure, host=request.host)
        for trusted in (None, '127.0.0.2', '127.0.0.1'):
            with self.subTest(trusted=trusted):
                server = create_server(app, host='127.0.0.1', port=0, threads=1,
                    asyncore_loop_timeout=0.05, **proxy_options(trusted))
                thread = threading.Thread(target=server.run, daemon=True)
                thread.start()
                try:
                    url = 'http://127.0.0.1:' + str(server.effective_port)
                    req = Request(url, headers={'X-Forwarded-For': '203.0.113.25',
                        'X-Forwarded-Proto': 'https', 'X-Forwarded-Host': 'outside.example'})
                    with build_opener(ProxyHandler({})).open(req, timeout=5) as response:
                        actual = json.load(response)
                    accepted = trusted == '127.0.0.1'
                    self.assertEqual(actual['ip'], '203.0.113.25' if accepted else '127.0.0.1')
                    self.assertEqual(actual['secure'], accepted)
                    self.assertTrue(actual['host'].startswith('127.0.0.1:'))
                finally:
                    server.close()
                    server.task_dispatcher.shutdown()
                    thread.join(3)
                    self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
