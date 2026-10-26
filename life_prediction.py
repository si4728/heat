from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from .hx_configuration import (
    API510_CODE_EDITION,
    API510_EXTERNAL_MAX_INTERVAL_YEARS,
    API510_INTERNAL_MAX_INTERVAL_YEARS,
    API510_INTERVAL_FRACTION,
    REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS,
    REMAINING_LIFE_AS_OF_DATE_MODE,
    REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT,
    REMAINING_LIFE_FIXED_AS_OF_DATE,
    REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT,
)

PLUGGING_WALL_LOSS_FRACTION = REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT / 100.0
DEFAULT_PLUGGING_LIMIT_PERCENT = REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT


def summarize_corrosion_rates(assessments: Iterable[Any]) -> dict:
    """Return explicit short-term, long-term, and governing corrosion rates."""
    usable = []
    for item in assessments:
        rate = getattr(item, "corrosion_rate_mm_per_year", None)
        elapsed = getattr(item, "elapsed_years", None)
        change = getattr(item, "thickness_change_mm", None)
        assessed = getattr(item, "assessed_at", None)
        if rate is None or elapsed is None or float(elapsed) <= 0:
            continue
        values = (float(rate), float(elapsed))
        if not all(math.isfinite(value) for value in values):
            continue
        usable.append({
            "rate": float(rate),
            "elapsed": float(elapsed),
            "change": float(change) if change is not None else float(rate) * float(elapsed),
            "assessed_at": assessed or datetime.min,
        })
    usable.sort(key=lambda row: row["assessed_at"])
    positive = [row for row in usable if row["rate"] > 0]
    short_term = positive[-1]["rate"] if positive else None
    total_years = sum(row["elapsed"] for row in usable)
    long_term = (
        sum(row["change"] for row in usable) / total_years
        if total_years > 0 else None
    )
    if long_term is not None and long_term <= 0:
        long_term = None
    candidates = [value for value in (short_term, long_term) if value is not None and value > 0]
    selected = max(candidates) if candidates else None
    if selected is None:
        basis = "NO_POSITIVE_RATE"
    elif short_term is not None and long_term is not None:
        basis = "SHORT_TERM_GOVERNS" if short_term >= long_term else "LONG_TERM_GOVERNS"
    elif short_term is not None:
        basis = "SHORT_TERM_ONLY"
    else:
        basis = "LONG_TERM_ONLY"
    return {
        "short_term_rate_mm_per_year": short_term,
        "long_term_rate_mm_per_year": long_term,
        "selected_rate_mm_per_year": selected,
        "selection_basis": basis,
        "assessment_count": len(usable),
    }


def remaining_life_as_of_date() -> date:
    """Return the configured reporting date without hard-coding a calendar year."""
    if REMAINING_LIFE_AS_OF_DATE_MODE == "system":
        return date.today()
    try:
        return date.fromisoformat(REMAINING_LIFE_FIXED_AS_OF_DATE)
    except ValueError as exc:
        raise RuntimeError(
            "[remaining_life] fixed_as_of_date must use YYYY-MM-DD format"
        ) from exc


# Compatibility for callers outside the application. New code should call
# remaining_life_as_of_date() so a long-running process does not retain an old date.
REMAINING_LIFE_BASE_YEAR = remaining_life_as_of_date().year


def _date_value(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError as exc:
        # Imported/localized date inputs can retain misplaced separators (for
        # example, ``202601-01-``). Normalize only an unambiguous YYYYMMDD value.
        digits = re.sub(r"\D", "", text)
        if len(digits) == 8:
            try:
                return datetime.strptime(digits, "%Y%m%d").date()
            except ValueError:
                pass
        raise ValueError("날짜는 YYYY-MM-DD 형식의 유효한 날짜여야 합니다.") from exc


def _decimal_year(value: date) -> float:
    start = date(value.year, 1, 1)
    next_start = date(value.year + 1, 1, 1)
    return value.year + (value - start).days / (next_start - start).days


def calculate_tube_plugging_year(*, current_year: int | None = None,
                                  measurement_date: date | datetime | str | None = None,
                                  nominal_thickness_mm: float,
                                  current_wall_loss_mm: float,
                                  corrosion_rate_mm_per_year: float | None,
                                  plugging_wall_loss_percent: float | None = None) -> dict | None:
    """Calculate the Plugging date from the tube's actual measurement date."""
    try:
        nominal_thickness_mm = float(nominal_thickness_mm)
        current_wall_loss_mm = float(current_wall_loss_mm)
        rate = None if corrosion_rate_mm_per_year is None else float(corrosion_rate_mm_per_year)
    except (TypeError, ValueError) as exc:
        raise ValueError("Tube 잔여수명 입력값은 숫자여야 합니다.") from exc
    if not all(math.isfinite(value) for value in (nominal_thickness_mm, current_wall_loss_mm)):
        raise ValueError("Tube 잔여수명 입력값은 유한한 숫자여야 합니다.")
    if rate is not None and not math.isfinite(rate):
        raise ValueError("부식속도는 유한한 숫자여야 합니다.")
    if nominal_thickness_mm <= 0 or current_wall_loss_mm < 0:
        return None
    if measurement_date is None:
        if current_year is None:
            raise ValueError("measurement_date or current_year is required")
        origin = date(int(current_year), 1, 1)
    else:
        origin = _date_value(measurement_date)
    plugging_fraction = (
        PLUGGING_WALL_LOSS_FRACTION
        if plugging_wall_loss_percent is None
        else float(plugging_wall_loss_percent) / 100.0
    )
    if not math.isfinite(plugging_fraction):
        raise ValueError("Plugging 판정 감육률은 유한한 숫자여야 합니다.")
    if not 0 < plugging_fraction <= 1:
        raise ValueError("Plugging 판정 감육률은 0%보다 크고 100% 이하여야 합니다.")
    plugging_loss_mm = nominal_thickness_mm * plugging_fraction
    remaining_loss_mm = plugging_loss_mm - current_wall_loss_mm
    if remaining_loss_mm <= 0:
        years_to_limit = 0.0
        exact_year = _decimal_year(origin)
        plugging_date = origin
        plugging_year = origin.year
    elif rate is None or rate <= 0:
        return None
    else:
        years_to_limit = remaining_loss_mm / rate
        exact_year = _decimal_year(origin) + years_to_limit
        plugging_date = origin + timedelta(days=years_to_limit * 365.2425)
        plugging_year = plugging_date.year
    return {
        "plugging_loss_mm": plugging_loss_mm,
        "remaining_loss_mm": max(remaining_loss_mm, 0.0),
        "projection_origin_date": origin.isoformat(),
        "years_from_measurement": years_to_limit,
        "plugging_date": plugging_date.isoformat(),
        "exact_year": exact_year,
        "plugging_year": plugging_year,
    }


def calculate_latest_installation_projection(*, installation_date, measurement_date,
                                             nominal_thickness_mm, wall_loss_percent,
                                             plugging_wall_loss_percent,
                                             rate_multiplier=1.0,
                                             installation_precision="DAY") -> dict:
    """Linear lifetime-average estimate, anchored to the latest measurement.

    Installation is assumed to have zero wall loss. This is not an approval
    to operate until the predicted limit date. YEAR dates are estimates.
    """
    try:
        measured = _date_value(measurement_date)
        installed = _date_value(installation_date)
        nominal, loss, limit, multiplier = map(float, (
            nominal_thickness_mm, wall_loss_percent,
            plugging_wall_loss_percent, rate_multiplier,
        ))
    except (ValueError, TypeError, OverflowError):
        return {"status": "INVALID_OR_MISSING_INPUT"}
    if not all(math.isfinite(v) for v in (nominal, loss, limit, multiplier)):
        return {"status": "INVALID_OR_MISSING_INPUT"}
    if nominal <= 0 or not 0 <= loss <= 100 or not 0 < limit <= 100 or multiplier <= 0:
        return {"status": "INVALID_OR_MISSING_INPUT"}
    if installation_precision == "YEAR":
        installed = date(installed.year, 7, 1)
    if installed >= measured:
        return {"status": "INSTALLATION_NOT_BEFORE_INSPECTION"}
    elapsed = (measured - installed).days / 365.2425
    percent_rate = loss / elapsed
    rate = nominal * percent_rate / 100.0 * multiplier
    common = {
        "installation_date_used": installed.isoformat(),
        "installation_precision": installation_precision,
        "measurement_date": measured.isoformat(),
        "elapsed_service_years": elapsed,
        "wall_loss_rate_percentage_points_per_year": percent_rate * multiplier,
        "corrosion_rate_mm_per_year": rate,
        "calculation_method": "LATEST_INSPECTION_INSTALLATION_AVERAGE",
        "assumption": "NO_TUBE_REPLACEMENT_ZERO_INITIAL_LOSS_CONSTANT_AVERAGE_RATE",
    }
    if loss == 0:
        return {**common, "status": "NO_POSITIVE_WALL_LOSS"}
    try:
        result = calculate_tube_plugging_year(
            measurement_date=measured, nominal_thickness_mm=nominal,
            current_wall_loss_mm=nominal * loss / 100.0,
            corrosion_rate_mm_per_year=rate,
            plugging_wall_loss_percent=limit,
        )
    except (ValueError, OverflowError):
        return {**common, "status": "PROJECTION_OUT_OF_DATE_RANGE"}
    return {**common, **result,
            "status": "ESTIMATED_INSTALLATION_YEAR" if installation_precision == "YEAR"
            else "CALCULATED_INSTALLATION_AVERAGE"}


def calculate_api510_inspection_interval(
    *,
    actual_thickness_mm: float,
    required_thickness_mm: float,
    corrosion_rate_mm_per_year: float,
    last_inspection_date: date | datetime | str,
    inspection_type: str = "INTERNAL_ON_STREAM",
    as_of_date: date | datetime | str | None = None,
) -> dict:
    """Calculate API 510 remaining life and a Section 6 inspection interval.

    Required thickness is an approved engineering input; this function does not
    derive it from nominal tube thickness or a wall-loss percentage.
    """
    try:
        actual = float(actual_thickness_mm)
        required = float(required_thickness_mm)
        rate = float(corrosion_rate_mm_per_year)
    except (TypeError, ValueError) as exc:
        raise ValueError("API 510 두께와 부식속도는 숫자로 입력해야 합니다.") from exc
    if not all(math.isfinite(value) for value in (actual, required, rate)):
        raise ValueError("API 510 입력값은 유한한 숫자여야 합니다.")
    if actual <= 0:
        raise ValueError("실제 측정두께는 0보다 커야 합니다.")
    if required < 0:
        raise ValueError("필요두께는 0 이상이어야 합니다.")
    if rate <= 0:
        raise ValueError("API 510 검사주기 계산에는 0보다 큰 적용 부식속도가 필요합니다.")

    inspection_type = str(inspection_type or "").strip().upper()
    maximums = {
        "INTERNAL_ON_STREAM": API510_INTERNAL_MAX_INTERVAL_YEARS,
        "EXTERNAL": API510_EXTERNAL_MAX_INTERVAL_YEARS,
    }
    if inspection_type not in maximums:
        raise ValueError("검사 유형은 내부/가동중 검사 또는 외부검사만 선택할 수 있습니다.")

    origin = _date_value(last_inspection_date)
    basis_date = _date_value(as_of_date) if as_of_date is not None else remaining_life_as_of_date()
    remaining_allowance = actual - required
    if remaining_allowance <= 0:
        remaining_life = 0.0
        interval_years = 0.0
        status = "ACTION_REQUIRED"
    else:
        remaining_life = remaining_allowance / rate
        interval_years = min(
            remaining_life * API510_INTERVAL_FRACTION,
            maximums[inspection_type],
        )
        status = "CALCULATED"
    next_date = origin + timedelta(days=interval_years * 365.2425)
    overdue = next_date < basis_date
    if overdue and status == "CALCULATED":
        status = "OVERDUE"
    return {
        "calculation_method": "API510",
        "code_edition": API510_CODE_EDITION,
        "inspection_type": inspection_type,
        "inspection_type_label": (
            "내부/가동중 검사" if inspection_type == "INTERNAL_ON_STREAM" else "외부검사"
        ),
        "actual_thickness_mm": actual,
        "required_thickness_mm": required,
        "corrosion_rate_mm_per_year": rate,
        "remaining_corrosion_allowance_mm": remaining_allowance,
        "remaining_life_years": remaining_life,
        "interval_fraction": API510_INTERVAL_FRACTION,
        "maximum_interval_years": maximums[inspection_type],
        "inspection_interval_years": interval_years,
        "last_inspection_date": origin.isoformat(),
        "next_inspection_date": next_date.isoformat(),
        "as_of_date": basis_date.isoformat(),
        "overdue": overdue,
        "status": status,
        "formula": "min((t_actual - t_required) / CR × interval factor, maximum interval)",
    }


def summarize_remaining_life(*, plugging_years: Iterable[int], total_tube_count: int,
                             is_critical: bool, current_year: int,
                             base_year: int | None = None,
                             allowable_plugging_percent: float | None = None) -> dict:
    """Aggregate projected Plugging years and find the first limit-exceeding year."""
    base_year = int(current_year if base_year is None else base_year)
    limit_percent = (
        DEFAULT_PLUGGING_LIMIT_PERCENT
        if allowable_plugging_percent is None
        else float(allowable_plugging_percent)
    )
    if limit_percent not in REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS:
        raise ValueError("허용 Plugging 한도는 1%부터 20%까지 선택할 수 있습니다.")
    allowable_count = math.floor(max(total_tube_count, 0) * limit_percent / 100.0)
    counts = Counter(int(year) for year in plugging_years)
    cumulative = 0
    yearly = []
    life_reached_year = None
    for year in sorted(counts):
        cumulative += counts[year]
        exceeded = cumulative > allowable_count
        yearly.append({
            "year": year,
            "new_plugging_count": counts[year],
            "cumulative_plugging_count": cumulative,
            "limit_exceeded": exceeded,
        })
        if exceeded and life_reached_year is None:
            life_reached_year = year
    return {
        "current_year": current_year,
        "base_year": base_year,
        "is_critical": bool(is_critical),
        "limit_percent": limit_percent,
        "allowable_plugging_count": allowable_count,
        "life_reached_year": life_reached_year,
        "remaining_life_years": life_reached_year - base_year if life_reached_year is not None else None,
        "yearly": yearly,
    }
