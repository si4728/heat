"""Idempotent, source-bound corrections explicitly requested by the customer."""
from datetime import datetime
import hashlib
import json
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from ..iris_v2_models import (CustomerCorrectionEvent, HeatExchangerSpecRevision,
    HeatExchangerSideSpec, HeatExchangerCapacity, IrisInspection, IrisInspectionSpecSnapshot,
    IrisTubeResult, HeatExchangerTube, TubeBundle, HeatExchanger, Equipment, ProcessUnit)

KEY='CUSTOMER_20261124'
SOURCES={
 '2025_1P_VCM1.pdf':'d9cadb6c3bd1147467e3cce6e75945910ae9b43df956845ff0f98b6e6f507af5',
 '2025_1P_VCM2.pdf':'761d86ad0d17ec418eff4464703b7bb601a4d3408ddf828188ec6928322b4ac3',
}
POSITIONS={(9,3),(13,4),(5,4),(3,4),(8,5),(9,7),(5,8),(3,8),(8,10),(11,10)}


def correct(engine, pdf_directory, *, apply=False, actor_label='USER_AUTHORIZED_CODEX_20261124'):
    for name,digest in SOURCES.items():
        if hashlib.sha256((Path(pdf_directory)/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Original PDF differs; recheck the evidence before correction')
    changes=[]
    journal_exists=inspect(engine).has_table('customer_correction_event')
    if apply and not journal_exists:raise ValueError('Correction journal migration is required')
    with Session(engine) as session, session.begin():
        def record(kind,identifier,field,old,new,source,page):
            entry=dict(entity_type=kind,entity_id=identifier,field_name=field,
                old_value_json=json.dumps(old,default=str),new_value_json=json.dumps(new,default=str),
                source_file=source,source_sha256=SOURCES[source],source_page=page)
            changes.append(entry)
            if apply:
                session.add(CustomerCorrectionEvent(correction_key=KEY,actor_label=actor_label,**entry))
        def existing(kind,identifier,field):
            if not journal_exists:return None
            return session.scalar(select(CustomerCorrectionEvent).where(
                CustomerCorrectionEvent.correction_key==KEY,CustomerCorrectionEvent.entity_type==kind,
                CustomerCorrectionEvent.entity_id==identifier,CustomerCorrectionEvent.field_name==field))
        # Verify stable scope before using the reviewed inspection identifiers.
        for hxid,unit,code,iid in [(122,'VCM1','E-341',375),(235,'VCM2','E-222',409)]:
            row=session.execute(select(Equipment,ProcessUnit).join(ProcessUnit,ProcessUnit.unit_id==Equipment.unit_id)
                .join(HeatExchanger,HeatExchanger.equipment_id==Equipment.equipment_id)
                .where(HeatExchanger.heat_exchanger_id==hxid)).first()
            inspection=session.get(IrisInspection,iid)
            spec=session.scalar(select(HeatExchangerSpecRevision).where(
                HeatExchangerSpecRevision.heat_exchanger_id==hxid,HeatExchangerSpecRevision.is_current.is_(True)).with_for_update())
            if not row or row[1].unit_code!=unit or not spec or spec.exchanger_code!=code or not inspection or inspection.heat_exchanger_id!=hxid:
                raise ValueError('Equipment/inspection identity differs from the reviewed evidence')
        results=session.execute(select(IrisTubeResult,HeatExchangerTube).join(
            HeatExchangerTube,HeatExchangerTube.tube_id==IrisTubeResult.tube_id).where(
            IrisTubeResult.iris_inspection_id==375).with_for_update()).all()
        if len(results)!=10 or {(t.row_no,t.column_no) for _,t in results}!=POSITIONS:
            raise ValueError('E-341 source row/column positions differ')
        for result,tube in results:
            prior=existing('iris_tube_result',result.iris_tube_result_id,'minimum_wall_thickness_mm')
            if prior:
                if result.minimum_wall_thickness_mm!=2.77:raise ValueError('E-341 previously corrected value changed')
                continue
            if result.minimum_wall_thickness_mm not in (None,2.77) or result.wall_loss_percent!=0:
                raise ValueError('E-341 expected pre-correction values differ')
            if result.minimum_wall_thickness_mm is None:
                record('iris_tube_result',result.iris_tube_result_id,'minimum_wall_thickness_mm',None,2.77,'2025_1P_VCM1.pdf',142)
                if apply:result.minimum_wall_thickness_mm=2.77
        inspection=session.get(IrisInspection,409)
        if inspection.total_tube_count_reported not in (179,328):raise ValueError('Unexpected E-222 report count')
        if inspection.total_tube_count_reported!=179:
            record('iris_inspection',409,'total_tube_count_reported',328,179,'2025_1P_VCM2.pdf',118)
            if apply:inspection.total_tube_count_reported=179
        snapshot=session.scalar(select(IrisInspectionSpecSnapshot).where(IrisInspectionSpecSnapshot.iris_inspection_id==409))
        if snapshot and snapshot.summary_total_tubes not in (None,179,328):raise ValueError('Unexpected E-222 snapshot count')
        if snapshot and snapshot.summary_total_tubes!=179:
            record('iris_inspection_spec_snapshot',snapshot.spec_snapshot_id,'summary_total_tubes',snapshot.summary_total_tubes,179,'2025_1P_VCM2.pdf',118)
            if apply:snapshot.summary_total_tubes=179
        current=session.scalar(select(HeatExchangerSpecRevision).where(HeatExchangerSpecRevision.heat_exchanger_id==235,HeatExchangerSpecRevision.is_current.is_(True)))
        if current.tube_count not in (179,328):raise ValueError('Unexpected E-222 current specification count')
        if current.tube_count==328:
            record('heat_exchanger',235,'current_spec_tube_count',328,179,'2025_1P_VCM2.pdf',118)
            if apply:
                now=datetime.now()
                values={c.name:getattr(current,c.name) for c in HeatExchangerSpecRevision.__table__.columns if not c.primary_key}
                values.update(tube_count=179,revision_no=current.revision_no+1,revision_code=str(current.revision_no+1),
                    effective_from=now,effective_to=None,is_current=True,
                    raw_json=json.dumps(dict(source=KEY,previous_spec_revision_id=current.spec_revision_id,
                        source_file='2025_1P_VCM2.pdf',source_page=118,source_sha256=SOURCES['2025_1P_VCM2.pdf'])))
                current.is_current=False;current.effective_to=now;session.flush()
                revised=HeatExchangerSpecRevision(**values);session.add(revised);session.flush()
                for side in session.scalars(select(HeatExchangerSideSpec).where(HeatExchangerSideSpec.spec_revision_id==current.spec_revision_id)).all():
                    copied=HeatExchangerSideSpec(**{c.name:(revised.spec_revision_id if c.name=='spec_revision_id' else getattr(side,c.name)) for c in HeatExchangerSideSpec.__table__.columns if not c.primary_key})
                    session.add(copied);session.flush()
                    for capacity in session.scalars(select(HeatExchangerCapacity).where(HeatExchangerCapacity.side_spec_id==side.side_spec_id)).all():
                        session.add(HeatExchangerCapacity(**{c.name:(copied.side_spec_id if c.name=='side_spec_id' else getattr(capacity,c.name)) for c in HeatExchangerCapacity.__table__.columns if not c.primary_key}))
        bundles=session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id==235,TubeBundle.retired_at.is_(None)).with_for_update()).all()
        if len(bundles)!=1:raise ValueError('E-222 active bundle identity needs review')
        for bundle in bundles:
            if bundle.expected_tube_count not in (None,179,328):raise ValueError('Unexpected E-222 bundle count')
            if bundle.expected_tube_count!=179:
                record('tube_bundle',bundle.bundle_id,'expected_tube_count',bundle.expected_tube_count,179,'2025_1P_VCM2.pdf',118)
                if apply:bundle.expected_tube_count=179
        if not apply:session.rollback()
    return changes
