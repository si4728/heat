from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only service verification for approved Tube Layouts.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--unit", choices=("VCM1", "VCM2"), required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    sys.path.insert(0, str(workspace.parent))
    from iris2 import services

    approval = json.loads(
        (workspace / "outputs" / "tube_layout_review_20260908" / f"{args.unit.lower()}_operational_approval_result.json")
        .read_text(encoding="utf-8")
    )
    ids = [int(value) for value in approval["revision_ids"]]
    connection = sqlite3.connect(
        (workspace / "data" / "heat_exchanger_db3.db").resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in ids)
    rows = connection.execute(
        f"""SELECT r.layout_revision_id, r.revision_status, r.bundle_id, b.heat_exchanger_id,
                   count(p.layout_point_id) AS point_count,
                   sum(p.verification_status='VERIFIED') AS verified,
                   sum(p.canonical_x=p.source_x AND p.canonical_y=p.source_y) AS canonical_match
            FROM tube_layout_revision r
            JOIN tube_layout_point p ON p.layout_revision_id=r.layout_revision_id
            JOIN tube_bundle b ON b.bundle_id=r.bundle_id
            WHERE r.layout_revision_id IN ({placeholders})
            GROUP BY r.layout_revision_id, b.heat_exchanger_id""",
        ids,
    ).fetchall()
    expected_by_exchanger: dict[int, int] = {}
    errors: list[str] = []
    for row in rows:
        count = int(row["point_count"])
        expected_by_exchanger[int(row["heat_exchanger_id"])] = (
            expected_by_exchanger.get(int(row["heat_exchanger_id"]), 0) + count
        )
        if row["revision_status"] != "APPROVED" or int(row["verified"]) != count or int(row["canonical_match"]) != count:
            errors.append(f"revision {row['layout_revision_id']} database state mismatch")

    payloads = []
    for exchanger_id, expected_points in sorted(expected_by_exchanger.items()):
        payload = services.tube_map_data(exchanger_id)
        if not payload:
            errors.append(f"exchanger {exchanger_id}: service returned no data")
            continue
        layout = payload["layout"]
        summary = payload["summary"]
        actual_points = sum(
            1 for tube in payload["tubes"] if tube.get("coordinate_source") == "APPROVED_LAYOUT"
        )
        if not layout["approved_layout_applied"] or layout["shape"] != "SOURCE_LAYOUT_GRID":
            errors.append(f"exchanger {exchanger_id}: approved source grid not active")
        if layout["initial_rotation_degrees"] != 0:
            errors.append(f"exchanger {exchanger_id}: rotation is not zero")
        if summary["unmapped_expected_count"] != 0:
            errors.append(f"exchanger {exchanger_id}: estimated positions remain")
        if actual_points < expected_points:
            errors.append(f"exchanger {exchanger_id}: only {actual_points}/{expected_points} approved points served")
        linked = [tube for tube in payload["tubes"] if tube.get("tube_id") is not None and tube.get("coordinate_source") == "APPROVED_LAYOUT"]
        if any(not tube.get("position_locked") for tube in linked):
            errors.append(f"exchanger {exchanger_id}: an approved linked point is editable")
        payloads.append({
            "heat_exchanger_id": exchanger_id,
            "expected_new_points": expected_points,
            "served_approved_points": actual_points,
            "display_tube_count": summary["display_tube_count"],
            "unlinked_layout_count": summary["unlinked_layout_count"],
        })
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    if quick_check != "ok" or foreign_key_issues:
        errors.append("database integrity validation failed")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "unit": args.unit,
        "revision_count": len(rows),
        "exchanger_count": len(expected_by_exchanger),
        "service_checks": payloads,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "errors": errors,
        "database_mode": "READ_ONLY",
        "database_changes": 0,
    }
    output = workspace / "outputs" / "tube_layout_review_20260908" / f"{args.unit.lower()}_operational_verification.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
