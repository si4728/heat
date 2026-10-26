"""Conservative thickness-trend pilot with time-based validation."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from .datasets import load_cohort_a, representative_by_tube_date
from .environment import require_ml_environment
from .quality_gates import evaluate_pair
from .readonly_db import readonly_connection


MODEL_VERSION = "thickness-trend-pilot-1.2"
SIGNIFICANT_THICKNESS_CHANGE_MM = 0.005
MAX_DIRECTION_SHIFT_FRACTION = 0.20


def _date(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _years(start: Any, end: Any) -> float:
    return (_date(end) - _date(start)).total_seconds() / (365.2425 * 86400)


def _positive_rate(earlier: dict[str, Any], later: dict[str, Any]) -> float | None:
    elapsed = _years(earlier["inspection_date"], later["inspection_date"])
    if elapsed <= 0 or earlier.get("minimum_wall_thickness_mm") is None or later.get("minimum_wall_thickness_mm") is None:
        return None
    value = (float(earlier["minimum_wall_thickness_mm"]) - float(later["minimum_wall_thickness_mm"])) / elapsed
    return value if value > 0 else None


def baseline_prediction(history: list[dict[str, Any]], target_date: Any) -> float | None:
    if len(history) < 2:
        return None
    short = _positive_rate(history[-2], history[-1])
    long = _positive_rate(history[0], history[-1])
    rates = [value for value in (short, long) if value is not None]
    if not rates:
        return None
    return float(history[-1]["minimum_wall_thickness_mm"]) - max(rates) * _years(history[-1]["inspection_date"], target_date)


def model_predictions(history: list[dict[str, Any]], target_date: Any) -> dict[str, float]:
    require_ml_environment()
    import numpy as np
    from sklearn.linear_model import HuberRegressor, TheilSenRegressor

    usable = [row for row in history if row.get("minimum_wall_thickness_mm") is not None]
    if len(usable) < 2:
        return {}
    origin = _date(usable[0]["inspection_date"])
    x = np.array([[_years(origin, row["inspection_date"])] for row in usable], dtype=float)
    y = np.array([float(row["minimum_wall_thickness_mm"]) for row in usable], dtype=float)
    target_x = np.array([[_years(origin, target_date)]], dtype=float)
    predictions = {
        "linear": float(np.polyval(np.polyfit(x[:, 0], y, 1), target_x[0, 0])),
        "last_observation": float(y[-1]),
    }
    if len(usable) >= 3:
        predictions["huber"] = float(HuberRegressor(epsilon=1.35, alpha=0.0, max_iter=500).fit(x, y).predict(target_x)[0])
        predictions["theil_sen"] = float(TheilSenRegressor(random_state=42).fit(x, y).predict(target_x)[0])
    return predictions


def _matched_result_ids(database_path: str | Path, target_year: int) -> set[int]:
    query = """
        SELECT a.current_result_id
        FROM tube_degradation_assessment a
        JOIN iris_tube_result r ON r.iris_tube_result_id = a.current_result_id
        JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
        WHERE a.confidence = 'POSITION_MATCHED'
          AND YEAR(COALESCE(i.inspection_date, i.report_date)) = ?
    """
    with readonly_connection(database_path) as connection:
        return {int(row[0]) for row in connection.execute(query, (target_year,))}


def validation_samples(database_path: str | Path, target_year: int) -> list[dict[str, Any]]:
    rows = representative_by_tube_date(load_cohort_a(database_path))
    by_tube: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tube[int(row["tube_id"])].append(row)
    matched = _matched_result_ids(database_path, target_year)
    samples: list[dict[str, Any]] = []
    for tube_rows in by_tube.values():
        ordered = sorted(tube_rows, key=lambda row: _date(row["inspection_date"]))
        for index, target in enumerate(ordered):
            if int(target["iris_tube_result_id"]) not in matched or _date(target["inspection_date"]).year != target_year:
                continue
            history = ordered[:index]
            if len(history) < 2 or target.get("minimum_wall_thickness_mm") is None:
                continue
            gate = evaluate_pair(history[-1], target)
            if not gate["passed"]:
                continue
            baseline = baseline_prediction(history, target["inspection_date"])
            candidates = model_predictions(history, target["inspection_date"])
            if baseline is None or not candidates:
                continue
            samples.append({
                "unit_code": target["unit_code"], "heat_exchanger_id": target["heat_exchanger_id"],
                "bundle_id": target["bundle_id"], "bundle_lifecycle_no": target["bundle_lifecycle_no"],
                "tube_lifecycle_no": target["tube_lifecycle_no"], "tube_no": target["tube_no"],
                "tube_id": target["tube_id"], "target_result_id": target["iris_tube_result_id"],
                "source_result_ids": [row["iris_tube_result_id"] for row in history],
                "target_date": str(target["inspection_date"]), "actual_thickness_mm": float(target["minimum_wall_thickness_mm"]),
                "forecast_horizon_years": _years(history[-1]["inspection_date"], target["inspection_date"]),
                "actual_wall_loss_percent": float(target["wall_loss_percent"]),
                "nominal_thickness_mm": float(target["calculated_nominal_thickness_mm"]),
                "baseline_prediction_mm": baseline, "candidate_predictions_mm": candidates,
                "quality": "G1_G7_PASS", "confidence": "POSITION_MATCHED",
            })
    return samples


def _mae(samples: list[dict[str, Any]], field) -> float:
    return mean(abs(float(field(row)) - row["actual_thickness_mm"]) for row in samples)


def directional_shift_diagnostics(
    calibration: list[dict[str, Any]],
    final: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare consecutive changes for the exact same equipment and Tube panel."""

    identity_fields = (
        "unit_code", "heat_exchanger_id", "bundle_id", "bundle_lifecycle_no",
        "tube_lifecycle_no", "tube_id",
    )
    calibration_by_identity = {
        tuple(row.get(field) for field in identity_fields): row
        for row in calibration
    }
    matched_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for final_row in final:
        identity = tuple(final_row.get(field) for field in identity_fields)
        calibration_row = calibration_by_identity.get(identity)
        if calibration_row is None:
            continue
        if not final_row["source_result_ids"] or final_row["source_result_ids"][-1] != calibration_row["target_result_id"]:
            continue
        matched_pairs.append((calibration_row, final_row))

    def summarize(changes: list[float]) -> dict[str, Any]:
        increases = sum(value > SIGNIFICANT_THICKNESS_CHANGE_MM for value in changes)
        decreases = sum(value < -SIGNIFICANT_THICKNESS_CHANGE_MM for value in changes)
        flat = len(changes) - increases - decreases
        return {
            "sample_count": len(changes),
            "measured_increase_count": increases,
            "measured_decrease_count": decreases,
            "approximately_flat_count": flat,
            "measured_increase_fraction": increases / len(changes) if changes else 0.0,
            "mean_thickness_change_mm": mean(changes) if changes else None,
        }

    calibration_changes = [
        float(calibration_row["actual_thickness_mm"])
        - float(calibration_row["candidate_predictions_mm"]["last_observation"])
        for calibration_row, _ in matched_pairs
    ]
    final_changes = [
        float(final_row["actual_thickness_mm"])
        - float(calibration_row["actual_thickness_mm"])
        for calibration_row, final_row in matched_pairs
    ]
    calibration_summary, final_summary = summarize(calibration_changes), summarize(final_changes)
    shift = abs(
        final_summary["measured_increase_fraction"]
        - calibration_summary["measured_increase_fraction"]
    )
    return {
        "analysis_scope": "same_equipment_bundle_lifecycle_and_tube_consecutive_panel",
        "identity_fields": list(identity_fields),
        "matched_sample_count": len(matched_pairs),
        "unmatched_calibration_count": len(calibration) - len(matched_pairs),
        "unmatched_final_count": len(final) - len(matched_pairs),
        "change_tolerance_mm": SIGNIFICANT_THICKNESS_CHANGE_MM,
        "maximum_allowed_increase_fraction_shift": MAX_DIRECTION_SHIFT_FRACTION,
        "calibration_2023": calibration_summary,
        "final_2025": final_summary,
        "increase_fraction_absolute_shift": shift,
        "stable": shift <= MAX_DIRECTION_SHIFT_FRACTION,
    }


def evaluate_trend_pilot(database_path: str | Path) -> dict[str, Any]:
    tuning = validation_samples(database_path, 2023)
    final = validation_samples(database_path, 2025)
    methods = sorted(set.intersection(*(set(row["candidate_predictions_mm"]) for row in tuning))) if tuning else []
    if not methods or not final:
        return {"status": "HOLD", "reason": "No quality-gated time-validation samples", "automatic_exposure_enabled": False}
    tuning_mae = {method: _mae(tuning, lambda row, method=method: row["candidate_predictions_mm"][method]) for method in methods}
    selected = min(methods, key=lambda method: (tuning_mae[method], method))
    eligible_final = [row for row in final if selected in row["candidate_predictions_mm"]]
    baseline_mae = _mae(eligible_final, lambda row: row["baseline_prediction_mm"])
    model_mae = _mae(eligible_final, lambda row: row["candidate_predictions_mm"][selected])
    improvement = (baseline_mae - model_mae) / baseline_mae if baseline_mae else 0.0
    directional_shift = directional_shift_diagnostics(tuning, eligible_final)

    # Normalize calibration residuals by forecast horizon.  A fixed-width band
    # calibrated on the mostly one-year 2023 holdout materially understates the
    # uncertainty of the roughly two-year 2025 forecast.  This conformal score
    # uses only the 2023 tuning fold and scales each final interval by its known
    # forecast horizon; no 2025 measured value participates in calibration.
    tuning_scores = sorted(
        abs(row["candidate_predictions_mm"][selected] - row["actual_thickness_mm"])
        / max(float(row["forecast_horizon_years"]), 1e-9)
        for row in tuning
        if selected in row["candidate_predictions_mm"]
    )
    quantile_index = min(len(tuning_scores) - 1, math.ceil((len(tuning_scores) + 1) * 0.8) - 1)
    radius_per_year = tuning_scores[quantile_index]
    radii = [radius_per_year * float(row["forecast_horizon_years"]) for row in eligible_final]
    coverage = mean(
        abs(row["candidate_predictions_mm"][selected] - row["actual_thickness_mm"]) <= radius
        for row, radius in zip(eligible_final, radii)
    )

    def false_safe(row: dict[str, Any], prediction: float) -> bool:
        predicted_loss = max(0.0, (row["nominal_thickness_mm"] - prediction) / row["nominal_thickness_mm"] * 100.0)
        return row["actual_wall_loss_percent"] >= 40.0 and predicted_loss < 40.0

    actual_high_risk = [row for row in eligible_final if row["actual_wall_loss_percent"] >= 40.0]
    baseline_false_safe = sum(false_safe(row, row["baseline_prediction_mm"]) for row in actual_high_risk)
    model_false_safe = sum(false_safe(row, row["candidate_predictions_mm"][selected]) for row in actual_high_risk)
    unit_counts = Counter(row["unit_code"] for row in eligible_final)
    gates = {
        "mae_improvement_ge_10_percent": improvement >= 0.10,
        "prediction_interval_coverage_75_to_90_percent": 0.75 <= coverage <= 0.90,
        "temporal_direction_distribution_stable": directional_shift["stable"],
        "false_safe_not_increased": model_false_safe <= baseline_false_safe,
        "minimum_30_per_production_line": bool(unit_counts) and min(unit_counts.values()) >= 30,
        "traceability_complete": all(row["source_result_ids"] and row["target_result_id"] for row in eligible_final),
    }
    status = "PASS" if all(gates.values()) else "HOLD"
    return {
        "status": status, "model_version": MODEL_VERSION, "selected_by_2023_tuning": selected,
        "tuning_sample_count": len(tuning), "final_sample_count": len(eligible_final), "final_unit_counts": dict(unit_counts),
        "baseline_mae_mm": baseline_mae, "model_mae_mm": model_mae, "mae_improvement_fraction": improvement,
        "prediction_interval": {
            "method": "horizon_normalized_split_conformal",
            "level": 0.80,
            "calibration_radius_mm_per_year": radius_per_year,
            "median_final_radius_mm": median(radii),
            "minimum_final_radius_mm": min(radii),
            "maximum_final_radius_mm": max(radii),
            "coverage": coverage,
        },
        "directional_shift": directional_shift,
        "hold_reason_codes": [
            code
            for failed, code in (
                (not (0.75 <= coverage <= 0.90), "PREDICTION_INTERVAL_UNDERCOVERAGE"),
                (not directional_shift["stable"], "TEMPORAL_DIRECTION_DISTRIBUTION_SHIFT"),
            )
            if failed
        ],
        "high_risk_count": len(actual_high_risk), "baseline_false_safe_count": baseline_false_safe,
        "model_false_safe_count": model_false_safe, "gates": gates,
        "automatic_exposure_enabled": status == "PASS",
        "predictions": eligible_final,
    }
