"""Short five-session HTTP load check plus isolated database write contention."""
import sys,json,time,statistics,urllib.request,hashlib,datetime
from pathlib import Path
from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from iris2.app import create_app
from iris2.database import get_engine
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
ROOT=Path(__file__).resolve().parents[1]
app=create_app()
with get_engine().connect() as c:admin=c.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1'))
serializer=app.session_interface.get_signing_serializer(app)
barrier=Barrier(5)
paths=['/','/exchangers','/inspections','/remaining-life/tubes','/exports/heat-exchangers-tubes.xlsx','/api/health']

def user(index):
    cookie=serializer.dumps({'user_id':admin,'last_activity_at':time.time(),'load_session':index})
    records=[]
    barrier.wait(timeout=10)
    for path in paths:
        started=time.monotonic()
        try:
            request=urllib.request.Request('http://127.0.0.1:4824'+path,headers={'Cookie':'iris2_session='+cookie})
            with urllib.request.urlopen(request,timeout=90) as response:
                payload=response.read()
                records.append({'session':index,'path':path,'status':response.status,'seconds':round(time.monotonic()-started,3),'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest() if path.endswith('.xlsx') else None})
        except Exception as exc:
            records.append({'session':index,'path':path,'status':'ERROR','seconds':round(time.monotonic()-started,3),'error':type(exc).__name__})
    return records
started=time.monotonic()
with ThreadPoolExecutor(max_workers=5) as pool:rows=[row for group in pool.map(user,range(5)) for row in group]
http_wall=time.monotonic()-started
by_path={}
for path in paths:
    values=[row['seconds'] for row in rows if row['path']==path]
    by_path[path]={'requests':len(values),'average_seconds':round(statistics.mean(values),3),'max_seconds':max(values)}
# Use an existing restored test schema only; never send load-test writes to operational data.
engine=engine_for(load_database_config(),'iris2_test_transition')
write_barrier=Barrier(5)
def writer(index):
    samples=[];write_barrier.wait(timeout=10)
    for repetition in range(5):
        begin=time.monotonic()
        try:
            with engine.begin() as c:
                c.exec_driver_sql('UPDATE equipment SET equipment_name=equipment_name WHERE equipment_id=1')
            samples.append({'status':'COMMITTED','seconds':round(time.monotonic()-begin,3)})
        except Exception as exc:samples.append({'status':'ERROR','error':type(exc).__name__})
    return samples
with ThreadPoolExecutor(max_workers=5) as pool:writes=[row for group in pool.map(writer,range(5)) for row in group]
report={'time_kst':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),'sessions':5,'session_accounts':'one existing administrator account; five independent signed sessions','http_requests':len(rows),'http_errors':sum(row['status']!=200 for row in rows),'http_wall_seconds':round(http_wall,3),'by_path':by_path,'excel_same_content':len({row['sha256'] for row in rows if row['path'].endswith('.xlsx')})==1,'isolated_write_transactions':len(writes),'isolated_write_errors':sum(row['status']!='COMMITTED' for row in writes),'isolated_write_max_seconds':max(row.get('seconds',0) for row in writes),'details':rows,'writes':writes,'limits':'Short localhost test. Cached export. No WAN/mobile/long-duration or LLM inference performance guarantee.'}
(ROOT/'reports/mariadb_transition/five_sessions.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({key:value for key,value in report.items() if key not in ['details','writes']}))
