"""Explicit measurement quality and comparability rules for VCM analysis."""
from datetime import date, datetime

VALID_QUALITY = {None, 'VALID', 'USER_APPROVED_211MM_BASIS'}


def exclusion_reason(inspection, result=None, *, as_of=None):
    if getattr(inspection, 'superseded_by_inspection_id', None) is not None:
        return 'SUPERSEDED'
    measured = getattr(inspection, 'inspection_date', None) or getattr(inspection, 'report_date', None)
    if measured is None:
        return 'NO_MEASUREMENT_DATE'
    when = measured.date() if isinstance(measured, datetime) else measured
    if as_of and when > as_of:
        return 'FUTURE_INSPECTION'
    # Customer review 2026-11-17: E-111's 2021 TOPSOUTH is not comparable
    # to full-length measurements. Other position codes are not inferred partial.
    if (getattr(inspection, 'heat_exchanger_id', None) == 100
            and str(getattr(inspection,'original_equipment_id','')).split('(')[0].strip().replace('_','-').upper() == 'E-111'
            and str(getattr(inspection, 'source_scope_code', '')).upper() == 'TOPSOUTH'
            and when.year == 2021):
        return 'PARTIAL_INSPECTION'
    if result is not None:
        if getattr(result, 'result_status', None) not in (None, 'VALID'):
            return 'INVALID_RESULT'
        if getattr(result, 'quality_status', None) not in VALID_QUALITY:
            return 'INVALID_QUALITY'
    return None


REASON_LABELS = {'PARTIAL_INSPECTION':'일부 구간 검사 · 감육속도 계산 제외',
    'SUPERSEDED':'대체된 검사', 'FUTURE_INSPECTION':'기준일 이후 검사',
    'INVALID_RESULT':'유효하지 않은 검사결과', 'INVALID_QUALITY':'품질 상태 제외',
    'NO_MEASUREMENT_DATE':'검사일·보고일 없음'}
