"""Planning recommendations from explicitly identified measured/estimated forecasts."""
from datetime import date

BASES = {'earliest': '실측·통계 추정 중 빠른 날짜', 'measured': '실측 튜브 기준', 'estimated': '통계 추정 기준'}


def recommendation(life, first_measured, *, basis='earliest'):
    if basis not in BASES:
        raise ValueError('권고 기준을 선택하세요.')
    options = []
    if basis != 'estimated' and first_measured:
        measured_date = first_measured['measurement_date']
        reached = first_measured['status'] == 'MEASURED_REACHED'
        options.append((first_measured['date'] or measured_date, measured_date,
                        '실측 튜브', reached, first_measured.get('tube_no')))
    estimate = life.get('sample_wall_loss_estimate') or {}
    prediction = estimate.get('first_threshold') or {}
    if basis != 'measured' and estimate.get('status') == 'ESTIMATED' and prediction.get('status') in ('FORECAST','ESTIMATED_REACHED'):
        measured_date = estimate['measurement_date']
        options.append((prediction.get('date') or measured_date, measured_date,
                        '통계 추정', prediction['status'] == 'ESTIMATED_REACHED', None))
    if not options:
        return None
    target, measured, source, reached, tube_no = min(options, key=lambda x: (x[0], x[2]))
    target, measured = date.fromisoformat(target), date.fromisoformat(measured)
    due = measured if reached or target <= measured else measured + (target - measured) // 2
    return dict(due_date=due, first_date=None if reached else target,
                measured_date=measured, source=source, threshold_reached=reached, tube_no=tube_no)


def horizon_end(as_of, horizon):
    if horizon == 'all':
        return date.max
    if str(horizon) not in ('1', '2', '5'):
        raise ValueError('권고 시기를 선택하세요.')
    try:
        return as_of.replace(year=as_of.year + int(horizon))
    except ValueError:
        return as_of.replace(year=as_of.year + int(horizon), day=28)
