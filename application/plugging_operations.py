"""Transactional actual plugging registration; forecasts never become operations."""
from datetime import date, datetime, timedelta, timezone
import re
from types import SimpleNamespace

from sqlalchemy import select
from ..iris_v2_database import session_scope
from ..hx_configuration import DB_PATH
from ..iris_v2_models import (HeatExchanger, Equipment, ProcessUnit, TubeBundle,
                             HeatExchangerTube, TubePluggingEvent)
from ..domain.tube_status import normalize_tube_status


class StateConflict(ValueError):
    pass


def _events(session, exchanger_id):
    return session.scalars(select(TubePluggingEvent).where(
        TubePluggingEvent.heat_exchanger_id == exchanger_id).order_by(
        TubePluggingEvent.plugging_event_id)).all()


def guard_legacy_status_change(session, tube_ids):
    if not tube_ids:return
    events=session.scalars(select(TubePluggingEvent).where(TubePluggingEvent.tube_id.in_(tube_ids))).all()
    cancelled={e.cancelled_event_id for e in events if e.operation=='CANCEL'}
    if any(e.operation=='COMPLETE' and e.plugging_event_id not in cancelled for e in events):
        raise ValueError('완료 원장이 있는 튜브는 분석 화면에서 원본 등록을 취소하세요.')


def _version(tube, events):
    return dict(status=tube.current_status,
        plugging_date=tube.plugging_date.isoformat() if tube.plugging_date else None,
        lifecycle_no=tube.lifecycle_no,
        event_id=max((e.plugging_event_id for e in events if e.tube_id == tube.tube_id), default=0))


def tubes_as_of(session, exchanger_id, tubes, as_of):
    """Detached calculation inputs: never change mapped business rows on reads."""
    events = _events(session, exchanger_id)
    cancelled = {e.cancelled_event_id for e in events if e.operation=='CANCEL'}
    active = {e.tube_id:e for e in events if e.operation=='COMPLETE' and e.plugging_event_id not in cancelled}
    result=[]
    for tube in tubes:
        values={column.name:getattr(tube,column.name) for column in HeatExchangerTube.__table__.columns}
        original=active.get(tube.tube_id)
        if original and original.effective_date>as_of:
            values.update(current_status=original.previous_status,plugging_date=original.previous_plugging_date)
        result.append(SimpleNamespace(**values))
    return result


def _exchanger(session, exchanger_id, *, lock=False):
    stmt = select(HeatExchanger, Equipment, ProcessUnit).join(
        Equipment, Equipment.equipment_id == HeatExchanger.equipment_id).join(
        ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id).where(
        HeatExchanger.heat_exchanger_id == exchanger_id,
        ProcessUnit.unit_code.in_(('PE','VCM1','VCM2')))
    row = session.execute(stmt.with_for_update() if lock else stmt).first()
    if row is None:
        raise PermissionError('PE·VCM1·VCM2 범위의 설비를 확인하세요.')
    return row


def state(exchanger_id):
    with session_scope(DB_PATH) as session:
        _exchanger(session, exchanger_id)
        tubes = session.scalars(select(HeatExchangerTube).join(TubeBundle).where(
            TubeBundle.heat_exchanger_id == exchanger_id, TubeBundle.retired_at.is_(None))).all()
        events = _events(session, exchanger_id)
        cancelled = {e.cancelled_event_id for e in events if e.operation == 'CANCEL'}
        active = {t.tube_id for t in tubes}
        return dict(versions={str(t.tube_id): _version(t, events) for t in tubes},
            history=[dict(event_id=e.plugging_event_id, tube_id=e.tube_id,
                tube_no=next((t.tube_no for t in tubes if t.tube_id == e.tube_id), str(e.tube_id)),
                operation=e.operation, date=e.effective_date.isoformat(),
                registered_at=e.registered_at.isoformat()+'Z', actor=e.actor_name,
                reason=e.reason, cancelled_event_id=e.cancelled_event_id,
                can_cancel=e.operation=='COMPLETE' and e.plugging_event_id not in cancelled and e.tube_id in active)
                for e in reversed(events)])


def apply(exchanger_id, data, actor):
    if not isinstance(data, dict):
        raise ValueError('등록 내용을 확인하세요.')
    operation, key = data.get('operation'), data.get('request_key')
    if operation not in ('COMPLETE','CANCEL') or not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,64}',key):
        raise ValueError('작업 종류와 요청 식별자를 확인하세요.')
    reason = data.get('reason')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:
        raise ValueError('등록·취소 사유를 1~1000자로 입력하세요.')
    today = datetime.now(timezone(timedelta(hours=9))).date()
    try:
        effective = date.fromisoformat(data.get('date','')) if operation == 'COMPLETE' else today
    except (TypeError,ValueError):
        raise ValueError('Plugging 완료 일자를 확인하세요.')
    if effective > today:
        raise ValueError('미래 일자는 완료로 등록할 수 없습니다.')
    ids = data.get('tube_ids') if operation == 'COMPLETE' else data.get('event_ids')
    if not isinstance(ids,list) or not 1<=len(ids)<=500 or any(type(i) is not int or i<=0 for i in ids):
        raise ValueError('실제 등록 튜브 또는 취소할 완료 이력을 선택하세요.')
    ids = sorted(set(ids))
    with session_scope(DB_PATH) as session:
        hx, equipment, _ = _exchanger(session, exchanger_id, lock=True)
        events = _events(session, exchanger_id)
        repeated = [e for e in events if e.request_key==key and e.actor_id==actor['user_id']]
        if repeated:
            if any(e.operation!=operation for e in repeated):
                raise StateConflict('같은 요청 식별자의 작업 종류가 다릅니다.')
            expected_ids = sorted(e.tube_id if operation=='COMPLETE' else e.cancelled_event_id for e in repeated)
            if any(e.operation!=operation or e.reason!=reason.strip() for e in repeated) or expected_ids!=ids or (
                    operation=='COMPLETE' and any(e.effective_date!=effective for e in repeated)):
                raise StateConflict('같은 요청 식별자의 내용이 다릅니다. 상태를 새로 조회하세요.')
            return dict(changed=0, replayed=True)
        cancelled = {e.cancelled_event_id for e in events if e.operation=='CANCEL'}
        originals = {e.plugging_event_id:e for e in events if e.operation=='COMPLETE'}
        selected = []
        if operation=='CANCEL':
            if any(i not in originals or i in cancelled for i in ids):
                raise StateConflict('이미 취소되었거나 해당 설비의 완료 이력이 아닙니다.')
            selected = [originals[i] for i in ids]
            tube_ids = sorted({e.tube_id for e in selected})
        else:
            tube_ids = ids
        tubes = session.scalars(select(HeatExchangerTube).join(TubeBundle).where(
            TubeBundle.heat_exchanger_id==exchanger_id, TubeBundle.retired_at.is_(None),
            HeatExchangerTube.tube_id.in_(tube_ids)).order_by(HeatExchangerTube.tube_id).with_for_update()).all()
        if len(tubes)!=len(tube_ids):
            raise ValueError('다른 설비·퇴역 번들·표시용 가상 위치는 등록할 수 없습니다.')
        versions = data.get('versions')
        if not isinstance(versions,dict) or any(versions.get(str(t.tube_id))!=_version(t,events) for t in tubes):
            raise StateConflict('튜브 상태가 변경되었습니다. 새로 조회한 뒤 다시 등록하세요.')
        for tube in tubes:
            status = normalize_tube_status(tube.current_status)
            original = next((e for e in selected if e.tube_id==tube.tube_id),None)
            if operation=='COMPLETE':
                if status!='IN_SERVICE':
                    raise StateConflict('이미 Plugging 완료되었거나 등록할 수 없는 운전 상태입니다.')
                starts = [d.date() if isinstance(d,datetime) else d for d in (equipment.install_date,tube.installed_at) if d]
                if starts and effective<max(starts):
                    raise ValueError('설치일 이전의 완료 일자는 등록할 수 없습니다.')
            elif (status!='PLUGGED' or tube.plugging_date!=datetime.combine(original.effective_date,datetime.min.time())
                  or _version(tube,events)['event_id']!=original.plugging_event_id):
                raise StateConflict('완료 후 튜브 상태가 바뀌었습니다. 원본 상태를 확인하세요.')
            event = TubePluggingEvent(heat_exchanger_id=exchanger_id,tube_id=tube.tube_id,
                operation=operation,effective_date=effective if operation=='COMPLETE' else original.effective_date,
                actor_id=actor['user_id'],actor_name=actor.get('display_name') or actor.get('username') or str(actor['user_id']),
                request_key=key,reason=reason.strip(),cancelled_event_id=original.plugging_event_id if original else None,
                previous_status=tube.current_status,previous_plugging_date=tube.plugging_date)
            session.add(event)
            tube.current_status = 'PLUGGED' if operation=='COMPLETE' else original.previous_status
            tube.plugging_date = datetime.combine(effective,datetime.min.time()) if operation=='COMPLETE' else original.previous_plugging_date
        session.flush()
        return dict(changed=len(tubes),replayed=False)
