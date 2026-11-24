"""Remaining-life bands without treating missing forecasts as healthy assets."""
from datetime import date

BANDS = {'long': '15년 초과', 'medium': '5년 초과~15년 이하',
         'short': '5년 이하', 'unknown': '산정 불가', 'uninspected': 'IRIS 미실시'}


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
    if life.get('registered_inspection_count') == 0:
        return 'uninspected'
    if life.get('status') != 'CALCULATED' or years is None or not life.get('total_tube_count'):
        return 'unknown'
    return 'long' if years > 15 else 'medium' if years > 5 else 'short'


def group_life_rows(rows, unit='', band=''):
    if band == 'not_reached':
        band = 'unknown'  # Existing saved links remain usable.
    unit = unit if unit in {r['unit_code'] for r in rows} else ''
    band = band if band in BANDS else ''
    rows = [r for r in rows if r['unit_code'] not in ('VCM3', 'VCM4')]
    teams = sorted({r.get('team_code') or ('VCM' if r['unit_code'].startswith('VCM') else 'PE') for r in rows})
    groups = []
    for team in teams:
        members = [r for r in rows if (r.get('team_code') or ('VCM' if r['unit_code'].startswith('VCM') else 'PE')) == team]
        groups.append(dict(team=team, label=f'{team} 생산팀',
            counts={key: sum(r['band'] == key for r in members) for key in BANDS}, total=len(members)))
    totals = {key: sum(g['counts'][key] for g in groups) for key in BANDS}
    return {'groups': groups, 'totals': totals, 'total': len(rows), 'bands': BANDS,
            'selected_unit': unit, 'selected_band': band,
            'rows': [r for r in rows if (not unit or r['unit_code'] == unit) and (not band or r['band'] == band)]}


def forecast_display(first, as_of):
    """Cap presentation only, strictly beyond the calendar 30-year anniversary."""
    if not first or first.get('status') != 'FORECAST':
        return None
    try:
        when = date.fromisoformat(first['date'])
    except (ValueError, TypeError, KeyError):
        return None
    try:
        boundary = as_of.replace(year=as_of.year + 30)
    except ValueError:
        boundary = date(as_of.year + 30, 2, 28)
    return '30년 이상' if when > boundary else when.isoformat()


def annual_team_rows(rows):
    """Aggregate the two processes once per year, retaining process report links."""
    years = {}
    for entry in rows:
        unit, year, inspections, exchangers, results, pdf = entry[:6]
        if unit in ('VCM3', 'VCM4'):
            continue
        code = entry[6] if len(entry) > 6 else ('VCM' if unit.startswith('VCM') else 'PE')
        team = f'{code or "미지정"} 생산팀'
        group = years.setdefault((year, team), dict(year=year, team=team,
            inspection_count=0, exchanger_count=0, result_count=0, processes=[]))
        group['inspection_count'] += inspections
        group['exchanger_count'] += exchangers
        group['result_count'] += results
        group['processes'].append(dict(unit=unit, pdf_available=pdf,
            inspection_count=inspections, exchanger_count=exchangers, result_count=results))
    return sorted(years.values(), key=lambda row: row['year'], reverse=True)
