"""Authenticated Flask/MariaDB/model integration; no business data writes."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from sqlalchemy import text
from iris2.app import create_app
from iris2.database import get_engine


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--browser-session',action='store_true',help='Write temporary private browser cookie; delete after browser check')
    args=parser.parse_args()
    app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
    with get_engine().connect() as connection:
        uid=connection.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
    if not uid:
        raise RuntimeError('Active administrator required')
    client=app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=uid,last_activity_at=time.time(),csrf_token='text-sql-web-verification')
    report={'checks':[]}
    def record(name,condition):
        report['checks'].append({'name':name,'passed':bool(condition)})
        print(name, bool(condition),flush=True)
        if not condition: raise AssertionError(name)
    anonymous=app.test_client().get('/inspections/text-to-sql')
    record('anonymous_login_required',anonymous.status_code==302)
    page=client.get('/inspections/text-to-sql')
    record('page_and_menu',page.status_code==200 and 'href="/inspections/text-to-sql"' in page.get_data(as_text=True))
    out=ROOT/'.taste-skill/text-to-sql'
    out.mkdir(parents=True,exist_ok=True)
    (out/'web-snapshot.html').write_text(page.get_data(as_text=True),encoding='utf-8')
    record('csrf_required',client.post('/inspections/text-to-sql/generate',json={}).status_code==400)
    rounds=client.get('/inspections/text-to-sql/inspections?exchanger_id=151')
    record('real_inspection_catalog',rounds.status_code==200 and any(r['iris_inspection_id']==389 for r in rounds.json['inspections']))
    start=time.monotonic()
    preview=client.post('/inspections/text-to-sql/generate',json={
        'exchanger_id':151,'inspection_id':389,'question':'검사 결과를 요약해 줘.'},
        headers={'X-CSRF-Token':'text-sql-web-verification'})
    record('real_model_sql_preview',preview.status_code==200 and 'token' in preview.json)
    report['generation_seconds']=round(time.monotonic()-start,2)
    report['proposal']=preview.json['proposal']
    executed=client.post('/inspections/text-to-sql/execute',json={'token':preview.json['token']},
        headers={'X-CSRF-Token':'text-sql-web-verification'})
    record('real_sql_execution',executed.status_code==200 and executed.json['result']['rows'][0]['inspected_tubes']==82)
    report['result']=executed.json['result']
    report['generation_seconds']=round(time.monotonic()-start,2)
    dest=ROOT/'reports/text_to_sql/web_validation.json'
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    if args.browser_session:
        cookie=client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        dest=ROOT/'tmp/text_to_sql_browser_session.json'
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(json.dumps({'name':cookie.key,'value':cookie.value}),encoding='utf-8')
        print('Temporary browser session prepared (not printed).',flush=True)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
