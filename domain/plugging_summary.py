"""Keep recorded operations, measured thresholds and forecasts distinct."""
from datetime import date

from .tube_status import normalize_tube_status


def plugging_counts(tubes, latest_results, projections, threshold, as_of, expected_count):
    actual = {t.tube_id for t in tubes if normalize_tube_status(t.current_status) == 'PLUGGED'}
    reached = {t.tube_id for t in tubes if t.tube_id not in actual
               and t.tube_id in latest_results
               and latest_results[t.tube_id][0].wall_loss_percent is not None
               and latest_results[t.tube_id][0].wall_loss_percent >= threshold}
    future = {p['tube_id'] for p in projections if p['tube_id'] not in actual
              and p['tube_id'] not in reached and date.fromisoformat(p['plugging_date']) > as_of}
    return {
        'actual_plugged_count': len(actual),
        'threshold_reached_count': len(reached),
        'future_plugging_count': len(future),
        'registered_in_service_count': sum(normalize_tube_status(t.current_status) == 'IN_SERVICE' for t in tubes),
        'uninspected_registered_count': sum(t.tube_id not in latest_results for t in tubes),
        'unregistered_tube_count': max(expected_count - len(tubes), 0) if expected_count else None,
    }
