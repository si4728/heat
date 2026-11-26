from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
from threading import Barrier
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from customer_clone import customer_clone
from iris2 import services
from iris2.app import create_app


class BootstrapSecurityTests(unittest.TestCase):
    def test_inactive_accounts_never_reopen_initial_admin_registration(self):
        with customer_clone() as (engine, schema):
            with engine.begin() as c:
                c.exec_driver_sql('UPDATE app_user SET is_active=0')
                before = c.scalar(text('SELECT COUNT(*) FROM app_user'))
            self.assertEqual(services.user_count(), before)
            app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
            client = app.test_client()
            with client.session_transaction() as s:
                s['csrf_token'] = 'bootstrap-test'
            self.assertEqual(client.get('/setup-admin').status_code, 302)
            self.assertEqual(client.post('/setup-admin', data=dict(csrf_token='bootstrap-test',
                username='blocked@example.test', display_name='Blocked', password='valid-test-password',
                password_confirm='valid-test-password')).status_code, 302)
            with self.assertRaises(ValueError):
                services.create_initial_admin(dict(username='blocked@example.test', display_name='Blocked',
                    password='valid-test-password', password_confirm='valid-test-password'))
            with engine.connect() as c:
                self.assertEqual(c.scalar(text('SELECT COUNT(*) FROM app_user')), before)

    def test_fresh_setup_requires_loopback_and_serializes_initial_creation(self):
        with customer_clone() as (engine, schema):
            with engine.begin() as c:
                # Disable FK checks only on this disposable test connection.
                c.exec_driver_sql('SET FOREIGN_KEY_CHECKS=0')
                c.exec_driver_sql('DELETE FROM user_screen_permission')
                c.exec_driver_sql('DELETE FROM app_user')
                c.exec_driver_sql('SET FOREIGN_KEY_CHECKS=1')
            app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
            client = app.test_client()
            for base, address in [('http://localhost', '192.0.2.1'), ('http://untrusted.example', '127.0.0.1')]:
                self.assertEqual(client.get('/setup-admin', base_url=base,
                    environ_overrides={'REMOTE_ADDR': address}, headers={'X-Forwarded-For': '127.0.0.1'}).status_code, 403)
            self.assertEqual(client.get('/setup-admin', base_url='http://localhost',
                environ_overrides={'REMOTE_ADDR': '127.0.0.1'}).status_code, 200)
            barrier = Barrier(2)
            def create(index):
                barrier.wait(timeout=10)
                try:
                    services.create_initial_admin(dict(username=f'initial{index}@example.test', display_name='Initial',
                        password='valid-test-password', password_confirm='valid-test-password'))
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                self.assertEqual(sorted(pool.map(create, (1, 2))), [False, True])
            self.assertEqual(services.user_count(), 1)


if __name__ == '__main__':
    unittest.main()
