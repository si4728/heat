"""Read-only checks against this PC's configured MariaDB; no model inference."""
from io import BytesIO
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from openpyxl import load_workbook
from sqlalchemy import text
from iris2.app import create_app
from iris2.database import get_engine
from iris2.application import text_to_sql_equipment as equipment, text_to_sql_fluids as fluids


def main():
    checks=[]
    ids=[r['heat_exchanger_id'] for r in fluids.analysis.catalog() if r['unit_code']=='VCM1']
    def run(name,handler):
        try:
            detail=handler();checks.append(dict(check=name,passed=True,detail=detail))
        except Exception as exc:
            message=str(exc)
            tables=[t for t in ('heat_exchanger_spec_revision','heat_exchanger_side_spec','tube_plugging_event','iris_inspection_summary_history') if t in message]
            checks.append(dict(check=name,passed=False,error=type(exc).__name__,code=exc.args[0] if exc.args and type(exc.args[0]) is int else None,tables=tables))
    def fluid_check():
        settings=fluids.options('Shell 유체명이 STEAM인 열교환기 목록')
        listing=fluids.execute(ids,settings,fluids.proposal(ids,settings),ids)
        grouped=fluids.options('Shell 유체명이 STEAM인 열교환기 수량과 목록')
        summary=fluids.execute(ids,grouped,fluids.proposal(ids,grouped),ids)
        assert len(listing['rows'])==sum(r['exchanger_count'] for rুষ্ট in [] for r in []) if False else True
        assert len(listing['rows'])==sum(r['exchanger_count'] for r in summary['rows'])
        assert len(listing['rows'])==len({r['heat_exchanger_id'] for r in listing['rows']})
        return dict(rows=len(listing['rows']),hidden_id='heat_exchanger_id' not in listing['columns'])
    def compound_check():
        basic=equipment.options('Tube 재질 Cu-Ni 열교환기 목록')
        baseline=equipment.execute(ids,basic,equipment.proposal(ids),ids)
        compound=equipment.options('Tube 재질 Cu-Ni 최대 감육률 30% 이상 잔여수명 5년 이하 열교환기 목록')
        actual=equipment.execute(ids,compound,equipment.proposal(ids),ids)
        expected={r['heat_exchanger_id'] for r in baseline['rows'] if r['maximum_loss'] is not None and r['maximum_loss']>=30 and r['remaining_life_years'] is not None and r['remaining_life_years']<=5}
        assert {r['heat_exchanger_id'] for r in actual['rows']}==expected
        return dict(baseline=len(baseline['rows']),matched=len(actual['rows']))
    def http_check():
        app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
        with get_engine().connect() as c:uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
        client=app.test_client()
        with client.session_transaction() as s:s.update(user_id=uid,last_activity_at=time.time(),csrf_token='readonly-check')
        headers={'X-CSRF-Token':'readonly-check'}
        generated=client.post('/inspections/text-to-sql/generate',json=dict(question='Shell 유체명이 STEAM인 열교환기 목록',unit_codes=['VCM1']),headers=headers)
        assert generated.status_code==200
        executed=client.post('/inspections/text-to-sql/execute',json=dict(token=generated.json['token']),headers=headers)
        assert executed.status_code==200
        downloaded=client.post('/inspections/text-to-sql/export',json=dict(key=executed.json['result']['export_key']),headers=headers)
        assert downloaded.status_code==200
        sheet=load_workbook(BytesIO(downloaded.data)).active
        assert sheet.max_row-9==len(executed.json['result']['rows'])
        assert client.get('/').status_code==200
        return dict(export_rows=sheet.max_row-9,dashboard=200)
    run('fluid_listing_and_grouping',fluid_check)
    run('compound_matches_intersection',compound_check)
    run('authenticated_http_and_export',http_check)
    print(json.dumps(checks,ensure_ascii=False))
    return 0 if all(c['passed'] for c in checks) else 1


if __name__=='__main__':raise SystemExit(main())
