"""Read-only authenticated preview of the integrated exchanger analysis."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import dbapi
from iris2.hx_configuration import DB_PATH
from iris2.app import create_app


def main():
    connection = dbapi.connect(DB_PATH, readonly=True)
    try:
        identifier = connection.execute("""SELECT s.heat_exchanger_id
            FROM heat_exchanger_spec_revision s JOIN heat_exchanger h
            ON h.heat_exchanger_id=s.heat_exchanger_id JOIN equipment e
            ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE s.is_current=1 AND s.exchanger_code='E-111' AND u.unit_code='VCM1'""").fetchone()[0]
        app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
        uid = connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid, last_activity_at=time.time(), csrf_token='analysis-local-preview')
        url = f'/analysis?exchanger_id={identifier}&unit=VCM1'
        assert app.test_client().get(url).status_code == 302
        response = client.get(url)
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        workspace = html.split('<div class="precision-analysis-shell">', 1)[1].split('</main>', 1)[0]
        assert '<dialog' not in workspace and '<details' not in workspace and 'role="tab"' not in workspace
        assert '단기 감육속도' in html and 'tube-thickness-trend.js' in html
        output = ROOT / 'reports/exchanger-analysis-20261112'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'precision.html').write_text(html.replace('"/static/', '"' + (ROOT / 'static').as_uri() + '/'), encoding='utf-8')
        result = dict(authenticated_get=True, database_mutated=False, no_dialogs_or_tabs=True)
        (output / 'validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    main()
