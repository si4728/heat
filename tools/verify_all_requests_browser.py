"""Full request screen audit on one disposable DB; production service stays stopped."""
from datetime import date
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from sqlalchemy import text
from werkzeug.serving import make_server, WSGIRequestHandler
from customer_clone import customer_clone
from iris2 import services
from iris2.app import create_app
from iris2.application import text_to_sql_commentary as commentary
from iris2.tools.audit_customer_requirements_20261126 import QUESTIONS


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', nargs='+', choices=('advanced', 'followups', 'pdf-fluid-queue', 'plugging', 'single-plugging', 'analysis-history', 'correction-screens', 'steam'))
    args = parser.parse_args()
    output = Path('reports/all-requests-audit-20261126/browser')
    output.mkdir(parents=True, exist_ok=True)
    stages = [('advanced', 'tools/verify_advanced_questions_browser.mjs'),
              ('followups', 'tools/verify_recheck_followups.mjs'),
              ('pdf-fluid-queue', 'tools/verify_all_requests_extras.mjs'),
              ('plugging', 'tools/verify_customer_completion_browser.mjs'),
              ('single-plugging', 'tools/verify_single_plugging_audit.mjs'),
              ('analysis-history', 'tools/verify_prior_analysis_requests.mjs'),
              ('correction-screens', 'tools/verify_correction_screens_audit.mjs'),
              ('steam', 'tools/verify_steam_classification_browser.mjs')]
    if args.stages:
        stages = [(label, script) for label, script in stages if label in args.stages]
    with customer_clone() as (engine, schema), patch.object(commentary, 'generate', return_value=dict(
            status='generated', text='브라우저 점검용 대체 의견. 실제 모델 검증은 별도 보고서를 확인하세요.', model='TEST_STUB')):
        app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
        with engine.connect() as c:
            uid = c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_active=1 AND is_admin=1'))
            thickness_id = c.scalar(text("SELECT heat_exchanger_id FROM heat_exchanger_spec_revision WHERE is_current=1 AND exchanger_code='E-122A'"))
            pe_thresholds = [dict(r) for r in c.execute(text("SELECT s.heat_exchanger_id,s.exchanger_code FROM heat_exchanger_spec_revision s JOIN heat_exchanger h ON h.heat_exchanger_id=s.heat_exchanger_id JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id WHERE s.is_current=1 AND u.unit_code='PE' AND s.exchanger_code IN ('E-131D','E-331B','E-331C','E-341A','E-341C','E-241B-1')")).mappings()]
            correction_targets = [dict(r) for r in c.execute(text("SELECT s.heat_exchanger_id,s.exchanger_code FROM heat_exchanger_spec_revision s JOIN heat_exchanger h ON h.heat_exchanger_id=s.heat_exchanger_id JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id WHERE s.is_current=1 AND u.unit_code IN ('VCM1','VCM2') AND s.exchanger_code IN ('E-13','E-122A','E-341','E-222','E-811','E-331A')")).mappings()]
        cookie = app.session_interface.get_signing_serializer(app).dumps(dict(
            user_id=uid,auth_stamp=services.user_access_profile(uid)['auth_stamp'], last_activity_at=time.time(), csrf_token='full-audit-browser'))
        server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        node = Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Microsoft VS Code/Code.exe'
        try:
            for label, script in stages:
                out = output / label
                out.mkdir(parents=True, exist_ok=True)
                settings = dict(base=f'http://127.0.0.1:{server.server_port}', cookie=cookie, out=str(out.resolve()),
                    questions=QUESTIONS, real_model=False, section='all', thickness_id=thickness_id,
                    today=date.today().isoformat(), audit=False, pe_thresholds=pe_thresholds,
                    correction_targets=correction_targets)
                gate = threading.Event()
                if label == 'pdf-fluid-queue':
                    gate_file = out / 'release-queue.signal'
                    gate_file.unlink(missing_ok=True)
                    settings['gate_file'] = str(gate_file.resolve())
                    def hold():
                        if not gate.wait(120):
                            raise RuntimeError('Browser queue audit deadline')
                        return {}, 200
                    queue = app.extensions['text_to_sql_model_queue']
                    blocker = queue.submit('full-audit-blocker', hold)
                    fillers = [queue.submit('full-audit-filler-' + str(i), lambda: ({}, 200)) for i in (1, 2)]
                    def release():
                        while not gate.wait(.1):
                            if gate_file.exists():
                                gate.set()
                    watcher = threading.Thread(target=release, daemon=True)
                    watcher.start()
                try:
                    print('Browser stage started: ' + label, flush=True)
                    result = subprocess.run([str(node) if node.is_file() else 'node', script],
                        input=json.dumps(settings), text=True, encoding='utf-8', capture_output=True,
                        env=dict(os.environ, ELECTRON_RUN_AS_NODE='1'), timeout=480)
                    (out / 'stdout.txt').write_text(result.stdout, encoding='utf-8')
                    (out / 'stderr.txt').write_text(result.stderr, encoding='utf-8')
                    if result.returncode:
                        raise RuntimeError('Browser audit failed at ' + label + '; inspect local report')
                    print('Browser stage passed: ' + label, flush=True)
                finally:
                    gate.set()
                    if label == 'pdf-fluid-queue':
                        watcher.join(3)
                        queue.wait(blocker, 'full-audit-blocker')
                        for i, key in enumerate(fillers, 1):
                            queue.wait(key, 'full-audit-filler-' + str(i))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(5)
    print('PASS: all screen audit stages; temporary server, account and schema removed.', flush=True)


if __name__ == '__main__':
    main()
