from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace.parent))
    from iris2 import services

    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    applied = json.loads((review_dir / "ubend_draft_apply_result.json").read_text(encoding="utf-8"))
    ids = [int(value) for value in applied["inserted_revision_ids"]]
    placeholders = ",".join("?" for _ in ids)
    connection = sqlite3.connect(
        (workspace / "data" / "heat_exchanger_db3.db").resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    revisions = connection.execute(
        f"""SELECT r.*, b.heat_exchanger_id, count(p.layout_point_id) AS actual_points,
                   sum(p.verification_status='PENDING') AS pending_points,
                   sum(p.canonical_x IS NOT NULL OR p.canonical_y IS NOT NULL) AS canonical_set
            FROM tube_layout_revision r
            JOIN tube_layout_point p ON p.layout_revision_id=r.layout_revision_id
            JOIN tube_bundle b ON b.bundle_id=r.bundle_id
            WHERE r.layout_revision_id IN ({placeholders})
            GROUP BY r.layout_revision_id""",
        ids,
    ).fetchall()
    errors: list[str] = []
    service_checks = []
    for row in revisions:
        if row["revision_status"] != "DRAFT":
            errors.append(f"revision {row['layout_revision_id']}: not DRAFT")
        if row["layout_count_basis"] != "TUBE_END" or row["coverage_status"] != "FULL":
            errors.append(f"revision {row['layout_revision_id']}: count semantics mismatch")
        if int(row["layout_point_count"]) != 2 * int(row["physical_tube_count"]):
            errors.append(f"revision {row['layout_revision_id']}: not a 2:1 end/tube ratio")
        if int(row["actual_points"]) != int(row["layout_point_count"]):
            errors.append(f"revision {row['layout_revision_id']}: point count mismatch")
        if int(row["pending_points"]) != int(row["actual_points"]) or int(row["canonical_set"]):
            errors.append(f"revision {row['layout_revision_id']}: point state mismatch")
        payload = services.tube_map_data(int(row["heat_exchanger_id"]))
        if payload["layout"]["approved_layout_applied"]:
            errors.append(f"revision {row['layout_revision_id']}: DRAFT leaked into operational service")
        service_checks.append({
            "layout_revision_id": row["layout_revision_id"],
            "heat_exchanger_id": row["heat_exchanger_id"],
            "physical_tube_count": row["physical_tube_count"],
            "layout_point_count": row["layout_point_count"],
            "operational_layout_applied": payload["layout"]["approved_layout_applied"],
            "operational_shape": payload["layout"]["shape"],
        })
    approved_count = connection.execute(
        "SELECT count(*) FROM tube_layout_revision WHERE revision_status='APPROVED'"
    ).fetchone()[0]
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    foreign_key_issues = len(connection.execute("PRAGMA foreign_key_check").fetchall())
    connection.close()
    if approved_count != 55:
        errors.append(f"approved revision count changed: {approved_count}")
    if quick_check != "ok" or foreign_key_issues:
        errors.append("database integrity check failed")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "revision_count": len(revisions),
        "point_count": sum(int(row["actual_points"]) for row in revisions),
        "approved_revision_count": approved_count,
        "service_checks": service_checks,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_issues,
        "errors": errors,
        "database_mode": "READ_ONLY",
        "database_changes": 0,
    }
    (review_dir / "ubend_draft_verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
