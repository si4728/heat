"""Read-only inspection-priority adapter for DB-confirmed Hotspot reviews."""

from __future__ import annotations

from iris2 import dbapi as db
from pathlib import Path
from typing import Any


def confirmed_hotspot_priorities(
    database_path: str | Path,
    review_database_path: str | Path,
    *,
    heat_exchanger_id: int | None = None,
) -> dict[str, Any]:
    review_database = Path(review_database_path).resolve()
    empty = {
        "enabled": False,
        "run_id": None,
        "priority": "NORMAL",
        "confirmed_count": 0,
        "candidate_tube_count": 0,
        "in_service_count": 0,
        "maximum_wall_loss_percent": None,
        "rows": [],
        "automatic_plan_creation_enabled": False,
        "automatic_engineering_decision_enabled": False,
    }
    if not db.exists(review_database):
        return empty
    review = db.connect(review_database.resolve().as_uri() + "?mode=ro", uri=True)
    review.row_factory = db.Row
    try:
        table = review.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='ml_hotspot_review_feedback'"
        ).fetchone()
        if not table:
            return empty
        latest = review.execute(
            "SELECT run_id FROM ml_hotspot_review_feedback ORDER BY hotspot_feedback_id DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return empty
        run_id = str(latest["run_id"])
        feedback = [dict(row) for row in review.execute(
            """SELECT * FROM ml_hotspot_review_feedback
                 WHERE run_id=? AND confirmation_status='CONFIRMED'
                 ORDER BY hotspot_score DESC, hotspot_feedback_id""",
            (run_id,),
        )]
    finally:
        review.close()
    if not feedback:
        return empty

    ids = [int(row["iris_tube_result_id"]) for row in feedback]
    placeholders = ",".join("?" for _ in ids)
    operational = db.connect(Path(database_path).resolve().as_uri() + "?mode=ro", uri=True)
    operational.row_factory = db.Row
    try:
        sql = f"""
            SELECT result.iris_tube_result_id,result.iris_inspection_id,result.tube_id,
                   result.wall_loss_percent,result.minimum_wall_thickness_mm,
                   inspection.heat_exchanger_id,inspection.inspection_date,
                   tube.tube_no,tube.row_no,tube.column_no,tube.current_status,
                   equipment.equipment_code,equipment.equipment_name,
                   unit.unit_code,plant.plant_code
              FROM iris_tube_result result
              JOIN iris_inspection inspection ON inspection.iris_inspection_id=result.iris_inspection_id
              JOIN heat_exchanger_tube tube ON tube.tube_id=result.tube_id
              JOIN heat_exchanger exchanger ON exchanger.heat_exchanger_id=inspection.heat_exchanger_id
              JOIN equipment equipment ON equipment.equipment_id=exchanger.equipment_id
              JOIN process_unit unit ON unit.unit_id=equipment.unit_id
              JOIN plant plant ON plant.plant_id=unit.plant_id
             WHERE result.iris_tube_result_id IN ({placeholders})
        """
        parameters: list[Any] = list(ids)
        if heat_exchanger_id is not None:
            sql += " AND inspection.heat_exchanger_id=?"
            parameters.append(int(heat_exchanger_id))
        source_rows = [dict(row) for row in operational.execute(sql, parameters)]
    finally:
        operational.close()

    feedback_by_result = {int(row["iris_tube_result_id"]): row for row in feedback}
    evidence_rows = []
    for row in source_rows:
        evidence = feedback_by_result[int(row["iris_tube_result_id"])]
        wall_loss = float(row["wall_loss_percent"] or 0.0)
        priority = "URGENT" if wall_loss >= 40.0 else "HIGH"
        evidence_rows.append({
            **row,
            "priority": priority,
            "priority_score": round(float(evidence["hotspot_score"]) + wall_loss, 6),
            "hotspot_score": float(evidence["hotspot_score"]),
            "confidence": evidence["confidence"],
            "confirmation_status": evidence["confirmation_status"],
            "pdf_source_file": evidence["pdf_source_file"],
            "pdf_source_page": int(evidence["pdf_source_page"]),
            "reason": "PDF·IRIS 원시자료와 승인 Layout이 일치한 Hotspot",
            "is_in_service": str(row["current_status"] or "").upper() in {"ACTIVE", "IN_SERVICE"},
        })
    by_tube: dict[int, dict[str, Any]] = {}
    for row in evidence_rows:
        tube_id = int(row["tube_id"])
        current = by_tube.get(tube_id)
        if current is None or (row["priority_score"], str(row["inspection_date"])) > (
            current["priority_score"], str(current["inspection_date"])
        ):
            by_tube[tube_id] = row
    rows = list(by_tube.values())
    rows.sort(key=lambda row: (0 if row["priority"] == "URGENT" else 1, -row["priority_score"], int(row["tube_id"])))
    levels = {row["priority"] for row in rows}
    overall = "URGENT" if "URGENT" in levels else "HIGH" if rows else "NORMAL"
    return {
        **empty,
        "enabled": bool(rows),
        "run_id": run_id,
        "priority": overall,
        "confirmed_count": len(evidence_rows),
        "candidate_tube_count": len(rows),
        "in_service_count": sum(row["is_in_service"] for row in rows),
        "maximum_wall_loss_percent": max((float(row["wall_loss_percent"]) for row in rows), default=None),
        "rows": rows,
    }
