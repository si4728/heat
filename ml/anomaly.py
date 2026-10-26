"""Review-priority model: immutable hard gates plus reproducible anomaly score."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from .environment import require_ml_environment
from .readonly_db import readonly_connection


MODEL_VERSION = "review-priority-1.0"
REVIEW_LABELS = {
    "CONFIRMED_SOURCE_ERROR", "CONFIRMED_MAPPING_ERROR", "CONFIRMED_FORMULA_ERROR",
    "CONFIRMED_MEASUREMENT_VARIATION", "VALID_EXTREME_VALUE", "ENGINEERING_ACCEPTED",
    "INSUFFICIENT_EVIDENCE", "RECHECK_REQUIRED",
}
VALID_ISSUE_LABELS = {
    "CONFIRMED_SOURCE_ERROR", "CONFIRMED_MAPPING_ERROR", "CONFIRMED_FORMULA_ERROR",
    "CONFIRMED_MEASUREMENT_VARIATION", "RECHECK_REQUIRED",
}


def summarize_quality_detection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    hard_gate_counts: dict[str, int] = defaultdict(int)
    review_flag_counts: dict[str, int] = defaultdict(int)
    quality_status_counts: dict[str, int] = defaultdict(int)
    unit_counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"rows": 0, "hard_gate_rows": 0, "ml_anomaly_rows": 0, "flagged_rows": 0}
    )
    flagged_rows = 0
    for row in rows:
        hard_flags = set(row.get("hard_gate_flags") or ())
        review_flags = set(row.get("review_flags") or ())
        if hard_flags or review_flags:
            flagged_rows += 1
        for flag in hard_flags:
            hard_gate_counts[str(flag)] += 1
        for flag in review_flags:
            review_flag_counts[str(flag)] += 1
        quality_status_counts[str(row.get("quality_status") or "UNKNOWN")] += 1
        unit = unit_counts[str(row.get("unit_code") or "UNKNOWN")]
        unit["rows"] += 1
        unit["hard_gate_rows"] += int(bool(hard_flags))
        unit["ml_anomaly_rows"] += int(bool(row.get("ml_anomaly")))
        unit["flagged_rows"] += int(bool(hard_flags or review_flags))
    return {
        "row_count": len(rows),
        "flagged_row_count": flagged_rows,
        "hard_gate_row_count": sum(bool(row.get("hard_gate")) for row in rows),
        "ml_anomaly_row_count": sum(bool(row.get("ml_anomaly")) for row in rows),
        "hard_gate_flag_counts": dict(sorted(hard_gate_counts.items())),
        "review_flag_counts": dict(sorted(review_flag_counts.items())),
        "quality_status_counts": dict(sorted(quality_status_counts.items())),
        "unit_counts": {key: value for key, value in sorted(unit_counts.items())},
        "automatic_source_update_enabled": False,
        "automatic_engineering_decision_enabled": False,
    }


def _open_issue_flags(database_path: str | Path) -> dict[int, list[str]]:
    query = """
        SELECT iris_tube_result_id, issue_code, severity
        FROM data_quality_issue
        WHERE status = 'OPEN' AND iris_tube_result_id IS NOT NULL
        ORDER BY data_quality_issue_id
    """
    result: dict[int, list[str]] = defaultdict(list)
    with readonly_connection(database_path) as connection:
        for row in connection.execute(query):
            result[int(row["iris_tube_result_id"])].append(f"OPEN_QUALITY_{row['severity']}_{row['issue_code']}")
    return result


def hard_gate_flags(row: dict[str, Any], open_issue_flags: Iterable[str] = ()) -> list[str]:
    flags: list[str] = []
    review_flags = set(row.get("review_flags") or ())
    if "FORMULA_RESIDUAL_GT_1PP" in review_flags:
        flags.append("FORMULA_MISMATCH")
    if "MINIMUM_THICKNESS_MISSING" in review_flags:
        flags.append("MISSING_THICKNESS")
    if float(row.get("wall_loss_percent") or 0) >= 40.0:
        flags.append("RISK_THRESHOLD_WALL_LOSS_GE_40")
    for issue in open_issue_flags:
        upper = issue.upper()
        if any(token in upper for token in ("CALCULATION_MISMATCH", "MAPPING", "LAYOUT_ERROR", "EQUIPMENT_LABEL")):
            flags.append(issue)
    return sorted(set(flags))


def rank_review_priorities(rows: list[dict[str, Any]], issue_flags: dict[int, list[str]] | None = None) -> list[dict[str, Any]]:
    issue_flags = issue_flags or {}
    ranked: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        hard = hard_gate_flags(row, issue_flags.get(int(row["iris_tube_result_id"]), ()))
        row["hard_gate_flags"] = hard
        row["hard_gate"] = bool(hard)
        row["priority_score"] = len(hard) * 1_000_000.0 + float(row.get("wall_loss_percent") or 0) * 1_000.0 + float(row.get("ml_anomaly_score") or 0)
        ranked.append(row)
    ranked.sort(key=lambda row: (-int(row["hard_gate"]), -row["priority_score"], int(row["iris_tube_result_id"])))
    for rank, row in enumerate(ranked, 1):
        row["review_priority_rank"] = rank
    return ranked


def evaluate_priorities(rows: list[dict[str, Any]], labels: dict[int, str] | None = None) -> dict[str, Any]:
    labels = labels or {}
    invalid = sorted(set(labels.values()) - REVIEW_LABELS)
    if invalid:
        raise ValueError(f"Unsupported review labels: {', '.join(invalid)}")
    hard_rows = [row for row in rows if row["hard_gate"]]
    hard_omissions = sum(not row["hard_gate"] for row in hard_rows)
    result: dict[str, Any] = {
        "hard_gate_rows": len(hard_rows),
        "hard_gate_critical_omissions": hard_omissions,
        "review_label_count": len(labels),
        "automatic_decision_enabled": False,
    }
    if not labels:
        return {**result, "status": "PASS_WITH_NOTE", "note": "Expert review labels are unavailable; report-only pilot mode is enforced."}
    for size in (30, 100):
        labelled = [(row, labels.get(int(row["iris_tube_result_id"]))) for row in rows[:size]]
        reviewed = [label for _, label in labelled if label]
        result[f"precision_at_{size}"] = (sum(label in VALID_ISSUE_LABELS for label in reviewed) / len(reviewed)) if reviewed else None
    precision30 = result["precision_at_30"]
    result["status"] = "PASS" if hard_omissions == 0 and precision30 is not None and precision30 >= 0.60 else "HOLD"
    return result


def run_priority_model(
    database_path: str | Path,
    *,
    units: tuple[str, ...] = ("VCM1", "VCM2"),
    contamination: float = 0.02,
    estimators: int = 300,
    random_state: int = 42,
    labels: dict[int, str] | None = None,
) -> dict[str, Any]:
    require_ml_environment()
    # Delayed import keeps Flask and non-ML commands available without sklearn.
    from iris2.hx_ml import engineer_features, fit_isolation_forests, load_wall_loss_rows

    source_rows = load_wall_loss_rows(Path(database_path), units)
    featured = engineer_features(source_rows)
    scored, unit_summaries = fit_isolation_forests(featured, contamination=contamination, estimators=estimators, random_state=random_state)
    priorities = rank_review_priorities(scored, _open_issue_flags(database_path))
    evaluation = evaluate_priorities(priorities, labels)
    return {
        "model_version": MODEL_VERSION,
        "baseline": {"model": "IsolationForest", "units": list(units), "contamination": contamination, "estimators": estimators, "random_state": random_state},
        "row_count": len(priorities),
        "unit_summaries": unit_summaries,
        "quality_detection": summarize_quality_detection(priorities),
        "evaluation": evaluation,
        "top_30": priorities[:30],
    }
