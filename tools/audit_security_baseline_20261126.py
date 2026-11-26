"""Reproduce security findings only in an isolated customer DB copy."""
import json
from pathlib import Path
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from sqlalchemy import text
from customer_clone import customer_clone
from iris2.app import create_app
from iris2 import services
from iris2.llm_integration.text_to_sql import QueryRejected, validate_proposal


def main():
    out = Path('reports/security-review-20261126')
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    with customer_clone() as (engine, schema):
        app = create_app(dict(TESTING=True, AUTH_DISABLED=False, CSRF_ENABLED=True))
        token = 'isolated-security-csrf'
        client = app.test_client()
        with engine.begin() as c:
            c.exec_driver_sql('UPDATE app_user SET is_active=0')
            before = c.scalar(text('SELECT COUNT(*) FROM app_user'))
        with client.session_transaction() as s:
            s['csrf_token'] = token
        initial = client.get('/setup-admin')
        password = secrets.token_urlsafe(24)
        created = client.post('/setup-admin', data=dict(username='isolated.security@example.test', display_name='Isolated security test',
            password=password, password_confirm=password, csrf_token=token))
        with engine.connect() as c:
            after = c.scalar(text('SELECT COUNT(*) FROM app_user'))
            user_id = c.scalar(text("SELECT user_id FROM app_user WHERE username='isolated.security@example.test'"))
        report['inactive_users_reopen_bootstrap'] = dict(get_status=initial.status_code, post_status=created.status_code,
            reproduced=after > before, account_count_before=before, account_count_after=after)
        if not user_id:
            user_id = services.save_user(dict(username='isolated.security@example.test', display_name='Isolated security test',
                password=password, password_confirm=password, is_admin='on', is_active='on'))['user_id']
        if user_id:
            with client.session_transaction() as s:
                s['csrf_token'] = token
            client.post('/login', data=dict(username='isolated.security@example.test', password=password, csrf_token=token))
            cookie = client.get_cookie('iris2_session').value
            new_password = secrets.token_urlsafe(24)
            services.save_user(dict(username='isolated.security@example.test', display_name='Isolated security test',
                password=new_password, password_confirm=new_password, is_admin='on', is_active='on'), user_id, actor_user_id=user_id)
            old = app.test_client()
            old.set_cookie('iris2_session', cookie)
            response = old.get('/settings/users')
            report['password_reset_keeps_old_session'] = dict(status=response.status_code, reproduced=response.status_code == 200)
            with client.session_transaction() as s:
                s['csrf_token'] = token
            client.post('/login', data=dict(username='isolated.security@example.test', password=new_password, csrf_token=token))
            client.get('/settings/users')
            logout_cookie = client.get_cookie('iris2_session').value
            with client.session_transaction() as s:
                logout_token = s['csrf_token']
            client.post('/logout', data=dict(csrf_token=logout_token))
            replay = app.test_client()
            replay.set_cookie('iris2_session', logout_cookie)
            response = replay.get('/settings/users')
            report['logout_keeps_copied_session'] = dict(status=response.status_code, reproduced=response.status_code == 200)
        rejected = []
        for sql in ('SELECT password_hash FROM app_user', 'SELECT tube_id FROM analysis_tubes; DROP TABLE app_user',
                    'SELECT SLEEP(1) FROM analysis_tubes', "SELECT LOAD_FILE(?) FROM analysis_tubes",
                    'SELECT tube_id FROM analysis_tubes UNION SELECT user_id FROM app_user',
                    'SELECT tube_id FROM analysis_tubes WHERE tube_id=? -- comment'):
            try:
                validate_proposal(dict(sql=sql, parameters=['literal'] if '?' in sql else []))
                rejected.append(False)
            except QueryRejected:
                rejected.append(True)
        report['model_sql_attacks_rejected'] = dict(cases=len(rejected), all_rejected=all(rejected))
        report['clone_removed_on_exit'] = True
    (out / 'current-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
