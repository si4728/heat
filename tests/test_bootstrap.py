import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.database import connection_url


class IsolationTests(unittest.TestCase):
    def test_no_legacy_package_loaded(self):
        self.assertFalse(any(name == "iris" or name.startswith("iris.") for name in sys.modules))

    def test_missing_config_cannot_fall_back(self):
        from iris2.db_config import load_database_config
        with self.assertRaises(ValueError):
            load_database_config(path=Path(__file__).parent / "missing.conf")

    def test_config_validation_and_literal_password(self):
        import tempfile
        from iris2.db_config import load_database_config
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "database.conf"
            template = "[database]\nhost=127.0.0.1\nport=3307\nname={name}\nuser={user}\npassword=p%#;:@/x\ncharset=utf8mb4\n"
            path.write_text(template.format(name="iris2", user="iris2_app"), encoding="utf-8")
            self.assertEqual(load_database_config(path=path)["password"], "p%#;:@/x")
            for name, user in [("production", "iris2_app"), ("iris2", "root")]:
                path.write_text(template.format(name=name, user=user), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_database_config(path=path)
            self.assertEqual(load_database_config(admin=True, path=path)["user"], "root")

    def test_environment_cannot_override_config_credentials(self):
        settings = dict(host="127.0.0.1", port=3307, name="iris2", user="iris2_app", password="file-password", charset="utf8mb4")
        with patch("iris2.database.load_database_config", return_value=settings):
            with patch.dict(os.environ, {"IRIS2_DB_PASSWORD": "wrong", "IRIS2_DB_NAME": "wrong"}):
                url = connection_url()
                self.assertEqual(url.password, "file-password")
                self.assertEqual(url.database, "iris2")

    def test_health_failure_redacts_secrets(self):
        with patch("iris2.services.database_health", side_effect=RuntimeError("super-secret-password")):
            response = create_app().test_client().get("/api/health")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("super-secret-password", response.get_data(as_text=True))

    def test_business_routes_require_authentication(self):
        app=create_app({'TESTING':True,'AUTH_DISABLED':False})
        self.assertGreater(len(list(app.url_map.iter_rules())),80)
        self.assertEqual(app.test_client().get('/exchangers').status_code,302)

    def test_schema_replaces_partial_unique_indexes(self):
        from iris2.migration.schema_draft import build_metadata
        metadata, replaced = build_metadata()
        self.assertEqual(len(replaced), 2)
        table = metadata.tables["heat_exchanger_spec_revision"]
        self.assertIsNotNone(table.c.current_exchanger_unique.computed)
        self.assertTrue(all(not idx.dialect_options["sqlite"].get("where") is not None for t in metadata.tables.values() for idx in t.indexes))


if __name__ == "__main__":
    unittest.main()
