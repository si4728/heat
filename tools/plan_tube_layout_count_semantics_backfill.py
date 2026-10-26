from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from classify_tube_layout_rollout import choose_report, report_index


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    source_rows = {
        row["source_path"]: row
        for row in read_csv(review_dir / "rollout_candidate_classification.csv")
    }
    reports = report_index(workspace)
    connection = sqlite3.connect(
        (workspace / "data" / "heat_exchanger_db3.db").resolve().as_uri() + "?mode=ro", uri=True
    )
    connection.row_factory = sqlite3.Row
    db_rows = connection.execute(
        """SELECT r.layout_revision_id, r.source_path, r.revision_status,
                  count(p.layout_point_id) AS point_count
           FROM tube_layout_revision r
           JOIN tube_layout_point p ON p.layout_revision_id=r.layout_revision_id
           GROUP BY r.layout_revision_id ORDER BY r.layout_revision_id"""
    ).fetchall()
    connection.close()

    proposals = []
    for db_row in db_rows:
        source = source_rows[str(db_row["source_path"])]
        unit = source["unit"]
        equipment = source["equipment_code"]
        report, error = choose_report(
            reports, unit, equipment, source["scope_code"], source["bundle_code"]
        )
        if error or report is None:
            raise RuntimeError(f"Report resolution failed for {db_row['source_path']}: {error}")
        details = report["report"]
        tube_type = str(
            details.get("iris_report_details", {}).get("basic_information", {}).get("tube_type")
            or "UNKNOWN"
        ).upper()
        physical_count = int(source["report_total_tube_count"])
        point_count = int(db_row["point_count"])
        discrepancy = ""
        if tube_type == "STRAIGHT" and point_count == physical_count:
            basis = "PHYSICAL_TUBE"
            coverage = "FULL"
            unresolved = 0
        elif tube_type == "U-BEND" and point_count == 2 * physical_count:
            basis = "TUBE_END"
            coverage = "FULL"
            unresolved = 0
        elif tube_type == "U-BEND" and point_count == physical_count:
            basis = "UNKNOWN"
            coverage = "UNKNOWN"
            unresolved = 0
            discrepancy = "Counts agree, but the source does not prove whether U-Bend points represent tubes or ends."
        else:
            basis = "UNKNOWN"
            coverage = "CONFLICT"
            unresolved = abs(point_count - physical_count)
            discrepancy = (
                f"Layout points={point_count}, report physical tubes={physical_count}; engineering review required."
            )
        if source["reasons"]:
            coverage = "CONFLICT"
            discrepancy = "; ".join(filter(None, [source["reasons"], discrepancy]))

        proposals.append({
            "layout_revision_id": int(db_row["layout_revision_id"]),
            "revision_status": db_row["revision_status"],
            "unit": unit,
            "equipment_code": equipment,
            "tube_type": tube_type,
            "physical_tube_count": physical_count,
            "layout_point_count": point_count,
            "layout_count_basis": basis,
            "coverage_status": coverage,
            "unresolved_count": unresolved,
            "count_discrepancy_note": discrepancy,
            "source_path": db_row["source_path"],
        })

    output_csv = review_dir / "count_semantics_backfill_plan.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(proposals[0]))
        writer.writeheader()
        writer.writerows(proposals)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_mode": "READ_ONLY",
        "database_changes": 0,
        "revision_count": len(proposals),
        "basis_counts": dict(sorted(Counter(row["layout_count_basis"] for row in proposals).items())),
        "coverage_counts": dict(sorted(Counter(row["coverage_status"] for row in proposals).items())),
        "status_counts": dict(sorted(Counter(row["revision_status"] for row in proposals).items())),
        "approval_required_before_database_apply": True,
    }
    (review_dir / "count_semantics_backfill_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
