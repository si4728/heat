"""Operational Stage 3 Hotspot and degradation-pattern review cycle.

The cycle reads the operational database in query-only mode and writes only
versioned review artifacts. It never updates measurements, layouts, or
engineering decisions.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .artifacts import ArtifactStore
from .datasets import COHORT_A_SQL_VERSION, DATASET_VERSION, cohort_counts, load_cohort_a
from .patterns import run_pattern_grouping
from .readonly_db import database_sha256, validate_database_path
from .snapshots import canonical_rows_sha256
from .spatial import run_spatial_pilot


OPERATION_VERSION = "hotspot-pattern-review-1.0"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@contextmanager
def _exclusive_run_lock(artifact_root: str | Path) -> Iterator[None]:
    root = Path(artifact_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".hotspot-pattern.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("A Hotspot-pattern operation is already running") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            json.dump({"pid": os.getpid(), "started_at": _now()}, target)
        yield
    finally:
        lock.unlink(missing_ok=True)


def run_hotspot_pattern_operation(
    database_path: str | Path,
    artifact_root: str | Path,
    *,
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
        spatial = run_spatial_pilot(database)
        patterns = run_pattern_grouping(database)
        after = database_sha256(database)

        spatial_safety_gates = [
            value
            for key, value in (spatial.get("gates") or {}).items()
            if key != "expert_top30_confirmation_ge_60_percent"
        ]
        gates = {
            "operational_database_unchanged": before == after,
            "source_rows_present": snapshot["row_count"] > 0,
            "spatial_safety_gates_passed": bool(spatial_safety_gates) and all(spatial_safety_gates),
            "pattern_quality_gates_passed": bool(patterns.get("gates")) and all(patterns["gates"].values()),
            "automatic_engineering_decision_disabled": (
                not bool(spatial.get("confirmed_risk_grade_enabled"))
                and not bool(patterns.get("automatic_engineering_classification_enabled"))
            ),
        }
        model_statuses = {str(spatial.get("status")), str(patterns.get("status"))}
        status = (
            "PASS_WITH_NOTE"
            if model_statuses <= {"PASS", "PASS_WITH_NOTE"} and all(gates.values())
            else "HOLD"
        )
        if before != after:
            status = "FAIL"

        summary = {
            "run_id": identifier,
            "operation": "HOTSPOT_DEGRADATION_PATTERN_REVIEW",
            "operation_version": OPERATION_VERSION,
            "started_at": started_at,
            "finished_at": _now(),
            "status": status,
            "stage_statuses": {"3": status},
            "database_sha256_before": before,
            "database_sha256_after": after,
            "operational_database_changed": before != after,
            "dataset_row_count": snapshot["row_count"],
            "spatial_row_count": spatial.get("row_count", 0),
            "hotspot_candidate_count": len(spatial.get("top_30") or []),
            "pattern_tube_count": patterns.get("tube_count", 0),
            "pattern_cluster_count": patterns.get("cluster_count", 0),
            "gates": gates,
            "automatic_measurement_update_enabled": False,
            "automatic_engineering_decision_enabled": False,
        }
        store.write_json(f"{identifier}/data/dataset_snapshot.json", snapshot)
        store.write_json(f"{identifier}/evaluation/spatial_pilot.json", spatial)
        store.write_json(f"{identifier}/evaluation/pattern_grouping.json", patterns)
        store.write_json(f"{identifier}/stage_3_result.json", summary)
        store.write_json(f"{identifier}/run_summary.json", summary)
        return summary

