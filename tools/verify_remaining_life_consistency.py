"""Read-only VCM1/VCM2 audit and browser/server arithmetic parity fixtures."""
import json, sys
from pathlib import Path
from sqlalchemy import select
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from iris2 import services
from iris2.iris_v2_models import HeatExchanger,Equipment,ProcessUnit,TubeBundle,HeatExchangerManagementCriteria,HeatExchangerSpecRevision
cases=[];issues=[]
with services.session_scope(services.DB_PATH) as session:
    masters=session.execute(select(HeatExchanger,Equipment,ProcessUnit)
        .join(Equipment,Equipment.equipment_id==HeatExchanger.equipment_id)
        .join(ProcessUnit,ProcessUnit.unit_id==Equipment.unit_id)
        .where(ProcessUnit.unit_code.in_(['VCM1','VCM2']))).all()
    for hx,equipment,unit in masters:
        identifier=hx.heat_exchanger_id
        bundles=session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id==identifier)).all()
        criteria=session.scalar(select(HeatExchangerManagementCriteria).where(HeatExchangerManagementCriteria.heat_exchanger_id==identifier))
        spec=session.scalar(select(HeatExchangerSpecRevision).where(HeatExchangerSpecRevision.heat_exchanger_id==identifier,HeatExchangerSpecRevision.is_current.is_(True)))
        baseline=services._remaining_life_projection(session,identifier,equipment,bundles,criteria)
        if baseline['equipment_summary']['total_tube_count']!=baseline['total_tube_count']:
            issues.append({'id':identifier,'error':'DISPLAY_TOTAL_MISMATCH'})
        if spec and spec.tube_count and baseline['total_tube_count']!=spec.tube_count:
            issues.append({'id':identifier,'error':'SPEC_TOTAL_MISMATCH'})
        if baseline['limit_percent']!=services.configured_plugging_limit(bool(equipment.is_critical)):
            issues.append({'id':identifier,'error':'CRITICAL_LIMIT_MISMATCH'})
        if baseline['plugging_wall_loss_percent']!=40:
            issues.append({'id':identifier,'error':'THRESHOLD_MISMATCH'})
        for multiplier in (0.1,0.5,1,1.5,2):
            calculated=baseline if multiplier==1 else services._remaining_life_projection(
                session,identifier,equipment,bundles,criteria,corrosion_rate_multiplier=multiplier)
            cases.append({'id':identifier,'multiplier':multiplier,'rows':baseline['tube_projections'],
                'expected':{str(p['tube_id']):p['plugging_date'] for p in calculated['tube_projections']}})
out=ROOT/'reports/system_recheck/20261028';out.mkdir(parents=True,exist_ok=True)
(ROOT/'tmp/life_parity_cases.json').write_text(json.dumps(cases,allow_nan=False),encoding='utf-8')
report={'assets':len(masters),'cases':len(cases),'issues':issues}
(out/'life_consistency.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
raise SystemExit(bool(issues))
