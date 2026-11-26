from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

import test_access_audit as audit_tests


class PublicHealthSecurityTests(unittest.TestCase):
    setUp = audit_tests.AccessAuditTests.setUp
    profile = staticmethod(audit_tests.AccessAuditTests.profile)

    def test_concurrent_public_probes_are_cached_without_full_integrity_scans(self):
        with patch('iris2.services.database_readiness', return_value=True) as ready, \
                patch('iris2.services.database_health') as full:
            def probe(_):
                with self.app.test_client() as client:
                    response = client.get('/api/health')
                    return response.status_code, response.json
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(probe, range(12)))
            self.assertTrue(all(status == 200 and data == dict(application='iris2', backend='mariadb', status='ok')
                for status, data in results))
            ready.assert_called_once()
            full.assert_not_called()

    def test_probe_failure_hides_details_and_recovers_after_cache_expiry(self):
        with patch('iris2.web.routes.api_v1.monotonic', return_value=100), \
                patch('iris2.services.database_readiness', side_effect=RuntimeError('private-credentials')) as ready:
            for _ in range(3):
                response = self.client.get('/api/health')
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('private-credentials', response.text)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            ready.assert_called_once()
        with patch('iris2.web.routes.api_v1.monotonic', return_value=102), \
                patch('iris2.services.database_readiness', return_value=True) as ready:
            self.assertEqual(self.client.get('/api/health').status_code, 200)
            ready.assert_called_once()


if __name__ == '__main__':
    unittest.main()
