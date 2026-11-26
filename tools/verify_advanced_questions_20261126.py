"""Read-only checks of all eight customer questions against the current app/DB."""
import json
import argparse
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from iris2 import services
from iris2.app import create_app
from iris2.database import get_engine
from iris2.tools.audit_customer_requirements_20261126 import QUESTIONS


def verify(engine,out):
    out.mkdir(parents=True,exist_ok=True)
    with engine.connect() as c:
        revisions=dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
        uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_active=1 AND is_admin=1'))
    app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
    client=app.test_client()
    with client.session_transaction() as session:session.update(user_id=uid,auth_stamp=services.user_access_profile(uid)['auth_stamp'],last_activity_at=time.time(),csrf_token='advanced-question-check')
    checks=[]
    for index,question in enumerate(QUESTIONS,1):
        started=time.monotonic()
        preview=client.post('/inspections/text-to-sql/generate',json=dict(question=question,result_unit='equipment'),headers={'X-CSRF-Token':'advanced-question-check'})
        entry=dict(number=index,question=question,preview_status=preview.status_code)
        if preview.status_code==200:
            response=client.post('/inspections/text-to-sql/execute',json=dict(token=preview.json['token']),headers={'X-CSRF-Token':'advanced-question-check'})
            result=(response.json or {}).get('result',{})
            entry.update(status=response.status_code,error=(response.json or {}).get('error'),rows=result.get('rows'),
                columns=result.get('columns'),result_unit=result.get('result_unit','equipment'),
                matched_count=result.get('matched_count'),matched_equipment_count=result.get('matched_equipment_count'),
                diagnostics=result.get('diagnostics'),basis_note=result.get('basis_note'))
        else:entry['error']=preview.json
        entry['duration_seconds']=round(time.monotonic()-started,3);checks.append(entry)
        print(json.dumps({key:entry.get(key) for key in ('number','preview_status','status','error','matched_count','result_unit','duration_seconds')},ensure_ascii=True),flush=True)
    with engine.connect() as c:
        unchanged=revisions==dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
    report=dict(passed=all(r.get('status')==200 for r in checks),business_revisions_unchanged=unchanged,checks=checks)
    (out/'api-checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],business_revisions_unchanged=unchanged)),flush=True)
    if not report['passed'] or not unchanged:raise SystemExit(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clone',action='store_true',help='Use a disposable schema and temporary SELECT-only test account')
    args=parser.parse_args()
    out=Path('reports/advanced-questions-20261126')
    if args.clone:
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
        from customer_clone import customer_clone
        with customer_clone(temporary_readers=True) as (engine,schema):verify(engine,out/'clone')
    else:verify(get_engine(),out)

if __name__=='__main__':main()
