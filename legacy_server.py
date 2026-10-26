from __future__ import annotations

import argparse
import sys
import sqlite3
import threading
import time
import webbrowser
from pathlib import Path

from waitress import serve


PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from iris2.app import app
from iris2.backup_manager import start_backup_scheduler
from iris2.hx_configuration import APP_DIR, DB_PATH, SERVER_HEALTH_CHECK, SERVER_HOST, SERVER_PORT


def main() -> int:
    if sqlite3.sqlite_version_info < (3, 51, 3):
        raise RuntimeError('SQLite 3.51.3 or newer is required. Run runtime/sqlite/install_runtime.ps1 with the project virtual environment.')
    parser = argparse.ArgumentParser(description="IRIS v3 Heat Exchanger System")
    parser.add_argument("--host", default=SERVER_HOST)
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--health-check", action=argparse.BooleanOptionalAction,
        default=SERVER_HEALTH_CHECK,
    )
    args = parser.parse_args()
    if args.health_check:
        response = app.test_client().get("/api/health")
        print(response.get_json())
        return 0 if response.status_code == 200 else 1
    url_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{url_host}:{args.port}"
    if not args.no_browser:
        def open_later():
            time.sleep(1.0)
            webbrowser.open(url)
        threading.Thread(target=open_later, daemon=True).start()
    print(f"IRIS v3 System: {url}")
    print(f"Database: {DB_PATH}")
    start_backup_scheduler(APP_DIR, DB_PATH)
    serve(app, host=args.host, port=args.port, threads=8)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
