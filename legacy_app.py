from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from flask import Flask

if __package__ in (None, ""):
    project_dir = Path(__file__).resolve().parent.parent
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    from iris2 import services
    from iris2.backup_manager import start_backup_scheduler
    from iris2.hx_configuration import (
        APP_SECRET_KEY,
        API_WRITE_TOKEN,
        AUTHENTICATION_REQUIRED,
        DB_PATH,
        JSON_AS_ASCII,
        MAX_CONTENT_LENGTH,
        PERMANENT_SESSION_LIFETIME_MINUTES,
        SERVER_HEALTH_CHECK,
        SERVER_HOST,
        SERVER_PORT,
        SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_SECURE,
        SESSION_IDLE_TIMEOUT_SECONDS,
        SESSION_REFRESH_EACH_REQUEST,
        ensure_directories,
    )
    from iris2.web.security import register_security
    from iris2.web.routes import ROUTE_REGISTRARS
else:
    from . import services
    from .backup_manager import start_backup_scheduler
    from .hx_configuration import (
        APP_SECRET_KEY,
        API_WRITE_TOKEN,
        AUTHENTICATION_REQUIRED,
        DB_PATH,
        JSON_AS_ASCII,
        MAX_CONTENT_LENGTH,
        PERMANENT_SESSION_LIFETIME_MINUTES,
        SERVER_HEALTH_CHECK,
        SERVER_HOST,
        SERVER_PORT,
        SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_SECURE,
        SESSION_IDLE_TIMEOUT_SECONDS,
        SESSION_REFRESH_EACH_REQUEST,
        ensure_directories,
    )
    from .web.security import register_security
    from .web.routes import ROUTE_REGISTRARS


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=APP_SECRET_KEY,
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        JSON_AS_ASCII=JSON_AS_ASCII,
        AUTH_DISABLED=not AUTHENTICATION_REQUIRED,
        SESSION_IDLE_TIMEOUT_SECONDS=SESSION_IDLE_TIMEOUT_SECONDS,
        PERMANENT_SESSION_LIFETIME=timedelta(
            minutes=PERMANENT_SESSION_LIFETIME_MINUTES
        ),
        SESSION_REFRESH_EACH_REQUEST=SESSION_REFRESH_EACH_REQUEST,
        SESSION_COOKIE_HTTPONLY=SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE=SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_SECURE=SESSION_COOKIE_SECURE,
        CSRF_ENABLED=True,
    )
    if test_config:
        app.config.update(test_config)
        if app.config.get("TESTING") and "AUTH_DISABLED" not in test_config:
            app.config["AUTH_DISABLED"] = True
        if app.config.get("TESTING") and "CSRF_ENABLED" not in test_config:
            app.config["CSRF_ENABLED"] = False

    ensure_directories()
    services.initialize()
    register_security(app)
    for register_routes in ROUTE_REGISTRARS:
        register_routes(app)
    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="지능형열교환시스템")
    parser.add_argument("--host", default=SERVER_HOST)
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument(
        "--health-check", action=argparse.BooleanOptionalAction,
        default=SERVER_HEALTH_CHECK,
    )
    args = parser.parse_args()
    if args.health_check:
        response = app.test_client().get("/api/health")
        print(response.get_json())
        return 0 if response.status_code == 200 else 1
    from waitress import serve
    print(f"지능형열교환기시스템: http://{args.host}:{args.port}")
    print(f"Database: {DB_PATH}")
    start_backup_scheduler(Path(__file__).resolve().parent, DB_PATH)
    serve(app, host=args.host, port=args.port, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
