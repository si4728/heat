"""Exercise real local SQL inference and commentary in one queue on a disposable DB."""
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from customer_clone import customer_clone
from iris2.app import create_app
from iris2.application import text_to_sql_service as service
from iris2.iris_v2_models import AppUser, UserScreenPermission
from iris2.llm_integration.model_config import load_local_runtime_config


def main():
    out=Path('reports/requirements-recheck-20261126');out.mkdir(parents=True,exist_ok=True)
    config=load_local_runtime_config(Path('llm_integration/models.local.json'))
    report=dict(model=config.models[config.default_model_key].model_name,observations=[])
    with customer_clone() as (engine,schema):
        with Session(engine) as s:
            owner=s.scalar(select(AppUser.user_id).where(AppUser.is_active.is_(True),AppUser.is_admin.is_(True)).limit(1))
            reader=AppUser(username='audit_'+uuid4().hex[:12],display_name='Isolated audit reader',password_hash='disabled-test-account',is_admin=False,is_active=True)
            s.add(reader);s.flush();reader_id=reader.user_id
            s.add_all([UserScreenPermission(user_id=reader_id,screen_key=key,can_view=True,can_edit=False)
                       for key in ('TEXT_TO_SQL','INSPECTIONS','EXCHANGERS','REMAINING_LIFE')]);s.commit()
        app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
        def client(uid):
            c=app.test_client()
            with c.session_transaction() as s:s.update(user_id=uid,last_activity_at=time.time(),csrf_token='live-queue-audit')
            return c
        first,second=client(owner),client(reader_id)
        def post(c,action,**data):
            return c.post('/inspections/text-to-sql/'+action,json=data,headers={'X-CSRF-Token':'live-queue-audit'})
        preview=post(second,'generate',question='E-106 열교환기 잔여수명과 차기 검사 권고일',result_unit='equipment',exchanger_ids=[151])
        assert preview.status_code==200,preview.json
        result=post(second,'execute',token=preview.json['token'])
        assert result.status_code==200,result.json
        summary_token=result.json['result']['summary_token']
        catalog=service.catalog()
        pe=next(r for r in catalog if r['unit_code']=='PE' and 'E-331B' in r['equipment_tag'])
        rounds=service.inspections(pe['heat_exchanger_id'])
        generation=post(first,'generate',question='검사 결과 요약',result_unit='tube',
            exchanger_id=pe['heat_exchanger_id'],inspection_id=rounds[0]['iris_inspection_id'],async_model=True)
        assert generation.status_code==202,generation.json
        commentary=post(second,'summarize',token=summary_token,async_model=True)
        assert commentary.status_code==202,commentary.json
        jobs=[(first,generation.json['model_job']),(second,commentary.json['model_job'])]
        report['summary_initial_state']=jobs[1][1]['state'];report['summary_initial_position']=jobs[1][1]['position']
        report['other_user_denied']=first.get(jobs[1][1]['status_url']).status_code==404
        queue=app.extensions['text_to_sql_model_queue']
        fillers=[queue.submit('audit-'+str(i),lambda:({},200)) for i in (1,2)]
        overflow=post(second,'summarize',token=summary_token,async_model=True)
        report['overflow_status']=overflow.status_code;report['overflow_error']=overflow.json.get('error')
        deadline=time.monotonic()+270;completed={};last=None
        while len(completed)<2 and time.monotonic()<deadline:
            snapshot=[]
            for index,(c,job) in enumerate(jobs):
                state=c.get(job['status_url']).json['model_job'];snapshot.append(state['state'])
                if state['state'] in ('succeeded','failed'):completed[index]=state
            if snapshot!=last:
                report['observations'].append(snapshot);print(json.dumps(dict(states=snapshot)),flush=True);last=snapshot
            time.sleep(.75)
        assert len(completed)==2,'Actual model request deadline exceeded'
        for index,kind in [(0,'sql'),(1,'commentary')]:
            state=completed[index];payload=state.get('result',{})
            report[kind]=dict(state=state['state'],http_status=state.get('http_status'),error=payload.get('error'))
            if kind=='commentary' and state['state']=='succeeded':
                report[kind].update(model=payload['commentary']['model'],sections=[s['title'] for s in payload['commentary'].get('sections',[])])
            elif kind=='sql' and state['state']=='succeeded':
                execution=post(first,'execute',token=payload['token'])
                report[kind]['execute_status']=execution.status_code
        for i,key in enumerate(fillers,1):queue.wait(key,'audit-'+str(i))
        report['passed']=(report['other_user_denied'] and report['overflow_status']==429
            and report['summary_initial_state']=='queued' and all(completed[i]['state']=='succeeded' for i in (0,1)))
    (out/'live-model-queue.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'],model=report['model'],sql=report['sql'],commentary=report['commentary']),ensure_ascii=True),flush=True)

if __name__=='__main__':main()
