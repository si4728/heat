"""One current measurement per tube, shared by analysis and equipment ranking."""
from datetime import datetime

from .inspection_lifecycle import is_current_installation_inspection
from .measurement_eligibility import exclusion_reason


def select_current_measurements(result_rows, tubes_by_id, equipment, *, as_of, enforce_quality=True):
    latest = {}
    eligible = []
    historical_count = 0

    def key(pair):
        result, inspection = pair
        measured = inspection.inspection_date or inspection.report_date
        measured = measured.date() if isinstance(measured, datetime) else measured
        loss = result.wall_loss_percent
        return measured, loss is not None, loss if loss is not None else 0, result.iris_tube_result_id

    for result, inspection in result_rows:
        tube = tubes_by_id.get(result.tube_id)
        if tube is None:
            continue
        if enforce_quality and exclusion_reason(inspection, result, as_of=as_of):
            continue
        measured = inspection.inspection_date or inspection.report_date
        if not is_current_installation_inspection(measured, equipment.install_date, tube.installed_at):
            historical_count += 1
            continue
        pair = result, inspection
        eligible.append(pair)
        previous = latest.get(result.tube_id)
        if previous is None or key(pair) > key(previous):
            latest[result.tube_id] = pair
    return latest, eligible, historical_count
