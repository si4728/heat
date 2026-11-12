"""Run the authenticated UI against existing isolated integration schemas only."""
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import db_config

original = db_config.load_database_config
settings = original()
settings['name'] = 'iris2_test_transition'
def demo_config(**kwargs):
    return dict(settings)
db_config.load_database_config = demo_config
from iris2 import dbapi
dbapi.load_database_config_schemas = lambda: {key: value + '_test_transition' for key, value in dbapi.SCHEMAS.items()}
from iris2.app import create_app
from iris2.database import get_engine
from iris2.application.auth_service import save_user
from sqlalchemy import text

app = create_app({'TESTING': False, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
with get_engine().connect() as conn:
    assert conn.scalar(text('SELECT DATABASE()')) == 'iris2_test_transition'
    assert conn.scalar(text('SELECT COUNT(*) FROM heat_exchanger')) > 0
password = secrets.token_urlsafe(24) + 'Aa1!'
username = 'video.guide.' + secrets.token_hex(3) + '@example.test'
save_user({'username': username, 'display_name': '영상 시연 관리자',
           'password': password, 'password_confirm': password,
           'is_active': '1', 'is_admin': '1'})
out = ROOT / 'outputs/menu_demo_v2'
out.mkdir(parents=True, exist_ok=True)
(out / 'session.private.json').write_text(json.dumps({'username': username, 'password': password}), encoding='utf-8')
print('Authenticated demo ready on 127.0.0.1:4831; all four stores use _test_transition schemas.', flush=True)
app.run(host='127.0.0.1', port=4831, debug=False, use_reloader=False)
