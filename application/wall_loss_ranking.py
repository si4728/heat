"""Rank the latest eligible measurement per tube using the analysis selection rule."""
from collections import Counter, defaultdict

from sqlalchemy import func, select

from ..domain.current_measurements import select_current_measurements
from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import (Equipment, HeatExchanger, HeatExchangerManagementCriteria,
    HeatExchangerSpecRevision, HeatExchangerTube, IrisInspection, IrisTubeResult, Plant, ProcessUnit, TubeBundle)
from ..life_prediction import remaining_life_as_of_date

SCOPE = ('PE', 'VCM1', 'VCM2')


def ranking(search='', plant_code='', unit_code=''):
    search, plant_code, unit_code = (str(value or '').strip() for value in (search, plant_code, unit_code))
    as_of = remaining_life_as_of_date()
    with session_scope(DB_PATH) as session:
        query = (select(HeatExchanger, Equipment, ProcessUnit, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .where(ProcessUnit.unit_code.in_(SCOPE)))
        if plant_code:
            query = query.where(Plant.plant_code == plant_code)
        if unit_code:
            query = query.where(ProcessUnit.unit_code == unit_code)
        masters = session.execute(query).all()
        ids = [hx.heat_exchanger_id for hx, *_ in masters]
        bundles = defaultdict(list)
        for bundle in session.scalars(select(TubeBundle).where(TubeBundle.heat_exchanger_id.in_(ids))):
            bundles[bundle.heat_exchanger_id].append(bundle)
        selected_bundles = {b.bundle_id for group in bundles.values()
                            for b in ([b for b in group if b.retired_at is None] or group)}
        tubes = {t.tube_id: t for t in session.scalars(select(HeatExchangerTube)
            .where(HeatExchangerTube.bundle_id.in_(selected_bundles)))}
        bundle_owners = {b.bundle_id: identifier for identifier, group in bundles.items() for b in group}
        tubes_by_hx = defaultdict(dict)
        for tube in tubes.values():
            tubes_by_hx[bundle_owners[tube.bundle_id]][tube.tube_id] = tube
        histories = defaultdict(list)
        for result, inspection in session.execute(select(IrisTubeResult, IrisInspection)
            .join(IrisInspection, IrisInspection.iris_inspection_id == IrisTubeResult.iris_inspection_id)
            .where(IrisInspection.heat_exchanger_id.in_(ids), IrisTubeResult.tube_id.in_(tubes))):
            if result.tube_id in tubes_by_hx[inspection.heat_exchanger_id]:
                histories[inspection.heat_exchanger_id].append((result, inspection))
        specs = {s.heat_exchanger_id: s for s in session.scalars(select(HeatExchangerSpecRevision)
            .where(HeatExchangerSpecRevision.heat_exchanger_id.in_(ids), HeatExchangerSpecRevision.is_current.is_(True)))}
        criteria = {c.heat_exchanger_id: c for c in session.scalars(select(HeatExchangerManagementCriteria)
            .where(HeatExchangerManagementCriteria.heat_exchanger_id.in_(ids)))}
        registered = dict(session.execute(select(IrisInspection.heat_exchanger_id, func.count())
            .where(IrisInspection.heat_exchanger_id.in_(ids)).group_by(IrisInspection.heat_exchanger_id)).all())
        rows = []
        for hx, equipment, unit, plant in masters:
            identifier = hx.heat_exchanger_id
            latest, eligible, _ = select_current_measurements(histories[identifier], tubes_by_hx[identifier],
                equipment, as_of=as_of)
            measured = [(r, i) for r, i in latest.values() if r.wall_loss_percent is not None]
            best = max(measured, key=lambda pair: (pair[0].wall_loss_percent,
                pair[1].inspection_date or pair[1].report_date, pair[0].iris_tube_result_id), default=None)
            result, inspection = best if best else (None, None)
            tube = tubes.get(result.tube_id) if result else None
            spec, rule = specs.get(identifier), criteria.get(identifier)
            loss = float(result.wall_loss_percent) if result else None
            warning = float(rule.warning_wall_loss_percent) if rule and rule.warning_wall_loss_percent is not None else 20.0
            critical = float(rule.critical_wall_loss_percent) if rule and rule.critical_wall_loss_percent is not None else 40.0
            row = dict(heat_exchanger_id=identifier, plant_code=plant.plant_code, unit_code=unit.unit_code,
                equipment_code=equipment.equipment_code, equipment_name=equipment.equipment_name,
                exchanger_code=spec.exchanger_code if spec else None, registered_inspection_count=registered.get(identifier, 0),
                tube_id=tube.tube_id if tube else None, tube_no=tube.tube_no if tube else None,
                wall_loss_percent=loss, minimum_wall_thickness_mm=result.minimum_wall_thickness_mm if result else None,
                inspection_date=(inspection.inspection_date or inspection.report_date) if inspection else None,
                iris_inspection_id=inspection.iris_inspection_id if inspection else None,
                report_number=inspection.report_number if inspection else None,
                result_count=sum(r.wall_loss_percent is not None for r, _ in eligible),
                measured_tube_count=len(measured), warning_threshold=warning, critical_threshold=critical,
                wall_loss_status='NO_DATA' if loss is None else 'CRITICAL' if loss >= critical else 'WARNING' if loss >= warning else 'NORMAL')
            if search and not any(search.casefold() in str(row.get(field) or '').casefold()
                    for field in ('equipment_code', 'equipment_name', 'exchanger_code', 'tube_no')):
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r['wall_loss_percent'] is None, -(r['wall_loss_percent'] or 0),
                                r['plant_code'], r['unit_code'], r['equipment_code']))
        counts = Counter(r['wall_loss_status'] for r in rows)
        return dict(rows=rows, status_counts={key: counts[key] for key in ('CRITICAL', 'WARNING', 'NORMAL', 'NO_DATA')},
            search=search, plant_code=plant_code, unit_code=unit_code,
            plants=list(session.scalars(select(Plant.plant_code).join(ProcessUnit, ProcessUnit.plant_id == Plant.plant_id)
                .where(ProcessUnit.unit_code.in_(SCOPE)).distinct().order_by(Plant.plant_code))),
            units=list(session.scalars(select(ProcessUnit.unit_code).where(ProcessUnit.unit_code.in_(SCOPE))
                .distinct().order_by(ProcessUnit.unit_code))), basis='튜브별 최근 유효 측정 중 최대값 · 분석 화면과 동일 기준')
