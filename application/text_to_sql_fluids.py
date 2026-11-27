"""Server-owned grouping of current exchanger fluids; no inspection prerequisite."""
from datetime import datetime, timezone
import hashlib
import re

from iris2 import dbapi
from iris2.application import text_to_sql_service as analysis
from iris2.hx_configuration import DB_PATH
from iris2.llm_integration.text_to_sql import QueryRejected


def normalized_fluid(value):
    name = str(value or '').strip().upper()
    return 'STEAM' if name == 'S:STEAM' else name or None


def describe(settings):
    unit='설비별 1행' if settings.get('listing') else '공정별 유체 집계' if settings['by_unit'] else '유체별 집계'
    return f"현재 사양 · {' / '.join(settings['sides'])} · 유체 {settings.get('fluid') or '전체'} · {unit} · 최대 500행"


def matches(question):
    return bool(re.search(r'유체|fluid', question, re.I))


def options(question):
    if re.search(r'검사|감육|두께|수명|압력|온도|재질|과거|이력|\d{4}\s*년|최근|작년|올해', question):
        raise QueryRejected('유체별 조회는 현재 사양의 유체명·설비 수·목록을 지원합니다. 검사·기간·운전조건은 함께 지정할 수 없습니다.')
    sides = []
    for side, pattern in [('SHELL', r'shell|쉘|셸'), ('TUBE', r'tube|튜브|전열관'), ('HEAD', r'head|헤드')]:
        if re.search(pattern, question, re.I):
            sides.append(side)
    if not sides:
        sides = ['SHELL', 'TUBE']
    match = re.search(r'유체(?:명)?\s*(?:이|은|가|=|:)\s*[\'"]?([A-Za-z][A-Za-z0-9 .+/_():-]*?)(?:[\'"]|\s*인|\s+(?:교환기|열교환기|설비)|$)', question, re.I)
    result=dict(sides=sides, by_unit=bool(re.search(r'공정\s*별|라인\s*별|VCM1.*VCM2|구분', question, re.I)),
                fluid=normalized_fluid(match[1]) if match else None)
    if re.search(r'목록|리스트',question) and not re.search(r'유체(?:명)?\s*별|측\s*별|집계|수량|개수|몇\s*대|대수',question):
        result['listing']=True
    return result


def select_equipment(data, question):
    from .text_to_sql_scope import mentioned_units
    equipment = analysis.catalog()
    ids, units = data.get('exchanger_ids'), data.get('unit_codes')
    if 'exchanger_id' in data:
        if ids is not None or units is not None:
            raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
        ids = [data['exchanger_id']]
    if ids is not None and (not isinstance(ids, list) or len(ids)>500 or any(type(i) is not int or i<=0 for i in ids)):
        raise QueryRejected('설비 선택을 확인하세요.')
    if units is not None and (ids is not None or not isinstance(units, list) or any(u not in ('PE','VCM1','VCM2') for u in units)):
        raise QueryRejected('PE·VCM1·VCM2 공정 또는 교환기를 선택하세요.')
    if ids and not set(ids)<={r['heat_exchanger_id'] for r in equipment}:
        raise PermissionError('PE·VCM1·VCM2 범위의 설비를 선택하세요.')
    mentioned = mentioned_units(question)
    named = set()
    canonical = lambda value: re.sub(r'[^A-Z0-9]', '', value.upper())
    for tag in re.findall(r'(?<![A-Za-z0-9])(?:AE|ER|E)\s*-?\s*\d+[A-Za-z]*(?:-\d+)?(?![A-Za-z0-9])', question, re.I):
        found = [r['heat_exchanger_id'] for r in equipment if canonical(tag) in
                 [canonical(t) for t in re.findall(r'(?:AE|ER|E)\s*-?\s*\d+[A-Za-z]*(?:-\d+)?$', r.get('equipment_tag') or '', re.I)]]
        if not found:
            raise QueryRejected(f'{tag}: 설비를 찾을 수 없습니다.')
        named.update(found)
    for row in equipment:
        code = str(row.get('equipment_code') or '')
        if code and re.search(r'(?<![A-Za-z0-9])'+re.escape(code)+r'(?![A-Za-z0-9])', question, re.I):
            named.add(row['heat_exchanger_id'])
    selected = [r for r in equipment if (not ids or r['heat_exchanger_id'] in ids)
                and (not units or r['unit_code'] in units)
                and (not named or r['heat_exchanger_id'] in named)
                and (not mentioned or r['unit_code'] in mentioned)]
    if not selected:
        raise QueryRejected('조회 범위에 교환기가 없습니다.')
    return selected


def proposal(ids, settings):
    if not ids or len(ids)>500 or any(type(i) is not int or i<=0 for i in ids):
        raise QueryRejected('조회 설비 범위가 올바르지 않습니다.')
    if (not isinstance(settings, dict) or not settings.get('sides')
            or any(s not in ('SHELL','TUBE','HEAD') for s in settings['sides'])
            or type(settings.get('by_unit')) is not bool
            or (settings.get('fluid') is not None and (not isinstance(settings['fluid'],str) or len(settings['fluid'])>200))):
        raise QueryRejected('유체별 조회 조건이 올바르지 않습니다.')
    parts, parameters = [], []
    for side in settings['sides']:
        fluid = {'SHELL':"COALESCE(NULLIF(TRIM(s.shell_fluid),''), NULLIF(TRIM(ss.fluid),''))",
                 'TUBE':"COALESCE(NULLIF(TRIM(s.tube_fluid),''), NULLIF(TRIM(ss.fluid),''))",
                 'HEAD':"NULLIF(TRIM(ss.fluid),'')"}[side]
        fluid = f"CASE WHEN UPPER({fluid})='S:STEAM' THEN 'STEAM' ELSE UPPER({fluid}) END"
        parts.append(f'''SELECT hx.heat_exchanger_id, u.unit_code, e.equipment_tag, e.equipment_name,
            '{side}' AS side_code, COALESCE({fluid}, '미등록') AS fluid_name
            FROM heat_exchanger hx JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            LEFT JOIN heat_exchanger_spec_revision s ON s.heat_exchanger_id=hx.heat_exchanger_id AND s.is_current=1
            LEFT JOIN heat_exchanger_side_spec ss ON ss.spec_revision_id=s.spec_revision_id AND ss.side_code='{side}'
            WHERE hx.heat_exchanger_id IN ({','.join('?' for _ in ids)}) AND u.unit_code IN ('PE','VCM1','VCM2')''')
        parameters.extend(ids)
    unit = 'unit_code, ' if settings['by_unit'] else ''
    where = 'WHERE fluid_name=?' if settings.get('fluid') else ''
    if where:
        parameters.append(settings['fluid'])
    sql = f'''SELECT {unit}side_code, fluid_name, COUNT(DISTINCT heat_exchanger_id) AS exchanger_count,
        GROUP_CONCAT(DISTINCT CONCAT(unit_code, ':', equipment_tag) ORDER BY unit_code,equipment_tag SEPARATOR ', ') AS equipment_list
        FROM ({' UNION ALL '.join(parts)}) current_fluids {where}
        GROUP BY {unit}side_code, fluid_name ORDER BY {unit}side_code, exchanger_count DESC, fluid_name LIMIT 501'''
    if settings.get('listing'):
        sql=f'''SELECT heat_exchanger_id, unit_code, equipment_tag, equipment_name,
            GROUP_CONCAT(DISTINCT side_code ORDER BY side_code SEPARATOR ', ') AS side_code,
            GROUP_CONCAT(DISTINCT fluid_name ORDER BY fluid_name SEPARATOR ', ') AS fluid_name
            FROM ({' UNION ALL '.join(parts)}) current_fluids {where}
            GROUP BY heat_exchanger_id, unit_code, equipment_tag, equipment_name
            ORDER BY unit_code, equipment_tag, heat_exchanger_id LIMIT 501'''
    return dict(sql=sql, parameters=parameters)


def execute(ids, settings, signed_proposal, allowed):
    if not set(ids)<=set(allowed):
        raise PermissionError('현재 조회할 수 없는 설비가 포함되어 있습니다.')
    expected = proposal(ids, settings)
    if signed_proposal != expected:
        raise QueryRejected('유체별 조회 SQL이 변경되었습니다. 다시 생성하세요.')
    connection = dbapi.connect(DB_PATH, readonly=True, readonly_profile='text_to_sql')
    try:
        grants = connection.execute('SHOW GRANTS').fetchall()
        if not grants or any(not re.match(r'^GRANT (?:USAGE|SELECT) ON ',str(r[0]),re.I)
                             or re.search(r'\bWITH GRANT OPTION\b',str(r[0]),re.I) for r in grants):
            raise QueryRejected('SELECT 전용 읽기 계정이 필요합니다.')
        connection.execute('SET SESSION max_statement_time=5')
        connection.execute('SET SESSION group_concat_max_len=1048576')
        connection.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        connection.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        cursor = connection.execute(expected['sql'], tuple(expected['parameters']))
        rows = [dict(row) for row in cursor.fetchmany(501)]
        return dict(columns=[c[0] for c in cursor.description if c[0]!='heat_exchanger_id'], rows=rows[:500], result_count=min(len(rows),500),
                    limit_reached=len(rows)>500, query_kind='fluid_grouping', settings=settings,
                    query_sha256=hashlib.sha256(expected['sql'].encode()).hexdigest(),
                    generated_at=datetime.now(timezone.utc).isoformat())
    finally:
        try: connection.rollback()
        finally: connection.close()
