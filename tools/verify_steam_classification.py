"""Verify the current operational Steam classification using read-only queries."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from iris2.application import text_to_sql_fluids as fluids, text_to_sql_service as service
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for


def main():
    config = load_database_config(path=Path('config/database-readonly.conf'))
    engine = engine_for(config, load_database_config()['name'])
    try:
        with engine.connect() as c:
            before = list(c.exec_driver_sql('SELECT spec_revision_id,shell_fluid,tube_fluid FROM heat_exchanger_spec_revision ORDER BY spec_revision_id'))
        ids = [r['heat_exchanger_id'] for r in service.catalog()]
        results = []
        for question in ('유체명이 STEAM인 열교환기 목록', '유체명이 S:STEAM인 열교환기 목록', '공정별 유체명별 열교환기 목록'):
            settings = fluids.options(question)
            results.append(fluids.execute(ids, settings, fluids.proposal(ids, settings), ids)['rows'])
        with engine.connect() as c:
            after = list(c.exec_driver_sql('SELECT spec_revision_id,shell_fluid,tube_fluid FROM heat_exchanger_spec_revision ORDER BY spec_revision_id'))
        counts = {r['side_code']: r['exchanger_count'] for r in results[0]}
        report = dict(passed=results[0] == results[1] and counts == {'SHELL': 37, 'TUBE': 2}
            and not any(r['fluid_name'] == 'S:STEAM' for r in results[2]) and before == after,
            counts=counts, alias_and_plain_equal=results[0] == results[1], source_values_unchanged=before == after,
            steam_by_unit=[r for r in results[2] if r['fluid_name'] == 'STEAM'])
        out = Path('reports/steam-classification-20261126')
        out.mkdir(parents=True, exist_ok=True)
        (out / 'operational-check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'steam_by_unit'}))
        return 0 if report['passed'] else 1
    finally:
        engine.dispose()


if __name__ == '__main__':
    raise SystemExit(main())
