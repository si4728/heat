"""Operational anomaly and data-quality detection cycle.

The cycle is fail-closed, single-run, read-only against the operational DB, and
writes only versioned artifacts. It never changes measurements or engineering
decisions.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .anomaly import run_priority_model
from .artifacts import ArtifactStore
from .datasets import COHORT_A_SQL_VERSION, DATASET_VERSION, cohort_counts, load_cohort_a
from .readonly_db import database_sha256, validate_database_path
from .review_feedback import latest_labels_by_result
from .snapshots import canonical_rows_sha256


OPERATION_VERSION = "anomaly-quality-operations-1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@contextmanager
def _exclusive_run_lock(artifact_root: str | Path) -> Iterator[None]:
    root = Path(artifact_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".anomaly-quality.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("An anomaly-quality operation is already running") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump({"pid": os.getpid(), "started_at": _now()}, target)
        yield
    finally:
        lock.unlink(missing_ok=True)


def run_anomaly_quality_operation(
    database_path: str | Path,
    artifact_root: str | Path,
    review_database_path: str | Path,
    *,
    units: tuple[str, ...] = ("VCM1", "VCM2"),
    contamination: float = 0.02,
    estimators: int = 300,
    random_state: int = 42,
    run_id: str | None = None,
) -> dict[str, Any]:
    database = validate_database_path(database_path, Path(database_path).resolve().parent)
    root = Path(artifact_root).resolve()
    identifier = run_id or _run_id()
    started_at = _now()
    with _exclusive_run_lock(root):
        store = ArtifactStore(root, protected_directories=(database.parent,))
        before = database_sha256(database)
        rows = load_cohort_a(database, data_root=database.parent)
        snapshot = {
            "dataset_version": DATASET_VERSION,
            "sql_version": COHORT_A_SQL_VERSION,
            "row_count": len(rows),
            "rows_sha256": canonical_rows_sha256(rows),
            "cohort_counts": cohort_counts(rows),
        }
        labels = latest_labels_by_result(review_database_path)
        evaluation_labels = labels if len(labels) >= 30 else None
        anomaly = run_priority_model(
            database,
            units=units,
            contamination=contamination,
            estimators=estimators,
            random_state=random_state,
            labels=evaluation_labels,
        )
        after = database_sha256(database)
        gates = {
            "operational_database_unchanged": before == after,
            "source_rows_present": snapshot["row_count"] > 0,
            "model_rows_present": int(anomaly.get("row_count") or 0) > 0,
            "hard_gate_critical_omissions_zero": int(
                anomaly.get("evaluation", {}).get("hard_gate_critical_omissions") or 0
            ) == 0,
            "automatic_decision_disabled": not bool(
                anomaly.get("evaluation", {}).get("automatic_decision_enabled")
            ),
        }
        model_status = str(anomaly.get("evaluation", {}).get("status") or "HOLD")
        status = model_status if all(gates.values()) else "FAIL"
        quality = {
            "operation_version": OPERATION_VERSION,
            "run_id": identifier,
            "generated_at": _now(),
            "status": status,
            "gates": gates,
            **(anomaly.get("quality_detection") or {}),
            "automatic_source_update_enabled": False,
            "automatic_engineering_decision_enabled": False,
        }
        summary = {
            "run_id": identifier,
            "operation": "ANOMALY_QUALITY_DETECTION",
            "operation_version": OPERATION_VERSION,
            "started_at": started_at,
            "finished_at": _now(),
            "status": status,
            "stage_statuses": {"2": status},
            "database_sha256_before": before,
            "database_sha256_after": after,
            "operational_database_changed": before != after,
            "dataset_row_count": snapshot["row_count"],
            "model_row_count": anomaly.get("row_count", 0),
            "expert_label_count": len(labels),
            "gates": gates,
            "automatic_measurement_update_enabled": False,
            "automatic_engineering_decision_enabled": False,
        }
        store.write_json(f"{identifier}/data/dataset_snapshot.json", snapshot)
        store.write_json(f"{identifier}/evaluation/anomaly_pilot.json", anomaly)
        store.write_json(f"{identifier}/evaluation/quality_detection.json", quality)
        store.write_json(f"{identifier}/stage_2_result.json", summary)
        store.write_json(f"{identifier}/run_summary.json", summary)
        return summary
