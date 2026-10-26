"""Read-only audit of dashboard coverage and VCM1/VCM2 tube records."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from sqlalchemy import text
from sqlalchemy.orm import Session
from iris2.database import get_engine
from iris2.services import _dashboard_data_entry_coverage


def main():
    report = {}
    with get_engine().connect() as connection:
        connection.exec_driver_sql('SET TRANSACTION READ ONLY')
        connection.commit()
        with connection.begin():
            def query(sql):
                return [dict(r) for r in connection.execute(text(sql)).mappings()]
            with Session(bind=connection) as session:
                report['dashboard'] = _dashboard_data_entry_coverage(session)
            base = '''FROM heat_exchanger_tube t
              JOIN tube_bundle b ON b.bundle_id=t.bundle_id
              JOIN heat_exchanger h ON h.heat_exchanger_id=b.heat_exchanger_id
              JOIN equipment e ON e.equipment_id=h.equipment_id
              JOIN process_unit u ON u.unit_id=e.unit_id'''
            scoped = " WHERE u.unit_code IN ('VCM1','VCM2')"
            report['scope_metrics'] = query('''SELECT u.unit_code, COUNT(*) AS registered,
              SUM(t.tube_no IS NOT NULL AND TRIM(t.tube_no)<>'') AS tube_number,
              SUM(t.current_status IS NOT NULL AND TRIM(t.current_status)<>'') AS status,
              SUM(t.current_status NOT IN ('IN_SERVICE','PLUGGED')) AS unsupported_status,
              SUM(t.row_no IS NOT NULL AND t.column_no IS NOT NULL) AS grid,
              SUM((t.row_no IS NULL) <> (t.column_no IS NULL)) AS partial_grid,
              SUM(t.row_no <= 0 OR t.column_no <= 0) AS nonpositive_grid,
              SUM(t.position_x IS NOT NULL AND t.position_y IS NOT NULL) AS xy,
              SUM((t.position_x IS NULL) <> (t.position_y IS NULL)) AS partial_xy,
              SUM(t.position_x IS NOT NULL AND t.position_y IS NOT NULL AND t.position_locked=1) AS locked_xy,
              SUM(t.pass_no IS NOT NULL) AS pass_number,
              SUM(t.pass_no <= 0) AS invalid_pass,
              SUM(t.installed_at IS NOT NULL) AS installation,
              SUM(t.installed_at > CURRENT_TIMESTAMP) AS future_installation,
              SUM(NOT(t.installed_at <=> e.install_date)) AS installation_differs_equipment,
              SUM(t.lifecycle_no > 1) AS later_lifecycle,
              SUM(EXISTS(SELECT 1 FROM iris_tube_result r WHERE r.tube_id=t.tube_id)) AS inspected,
              SUM(EXISTS(SELECT 1 FROM iris_tube_result r WHERE r.tube_id=t.tube_id AND r.minimum_wall_thickness_mm IS NOT NULL)) AS thickness,
              SUM(EXISTS(SELECT 1 FROM tube_layout_point p JOIN tube_layout_revision l ON l.layout_revision_id=p.layout_revision_id
                  WHERE p.tube_id=t.tube_id AND p.verification_status='VERIFIED' AND l.revision_status='APPROVED')) AS approved_layout
              ''' + base + scoped + ' GROUP BY u.unit_code')
            report['equipment'] = query('''SELECT h.heat_exchanger_id, e.equipment_code,u.unit_code,
              e.install_date, cs.tube_count AS expected, cs.pass_count,
              COUNT(t.tube_id) AS registered,
              SUM(t.row_no IS NOT NULL AND t.column_no IS NOT NULL) AS grid,
              SUM(t.position_x IS NOT NULL AND t.position_y IS NOT NULL) AS xy,
              SUM(t.pass_no IS NOT NULL) AS pass_number,
              SUM(t.installed_at IS NOT NULL) AS installation
              FROM heat_exchanger h JOIN equipment e ON e.equipment_id=h.equipment_id
              JOIN process_unit u ON u.unit_id=e.unit_id
              LEFT JOIN heat_exchanger_spec_revision cs ON cs.heat_exchanger_id=h.heat_exchanger_id AND cs.is_current=1
              LEFT JOIN tube_bundle b ON b.heat_exchanger_id=h.heat_exchanger_id
              LEFT JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
              WHERE u.unit_code IN ('VCM1','VCM2')
              GROUP BY h.heat_exchanger_id,e.equipment_code,u.unit_code,e.install_date,cs.tube_count,cs.pass_count
              ORDER BY u.unit_code,e.equipment_code''')
            report['duplicate_grid'] = query('''SELECT t.bundle_id,t.lifecycle_no,t.row_no,t.column_no,COUNT(*) AS count
              ''' + base + scoped + ''' AND t.row_no IS NOT NULL AND t.column_no IS NOT NULL
              GROUP BY t.bundle_id,t.lifecycle_no,t.row_no,t.column_no HAVING COUNT(*)>1''')
            report['grid_review'] = query('''SELECT t.tube_id,t.tube_no,t.row_no,t.column_no,e.equipment_code,u.unit_code
              ''' + base + scoped + ' AND (t.row_no<=0 OR t.column_no<=0)')
            report['date_review'] = query('''SELECT e.equipment_code,u.unit_code,t.installed_at,
              MIN(i.report_date) AS first_inspection,COUNT(DISTINCT t.tube_id) AS tubes,COUNT(*) AS results
              ''' + base + ''' JOIN iris_tube_result r ON r.tube_id=t.tube_id
              JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
              ''' + scoped + ''' AND i.report_date<t.installed_at
              GROUP BY e.equipment_code,u.unit_code,t.installed_at ORDER BY results DESC''')
            report['thickness_review'] = query('''SELECT t.tube_id,t.tube_no,e.equipment_code,u.unit_code,
              r.minimum_wall_thickness_mm,r.wall_loss_percent,r.wall_loss_depth_mm,r.result_status
              ''' + base + ' JOIN iris_tube_result r ON r.tube_id=t.tube_id' + scoped + ' AND r.minimum_wall_thickness_mm<=0')
            report['result_quality'] = query('''SELECT u.unit_code,COUNT(*) AS results,
              SUM(r.result_status<>'VALID' OR r.result_status IS NULL) AS nonvalid,
              SUM(r.minimum_wall_thickness_mm<=0) AS nonpositive_thickness,
              SUM(r.wall_loss_percent<0 OR r.wall_loss_percent>100) AS invalid_loss,
              SUM(i.report_date<t.installed_at) AS inspection_before_installation
              ''' + base + ''' JOIN iris_tube_result r ON r.tube_id=t.tube_id
              JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
              ''' + scoped + ' GROUP BY u.unit_code')
            report['layout'] = query('''SELECT u.unit_code,l.revision_status,p.verification_status,
              COUNT(*) AS points,SUM(p.tube_id IS NULL) AS unlinked,
              SUM(p.source_x IS NULL OR p.source_y IS NULL) AS missing_xy
              FROM tube_layout_point p JOIN tube_layout_revision l ON l.layout_revision_id=p.layout_revision_id
              JOIN tube_bundle b ON b.bundle_id=l.bundle_id
              JOIN heat_exchanger h ON h.heat_exchanger_id=b.heat_exchanger_id
              JOIN equipment e ON e.equipment_id=h.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id
              WHERE u.unit_code IN ('VCM1','VCM2')
              GROUP BY u.unit_code,l.revision_status,p.verification_status''')
    report['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
    target = ROOT/'reports'/'tube_data_coverage_audit.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    summary = {key: report[key] for key in ('scope_metrics','result_quality','layout','grid_review','date_review','thickness_review')}
    summary['equipment_totals'] = [{
        'unit': unit, 'exchangers': len([e for e in report['equipment'] if e['unit_code']==unit]),
        'specified': sum(e['expected'] is not None for e in report['equipment'] if e['unit_code']==unit),
        'expected': sum(e['expected'] or 0 for e in report['equipment'] if e['unit_code']==unit),
        'registered': sum(e['registered'] for e in report['equipment'] if e['unit_code']==unit),
        'without_tubes': sum(e['registered']==0 for e in report['equipment'] if e['unit_code']==unit),
        'over_expected': [e['equipment_code'] for e in report['equipment'] if e['unit_code']==unit and e['expected'] is not None and e['registered']>e['expected']],
    } for unit in ('VCM1','VCM2')]
    print(json.dumps(summary,default=str,ensure_ascii=True))


if __name__ == '__main__':
    main()
