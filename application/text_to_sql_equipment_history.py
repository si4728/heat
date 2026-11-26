"""Bounded SELECT-only inspection cohorts and completion history for equipment queries."""
from datetime import date, datetime
import math
import re
from types import SimpleNamespace

from .. import dbapi
from ..hx_configuration import DB_PATH
from ..llm_integration.text_to_sql import QueryRejected
from ..domain.measurement_eligibility import exclusion_reason
from ..domain.inspection_lifecycle import current_installation_date, is_current_installation_inspection


class HistoryNotReady(RuntimeError):
    pass


def day(value):
    if isinstance(value,datetime):return value.date()
    if isinstance(value,date):return value
    try:return date.fromisoformat(str(value)[:10])
    except (ValueError,TypeError):return None


def read(ids):
    if not ids or len(ids)>500 or any(type(i) is not int or i<=0 for i in ids):
        raise QueryRejected('조회 설비 범위를 확인하세요.')
    placeholders=','.join('?' for _ in ids)
    connection=dbapi.connect(DB_PATH,readonly=True,readonly_profile='text_to_sql')
    def rows(sql):
        result=[dict(r) for r in connection.execute(sql,tuple(ids)).fetchmany(100001)]
        if len(result)>100000:raise QueryRejected('이력 범위가 너무 큽니다. 설비 범위를 줄이세요.')
        return result
    try:
        grants=connection.execute('SHOW GRANTS').fetchall()
        if not grants or any(not re.match(r'^GRANT (?:USAGE|SELECT) ON ',str(r[0]),re.I)
                or 'WITH GRANT OPTION' in str(r[0]).upper() for r in grants):
            raise QueryRejected('SELECT 전용 계정이 필요합니다.')
        connection.execute('SET SESSION max_statement_time=5')
        connection.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        connection.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        masters=rows(f'''SELECT hx.heat_exchanger_id,hx.iris_applicability,
            e.install_date AS equipment_install_date,e.production_team_code,u.unit_code
            FROM heat_exchanger hx JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE hx.heat_exchanger_id IN ({placeholders}) AND u.unit_code IN ('PE','VCM1','VCM2')''')
        if {r['heat_exchanger_id'] for r in masters}!=set(ids):
            raise PermissionError('조회 중 설비 범위가 변경되었습니다. 다시 조회하세요.')
        return dict(masters={r['heat_exchanger_id']:r for r in masters},
            inspections=rows(f'SELECT i.* FROM iris_inspection i WHERE i.heat_exchanger_id IN ({placeholders})'),
            results=rows(f'''SELECT r.*,t.bundle_id AS tube_bundle_id,t.installed_at AS tube_installed_at,
                b.retired_at AS bundle_retired_at FROM iris_tube_result r
                JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
                JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id JOIN tube_bundle b ON b.bundle_id=t.bundle_id
                WHERE i.heat_exchanger_id IN ({placeholders}) AND b.heat_exchanger_id=i.heat_exchanger_id
                ORDER BY r.iris_tube_result_id'''),
            tubes=rows(f'''SELECT t.*,b.heat_exchanger_id,b.retired_at AS bundle_retired_at,b.bundle_code
                FROM heat_exchanger_tube t JOIN tube_bundle b ON b.bundle_id=t.bundle_id
                WHERE b.heat_exchanger_id IN ({placeholders})'''),
            reports=rows(f'''SELECT h.* FROM iris_inspection_summary_history h
                JOIN iris_inspection i ON i.iris_inspection_id=h.iris_inspection_id
                WHERE i.heat_exchanger_id IN ({placeholders})'''),
            operations=rows(f'SELECT p.* FROM tube_plugging_event p WHERE p.heat_exchanger_id IN ({placeholders})'))
    except dbapi.DatabaseError as exc:
        if exc.args and exc.args[0]==1142:
            raise HistoryNotReady('고급 검사 이력 조회 준비가 필요합니다. 관리자에게 문의하세요.') from exc
        raise
    finally:
        connection.rollback();connection.close()


def inspection_object(row):
    values=dict(row)
    for key in ('inspection_date','report_date','installation_or_replacement_date'):
        values[key]=day(values.get(key))
    return SimpleNamespace(**values)


def cohorts(data,identifier,as_of,*,current=True):
    master=data['masters'][identifier]
    output=[]
    for inspection in data['inspections']:
        if inspection['heat_exchanger_id']!=identifier:continue
        obj=inspection_object(inspection)
        reason=exclusion_reason(obj,as_of=as_of)
        if reason and (current or reason!='PARTIAL_INSPECTION'):continue
        measured=obj.inspection_date or obj.report_date
        selected={};installed=set();bundles=set()
        for result in data['results']:
            if result['iris_inspection_id']!=inspection['iris_inspection_id']:continue
            eligible=exclusion_reason(obj,SimpleNamespace(**result),as_of=as_of)
            if eligible and (current or eligible!='PARTIAL_INSPECTION'):continue
            # Partial-scope history still requires valid result/quality statuses.
            if not current and eligible=='PARTIAL_INSPECTION':
                if result.get('result_status') not in (None,'VALID') or result.get('quality_status') not in (None,'VALID','USER_APPROVED_211MM_BASIS'):continue
            if current and (result.get('bundle_retired_at') is not None or not is_current_installation_inspection(
                    measured,day(master.get('equipment_install_date')),day(result.get('tube_installed_at')))):continue
            loss=result.get('wall_loss_percent')
            if loss is None or not math.isfinite(float(loss)) or not 0<=float(loss)<=100:continue
            key=result['tube_id']
            if key not in selected or loss>selected[key]['wall_loss_percent']:selected[key]=result
            start=current_installation_date(day(master.get('equipment_install_date')),
                day(result.get('tube_installed_at')),obj.installation_or_replacement_date)
            if inspection.get('installation_or_replacement_year') and inspection.get('installation_or_replacement_date_precision')=='YEAR':
                start=current_installation_date(start,date(inspection['installation_or_replacement_year'],7,1))
            installed.add(start);bundles.add(result['tube_bundle_id'])
        output.append(dict(inspection=inspection,date=measured,results=list(selected.values()),
            maximum_loss=max((float(r['wall_loss_percent']) for r in selected.values()),default=None),
            sample_count=len(selected),bundles=bundles,installed=installed,
            partial=reason=='PARTIAL_INSPECTION',
            old_installation=not is_current_installation_inspection(measured,day(master.get('equipment_install_date')))))
    return sorted(output,key=lambda r:(r['date'],r['inspection']['iris_inspection_id']),reverse=True)


def latest_pair(data,identifier,as_of):
    groups=[g for g in cohorts(data,identifier,as_of) if g['sample_count']]
    dates=sorted({g['date'] for g in groups},reverse=True)
    if len(dates)<2:return None,'유효 검사 2회 미만'
    latest=[g for g in groups if g['date']==dates[0]]
    previous=[g for g in groups if g['date']==dates[1]]
    if len(latest)!=1 or len(previous)!=1:return None,'동일 날짜 복수 회차 · 비교 집단 확인 필요'
    latest,previous=latest[0],previous[0]
    if latest['bundles']!=previous['bundles'] or latest['installed']!=previous['installed'] or len(latest['installed'])!=1:
        return None,'설치·번들 기준 불일치'
    return (previous,latest),None


def last_inspection(data,identifier,as_of):
    dates=[];undated=False
    for row in data['inspections']:
        if row['heat_exchanger_id']!=identifier or row.get('superseded_by_inspection_id') is not None:continue
        measured=day(row.get('inspection_date')) or day(row.get('report_date'))
        if measured is None:undated=True
        elif measured<=as_of:dates.append(measured)
    return max(dates,default=None),undated


def cumulative_completed(data,identifier,bundles,measured):
    if not measured or not bundles:return None,'완료 일자·번들 근거 없음'
    operations=[e for e in data['operations'] if e['heat_exchanger_id']==identifier]
    cancelled={e['cancelled_event_id'] for e in operations if e['operation']=='CANCEL'}
    managed={e['tube_id'] for e in operations}
    tubes={t['tube_id']:t for t in data['tubes'] if t['heat_exchanger_id']==identifier and t['bundle_id'] in bundles}
    dated={e['tube_id']:day(e['effective_date']) for e in operations
           if e['operation']=='COMPLETE' and e['plugging_event_id'] not in cancelled and e['tube_id'] in tubes}
    for identifier,tube in tubes.items():
        if identifier not in managed and str(tube.get('current_status','')).upper()=='PLUGGED':
            dated[identifier]=day(tube.get('plugging_date'))
    # An absent ledger is unknown, rather than a historical zero completion count.
    if not dated:return None,'완료 이력 미등록 · 0본으로 해석하지 않음'
    if any(value is None for value in dated.values()):return None,'일자 미상 완료 튜브 있음'
    if min(dated.values())>measured:return None,'완료 이력 등록 이전 검사 · 당시 수량 미확인'
    return sum(value<=measured for value in dated.values()),'완료 원장·기존 일자 등록 기준'
