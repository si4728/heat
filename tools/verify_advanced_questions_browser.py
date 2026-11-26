"""Real browser checks; a temporary schema/account only, never production grants."""
import argparse
import json
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
from werkzeug.serving import make_server,WSGIRequestHandler
from customer_clone import customer_clone
from iris2.app import create_app
from iris2.application import text_to_sql_commentary as commentary
from iris2.tools.audit_customer_requirements_20261126 import QUESTIONS


class QuietHandler(WSGIRequestHandler):
    def log_request(self,*args,**kwargs):pass


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real-aggregate-model',action='store_true',help='Use real local inference for team/inspection results')
    args=parser.parse_args()
    out=Path('reports/advanced-questions-20261126/browser');out.mkdir(parents=True,exist_ok=True)
    real_generate=commentary.generate
    def generate(facts):
        if args.real_aggregate_model and facts.get('scope_label'):return real_generate(facts)
        return dict(status='generated',text='브라우저 시험용 의견 · 실제 조회 데이터는 표에서 확인합니다.',model='TEST_STUB')
    with customer_clone(temporary_readers=True) as (engine,schema),patch.object(commentary,'generate',side_effect=generate):
        app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
        with engine.connect() as c:uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
        session=dict(user_id=uid,last_activity_at=time.time(),csrf_token='advanced-browser-check')
        cookie=app.session_interface.get_signing_serializer(app).dumps(session)
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        settings=dict(base=f'http://127.0.0.1:{server.server_port}',cookie=cookie,out=str(out.resolve()),
            questions=QUESTIONS,real_model=args.real_aggregate_model)
        node=Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Microsoft VS Code/Code.exe'
        try:
            result=subprocess.run([str(node) if node.is_file() else 'node','tools/verify_advanced_questions_browser.mjs'],
                input=json.dumps(settings),text=True,encoding='utf-8',capture_output=True,
                env=dict(os.environ,ELECTRON_RUN_AS_NODE='1'),timeout=480)
            (out/'stdout.txt').write_text(result.stdout,encoding='utf-8');(out/'stderr.txt').write_text(result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError('Advanced browser checks failed; inspect local report')
            print(result.stdout,flush=True)
        finally:server.shutdown();server.server_close();thread.join(5)
    print('Temporary account/schema and server removed; production permissions and port unchanged.',flush=True)

if __name__=='__main__':main()
