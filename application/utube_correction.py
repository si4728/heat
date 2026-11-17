"""Customer-approved physical U-tube counts, preserving prior spec revisions."""
from datetime import datetime
import json
from sqlalchemy import select, func
from ..iris_v2_models import (HeatExchanger, Equipment, ProcessUnit, HeatExchangerSpecRevision,
    HeatExchangerSideSpec, HeatExchangerCapacity, TubeBundle, IrisInspection)

TARGETS = ((80,'VCM1','E-123',18,9,352,44), (103,'VCM1','E-550',92,46,379,156),
           (202,'VCM2','E-401',160,80,417,152))
CHANGE_ID = 'REVIEW_20261117_PHYSICAL_UTUBE_COUNT'


def values(row):
    return {column.key:getattr(row,column.key) for column in row.__table__.columns
            if not column.primary_key and column.computed is None}


def correct_counts(session, *, apply=False):
    plan=[]
    for identifier,unit,code,old,new,inspection_id,page in TARGETS:
        hx=session.scalar(select(HeatExchanger).where(HeatExchanger.heat_exchanger_id==identifier).with_for_update())
        if hx is None:
            raise ValueError(f'{code}: exchanger is missing')
        actual_unit=session.scalar(select(ProcessUnit.unit_code).join(Equipment,Equipment.unit_id==ProcessUnit.unit_id).where(Equipment.equipment_id==hx.equipment_id))
        spec=session.scalar(select(HeatExchangerSpecRevision).where(HeatExchangerSpecRevision.heat_exchanger_id==identifier,HeatExchangerSpecRevision.is_current.is_(True)))
        evidence=session.get(IrisInspection,inspection_id)
        bundles=list(session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id==identifier,TubeBundle.retired_at.is_(None))))
        if (actual_unit!=unit or not spec or spec.exchanger_code!=code or spec.tube_count not in (old,new)
                or not evidence or evidence.heat_exchanger_id!=identifier or evidence.total_tube_count_reported!=new
                or len(bundles)!=1 or bundles[0].expected_tube_count not in (old,new)):
            raise ValueError(f'{code}: count/identity/evidence precondition does not match')
        plan.append((spec,bundles[0],dict(heat_exchanger_id=identifier,unit=unit,code=code,
            old_spec_revision_id=spec.spec_revision_id,old_count=spec.tube_count,new_count=new,
            old_bundle_count=bundles[0].expected_tube_count,inspection_id=inspection_id,pdf_page=page)))
    result=[]
    for spec,bundle,item in plan:
        item['changed']=spec.tube_count!=item['new_count'] or bundle.expected_tube_count!=item['new_count']
        if apply and item['changed']:
            if spec.tube_count!=item['new_count']:
                data=values(spec)
                revision=session.scalar(select(func.max(HeatExchangerSpecRevision.revision_no)).where(HeatExchangerSpecRevision.heat_exchanger_id==spec.heat_exchanger_id))+1
                data.update(tube_count=item['new_count'],revision_no=revision,revision_code=str(revision),
                    effective_from=datetime.now(),effective_to=None,is_current=True,
                    raw_json=json.dumps(dict(change_id=CHANGE_ID,evidence=item,previous_raw_json=spec.raw_json),ensure_ascii=False))
                spec.is_current=False;spec.effective_to=data['effective_from'];session.flush()
                replacement=HeatExchangerSpecRevision(**data);session.add(replacement);session.flush()
                for side in list(spec.side_specs):
                    copied=HeatExchangerSideSpec(**(values(side)|dict(spec_revision_id=replacement.spec_revision_id)))
                    session.add(copied);session.flush()
                    for capacity in side.capacities:
                        session.add(HeatExchangerCapacity(**(values(capacity)|dict(side_spec_id=copied.side_spec_id))))
                item['new_spec_revision_id']=replacement.spec_revision_id
            bundle.expected_tube_count=item['new_count']
        result.append(item)
    session.flush()
    return result
