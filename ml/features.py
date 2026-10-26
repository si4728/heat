"""Leakage-safe temporal feature construction."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


MODEL_FEATURES = (
    "prior_wall_loss_percent", "prior_minimum_wall_thickness_mm",
    "prior_observation_count", "elapsed_since_prior_years",
)


def _date(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def temporal_examples(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["tube_id"]].append(row)
    examples: list[dict[str, Any]] = []
    for tube_rows in grouped.values():
        ordered = sorted(tube_rows, key=lambda row: (_date(row["inspection_date"]), row["iris_tube_result_id"]))
        for index in range(1, len(ordered)):
            prior, target = ordered[index - 1], ordered[index]
            elapsed = (_date(target["inspection_date"]) - _date(prior["inspection_date"])).total_seconds() / (365.2425 * 86400)
            examples.append({
                **{key: target.get(key) for key in ("plant_id", "unit_id", "heat_exchanger_id", "bundle_id", "tube_id")},
                "source_result_id": prior["iris_tube_result_id"],
                "target_result_id": target["iris_tube_result_id"],
                "feature_date": prior["inspection_date"],
                "target_date": target["inspection_date"],
                "prior_wall_loss_percent": prior.get("wall_loss_percent"),
                "prior_minimum_wall_thickness_mm": prior.get("minimum_wall_thickness_mm"),
                "prior_observation_count": index,
                "elapsed_since_prior_years": elapsed,
                "target_wall_loss_percent": target.get("wall_loss_percent"),
                "target_minimum_wall_thickness_mm": target.get("minimum_wall_thickness_mm"),
            })
    return examples


def model_feature_row(example: dict[str, Any]) -> dict[str, Any]:
    """Return only approved predictors; IDs and targets remain trace metadata."""
    return {field: example.get(field) for field in MODEL_FEATURES}
