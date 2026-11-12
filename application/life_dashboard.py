"""Remaining-life bands without treating missing forecasts as healthy assets."""

BANDS = {'long': '15년 초과', 'medium': '5년 초과~15년 이하',
         'short': '5년 이하', 'unknown': '산정 불가', 'not_reached': '한도 미도달'}


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
