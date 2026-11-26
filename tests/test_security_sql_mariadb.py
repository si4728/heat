"""Exercise injection-shaped values against a disposable MariaDB copy."""
from pathlib import Path
import secrets
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from customer_clone import customer_clone
from iris2 import services
from iris2.llm_integration import text_to_sql as sql


class SqlInjectionMariaDBTests(unittest.TestCase):
    def test_login_and_query_values_cannot_change_the_query_or_authorized_scope(self):
        with customer_clone():
            password = secrets.token_urlsafe(24)
            username = 'sql-security@example.test'
            services.save_user(dict(username=username, display_name='SQL security',
                password=password, password_confirm=password, is_admin='on', is_active='on'))
            count = services.user_count()
            self.assertIsNotNone(services.authenticate_user(username, password))
            for name, supplied in (("' OR 1=1 --@example.test", password),
                                   (username, "' OR 1=1 --"),
                                   ("x'; DROP TABLE app_user;--", password)):
                self.assertIsNone(services.authenticate_user(name, supplied))
            self.assertEqual(services.user_count(), count)
            proposal = dict(sql='SELECT COUNT(*) AS matched FROM analysis_tubes WHERE source_tube_id = ?',
                parameters=["' OR 1=1; DROP TABLE app_user; --"])
            result = sql.execute_proposal(proposal, exchanger_id=151, authorized_exchanger_ids={151})
            self.assertEqual(result['rows'][0]['matched'], 0)
            self.assertEqual(services.user_count(), count)
            with patch.object(sql.dbapi, 'connect') as connect:
                with self.assertRaises(PermissionError):
                    sql.execute_proposal(proposal, exchanger_id=151, authorized_exchanger_ids={100})
                connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
