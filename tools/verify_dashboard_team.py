"""Read-only SQL parity and authenticated dashboard snapshots."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import dbapi, services
from iris2.hx_configuration import DB_PATH
from iris2.app import create_app


def main():
    connection = dbapi.connect(DB_PATH, readonly=True)
    try:
        data = services.dashboard_data()
        life = data['life_dashboard']
        expected = connection.execute("""SELECT COUNT(*) FROM heat_exchanger h
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2')""").fetchone()[0]
        assert life['total'] == expected == sum(life['totals'].values())
        assert data['counts']['exchangers'] == expected
        assert sum(count for _, count in data['units']) == expected
        scoped_counts = connection.execute("""SELECT COUNT(i.iris_inspection_id),
            COALESCE(SUM(i.extracted_tube_result_count),0) FROM iris_inspection i
            JOIN heat_exchanger h ON h.heat_exchanger_id=i.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code IN ('VCM1','VCM2')""").fetchone()
        assert data['counts']['inspections'] == scoped_counts[0]
        scope = """SELECT h.heat_exchanger_id FROM heat_exchanger h JOIN equipment e
            ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2')"""
        tubes = connection.execute(f"""SELECT COALESCE(SUM(tube_count),0)
            FROM heat_exchanger_spec_revision WHERE is_current=1
            AND heat_exchanger_id IN ({scope})""").fetchone()[0]
        results = connection.execute(f"""SELECT COUNT(*) FROM iris_tube_result r
            JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
            WHERE i.heat_exchanger_id IN ({scope})""").fetchone()[0]
        assert data['counts']['tubes'] == tubes and data['counts']['results'] == results
        assert len(life['groups']) == 1 and life['groups'][0]['total'] == expected
        annual = connection.execute("""SELECT c.campaign_year, COUNT(i.iris_inspection_id),
            COUNT(DISTINCT i.heat_exchanger_id), COALESCE(SUM(i.extracted_tube_result_count),0)
            FROM iris_inspection i JOIN inspection_campaign c ON c.campaign_id=i.campaign_id
            JOIN process_unit u ON u.unit_id=c.unit_id JOIN heat_exchanger h
            ON h.heat_exchanger_id=i.heat_exchanger_id WHERE u.unit_code IN ('VCM1','VCM2')
            GROUP BY c.campaign_year ORDER BY c.campaign_year DESC""").fetchall()
        assert [tuple((r['year'],r['inspection_count'],r['exchanger_count'],r['result_count']))
                for r in data['team_yearly_rows']] == [tuple(r) for r in annual]
        app = create_app({'TESTING':True,'AUTH_DISABLED':False,'CSRF_ENABLED':True,'QR_UI_ENABLED':True})
        uid = connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=uid,last_activity_at=time.time(),csrf_token='dashboard-local-preview')
        assert app.test_client().get('/').status_code == 302
        response = client.get('/')
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'data-qr-scan-open' not in html and 'dashboard-qr-scanner.js' not in html
        assert 'VCM 생산팀' in html and '30년 이상' in html
        output = ROOT / 'reports/dashboard-team-20261112'
        output.mkdir(parents=True,exist_ok=True)
        (output/'dashboard.html').write_text(html.replace('"/static/','"'+(ROOT/'static').as_uri()+'/'),encoding='utf-8')
        result=dict(equipment=expected,inspections=data['counts']['inspections'],annual_years=len(annual),sql_parity=True,
                    authenticated=True,qr_hidden_with_flag_enabled=True,database_mutated=False)
        (output/'validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally:
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    main()
