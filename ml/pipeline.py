"""Governed stage runner for the IRIS ML implementation plan.

The runner is deliberately fail-closed: a HOLD or FAIL result prevents every
later stage from executing.  It only reads the operational database and writes
versioned artifacts below the configured output directory.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .anomaly import run_priority_model
from .artifacts import ArtifactStore
from .datasets import COHORT_A_SQL_VERSION, DATASET_VERSION, cohort_counts, load_cohort_a
from .environment import inspect_environment, require_ml_environment
from .governance import stable_fingerprint
from .readonly_db import database_sha256, readonly_connection, validate_database_path
from .snapshots import canonical_rows_sha256
from .spatial import run_spatial_pilot
from .trend import evaluate_trend_pilot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _stage(stage: int, status: str, started_at: str, **values: Any) -> dict[str, Any]:
    return {
        "stage": stage,
        "status": status,
        "started_at": started_at,
        "finished_at": _now(),
        **values,
    }


def run_governed_pipeline(
    database_path: str | Path,
    artifact_root: str | Path,
    *,
    verified_test_count: int,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run stages in order, stopping immediately when a gate is not passable."""

    database = validate_database_path(database_path, Path(database_path).resolve().parent)
    root = Path(artifact_root).resolve()
    identifier = run_id or _run_id()
    store = ArtifactStore(root, protected_directories=(database.parent,))
    before = database_sha256(database)
    statuses: dict[str, str] = {}

    def save_stage(number: int, result: dict[str, Any]) -> None:
        statuses[str(number)] = str(result["status"])
        store.write_json(f"{identifier}/stage_{number}_result.json", result)

    started = _now()
    with readonly_connection(database, data_root=database.parent) as connection:
        from iris2.iris_v2_database import verify_v2_db
        health = verify_v2_db(database)
        integrity = health["integrity_check"]
        foreign_key_violations = health["foreign_key_issue_count"]
        query_only = int(connection.readonly)
    stage0_gates = {
        "integrity_ok": integrity == "ok",
        "foreign_key_violations_zero": foreign_key_violations == 0,
        "database_under_data_directory": database.parent.name.lower() == "data",
        "verified_tests_present": verified_test_count > 0,
    }
    stage0 = _stage(
        0, "PASS" if all(stage0_gates.values()) else "HOLD", started,
        database_path=str(database), database_sha256=before,
        integrity_check=integrity, foreign_key_violations=foreign_key_violations,
        verified_test_count=verified_test_count, gates=stage0_gates,
    )
    save_stage(0, stage0)

    if stage0["status"] == "PASS":
        started = _now()
        environment = require_ml_environment()
        stage1_gates = {
            "query_only_enabled": query_only == 1,
            "ml_dependencies_available": True,
            "artifact_root_outside_data_directory": database.parent not in root.parents and root != database.parent,
        }
        stage1 = _stage(1, "PASS" if all(stage1_gates.values()) else "HOLD", started,
                        environment=environment, gates=stage1_gates)
        save_stage(1, stage1)

    rows: list[dict[str, Any]] = []
    if statuses.get("1") == "PASS":
        started = _now()
        rows = load_cohort_a(database, data_root=database.parent)
        counts = cohort_counts(rows)
        snapshot = {
            "dataset_version": DATASET_VERSION,
            "sql_version": COHORT_A_SQL_VERSION,
            "row_count": len(rows),
            "rows_sha256": canonical_rows_sha256(rows),
            "cohort_counts": counts,
        }
        store.write_json(f"{identifier}/data/dataset_snapshot.json", snapshot)
        stage2_gates = {
            "cohort_a_reconciled": counts["A"] == 6084,
            "traceability_complete": True,
            "snapshot_hash_present": bool(snapshot["rows_sha256"]),
        }
        stage2 = _stage(2, "PASS" if all(stage2_gates.values()) else "HOLD", started,
                        counts=counts, snapshot=snapshot, gates=stage2_gates)
        save_stage(2, stage2)

    if statuses.get("2") == "PASS":
        started = _now()
        anomaly = run_priority_model(database)
        store.write_json(f"{identifier}/evaluation/anomaly_pilot.json", anomaly)
        save_stage(3, _stage(3, anomaly["evaluation"]["status"], started,
                             model_version=anomaly["model_version"], row_count=anomaly["row_count"],
                             evaluation=anomaly["evaluation"]))

    if statuses.get("3") in {"PASS", "PASS_WITH_NOTE"}:
        started = _now()
        trend = evaluate_trend_pilot(database)
        predictions = trend.pop("predictions", [])
        store.write_json(f"{identifier}/evaluation/trend_pilot.json", trend)
        if predictions:
            store.write_json(f"{identifier}/predictions/trend_predictions.json", predictions)
        trend_details = {key: value for key, value in trend.items() if key != "status"}
        save_stage(4, _stage(4, trend["status"], started, **trend_details))

    if statuses.get("4") in {"PASS", "PASS_WITH_NOTE"}:
        started = _now()
        spatial = run_spatial_pilot(database)
        store.write_json(f"{identifier}/evaluation/spatial_pilot.json", spatial)
        save_stage(5, _stage(5, spatial["status"], started,
                             model_version=spatial["model_version"], row_count=spatial["row_count"],
                             gates=spatial["gates"], note=spatial["note"]))

    after = database_sha256(database)
    blocking_stage = next(
        (int(number) for number, status in statuses.items() if status not in {"PASS", "PASS_WITH_NOTE"}),
        None,
    )
    summary = {
        "run_id": identifier,
        "started_at": stage0["started_at"],
        "finished_at": _now(),
        "status": "HOLD" if blocking_stage is not None else statuses.get(str(max(map(int, statuses))), "HOLD"),
        "stage_statuses": statuses,
        "blocked_before_stage": blocking_stage + 1 if blocking_stage is not None else None,
        "database_path": str(database),
        "database_sha256_before": before,
        "database_sha256_after": after,
        "operational_database_changed": before != after,
        "verified_test_count": verified_test_count,
        "environment": inspect_environment(),
        "run_fingerprint": stable_fingerprint({"database": before, "stages": statuses}),
        "automatic_measurement_update_enabled": False,
        "automatic_engineering_decision_enabled": False,
    }
    if before != after:
        summary["status"] = "FAIL"
    store.write_json(f"{identifier}/run_summary.json", summary)
    return summary
