from pathlib import Path
import secrets
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from customer_clone import customer_clone
from iris2 import services
from iris2.app import create_app


class SessionPasswordBindingTests(unittest.TestCase):
    def test_password_reset_revokes_old_and_unbound_sessions(self):
        with customer_clone():
            password = secrets.token_urlsafe(24)
            user = services.save_user(dict(username='session-security@example.test', display_name='Session security',
                password=password, password_confirm=password, is_admin='on', is_active='on'))
            uid = user['user_id']
            app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
            app.view_functions['users_admin'] = lambda: 'authorized admin'
            client = app.test_client()
            def login(value):
                with client.session_transaction() as s:
                    s['csrf_token'] = 'security-session-test'
                return client.post('/login', data=dict(username='session-security@example.test', password=value,
                    csrf_token='security-session-test'))
            self.assertEqual(login(password).status_code, 302)
            self.assertEqual(client.get('/settings/users').status_code, 200)
            old_cookie = client.get_cookie('iris2_session').value
            old_stamp = services.user_access_profile(uid)['auth_stamp']
            self.assertEqual(len(old_stamp), 64)
            missing = app.test_client()
            with missing.session_transaction() as s:
                s.update(user_id=uid, last_activity_at=time.time())
            self.assertEqual(missing.get('/settings/users').status_code, 302)
            next_password = secrets.token_urlsafe(24)
            services.save_user(dict(username='session-security@example.test', display_name='Session security',
                password=next_password, password_confirm=next_password, is_admin='on', is_active='on'), uid, actor_user_id=uid)
            self.assertNotEqual(old_stamp, services.user_access_profile(uid)['auth_stamp'])
            replay = app.test_client()
            replay.set_cookie('iris2_session', old_cookie)
            self.assertEqual(replay.get('/settings/users').status_code, 302)
            self.assertEqual(client.get('/settings/users').status_code, 302)
            self.assertEqual(login(next_password).status_code, 302)
            self.assertEqual(client.get('/settings/users').status_code, 200)


if __name__ == '__main__':
    unittest.main()
