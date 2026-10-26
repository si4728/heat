"""Read-only adapter from governed ML artifacts to the review UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .datasets import load_cohort_a
from .readonly_db import database_sha256
from .review_feedback import (
    LABEL_DEFINITIONS,
    evaluate_expert_feedback,
    latest_hotspot_review_feedback,
    latest_review_feedback,
)
from .snapshots import canonical_rows_sha256


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def latest_run_directory(
    artifact_root: str | Path,
    required_artifact: str = "run_summary.json",
) -> Path | None:
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        return None
    candidates = [
        item for item in root.iterdir()
        if item.is_dir()
        and (item / "run_summary.json").is_file()
        and (item / required_artifact).is_file()
    ]
    return max(candidates, key=lambda item: item.name) if candidates else None


def anomaly_run_history(artifact_root: str | Path, limit: int = 10) -> list[dict[str, Any]]:
    root = Path(artifact_root).resolve()
    if not root.is_dir():
        return []
    candidates = sorted(
        (
            item for item in root.iterdir()
            if item.is_dir()
            and (item / "run_summary.json").is_file()
            and (item / "evaluation" / "anomaly_pilot.json").is_file()
        ),
        key=lambda item: item.name,
        reverse=True,
    )[:limit]
    history: list[dict[str, Any]] = []
    for directory in candidates:
        try:
            summary = _read_object(directory / "run_summary.json")
            anomaly = _read_object(directory / "evaluation" / "anomaly_pilot.json")
            quality_path = directory / "evaluation" / "quality_detection.json"
            quality = _read_object(quality_path) if quality_path.is_file() else anomaly.get("quality_detection") or {}
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        history.append({
            "run_id": summary.get("run_id", directory.name),
            "operation": summary.get("operation", "GOVERNED_PIPELINE"),
            "status": summary.get("status", anomaly.get("evaluation", {}).get("status", "UNKNOWN")),
            "finished_at": summary.get("finished_at"),
            "model_version": anomaly.get("model_version"),
            "model_row_count": anomaly.get("row_count", 0),
            "hard_gate_row_count": quality.get("hard_gate_row_count", anomaly.get("evaluation", {}).get("hard_gate_rows", 0)),
            "ml_anomaly_row_count": quality.get("ml_anomaly_row_count"),
            "operational_database_changed": bool(summary.get("operational_database_changed", False)),
        })
    return history


def load_latest_ml_review(
    database_path: str | Path,
    artifact_root: str | Path,
    *,
    unit_code: str = "",
    equipment_code: str = "",
    hard_only: bool = False,
    feedback_database_path: str | Path | None = None,
) -> dict[str, Any]:
    run_directory = latest_run_directory(artifact_root, "evaluation/anomaly_pilot.json")
    empty = {
        "availability": "UNAVAILABLE", "enabled": False, "rows": [],
        "unit_code": unit_code.strip().upper(), "equipment_code": equipment_code.strip().upper(),
        "hard_only": hard_only, "message": "사용 가능한 ML 검토 Artifact가 없습니다.",
        "label_definitions": LABEL_DEFINITIONS,
        "expert_evaluation": {},
        "quality_detection": {},
        "anomaly_run_history": anomaly_run_history(artifact_root),
    }
    if run_directory is None:
        return empty
    try:
        summary = _read_object(run_directory / "run_summary.json")
        anomaly = _read_object(run_directory / "evaluation" / "anomaly_pilot.json")
        snapshot = _read_object(run_directory / "data" / "dataset_snapshot.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**empty, "availability": "INVALID", "message": f"ML Artifact를 안전하게 읽을 수 없습니다: {exc}"}

    current_hash = database_sha256(database_path)
    artifact_hash = str(summary.get("database_sha256_after") or summary.get("database_sha256_before") or "")
    match_basis = "PHYSICAL_SHA256"
    if artifact_hash != current_hash:
        expected_rows_hash = str(snapshot.get("rows_sha256") or "")
        current_rows_hash = canonical_rows_sha256(load_cohort_a(database_path)) if expected_rows_hash else ""
        match_basis = "LOGICAL_DATASET_SHA256"
    else:
        expected_rows_hash = current_rows_hash = ""
    logical_match = bool(expected_rows_hash) and expected_rows_hash == current_rows_hash
    if not artifact_hash or (artifact_hash != current_hash and not logical_match):
        return {
            **empty, "availability": "STALE", "run_id": summary.get("run_id", run_directory.name),
            "message": "운영 DB가 분석 시점과 달라 ML 결과를 비활성화했습니다. 새 Snapshot으로 재실행해야 합니다.",
        }

    evaluation = anomaly.get("evaluation") or {}
    if evaluation.get("status") not in {"PASS", "PASS_WITH_NOTE"}:
        return {**empty, "availability": "HOLD", "message": "이상치 모델 Gate가 통과되지 않아 결과를 표시하지 않습니다."}

    required = {"iris_tube_result_id", "iris_inspection_id", "tube_id", "equipment_code", "unit_code", "review_priority_rank"}
    source_rows: list[dict[str, Any]] = []
    for source in anomaly.get("top_30") or []:
        if not isinstance(source, dict) or not required.issubset(source):
            continue
        row = dict(source)
        source_rows.append(row)
    feedback = (
        latest_review_feedback(feedback_database_path, str(summary.get("run_id", run_directory.name)))
        if feedback_database_path else {}
    )
    expert_evaluation = evaluate_expert_feedback(
        source_rows,
        feedback,
        hard_gate_critical_omissions=int(evaluation.get("hard_gate_critical_omissions") or 0),
    )
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        row["review_feedback"] = feedback.get(int(row["iris_tube_result_id"]))
        if empty["unit_code"] and str(row.get("unit_code", "")).upper() != empty["unit_code"]:
            continue
        if empty["equipment_code"] and empty["equipment_code"] not in str(row.get("equipment_code", "")).upper():
            continue
        if hard_only and not row.get("hard_gate"):
            continue
        rows.append(row)
    rows.sort(key=lambda row: (int(row["review_priority_rank"]), int(row["iris_tube_result_id"])))
    return {
        **empty,
        "availability": "READY",
        "enabled": True,
        "message": evaluation.get("note") or "검토지원 결과입니다.",
        "rows": rows,
        "run_id": summary.get("run_id", run_directory.name),
        "model_version": anomaly.get("model_version"),
        "database_sha256": current_hash,
        "database_match_basis": match_basis,
        "total_model_rows": anomaly.get("row_count", 0),
        "hard_gate_rows": evaluation.get("hard_gate_rows", 0),
        "review_label_count": len(feedback),
        "label_definitions": LABEL_DEFINITIONS,
        "expert_evaluation": expert_evaluation,
        "quality_detection": anomaly.get("quality_detection") or {},
        "anomaly_run_history": anomaly_run_history(artifact_root),
        "automatic_decision_enabled": bool(evaluation.get("automatic_decision_enabled", False)),
    }


def load_latest_spatial_review(
    database_path: str | Path,
    artifact_root: str | Path,
    *,
    unit_code: str = "",
    equipment_code: str = "",
    inspection_year: str = "",
    feedback_database_path: str | Path | None = None,
) -> dict[str, Any]:
    selected_unit = unit_code.strip().upper()
    selected_equipment = equipment_code.strip().upper()
    try:
        selected_year = int(inspection_year) if inspection_year else None
    except (TypeError, ValueError):
        selected_year = None
    empty = {
        "availability": "UNAVAILABLE", "enabled": False, "rows": [],
        "unit_code": selected_unit, "equipment_code": selected_equipment,
        "inspection_year": selected_year, "message": "사용 가능한 공간 Hotspot Artifact가 없습니다.",
        "expert_reviewed_count": 0, "expert_confirmed_count": 0,
        "expert_confirmation_rate": 0.0, "expert_confirmation_gate_passed": False,
    }
    run_directory = latest_run_directory(artifact_root, "evaluation/spatial_pilot.json")
    if run_directory is None:
        return empty
    try:
        summary = _read_object(run_directory / "run_summary.json")
        spatial = _read_object(run_directory / "evaluation" / "spatial_pilot.json")
        snapshot = _read_object(run_directory / "data" / "dataset_snapshot.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**empty, "availability": "INVALID", "message": f"공간 Hotspot Artifact를 안전하게 읽을 수 없습니다: {exc}"}

    current_hash = database_sha256(database_path)
    artifact_hash = str(summary.get("database_sha256_after") or summary.get("database_sha256_before") or "")
    match_basis = "PHYSICAL_SHA256"
    if artifact_hash != current_hash:
        expected_rows_hash = str(snapshot.get("rows_sha256") or "")
        current_rows_hash = canonical_rows_sha256(load_cohort_a(database_path)) if expected_rows_hash else ""
        logical_match = bool(expected_rows_hash) and expected_rows_hash == current_rows_hash
        match_basis = "LOGICAL_DATASET_SHA256"
        if not logical_match:
            return {**empty, "availability": "STALE", "message": "운영 데이터가 공간분석 시점과 달라 결과를 비활성화했습니다."}
    if spatial.get("status") not in {"PASS", "PASS_WITH_NOTE"}:
        return {**empty, "availability": "HOLD", "message": "공간 Hotspot 안전 Gate가 통과되지 않았습니다."}

    expert_review = {}
    expert_review_path = run_directory / "expert_review" / "hotspot_top30_review.json"
    if expert_review_path.is_file():
        try:
            candidate = _read_object(expert_review_path)
            if (
                str(candidate.get("run_id")) == str(summary.get("run_id", run_directory.name))
                and (
                    str(candidate.get("database_sha256")) == current_hash
                    or (
                        bool(candidate.get("dataset_rows_sha256"))
                        and str(candidate.get("dataset_rows_sha256")) == str(snapshot.get("rows_sha256"))
                    )
                )
            ):
                expert_review = candidate
        except (OSError, ValueError, json.JSONDecodeError):
            expert_review = {}
    expert_by_result = {
        int(item["iris_tube_result_id"]): item
        for item in expert_review.get("reviews") or []
        if isinstance(item, dict) and item.get("iris_tube_result_id") is not None
    }
    stored_feedback = (
        latest_hotspot_review_feedback(
            feedback_database_path,
            str(summary.get("run_id", run_directory.name)),
        )
        if feedback_database_path else {}
    )
    rows = []
    required = {"tube_id", "iris_inspection_id", "iris_tube_result_id", "equipment_code", "unit_code", "inspection_year", "evidence_tubes"}
    for source in spatial.get("top_30") or []:
        if not isinstance(source, dict) or not required.issubset(source):
            continue
        if selected_unit and str(source.get("unit_code", "")).upper() != selected_unit:
            continue
        if selected_equipment and selected_equipment not in str(source.get("equipment_code", "")).upper():
            continue
        if selected_year and int(source.get("inspection_year") or 0) != selected_year:
            continue
        row = dict(source)
        row["expert_review"] = expert_by_result.get(int(row["iris_tube_result_id"]))
        row["stored_hotspot_confirmation"] = stored_feedback.get(int(row["iris_tube_result_id"]))
        rows.append(row)
    rows.sort(key=lambda row: (-float(row.get("hotspot_score") or 0), int(row["tube_id"])))
    years = sorted({int(row["inspection_year"]) for row in spatial.get("top_30") or []}, reverse=True)
    return {
        **empty, "availability": "READY", "enabled": True, "rows": rows,
        "years": years, "message": spatial.get("note") or "공간 Hotspot 검토지원 결과입니다.",
        "run_id": summary.get("run_id", run_directory.name), "model_version": spatial.get("model_version"),
        "database_match_basis": match_basis, "total_spatial_rows": spatial.get("row_count", 0),
        "layout_revision_count": spatial.get("layout_revision_count", 0), "equipment_count": spatial.get("equipment_count", 0),
        "confirmed_risk_grade_enabled": bool(spatial.get("confirmed_risk_grade_enabled", False)),
        "expert_reviewed_count": int(expert_review.get("reviewed_count") or 0),
        "expert_confirmed_count": int(expert_review.get("confirmed_count") or 0),
        "expert_confirmation_rate": float(expert_review.get("confirmation_rate") or 0.0),
        "expert_confirmation_gate_passed": bool(expert_review.get("expert_top30_confirmation_ge_60_percent", False)),
        "stored_hotspot_confirmation_count": len(stored_feedback),
    }


def load_latest_pattern_review(
    database_path: str | Path,
    artifact_root: str | Path,
    *,
    pattern_code: str = "",
    unit_code: str = "",
    equipment_code: str = "",
    page: Any = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    selected_pattern = pattern_code.strip().upper()
    selected_unit = unit_code.strip().upper()
    selected_equipment = equipment_code.strip().upper()
    try:
        selected_page = max(1, int(page))
    except (TypeError, ValueError):
        selected_page = 1
    empty = {
        "availability": "UNAVAILABLE", "enabled": False, "rows": [], "profiles": [],
        "pattern_code": selected_pattern, "unit_code": selected_unit,
        "equipment_code": selected_equipment, "page": selected_page, "page_count": 1,
        "per_page": per_page, "total_count": 0,
        "message": "사용 가능한 유사 열화 패턴 Artifact가 없습니다.",
    }
    run_directory = latest_run_directory(artifact_root, "evaluation/pattern_grouping.json")
    if run_directory is None:
        return empty
    try:
        summary = _read_object(run_directory / "run_summary.json")
        patterns = _read_object(run_directory / "evaluation" / "pattern_grouping.json")
        snapshot = _read_object(run_directory / "data" / "dataset_snapshot.json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {**empty, "availability": "INVALID", "message": f"열화 패턴 Artifact를 안전하게 읽을 수 없습니다: {exc}"}

    current_hash = database_sha256(database_path)
    artifact_hash = str(summary.get("database_sha256_after") or summary.get("database_sha256_before") or "")
    match_basis = "PHYSICAL_SHA256"
    if artifact_hash != current_hash:
        expected_rows_hash = str(snapshot.get("rows_sha256") or "")
        current_rows_hash = canonical_rows_sha256(load_cohort_a(database_path)) if expected_rows_hash else ""
        match_basis = "LOGICAL_DATASET_SHA256"
        if not expected_rows_hash or expected_rows_hash != current_rows_hash:
            return {**empty, "availability": "STALE", "message": "운영 데이터가 군집분석 시점과 달라 결과를 비활성화했습니다."}
    if patterns.get("status") not in {"PASS", "PASS_WITH_NOTE"}:
        return {**empty, "availability": "HOLD", "message": "유사 열화 패턴 품질 Gate가 통과되지 않았습니다."}

    allowed_patterns = {str(profile.get("pattern_code")) for profile in patterns.get("profiles") or []}
    if selected_pattern not in allowed_patterns:
        selected_pattern = ""
    required = {"tube_id", "heat_exchanger_id", "latest_inspection_id", "latest_result_id", "pattern_code", "unit_code", "equipment_code"}
    filtered = []
    for source in patterns.get("members") or []:
        if not isinstance(source, dict) or not required.issubset(source):
            continue
        if selected_pattern and source["pattern_code"] != selected_pattern:
            continue
        if selected_unit and str(source["unit_code"]).upper() != selected_unit:
            continue
        if selected_equipment and selected_equipment not in str(source["equipment_code"]).upper():
            continue
        filtered.append(source)
    filtered.sort(key=lambda row: (row["pattern_code"], float(row["distance_to_cluster_center"]), int(row["tube_id"])))
    total_count = len(filtered)
    page_count = max(1, (total_count + per_page - 1) // per_page)
    selected_page = min(selected_page, page_count)
    start = (selected_page - 1) * per_page
    return {
        **empty, "availability": "READY", "enabled": True,
        "rows": filtered[start:start + per_page], "profiles": patterns.get("profiles") or [],
        "pattern_code": selected_pattern, "page": selected_page, "page_count": page_count,
        "total_count": total_count, "message": patterns.get("note") or "유사 열화 패턴 검토지원 결과입니다.",
        "run_id": summary.get("run_id", run_directory.name), "model_version": patterns.get("model_version"),
        "database_match_basis": match_basis, "tube_count": patterns.get("tube_count", 0),
        "silhouette": patterns.get("silhouette"), "stability_ari": patterns.get("stability_ari"),
        "automatic_engineering_classification_enabled": bool(patterns.get("automatic_engineering_classification_enabled", False)),
    }
