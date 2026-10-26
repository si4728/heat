"""Read private iris2 DB configuration without environment credential overrides."""
from __future__ import annotations
import configparser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
APP_CONFIG = APP_DIR / "config/database.conf"
ADMIN_CONFIG = APP_DIR / "config/database-admin.conf"


def load_database_config(*, admin=False, path=None):
    target = Path(path) if path is not None else (ADMIN_CONFIG if admin else APP_CONFIG)
    parser = configparser.ConfigParser(interpolation=None)
    try:
        with target.open(encoding="utf-8-sig") as stream:
            parser.read_file(stream)
        section = parser["database"]
        settings = {key: section[key] for key in ("host", "name", "user", "password", "charset")}
        settings["port"] = section.getint("port")
        if any(not value.strip() for value in settings.values() if isinstance(value, str)):
            raise ValueError()
        if not 1 <= settings["port"] <= 65535:
            raise ValueError()
        if not settings["name"].startswith("iris2"):
            raise ValueError()
        if not admin and not settings["user"].startswith("iris2"):
            raise ValueError()
        return settings
    except (OSError, configparser.Error, KeyError, ValueError):
        raise ValueError("Invalid or missing iris2 database configuration; check the private config file") from None
