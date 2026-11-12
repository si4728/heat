"""Remaining-life bands without treating missing forecasts as healthy assets."""
from datetime import date

BANDS = {'long': '15년 초과', 'medium': '5년 초과~15년 이하',
         'short': '5년 이하', 'unknown': '산정 불가', 'not_reached': '한도 미도달'}


def first_tube_threshold(projections):
    """Earliest measured-tube forecast, excluding recorded plugging operations."""
    candidates = []
    for row in projections:
        if row.get('basis') != 'CALCULATED' or not row.get('measurement_date'):
            continue
        try:
            forecast_date = date.fromisoformat(row['plugging_date'])
            measured_date = date.fromisoformat(row['measurement_date'])
        except (KeyError, TypeError, ValueError):
            continue
        reached = bool(row.get('plugging_threshold_reached'))
        candidates.append({
            'status': 'MEASURED_REACHED' if reached else 'FORECAST',
            'date': None if reached else forecast_date.isoformat(),
            'measurement_date': measured_date.isoformat(),
            'tube_id': row['tube_id'], 'tube_no': row['tube_no'],
            '_sort_date': measured_date if reached else forecast_date,
        })
    if not candidates:
        return None
    first = min(candidates, key=lambda row: (
        row['status'] != 'MEASURED_REACHED', row['_sort_date'], row['tube_id']))
    first.pop('_sort_date')
    return first


def life_band(life):
    years = life.get('remaining_life_years')
    if life.get('status') == 'LIMIT_NOT_REACHED' and life.get('total_tube_count'):
        return 'not_reached'
    if life.get('status') != 'CALCULATED' or years is None or not life.get('total_tube_count'):
        return 'unknown'
    return 'long' if years > 15 else 'medium' if years > 5 else 'short'


def group_life_rows(rows, unit='', band=''):
    unit = unit if unit in {'VCM1', 'VCM2'} else ''
    band = band if band in BANDS else ''
    groups = []
    for code in ('VCM1', 'VCM2'):
        items = [r for r in rows if r['unit_code'] == code]
        groups.append({'unit': code, 'counts': {key: sum(r['band'] == key for r in items) for key in BANDS},
                       'total': len(items)})
    totals = {key: sum(g['counts'][key] for g in groups) for key in BANDS}
    return {'groups': groups, 'totals': totals, 'total': len(rows), 'bands': BANDS,
            'selected_unit': unit, 'selected_band': band,
            'rows': [r for r in rows if (not unit or r['unit_code'] == unit) and (not band or r['band'] == band)]}
