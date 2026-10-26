from __future__ import annotations
import argparse
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from iris2.app import create_app


def create_listener(host, port):
    family = socket.AF_INET6 if ':' in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((host, port))
        return listener
    except Exception:
        listener.close()
        raise


def main():
    parser = argparse.ArgumentParser(description="IRIS2 independent MariaDB development server")
    parser.add_argument("--host", default=os.environ.get("IRIS2_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("IRIS2_PORT", "4824")))
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.port == 4823:
        parser.error("Port 4823 is reserved for iris; choose a separate port")
    app = create_app()
    if args.health_check:
        response = app.test_client().get("/api/health")
        print(response.get_json())
        return 0 if response.status_code == 200 else 1
    from waitress import serve
    from iris2.backup_manager import start_backup_scheduler
    from iris2.hx_configuration import DB_PATH
    try:
        listener = create_listener(args.host, args.port)
    except OSError:
        parser.error('The requested address/port is already in use or unavailable; a second IRIS2 server was not started.')
    try:
        start_backup_scheduler(ROOT, DB_PATH)
        print(f"IRIS2 MariaDB: http://{args.host}:{args.port}", flush=True)
        serve(app, sockets=[listener], threads=8)
    finally:
        listener.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
