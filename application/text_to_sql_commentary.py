"""Bounded local result narration, with signed server-owned evidence."""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

from iris2.hx_configuration import APP_DIR
from iris2.llm_integration.model_config import load_local_runtime_config
from iris2.llm_integration.text_to_sql import QueryRejected


def _day(value):
    try:return date.fromisoformat(str(value)[:10])
    except (TypeError,ValueError):return None


def evidence(result, *, all_rows=None):
    """Aggregate before the display limit; select evidence by risk, never input order."""
    rows=result['rows'] if all_rows is None else all_rows
    matched=result.get('matched_count',len(rows))
    today=datetime.now(timezone(timedelta(hours=9))).date()
    basis_days={str(r['calculation_date'])[:10] for r in rows if _day(r.get('calculation_date'))}
    # Each row's own analysis date governs overdue/near-due classification.
    def basis(r):return _day(r.get('calculation_date')) or today
    def reached(r):return r.get('remaining_life_years') is not None and r['remaining_life_years']<=0
    def overdue(r):return _day(r.get('recommendation_date')) is not None and _day(r['recommendation_date'])<basis(r)
    def short(r):return r.get('remaining_life_years') is not None and 0<r['remaining_life_years']<=5
    def unknown(r):return r.get('remaining_life_years') is None and r.get('analysis_status')!='NO_INSPECTION'
    def rank(r):
        due=_day(r.get('recommendation_date'))
        near=due is not None and due<=basis(r)+timedelta(days=365)
        tier=0 if reached(r) else 1 if overdue(r) else 2 if near else 3 if short(r) else 4 if unknown(r) else 5
        return (tier,due or date.max,r.get('remaining_life_years') if r.get('remaining_life_years') is not None else float('inf'),r['heat_exchanger_id'])
    stats=dict(reached=sum(reached(r) for r in rows),overdue=sum(overdue(r) for r in rows),
        short_life=sum(short(r) for r in rows),missing_life=sum(unknown(r) for r in rows),
        long_life=sum(r.get('remaining_life_years') is not None and r['remaining_life_years']>5 for r in rows),
        not_reached=sum(r.get('analysis_status')=='LIMIT_NOT_REACHED' for r in rows),
        uninspected=sum(r.get('analysis_status')=='NO_INSPECTION' for r in rows),
        missing_recommendation=sum(_day(r.get('recommendation_date')) is None for r in rows),
        small_sample=sum(r.get('sample_count') is not None and r['sample_count']<10 for r in rows))
    complete=len(rows)==matched
    statements=[]
    def add(identifier,section,text,**extra):
        statements.append(dict(id=identifier,section=section,text=text,**extra))
    add('G_SCOPE','overview',f"조회 조건: {result.get('filter_description') or '선택한 설비 범위'}. 조건 일치 {matched}대 중 표에는 {len(result['rows'])}대를 표시합니다. 종합 의견의 집계 대상은 {'조건 일치 전체' if complete else '확인 가능한'} {len(rows)}대입니다.")
    add('G_STATE','overview',f"분석상 도달 상태 {stats['reached']}대, 잔여수명 0년 초과 5년 이하 {stats['short_life']}대, 5년 초과 {stats['long_life']}대, IRIS 이력 미등록 {stats['uninspected']}대, 산정 불가 {stats['missing_life']}대(이 중 가용 데이터 한도 미도달 {stats['not_reached']}대)입니다.")
    add('G_DATES','overview',f"각 설비의 분석 기준일 대비 검사 권고일 경과 {stats['overdue']}대, 권고일 미산정 {stats['missing_recommendation']}대입니다.")
    keys=['heat_exchanger_id','exchanger_code','team_code','unit_code','matching_tube_count',
          'remaining_display','recommendation_date','maximum_loss','life_source','first_display','measured_estimated_loss']
    examples=[]
    for index,row in enumerate(sorted(rows,key=rank)[:8],1):
        code=row.get('exchanger_code') or row.get('equipment_tag') or '설비코드 미등록'
        reason='분석상 도달 상태' if reached(row) else '검사 권고일 경과' if overdue(row) else '검사 권고일이 가까운 순서' if rank(row)[0]==2 else '잔여수명 5년 이하' if short(row) else '산정 자료 확인 대상' if unknown(row) else '가용 데이터 한도 미도달' if row.get('analysis_status')=='LIMIT_NOT_REACHED' else '권고일·잔여수명 순서'
        value=f"{code} [{row.get('team_code') or '생산팀 미등록'} / {row.get('unit_code') or '공정 미등록'}]: {reason}. 예상 잔여수명 {row.get('remaining_display') or '산정 불가'}, 차기 검사 권고일 {row.get('recommendation_date') or '산정 불가'}"
        if row.get('maximum_loss') is not None:value+=f", 최대 감육률 {row['maximum_loss']}%"
        if row.get('matching_tube_count') is not None:value+=f", 조건 해당 튜브 {row['matching_tube_count']}본"
        if row.get('life_source'):value+=f". 산정 근거: {row['life_source']}"
        if row.get('uncalculable_reason'):value+=f". 미산정 사유: {row['uncalculable_reason']}"
        if row.get('wall_loss_increase_percent_points') is not None:
            value+=f". 최대 감육률 변화 {row['previous_maximum_loss']}% → {row['latest_maximum_loss']}%, {row['wall_loss_increase_percent_points']}%p"
        if row.get('maximum_corrosion_rate_mm_per_year') is not None:
            value+=f". 최대 적용 감육속도 {row['maximum_corrosion_rate_mm_per_year']}mm/년"
        if row.get('sample_review_reason'):value+=f". {row['sample_review_reason']}"
        if row.get('tube_material'):value+=f". 현재 Tube 재질 {row['tube_material']}"
        if row.get('missing_inspection_reason'):value+=f". {row['missing_inspection_reason']}"
        add(f'P{index:02d}','priorities',value+'.',equipment_id=row['heat_exchanger_id'],equipment_code=code)
        examples.append({k:row.get(k) for k in keys})
    add('L_BASIS','limitations','잔여수명과 검사 권고일은 분석 화면의 계산값입니다. 기준 도달 상태를 즉시 교체 지시로 해석하지 않으며, 정비 조치는 승인된 검사·정비 기준으로 판단해야 합니다.')
    if stats['missing_life'] or stats['missing_recommendation']:
        add('L_MISSING','limitations',f"잔여수명 미산정 {stats['missing_life']}대와 권고일 미산정 {stats['missing_recommendation']}대는 0년 또는 즉시 검사로 간주하지 않습니다.")
    if stats['small_sample']:
        add('L_SAMPLE','limitations',f"유효 표본 10본 미만 {stats['small_sample']}대입니다. 표본 부족만으로 안전 여부나 검사 범위 확대를 확정하지 않습니다.")
    if len(rows)>len(examples):
        add('L_SELECTION','limitations',f"전체 집계와 별도로 우선 확인 상세 근거는 {len(examples)}대이며, 도달 상태·권고일 경과·가까운 권고일·짧은 잔여수명 순으로 선정했습니다.")
    if not complete:
        add('L_PARTIAL','limitations','조건 일치 전체의 상세 자료가 없어 확인 가능한 결과만 집계했습니다. 전체 집계로 해석하지 마세요.')
    if len(basis_days)>1:
        add('L_DATES','limitations','분석 기준일이 다른 설비가 포함되어 있으므로 설비별 기준일을 함께 확인해야 합니다.')
    return dict(total_rows=len(result['rows']),matched_count=matched,analyzed_count=len(rows),
        coverage_complete=complete,stats=stats,examples=examples,statements=statements)


def validate(payload, facts):
    """The model selects fact IDs; all rendered claims come from signed evidence."""
    allowed={f['id']:f for f in facts.get('statements',[])}
    if not isinstance(payload,dict) or set(payload)!={'overview','priorities','limitations'}:
        raise QueryRejected('종합 의견의 세 부분을 확인할 수 없습니다.')
    required={'G_SCOPE','G_STATE','G_DATES','L_BASIS'}
    required.update(f['id'] for f in allowed.values() if f['section']=='limitations')
    if any(f['section']=='priorities' for f in allowed.values()):required.add('P01')
    selected=set();sections=[]
    for key,title in [('overview','조회 요약'),('priorities','우선 확인 대상'),('limitations','해석의 한계')]:
        identifiers=payload[key]
        if (not isinstance(identifiers,list) or len(identifiers)>12
                or any(not isinstance(i,str) or i not in allowed or allowed[i]['section']!=key for i in identifiers)
                or len(set(identifiers))!=len(identifiers)):
            raise QueryRejected('조회 근거와 일치하지 않는 종합 의견을 표시하지 않습니다.')
        selected.update(identifiers)
        # Priority order stays tied to the server's risk classification.
        order=sorted(identifiers) if key=='priorities' else identifiers
        sections.append(dict(key=key,title=title,items=[allowed[i] for i in order]))
    if not required<=selected:
        raise QueryRejected('전체 집계·최우선 대상·해석 제한이 누락되어 종합 의견을 표시하지 않습니다.')
    return sections


def generate(facts):
    config=load_local_runtime_config(APP_DIR/'llm_integration/models.local.json')
    name=config.models[config.default_model_key].model_name
    if not facts['total_rows']:
        return dict(status='empty',text='조건에 맞는 열교환기가 없어 종합 의견을 생성하지 않았습니다.',model=name)
    env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','LLAMA_CPP_LIB_PATH','LLAMA_N_GPU_LAYERS','LLAMA_N_CTX'):
        env.pop(key,None)
    env.update(PYTHONIOENCODING='utf-8',LLAMA_N_THREADS='8',LLAMA_N_GPU_LAYERS='0')
    try:
        process=subprocess.run([sys.executable,str(APP_DIR/'tools/summarize_text_to_sql.py')],
            input=json.dumps(facts,ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',
            cwd=APP_DIR,env=env,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output=json.loads(process.stdout)
    except (subprocess.TimeoutExpired,ValueError) as exc:
        raise QueryRejected('로컬 종합 의견을 생성하지 못했습니다. 조회 표는 그대로 확인할 수 있습니다.') from exc
    if process.returncode or not isinstance(output,dict) or output.get('error'):
        raise QueryRejected('로컬 모델 실행에 실패했습니다. 조회 표는 그대로 확인할 수 있습니다.')
    sections=validate(output,facts)
    text='\n\n'.join(section['title']+'\n'+'\n'.join(item['text'] for item in section['items']) for section in sections)
    return dict(status='generated',text=text,sections=sections,model=name,
                method='AI 근거 선정·구성 / 수치 문장은 서버 확인값',
                scope=facts.get('scope_label') or f"조건 일치 {facts['matched_count']}대 중 {facts['analyzed_count']}대 집계 · 우선 후보 근거 {len(facts['examples'])}대",example_count=len(facts['examples']))
