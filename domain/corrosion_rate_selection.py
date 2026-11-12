"""Customer-approved selection from actual measurements of one installation."""
from datetime import date, datetime
import math
from statistics import fmean

from .short_term_corrosion import short_term_corrosion_rate


def select_corrosion_rate(current, history, *, long_term_rate=None, installed_at=None):
    def when(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def number(value):
        if value is None or isinstance(value, bool):
            return None
        try:
            value = float(value)
            return value if math.isfinite(value) else None
        except (ValueError, TypeError, OverflowError):
            return None

    history = list(history)
    short = short_term_corrosion_rate(current, history, installed_at=installed_at)
    origin, installed = when(current.get('date')), when(installed_at)
    current_thickness = number(current.get('thickness_mm'))
    measurements = {}
    if (origin is not None and current_thickness is not None and current_thickness >= 0
            and (installed is None or origin >= installed)):
        for row in history:
            measured, thickness = when(row.get('date')), number(row.get('thickness_mm'))
            if (measured is not None and measured < origin and thickness is not None
                    and thickness >= 0 and (installed is None or measured >= installed)):
                measurements[measured] = min(measurements.get(measured, thickness), thickness)
        measurements[origin] = current_thickness
    count = len(measurements)
    trend = None
    if count >= 3:
        points = sorted(measurements.items())
        xs = [(measured - origin).days / 365.2425 for measured, _ in points]
        ys = [thickness for _, thickness in points]
        try:
            mean_x, mean_y = fmean(xs), fmean(ys)
            trend = -math.fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / math.fsum(
                (x - mean_x) ** 2 for x in xs)
            if not math.isfinite(trend):
                trend = None
        except (ValueError, OverflowError):
            trend = None
    long = number(long_term_rate)
    positive_long = long if long is not None and long > 0 else None
    short_rate = short['short_term_rate_mm_per_year']
    selected, basis, label = positive_long, 'LONG_TERM', '장기'
    if count >= 3:
        if trend is not None and trend > 0:
            selected, basis, label = trend, 'REGRESSION', f'추세({count}회)'
        elif trend is not None:
            basis, label = 'REGRESSION_NON_POSITIVE_LONG_TERM', '추세 0 이하 → 장기'
        else:
            basis, label = 'REGRESSION_INVALID_LONG_TERM', '추세 산정 불가 → 장기'
    elif short_rate is not None:
        if short_rate <= 0:
            basis, label = 'SHORT_TERM_NON_POSITIVE_LONG_TERM', '단기 0 이하 → 장기'
        elif positive_long is None or short_rate > positive_long:
            selected, basis, label = short_rate, 'SHORT_TERM', '단기'
    if selected is None:
        basis, label = 'NO_POSITIVE_RATE', '산정 불가'
    return dict(short, measurement_count=count, regression_rate_mm_per_year=trend,
                long_term_rate_mm_per_year=long, selected_rate_mm_per_year=selected,
                selection_basis=basis, selection_label=label)
