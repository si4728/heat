from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


EXPECTED = {
    103: (46, 92),
    155: (393, 786),
    160: (393, 786),
    243: (393, 786),
    202: (80, 160),
}


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace.parent))
    from iris2 import services

    errors: list[str] = []
    checks = []
    for exchanger_id, (physical_count, point_count) in EXPECTED.items():
        payload = services.tube_map_data(exchanger_id)
        layout = payload["layout"]
        summary = payload["summary"]
        approved_points = sum(
            tube.get("coordinate_source") == "APPROVED_LAYOUT" for tube in payload["tubes"]
        )
        linked = [
            tube for tube in payload["tubes"]
            if tube.get("tube_id") is not None and tube.get("coordinate_source") == "APPROVED_LAYOUT"
        ]
        actual = {
            "physical_tube_count": layout["physical_tube_count"],
            "layout_point_count": layout["layout_point_count"],
            "count_basis": layout["count_basis"],
            "coverage_status": layout["coverage_status"],
            "summary_expected_tube_count": summary["expected_tube_count"],
            "display_position_count": summary["display_position_count"],
            "approved_points": approved_points,
            "unmapped_expected_count": summary["unmapped_expected_count"],
        }
        wanted = {
            "physical_tube_count": physical_count,
            "layout_point_count": point_count,
            "count_basis": "TUBE_END",
            "coverage_status": "FULL",
            "summary_expected_tube_count": physical_count,
            "display_position_count": point_count,
            "approved_points": point_count,
            "unmapped_expected_count": 0,
        }
        if not layout["approved_layout_applied"] or layout["shape"] != "SOURCE_LAYOUT_GRID":
            errors.append(f"exchanger {exchanger_id}: approved source grid is not active")
        if layout["initial_rotation_degrees"] != 0:
            errors.append(f"exchanger {exchanger_id}: rotation is not zero")
        if actual != wanted:
            errors.append(f"exchanger {exchanger_id}: {actual} != {wanted}")
        if any(not tube.get("position_locked") for tube in linked):
            errors.append(f"exchanger {exchanger_id}: an approved linked point is editable")
        checks.append({"heat_exchanger_id": exchanger_id, **actual})

    connection = sqlite3.connect(
        (workspace / "data" / "heat_exchanger_db3.db").resolve().as_uri() + "?mode=ro", uri=True
    )
    approved_count = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
    ).fetchone()[0]
    draft_count = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE revision_status='DRAFT'"
    ).fetchone()[0]
    verified_points = connection.execute(
        "SELECT count(*) FROM tube_layout_point WHERE verification_status='VERIFIED'"
    ).fetchone()[0]
    pending_points = connection.execute(
        "SELECT count(*) FROM tube_layout_point WHERE verification_status='PENDING'"
    ).fetchone()[0]
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    expected_state = (60, 3, 23324, 687)
    if (approved_count, draft_count, verified_points, pending_points) != expected_state:
        errors.append(
            f"global state mismatch: {(approved_count, draft_count, verified_points, pending_points)} != {expected_state}"
        )
    if quick_check != "ok" or foreign_key_issues:
        errors.append("database integrity validation failed")
    result = {
        "status": "PASS" if not errors else "FAIL",
        "service_checks": checks,
        "approved_revision_count": approved_count,
        "draft_revision_count": draft_count,
        "verified_point_count": verified_points,
        "pending_point_count": pending_points,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "errors": errors,
        "database_mode": "READ_ONLY",
        "database_changes": 0,
    }
    output = workspace / "outputs" / "tube_layout_review_20260908" / "ubend_operational_verification.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
