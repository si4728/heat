"""Current-installation eligibility; earlier inspections remain valid history."""
from datetime import date, datetime


def current_installation_date(*values):
    dates = [value.date() if isinstance(value, datetime) else value for value in values if value is not None]
    return max(dates) if dates else None


def is_current_installation_inspection(measured, *installation_dates):
    if measured is None:
        return False
    measured = measured.date() if isinstance(measured, datetime) else measured
    installed = current_installation_date(*installation_dates)
    return installed is None or measured >= installed
