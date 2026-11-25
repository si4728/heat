"""Run browser UAT only against an ephemeral, disposable MariaDB copy."""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from sqlalchemy import text
from werkzeug.serving import make_server
from customer_clone import customer_clone
from iris2.app import create_app
from iris2.hx_configuration import PDF_REPORT_DIR
from iris2.application.customer_corrections_20261124 import correct
from iris2.migration.plugging_operations import apply_migration


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('reports/customer-completion-20261124/browser'))
    parser.add_argument('--audit-conditions',action='store_true')
    args=parser.parse_args()
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    with customer_clone() as (engine,schema):
        apply_migration(engine);correct(engine,PDF_REPORT_DIR,apply=True)
        with patch('iris2.web.routes.text_to_sql.commentary.generate',return_value=dict(
                text='브라우저 시험용 의견입니다. 계산값은 실제 복제 DB에서 조회했습니다.',model='TEST_STUB',status='generated')):
            app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
            with engine.connect() as c:uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_active=1 AND is_admin=1'))
            server=make_server('127.0.0.1',0,app,threaded=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            session={'user_id':uid,'last_activity_at':time.time(),'csrf_token':'isolated-browser-test'}
            cookie=app.session_interface.get_signing_serializer(app).dumps(session)
            from datetime import datetime,timedelta,timezone
            settings=dict(base=f'http://127.0.0.1:{server.server_port}',cookie=cookie,out=str(out.resolve()),audit=args.audit_conditions,
                today=datetime.now(timezone(timedelta(hours=9))).date().isoformat())
            node=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Microsoft VS Code/Code.exe'
            executable=str(node) if node.is_file() else 'node'
            env=dict(os.environ,ELECTRON_RUN_AS_NODE='1')
            try:
                result=subprocess.run([executable,'tools/verify_customer_completion_browser.mjs'],input=json.dumps(settings),
                    text=True,encoding='utf-8',stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,timeout=240)
                (out/'stdout.txt').write_text(result.stdout,encoding='utf-8')
                (out/'stderr.txt').write_text(result.stderr,encoding='utf-8')
                if result.returncode:raise RuntimeError('Browser UAT failed; inspect the local browser report')
                print(result.stdout)
            finally:
                server.shutdown();server.server_close();thread.join(5)
    print('Disposable test server and schema removed; production port 4824 was not started')

if __name__=='__main__':main()
