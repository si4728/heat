"""Equipment rows backed by the same overview used by the analysis screen."""
from datetime import datetime, timezone
import hashlib
import re

from iris2 import dbapi, services
from iris2.application import text_to_sql_fluids as fluids
from iris2.hx_configuration import DB_PATH
from iris2.llm_integration.text_to_sql import QueryRejected


def options(question):
    if not re.search(r'열교환기|교환기|설비|검사|잔여|감육|권고|분석',question):
        raise QueryRejected('열교환기 목록·잔여수명·차기 검사 권고일을 질문하세요.')
    date_filter=re.search(r'차기\s*검사\s*권고일(?:이|은|가)?\s*(\d{4})\s*년\s*(이내|이전|이후)',question)
    remaining_question=question[:date_filter.start()]+question[date_filter.end():] if date_filter else question
    if re.search(r'평균|최소|재질|온도|압력|기간|비교|예측해|계산해|\d{4}\s*년|최근\s*(?:\d|두|한)|감육\s*속도|표본|추이|회차별|증가|Plugging|적용\s*대상', remaining_question,re.I):
        raise QueryRejected('열교환기 결과는 현재 분석값을 조회합니다. 평균·최소·기간·운전조건 비교는 지원하지 않습니다.')
    conditions = []
    for field, pattern in [('remaining_life_years',r'잔여\s*수명(?:이|은|가)?\s*(\d+(?:\.\d+)?)\s*년\s*(이하|미만|이상|초과)'),
                           ('maximum_loss',r'감육률(?:이|은|가)?\s*(\d+(?:\.\d+)?)\s*%\s*(이하|미만|이상|초과)')]:
        found = re.findall(pattern, question)
        if len(found)>1:
            raise QueryRejected('각 조회 항목에 조건을 하나만 지정하세요.')
        if found:
            value, op = found[0]
            if field=='maximum_loss' and float(value)>100:
                raise QueryRejected('감육률은 0~100%입니다.')
            conditions.append([field,op,float(value)])
    if date_filter:
        year,op=date_filter.groups()
        conditions.append(['recommendation_date',{'이내':'이하','이전':'미만','이후':'초과'}[op],
                           f'{year}-12-31' if op=='이내' else f'{year}-01-01'])
    if re.search(r'잔여\s*수명(?:이|은|가)?\s*\d|감육률(?:이|은|가)?\s*\d',question) and not conditions:
        raise QueryRejected('조건은 잔여수명 5년 이하 또는 최대 감육률 30% 이상처럼 입력하세요.')
    if re.search(r'차기.*(?:이전|이후|까지|부터)|미검사|미등록|STEAM|유체',remaining_question,re.I):
        raise QueryRejected('해당 조건은 열교환기 분석 조회에서 아직 지원하지 않습니다. 유체명별 집계는 별도 질문으로 조회하세요.')
    match = re.search(r'(?:상위\s*)?(\d+)\s*(?:대|개)',question)
    limit = int(match[1]) if match else 100
    if not 1<=limit<=100:
        raise QueryRejected('조회 개수는 1~100대입니다.')
    return dict(conditions=conditions,limit=limit,explicit_limit=bool(match),sort='loss' if re.search(r'감육.*(?:상위|심한|큰)|(?:상위|심한).*감육',question) else 'equipment')


def proposal(ids):
    if not ids or len(ids)>500 or any(type(i) is not int or i<=0 for i in ids):
        raise QueryRejected('조회 설비 범위가 올바르지 않습니다.')
    return dict(sql='''SELECT hx.heat_exchanger_id, u.unit_code, e.equipment_code,
        e.equipment_tag, e.equipment_name FROM heat_exchanger hx
        JOIN equipment e ON e.equipment_id=hx.equipment_id
        JOIN process_unit u ON u.unit_id=e.unit_id
        WHERE u.unit_code IN ('PE','VCM1','VCM2') AND hx.heat_exchanger_id IN ('''+','.join('?' for _ in ids)+''')
        ORDER BY u.unit_code,e.equipment_tag,hx.heat_exchanger_id LIMIT 500''', parameters=ids)


def execute(ids, settings, signed, allowed):
    expected=proposal(ids)
    if not set(ids)<=set(allowed):
        raise PermissionError('현재 조회할 수 없는 설비가 포함되어 있습니다.')
    if signed!=expected:
        raise QueryRejected('열교환기 조회 SQL이 변경되었습니다. 다시 생성하세요.')
    connection=dbapi.connect(DB_PATH,readonly=True,readonly_profile='text_to_sql')
    try:
        grants=connection.execute('SHOW GRANTS').fetchall()
        if not grants or any(not re.match(r'^GRANT (?:USAGE|SELECT) ON ',str(r[0]),re.I)
                            or re.search(r'\bWITH GRANT OPTION\b',str(r[0]),re.I) for r in grants):
            raise QueryRejected('SELECT 전용 계정이 필요합니다.')
        connection.execute('SET SESSION max_statement_time=5')
        masters=[dict(r) for r in connection.execute(expected['sql'],tuple(ids)).fetchall()]
    finally:
        connection.rollback();connection.close()
    rows=[]
    for master in masters:
        detail=services.exchanger_detail(master['heat_exchanger_id'])
        if not detail:
            raise QueryRejected('조회 중 설비 정보가 변경되었습니다. 다시 조회하세요.')
        life=detail['remaining_life']; overview=life['equipment_overview']
        summary=life['equipment_summary']
        losses=[r['wall_loss_percent'] for r in life.get('analysis_tube_rows',[]) if r.get('wall_loss_percent') is not None]
        team=getattr(detail.get('master',[None,None])[1],'production_team_code',None)
        short_code=getattr(detail.get('spec'),'exchanger_code',None)
        if not short_code:
            match=re.search(r'(?:AE|ER|E)-?\d+[A-Za-z]*(?:-\d+)?$',master.get('equipment_tag',''))
            short_code=match[0] if match else master.get('equipment_tag')
        row=dict(master,latest_inspection_date=summary.get('latest_inspection_date'),
                 team_code=team,exchanger_code=short_code,
                 maximum_loss=max(losses) if losses else None,
                 remaining_life_years=overview['remaining_life_years'],
                 remaining_display=overview['remaining_display'],life_source=overview['source'],
                 recommendation_date=overview['recommendation_date'],
                 first_display=overview.get('first_display'),
                 measured_max=overview.get('measured_max'),estimated_max=overview.get('estimated_max'),
                 sample_count=overview.get('sample_count'),sample_status=overview.get('sample_status'),
                 analysis_status=overview.get('status'),
                 uncalculable_reason=overview.get('uncalculable_reason'),
                 calculation_date=life.get('as_of_date'))
        measured,estimated=row['measured_max'],row['estimated_max']
        row['measured_estimated_loss']=('—' if measured is None else f'{measured:.1f}')+' / '+('—' if estimated is None else f'{estimated:.1f}')
        keep=True
        tube_conditions=[(op,value) for field,op,value in settings['conditions'] if field=='maximum_loss']
        row['matching_tube_count']=None
        if tube_conditions:
            op,value=tube_conditions[0]
            check={'이하':lambda x:x<=value,'미만':lambda x:x<value,'이상':lambda x:x>=value,'초과':lambda x:x>value}[op]
            row['matching_tube_count']=sum(check(loss) for loss in losses)
        for field,op,value in settings['conditions']:
            actual=row[field]
            keep=keep and actual is not None and {'이하':lambda x:x<=value,'미만':lambda x:x<value,
                                                 '이상':lambda x:x>=value,'초과':lambda x:x>value}[op](actual)
        if keep:rows.append(row)
    if settings['sort']=='loss':
        rows.sort(key=lambda r:(r['maximum_loss'] is None,-(r['maximum_loss'] or 0),r['heat_exchanger_id']))
    limit=settings['limit']; total=len(rows)
    columns=['team_code','unit_code','exchanger_code','equipment_name','latest_inspection_date']
    if any(c[0]=='maximum_loss' for c in settings['conditions']):columns+=['matching_tube_count','maximum_loss']
    columns+=['remaining_display','life_source','first_display','measured_estimated_loss','recommendation_date','uncalculable_reason']
    names={'remaining_life_years':'예상 잔여수명','maximum_loss':'최대 감육률','recommendation_date':'차기 검사 권고일'}
    units={'remaining_life_years':'년','maximum_loss':'%','recommendation_date':''}
    filter_description=' · '.join(f'{names[field]} {value}{units[field]} {op}' for field,op,value in settings['conditions']) or '선택한 설비 범위의 현재 기본 분석값'
    result=dict(query_kind='equipment_analysis',columns=columns,
        rows=rows[:limit],result_count=min(total,limit),matched_count=total,limit_reached=total>limit,
        filter_description=filter_description,
        query_sha256=hashlib.sha256(expected['sql'].encode()).hexdigest(),
        generated_at=datetime.now(timezone.utc).isoformat())
    from iris2.application.text_to_sql_commentary import evidence
    if settings.get('explicit_limit'):
        summary_result=dict(result,matched_count=len(rows[:limit]),
            filter_description=filter_description+f' · 조건 부합 전체 {total}대 중 요청한 {limit}대 범위')
        result['_commentary_facts']=evidence(summary_result,all_rows=rows[:limit])
    else:
        result['_commentary_facts']=evidence(result,all_rows=rows)
    return result
