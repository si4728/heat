"""Versioned, traceable ML dataset extraction from the operational database."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .readonly_db import readonly_connection


DATASET_VERSION = "iris-ml-datamart-1.0"
COHORT_A_SQL_VERSION = "cohort-a-wall-loss-v1"
TRACE_FIELDS = (
    "plant_id", "unit_id", "heat_exchanger_id", "bundle_id", "tube_id",
    "iris_inspection_id", "iris_tube_result_id", "inspection_date",
    "source_document_id", "source_page",
)

COHORT_A_SQL = """
SELECT
    p.plant_id,
    u.unit_id,
    i.heat_exchanger_id,
    i.bundle_id,
    r.tube_id,
    i.iris_inspection_id,
    r.iris_tube_result_id,
    COALESCE(i.inspection_date, i.report_date) AS inspection_date,
    i.source_document_id,
    r.source_page,
    p.plant_code,
    u.unit_code,
    e.equipment_code,
    b.lifecycle_no AS bundle_lifecycle_no,
    t.lifecycle_no AS tube_lifecycle_no,
    t.tube_no,
    COALESCE(sc.scope_code, 'ALL') AS scope_code,
    r.minimum_wall_thickness_mm,
    r.wall_loss_depth_mm,
    r.wall_loss_percent,
    r.design_wall_thickness_mm,
    r.location_mm,
    r.corrosion_type,
    r.result_status,
    r.quality_status,
    CASE
      WHEN r.minimum_wall_thickness_mm IS NOT NULL AND r.wall_loss_depth_mm IS NOT NULL
      THEN r.minimum_wall_thickness_mm + r.wall_loss_depth_mm
    END AS calculated_nominal_thickness_mm
FROM iris_tube_result r
JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
JOIN inspection_campaign c ON c.campaign_id = i.campaign_id
JOIN process_unit u ON u.unit_id = c.unit_id
JOIN plant p ON p.plant_id = u.plant_id
JOIN heat_exchanger h ON h.heat_exchanger_id = i.heat_exchanger_id
JOIN equipment e ON e.equipment_id = h.equipment_id
JOIN tube_bundle b ON b.bundle_id = i.bundle_id
JOIN heat_exchanger_tube t ON t.tube_id = r.tube_id
LEFT JOIN inspection_scope sc ON sc.inspection_scope_id = i.inspection_scope_id
WHERE r.wall_loss_percent IS NOT NULL
ORDER BY p.plant_id, u.unit_id, i.heat_exchanger_id, i.bundle_id,
         r.tube_id, inspection_date, r.iris_tube_result_id
"""


def load_cohort_a(database_path: str | Path, *, data_root: str | Path | None = None) -> list[dict[str, Any]]:
    with readonly_connection(database_path, data_root=data_root) as connection:
        rows = [dict(row) for row in connection.execute(COHORT_A_SQL)]
    validate_traceability(rows)
    return rows


def validate_traceability(rows: Iterable[dict[str, Any]]) -> None:
    seen: set[Any] = set()
    for index, row in enumerate(rows):
        missing = [field for field in TRACE_FIELDS if row.get(field) in (None, "")]
        if missing:
            raise ValueError(f"Row {index} lacks trace fields: {', '.join(missing)}")
        result_id = row["iris_tube_result_id"]
        if result_id in seen:
            raise ValueError(f"Duplicate iris_tube_result_id: {result_id}")
        seen.add(result_id)


def representative_by_tube_date(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse multi-scope readings using the conservative business rule."""

    grouped: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["tube_id"], str(row["inspection_date"])[:10])].append(row)
    representatives: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: (str(item[0]), item[1])):
        candidates = grouped[key]
        chosen = max(
            candidates,
            key=lambda row: (
                float(row["wall_loss_percent"]),
                -(float(row["minimum_wall_thickness_mm"]) if row["minimum_wall_thickness_mm"] is not None else float("inf")),
                -int(row["iris_tube_result_id"]),
            ),
        ).copy()
        valid_thickness = [float(row["minimum_wall_thickness_mm"]) for row in candidates if row["minimum_wall_thickness_mm"] is not None]
        chosen["minimum_wall_thickness_mm"] = min(valid_thickness) if valid_thickness else None
        chosen["wall_loss_percent"] = max(float(row["wall_loss_percent"]) for row in candidates)
        chosen["represented_result_ids"] = sorted(int(row["iris_tube_result_id"]) for row in candidates)
        representatives.append(chosen)
    return representatives


def cohort_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    materialized = list(rows)
    dates_by_tube: dict[Any, set[str]] = defaultdict(set)
    for row in materialized:
        dates_by_tube[row["tube_id"]].add(str(row["inspection_date"])[:10])
    return {
        "A": len(materialized),
        "B_tubes": sum(len(dates) >= 2 for dates in dates_by_tube.values()),
        "C_tubes": sum(len(dates) >= 3 for dates in dates_by_tube.values()),
    }


def assert_no_group_leakage(train: Iterable[dict[str, Any]], validation: Iterable[dict[str, Any]]) -> None:
    train_rows, validation_rows = list(train), list(validation)
    for field in ("tube_id", "heat_exchanger_id"):
        overlap = {row[field] for row in train_rows} & {row[field] for row in validation_rows}
        if overlap:
            raise ValueError(f"Data leakage: {field} appears in both splits")
    if any(_as_datetime(row["inspection_date"]) >= _as_datetime(row["target_date"]) for row in train_rows if row.get("target_date")):
        raise ValueError("Future/current inspection information leaked into training features")


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
