"""UI/HTTP smoke test with explicit fixture data; no DB, model or service startup."""
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from unittest.mock import patch
from werkzeug.serving import make_server, WSGIRequestHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.application import text_to_sql_equipment as equipment, text_to_sql_fluids as fluids


class QuietHandler(WSGIRequestHandler):
    def log_request(self,*args,**kwargs):pass


def main():
    root=Path(__file__).resolve().parents[1]
    out=root/'reports/text-sql-enhancements-20261127';out.mkdir(parents=True,exist_ok=True)
    master=dict(heat_exchanger_id=1,unit_code='VCM1',equipment_tag='E-TEST-1',equipment_code='TEST-1',equipment_name='브라우저 검증용 설비')
    profile=dict(user_id=1,username='검증 계정',is_admin=True,is_active=True)
    profile['auth_stamp'] = 'enhancement-test-profile'
    row=dict(master,exchanger_code='E-TEST-1',maximum_loss=35,remaining_display='4.0년',remaining_life_years=4,
             tube_material='Cu-Ni',recommendation_date='2027-01-01',matching_tube_count=2,calculation_date='2026-11-27')
    def equipment_result(*args):
        return dict(query_kind='equipment_analysis',columns=['unit_code','exchanger_code','tube_material','maximum_loss','remaining_display'],
            rows=[row],result_count=1,matched_count=1,limit_reached=False,filter_description=equipment.describe(args[1]),
            generated_at=datetime.now(timezone.utc).isoformat(),_commentary_facts={})
    def fluid_result(*args):
        return dict(query_kind='fluid_grouping',columns=['unit_code','equipment_tag','equipment_name','side_code','fluid_name'],
            rows=[dict(master,side_code='SHELL',fluid_name='STEAM')],result_count=1,settings=args[1],limit_reached=False,
            generated_at=datetime.now(timezone.utc).isoformat())
    with ExitStack() as stack:
        for target,value in [('iris2.services.initialize',None),('iris2.services.user_count',1),
                ('iris2.services.user_access_profile',profile),('iris2.services.active_theme_data',dict(preset_key='BLUE',background_color='#f4f6f8',label_color='#536170')),
                ('iris2.application.text_to_sql_service.catalog',[master])]:
            stack.enter_context(patch(target,return_value=value))
        stack.enter_context(patch.object(equipment,'execute',side_effect=equipment_result))
        stack.enter_context(patch('iris2.web.security.organization_catalog',return_value=dict(entries=[])))
        stack.enter_context(patch.object(fluids,'execute',side_effect=fluid_result))
        stack.enter_context(patch('iris2.application.text_to_sql_commentary.generate',return_value=dict(text='시험용 해설',model='TEST_STUB',status='generated')))
        app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
        cookie=app.session_interface.get_signing_serializer(app).dumps(dict(
            user_id=1, auth_stamp=profile['auth_stamp'], last_activity_at=time.time(), csrf_token='enhancement-test'))
        server=make_server('127.0.0.1',0,app,threaded=True,request_handler=QuietHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            node = shutil.which('node')
            env = os.environ.copy()
            if node is None:
                vscode = Path(env.get('LOCALAPPDATA', '')) / 'Programs/Microsoft VS Code/Code.exe'
                if not vscode.is_file():
                    raise RuntimeError('Node.js or VS Code is required for the browser check')
                node = str(vscode)
                env['ELECTRON_RUN_AS_NODE'] = '1'
            result=subprocess.run([node,'tools/verify_text_sql_enhancements_browser.mjs'],
                input=json.dumps(dict(base=f'http://127.0.0.1:{server.server_port}',cookie=cookie,out=str(out))),
                capture_output=True,text=True,encoding='utf-8',env=env,timeout=120)
            (out/'browser.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            if result.returncode:raise RuntimeError('Browser check failed; see local report')
            print(result.stdout)
            from openpyxl import load_workbook
            downloaded=load_workbook(out/'text-to-sql.xlsx')
            assert downloaded.active.cell(10,5).value=='STEAM'
            print('PASS: downloaded XLSX contains displayed fixture result; no live DB/model used.')
        finally:server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':main()
