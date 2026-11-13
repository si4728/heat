"""Read-only queue reconciliation and dashboard visibility checks."""
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2 import dbapi, services
from iris2.app import create_app
from iris2.application.api510_service import pending_api510_reviews
from iris2.hx_configuration import DB_PATH


class Api510ReviewDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({'TESTING':True, 'AUTH_DISABLED':False, 'CSRF_ENABLED':True})
        cls.dashboard_data = services.dashboard_data()

    def client(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=1, last_activity_at=time.time(), csrf_token='audit-test')
        return client

    def test_queue_matches_independent_mariadb_scope_and_status_query(self):
        queue = pending_api510_reviews()
        connection = dbapi.connect(DB_PATH, readonly=True)
        try:
            expected = list(connection.execute("""SELECT a.api510_calculation_id
                FROM api510_calculation a
                JOIN pressure_boundary_component p ON p.pressure_component_id=a.pressure_component_id
                JOIN heat_exchanger h ON h.heat_exchanger_id=p.heat_exchanger_id
                JOIN equipment e ON e.equipment_id=h.equipment_id
                JOIN process_unit u ON u.unit_id=e.unit_id
                WHERE a.status='SUBMITTED' AND u.unit_code IN ('VCM1','VCM2')
                ORDER BY COALESCE(a.submitted_at,a.created_at),a.api510_calculation_id"""))
        finally:
            connection.close()
        self.assertEqual(queue['count'], len(expected))
        self.assertEqual([r['calculation_id'] for r in queue['rows']], [r[0] for r in expected[:10]])
        self.assertTrue(all(r['unit_code'] in ('VCM1','VCM2') for r in queue['rows']))

    def render(self, admin, queue):
        profile = dict(user_id=1, username='review-test', is_admin=admin, is_active=True,
                       permissions={'DASHBOARD':dict(can_view=True, can_edit=False)})
        with patch('iris2.services.user_count', return_value=1), patch(
            'iris2.services.user_access_profile', return_value=profile), patch(
            'iris2.services.dashboard_data', return_value=self.dashboard_data), patch(
            'iris2.web.routes.dashboard.pending_api510_reviews', return_value=queue) as query:
            response = self.client().get('/')
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True), query

    def test_admin_sees_pending_count_and_specific_calculation_link(self):
        html, query = self.render(True, dict(count=12, limit=10, rows=[dict(
            calculation_id=987, heat_exchanger_id=151, exchanger_code='E-106',
            component_code='SHELL-1', unit_code='VCM2', created_by='engineer',
            submitted_at=datetime(2026,11,13,9,30))]))
        query.assert_called_once_with()
        self.assertIn('API 510 검토·승인 대기 <span>12건', html)
        self.assertIn('/exchangers/151/api510#api510-calculation-987', html)
        self.assertIn('2026-11-13 09:30', html)
        self.assertNotIn('action="/api510-calculations/', html)

    def test_empty_queue_has_explicit_zero_and_empty_message(self):
        html, _ = self.render(True, dict(count=0, rows=[], limit=10))
        self.assertIn('API 510 검토·승인 대기 <span>0건', html)
        self.assertIn('검토·승인 대기 중인 API 510 계산결과가 없습니다.', html)

    def test_non_admin_does_not_query_or_see_review_queue(self):
        html, query = self.render(False, dict(count=12, rows=[], limit=10))
        query.assert_not_called()
        self.assertNotIn('id="api510-review-queue"', html)


if __name__ == '__main__':
    unittest.main()
