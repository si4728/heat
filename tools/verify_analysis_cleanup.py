"""Read-only MariaDB parity checks and authenticated UI preview exports."""
import json
import argparse
from pathlib import Path
import re
import sys
import subprocess
import time
from urllib.request import Request, build_opener, ProxyHandler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import services, dbapi
from iris2.app import create_app
from iris2.hx_configuration import DB_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-check', action='store_true', help='Compare the existing local server without restarting it.')
    parser.add_argument('--runtime-browser', action='store_true', help='Run browser checks against the existing local server with an in-memory session.')
    args = parser.parse_args()
    out = ROOT / 'reports/analysis-cleanup-20261119'
    out.mkdir(parents=True, exist_ok=True)
    connection = dbapi.connect(DB_PATH, readonly=True)
    try:
        data = services.dashboard_data()
        listed = services.list_exchangers()
        list_ids = {h.heat_exchanger_id for h, e, u, p in listed['rows'] if u.unit_code not in ('VCM3','VCM4')}
        assert {r['heat_exchanger_id'] for r in data['life_dashboard']['rows']} == list_ids
        inspected = services.list_exchangers(status='INSPECTED')
        inspected_ids = {h.heat_exchanger_id for h,e,u,p in inspected['rows'] if u.unit_code not in ('VCM3','VCM4')}
        assert inspected_ids <= list_ids
        statuses = connection.execute("""SELECT e.production_team_code, h.inspection_lifecycle_status, COUNT(*)
            FROM heat_exchanger h JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code NOT IN ('VCM3','VCM4')
            GROUP BY e.production_team_code, h.inspection_lifecycle_status""").fetchall()
        assert sum(count for team,status,count in statuses if status == 'INSPECTED') == len(inspected_ids)
        for group in data['life_dashboard']['groups']:
            assert group['total'] == sum(count for team,status,count in statuses if team == group['team'])
        annual = connection.execute("""SELECT c.campaign_year, e.production_team_code,
            COUNT(*), COUNT(DISTINCT i.heat_exchanger_id), COALESCE(SUM(i.extracted_tube_result_count),0)
            FROM iris_inspection i JOIN inspection_campaign c ON c.campaign_id=i.campaign_id
            JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code NOT IN ('VCM3','VCM4') GROUP BY c.campaign_year,e.production_team_code""").fetchall()
        assert {(r['year'],r['team'],r['inspection_count'],r['exchanger_count'],r['result_count'])
                for r in data['team_yearly_rows']} == {
                    (year,f'{team} 생산팀',inspections,exchangers,results)
                    for year,team,inspections,exchangers,results in annual}
        identifier = connection.execute("""SELECT s.heat_exchanger_id FROM heat_exchanger_spec_revision s
            JOIN heat_exchanger h ON h.heat_exchanger_id=s.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE s.is_current=1 AND s.exchanger_code='E-111' AND u.unit_code='VCM1'""").fetchone()[0]
        detail = services.precision_analysis_data(identifier, unit_code='VCM1')
        rows = detail['selected_detail']['remaining_life']['analysis_tube_rows']
        tube = next(r for r in rows if r['tube_no'] == '18-13')
        assert tube['selected_base_corrosion_rate_mm_per_year'] >= tube['long_term_corrosion_rate_mm_per_year']
        for row in rows:
            long = row.get('long_term_corrosion_rate_mm_per_year')
            trend = row.get('regression_corrosion_rate_mm_per_year')
            selected = row.get('selected_base_corrosion_rate_mm_per_year')
            if selected is not None and long is not None and long > 0:
                assert selected >= long, row['tube_no']
            if trend is not None and trend > 0:
                assert selected is not None and selected >= trend, row['tube_no']
        app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
        uid = connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid,auth_stamp=services.user_access_profile(uid)['auth_stamp'],last_activity_at=time.time(),csrf_token='cleanup-local-preview')
        for name, url in [('precision', f'/analysis?exchanger_id={identifier}&unit=VCM1'), ('dashboard','/'), ('exchangers','/exchangers')]:
            response = client.get(url)
            assert response.status_code == 200, (name,response.status_code)
            html = response.get_data(as_text=True)
            (out/f'{name}.html').write_text(html.replace('"/static/', '"'+(ROOT/'static').as_uri()+'/'),encoding='utf-8')
        result = dict(total=len(list_ids), inspected=len(inspected_ids),
            teams={g['team']:g['total'] for g in data['life_dashboard']['groups']},
            inspected_by_team={team: count for team,status,count in statuses if status == 'INSPECTED'},
            annual_team_parity=True, checked_tube_rates=len(rows),
            tube='18-13', long=tube['long_term_corrosion_rate_mm_per_year'],
            selected=tube['selected_base_corrosion_rate_mm_per_year'],
            basis=tube['corrosion_rate_selection_label'], database_mutated=False)
        if args.runtime_check or args.runtime_browser:
            cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
            request = Request(f'http://127.0.0.1:4824/analysis?exchanger_id={identifier}&unit=VCM1',
                headers={'Cookie': f'{cookie.key}={cookie.value}'})
            try:
                opener = build_opener(ProxyHandler({}))
                with opener.open(request, timeout=30) as response:
                    html = response.read().decode('utf-8')
                (out/'runtime-precision.html').write_text(html,encoding='utf-8')
                match = re.search(r'<script id="precision-life-data"[^>]*>(.*?)</script>',html,re.S)
                if match:
                    runtime_rows = json.loads(match[1])['analysis_tube_rows']
                    runtime_tube = next(r for r in runtime_rows if r['tube_no']=='18-13')
                    result['runtime'] = dict(reachable=True,
                        selected=runtime_tube['selected_base_corrosion_rate_mm_per_year'],
                        matches_source=runtime_tube['selected_base_corrosion_rate_mm_per_year']==tube['selected_base_corrosion_rate_mm_per_year'])
                    runtime_pages = {}
                    for name,path in [('dashboard','/'),('exchangers','/exchangers')]:
                        with opener.open(Request(f'http://127.0.0.1:4824{path}',
                            headers={'Cookie':f'{cookie.key}={cookie.value}'}),timeout=60) as response:
                            page_html = response.read().decode('utf-8')
                            runtime_pages[name] = response.status
                        (out/f'runtime-{name}.html').write_text(page_html,encoding='utf-8')
                    result['runtime']['page_statuses'] = runtime_pages
                    if args.runtime_browser:
                        browser = subprocess.run(['node','tools/verify_analysis_cleanup_browser.mjs','--runtime'],
                            input=json.dumps(dict(cookie=dict(name=cookie.key,value=cookie.value),
                                analysis_path=f'/analysis?exchanger_id={identifier}&unit=VCM1')),
                            text=True,encoding='utf-8',capture_output=True,cwd=ROOT,timeout=180)
                        (out/'runtime-browser-run.log').write_text(browser.stdout+browser.stderr,encoding='utf-8')
                        result['runtime']['browser_passed'] = browser.returncode == 0
                else:
                    result['runtime'] = dict(reachable=True,authenticated=False)
            except Exception as exc:
                result['runtime'] = dict(reachable=False,error_type=type(exc).__name__)
        (out/'validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True))
    finally:
        connection.rollback()
        connection.close()

if __name__ == '__main__':
    main()
