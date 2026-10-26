"""One scheduler tick for an external Windows Task Scheduler, if configured."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.backup_manager import run_due_backup,backup_schedule_status
from iris2.db_config import APP_DIR
try:
    result=run_due_backup(APP_DIR,APP_DIR/'data/heat_exchanger_db3.db')
    print(json.dumps({'result':result.get('status') if result else 'NOT_DUE_OR_BUSY','schedule':backup_schedule_status(APP_DIR)}))
    raise SystemExit(1 if result and result.get('status')=='FAILED' else 0)
except Exception:
    print(json.dumps({'result':'SCHEDULER_CHECK_FAILED'}))
    raise SystemExit(1)
