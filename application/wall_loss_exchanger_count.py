"""Deterministic count of distinct exchangers having a matching valid Tube result."""
import re

from iris2.llm_integration.question_language import normalize

THRESHOLD = re.compile(r'감육률\s*(-?\d+(?:\.\d+)?)\s*%\s*(이상|초과|이하|미만)')


def matches(question):
    text = normalize(question)
    return bool(THRESHOLD.search(text) and re.search(r'열교환기|교환기', text)
                and re.search(r'수량|개수|몇\s*대|대수|수\b|수[는를가]', text)
                and re.search(r'공정별|라인별|공정\s*별|라인\s*별|VCM1.*VCM2|구분', text, re.I))


def proposal(question):
    from iris2.llm_integration.text_to_sql import QueryRejected
    text = normalize(question)
    conditions = THRESHOLD.findall(text)
    if not matches(text) or len(conditions) != 1:
        raise QueryRejected('공정별 교환기 수는 감육률 조건 한 개를 지정하세요.')
    if re.search(r'평균|최대|최소|모든|전부|전체\s*(?:Tube|튜브)|비교|미검사|미등록|미만.*이상|이상.*이하|상위|하위|재질|두께', text, re.I):
        raise QueryRejected('이 집계는 감육률 조건을 만족하는 튜브가 하나 이상인 교환기 수입니다. 추가 조건 없이 질문하세요.')
    value, comparison = conditions[0]
    threshold = float(value)
    if not 0 <= threshold <= 100:
        raise QueryRejected('감육률은 0~100% 범위로 입력하세요.')
    operator = {'이상': '>=', '초과': '>', '이하': '<=', '미만': '<'}[comparison]
    return dict(sql=f'''SELECT unit_code, COUNT(DISTINCT heat_exchanger_id) AS exchanger_count
        FROM analysis_tubes WHERE wall_loss_percent {operator} ?
        GROUP BY unit_code ORDER BY unit_code ASC LIMIT 100''', parameters=[threshold])


def is_proposal(value):
    """Recognize only the fixed grammar; no model-generated aggregate extensions."""
    import sqlglot
    parameters = value.get('parameters', [])
    if len(parameters) != 1 or type(parameters[0]) not in (int, float) or not 0 <= parameters[0] <= 100:
        return False
    for comparison in ('이상', '초과', '이하', '미만'):
        sample = proposal(f'감육률 10% {comparison} 교환기 수량 공정별')
        sql = sqlglot.parse_one(sample['sql'], read='mysql').sql(dialect='mysql')
        if value.get('sql') == sql:
            return True
    return False
