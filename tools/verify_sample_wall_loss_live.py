"""Read-only service/SQL parity and figure-5 checks, without loading a model."""
import argparse
import json
import math
from pathlib import Path
from statistics import linear_regression
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2 import dbapi, services
from iris2.hx_configuration import DB_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exchanger-code', default='E-104B')
    parser.add_argument('--web', action='store_true', help='Check authenticated GET pages and save local HTML previews')
    args = parser.parse_args()
    connection = dbapi.connect(DB_PATH, readonly=True)
    try:
        matches = connection.execute('''SELECT s.heat_exchanger_id FROM heat_exchanger_spec_revision s
            JOIN heat_exchanger h ON h.heat_exchanger_id=s.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=h.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE s.is_current=1 AND s.exchanger_code=? AND u.unit_code IN ('VCM1','VCM2')''',
            (args.exchanger_code,)).fetchall()
        if len(matches) != 1:
            raise ValueError('Choose a unique VCM1/VCM2 exchanger code')
        identifier = matches[0][0]
        detail = services.exchanger_detail(identifier)
        estimate = detail['remaining_life']['sample_wall_loss_estimate']
        assert estimate['status'] == 'ESTIMATED', estimate['status']
        losses = sorted(float(row[0]) for row in connection.execute('''SELECT wall_loss_percent
            FROM iris_tube_result WHERE iris_inspection_id=? AND result_status='VALID'
            AND quality_status='VALID' AND wall_loss_percent BETWEEN 0 AND 100''',
            (estimate['inspection_id'],)).fetchall())
        assert len(losses) == estimate['sample_count']
        reduced = [-math.log(-math.log((i - .3) / (len(losses) + .4)))
                   for i in range(1, len(losses) + 1)]
        fit = linear_regression(reduced, losses)
        assert math.isclose(fit.slope, estimate['beta'], rel_tol=1e-12)
        assert math.isclose(fit.intercept, estimate['mu'], rel_tol=1e-12)
        if args.exchanger_code == 'E-104B':
            assert estimate['sample_count'] == 10 and estimate['total_tube_count'] == 52
            assert abs(estimate['estimated_max_wall_loss_percent'] - 31.7) < .1
            assert abs(estimate['upper_20_wall_loss_percent'] - 21.7) < .1
            assert estimate['first_threshold']['year'] == 2026
            assert estimate['twenty_percent_threshold']['year'] == 2032
        output = ROOT / 'reports/sample-wall-loss-20261112'
        output.mkdir(parents=True, exist_ok=True)
        (output / 'live_validation.json').write_text(json.dumps(dict(
            exchanger_code=args.exchanger_code, service_sql_parity=True,
            independent_regression_parity=True, database_mutated=False,
            estimate=estimate), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        if args.web:
            from iris2.app import create_app
            app = create_app({'TESTING': True, 'AUTH_DISABLED': False, 'CSRF_ENABLED': True})
            uid = connection.execute('SELECT MIN(user_id) FROM app_user WHERE is_admin=1 AND is_active=1').fetchone()[0]
            if uid is None:
                raise ValueError('Active administrator needed for authenticated read-only checks')
            client = app.test_client()
            with client.session_transaction() as session:
                session.update(user_id=uid, last_activity_at=time.time(), csrf_token='sample-estimate-local-preview')
            checks = []
            for name, url in [('precision', f'/analysis?exchanger_id={identifier}'),
                              ('detail', f'/exchangers/{identifier}')]:
                assert app.test_client().get(url).status_code == 302
                response = client.get(url)
                html = response.get_data(as_text=True)
                assert response.status_code == 200
                assert 'sample-wall-loss-title' in html
                if args.exchanger_code == 'E-104B':
                    assert '31.7%' in html and '21.7%' in html
                html = html.replace('"/static/', '"' + (ROOT / 'static').as_uri() + '/')
                (output / f'{name}.html').write_text(html, encoding='utf-8')
                checks.append(dict(page=name, status=response.status_code, authenticated=True))
            # The E-121B report has five valid tubes: current measured forecasts remain present.
            short = connection.execute('''SELECT heat_exchanger_id FROM heat_exchanger_spec_revision
                WHERE is_current=1 AND exchanger_code='E-121B' ''').fetchall()
            if len(short) == 1:
                response = client.get(f'/exchangers/{short[0][0]}')
                html = response.get_data(as_text=True)
                assert response.status_code == 200 and '표본 부족' in html
                assert '튜브별 Plugging 판정 기준 도달 예상' in html
                (output / 'insufficient.html').write_text(
                    html.replace('"/static/', '"' + (ROOT / 'static').as_uri() + '/'), encoding='utf-8')
                checks.append(dict(page='insufficient', status=200, measured_forecasts_retained=True))
            (output / 'web_validation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
        print(json.dumps(dict(exchanger_code=args.exchanger_code, sample_count=estimate['sample_count'],
            measured_max=estimate['measured_max_wall_loss_percent'],
            estimated_max=estimate['estimated_max_wall_loss_percent'],
            upper_20=estimate['upper_20_wall_loss_percent'],
            first_year=estimate['first_threshold']['year'],
            twenty_percent_year=estimate['twenty_percent_threshold']['year'], passed=True)))
    finally:
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Sample estimate verification failed ({type(exc).__name__}); inspect the local data and settings.')
        raise SystemExit(1)
