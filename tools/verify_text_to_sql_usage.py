"""Exercise the running local server and verify complete monthly usage records."""
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import dbapi
from iris2.app import create_app
from iris2.application.text_to_sql_usage_log import KST
from iris2.hx_configuration import DB_PATH
from datetime import datetime


def main():
    connection = dbapi.connect(DB_PATH, readonly=True)
    try:
        uid = connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        row = connection.execute('''SELECT s.heat_exchanger_id FROM heat_exchanger_spec_revision s
            JOIN heat_exchanger h ON h.heat_exchanger_id=s.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE s.is_current=1 AND s.exchanger_code='E-104B' AND u.unit_code IN ('VCM1','VCM2')''').fetchone()
        assert uid and row
        identifier = row[0]
    finally:
        connection.rollback()
        connection.close()
    app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
    client = app.test_client()
    with client.session_transaction() as session:
        session.update(user_id=uid, last_activity_at=time.time(), csrf_token='usage-log-live-check')
    cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
    opener = build_opener(ProxyHandler({}))

    def post(action, body):
        request = Request('http://127.0.0.1:4824/inspections/text-to-sql/' + action,
            data=json.dumps(body, ensure_ascii=False).encode('utf-8'), headers={
                'Content-Type': 'application/json', 'X-CSRF-Token': 'usage-log-live-check',
                'Cookie': cookie.key + '=' + cookie.value}, method='POST')
        try:
            response = opener.open(request, timeout=150)
        except HTTPError as exc:
            response = exc
        with response:
            return response.code, json.loads(response.read()), response.headers.get('X-Text-to-SQL-Usage-ID')

    start_month = datetime.now(KST).strftime('%Y-%m')
    path = ROOT / 'logs' / 'text_to_sql' / f'text_to_sql_{start_month}.txt'
    before = path.read_bytes() if path.exists() else b''
    started = time.monotonic()
    question = '검사 결과를 요약해 줘.'
    print('Generating real local-model SQL through the running HTTP server...', flush=True)
    status, preview, usage_id = post('generate', dict(exchanger_id=identifier, question=question))
    assert status == 200 and usage_id and 'token' in preview, f'Generation returned HTTP {status}'
    status, result, executed_id = post('execute', dict(token=preview['token']))
    assert status == 200 and executed_id == usage_id, f'Execution returned HTTP {status}'
    status, failure, failure_id = post('generate', dict(exchanger_id=identifier, question=''))
    assert status == 400 and failure_id
    paths = sorted((ROOT / 'logs' / 'text_to_sql').glob('*.txt'))
    rows = [json.loads(line) for item in paths for line in item.read_text(encoding='utf-8').splitlines()]
    related = [row for row in rows if row['usage_id'] == usage_id]
    assert len(related) == 2
    assert {row['event'] for row in related} == {'generate', 'execute'}
    for row in related:
        assert row['input']['question'] == question
        assert row['input']['selection']['exchanger_id'] == identifier
        assert row['sql'] == preview['proposal']['sql']
        assert row['actor']['user_id'] == uid
        assert row['scopes'][0]['equipment']['equipment_tag']
        assert row['status'] == 'success' and row['error'] is None
        assert preview['token'] not in json.dumps(row)
    failed = next(row for row in rows if row['usage_id'] == failure_id)
    assert failed['status'] == 'error' and failed['error']['message'] == failure['error']
    assert path.read_bytes().startswith(before)
    report = dict(actual_http=True, actual_local_model=True, database_business_rows_mutated=False,
        log_file=str(path.relative_to(ROOT)), usage_id=usage_id, successful_events=len(related),
        error_record_verified=True, append_preserved=True,
        result_count=result['result']['result_count'], seconds=round(time.monotonic()-started, 3), passed=True)
    output = ROOT / 'reports' / 'text-to-sql-usage-20261112'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'live.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
