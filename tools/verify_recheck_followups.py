"""Verify remaining review fixes in a browser against a disposable MariaDB copy."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from sqlalchemy import text
from werkzeug.serving import make_server, WSGIRequestHandler
from customer_clone import customer_clone
from iris2 import services
from iris2.app import create_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--section', choices=('all', 'dashboard', 'analysis', 'thickness'), default='all')
    args = parser.parse_args()
    out = Path('reports/recheck-followups-20261126/browser')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'failure.txt').unlink(missing_ok=True)
    with customer_clone() as (engine, schema):
        app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
        with engine.connect() as c:
            uid = c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
            thickness_id = c.scalar(text("SELECT heat_exchanger_id FROM heat_exchanger_spec_revision WHERE is_current=1 AND exchanger_code='E-122A'"))
        session = dict(user_id=uid,auth_stamp=services.user_access_profile(uid)['auth_stamp'], last_activity_at=time.time(), csrf_token='followups-browser-check')
        cookie = app.session_interface.get_signing_serializer(app).dumps(session)
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        settings = dict(base=f'http://127.0.0.1:{server.server_port}', cookie=cookie, out=str(out.resolve()), section=args.section,
                        thickness_id=thickness_id)
        node = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Microsoft VS Code/Code.exe'
        try:
            result = subprocess.run([str(node) if node.is_file() else 'node', 'tools/verify_recheck_followups.mjs'],
                input=json.dumps(settings), text=True, encoding='utf-8', capture_output=True,
                env=dict(os.environ, ELECTRON_RUN_AS_NODE='1'), timeout=480)
            (out / 'stdout.txt').write_text(result.stdout, encoding='utf-8')
            (out / 'stderr.txt').write_text(result.stderr, encoding='utf-8')
            if result.returncode:
                raise RuntimeError('Followup browser checks failed; inspect the local report')
            print(f'PASS: {args.section} browser checks. UTF-8 details saved in local report.', flush=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
    print('Temporary database/account/server removed; production service remains stopped.', flush=True)


if __name__ == '__main__':
    main()
