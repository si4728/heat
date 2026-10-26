from __future__ import annotations

import csv
import glob
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from classify_tube_layout_rollout import choose_report, report_index


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def historical_counts(workspace: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    pattern = str(workspace / "data" / "*IRIS2_all_tube_results.json")
    for filename in glob.glob(pattern):
        match = re.search(r"(20\d{2})(VCM[12])", os.path.basename(filename))
        if not match:
            continue
        year, unit = int(match.group(1)), match.group(2)
        payload = json.loads(Path(filename).read_text(encoding="utf-8"))
        for report in payload.get("inspection_reports", []):
            details = report.get("report", {})
            equipment = str(details.get("equipment_id") or "").upper()
            scope = details.get("inspection_scope")
            scope_code = str(scope.get("scope_code") or "ALL").upper() if isinstance(scope, dict) else "ALL"
            result[(unit, equipment)].append({
                "year": year,
                "scope": scope_code,
                "count": details.get("inspection_summary", {}).get("total_tube_count"),
            })
    return result


def main() -> int:
    workspace = Path(__file__).resolve().parents[1]
    review_dir = workspace / "outputs" / "tube_layout_review_20260908"
    rows = [
        row for row in read_csv(review_dir / "rollout_candidate_classification.csv")
        if row["classification"] == "REVIEW_REQUIRED"
    ]
    reports = report_index(workspace)
    history = historical_counts(workspace)
    diagnosed: list[dict[str, Any]] = []

    for row in rows:
        unit = row["unit"]
        equipment = row["equipment_code"]
        bundle_code = row["bundle_code"]
        report, error = choose_report(reports, unit, equipment, row["scope_code"], bundle_code)
        if error or report is None:
            raise RuntimeError(f"Unable to resolve 2025 report for {unit} {equipment}: {error}")
        details = report["report"]
        basic = details.get("iris_report_details", {}).get("basic_information", {})
        tube_type = str(basic.get("tube_type") or "UNKNOWN").upper()
        source_count = int(row["source_tube_count"])
        master_count = int(row["master_expected_tube_count"])
        report_count = int(row["report_total_tube_count"])
        map_count = int(row["map_total_tube_count"])
        prior = sorted(
            [
                item for item in history[(unit, equipment)]
                if item["year"] < 2025 and item["count"] is not None
            ],
            key=lambda item: (item["year"], item["scope"]),
        )
        prior_counts = [int(item["count"]) for item in prior]

        if tube_type == "U-BEND" and source_count == map_count and (
            source_count == 2 * report_count or master_count == 2 * report_count
        ):
            category = "U_BEND_TUBE_END_COUNT_BASIS"
            confidence = "HIGH"
            recommendation = (
                "Store physical-tube count and layout-point count separately; mark layout points as TUBE_END. "
                "Approve only after the UI stops labeling every layout point as a physical tube."
            )
        elif equipment == "E-103":
            category = "THREE_WAY_COUNT_CONFLICT"
            confidence = "HIGH"
            recommendation = (
                "Manual engineering review required: source/map=32, report=38 and master=160. "
                "Confirm the active bundle/replacement configuration before any approval."
            )
        elif source_count in prior_counts and source_count == map_count:
            category = "CURRENT_REPORT_OR_MASTER_CHANGED_FROM_HISTORICAL_LAYOUT"
            confidence = "MEDIUM"
            recommendation = (
                "Confirm whether the bundle was replaced or its inspection scope changed in 2025. "
                "If not, correct the report/master count provenance before approving the historical layout."
            )
        else:
            category = "UNRESOLVED_LAYOUT_COUNT_CONFLICT"
            confidence = "LOW"
            recommendation = "Compare the physical Tube Sheet drawing and 2025 field record before approval."

        source_issues = report.get("validation", {}).get("source_pdf_inconsistencies", [])
        count_issue_documented = any(
            "배열도 범례 합계" in str(issue.get("description") or "")
            for issue in source_issues if isinstance(issue, dict)
        )
        diagnosed.append({
            "category": category,
            "confidence": confidence,
            "unit": unit,
            "equipment_code": equipment,
            "bundle_id": int(row["bundle_id"]),
            "tube_type": tube_type,
            "source_mdb_points": source_count,
            "map_points": map_count,
            "report_total": report_count,
            "master_expected": master_count,
            "prior_year_counts": ";".join(
                f"{item['year']}:{item['count']}[{item['scope']}]" for item in prior
            ),
            "source_count_issue_documented": "YES" if count_issue_documented else "NO",
            "recommendation": recommendation,
            "source_path": row["source_path"],
        })

    output_csv = review_dir / "mismatch_diagnosis.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(diagnosed[0]))
        writer.writeheader()
        writer.writerows(diagnosed)

    categories = Counter(row["category"] for row in diagnosed)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_mode": "READ_ONLY",
        "database_changes": 0,
        "review_required_count": len(diagnosed),
        "category_counts": dict(sorted(categories.items())),
        "recommended_schema_fields": [
            "physical_tube_count", "layout_point_count", "layout_count_basis",
            "coverage_status", "unresolved_count", "count_discrepancy_note",
        ],
        "approval_required_before_database_apply": True,
    }
    (review_dir / "mismatch_diagnosis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        "# Tube Layout mismatch diagnosis",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "This analysis is read-only. No database records were inserted or updated.",
        "",
        "## Classification",
        "",
        "| Category | Count | Operational decision |",
        "|---|---:|---|",
        f"| U-Bend tube-end count basis | {categories['U_BEND_TUBE_END_COUNT_BASIS']} | Schema/UI semantics must be added before approval |",
        f"| 2025 report/master differs from historical layout | {categories['CURRENT_REPORT_OR_MASTER_CHANGED_FROM_HISTORICAL_LAYOUT']} | Confirm replacement/scope history |",
        f"| Three-way count conflict | {categories['THREE_WAY_COUNT_CONFLICT']} | Manual engineering review |",
        f"| Other unresolved | {categories['UNRESOLVED_LAYOUT_COUNT_CONFLICT']} | Physical drawing review |",
        "",
        "## Equipment detail",
        "",
        "| Equipment | Type | MDB/Map/Report/Master | Historical totals | Category |",
        "|---|---|---|---|---|",
    ]
    for item in diagnosed:
        totals = "/".join(str(item[key]) for key in (
            "source_mdb_points", "map_points", "report_total", "master_expected"
        ))
        lines.append(
            f"| {item['unit']} {item['equipment_code']} | {item['tube_type']} | {totals} | "
            f"{item['prior_year_counts']} | {item['category']} |"
        )
    lines.extend([
        "",
        "## Improvement required before the next approval",
        "",
        "The current UI treats every displayed layout point as a tube. That is not reliable for U-Bend exchangers, where a physical tube may have two Tube Sheet ends. Add separate physical-tube and layout-point counts, a count-basis field (`PHYSICAL_TUBE`, `TUBE_END`, or `UNKNOWN`), coverage status, unresolved count, and a discrepancy note. Until then, all 15 layouts remain unapproved.",
        "",
        "The next safe implementation step is a nullable/defaulted schema migration plus UI wording changes. Database migration requires explicit user confirmation.",
    ])
    (review_dir / "MISMATCH_DIAGNOSIS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
