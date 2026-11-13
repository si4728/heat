"""Bounded inspection-history ranking intent; never execute model-generated joins."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import re

from iris2 import dbapi
from iris2.application import query_period
from iris2.hx_configuration import DB_PATH
from iris2.llm_integration.text_to_sql import QueryRejected


def tube_ranking(question):
    return bool(re.search(r'튜브|tube', question, re.I))


def matches(question):
    return bool(re.search(r'열교환기|교환기|설비|튜브|tube', question, re.I) and '검사' in question
                and re.search(r'(?:제일|가장)\s*많|많이|횟수|빈도|건수', question))


def options(question, today=None):
    if re.search(r'잔여수명|차기|예측|건전성|종합의견|비교|적은|적게',question):
        raise QueryRejected('검사 횟수 이력 조회만 지원합니다. 수명·차기검사 예측은 별도 분석을 사용하세요.')
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    tubes = tube_ranking(question)
    period, ranking_question = query_period.parse(question, today)
    count = re.search(r'(?:상위\s*)?(\d+)\s*(?:대|개(?!월))', ranking_question)
    limit = int(count[1]) if count else 20
    if not 1 <= limit <= 100:
        raise QueryRejected('순위 조회 개수는 1~100개입니다.')
    if period is None:
        period = (dict(start='1000-01-01', end=today.isoformat()) if tubes else
                  query_period.parse('최근 5년', today)[0])
    start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
    result = dict(start=start.isoformat(),end=end.isoformat(),limit=limit)
    if period.get('all_history'):
        result['all_history'] = True
    if tubes:
        result.update(target='tube', all_history=start == date(1000,1,1))
    return result


def proposal(ids, period):
    if not ids or len(ids)>500 or any(type(i) is not int or i<=0 for i in ids):
        raise QueryRejected('조회 설비 범위가 올바르지 않습니다.')
    # Only the server constructs this SQL; no grammar/model extension is needed.
    sql = '''SELECT hx.heat_exchanger_id, u.unit_code, e.equipment_tag,
        e.equipment_code, e.equipment_name,
        COUNT(DISTINCT i.iris_inspection_id) AS inspection_count,
        MAX(COALESCE(i.inspection_date,i.report_date)) AS latest_inspection_date
        FROM iris_inspection i
        JOIN heat_exchanger hx ON hx.heat_exchanger_id=i.heat_exchanger_id
        JOIN equipment e ON e.equipment_id=hx.equipment_id
        JOIN process_unit u ON u.unit_id=e.unit_id
        WHERE hx.heat_exchanger_id IN (''' + ','.join('?' for _ in ids) + ''')
        AND u.unit_code IN ('VCM1','VCM2')
        AND UPPER(TRIM(i.inspection_method))='IRIS'
        AND i.superseded_by_inspection_id IS NULL
        AND COALESCE(i.inspection_date,i.report_date)>=?
        AND COALESCE(i.inspection_date,i.report_date)<?
        GROUP BY hx.heat_exchanger_id,u.unit_code,e.equipment_tag,e.equipment_code,e.equipment_name
        ORDER BY inspection_count DESC,latest_inspection_date DESC,hx.heat_exchanger_id ASC
        LIMIT ''' + str(period['limit'])
    if period.get('target') == 'tube':
        sql = """SELECT hx.heat_exchanger_id, u.unit_code, e.equipment_tag,
            b.bundle_code, t.tube_no,
            COUNT(DISTINCT i.iris_inspection_id) AS inspection_count,
            MAX(COALESCE(i.inspection_date,i.report_date)) AS latest_inspection_date
            FROM iris_tube_result r
            JOIN iris_inspection i ON i.iris_inspection_id=r.iris_inspection_id
            JOIN heat_exchanger_tube t ON t.tube_id=r.tube_id
            JOIN tube_bundle b ON b.bundle_id=t.bundle_id
            JOIN heat_exchanger hx ON hx.heat_exchanger_id=b.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE hx.heat_exchanger_id IN (""" + ','.join('?' for _ in ids) + """)
            AND i.heat_exchanger_id=hx.heat_exchanger_id
            AND u.unit_code IN ('VCM1','VCM2')
            AND UPPER(TRIM(i.inspection_method))='IRIS'
            AND i.superseded_by_inspection_id IS NULL AND r.result_status='VALID'
            AND COALESCE(i.inspection_date,i.report_date)>=?
            AND COALESCE(i.inspection_date,i.report_date)<?
            GROUP BY hx.heat_exchanger_id,u.unit_code,e.equipment_tag,b.bundle_code,t.tube_no
            ORDER BY inspection_count DESC,u.unit_code ASC,e.equipment_tag ASC,
                     hx.heat_exchanger_id ASC,b.bundle_code ASC,t.tube_no ASC
            LIMIT """ + str(period['limit'])
    end_exclusive=(date.fromisoformat(period['end'])+timedelta(days=1)).isoformat()
    return dict(sql=sql,parameters=[*ids,period['start'],end_exclusive])


def execute(ids, period, signed_proposal, allowed):
    if not set(ids)<=set(allowed):
        raise PermissionError('현재 조회할 수 없는 설비가 포함되어 있습니다.')
    expected = proposal(ids,period)
    if signed_proposal != expected:
        raise QueryRejected('검사 횟수 조회 SQL이 변경되었습니다. 다시 생성하세요.')
    connection=dbapi.connect(DB_PATH,readonly=True,readonly_profile='text_to_sql')
    try:
        grants=connection.execute('SHOW GRANTS').fetchall()
        if not grants or any(not re.match(r'^GRANT (?:USAGE|SELECT) ON ',str(r[0]),re.I)
                             or re.search(r'\bWITH GRANT OPTION\b',str(r[0]),re.I) for r in grants):
            raise QueryRejected('SELECT 전용 읽기 계정이 필요합니다.')
        connection.execute('SET SESSION max_statement_time=5')
        connection.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        cursor=connection.execute(expected['sql'],tuple(expected['parameters']))
        rows=[dict(row) for row in cursor.fetchmany(period['limit'])]
        for row in rows:
            value=row.get('latest_inspection_date')
            if hasattr(value,'isoformat'):
                row['latest_inspection_date']=value.isoformat()
        return dict(columns=[c[0] for c in cursor.description], rows=rows,result_count=len(rows),
                    limit_reached=len(rows)==period['limit'],period=period,query_kind='inspection_frequency',
                    query_sha256=hashlib.sha256(expected['sql'].encode()).hexdigest(),
                    generated_at=datetime.now(timezone.utc).isoformat())
    finally:
        try: connection.rollback()
        finally: connection.close()
