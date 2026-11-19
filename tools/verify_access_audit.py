"""Verify actual local audit UI; transfer the session to Chrome through stdin only."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from sqlalchemy import select
from iris2.app import create_app
from iris2.database import get_engine
from iris2.iris_v2_models import AppUser


def main():
    app=create_app(dict(TESTING=True,AUTH_DISABLED=False,CSRF_ENABLED=True))
    with get_engine().connect() as connection:
        user_id=connection.scalar(select(AppUser.user_id).where(AppUser.is_admin.is_(True),AppUser.is_active.is_(True)).order_by(AppUser.user_id).limit(1))
    if not user_id:raise RuntimeError('An existing active administrator is required')
    client=app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=user_id,last_activity_at=time.time(),csrf_token=secrets.token_urlsafe(32))
    cookie=client.get_cookie(app.config['SESSION_COOKIE_NAME'])
    result=subprocess.run(['node','tools/verify_access_audit_browser.mjs'],
        input=json.dumps(dict(cookie=dict(name=cookie.key,value=cookie.value))),
        text=True,encoding='utf-8',capture_output=True,cwd=ROOT,timeout=180)
    out=ROOT/'reports/access-audit-20261119'
    out.mkdir(parents=True,exist_ok=True)
    (out/'browser-run.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:
        print(result.stderr)
        raise SystemExit(result.returncode)
    print(result.stdout)

if __name__=='__main__':main()
