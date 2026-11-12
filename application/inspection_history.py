"""VCM1/VCM2 inspection-year and organization-process history views."""
from sqlalchemy import func, or_, select

from ..hx_configuration import DB_PATH
from ..iris_v2_database import session_scope
from ..iris_v2_models import (Equipment, HeatExchanger, HeatExchangerSpecRevision,
                             IrisInspection, IrisTubeResult, ProcessUnit, Plant)


def history_matrix(equipment, inspections):
    """Annual maxima select their own report, rather than linking the latest report."""
    by_id = {row['heat_exchanger_id']: dict(row, cells={}, inspection_count=0) for row in equipment}
    years = set()
    for item in inspections:
        row = by_id.get(item['heat_exchanger_id'])
        if row is None or item.get('date') is None:
            continue
        year = item['date'].year
        years.add(year)
        row['inspection_count'] += 1
        cell = row['cells'].get(year)
        loss = item.get('loss_percent')
        if cell is None:
            row['cells'][year] = dict(item, inspection_count=1)
        else:
            count = cell['inspection_count'] + 1
            if (loss is not None and (cell['loss_percent'] is None or loss > cell['loss_percent'])) or (
                    loss == cell['loss_percent'] and item['date'] > cell['date']):
                row['cells'][year] = dict(item, inspection_count=count)
            else:
                cell['inspection_count'] = count
    for row in by_id.values():
        known = [row['cells'][year]['loss_percent'] for year in sorted(row['cells'])
                 if row['cells'][year]['loss_percent'] is not None]
        row['change_percentage_points'] = known[-1] - known[-2] if len(known) >= 2 else None
    return list(by_id.values()), sorted(years)


def inspection_history_data(*, mode, year='', unit='', process='', search=''):
    if mode not in ('yearly', 'process') or unit not in ('', 'VCM1', 'VCM2'):
        raise ValueError('조회 구분과 VCM1·VCM2 공정을 확인하세요.')
    with session_scope(DB_PATH) as session:
        masters = session.execute(select(HeatExchanger, Equipment, ProcessUnit, HeatExchangerSpecRevision, Plant)
            .join(Equipment, Equipment.equipment_id == HeatExchanger.equipment_id)
            .join(ProcessUnit, ProcessUnit.unit_id == Equipment.unit_id)
            .join(Plant, Plant.plant_id == ProcessUnit.plant_id)
            .outerjoin(HeatExchangerSpecRevision, (HeatExchangerSpecRevision.heat_exchanger_id == HeatExchanger.heat_exchanger_id)
                       & HeatExchangerSpecRevision.is_current.is_(True))
            .where(ProcessUnit.unit_code.in_(('VCM1', 'VCM2')))).all()
        all_equipment = [dict(heat_exchanger_id=h.heat_exchanger_id, equipment_code=e.equipment_code,
            exchanger_code=(s.exchanger_code if s else None) or e.equipment_tag or e.equipment_code,
            equipment_name=e.equipment_name, unit_code=u.unit_code,
            team_code=e.production_team_code or 'VCM', process_code=e.process_code or '',
            plant_code=p.plant_code) for h, e, u, s, p in masters]
        processes = sorted({row['process_code'] for row in all_equipment if not unit or row['unit_code'] == unit})
        if process and process not in processes and process != '__NONE__':
            raise ValueError('등록된 공정을 선택하세요.')
        selected = [r for r in all_equipment if (not unit or r['unit_code'] == unit)
            and (not process or r['process_code'] == ('' if process == '__NONE__' else process))
            and (not search or search.casefold() in ' '.join(str(r[k] or '') for k in
                 ('exchanger_code','equipment_code','equipment_name','process_code')).casefold())]
        ids = [r['heat_exchanger_id'] for r in selected]
        records = session.scalars(select(IrisInspection).where(
            IrisInspection.heat_exchanger_id.in_(ids), IrisInspection.superseded_by_inspection_id.is_(None),
            or_(IrisInspection.inspection_date.is_not(None), IrisInspection.report_date.is_not(None)))).all() if ids else []
        inspection_ids = [i.iris_inspection_id for i in records]
        maxima = dict(session.execute(select(IrisTubeResult.iris_inspection_id, func.max(IrisTubeResult.wall_loss_percent))
            .where(IrisTubeResult.iris_inspection_id.in_(inspection_ids),
                or_(IrisTubeResult.quality_status.is_(None), IrisTubeResult.quality_status == 'VALID'),
                or_(IrisTubeResult.result_status.is_(None), IrisTubeResult.result_status == 'VALID'))
            .group_by(IrisTubeResult.iris_inspection_id)).all()) if inspection_ids else {}
        history = [dict(heat_exchanger_id=i.heat_exchanger_id, inspection_id=i.iris_inspection_id,
            date=(i.inspection_date or i.report_date).date(), report_number=i.report_number,
            loss_percent=float(maxima.get(i.iris_inspection_id) if maxima.get(i.iris_inspection_id) is not None
                else i.reported_maximum_wall_loss_percent) if maxima.get(i.iris_inspection_id) is not None
                or i.reported_maximum_wall_loss_percent is not None else None,
            tube_count=i.inspected_tube_count_reported if i.inspected_tube_count_reported is not None
                else i.extracted_tube_result_count) for i in records]
    rows, years = history_matrix(sorted(selected, key=lambda r: (r['exchanger_code'] or '',r['heat_exchanger_id'])), history)
    if year:
        try:
            selected_year = int(year)
        except (ValueError, TypeError):
            raise ValueError('유효한 검사 연도를 선택하세요.') from None
        if not 1900 <= selected_year <= 9999:
            raise ValueError('유효한 검사 연도를 선택하세요.')
    else:
        selected_year = max(years) if years else None
    filtered = [i for i in history if mode == 'process' or i['date'].year == selected_year]
    from ..services import find_inspection_pdf
    pdfs = {}
    for row in rows:
        for cell_year, cell in row['cells'].items():
            if mode == 'yearly' and cell_year != selected_year:
                continue
            identifier = cell['inspection_id']
            if identifier not in pdfs:
                pdfs[identifier] = bool(find_inspection_pdf(identifier))
            cell['pdf_available'] = pdfs[identifier]
    return dict(mode=mode, rows=rows, years=years, selected_year=selected_year, unit=unit,
        process=process, processes=processes, search=search,
        equipment_count=len(rows), inspected_equipment_count=len({i['heat_exchanger_id'] for i in filtered}),
        inspection_count=len(filtered), tube_count=sum(i['tube_count'] or 0 for i in filtered),
        record_years=sorted({i['date'].year for i in filtered}))
