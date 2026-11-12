"""Scoped recommendation list and inline registration using existing tube targets."""
from datetime import date
from sqlalchemy import select

from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import (Equipment, HeatExchanger, HeatExchangerManagementCriteria,
    HeatExchangerSpecRevision, HeatExchangerTube, InspectionPlan, ProcessUnit, TubeBundle)
from ..domain.inspection_recommendation import BASES, horizon_end, recommendation
from ..domain.tube_status import normalize_tube_status
from .life_dashboard import first_tube_threshold


def recommended_plans_data(*, unit='', process='', horizon='2', basis='measured', exchanger_id=None):
    from .. import services
    if unit not in ('', 'VCM1', 'VCM2') or basis not in BASES:
        raise ValueError('VCM1·VCM2와 권고 기준을 확인하세요.')
    as_of = services.remaining_life_as_of_date()
    cutoff = horizon_end(as_of, horizon)
    with session_scope(DB_PATH) as session:
        query = select(HeatExchanger, Equipment, ProcessUnit).join(Equipment,
            Equipment.equipment_id == HeatExchanger.equipment_id).join(ProcessUnit,
            ProcessUnit.unit_id == Equipment.unit_id).where(ProcessUnit.unit_code.in_(('VCM1','VCM2')))
        if exchanger_id is not None:
            query = query.where(HeatExchanger.heat_exchanger_id == exchanger_id)
        masters = session.execute(query).all()
        processes = sorted({e.process_code or '' for _, e, u in masters if not unit or u.unit_code == unit})
        if process and process not in processes and process != '__NONE__':
            raise ValueError('등록된 공정을 선택하세요.')
        ids = [h.heat_exchanger_id for h,e,u in masters]
        specs = {s.heat_exchanger_id:s for s in session.scalars(select(HeatExchangerSpecRevision).where(
            HeatExchangerSpecRevision.heat_exchanger_id.in_(ids),HeatExchangerSpecRevision.is_current.is_(True)))}
        bundles = list(session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id.in_(ids))))
        criteria = {c.heat_exchanger_id:c for c in session.scalars(select(HeatExchangerManagementCriteria).where(
            HeatExchangerManagementCriteria.heat_exchanger_id.in_(ids)))}
        plans = session.scalars(select(InspectionPlan).where(InspectionPlan.heat_exchanger_id.in_(ids),
            InspectionPlan.status.notin_(('COMPLETED','CANCELLED'))).order_by(InspectionPlan.planned_date)).all()
        open_plans = {}
        for plan in plans:
            open_plans.setdefault(plan.heat_exchanger_id,plan)
        rows=[]
        for hx,e,u in masters:
            if (unit and u.unit_code != unit) or (process and (e.process_code or '') != ('' if process == '__NONE__' else process)):
                continue
            life = services._remaining_life_projection(session,hx.heat_exchanger_id,e,
                [b for b in bundles if b.heat_exchanger_id == hx.heat_exchanger_id],criteria.get(hx.heat_exchanger_id),as_of_date=as_of)
            rec = recommendation(life,first_tube_threshold(life.get('tube_projections',[])),basis=basis)
            if not rec or rec['due_date'] > cutoff:
                continue
            spec=specs.get(hx.heat_exchanger_id)
            rows.append(dict(heat_exchanger_id=hx.heat_exchanger_id,
                exchanger_code=(spec.exchanger_code if spec else None) or e.equipment_tag or e.equipment_code,
                equipment_name=e.equipment_name,unit_code=u.unit_code,process_code=e.process_code or '',
                team_code=e.production_team_code or 'VCM', **rec,
                overdue=rec['due_date'] < as_of, open_plan=open_plans.get(hx.heat_exchanger_id)))
    rows.sort(key=lambda r:(r['due_date'],r['exchanger_code'] or '',r['heat_exchanger_id']))
    return dict(rows=rows,unit=unit,process=process,processes=processes,horizon=str(horizon),
        basis=basis,bases=BASES,as_of_date=as_of,cutoff=cutoff)


def available_tubes(exchanger_id):
    with session_scope(DB_PATH) as session:
        rows=session.scalars(select(HeatExchangerTube).join(TubeBundle,
            TubeBundle.bundle_id==HeatExchangerTube.bundle_id).join(HeatExchanger,
            HeatExchanger.heat_exchanger_id==TubeBundle.heat_exchanger_id).join(Equipment,
            Equipment.equipment_id==HeatExchanger.equipment_id).join(ProcessUnit,
            ProcessUnit.unit_id==Equipment.unit_id).where(
                HeatExchanger.heat_exchanger_id==exchanger_id,TubeBundle.retired_at.is_(None),
                ProcessUnit.unit_code.in_(('VCM1','VCM2'))).order_by(HeatExchangerTube.tube_no)).all()
        return [dict(tube_id=t.tube_id,tube_no=t.tube_no) for t in rows
                if normalize_tube_status(t.current_status)=='IN_SERVICE']


def save_recommended_plan(payload, user_id):
    from .. import services
    if not user_id:
        raise ValueError('로그인한 신청자가 필요합니다.')
    identifier=services._int(payload.get('heat_exchanger_id'))
    if not identifier:
        raise ValueError('권고 대상 설비를 선택하세요.')
    basis=payload.get('recommendation_basis','measured')
    if basis != 'measured':
        raise ValueError('권고 기준이 실측 튜브로 확정되었습니다. 화면을 새로고침하세요.')
    horizon=payload.get('recommendation_horizon','2')
    with session_scope(DB_PATH) as session:
        hx=session.scalar(select(HeatExchanger).where(HeatExchanger.heat_exchanger_id==identifier).with_for_update())
        if not hx:
            raise ValueError('권고 대상 설비가 없습니다.')
        candidates=recommended_plans_data(basis=basis,horizon=horizon,exchanger_id=identifier)['rows']
        if not candidates:
            raise ValueError('현재 권고 대상이 아닙니다. 화면을 새로고침하세요.')
        if session.scalar(select(InspectionPlan.inspection_plan_id).where(
                InspectionPlan.heat_exchanger_id==identifier,InspectionPlan.status.notin_(('COMPLETED','CANCELLED')))):
            raise ValueError('진행 중인 계획이 이미 등록되어 있습니다.')
        try:
            selected={int(value) for value in payload.get('tube_ids',[])}
        except (ValueError,TypeError):
            raise ValueError('실제 검사 대상 Tube를 선택하세요.') from None
        if not selected or not selected <= {r['tube_id'] for r in available_tubes(identifier)}:
            raise ValueError('현재 사용 중인 대상 설비의 Tube를 선택하세요.')
        rec=candidates[0]
        data=dict(payload,notes=f"권고일 {rec['due_date'].isoformat()} · 근거 {rec['source']} · 기준 {BASES[basis]}",
                  inspection_method='IRIS',scope_code='SELECTED',priority='HIGH' if rec['overdue'] else 'NORMAL')
        return services.save_inspection_plan(data,user_id,_session=session)
