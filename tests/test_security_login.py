from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application.login_guard import LoginGuard
import test_access_audit as audit_tests


class LoginSecurityTests(unittest.TestCase):
    setUp = audit_tests.AccessAuditTests.setUp
    profile = staticmethod(audit_tests.AccessAuditTests.profile)

    def test_failures_are_throttled_without_trusting_forwarded_headers(self):
        with self.client.session_transaction() as s:
            s['csrf_token'] = 'csrf'
        with patch('iris2.services.authenticate_user', return_value=None) as authenticate:
            for index in range(5):
                r = self.client.post('/login', data=dict(username='user@example.test', password='wrong', csrf_token='csrf'),
                    headers={'X-Forwarded-For': f'192.0.2.{index+1}'})
                self.assertEqual(r.status_code, 200)
            r = self.client.post('/login', data=dict(username='user@example.test', password='wrong', csrf_token='csrf'))
            self.assertEqual(r.status_code, 429)
            self.assertGreater(int(r.headers['Retry-After']), 0)
            self.assertEqual(authenticate.call_count, 5)

    def test_successful_requests_do_not_consume_failed_attempt_budget(self):
        with patch('iris2.services.authenticate_user', return_value=self.profile(1)):
            for _ in range(7):
                with self.client.session_transaction() as s:
                    s['csrf_token'] = 'csrf'
                self.assertEqual(self.client.post('/login', data=dict(username='user@example.test', password='valid', csrf_token='csrf')).status_code, 302)

    def test_authentication_form_has_a_separate_small_body_limit(self):
        self.assertEqual(self.client.post('/login', data={'password': 'x' * 20000}).status_code, 413)

    def test_parallel_reservations_expiry_source_limit_and_bounded_memory(self):
        current = [1000]
        guard = LoginGuard(attempts=2, source_attempts=3, window=10, max_buckets=8, clock=lambda: current[0])
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: guard.begin('same-source', 'same-user'), range(3)))
        self.assertEqual(sum(ticket is not None for ticket, _ in results), 2)
        ticket = next(ticket for ticket, _ in results if ticket is not None)
        guard.finish(ticket, success=True)
        self.assertIsNotNone(guard.begin('same-source', 'same-user')[0])
        self.assertIsNotNone(guard.begin('same-source', 'another-user')[0])
        self.assertIsNone(guard.begin('same-source', 'third-user')[0])
        current[0] += 11
        self.assertIsNotNone(guard.begin('same-source', 'same-user')[0])
        for index in range(100):
            guard.begin(str(index), 'new-user')
        self.assertLessEqual(len(guard.buckets), 8)


if __name__ == '__main__':
    unittest.main()
