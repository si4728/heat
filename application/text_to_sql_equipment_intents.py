"""Explicit advanced equipment intents; unsupported conditions never become all rows."""
import re
from ..llm_integration.text_to_sql import QueryRejected

NUMBER=r'(\d+(?:\.\d+)?)'
OP=r'(이하|미만|이상|초과|이내)'
UNITS={'equipment':'열교환기별 1행','team':'생산팀별 1행','inspection':'검사 회차별 1행'}


def compare(actual,op,value):
    if actual is None:return False
    return {'이하':lambda:actual<=value,'이내':lambda:actual<=value,'미만':lambda:actual<value,
            '이상':lambda:actual>=value,'초과':lambda:actual>value}[op]()


def parse(question):
    q=re.sub(r'\s+',' ',question).strip()
    top=re.search(r'(?:상위\s*)?(\d+)\s*(?:대|개)',q)
    limit=int(top[1]) if top else 100
    if not 1<=limit<=100:raise QueryRejected('조회 개수는 1~100대입니다.')
    base=dict(conditions=[],limit=limit,explicit_limit=bool(top),sort='equipment')
    triggers=[]
    if re.search(r'회차\s*별|추이',q):triggers.append('history')
    if re.search(r'증가',q):triggers.append('increase')
    if re.search(r'감육\s*속도',q):triggers.append('rate')
    if re.search(r'표본',q):triggers.append('sample')
    if re.search(r'재질|Cu\s*[-−–]?\s*Ni',q,re.I):triggers.append('material')
    if re.search(r'IRIS\s*적용\s*대상',q,re.I):triggers.append('overdue_iris')
    if re.search(r'Plugging',q,re.I) and 'history' not in triggers:triggers.append('team_limit')
    if not triggers:
        if re.search(r'IRIS\s*미실시|산정\s*불가',q,re.I):
            if re.search(r'최근|기간|평균|(?:잔여\s*수명|감육률)(?:이|은|가|는)?\s*\d',q):
                raise QueryRejected('상태 조회와 기간·수치 조건은 나누어 질문하세요.')
            status='uninspected' if re.search(r'IRIS\s*미실시',q,re.I) else 'unknown'
            return dict(base,mode='status',status=status,result_unit='equipment',description='IRIS 이력 미등록 설비' if status=='uninspected' else '검사 이력은 있으나 수명 수치 산정 불가')
        return None
    if len(triggers)!=1:
        raise QueryRejected('서로 다른 고급 조회 조건은 한 가지씩 질문하세요. 조건을 임의로 생략하지 않습니다.')
    if re.search(r'평균|온도|압력|예측해|계산해|기간|\d{4}\s*년',q):
        raise QueryRejected('고급 조회는 현재 분석값 또는 등록 검사 이력을 사용합니다. 기간·운전조건 복합 비교는 지원하지 않습니다.')
    mode=triggers[0]
    if mode!='overdue_iris' and re.search(r'지난|최근\s*\d+\s*(?:년|개월|달|일)|\d+\s*년\s*(?:간|동안|부터)',q):
        raise QueryRejected('고급 조회의 별도 기간 조건은 지원하지 않습니다. 기간을 임의로 생략하지 않습니다.')
    options=dict(base,mode=mode,result_unit='equipment')
    remaining_numeric=q
    if mode=='history':
        if re.search(r'이상|이하|미만|초과|증가|생산팀별',q):
            raise QueryRejected('회차별 추이는 별도 조건 없이 한 설비의 검사 이력을 조회하세요.')
        recent=re.search(r'최근\s*(\d+|두|한)\s*(?:회|번)',q)
        count={'두':2,'한':1}.get(recent[1],int(recent[1]) if recent and recent[1].isdigit() else 100) if recent else 100
        if not 1<=count<=100:raise QueryRejected('검사 이력 조회는 최대 100회입니다.')
        options.update(result_unit='inspection',limit=count,description='검사 회차별 최대 감육률·보고서 Plugging·실제 완료 이력')
    elif mode=='increase':
        if not re.search(r'최근\s*(?:두|2)\s*(?:번|회)',q) or '증가율' in q:
            raise QueryRejected('최근 두 번의 검사 간 최대 감육률 차이를 %p로 조회하세요.')
        found=re.search(NUMBER+r'\s*%\s*(?:p|포인트)?\s*'+OP,q,re.I)
        if not found or float(found[1])>100:raise QueryRejected('증가 조건은 최대 감육률 5%p 이상 증가처럼 입력하세요.')
        options.update(value=float(found[1]),op=found[2],description=f'최근 두 유효 검사 최대 감육률 차이 {found[1]}%p {found[2]}')
        remaining_numeric=q[:found.start()]+q[found.end():]
    elif mode=='rate':
        found=re.search(r'감육\s*속도(?:가|는|이|은)?\s*'+NUMBER+r'\s*mm\s*/\s*(?:년|year|yr)\s*'+OP,q,re.I)
        if not found:raise QueryRejected('감육속도 조건은 0.1 mm/년 이상처럼 단위와 함께 입력하세요.')
        options.update(value=float(found[1]),op=found[2],description=f'분석 적용 감육속도 {found[1]}mm/년 {found[2]} 튜브 보유')
    elif mode=='sample':
        found=re.search(r'표본(?:\s*수)?(?:이|가|은|는)?\s*(\d+)\s*본\s*'+OP,q)
        if not found:raise QueryRejected('표본 조건은 검사 표본 10본 미만처럼 입력하세요.')
        value=int(found[1])
        if not 0<=value<=100000:raise QueryRejected('표본 수 조건을 확인하세요.')
        if re.search(r'재검사|범위',q) and found[2] not in ('미만','이하'):
            raise QueryRejected('재검사 검토 대상은 표본 수 미만·이하 조건으로 조회하세요.')
        options.update(value=value,op=found[2],description=f'최근 유효 검사 표본 {value}본 {found[2]} · 검사 범위 확대 검토 대상')
    elif mode=='material':
        if re.search(r'Shell|Head|쉘',q,re.I) or not re.search(r'Cu\s*[-−–]?\s*Ni',q,re.I):
            raise QueryRejected('현재 지원하는 재질 조건은 Tube 재질 Cu-Ni입니다.')
        if re.search(r'이상|이하|초과|미만|잔여',q):raise QueryRejected('재질 순위는 다른 수치 조건 없이 조회하세요.')
        options.update(material='CUNI',sort='loss',description='현재 승인 사양 Tube 재질 Cu-Ni · 현재 유효 최대 감육률 순위')
    elif mode=='overdue_iris':
        found=re.search(r'최근\s*(\d+)\s*년',q)
        if not found or not re.search(r'없|미검사|미실시',q):raise QueryRejected('IRIS 적용 대상 중 최근 5년간 검사 이력이 없는 설비처럼 질문하세요.')
        years=int(found[1])
        if not 1<=years<=100:raise QueryRejected('무검사 기간은 1~100년입니다.')
        options.update(years=years,description=f'IRIS 적용 대상(REQUIRED·OPTIONAL) 중 최근 {years}년간 검사 이력 없음')
    else:
        found=re.search(r'Plugging\s*'+NUMBER+r'\s*%',q,re.I)
        horizon=re.search(r'도달(?:까지|이)?\s*'+NUMBER+r'\s*년\s*'+OP,q)
        if not found or not horizon or not re.search(r'생산팀\s*별',q):
            raise QueryRejected('Plugging 20% 도달까지 10년 이내인 설비를 생산팀별로 집계해 주세요.')
        percent=float(found[1]);years=float(horizon[1])
        if not percent.is_integer() or not 1<=percent<=20 or years>100:
            raise QueryRejected('Plugging 한도는 1~20%, 조회 기간은 0~100년입니다.')
        options.update(result_unit='team',limit_percent=percent,value=years,op=horizon[2],
            description=f'Plugging {percent:g}% 한도 초과까지 {years:g}년 {horizon[2]} · 생산팀별 집계')
    # A second numeric condition must never disappear silently.
    if re.search(r'(?:잔여\s*수명|감육률)(?:이|은|가|는)?\s*\d',remaining_numeric):
        raise QueryRejected('고급 조회와 잔여수명·감육률 수치 조건은 나누어 질문하세요.')
    return options
