"""Server-owned Korean date ranges shared by Text-to-SQL query paths."""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

from iris2.llm_integration.text_to_sql import QueryRejected

DAY = r'\d{4}[-./]\d{1,2}[-./]\d{1,2}'


def _months_before(today, months):
    year, month = divmod(today.year * 12 + today.month - 1 - months, 12)
    return date(year, month + 1, min(today.day, calendar.monthrange(year, month + 1)[1]))


def parse(question, today=None):
    """Return (inclusive period or None, question with only the date phrase removed).

    Reject malformed/ambiguous date expressions rather than silently using latest.
    """
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    patterns = [
        ('range', rf'({DAY})\s*(?:부터|~|～|–|—|\bto\b)\s*({DAY})(?:\s*까지)?'),
        ('month', r'(?<!\d)(\d{4})\s*년\s*(\d{1,2})\s*월'),
        ('calendar', r'이번\s*달|이달|지난\s*달|전월|이번\s*주|지난\s*주|오늘|어제|상반기|하반기'),
        ('relative', r'최근\s*(\d+)\s*(년|개월|달|일)'),
        ('year', r'(?<!\d)(\d{4})\s*년'),
        ('named', r'올해|작년|전체\s*(?:기간|이력)'),
    ]
    found = []
    remaining = question
    for kind, pattern in patterns:
        for match in list(re.finditer(pattern, remaining)):
            found.append((kind, match))
        remaining = re.sub(pattern, lambda m: ' ' * len(m[0]), remaining)
    if len(found) > 1:
        raise QueryRejected('기간을 하나만 지정하세요. 예: 최근 3개월 또는 2025-01-01~2025-12-31')
    if re.search(r'최근\s*(?:\d|한|두|세|몇)|\d{4}[-./]|\d+\s*(?:년|개월|달|일)|올\s*해|작\s*년|내년|내일|다음\s*(?:달|주|해)|지난|이번|기간|부터|까지', remaining):
        raise QueryRejected('기간은 최근 N년·N개월·N일, 이번 달·지난달, 이번 주·지난주, 오늘·어제, 상반기·하반기, 올해·작년, YYYY년 M월, 날짜 범위 또는 전체 이력으로 입력하세요.')
    if not found:
        return None, question
    kind, match = found[0]
    try:
        if kind == 'range':
            start, end = [date(*map(int, re.split(r'[-./]', value))) for value in match.groups()]
        elif kind == 'relative':
            number, unit = int(match[1]), match[2]
            maximum = {'년':100, '개월':1200, '달':1200, '일':36525}[unit]
            if not 1 <= number <= maximum:
                raise ValueError()
            start = (_months_before(today, number * 12) if unit == '년' else
                     _months_before(today, number) if unit in ('개월', '달') else
                     today - timedelta(days=number))
            end = today
        elif kind == 'year':
            start, end = date(int(match[1]),1,1), date(int(match[1]),12,31)
        elif kind == 'month':
            year, month = int(match[1]), int(match[2])
            start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
        elif kind == 'calendar':
            phrase = re.sub(r'\s+', '', match[0])
            if phrase in ('이번달', '이달', '지난달', '전월'):
                anchor = today.replace(day=1)
                if phrase in ('지난달', '전월'):
                    anchor -= timedelta(days=1)
                start = anchor.replace(day=1)
                end = date(anchor.year, anchor.month, calendar.monthrange(anchor.year, anchor.month)[1])
            elif phrase in ('이번주', '지난주'):
                start = today - timedelta(days=today.weekday())
                if phrase == '지난주':
                    start -= timedelta(days=7)
                end = start + timedelta(days=6)
            elif phrase in ('오늘', '어제'):
                start = end = today - timedelta(days=phrase == '어제')
            else:
                start = date(today.year, 1 if phrase == '상반기' else 7, 1)
                end = date(today.year, 6, 30) if phrase == '상반기' else date(today.year, 12, 31)
        elif match[0] == '올해':
            start, end = date(today.year,1,1), today
        elif match[0] == '작년':
            start, end = date(today.year-1,1,1), date(today.year-1,12,31)
        else:
            start, end = date(1000,1,1), today
        if start < date(1000,1,1) or start > end or end >= date.max:
            raise ValueError()
        # Historical inspection queries never include future records.
        end = min(end, today)
        if start > end:
            raise ValueError()
    except (ValueError, OverflowError):
        raise QueryRejected('유효한 과거 기간을 입력하세요. 시작일은 종료일보다 늦을 수 없습니다.') from None
    period = dict(start=start.isoformat(), end=end.isoformat())
    if kind == 'named' and '전체' in match[0]:
        period['all_history'] = True
    return period, re.sub(r'\s+', ' ', remaining).strip()
