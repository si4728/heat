import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from iris2.application.auth_service import user_can
from iris2.web.security import register_security


class PdfOcrPermissionsTest(unittest.TestCase):
    def profile(self, username, admin=False, active=True):
        return dict(user_id=1, username=username, is_admin=admin,
                    is_active=active, permissions={})

    def test_only_named_active_account_can_view_and_edit(self):
        for admin in (False, True):
            for edit in (False, True):
                self.assertTrue(user_can(self.profile('silicon@gmail.com', admin), 'PDF_OCR_REVIEW', edit))
                self.assertFalse(user_can(self.profile('admin@gmail.com', admin), 'PDF_OCR_REVIEW', edit))
                self.assertFalse(user_can(self.profile('silicon@gmail.com', admin, False), 'PDF_OCR_REVIEW', edit))
        self.assertFalse(user_can(None, 'PDF_OCR_REVIEW'))

    def test_direct_routes_and_template_permission(self):
        app = Flask(__name__)
        app.config.update(SECRET_KEY='test', CSRF_ENABLED=False,
                          SESSION_IDLE_TIMEOUT_SECONDS=1800)
        register_security(app)
        app.register_error_handler(403, lambda error: ('forbidden', 403))
        for endpoint, path, methods in (
            ('pdf_ocr_review_dashboard', '/imports/pdf-review', ['GET']),
            ('pdf_ocr_source', '/imports/pdf-review/1/source', ['GET']),
            ('pdf_ocr_approve', '/imports/pdf-review/1/approve', ['POST']),
        ):
            app.add_url_rule(path, endpoint, lambda: 'allowed', methods=methods)
        with app.test_client() as client:
            with client.session_transaction() as session:
                session['user_id'] = 1
            for username, admin, expected in (
                ('silicon@gmail.com', False, 200),
                ('silicon@gmail.com', True, 200),
                ('admin@gmail.com', True, 403),
                ('other@gmail.com', False, 403),
            ):
                with patch('iris2.web.security.services.user_count', return_value=2), patch(
                    'iris2.web.security.services.user_access_profile', return_value=self.profile(username, admin)
                ):
                    for path, method in (('/imports/pdf-review', 'GET'),
                                         ('/imports/pdf-review/1/source', 'GET'),
                                         ('/imports/pdf-review/1/approve', 'POST')):
                        self.assertEqual(client.open(path, method=method).status_code, expected)
            app.config['AUTH_DISABLED'] = True
            self.assertEqual(client.get('/imports/pdf-review').status_code, 403)


if __name__ == '__main__':
    unittest.main()
