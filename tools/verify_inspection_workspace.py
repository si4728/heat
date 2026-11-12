"""Read-only real web checks and optional rollback-only writes in an existing test schema."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))


def rollback_registration_check():
    from sqlalchemy import create_engine,select,func
    from sqlalchemy.engine import URL
    from sqlalchemy.orm import Session
    from iris2 import services
    from iris2.application import inspection_recommendations as plans
    from iris2.db_config import load_database_config
    from iris2.iris_v2_models import InspectionPlan,InspectionPlanTubeTarget,InspectionPlanEvent,AppUser
    cfg=load_database_config()
    schema='iris2_test_transition'
    engine=create_engine(URL.create('mysql+pymysql',username=cfg['user'],password=cfg['password'],
        host=cfg['host'],port=cfg['port'],database=schema,query={'charset':cfg['charset']}),hide_parameters=True)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('SELECT DATABASE()').scalar()==schema
        before=connection.exec_driver_sql('SELECT COUNT(*) FROM inspection_plan_v2').scalar()
        connection.rollback()
        transaction=connection.begin()
        session=Session(bind=connection,expire_on_commit=False)
        @contextmanager
        def same_session(*args,**kwargs):
            yield session
        try:
            with patch.object(plans,'session_scope',same_session),patch.object(services,'session_scope',same_session):
                user_id=session.scalar(select(func.min(AppUser.user_id)).where(AppUser.is_admin.is_(True),AppUser.is_active.is_(True)))
                rows=plans.recommended_plans_data(horizon='all')['rows']
                row=next(r for r in rows if not r['open_plan'] and plans.available_tubes(r['heat_exchanger_id']))
                tube=plans.available_tubes(row['heat_exchanger_id'])[0]
                payload=dict(heat_exchanger_id=str(row['heat_exchanger_id']),planned_date='2027-01-15',
                    tube_ids=[str(tube['tube_id'])],recommendation_horizon='all',recommendation_basis='measured')
                plan_id=plans.save_recommended_plan(payload,user_id)
                session.flush()
                assert session.scalar(select(func.count()).select_from(InspectionPlanTubeTarget).where(
                    InspectionPlanTubeTarget.inspection_plan_id==plan_id))==1
                assert session.scalar(select(func.count()).select_from(InspectionPlanEvent).where(
                    InspectionPlanEvent.inspection_plan_id==plan_id))==1
                try:plans.save_recommended_plan(payload,user_id)
                except ValueError:pass
                else:raise AssertionError('Duplicate plan was accepted')
                other=next(r for r in rows if r['heat_exchanger_id']!=row['heat_exchanger_id'] and not r['open_plan'])
                bad=dict(payload,heat_exchanger_id=str(other['heat_exchanger_id']))
                try:plans.save_recommended_plan(bad,user_id)
                except ValueError:pass
                else:raise AssertionError('Cross-equipment tube was accepted')
        finally:
            session.close()
            transaction.rollback()
        after=connection.exec_driver_sql('SELECT COUNT(*) FROM inspection_plan_v2').scalar()
        assert before==after
    engine.dispose()
    return dict(schema=schema,registration_and_target_and_event=True,duplicate_rejected=True,
                cross_equipment_rejected=True,rolled_back=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--integration',action='store_true',help='Write then roll back in existing iris2_test_transition only')
    args=parser.parse_args()
    from iris2 import dbapi
    from iris2.hx_configuration import DB_PATH
    from iris2.app import create_app
    from iris2.application.inspection_history import inspection_history_data
    from iris2.application.inspection_recommendations import recommended_plans_data
    out=ROOT/'reports/inspection-workspace-20261112';out.mkdir(parents=True,exist_ok=True)
    app=create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True})
    connection=dbapi.connect(DB_PATH,readonly=True)
    try:
        uid=connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        source_inspections=connection.execute('''SELECT COUNT(*) FROM iris_inspection i
            JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2') AND i.superseded_by_inspection_id IS NULL
            AND COALESCE(i.inspection_date,i.report_date) IS NOT NULL''').fetchone()[0]
        source_equipment=connection.execute('''SELECT COUNT(*) FROM heat_exchanger h
            JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2')''').fetchone()[0]
    finally:connection.rollback();connection.close()
    client=app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=uid,last_activity_at=time.time(),csrf_token='inspection-workspace-preview')
    checks=[]
    for name,url in [('yearly','/inspections/yearly'),('process','/inspections/process'),
                     ('plans','/inspection-plans'),('manage','/inspection-plans?manage=1')]:
        assert app.test_client().get(url).status_code==302
        response=client.get(url)
        assert response.status_code==200,(name,response.status_code)
        html=response.get_data(as_text=True)
        (out/f'{name}.html').write_text(html.replace('"/static/','"'+(ROOT/'static').as_uri()+'/'),encoding='utf-8')
        checks.append(dict(page=name,status=response.status_code,login_required=True))
    readonly_profile=dict(user_id=uid,username='workflow-reader',is_admin=False,is_active=True,
        permissions={'INSPECTIONS':dict(can_view=True,can_edit=False)})
    with patch('iris2.services.user_access_profile',return_value=readonly_profile):
        response=client.get('/inspection-plans')
        assert response.status_code==200 and 'class="recommendation-register"' not in response.get_data(as_text=True)
        assert client.post('/inspection-plans',data={'csrf_token':'inspection-workspace-preview',
            'registration_source':'recommendation'}).status_code==403
    checks.append(dict(page='readonly_permissions',get_allowed=True,registration_forbidden=True))
    history=inspection_history_data(mode='process')
    assert history['equipment_count']==source_equipment
    assert history['inspection_count']==source_inspections
    assert sum(r['inspection_count'] for r in history['rows'])==history['inspection_count']
    assert all(r['unit_code'] in ('VCM1','VCM2') for r in history['rows'])
    recs=recommended_plans_data()
    assert all(r['due_date']<=recs['cutoff'] for r in recs['rows'])
    unregistered=next((r for r in recs['rows'] if not r['open_plan']),None)
    if unregistered:
        response=client.get(f"/inspection-plans/recommended/{unregistered['heat_exchanger_id']}/tubes")
        assert response.status_code==200 and isinstance(response.json['tubes'],list)
        (out/'tubes.json').write_text(json.dumps(dict(response.json,heat_exchanger_id=unregistered['heat_exchanger_id']),ensure_ascii=False),encoding='utf-8')
    result=dict(checks=checks,history_equipment=history['equipment_count'],history_inspections=history['inspection_count'],
        recommended_equipment=len(recs['rows']),database_business_writes=False)
    if args.integration:
        result['test_schema']=rollback_registration_check()
        (out/'integration-validation.json').write_text(json.dumps(result['test_schema'],indent=2),encoding='utf-8')
    (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(f'Inspection workspace verification failed ({type(exc).__name__}); inspect local data and settings.')
        raise SystemExit(1)
