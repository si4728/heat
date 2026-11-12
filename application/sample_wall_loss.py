"""Select one current-installation inspection cohort for the figure-5 model."""
from datetime import date, datetime
import math
from ..domain.inspection_lifecycle import current_installation_date, is_current_installation_inspection
from ..domain.sample_wall_loss import MINIMUM_SAMPLE_SIZE, estimate_sample_wall_loss


def build_sample_estimate(result_rows, tubes_by_id, equipment, master_spec, *, threshold_percent,
                          inspections=None):
    cohorts = {}
    if inspections is not None:
        for inspection in inspections:
            measured = inspection.inspection_date or inspection.report_date
            if (inspection.superseded_by_inspection_id is None and measured is not None
                    and is_current_installation_inspection(measured, equipment.install_date)):
                cohorts[inspection.iris_inspection_id] = [inspection, {}]
    for result, inspection in result_rows:
        measured = inspection.inspection_date or inspection.report_date
        tube = tubes_by_id.get(result.tube_id)
        if (tube is None or measured is None or inspection.superseded_by_inspection_id is not None
                or (inspections is not None and inspection.iris_inspection_id not in cohorts)
                or not is_current_installation_inspection(measured, equipment.install_date, tube.installed_at)):
            continue
        cohorts.setdefault(inspection.iris_inspection_id, [inspection, {}])[1][result.tube_id] = result
    total = int(master_spec.tube_count) if master_spec and master_spec.tube_count else None
    if not cohorts:
        return estimate_sample_wall_loss([], total_tube_count=total)
    inspection, results = max(cohorts.values(), key=lambda pair: (
        pair[0].inspection_date or pair[0].report_date, pair[0].iris_inspection_id))
    measured = inspection.inspection_date or inspection.report_date
    latest_date = measured.date() if isinstance(measured, datetime) else measured
    valid = [r for r in results.values()
             if r.result_status in (None, 'VALID') and r.quality_status in (None, 'VALID')
             and r.wall_loss_percent is not None and math.isfinite(r.wall_loss_percent)
             and 0 <= r.wall_loss_percent <= 100]
    installed_dates = set()
    for result in valid:
        installed = current_installation_date(equipment.install_date,
            tubes_by_id[result.tube_id].installed_at, inspection.installation_or_replacement_date)
        if inspection.installation_or_replacement_year is not None and inspection.installation_or_replacement_date_precision == 'YEAR':
            installed = current_installation_date(installed, date(inspection.installation_or_replacement_year, 7, 1))
        installed_dates.add(installed)
    ambiguous = sum((i.inspection_date or i.report_date) == measured for i, _ in cohorts.values()) > 1
    blocked = 'AMBIGUOUS_INSPECTION' if ambiguous else 'MIXED_INSTALLATION_DATES' if len(installed_dates) > 1 else None
    estimate = estimate_sample_wall_loss(
        [] if blocked else [r.wall_loss_percent for r in valid], total_tube_count=total,
        installation_date=next(iter(installed_dates), None), measurement_date=latest_date,
        threshold_percent=threshold_percent)
    if blocked:
        measured_only = estimate_sample_wall_loss([r.wall_loss_percent for r in valid], total_tube_count=total)
        status = (measured_only['status'] if measured_only['sample_count'] < MINIMUM_SAMPLE_SIZE else blocked)
        estimate.update(status=status, cohort_issue=blocked, sample_count=measured_only['sample_count'],
                        measured_max_wall_loss_percent=measured_only['measured_max_wall_loss_percent'])
    installed = next(iter(installed_dates), None) if len(installed_dates) == 1 else None
    reported = inspection.total_tube_count_reported
    estimate.update(inspection_id=inspection.iris_inspection_id, report_number=inspection.report_number,
        measurement_date=latest_date.isoformat(),
        installation_date=installed.isoformat() if installed else None,
        installation_precision=inspection.installation_or_replacement_date_precision or 'DAY',
        reported_total_tube_count=reported,
        population_count_mismatch=bool(total and reported and total != reported),
        threshold_percent=threshold_percent, total_count_source='CURRENT_SPECIFICATION')
    return estimate
