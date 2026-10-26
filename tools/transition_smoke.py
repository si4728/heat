"""Authenticated, read-only route sweep on migrated MariaDB."""
import json,sys,time,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.app import create_app
from iris2.database import get_engine
from sqlalchemy import text
root=Path(__file__).resolve().parents[1]
app=create_app({'TESTING':True,'AUTH_DISABLED':False})
with get_engine().connect() as conn:
    admin=conn.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
    exchanger=conn.scalar(text('SELECT heat_exchanger_id FROM iris_inspection WHERE superseded_by_inspection_id IS NULL ORDER BY iris_inspection_id LIMIT 1'))
    inspection=conn.scalar(text('SELECT MIN(iris_inspection_id) FROM iris_inspection'))
    tube=conn.scalar(text('SELECT MIN(tube_id) FROM heat_exchanger_tube'))
results=[]
client=app.test_client()
with client.session_transaction() as session:
    session['user_id']=admin;session['last_activity_at']=time.time()
for rule in app.url_map.iter_rules():
    if 'GET' not in rule.methods or rule.endpoint in {'static','setup_admin','inspection_pdf_view','pdf_report_view','work_order_detail','pdf_ocr_source','export_heat_exchangers_tubes'}:continue
    url=rule.rule.replace('<int:exchanger_id>',str(exchanger)).replace('<int:inspection_id>',str(inspection)).replace('<int:tube_id>',str(tube))
    if '<' in url:continue
    if rule.endpoint=='pdf_ocr_review_dashboard':
        with get_engine().connect() as conn:
            allowed=conn.scalar(text("SELECT user_id FROM app_user WHERE username='silicon@gmail.com' AND is_active=1"))
        if allowed:
            with client.session_transaction() as session:session['user_id']=allowed
    else:
        with client.session_transaction() as session:session['user_id']=admin
    started=time.monotonic()
    try:
        response=client.get(url)
        entry={'url':url,'status':response.status_code,'seconds':round(time.monotonic()-started,3)}
    except Exception as exc:
        entry={'url':url,'status':500,'error':type(exc).__name__,'detail':str(exc)[:500]}
    results.append(entry)
    print(json.dumps(entry),flush=True)
(root/'reports/mariadb_transition/route_smoke.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print('FAILURES',sum(item['status']>=400 and not (item['url']=='/imports/pdf-review' and item['status']==403) for item in results))
