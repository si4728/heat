"""Supported sample questions; help never generates or executes SQL."""
import re

PATTERN = r'(?:도움말(?:\s*(?:알려\s*줘(?:요)?|보여\s*줘(?:요)?|알려\s*주세요|보여\s*주세요))?|사용법|예시\s*질문|샘플(?:\s*질문)?|help)'
EXAMPLES = (
    '검사 결과를 요약해 줘.',
    '감육이 가장 심한 Tube 5개를 알려줘.',
    '감육률 30% 이상인 Tube를 보여줘.',
    '튜브별 감육률 10% 이상인 교환기 수량은, VCM1과 VCM2로 구분해줘',
    '최근 IRIS 검사를 제일 많이 수행한 열교환기를 리스트해줘.',
    '최근 3개월 검사를 제일 많이한 튜브 10개 리스트 해줘, 튜브번호 별 1행씩',
    'E-111의 2025년 IRIS 검사 보고서 PDF 보여줘.',
    '2025년 감육률 10% 이상인 교환기 수량을 VCM1과 VCM2로 구분해줘',
)


def matches(question):
    return isinstance(question, str) and bool(re.fullmatch(PATTERN + r'[.!?。？！]*', question.strip(), re.I))


def response():
    return dict(query_kind='help', examples=list(EXAMPLES),
                guidance='예시를 선택하면 질문창에 입력됩니다. 검사 요약·튜브 목록은 먼저 교환기 또는 공정을 선택하세요. 기간을 생략하면 최근 유효 검사 기준이며, 검사 횟수 순위는 설비 최근 5년·튜브 전체 이력 기준입니다. 기간은 질문 앞에 입력할 수 있습니다. 조회 결과의 차트 유형은 아래 차트 영역에서 변경합니다.')
