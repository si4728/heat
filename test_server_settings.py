from __future__ import annotations

import configparser
import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_DIR / "iris" / "hx_configuration.conf"


class ServerSettingsTest(unittest.TestCase):
    def test_server_defaults_are_loaded_from_configuration(self):
        command = (
            "import json; "
            "from iris2.hx_configuration import "
            "APP_SECRET_KEY, SERVER_HEALTH_CHECK, SERVER_HOST, SERVER_PORT; "
            "print(json.dumps({'host': SERVER_HOST, 'port': SERVER_PORT, "
            "'health_check': SERVER_HEALTH_CHECK, 'secret_length': len(APP_SECRET_KEY), "
            "'placeholder': APP_SECRET_KEY == 'iris-v3-local-system'}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", command],
            cwd=PROJECT_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
        settings = json.loads(result.stdout)
        config = configparser.ConfigParser(interpolation=None)
        config.read(CONFIG_PATH, encoding="utf-8")

        self.assertEqual(settings["host"], config.get("server", "host"))
        self.assertIn(settings["host"], {"127.0.0.1", "0.0.0.0", "::"})
        self.assertEqual(settings["port"], config.getint("server", "port"))
        self.assertEqual(settings["port"], 4823)
        self.assertEqual(
            settings["health_check"], config.getboolean("server", "health_check")
        )
        self.assertGreaterEqual(settings["secret_length"], 32)
        self.assertFalse(settings["placeholder"])


if __name__ == "__main__":
    unittest.main()
