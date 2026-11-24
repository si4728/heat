"""Resolve report requests using verified inspection IDs, never model-generated URLs."""
import re

from flask import url_for

from iris2 import services
from iris2.application import query_period, text_to_sql_service as analysis
from iris2.llm_integration.text_to_sql import QueryRejected


def matches(question):
    return bool(re.search(r'pdf|보고서|report', question, re.I)) and not bool(
        re.search(r'요약|감육|두께|순위|횟수|통계|비교', question))


def response(question, data):
    from .text_to_sql_scope import mentioned_units as question_units
    catalog = analysis.catalog()
    # A named equipment must never silently fall back to the selected equipment.
    tags = re.findall(r'(?<![A-Za-z0-9])(?:AE|ER|E)\s*-?\s*\d+[A-Za-z]*(?:-\d+)?(?![A-Za-z0-9])', question, re.I)
    canonical = lambda value: re.sub(r'[^A-Z0-9]', '', str(value).upper())
    named = set()
    for tag in tags:
        found = [r['heat_exchanger_id'] for r in catalog if canonical(tag) in
                 [canonical(value) for value in re.findall(r'(?:AE|ER|E)\s*-?\s*\d+[A-Za-z]*(?:-\d+)?$', r.get('equipment_tag') or '', re.I)]
                 + [canonical(r.get('equipment_code'))]]
        if not found:
            raise QueryRejected(f'{tag}: PE·VCM1·VCM2 설비를 찾을 수 없습니다.')
        named.update(found)
    for row in catalog:
        code = str(row.get('equipment_code') or '')
        if code and re.search(r'(?<![A-Za-z0-9])'+re.escape(code)+r'(?![A-Za-z0-9])', question, re.I):
            named.add(row['heat_exchanger_id'])
    ids = data.get('exchanger_ids')
    units = data.get('unit_codes')
    if 'exchanger_id' in data:
        if ids is not None or units is not None:
            raise QueryRejected('조회 범위 선택 방식을 하나만 지정하세요.')
        ids = [data['exchanger_id']]
    if ids is not None and (not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids)):
        raise QueryRejected('교환기 선택을 확인하세요.')
    if units is not None and (ids is not None or not isinstance(units, list) or any(u not in ('PE','VCM1','VCM2') for u in units)):
        raise QueryRejected('PE·VCM1·VCM2 공정 또는 교환기를 선택하세요.')
    allowed = {r['heat_exchanger_id'] for r in catalog}
    if ids and not set(ids) <= allowed:
        raise PermissionError('PE·VCM1·VCM2 범위의 설비를 선택하세요.')
    mentioned_units = question_units(question)
    selected = [r for r in catalog if
                (not named or r['heat_exchanger_id'] in named) and
                (not ids or r['heat_exchanger_id'] in ids) and
                (not units or r['unit_code'] in units) and
                (not mentioned_units or r['unit_code'] in mentioned_units)]
    if not (named or ids or units or mentioned_units):
        raise QueryRejected('보고서를 조회할 교환기 또는 공정을 선택하거나 질문에 설비 코드를 입력하세요.')
    if not selected:
        raise QueryRejected('질문의 설비와 선택 범위가 일치하지 않습니다.')
    inspection_id = data.get('inspection_id')
    if inspection_id is not None and (type(inspection_id) is not int or inspection_id <= 0 or len(selected) != 1):
        raise QueryRejected('검사 회차는 단일 설비에서만 지정하세요.')
    period, _ = query_period.parse(re.sub(r'최근(?!\s*\d)', '', question))
    reports, missing, scopes = [], [], []
    for equipment in selected:
        rounds = analysis.inspections(equipment['heat_exchanger_id'])
        if inspection_id is not None:
            rounds = [r for r in rounds if r['iris_inspection_id'] == inspection_id]
            if not rounds:
                raise QueryRejected('선택한 설비의 검사 회차가 아닙니다.')
        if period:
            rounds = [r for r in rounds if r['effective_date'] and period['start'] <= str(r['effective_date'])[:10] <= period['end']]
        elif re.search(r'최근|최신', question) and rounds:
            rounds = [r for r in rounds if r['effective_date'] == rounds[0]['effective_date']]
        for inspection in rounds:
            pdf = services.find_inspection_pdf(inspection['iris_inspection_id'])
            scopes.append(dict(equipment=equipment, inspection=inspection))
            if not pdf:
                missing.append(inspection['iris_inspection_id'])
                continue
            page = pdf.get('page')
            href = url_for('inspection_pdf_view', inspection_id=inspection['iris_inspection_id'])
            if page and page > 0:
                href += f'#page={page}'
            reports.append(dict(equipment_tag=equipment.get('equipment_tag') or equipment['equipment_code'],
                unit_code=equipment['unit_code'], inspection_date=str(inspection['effective_date'] or '')[:10],
                report_number=inspection.get('report_number'), page=page, url=href))
    return dict(query_kind='inspection_reports', reports=reports[:100], scopes=scopes,
                missing_count=len(missing), limit_reached=len(reports)>100)
