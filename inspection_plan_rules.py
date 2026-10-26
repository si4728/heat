"""Business-day rules for inspection-plan application and approval dates."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta


def _replace_date(value: date | datetime, year: int, month: int, day: int):
    if isinstance(value, datetime):
        return value.replace(year=year, month=month, day=day)
    return value.replace(year=year, month=month, day=day)


def subtract_calendar_months(value: date | datetime, months: int) -> date | datetime:
    """Subtract calendar months, clamping end-of-month dates when necessary."""
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return _replace_date(value, year, month, day)


def previous_weekday(value: date | datetime) -> date | datetime:
    """Keep weekdays and move Saturday/Sunday back to the preceding Friday."""
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def next_weekday(value: date | datetime) -> date | datetime:
    """Keep weekdays and move Saturday/Sunday forward to the following Monday."""
    while value.weekday() >= 5:
        value += timedelta(days=1)
    return value


def inspection_plan_application_date(inspection_date: date | datetime) -> date | datetime:
    """Select the application weekday three calendar months before inspection."""
    return previous_weekday(subtract_calendar_months(inspection_date, 3))


def inspection_plan_approval_date(application_date: date | datetime) -> date | datetime:
    """Select a weekday no later than seven days after application.

    Five calendar days is the standard lead time. Weekend results move forward to
    Monday, which is still within the requested seven-day window.
    """
    approval_date = next_weekday(application_date + timedelta(days=5))
    if approval_date > application_date + timedelta(days=7):
        raise ValueError("검사계획 승인일은 신청일로부터 7일 이내여야 합니다.")
    return approval_date
