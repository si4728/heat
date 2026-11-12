"""Export local, read-only screen snapshots for the menu guide video."""
import base64
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2.app import create_app
from iris2.database import get_engine
from sqlalchemy import text

OUT = ROOT / 'outputs/menu_guide_20261026'
OUT.mkdir(parents=True, exist_ok=True)
app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
with get_engine().connect() as connection:
    admin = connection.scalar(text('SELECT MIN(user_id) FROM app_user WHERE is_active=1 AND is_admin=1'))
client = app.test_client()
with client.session_transaction() as session:
    session.update(user_id=admin, last_activity_at=time.time())

def inline(match):
    kind, path = match.group(1), match.group(2)
    response = client.get(path.replace('&amp;', '&'))
    if response.status_code != 200:
        return ''
    content = response.get_data(as_text=True)
    return '<style>' + content + '</style>' if kind == 'link' else '<script>' + content + '</script>'

routes = {'dashboard': '/', 'exchangers': '/exchangers?unit=VCM1',
          'inspections': '/inspections', 'analysis': '/analysis?unit=VCM1&exchanger_id=67',
          'maintenance': '/maintenance', 'settings': '/settings/wall-loss-colors'}
for name, route in routes.items():
    response = client.get(route)
    if response.status_code != 200:
        print(name, response.status_code)
        continue
    page = response.get_data(as_text=True)
    page = re.sub(r'<(link)\b[^>]*href="(/static/[^\"]+)"[^>]*>', inline, page)
    page = re.sub(r'<(script)\b[^>]*src="(/static/[^\"]+)"[^>]*>\s*</script>', inline, page)
    page = re.sub(r'<form\b', '<form onsubmit="return false"', page)
    page = re.sub(r'<input[^>]*name="csrf_token"[^>]*>', '', page)
    page = re.sub(r'<span class="current-user-id">.*?</span>', '<span class="current-user-id">안내 사용자</span>', page)
    page = page.replace('</head>', '<style>.user-profile,.user-info,.user-menu{visibility:hidden} a{pointer-events:none}</style></head>')
    (OUT / f'{name}.html').write_text(page, encoding='utf-8')
    print(name, response.status_code, len(page))
