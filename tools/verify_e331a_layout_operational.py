from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace.parent))
    from iris2 import services

    db_path = workspace / "data" / "heat_exchanger_db3.db"
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """SELECT r.layout_revision_id, r.revision_status, r.bundle_id, b.heat_exchanger_id,
                  count(p.layout_point_id) AS point_count,
                  sum(p.verification_status='VERIFIED') AS verified,
                  sum(p.canonical_x=p.source_x AND p.canonical_y=p.source_y) AS canonical_match
           FROM tube_layout_revision r
           JOIN tube_layout_point p ON p.layout_revision_id=r.layout_revision_id
           JOIN tube_bundle b ON b.bundle_id=r.bundle_id
           WHERE r.layout_revision_id IN (3, 4)
           GROUP BY r.layout_revision_id, b.heat_exchanger_id
           ORDER BY r.layout_revision_id"""
    ).fetchall()
    statuses = {int(row["layout_revision_id"]): row["revision_status"] for row in rows}
    exchanger_id = int(rows[0]["heat_exchanger_id"])
    payload = services.tube_map_data(exchanger_id)
    layout = payload["layout"]
    summary = payload["summary"]
    approved_points = [
        tube for tube in payload["tubes"] if tube.get("coordinate_source") == "APPROVED_LAYOUT"
    ]
    linked_points = [tube for tube in approved_points if tube.get("tube_id") is not None]
    errors: list[str] = []
    if statuses != {3: "REJECTED", 4: "APPROVED"}:
        errors.append(f"revision status mismatch: {statuses}")
    canonical = next(row for row in rows if int(row["layout_revision_id"]) == 4)
    if int(canonical["point_count"]) != 20 or int(canonical["verified"]) != 20 or int(canonical["canonical_match"]) != 20:
        errors.append("canonical revision point state mismatch")
    if not layout["approved_layout_applied"] or layout["shape"] != "SOURCE_LAYOUT_GRID":
        errors.append("approved source grid is not active")
    if layout["initial_rotation_degrees"] != 0:
        errors.append("initial rotation is not zero")
    if len(approved_points) != 20:
        errors.append(f"served approved points mismatch: {len(approved_points)}")
    if len(linked_points) != 8:
        errors.append(f"served linked points mismatch: {len(linked_points)}")
    if summary["unmapped_expected_count"] != 0 or summary["unlinked_layout_count"] != 12:
        errors.append("estimated/unlinked count mismatch")
    if any(not tube.get("position_locked") for tube in linked_points):
        errors.append("an approved linked point remains editable")
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    if quick_check != "ok" or foreign_key_issues:
        errors.append("database integrity validation failed")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "equipment": "E-331A",
        "canonical_revision_id": 4,
        "duplicate_revision_id": 3,
        "revision_statuses": statuses,
        "served_approved_points": len(approved_points),
        "served_linked_points": len(linked_points),
        "served_unlinked_points": summary["unlinked_layout_count"],
        "estimated_positions": summary["unmapped_expected_count"],
        "shape": layout["shape"],
        "initial_rotation_degrees": layout["initial_rotation_degrees"],
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "errors": errors,
        "database_mode": "READ_ONLY",
        "database_changes": 0,
    }
    output = workspace / "outputs" / "tube_layout_review_20260908" / "e331a_operational_verification.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
