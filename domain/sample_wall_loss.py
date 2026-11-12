"""Customer figure-5 Gumbel probability-plot regression; no database writes."""
from datetime import date, datetime, timedelta
import math
from statistics import fmean

MODEL_VERSION = 'GUMBEL_PROBABILITY_PLOT_V1'
MINIMUM_SAMPLE_SIZE = 10


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def project_loss_threshold(loss, *, installed, measured, threshold, estimated=False):
    """Figure 5: measured date + (threshold-X)/(X/service years)."""
    if loss is None:
        return {'status': 'NOT_ESTIMATED', 'date': None, 'year': None}
    if loss >= threshold:
        return {'status': 'ESTIMATED_REACHED' if estimated else 'MEASURED_REACHED', 'date': None, 'year': None}
    try:
        start, origin = _date(installed), _date(measured)
    except (TypeError, ValueError):
        return {'status': 'INVALID_INSTALLATION_DATE', 'date': None, 'year': None}
    if start >= origin:
        return {'status': 'INVALID_INSTALLATION_DATE', 'date': None, 'year': None}
    if loss <= 0:
        return {'status': 'NO_POSITIVE_LOSS', 'date': None, 'year': None}
    elapsed_days = (origin - start).days
    days_remaining = elapsed_days * ((threshold - loss) / loss)
    if not math.isfinite(days_remaining) or days_remaining > (date.max - origin).days:
        return {'status': 'DATE_OUT_OF_RANGE', 'date': None, 'year': None}
    target = origin + timedelta(days=math.floor(days_remaining))
    return {'status': 'FORECAST', 'date': target.isoformat(), 'year': target.year,
            'years_after_inspection': days_remaining / 365.2425,
            'rate_percentage_points_per_year': loss / (elapsed_days / 365.2425)}


def estimate_sample_wall_loss(losses, *, total_tube_count, installation_date=None,
                              measurement_date=None, threshold_percent=40.0):
    values = []
    for value in losses:
        if value is None or isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and 0 <= value <= 100:
            values.append(value)
    values.sort()
    n = len(values)
    result = dict(model_version=MODEL_VERSION, status='SAMPLE_INSUFFICIENT',
        sample_count=n, minimum_sample_count=MINIMUM_SAMPLE_SIZE,
        total_tube_count=total_tube_count, threshold_percent=threshold_percent,
        measured_max_wall_loss_percent=max(values) if values else None,
        estimated_max_wall_loss_percent=None, upper_20_wall_loss_percent=None,
        first_threshold={'status': 'NOT_ESTIMATED', 'date': None, 'year': None},
        twenty_percent_threshold={'status': 'NOT_ESTIMATED', 'date': None, 'year': None})
    if not n:
        result['status'] = 'NO_VALID_SAMPLE'
        return result
    if n < MINIMUM_SAMPLE_SIZE:
        return result
    if type(total_tube_count) is not int or total_tube_count < n:
        result['status'] = 'INVALID_TOTAL_COUNT'
        return result
    if not math.isfinite(threshold_percent) or not 0 < threshold_percent <= 100:
        raise ValueError('Threshold must be greater than zero and at most 100 percent')
    # Regress wall loss x on reduced variate y, as Excel SLOPE(x, y).
    reduced = [-math.log(-math.log((i - 0.3) / (n + 0.4))) for i in range(1, n + 1)]
    mean_y, mean_x = fmean(reduced), fmean(values)
    ss_y = sum((y - mean_y) ** 2 for y in reduced)
    ss_x = sum((x - mean_x) ** 2 for x in values)
    beta = sum((y - mean_y) * (x - mean_x) for y, x in zip(reduced, values)) / ss_y
    if beta <= 0 or ss_x <= 0:
        result['status'] = 'DEGENERATE_SAMPLE'
        return result
    mu = mean_x - beta * mean_y
    max_reduced = -math.log(-math.log1p(-1 / total_tube_count))
    upper_20_reduced = -math.log(-math.log(0.8))
    raw_max = mu + beta * max_reduced
    raw_upper_20 = mu + beta * upper_20_reduced
    # The estimate cannot erase a larger observed maximum or exceed 100% loss.
    estimated_max = min(100.0, max(values[-1], raw_max))
    upper_20 = min(100.0, max(0.0, raw_upper_20))
    residual = sum((x - (mu + beta * y)) ** 2 for y, x in zip(reduced, values))
    result.update(status='ESTIMATED', mu=mu, beta=beta,
        r_squared=max(0.0, min(1.0, 1 - residual / ss_x)),
        raw_estimated_max_wall_loss_percent=raw_max,
        raw_upper_20_wall_loss_percent=raw_upper_20,
        max_reduced_variate=max_reduced, upper_20_reduced_variate=upper_20_reduced,
        estimated_max_wall_loss_percent=estimated_max,
        upper_20_wall_loss_percent=upper_20,
        maximum_capped=raw_max > 100, upper_20_capped=raw_upper_20 > 100,
        observed_max_floor_applied=raw_max < values[-1],
        sample_points=[dict(rank=i, wall_loss_percent=x, reduced_variate=y)
                       for i, (x, y) in enumerate(zip(values, reduced), 1)])
    result['first_threshold'] = project_loss_threshold(estimated_max,
        installed=installation_date, measured=measurement_date, threshold=threshold_percent, estimated=True)
    result['twenty_percent_threshold'] = project_loss_threshold(upper_20,
        installed=installation_date, measured=measurement_date, threshold=threshold_percent, estimated=True)
    result['measured_max_threshold'] = project_loss_threshold(values[-1],
        installed=installation_date, measured=measurement_date, threshold=threshold_percent)
    return result
