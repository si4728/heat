"""Seven advanced equipment questions using shared analysis and explicit history rules."""
from collections import Counter
from datetime import date
from decimal import Decimal
import math
import re

from .. import services
from ..llm_integration.text_to_sql import QueryRejected
from . import text_to_sql_equipment_history as history
from .text_to_sql_equipment_intents import compare

IDENTITY=['team_code','unit_code','exchanger_code','equipment_name','latest_inspection_date']
TAIL=['remaining_display','recommendation_date']


def assemble(rows,details,settings,*,data=None,as_of=None):
    as_of=as_of or services.remaining_life_as_of_date()
    mode=settings['mode'];diagnostics=Counter();matched=[]
    columns=IDENTITY+TAIL
    if mode in ('increase','overdue_iris','history') and data is None:
        data=history.read([r['heat_exchanger_id'] for r in rows])
    for original in rows:
        row=dict(original);identifier=row['heat_exchanger_id']
        life=details[identifier]['remaining_life']
        if mode=='status':
            if life['equipment_overview']['band']!=settings['status']:continue
            columns=IDENTITY+['remaining_display','uncalculable_reason']
        elif mode=='rate':
            values=[float(t['corrosion_rate_mm_per_year']) for t in life.get('analysis_tube_rows',[])
                if t.get('corrosion_rate_mm_per_year') is not None and math.isfinite(float(t['corrosion_rate_mm_per_year']))
                and float(t['corrosion_rate_mm_per_year'])>0]
            hits=[value for value in values if compare(value,settings['op'],settings['value'])]
            if not hits:continue
            row.update(matching_tube_count=len(hits),maximum_corrosion_rate_mm_per_year=max(values))
            columns=IDENTITY+['matching_tube_count','maximum_corrosion_rate_mm_per_year']+TAIL
        elif mode=='sample':
            sample=life.get('sample_wall_loss_estimate') or {}
            if sample.get('inspection_id') is None:
                diagnostics['최근 유효 검사 집단 없음']+=1;continue
            if not compare(sample.get('sample_count'),settings['op'],settings['value']):continue
            count=sample['sample_count'];minimum=sample.get('minimum_sample_count',10)
            row.update(total_tube_count=life.get('total_tube_count'),
                latest_inspection_date=sample.get('measurement_date') or row.get('latest_inspection_date'),
                sample_review_reason=(f'유효 표본 {count}본 · 통계 추정 최소 {minimum}본 미만 · 검사 범위 확대 검토'
                    if count<minimum else f'요청한 표본 수 조건 부합 · 검사 범위 확대는 별도 검토'))
            columns=IDENTITY+['sample_count','total_tube_count','measured_estimated_loss','sample_review_reason']
        elif mode=='material':
            spec=details[identifier].get('spec')
            material=getattr(spec,'tube_material',None)
            if not material or not re.sub(r'[^A-Z0-9]','',material.upper()).startswith('CUNI'):continue
            if row.get('maximum_loss') is None:
                diagnostics['재질 일치 · 최대 감육률 미산정 제외']+=1;continue
            row['tube_material']=material
            columns=IDENTITY+['tube_material','maximum_loss']+TAIL
        elif mode=='increase':
            pair,reason=history.latest_pair(data,identifier,as_of)
            if not pair:
                diagnostics[reason]+=1;continue
            previous,latest=pair;delta=float(Decimal(str(latest['maximum_loss']))-Decimal(str(previous['maximum_loss'])))
            if delta<0 or not compare(delta,settings['op'],settings['value']):continue
            row.update(previous_inspection_date=previous['date'].isoformat(),latest_inspection_date=latest['date'].isoformat(),
                previous_maximum_loss=previous['maximum_loss'],latest_maximum_loss=latest['maximum_loss'],
                wall_loss_increase_percent_points=round(delta,6),previous_sample_count=previous['sample_count'],
                latest_sample_count=latest['sample_count'])
            columns=IDENTITY+['previous_inspection_date','previous_maximum_loss','latest_maximum_loss',
                'wall_loss_increase_percent_points','previous_sample_count','latest_sample_count']+TAIL
        elif mode=='overdue_iris':
            applicability=data['masters'][identifier]['iris_applicability']
            if applicability not in ('REQUIRED','OPTIONAL'):
                diagnostics['IRIS 비대상·적용 여부 미확인 제외']+=1;continue
            latest,undated=history.last_inspection(data,identifier,as_of)
            if undated:
                diagnostics['날짜 미상 검사 이력 · 판정 제외']+=1;continue
            try:cutoff=as_of.replace(year=as_of.year-settings['years'])
            except ValueError:cutoff=date(as_of.year-settings['years'],2,28)
            if latest is not None and latest>=cutoff:continue
            row.update(latest_inspection_date=latest.isoformat() if latest else None,
                iris_applicability=applicability,inspection_cutoff_date=cutoff.isoformat(),
                missing_inspection_reason='조회 기준일까지 유효 검사 이력 없음' if latest is None else f'{cutoff.isoformat()} 이후 검사 이력 없음')
            columns=IDENTITY+['iris_applicability','inspection_cutoff_date','missing_inspection_reason']
        elif mode=='history':
            if len(rows)!=1:raise QueryRejected('검사 회차별 추이는 설비 한 대를 선택하거나 질문에 설비 코드를 지정하세요.')
            reports={r['iris_inspection_id']:r for r in data['reports']}
            groups=history.cohorts(data,identifier,as_of,current=False)
            for group in reversed(groups[:settings['limit']]):
                inspection=group['inspection'];report=reports.get(inspection['iris_inspection_id'],{})
                bundles=group['bundles'] or ({inspection['bundle_id']} if inspection.get('bundle_id') else set())
                actual,note=history.cumulative_completed(data,identifier,bundles,group['date'])
                tags=[]
                if group['partial']:tags.append('일부 구간 검사 · 직접 비교 제외')
                if group['old_installation']:tags.append('과거 설치 이력')
                tags.append(note)
                matched.append(dict({key:row.get(key) for key in ('heat_exchanger_id','team_code','unit_code','exchanger_code','equipment_name')},
                    iris_inspection_id=inspection['iris_inspection_id'],report_number=inspection.get('report_number'),
                    inspection_date=group['date'].isoformat(),inspection_scope=inspection.get('source_scope_code'),
                    inspected_tube_count=group['sample_count'],maximum_loss=group['maximum_loss'],
                    reported_plugging_before=report.get('plugged_tube_count_before'),
                    reported_plugging_after=report.get('plugged_tube_count_after'),
                    cumulative_actual_plugging_count=actual,history_basis=' · '.join(tags)))
            columns=IDENTITY[:4]+['inspection_date','report_number','inspection_scope','inspected_tube_count','maximum_loss',
                'reported_plugging_before','reported_plugging_after','cumulative_actual_plugging_count','history_basis']
            continue
        elif mode=='team_limit':
            if not compare(row.get('remaining_life_years'),settings['op'],settings['value']):
                if row.get('remaining_life_years') is None:diagnostics['한도 도달 시점 미산정 제외']+=1
                continue
        else:raise QueryRejected('지원하지 않는 열교환기 조회 조건입니다.')
        matched.append(row)
    if mode=='increase':matched.sort(key=lambda r:(-r['wall_loss_increase_percent_points'],r['heat_exchanger_id']))
    elif mode=='rate':matched.sort(key=lambda r:(-r['maximum_corrosion_rate_mm_per_year'],r['heat_exchanger_id']))
    elif mode=='material':matched.sort(key=lambda r:(r.get('maximum_loss') is None,-(r.get('maximum_loss') or 0),r['heat_exchanger_id']))
    elif mode=='sample':matched.sort(key=lambda r:(r['sample_count'],r['heat_exchanger_id']))
    equipment_count=len(matched)
    if mode=='team_limit':
        groups=[]
        for team in sorted({r.get('team_code') or '미등록' for r in matched}):
            members=[r for r in matched if (r.get('team_code') or '미등록')==team]
            def target_year(member):
                source=details[member['heat_exchanger_id']]['remaining_life']
                overview=source['equipment_overview']
                target=history.day(overview.get('target_date'))
                if target:return target.year
                if overview.get('estimated_reached'):
                    measured=history.day(overview.get('measurement_date'))
                    if measured:return measured.year
                return source.get('life_reached_year') or as_of.year
            earliest=min(members,key=lambda r:(target_year(r),r['remaining_life_years'],r['heat_exchanger_id']))
            years=earliest['remaining_life_years']
            groups.append(dict(team_code=team,exchanger_count=len(members),earliest_remaining_life_years=round(years,2),
                earliest_limit_year=target_year(earliest),earliest_exchanger=earliest['exchanger_code'],
                heat_exchanger_id=earliest['heat_exchanger_id'],equipment_list=', '.join(r['exchanger_code'] for r in members)))
        matched=groups;columns=['team_code','exchanger_count','earliest_remaining_life_years','earliest_limit_year','earliest_exchanger','equipment_list']
    result=dict(rows=matched[:settings['limit']],columns=columns,result_count=min(len(matched),settings['limit']),
        matched_count=len(matched),limit_reached=len(matched)>settings['limit'],result_unit=settings['result_unit'],
        filter_description=settings['description'],query_mode=mode,diagnostics=dict(diagnostics),
        calculation_date=as_of.isoformat(),matched_equipment_count=equipment_count,
        basis_note=basis_note(mode,settings))
    if mode=='history':result['matched_equipment_count']=1 if matched else 0
    return result,matched


def basis_note(mode,settings):
    return {
        'increase':'최근 두 유효 검사 날짜 · 같은 설치·번들 기준 · 부분/대체/무효 검사 제외 · 최대값 차이(%p), 표본 구성이 다를 수 있음',
        'rate':'분석 화면 기본 적용 감육속도(mm/년) · 유효한 양수만 검색 · 튜브 수는 조건 부합 튜브 수',
        'sample':'최근 유효 검사 집단의 표본 수 · IRIS 미실시 제외 · 표본 부족은 검사 범위 확대 검토 근거이며 자동 정비 판정이 아님',
        'material':'현재 승인 사양의 Tube 재질 · Cu-Ni/CuNi 표기 정규화 · 재질 코드의 임의 치환 없음',
        'overdue_iris':'IRIS 적용 REQUIRED·OPTIONAL만 포함 · 검사일 없으면 보고일 · 날짜 미상 이력은 판정 제외 · 기간 경계일 포함',
        'team_limit':f"한도 {settings.get('limit_percent',20):g}% 시뮬레이션 · 도달 상태(0년) 포함 · 산정 불가를 0년으로 집계하지 않음 · 예측 도달은 실제 완료·즉시 정비 지시가 아님",
        'history':'보고서 전/후 Plugging과 실제 완료 원장을 구분 · 미기록은 0본이 아님 · 취소된 완료는 실제 누적에서 제외 · 과거 설치/일부 구간은 표시로 구분',
        'status':'대시보드와 동일한 검사 이력·잔여수명 구간 기준',
    }[mode]


def aggregate_evidence(result,all_rows):
    """Narration facts for team/inspection rows, without fictional equipment-life stats."""
    statements=[]
    def add(key,section,text):statements.append(dict(id=key,section=section,text=text))
    unit='생산팀' if result['result_unit']=='team' else '검사 회차'
    add('G_SCOPE','overview',f"조회 조건: {result['filter_description']}. 조건 일치 {result['matched_count']}개 {unit} 중 {result['result_count']}행을 표시합니다.")
    if unit=='생산팀':
        add('G_STATE','overview',f"조건에 해당하는 열교환기는 전체 {result['matched_equipment_count']}대이며 생산팀별로 한 번씩 집계합니다.")
    else:
        add('G_STATE','overview',f"선택 설비의 유효 검사 이력 {len(all_rows)}회입니다. 회차별 최대 감육률과 보고서·실제 완료 수량을 구분합니다.")
    add('G_DATES','overview',f"조회 계산 기준일은 {result['calculation_date']}입니다. 과거 회차에 현재 잔여수명을 대입하지 않습니다.")
    for index,row in enumerate(all_rows[:8],1):
        if unit=='생산팀':
            message=f"{row['team_code']}: 조건 일치 {row['exchanger_count']}대. 가장 빠른 도달 설비 {row['earliest_exchanger']}, 잔여기간 {row['earliest_remaining_life_years']}년, 도달 연도 {row['earliest_limit_year']}년."
        else:
            value=lambda key:'미기록' if row.get(key) is None else str(row[key])
            message=f"{row['exchanger_code']} · {row['inspection_date']} · {row.get('report_number') or '보고서 번호 미등록'}: 최대 감육률 {value('maximum_loss')}%, 검사 표본 {row['inspected_tube_count']}본. 보고서 검사 후 Plugging {value('reported_plugging_after')}본, 실제 누적 완료 {value('cumulative_actual_plugging_count')}본."
        add(f'P{index:02d}','priorities',message)
    add('L_BASIS','limitations',result['basis_note'])
    if result.get('diagnostics'):add('L_EXCLUDED','limitations','조회 판정 제외: '+' · '.join(f'{reason} {count}대' for reason,count in result['diagnostics'].items()))
    if len(all_rows)>8:add('L_SELECTION','limitations','세부 의견은 표시 순서의 첫 8행을 후보로 사용하며 전체 표를 대신하지 않습니다.')
    return dict(total_rows=result['result_count'],matched_count=result['matched_count'],analyzed_count=len(all_rows),
        coverage_complete=True,stats={},examples=all_rows[:8],statements=statements,
        scope_label=f"{unit} {result['matched_count']}행 · 조회 기준일 {result['calculation_date']}")
