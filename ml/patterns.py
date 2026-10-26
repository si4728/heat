"""Unsupervised grouping of similar multi-year Tube degradation patterns."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .datasets import load_cohort_a, representative_by_tube_date
from .environment import require_ml_environment


MODEL_VERSION = "tube-degradation-pattern-kmeans-1.0"
MODEL_FEATURES = (
    "latest_wall_loss_percent",
    "maximum_wall_loss_percent",
    "mean_wall_loss_percent",
    "wall_loss_slope_pp_per_year",
    "wall_loss_volatility_pp",
    "maximum_interval_change_pp",
    "inspection_count",
    "latest_minimum_thickness_mm",
)
PATTERN_LABELS = {
    "STABLE_OR_LOW_CHANGE": "안정·저변화형",
    "HIGH_VARIABILITY_OR_REVERSAL": "고변동·역전형",
    "HIGH_WALL_LOSS": "고감육형",
}


def _date(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_tube_pattern_features(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    import numpy as np

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in representative_by_tube_date(rows):
        grouped[int(row["tube_id"])].append(row)
    result: list[dict[str, Any]] = []
    for tube_rows in grouped.values():
        ordered = sorted(tube_rows, key=lambda row: (_date(row["inspection_date"]), int(row["iris_tube_result_id"])))
        if len(ordered) < 2:
            continue
        dates = [_date(row["inspection_date"]) for row in ordered]
        elapsed = np.array([(item - dates[0]).total_seconds() / (365.2425 * 86400) for item in dates], dtype=float)
        losses = np.array([float(row["wall_loss_percent"]) for row in ordered], dtype=float)
        if elapsed[-1] <= 0:
            continue
        thicknesses = [float(row["minimum_wall_thickness_mm"]) for row in ordered if row.get("minimum_wall_thickness_mm") is not None]
        interval_changes = np.diff(losses)
        latest = ordered[-1]
        result.append({
            "plant_id": latest["plant_id"], "unit_id": latest["unit_id"],
            "heat_exchanger_id": latest["heat_exchanger_id"], "bundle_id": latest["bundle_id"],
            "tube_id": latest["tube_id"], "unit_code": latest["unit_code"],
            "equipment_code": latest["equipment_code"], "tube_no": latest["tube_no"],
            "latest_inspection_id": latest["iris_inspection_id"],
            "latest_result_id": latest["iris_tube_result_id"],
            "latest_inspection_date": str(latest["inspection_date"]),
            "source_result_ids": [row["iris_tube_result_id"] for row in ordered],
            "latest_wall_loss_percent": float(losses[-1]),
            "maximum_wall_loss_percent": float(losses.max()),
            "mean_wall_loss_percent": float(losses.mean()),
            "wall_loss_slope_pp_per_year": float(np.polyfit(elapsed, losses, 1)[0]),
            "wall_loss_volatility_pp": float(losses.std()),
            "maximum_interval_change_pp": float(max(abs(interval_changes))) if len(interval_changes) else 0.0,
            "inspection_count": len(ordered),
            "latest_minimum_thickness_mm": thicknesses[-1] if thicknesses else None,
        })
    return result


def _semantic_labels(members: list[dict[str, Any]], labels: Any) -> dict[int, str]:
    cluster_ids = sorted({int(value) for value in labels})
    profiles = {}
    for cluster_id in cluster_ids:
        cluster_rows = [row for row, label in zip(members, labels) if int(label) == cluster_id]
        profiles[cluster_id] = {
            "latest": median(row["latest_wall_loss_percent"] for row in cluster_rows),
            "slope": median(row["wall_loss_slope_pp_per_year"] for row in cluster_rows),
            "volatility": median(row["wall_loss_volatility_pp"] for row in cluster_rows),
        }
    high = max(cluster_ids, key=lambda item: (profiles[item]["latest"], profiles[item]["volatility"]))
    remaining = [item for item in cluster_ids if item != high]
    variable = max(remaining, key=lambda item: (profiles[item]["volatility"], abs(profiles[item]["slope"])))
    stable = next(item for item in remaining if item != variable)
    return {high: "HIGH_WALL_LOSS", variable: "HIGH_VARIABILITY_OR_REVERSAL", stable: "STABLE_OR_LOW_CHANGE"}


def cluster_tube_patterns(members: list[dict[str, Any]], *, cluster_count: int = 3, random_state: int = 42) -> dict[str, Any]:
    require_ml_environment()
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import adjusted_rand_score, silhouette_score
    from sklearn.preprocessing import RobustScaler

    if len(members) < max(30, cluster_count * 5):
        raise ValueError("Insufficient multi-inspection Tube rows for pattern grouping")
    raw = np.array([[np.nan if row.get(field) is None else float(row[field]) for field in MODEL_FEATURES] for row in members], dtype=float)
    imputer = SimpleImputer(strategy="median")
    scaler = RobustScaler()
    matrix = scaler.fit_transform(imputer.fit_transform(raw))
    primary = KMeans(n_clusters=cluster_count, random_state=random_state, n_init=20).fit(matrix)
    repeat = KMeans(n_clusters=cluster_count, random_state=random_state + 1, n_init=20).fit(matrix)
    silhouette = float(silhouette_score(matrix, primary.labels_, sample_size=min(1200, len(members)), random_state=random_state))
    stability = float(adjusted_rand_score(primary.labels_, repeat.labels_))
    names = _semantic_labels(members, primary.labels_)
    assigned = []
    for row, cluster_id, distances in zip(members, primary.labels_, primary.transform(matrix)):
        item = dict(row)
        pattern_code = names[int(cluster_id)]
        item.update(
            cluster_id=int(cluster_id), pattern_code=pattern_code,
            pattern_label=PATTERN_LABELS[pattern_code],
            distance_to_cluster_center=float(distances[int(cluster_id)]),
        )
        assigned.append(item)
    profiles = []
    for cluster_id, pattern_code in sorted(names.items(), key=lambda item: item[1]):
        cluster_rows = [row for row in assigned if row["cluster_id"] == cluster_id]
        profiles.append({
            "cluster_id": cluster_id, "pattern_code": pattern_code,
            "pattern_label": PATTERN_LABELS[pattern_code], "tube_count": len(cluster_rows),
            **{f"median_{field}": median(row[field] for row in cluster_rows if row[field] is not None) for field in MODEL_FEATURES},
        })
    assigned.sort(key=lambda row: (row["pattern_code"], row["distance_to_cluster_center"], int(row["tube_id"])))
    return {"members": assigned, "profiles": profiles, "silhouette": silhouette, "stability_ari": stability}


def run_pattern_grouping(database_path: str | Path) -> dict[str, Any]:
    source_rows = load_cohort_a(database_path)
    features = build_tube_pattern_features(source_rows)
    clustered = cluster_tube_patterns(features)
    minimum_cluster_size = min(profile["tube_count"] for profile in clustered["profiles"])
    gates = {
        "multi_inspection_tubes_ge_1000": len(features) >= 1000,
        "silhouette_ge_0_40": clustered["silhouette"] >= 0.40,
        "seed_stability_ari_ge_0_95": clustered["stability_ari"] >= 0.95,
        "minimum_cluster_size_ge_50": minimum_cluster_size >= 50,
        "identifiers_excluded_from_features": not any(field.endswith("_id") for field in MODEL_FEATURES),
    }
    status = "PASS_WITH_NOTE" if all(gates.values()) else "HOLD"
    return {
        "status": status, "model_version": MODEL_VERSION, "cluster_count": 3,
        "tube_count": len(features), "feature_names": list(MODEL_FEATURES),
        "silhouette": clustered["silhouette"], "stability_ari": clustered["stability_ari"],
        "profiles": clustered["profiles"], "members": clustered["members"], "gates": gates,
        "automatic_engineering_classification_enabled": False,
        "note": "Unsupervised similarity groups are review aids, not damage or fitness-for-service classes.",
    }
