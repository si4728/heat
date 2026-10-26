"""Approved-layout-only spatial corrosion hotspot pilot."""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from .readonly_db import readonly_connection


MODEL_VERSION = "spatial-hotspot-knn-1.0"
K_NEIGHBORS = 6
HOTSPOT_THRESHOLD = 2.0


def transform_point(
    x: float,
    y: float,
    *,
    rotation_degrees: float = 0.0,
    flip_x: bool = False,
    flip_y: bool = False,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[float, float]:
    """Apply the documented layout transform in flip/scale/rotate/offset order."""

    transformed_x = (-float(x) if flip_x else float(x)) * float(scale_x)
    transformed_y = (-float(y) if flip_y else float(y)) * float(scale_y)
    angle = math.radians(float(rotation_degrees))
    rotated_x = transformed_x * math.cos(angle) - transformed_y * math.sin(angle)
    rotated_y = transformed_x * math.sin(angle) + transformed_y * math.cos(angle)
    return rotated_x + float(offset_x), rotated_y + float(offset_y)


SPATIAL_ROWS_SQL = """
WITH approved_revision AS (
    SELECT revision.*,
           ROW_NUMBER() OVER (
               PARTITION BY revision.bundle_id
               ORDER BY COALESCE(revision.approved_at, revision.created_at) DESC,
                        revision.layout_revision_id DESC
           ) AS revision_rank
      FROM tube_layout_revision revision
     WHERE revision.revision_status = 'APPROVED'
), approved_point AS (
    SELECT revision.layout_revision_id, revision.bundle_id,
           point.layout_point_id, point.tube_id,
           point.canonical_x, point.canonical_y,
           point.source_row, point.source_column,
           revision.revision_status, point.verification_status, point.mapping_status
      FROM approved_revision revision
      JOIN tube_layout_point point
        ON point.layout_revision_id = revision.layout_revision_id
     WHERE revision.revision_rank = 1
       AND point.verification_status = 'VERIFIED'
       AND point.mapping_status = 'EXISTING_TUBE_MATCH'
       AND point.tube_id IS NOT NULL
       AND point.canonical_x IS NOT NULL
       AND point.canonical_y IS NOT NULL
), ranked_result AS (
    SELECT point.*,
           plant.plant_id, unit.unit_id, inspection.heat_exchanger_id,
           plant.plant_code, unit.unit_code, equipment.equipment_code,
           tube.tube_no, tube.row_no, tube.column_no,
           result.iris_tube_result_id, inspection.iris_inspection_id,
           inspection.source_document_id, result.source_page,
           YEAR(COALESCE(inspection.inspection_date, inspection.report_date)) AS inspection_year,
           COALESCE(inspection.inspection_date, inspection.report_date) AS inspection_date,
           result.wall_loss_percent, result.minimum_wall_thickness_mm,
           ROW_NUMBER() OVER (
               PARTITION BY point.layout_revision_id, point.tube_id,
                            YEAR(COALESCE(inspection.inspection_date, inspection.report_date))
               ORDER BY result.wall_loss_percent DESC,
                        result.minimum_wall_thickness_mm ASC,
                        result.iris_tube_result_id ASC
           ) AS result_rank
      FROM approved_point point
      JOIN heat_exchanger_tube tube ON tube.tube_id = point.tube_id
      JOIN iris_tube_result result ON result.tube_id = point.tube_id
      JOIN iris_inspection inspection
        ON inspection.iris_inspection_id = result.iris_inspection_id
       AND inspection.bundle_id = point.bundle_id
      JOIN heat_exchanger exchanger ON exchanger.heat_exchanger_id = inspection.heat_exchanger_id
      JOIN equipment equipment ON equipment.equipment_id = exchanger.equipment_id
      JOIN process_unit unit ON unit.unit_id = equipment.unit_id
      JOIN plant plant ON plant.plant_id = unit.plant_id
     WHERE result.wall_loss_percent IS NOT NULL
)
SELECT * FROM ranked_result WHERE result_rank = 1
ORDER BY layout_revision_id, inspection_year, tube_id
"""


def load_spatial_rows(database_path: str | Path) -> list[dict[str, Any]]:
    with readonly_connection(database_path) as connection:
        rows = [dict(row) for row in connection.execute(SPATIAL_ROWS_SQL)]
    validate_approved_rows(rows)
    return rows


def validate_approved_rows(rows: Iterable[dict[str, Any]]) -> None:
    for index, row in enumerate(rows):
        if row.get("revision_status") != "APPROVED":
            raise ValueError(f"Unapproved layout at row {index}")
        if row.get("verification_status") != "VERIFIED":
            raise ValueError(f"Unverified layout point at row {index}")
        if row.get("mapping_status") != "EXISTING_TUBE_MATCH":
            raise ValueError(f"Unresolved tube mapping at row {index}")
        if row.get("canonical_x") is None or row.get("canonical_y") is None:
            raise ValueError(f"Missing canonical coordinate at row {index}")


def _weighted_median(values_and_weights: list[tuple[float, float]]) -> float:
    ordered = sorted(values_and_weights)
    threshold = sum(weight for _, weight in ordered) / 2.0
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return ordered[-1][0]


def score_spatial_hotspots(rows: Iterable[dict[str, Any]], *, neighbors: int = K_NEIGHBORS) -> list[dict[str, Any]]:
    if neighbors < 2:
        raise ValueError("At least two spatial neighbors are required")
    materialized = [dict(row) for row in rows]
    validate_approved_rows(materialized)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in materialized:
        grouped[(int(row["layout_revision_id"]), int(row["inspection_year"]))].append(row)

    scored: list[dict[str, Any]] = []
    for group_rows in grouped.values():
        losses = [float(row["wall_loss_percent"]) for row in group_rows]
        center = median(losses)
        mad = median(abs(value - center) for value in losses)
        robust_scale = max(1.4826 * mad, 1.0)
        for row in group_rows:
            distances: list[tuple[float, dict[str, Any]]] = []
            for candidate in group_rows:
                if candidate["tube_id"] == row["tube_id"]:
                    continue
                distance = math.hypot(
                    float(candidate["canonical_x"]) - float(row["canonical_x"]),
                    float(candidate["canonical_y"]) - float(row["canonical_y"]),
                )
                if distance > 0:
                    distances.append((distance, candidate))
            nearest = sorted(distances, key=lambda item: (item[0], int(item[1]["tube_id"])))[:neighbors]
            result = dict(row)
            result["neighbor_count"] = len(nearest)
            if len(nearest) < 2:
                result.update(spatial_status="INSUFFICIENT_NEIGHBORS", neighbor_weighted_median=None, spatial_residual_pp=None, local_moran_i=None, hotspot_score=None, evidence_tubes=[])
            else:
                weighted = [(float(candidate["wall_loss_percent"]), 1.0 / distance) for distance, candidate in nearest]
                neighbor_median = _weighted_median(weighted)
                self_z = (float(row["wall_loss_percent"]) - center) / robust_scale
                total_weight = sum(1.0 / distance for distance, _ in nearest)
                neighbor_z = sum(((float(candidate["wall_loss_percent"]) - center) / robust_scale) / distance for distance, candidate in nearest) / total_weight
                local_moran = self_z * neighbor_z
                residual = float(row["wall_loss_percent"]) - neighbor_median
                score = max(0.0, self_z) * (1.0 + max(0.0, neighbor_z)) + max(0.0, residual) / robust_scale
                result.update(
                    spatial_status="SCORED", neighbor_weighted_median=neighbor_median,
                    spatial_residual_pp=residual, local_moran_i=local_moran,
                    hotspot_score=score,
                    evidence_tubes=[{
                        "tube_id": candidate["tube_id"], "tube_no": candidate.get("tube_no"),
                        "distance": distance, "wall_loss_percent": candidate["wall_loss_percent"],
                    } for distance, candidate in nearest],
                )
            scored.append(result)
    _assign_change_states(scored)
    return scored


def _assign_change_states(rows: list[dict[str, Any]]) -> None:
    histories: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        histories[(int(row["bundle_id"]), int(row["tube_id"]))].append(row)
    for history in histories.values():
        history.sort(key=lambda row: int(row["inspection_year"]))
        previous_hotspot = False
        for row in history:
            current_hotspot = row.get("hotspot_score") is not None and float(row["hotspot_score"]) >= HOTSPOT_THRESHOLD
            if current_hotspot:
                row["change_state"] = "PERSISTING" if previous_hotspot else "NEW"
            elif previous_hotspot:
                row["change_state"] = "DECREASED"
            else:
                row["change_state"] = "NONE"
            previous_hotspot = current_hotspot


def run_spatial_pilot(database_path: str | Path) -> dict[str, Any]:
    rows = load_spatial_rows(database_path)
    scored = score_spatial_hotspots(rows)
    candidates = [row for row in scored if row.get("hotspot_score") is not None]
    candidates.sort(key=lambda row: (-float(row["hotspot_score"]), -float(row["wall_loss_percent"]), int(row["tube_id"])))
    unapproved = sum(row.get("revision_status") != "APPROVED" for row in rows)
    invalid_coordinates = sum(row.get("canonical_x") is None or row.get("canonical_y") is None for row in rows)
    missing_evidence = sum(not row.get("evidence_tubes") for row in candidates[:30])
    gates = {
        "unapproved_layout_rows_zero": unapproved == 0,
        "coordinate_errors_zero": invalid_coordinates == 0,
        "top30_evidence_complete": missing_evidence == 0,
        "expert_top30_confirmation_ge_60_percent": False,
    }
    safety_gates = all(value for key, value in gates.items() if key != "expert_top30_confirmation_ge_60_percent")
    return {
        "status": "PASS_WITH_NOTE" if safety_gates else "HOLD",
        "model_version": MODEL_VERSION,
        "row_count": len(rows),
        "scored_count": len(candidates),
        "layout_revision_count": len({row["layout_revision_id"] for row in rows}),
        "equipment_count": len({row["heat_exchanger_id"] for row in rows}),
        "gates": gates,
        "confirmed_risk_grade_enabled": False,
        "note": "Expert hotspot labels are unavailable; candidates are report-only.",
        "top_30": candidates[:30],
    }
