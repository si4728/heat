"""One equipment overview for analysis, detail and dashboard; raw forecasts retained."""
from datetime import date
from .life_dashboard import first_tube_threshold, forecast_display, life_band
from ..domain.inspection_recommendation import recommendation


def prediction_label(prediction, as_of):
    status = (prediction or {}).get('status')
    if status == 'FORECAST':
        display = forecast_display(prediction, as_of)
        return display if display == '30년 이상' else f'{display[:4]}년' if display else '산정 불가'
    return {'MEASURED_REACHED':'검사 시 기준 도달', 'ESTIMATED_REACHED':'검사일 기준 추정상 도달',
        'INVALID_INSTALLATION_DATE':'설치일 확인 필요', 'NO_POSITIVE_LOSS':'양의 감육률 없음',
        'DATE_OUT_OF_RANGE':'예상일 범위 초과'}.get(status, '산정 불가')


def build_equipment_summary(life, as_of):
    estimate = life.get('sample_wall_loss_estimate') or {}
    for key in ('first_threshold','twenty_percent_threshold','measured_max_threshold'):
        if estimate.get(key):
            estimate[key]['display'] = prediction_label(estimate[key],as_of)
    for row in life.get('analysis_tube_rows', []):
        when = next((p.get('plugging_date') for p in life.get('tube_projections',[]) if p['tube_id'] == row['tube_id']), None)
        row['forecast_display'] = prediction_label(dict(status='FORECAST',date=when),as_of) if when else '산정 불가'
    predicted = estimate.get('twenty_percent_threshold') or {}
    use_estimate = estimate.get('status') == 'ESTIMATED' and predicted.get('status') in ('FORECAST','ESTIMATED_REACHED')
    status, years = life.get('status'), life.get('remaining_life_years')
    actual_exceeded = (life.get('allowable_plugging_count') is not None
        and life.get('actual_plugged_count', 0) > life['allowable_plugging_count'])
    if actual_exceeded:
        use_estimate = False
        status, years = 'CALCULATED', 0
    target = None
    if use_estimate:
        status = 'CALCULATED'
        target = predicted.get('date')
        years = max(0, (date.fromisoformat(target) - as_of).days / 365.2425) if target else 0
    if status == 'CALCULATED' and years is not None:
        capped = forecast_display(predicted,as_of) == '30년 이상' if use_estimate and target else years > 30
        value = '30년 이상' if capped else f'{max(0, years):.1f}년'
        band = life_band(dict(status=status,remaining_life_years=years,total_tube_count=life.get('total_tube_count')))
    else:
        band = 'uninspected' if life.get('registered_inspection_count') == 0 else 'unknown'
        value = 'IRIS 미실시' if band == 'uninspected' else '산정 불가'
    reasons = []
    if band == 'uninspected':
        reasons.append('시스템에 IRIS 검사 이력 미등록')
    elif band == 'unknown':
        if estimate.get('measured_max_wall_loss_percent') == 0:
            reasons.append('감육 미검출 · 양의 감육속도 미확보')
        if estimate.get('status') in ('SAMPLE_INSUFFICIENT', 'NO_VALID_SAMPLE'):
            reasons.append('유효 표본 10본 미만' if estimate.get('sample_count',0) else '유효 검사 표본 없음 · 데이터 확인 필요')
        if estimate.get('status') == 'DEGENERATE_SAMPLE' and not reasons:
            reasons.append('표본 감육률의 분산 없음')
        if any(r.get('minimum_wall_thickness_mm') is None for r in life.get('analysis_tube_rows', [])):
            reasons.append('최소두께 원본 확인 필요')
        if estimate.get('status') in ('AMBIGUOUS_INSPECTION','MIXED_INSTALLATION_DATES','INVALID_TOTAL_COUNT'):
            reasons.append('검사 집단·설치일·전체 수량 데이터 확인 필요')
        if not life.get('total_tube_count'):
            reasons.append('승인 설계 수량 미등록')
        if status == 'LIMIT_NOT_REACHED':
            reasons.append('가용 데이터에서 한도 도달 시점 미산정')
        if not reasons:
            reasons.append('계산 입력 데이터 확인 필요')
    first_measured = first_tube_threshold(life.get('tube_projections',[]))
    first = estimate.get('first_threshold') if (estimate.get('status') == 'ESTIMATED'
        and (estimate.get('first_threshold') or {}).get('status') in ('FORECAST','ESTIMATED_REACHED')) else first_measured
    first = first or first_measured
    source = '통계 추정' if use_estimate else '실측 튜브 수량 한도'
    if life.get('actual_plugged_count',0):
        source = '통계 추정 · 실제 완료 반영' if use_estimate else '실제 완료 + 실측 튜브 예측'
    rec = recommendation(life, first_measured, basis='measured')
    first_date = (first or {}).get('date')
    first_urgent = (first or {}).get('status') in ('MEASURED_REACHED','ESTIMATED_REACHED') or (
        first_date is not None and (date.fromisoformat(first_date)-as_of).days <= 5*365.2425)
    return dict(status='NO_INSPECTION' if band=='uninspected' else status, basis='SAMPLE_20_PERCENT' if use_estimate else 'MEASURED_COUNT',
        source=source, band=band, remaining_life_years=years, remaining_display=value,
        target_date=target, target_display=prediction_label(predicted,as_of) if use_estimate else (
            '30년 이상' if years is not None and years > 30 else
            f"{life['life_reached_year']}년" if life.get('life_reached_year') else '산정 불가'),
        uncalculable_reason=' · '.join(reasons),
        threshold_reached_count=life.get('threshold_reached_count',0),
        actual_plugged_count=life.get('actual_plugged_count',0),
        estimated_reached=predicted.get('status') == 'ESTIMATED_REACHED',
        urgent=years is not None and years <= 5, first=first,
        first_display=prediction_label(first,as_of), first_urgent=first_urgent,
        first_source='통계 추정' if first is estimate.get('first_threshold') else '실측 튜브',
        measured_first=first_measured,
        measured_max=estimate.get('measured_max_wall_loss_percent'),
        estimated_max=estimate.get('estimated_max_wall_loss_percent'),
        sample_count=estimate.get('sample_count',0), raw_sample_count=estimate.get('raw_sample_count',0),
        total_tube_count=life.get('total_tube_count'), sample_status=estimate.get('status','NO_VALID_SAMPLE'),
        measurement_date=estimate.get('measurement_date') or life.get('equipment_summary',{}).get('latest_inspection_date'), recommendation_date=rec['due_date'].isoformat() if rec else None,
        top_tubes=life.get('defect_rows',[])[:5])
