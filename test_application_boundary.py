from __future__ import annotations

import ast
import configparser
import unittest
from pathlib import Path

from tools.build_deployments_folder import ignore_iris, sanitized_configuration


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "hx_configuration.conf"


def configured_path(config: configparser.ConfigParser, option: str) -> Path:
    path = Path(config.get("database" if option == "name" else "paths", option))
    if not path.is_absolute():
        path = CONFIG_PATH.parent / path
    return path.resolve()


class ApplicationBoundaryTest(unittest.TestCase):
    def test_configured_application_paths_stay_under_iris(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(CONFIG_PATH, encoding="utf-8")
        paths = (
            configured_path(config, "name"),
            configured_path(config, "uploads"),
            configured_path(config, "reports"),
            configured_path(config, "pdf_reports"),
            configured_path(config, "cumulative_report"),
        )
        for path in paths:
            self.assertTrue(
                path.is_relative_to(APP_DIR),
                f"Configured path escapes iris: {path}",
            )

    def test_runtime_assets_stay_under_iris(self):
        required = (
            APP_DIR / "data" / "heat_exchanger_db3.db",
            APP_DIR / "static" / "hanwha_solution2.jpg",
            APP_DIR / "static" / "vendor" / "three" / "three.min.js",
            APP_DIR / "docs" / "PLUGGING_UNCALCULABLE_GUIDE_20260807.md",
        )
        for path in required:
            self.assertTrue(path.is_file(), f"Required iris asset is missing: {path}")

    def test_iris_python_does_not_import_root_python_modules(self):
        workspace = APP_DIR.parent
        outside_imports: list[str] = []
        for source in APP_DIR.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
            for node in ast.walk(tree):
                modules: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                for module in modules:
                    root_module = module.split(".", 1)[0]
                    candidate = workspace / f"{root_module}.py"
                    if candidate.is_file():
                        outside_imports.append(
                            f"{source.name}:{node.lineno} -> {candidate.name}"
                        )
        self.assertEqual(outside_imports, [])

    def test_delivery_excludes_live_database_and_secrets(self):
        ignored = ignore_iris(
            str(APP_DIR / "data"),
            ["heat_exchanger_db3.db", "heat_exchanger_db3.db-wal", ".session_secret"],
        )
        self.assertEqual(
            ignored,
            {"heat_exchanger_db3.db", "heat_exchanger_db3.db-wal", ".session_secret"},
        )
        self.assertIn(
            "hx_configuration.conf",
            ignore_iris(str(APP_DIR), ["hx_configuration.conf"]),
        )
        sanitized = sanitized_configuration(
            "host = 0.0.0.0\nsecret_key = exposed\napi_write_token = exposed\n"
        )
        self.assertIn("host = 127.0.0.1", sanitized)
        self.assertIn("secret_key =\n", sanitized)
        self.assertIn("api_write_token =\n", sanitized)
        self.assertNotIn("exposed", sanitized)


if __name__ == "__main__":
    unittest.main()
