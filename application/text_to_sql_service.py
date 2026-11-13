"""Web-facing scope catalog and bounded independent local inference process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from iris2 import dbapi
from iris2.hx_configuration import APP_DIR, DB_PATH
from iris2.llm_integration.text_to_sql import QueryRejected


def catalog() -> list[dict]:
    connection = dbapi.connect(DB_PATH, readonly=True, readonly_profile='text_to_sql')
    try:
        connection.execute('SET SESSION max_statement_time=5')
        return [dict(row) for row in connection.execute("""SELECT hx.heat_exchanger_id,
            e.equipment_code, e.equipment_tag, e.equipment_name, u.unit_code
            FROM heat_exchanger hx JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE u.unit_code IN ('VCM1','VCM2')
            ORDER BY u.unit_code, e.equipment_tag, e.equipment_code""").fetchall()]
    finally:
        connection.rollback()
        connection.close()


def inspections(exchanger_id: int) -> list[dict]:
    connection = dbapi.connect(DB_PATH, readonly=True, readonly_profile='text_to_sql')
    try:
        connection.execute('SET SESSION max_statement_time=5')
        return [dict(row) for row in connection.execute("""SELECT i.iris_inspection_id,
            i.report_number, i.inspection_date, i.report_date, i.source_document_id,
            COALESCE(i.inspection_date,i.report_date) AS effective_date
            FROM iris_inspection i JOIN heat_exchanger hx ON hx.heat_exchanger_id=i.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=hx.equipment_id
            JOIN process_unit u ON u.unit_id=e.unit_id
            WHERE hx.heat_exchanger_id=? AND u.unit_code IN ('VCM1','VCM2')
            AND i.superseded_by_inspection_id IS NULL
            ORDER BY effective_date DESC, i.iris_inspection_id DESC""", (exchanger_id,)).fetchall()]
    finally:
        connection.rollback()
        connection.close()


def select_scope(exchanger_id: int, inspection_id: int | None) -> tuple[dict, dict, frozenset]:
    equipment = catalog()
    allowed = frozenset(row['heat_exchanger_id'] for row in equipment)
    if exchanger_id not in allowed:
        raise PermissionError('VCM1·VCM2 범위의 설비를 선택하세요.')
    rounds = inspections(exchanger_id)
    selected = next((r for r in rounds if r['iris_inspection_id'] == inspection_id), None) if inspection_id else (rounds[0] if rounds else None)
    if not selected:
        raise QueryRejected('선택한 설비의 유효한 검사 회차가 없습니다.')
    if not selected['effective_date']:
        raise QueryRejected('검사일·보고일이 없는 회차는 분석할 수 없습니다.')
    if not inspection_id and len(rounds) > 1 and rounds[0]['effective_date'] == rounds[1]['effective_date']:
        raise QueryRejected('최근 날짜에 여러 검사 회차가 있습니다. 보고서 번호로 회차를 선택하세요.')
    return next(r for r in equipment if r['heat_exchanger_id'] == exchanger_id), selected, allowed


def select_scopes(*, exchanger_ids=None, unit_codes=None, inspection_id=None):
    """Resolve the requested set on the server; never trust client-supplied pairs."""
    equipment = catalog()
    allowed = frozenset(row['heat_exchanger_id'] for row in equipment)
    if unit_codes is not None:
        if exchanger_ids is not None or inspection_id is not None:
            raise QueryRejected('공정 선택과 설비·검사 회차 선택을 함께 사용할 수 없습니다.')
        if not isinstance(unit_codes, list) or not unit_codes or any(
                unit not in ('VCM1', 'VCM2') for unit in unit_codes):
            raise QueryRejected('VCM1 또는 VCM2 공정을 선택하세요.')
        ids = [row['heat_exchanger_id'] for row in equipment if row['unit_code'] in unit_codes]
    else:
        if not isinstance(exchanger_ids, list) or not exchanger_ids or len(exchanger_ids) > 500 or any(
                type(value) is not int or value <= 0 for value in exchanger_ids):
            raise QueryRejected('교환기를 한 대 이상 선택하세요.')
        ids = list(dict.fromkeys(exchanger_ids))
        if not set(ids) <= allowed:
            raise PermissionError('VCM1·VCM2 범위의 설비를 선택하세요.')
        if inspection_id is not None and (type(inspection_id) is not int or len(ids) != 1):
            raise QueryRejected('검사 회차는 교환기 한 대를 선택한 경우에만 지정할 수 있습니다.')
    scopes, excluded = [], []
    for identifier in ids:
        row = next(row for row in equipment if row['heat_exchanger_id'] == identifier)
        rounds = inspections(identifier)
        if not rounds:
            if unit_codes is None:
                raise QueryRejected(f"{row.get('equipment_tag') or identifier}: 유효한 검사 회차가 없습니다.")
            excluded.append(dict(equipment=row, reason='유효한 검사 회차 없음'))
            continue
        selected = next((r for r in rounds if r['iris_inspection_id'] == inspection_id), None) if inspection_id else rounds[0]
        if not selected or not selected['effective_date']:
            if unit_codes is not None:
                excluded.append(dict(equipment=row, reason='검사일·보고일 없음'))
                continue
            raise QueryRejected(f"{row.get('equipment_tag') or identifier}: 날짜가 있는 유효한 검사 회차를 선택하세요.")
        if inspection_id is None and len(rounds) > 1 and rounds[0]['effective_date'] == rounds[1]['effective_date']:
            if unit_codes is not None:
                excluded.append(dict(equipment=row, reason='최근 날짜에 여러 검사 회차 존재: 단일 설비에서 회차 지정 필요'))
                continue
            raise QueryRejected(f"{row.get('equipment_tag') or identifier}: 최근 날짜에 여러 검사 회차가 있습니다. 단일 교환기로 검사 회차를 지정하세요.")
        scopes.append(dict(equipment=row, inspection=selected))
    if not scopes:
        raise QueryRejected('선택 범위에 유효한 검사 회차가 없습니다.')
    return scopes, excluded, allowed


def select_period_scopes(period, *, exchanger_ids=None, unit_codes=None, inspection_id=None):
    """Pin every eligible inspection in the date range, not just the latest."""
    equipment = catalog()
    allowed = frozenset(row['heat_exchanger_id'] for row in equipment)
    if unit_codes is not None:
        if (exchanger_ids is not None or inspection_id is not None
                or not isinstance(unit_codes, list) or not unit_codes
                or any(unit not in ('VCM1', 'VCM2') for unit in unit_codes)):
            raise QueryRejected('VCM1·VCM2 공정 또는 설비를 한 가지 방식으로 선택하세요.')
        selected = [row for row in equipment if row['unit_code'] in unit_codes]
    else:
        if exchanger_ids is None:
            selected = equipment
        else:
            if (not isinstance(exchanger_ids, list) or not exchanger_ids or len(exchanger_ids) > 500
                    or any(type(i) is not int or i <= 0 for i in exchanger_ids)):
                raise QueryRejected('조회 설비 범위가 올바르지 않습니다.')
            if not set(exchanger_ids) <= allowed:
                raise PermissionError('VCM1·VCM2 범위의 설비를 선택하세요.')
            selected = [row for row in equipment if row['heat_exchanger_id'] in exchanger_ids]
    if inspection_id is not None and (type(inspection_id) is not int or inspection_id <= 0 or len(selected) != 1):
        raise QueryRejected('검사 회차는 단일 설비에서만 지정하세요.')
    scopes, excluded = [], []
    for row in selected:
        rounds = inspections(row['heat_exchanger_id'])
        matching = [r for r in rounds if r['effective_date']
                    and period['start'] <= str(r['effective_date'])[:10] <= period['end']
                    and (inspection_id is None or r['iris_inspection_id'] == inspection_id)]
        if not matching:
            excluded.append(dict(equipment=row, reason='기간 내 유효한 검사 회차 없음'))
        scopes.extend(dict(equipment=row, inspection=r) for r in matching)
    if not scopes:
        raise QueryRejected('선택한 기간 내 유효한 검사 회차가 없습니다.')
    if len(scopes) > 500:
        raise QueryRejected('기간 내 검사 회차가 500개를 초과합니다. 기간이나 설비 범위를 줄이세요.')
    return scopes, excluded, allowed


def generate_in_worker(question: str) -> dict:
    # Native inference is isolated: timeout kills the child and frees its model.
    environment = dict(os.environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'LLAMA_CPP_LIB_PATH', 'LLAMA_N_GPU_LAYERS', 'LLAMA_N_CTX'):
        environment.pop(key, None)
    environment.update(PYTHONIOENCODING='utf-8', LLAMA_N_THREADS='8', LLAMA_N_GPU_LAYERS='0')
    try:
        process = subprocess.run(
            [sys.executable, str(Path(APP_DIR)/'tools/generate_text_to_sql.py')],
            input=json.dumps({'question': question}, ensure_ascii=False),
            capture_output=True, text=True, encoding='utf-8', env=environment,
            cwd=APP_DIR, timeout=120,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise QueryRejected('SQL 생성 시간이 120초를 초과했습니다. 질문을 짧게 바꿔 다시 시도하세요.') from exc
    try:
        payload = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise QueryRejected('로컬 모델을 실행할 수 없습니다. 모델 설정을 확인하세요.') from exc
    if process.returncode or payload.get('error'):
        raise QueryRejected(payload.get('error') or 'SQL 생성에 실패했습니다.')
    return payload['proposal']
