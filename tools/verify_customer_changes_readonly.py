"""Verify applied values and calculation displays using SELECT-only MariaDB access."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from iris2 import services
from iris2.application import text_to_sql_fluids as fluids, text_to_sql_service as sql_service
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for


def main():
    config=load_database_config(path=Path('config/database-readonly.conf'))
    engine=engine_for(config,load_database_config()['name'])
    @contextmanager
    def readonly_scope(*args,**kwargs):
        with engine.connect() as connection:
            connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            with Session(bind=connection) as session:
                yield session
            connection.rollback()
    try:
        with patch('iris2.services.session_scope',readonly_scope):
            life=services.dashboard_remaining_life()
            assert life['total']==sum(life['totals'].values())
            assert set(life['bands'])=={'long','medium','short','unknown','uninspected'}
            pe=[r for r in life['rows'] if r['unit_code']=='PE' and r['band']!='uninspected']
            assert len(pe)==10
            assert all(r['uncalculable_reason'] for r in life['rows'] if r['band']=='unknown')
            assert all('2321' not in r['target_display'] for r in life['rows'])
            details=[]
            for row in pe:
                summary=services.exchanger_detail(row['heat_exchanger_id'])['remaining_life']['equipment_overview']
                assert summary['measurement_date']
                details.append(dict(code=row['exchanger_code'],date=summary['measurement_date'],sample=summary['sample_count'],
                    measured_max=summary['measured_max'],remaining=summary['remaining_display'],reached=row['threshold_reached_count']))
            assert services.precision_analysis_data(235)['selected_detail'] is not None
        catalog=sql_service.catalog()
        assert {r['unit_code'] for r in catalog}=={'PE','VCM1','VCM2'}
        assert len(catalog)==life['total']
        for name in ('ER-201','E-241B-1'):
            selected=fluids.select_equipment({},'PE '+name+' 잔여수명')
            assert len(selected)==1 and selected[0]['unit_code']=='PE'
        with engine.connect() as c:
            assert c.scalar(text('SELECT COUNT(*) FROM iris_tube_result WHERE iris_inspection_id=375 AND minimum_wall_thickness_mm=2.77'))==10
            assert c.scalar(text('SELECT tube_count FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=235 AND is_current=1'))==179
            e811=str(c.scalar(text("SELECT i.inspection_date FROM iris_inspection i JOIN heat_exchanger_spec_revision s ON s.heat_exchanger_id=i.heat_exchanger_id AND s.is_current=1 JOIN heat_exchanger hx ON hx.heat_exchanger_id=i.heat_exchanger_id JOIN equipment e ON e.equipment_id=hx.equipment_id JOIN process_unit u ON u.unit_id=e.unit_id WHERE u.unit_code='VCM1' AND s.exchanger_code='E-811' AND YEAR(i.inspection_date)=2020 LIMIT 1")))[:10]
            assert e811=='2020-10-24'
            operations=c.scalar(text('SELECT COUNT(*) FROM tube_plugging_event'))
        result=dict(verified_at=datetime.now().isoformat(),total=life['total'],bands=life['totals'],pe=details,
            text_to_sql_catalog=len(catalog),e341_corrected_tubes=10,e222_current_count=179,e811_date=e811,
            production_plugging_events=operations,readonly_account=True)
        out=Path('reports/customer-completion-20261124/readonly-verification.json');out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(passed=True,total=result['total'],bands=result['bands'],production_plugging_events=operations)))
    finally:engine.dispose()

if __name__=='__main__':main()
