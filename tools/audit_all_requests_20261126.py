"""Read-only evidence for the user's complete PE/VCM1/VCM2 request checklist."""
from collections import Counter
from contextlib import contextmanager
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from iris2 import dbapi, services
from iris2.application import wall_loss_ranking, text_to_sql_service, text_to_sql_fluids
from iris2.application.customer_corrections_20261124 import SOURCES
from iris2.db_config import load_database_config
from iris2.hx_configuration import DB_PATH, PDF_REPORT_DIR
from iris2.migration.migrate_all import engine_for
from iris2.tools.audit_customer_requirements_20261126 import boundary_cases

OUT = Path('reports/all-requests-audit-20261126')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_database_config(path=Path('config/database-readonly.conf'))
    engine = engine_for(config, load_database_config()['name'])
    checks = []

    def check(name, passed, **evidence):
        checks.append(dict(name=name, passed=bool(passed), **evidence))

    @contextmanager
    def readonly_scope(*args, **kwargs):
        with engine.connect() as c:
            c.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            with Session(bind=c) as session:
                yield session
            c.rollback()

    try:
        with engine.connect() as c:
            revisions = dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
            operations_before = c.scalar(text('SELECT COUNT(*) FROM tube_plugging_event'))
        with patch.object(services, 'session_scope', readonly_scope), patch.object(wall_loss_ranking, 'session_scope', readonly_scope):
            dashboard = services.dashboard_remaining_life()
            catalog = text_to_sql_service.catalog()
            check('scope_including_uninspected', {r['unit_code'] for r in catalog} == {'PE', 'VCM1', 'VCM2'}
                  and {r['heat_exchanger_id'] for r in catalog} == {r['heat_exchanger_id'] for r in dashboard['rows']},
                  catalog=len(catalog), by_unit=dict(Counter(r['unit_code'] for r in catalog)))
            check('life_bands_and_uncalculable_reasons', set(dashboard['bands']) == {'long', 'medium', 'short', 'unknown', 'uninspected'}
                  and sum(dashboard['totals'].values()) == dashboard['total']
                  and all(r['uncalculable_reason'] for r in dashboard['rows'] if r['band'] == 'unknown'), bands=dashboard['totals'])
            ranked = services.exchanger_wall_loss_ranking()['rows']
            ranking = {r['heat_exchanger_id']: r for r in ranked}
            mismatches = []
            detail_rows = []
            pe = []
            zero = []
            for row in dashboard['rows']:
                identifier = row['heat_exchanger_id']
                life = services.exchanger_detail(identifier)['remaining_life']
                overview = life['equipment_overview']
                maximum = max((r['wall_loss_percent'] for r in life['analysis_tube_rows'] if r['wall_loss_percent'] is not None), default=None)
                if (row['remaining_display'] != overview['remaining_display'] or row['band'] != overview['band']
                        or ranking[identifier]['wall_loss_percent'] != maximum):
                    mismatches.append(identifier)
                item = dict(code=row['exchanger_code'], unit=row['unit_code'], id=identifier, max_loss=maximum,
                    remaining=overview['remaining_display'], recommendation=overview['recommendation_date'],
                    sample=overview['sample_count'], measured=overview['measured_max'], estimated=overview['estimated_max'],
                    measurement_date=overview['measurement_date'], reached=overview['threshold_reached_count'],
                    estimated_reached=overview['estimated_reached'], reason=overview['uncalculable_reason'],
                    sample_status=overview['sample_status'], band=overview['band'])
                detail_rows.append(item)
                if row['unit_code'] == 'PE' and row['band'] != 'uninspected':
                    pe.append(item)
                if row['exchanger_code'] in ('E-13', 'E-122A', 'E-341', 'E-222'):
                    zero.append(item)
            check('analysis_dashboard_ranking_parity', not mismatches and len(ranking) == len(detail_rows),
                  equipment=len(detail_rows), mismatches=mismatches)
            by_id = {r['id']: r for r in detail_rows}
            check('approved_quality_sample', by_id[142]['sample'] == 20 and by_id[142]['sample_status'] == 'ESTIMATED', row=by_id[142])
            ambiguous = [by_id[i] for i in (139, 143, 199)]
            check('ambiguous_bundle_safety', all(r['sample_status'] == 'AMBIGUOUS_INSPECTION' for r in ambiguous),
                  pending_source_identification=ambiguous)
            check('uninspected_selection_not_redirected', services.precision_analysis_data(106)['selected_exchanger_id'] == 106
                  and services.precision_analysis_data(106)['selected_detail'] is None, requested_id=106)
            check('pe_ten_inspections_dates', len(pe) == 10 and all(r['measurement_date'] for r in pe), rows=pe)
            reached_codes = {'E-131D', 'E-331B', 'E-331C', 'E-341A', 'E-341C', 'E-241B-1'}
            reached = [r for r in pe if r['code'] in reached_codes]
            check('pe_six_measured_thresholds', {r['code'] for r in reached} == reached_codes and all(r['reached'] > 0 for r in reached), rows=reached)
            check('zero_loss_equipment_not_fabricated', len(zero) == 4 and all(r['max_loss'] == 0 and r['band'] == 'unknown' for r in zero), rows=zero)
            check('far_future_display_capped', all('2321' not in str(r['target_display']) and '2321' not in str(r['remaining_display'])
                  for r in dashboard['rows']), equipment=len(dashboard['rows']))
            links = []
            missing = []
            for equipment in catalog:
                for inspection in text_to_sql_service.inspections(equipment['heat_exchanger_id']):
                    pdf = services.find_inspection_pdf(inspection['iris_inspection_id'])
                    item = dict(unit=equipment['unit_code'], inspection_id=inspection['iris_inspection_id'])
                    if pdf:
                        links.append(dict(item, page=pdf['page'], file=pdf['path'].name))
                    else:
                        missing.append(item)
            check('registered_inspection_pdf_files', not missing, inspected=len(links) + len(missing), available=len(links),
                  mapped_pages=sum(r['page'] is not None for r in links), missing=missing)
            hashes = {name: hashlib.sha256((PDF_REPORT_DIR / name).read_bytes()).hexdigest() == digest for name, digest in SOURCES.items()}
            check('correction_pdf_evidence_unchanged', all(hashes.values()), source_files=hashes)
            fluid_results = []
            for question in ('유체명이 STEAM 인 열교환기 목록', '공정별 유체명별 열교환기 목록'):
                settings = text_to_sql_fluids.options(question)
                ids = [r['heat_exchanger_id'] for r in text_to_sql_fluids.select_equipment({}, question)]
                result = text_to_sql_fluids.execute(ids, settings, text_to_sql_fluids.proposal(ids, settings), ids)
                fluid_results.append(dict(question=question, rows=result['rows'], settings=settings))
            check('steam_and_fluid_grouping', bool(fluid_results[0]['rows']) and all(r['fluid_name'] == 'STEAM' for r in fluid_results[0]['rows'])
                  and bool(fluid_results[1]['rows']), results=fluid_results)
            variants = [{key: r[key] for key in ('unit_code', 'side_code', 'fluid_name', 'exchanger_count')}
                        for r in fluid_results[1]['rows'] if 'STEAM' in r['fluid_name']]
            check('steam_alias_grouping', not any(r['fluid_name'] == 'S:STEAM' for r in variants)
                  and any(r['unit_code'] == 'VCM1' and r['side_code'] == 'SHELL' and r['fluid_name'] == 'STEAM' for r in variants),
                  steam_variants=variants)
        with engine.connect() as c:
            def scalar(sql):
                return c.scalar(text(sql))
            utubes = [dict(r) for r in c.execute(text('SELECT heat_exchanger_id,tube_count FROM heat_exchanger_spec_revision WHERE is_current=1 AND heat_exchanger_id IN (80,103,202)')).mappings()]
            check('physical_utube_counts', {r['heat_exchanger_id']: r['tube_count'] for r in utubes} == {80: 9, 103: 46, 202: 80}, rows=utubes)
            check('e341_thickness', scalar('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=375 AND minimum_wall_thickness_mm=2.77') == 10,
                  inspection=375, corrected_tubes=scalar('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=375 AND minimum_wall_thickness_mm=2.77'))
            counts = dict(current=scalar('SELECT tube_count FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=235 AND is_current=1'),
                report=scalar('SELECT total_tube_count_reported FROM iris_inspection WHERE iris_inspection_id=409'),
                bundle=scalar('SELECT expected_tube_count FROM tube_bundle WHERE heat_exchanger_id=235 AND retired_at IS NULL'),
                old_spec=scalar('SELECT COUNT(*) FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=235 AND is_current=0 AND tube_count=328'))
            check('e222_count_and_original_preservation', counts['current'] == counts['report'] == counts['bundle'] == 179 and counts['old_spec'] > 0, **counts)
            e122a = scalar('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=350 AND minimum_wall_thickness_mm IS NULL')
            check('e122a_source_thickness_blank_preserved', e122a == 10, missing_measured_tubes=e122a)
            e811 = str(scalar("SELECT i.inspection_date FROM iris_inspection i JOIN heat_exchanger_spec_revision s ON s.heat_exchanger_id=i.heat_exchanger_id AND s.is_current=1 WHERE s.exchanger_code='E-811' AND YEAR(i.inspection_date)=2020 ORDER BY i.inspection_date LIMIT 1"))[:10]
            check('e811_date', e811 == '2020-10-24', inspection_date=e811)
            journal = [dict(r) for r in c.execute(text("SELECT entity_type,field_name,COUNT(*) AS event_count FROM customer_correction_event WHERE correction_key='CUSTOMER_20261124' GROUP BY entity_type,field_name")).mappings()]
            journal_counts = {(r['entity_type'], r['field_name']): r['event_count'] for r in journal}
            check('correction_audit_journal', journal_counts.get(('iris_tube_result', 'minimum_wall_thickness_mm')) == 10
                  and journal_counts.get(('heat_exchanger', 'current_spec_tube_count')) == 1
                  and journal_counts.get(('tube_bundle', 'expected_tube_count')) == 1, events=journal)
            after = dict(c.exec_driver_sql('SELECT table_name,revision FROM iris2_database_revision').all())
            check('business_data_unchanged', revisions == after and operations_before == scalar('SELECT COUNT(*) FROM tube_plugging_event'),
                  plugging_events=operations_before)
        boundary = boundary_cases()
        check('observed_and_uninspected_boundaries', not any(r['reproduced'] for r in boundary.values()), results=boundary)
        reader = dbapi.connect(DB_PATH, readonly=True, readonly_profile='text_to_sql')
        try:
            grants = [str(r[0]) for r in reader.execute('SHOW GRANTS').fetchall()]
            check('text_to_sql_select_only_and_history_grants', all(re.match(r'^GRANT (?:USAGE|SELECT) ON ', g, re.I) and 'WITH GRANT OPTION' not in g.upper() for g in grants)
                  and all(any(f'`{table}`' in g for g in grants) for table in ('iris_inspection_summary_history', 'tube_plugging_event')))
        finally:
            reader.close()
        report = dict(source_scope=['PE', 'VCM1', 'VCM2'], verified_at=date.today().isoformat(),
            passed=all(r['passed'] for r in checks), checks=checks, equipment=detail_rows)
        (OUT / 'readonly-data.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(json.dumps(dict(passed=report['passed'], checks=[dict(name=r['name'], passed=r['passed']) for r in checks]), ensure_ascii=True))
        raise SystemExit(0 if report['passed'] else 1)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
