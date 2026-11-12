"""Short-term thickness loss from two actual, current-installation measurements."""
from datetime import date, datetime
import math


def short_term_corrosion_rate(current, history, *, installed_at=None):
    def measured_date(value):
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except (ValueError, TypeError):
            return None

    def thickness(value):
        if isinstance(value,bool):
            return None
        try:
            result=float(value)
            return result if math.isfinite(result) and result >= 0 else None
        except (ValueError,TypeError,OverflowError):
            return None

    empty=dict(short_term_rate_mm_per_year=None,short_term_status='INSUFFICIENT_DATA',
               short_term_previous_date=None,short_term_current_date=None,
               short_term_previous_thickness_mm=None,short_term_current_thickness_mm=None)
    current_date=measured_date(current.get('date'))
    current_thickness=thickness(current.get('thickness_mm'))
    installed=measured_date(installed_at)
    if current_date is None or current_thickness is None or (installed and current_date < installed):
        return dict(empty,short_term_status='NO_CURRENT_MEASUREMENT')
    candidates=[]
    for row in history:
        when=measured_date(row.get('date'))
        value=thickness(row.get('thickness_mm'))
        if when is not None and value is not None and when < current_date and (installed is None or when >= installed):
            candidates.append((when,value))
    if not candidates:
        return empty
    previous_date=max(when for when,_ in candidates)
    same_day=[value for when,value in candidates if when == previous_date]
    previous_thickness=min(same_day)
    years=(current_date-previous_date).days/365.2425
    rate=(previous_thickness-current_thickness)/years
    if not math.isfinite(rate):
        return dict(empty,short_term_status='INVALID_RATE')
    return dict(short_term_rate_mm_per_year=rate,
        short_term_status='POSITIVE' if rate > 0 else 'NON_POSITIVE',
        short_term_previous_date=previous_date.isoformat(),short_term_current_date=current_date.isoformat(),
        short_term_previous_thickness_mm=previous_thickness,short_term_current_thickness_mm=current_thickness,
        short_term_elapsed_years=years,short_term_previous_duplicate_count=len(same_day))
