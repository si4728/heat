"""Current requirement audit: read-only application requests and isolated boundary inputs."""
from datetime import date
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from iris2 import services
from iris2.app import create_app
from iris2.application.equipment_summary import build_equipment_summary
from iris2.application.text_to_sql_equipment import options
from iris2.database import get_engine
from iris2.domain.sample_wall_loss import estimate_sample_wall_loss

OUT=Path('reports/requirements-recheck-20261126')
QUESTIONS=[
 '공정별 차기 검사 권고일이 2027년 이내인 열교환기를 보여줘',
 '최근 두 번의 검사 사이 최대 감육률이 5%p 이상 증가한 열교환기는?',
 '감육속도가 0.1 mm/년 이상인 튜브가 있는 열교환기를 알려줘',
 'Plugging 20% 도달까지 10년 이내인 열교환기를 생산팀별로 세어줘',
 '검사 표본이 10본 미만이라 재검사 범위를 늘려야 하는 열교환기는?',
 'IRIS 적용 대상인데 최근 5년간 검사 이력이 없는 열교환기는?',
 'Tube 재질이 Cu-Ni인 열교환기 중 최대 감육률 상위 10대',
 'E-106의 검사 회차별 최대 감육률과 Plugging 수량 추이를 보여줘',
]


def boundary_cases():
    # An observed count above the limit is known even when a fitted quantile is lower.
    estimate=estimate_sample_wall_loss([0]*79+[40]*21,total_tube_count=100,
        installation_date='2010-01-01',measurement_date='2025-01-01')
    base=dict(status='CALCULATED',remaining_life_years=0,total_tube_count=100,
        allowable_plugging_count=20,actual_plugged_count=0,threshold_reached_count=21,
        registered_inspection_count=1,tube_projections=[],analysis_tube_rows=[],
        life_reached_year=2026,sample_wall_loss_estimate=estimate)
    summary=build_equipment_summary(base,date(2026,11,26))
    no_iris=dict(base,sample_wall_loss_estimate={},registered_inspection_count=0,
                 actual_plugged_count=21,threshold_reached_count=0)
    uninspected=build_equipment_summary(no_iris,date(2026,11,26))
    return dict(observed_limit_overridden=dict(observed_reached=21,allowed=20,
        model_status=estimate['status'],model_upper_loss=estimate.get('upper_20_wall_loss_percent'),
        displayed_years=summary['remaining_life_years'],displayed=summary['remaining_display'],
        reproduced=summary['remaining_life_years']>0),
        uninspected_with_operations=dict(registered_inspection_count=0,
            displayed_band=uninspected['band'],reproduced=uninspected['band']!='uninspected'))


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    with get_engine().connect() as c:
        before=dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
        uid=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_active=1 AND is_admin=1'))
    app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
    client=app.test_client()
    with client.session_transaction() as s:s.update(user_id=uid,last_activity_at=time.time(),csrf_token='requirement-review-only')
    def post(action,data):
        return client.post('/inspections/text-to-sql/'+action,json=data,headers={'X-CSRF-Token':'requirement-review-only'})
    samples=[]
    for question in QUESTIONS:
        response=post('generate',dict(question=question,result_unit='equipment'))
        samples.append(dict(question=question,status=response.status_code,
                            kind=(response.json or {}).get('query_kind'),error=(response.json or {}).get('error')))
    silent=[]
    for question in ('IRIS 미실시 열교환기를 보여줘','산정 불가 열교환기를 보여줘'):
        preview=post('generate',dict(question=question,result_unit='equipment'))
        item=dict(question=question,preview_status=preview.status_code,options=options(question))
        if preview.status_code==200:
            response=post('execute',dict(token=preview.json['token']))
            result=(response.json or {}).get('result',{})
            item.update(status=response.status_code,matched=result.get('matched_count'),
                        returned=result.get('result_count'),states=sorted({r.get('analysis_status','') for r in result.get('rows',[])}))
        silent.append(item)
    ranking=services.exchanger_wall_loss_ranking()
    selected=next(r for r in ranking['rows'] if r['heat_exchanger_id']==100)
    life=services.exchanger_detail(100)['remaining_life']
    inconsistent=[]
    for row in ranking['rows']:
        if row['unit_code'] not in ('PE','VCM1','VCM2') or not row.get('registered_inspection_count'):continue
        current=services.exchanger_detail(row['heat_exchanger_id'])['remaining_life']
        years=current['equipment_overview']['remaining_life_years']
        if current['status']=='CALCULATED' and current['remaining_life_years']==0 and years is not None and years>0:
            inconsistent.append(dict(id=row['heat_exchanger_id'],code=row.get('exchanger_code'),years=years))
    with get_engine().connect() as c:
        after=dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
        e111_source=[dict(r) for r in c.execute(text('SELECT i.iris_inspection_id,YEAR(COALESCE(i.inspection_date,i.report_date)) AS year,i.source_scope_code,r.wall_loss_percent FROM iris_tube_result r JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id WHERE i.iris_inspection_id=:iid AND r.wall_loss_percent=:loss LIMIT 1'),dict(iid=selected['iris_inspection_id'],loss=selected['wall_loss_percent'])).mappings()]
    report=dict(date='2026-11-26',samples=samples,silent_conditions=silent,boundaries=boundary_cases(),
        e111=dict(ranking_max=float(selected['wall_loss_percent']),ranking_inspection=selected['iris_inspection_id'],
            analysis_current_max=max(r['wall_loss_percent'] for r in life['analysis_tube_rows'] if r.get('wall_loss_percent') is not None),
            source=e111_source),actual_overrides=inconsistent,
        business_revisions_unchanged=before==after)
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,default=str))

if __name__=='__main__':main()
