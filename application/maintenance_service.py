from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from ..domain.tube_status import TUBE_OPERATION_STATUSES, normalize_tube_status
from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import (
    Equipment,
    HeatExchanger,
    HeatExchangerTube,
    MaintenanceRecord,
    Plant,
    ProcessUnit,
    TubeBundle,
    TubeLifecycleEvent,
    WorkOrder,
)


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _date(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d")


def maintenance_data() -> dict[str, Any]:
    with session_scope(DB_PATH) as session:
        orders = session.execute(select(WorkOrder, Equipment, ProcessUnit, Plant)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == WorkOrder.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .order_by(WorkOrder.created_at.desc())).all()
        exchangers = session.execute(select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .order_by(Plant.plant_code, ProcessUnit.unit_code, Equipment.equipment_code)).all()
        return {"orders": orders, "exchangers": exchangers}


def save_work_order(data: dict[str, Any]) -> int:
    exchanger_id = _int(data.get("heat_exchanger_id"))
    title = str(data.get("title") or "").strip()
    if not exchanger_id or not title:
        raise ValueError("열교환기와 작업 제목은 필수입니다.")
    with session_scope(DB_PATH) as session:
        if not session.get(HeatExchanger, exchanger_id):
            raise ValueError("열교환기를 찾을 수 없습니다.")
        code = str(data.get("work_order_code") or f"WO-{datetime.now():%Y%m%d%H%M%S%f}").strip().upper()
        if session.scalar(select(WorkOrder).where(WorkOrder.work_order_code == code)):
            raise ValueError("작업지시 번호가 이미 존재합니다.")
        order = WorkOrder(work_order_code=code, heat_exchanger_id=exchanger_id, title=title,
            work_type=data.get("work_type") or "MAINTENANCE", priority=data.get("priority") or "NORMAL",
            planned_start=_date(data.get("planned_start")), planned_end=_date(data.get("planned_end")),
            description=str(data.get("description") or "").strip() or None)
        session.add(order); session.flush(); return order.work_order_id


def work_order_detail_data(order_id: int) -> dict[str, Any] | None:
    with session_scope(DB_PATH) as session:
        master = session.execute(select(WorkOrder, HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(HeatExchanger, HeatExchanger.heat_exchanger_id == WorkOrder.heat_exchanger_id)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .where(WorkOrder.work_order_id == order_id)).first()
        if not master: return None
        records = session.execute(select(MaintenanceRecord, HeatExchangerTube)
            .outerjoin(HeatExchangerTube, HeatExchangerTube.tube_id == MaintenanceRecord.tube_id)
            .where(MaintenanceRecord.work_order_id == order_id)
            .order_by(MaintenanceRecord.action_date.desc())).all()
        tubes = session.scalars(
            select(HeatExchangerTube)
            .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
            .where(TubeBundle.heat_exchanger_id == master[0].heat_exchanger_id)
            .order_by(HeatExchangerTube.row_no, HeatExchangerTube.column_no,
                      HeatExchangerTube.tube_no)
        ).all()
        return {"master": master, "records": records, "tubes": tubes}


def update_work_order(order_id: int, data: dict[str, Any]) -> bool:
    allowed = {"REQUESTED", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
    status = str(data.get("status") or "").upper()
    if status not in allowed: raise ValueError("지원하지 않는 작업 상태입니다.")
    with session_scope(DB_PATH) as session:
        order = session.get(WorkOrder, order_id)
        if not order: return False
        order.status = status; order.result = str(data.get("result") or "").strip() or order.result
        if status == "COMPLETED": order.completed_at = datetime.now()
        return True


def add_maintenance_record(order_id: int, data: dict[str, Any]) -> int:
    with session_scope(DB_PATH) as session:
        order = session.get(WorkOrder, order_id)
        if not order: raise ValueError("작업지시를 찾을 수 없습니다.")
        raw_tube_id = str(data.get("tube_id") or "").strip()
        tube_id = _int(raw_tube_id) if raw_tube_id else None
        if tube_id is not None and tube_id <= 0:
            raise ValueError("Tube ID는 1 이상의 양수여야 합니다.")
        tube = None
        if tube_id is not None:
            tube = session.scalar(
                select(HeatExchangerTube)
                .join(TubeBundle, TubeBundle.bundle_id == HeatExchangerTube.bundle_id)
                .where(
                    HeatExchangerTube.tube_id == tube_id,
                    TubeBundle.heat_exchanger_id == order.heat_exchanger_id,
                )
            )
            if not tube:
                raise ValueError("선택한 Tube ID는 이 작업지시의 열교환기에 등록된 튜브가 아닙니다.")
        exclude_plugged = str(data.get("exclude_plugged") or "").lower() in {
            "1", "true", "on", "yes"
        }
        if tube and exclude_plugged and normalize_tube_status(tube.current_status) == "PLUGGED":
            raise ValueError("PLUGGED 상태 제외 옵션이 선택되어 있어 해당 튜브를 저장할 수 없습니다.")
        action_type = str(data.get("action_type") or "MAINTENANCE").upper()
        if action_type not in {"MAINTENANCE", "REPLACEMENT", "PLUGGING"}:
            raise ValueError("지원하지 않는 정비 작업 유형입니다.")
        if action_type == "REPLACEMENT" and tube is not None:
            raise ValueError("Replacement는 열교환기 전체 교체 작업입니다. 튜브를 선택할 수 없습니다.")
        new_status = normalize_tube_status(data.get("new_status")) if data.get("new_status") else None
        if new_status and new_status not in TUBE_OPERATION_STATUSES: raise ValueError("지원하지 않는 튜브 상태입니다.")
        if new_status and tube is None:
            raise ValueError("튜브 상태를 변경하려면 열교환기에 등록된 Tube ID를 선택해 주세요.")
        old_status = normalize_tube_status(tube.current_status) if tube else None
        if tube and new_status: tube.current_status = new_status
        record = MaintenanceRecord(work_order_id=order_id, heat_exchanger_id=order.heat_exchanger_id,
            tube_id=tube_id, action_type=action_type,
            old_status=old_status, new_status=new_status,
            details=str(data.get("details") or "").strip() or None)
        session.add(record); session.flush()
        if tube and new_status and old_status != new_status:
            session.add(TubeLifecycleEvent(tube_id=tube_id,
                event_type=f"WORK_ORDER_{record.action_type}_{old_status}_TO_{new_status}",
                reason=f"{order.work_order_code}: {record.details or ''}"))
        return record.maintenance_record_id

