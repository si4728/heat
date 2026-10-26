from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


PILOT_BUNDLES = {24, 25, 29, 46}


def normalized_label(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def base_equipment_label(value: Any) -> str:
    match = re.search(r"(?<![A-Z0-9])((?:AE|E)[-_ ]?\d{3}[A-Z]?)", str(value or "").upper())
    return normalized_label(match.group(1)) if match else normalized_label(value)


def normalized_section(value: Any) -> str:
    text = str(value or "").upper()
    text = re.sub(r"\b(INLET|OUTLET)\b", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def report_scope(report: dict[str, Any]) -> str:
    value = report.get("report", {}).get("inspection_scope")
    if isinstance(value, dict):
        return str(value.get("scope_code") or "ALL").upper()
    return "ALL"


def expected_source_label(report: dict[str, Any]) -> str:
    details = report.get("report", {})
    scope = details.get("inspection_scope")
    if isinstance(scope, dict) and scope.get("source_equipment_label"):
        return str(scope["source_equipment_label"])
    labels = details.get("source_equipment_labels") or []
    if labels:
        return str(labels[0])
    return str(details.get("equipment_id") or "")


def report_index(workspace: Path) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for unit in ("VCM1", "VCM2"):
        source = workspace / "data" / f"2025{unit}_IRIS2_all_tube_results.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        for report in payload.get("inspection_reports", []):
            details = report.get("report", {})
            equipment = str(details.get("equipment_id") or "").upper()
            result[(unit, equipment, report_scope(report))].append(report)
    return result


def current_revision_status(db_path: Path) -> dict[tuple[int, str], str]:
    connection = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tube_layout_revision'"
        ).fetchone()
        if not exists:
            return {}
        return {
            (int(row[0]), str(row[1])): str(row[2])
            for row in connection.execute(
                "SELECT bundle_id, source_path, revision_status FROM tube_layout_revision"
            )
        }
    finally:
        connection.close()


def choose_report(
    index: dict[tuple[str, str, str], list[dict[str, Any]]],
    unit: str,
    equipment: str,
    scope: str,
    bundle_code: str,
) -> tuple[dict[str, Any] | None, str | None]:
    matches = index.get((unit, equipment, scope), [])
    if len(matches) == 1:
        return matches[0], None
    if scope == "ALL" and bundle_code.upper() not in {"", "MAIN", "ALL"}:
        matches = index.get((unit, equipment, bundle_code.upper()), [])
        if len(matches) == 1:
            return matches[0], None
    if not matches and scope != "ALL":
        matches = index.get((unit, equipment, "ALL"), [])
    if len(matches) == 1:
        return matches[0], None
    return None, "REPORT_NOT_UNIQUE" if matches else "REPORT_NOT_FOUND"


def main() -> int:
    parser = argparse.ArgumentParser(description="Classify Tube Layout rollout candidates without DB writes.")
    parser.add_argument("--workspace", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    output_dir = (args.output_dir or workspace / "outputs" / "tube_layout_review_20260908").resolve()
    revisions_file = output_dir / "layout_revisions.csv"
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    reports = report_index(workspace)
    db_status = current_revision_status(db_path)

    with revisions_file.open(encoding="utf-8-sig", newline="") as stream:
        source_rows = list(csv.DictReader(stream))

    classified: list[dict[str, Any]] = []
    for source in source_rows:
        source_path = source["source_path"]
        unit = source_path.split("\\", 1)[0].upper()
        equipment = source["canonical_equipment_code"].upper()
        scope = (source.get("scope_code") or "ALL").upper()
        bundle_code = (source.get("bundle_code") or "").upper()
        bundle_id = int(source["bundle_id"])
        report, report_error = choose_report(reports, unit, equipment, scope, bundle_code)
        reasons: list[str] = []

        source_count = int(source["source_tube_count"])
        expected_count = int(source["bundle_expected_tube_count"]) if source["bundle_expected_tube_count"] else None
        report_total = None
        map_total = None
        map_label = ""
        expected_label = ""
        report_page = ""
        map_page = ""
        map_section = ""

        if report_error:
            reasons.append(report_error)
        else:
            details = report.get("report", {})
            tube_map = report.get("tube_map") or {}
            report_total = details.get("inspection_summary", {}).get("total_tube_count")
            map_total = tube_map.get("total_tubes")
            map_label = str(tube_map.get("map_exchanger") or "")
            expected_label = expected_source_label(report)
            report_page = ",".join(str(v) for v in details.get("source_report_pages") or [])
            map_page = str(tube_map.get("source_page") or "")
            map_section = str(tube_map.get("section") or "")

            if base_equipment_label(map_label) != base_equipment_label(expected_label):
                reasons.append("MAP_EQUIPMENT_LABEL_MISMATCH")
            if report_total is None or int(report_total) != source_count:
                reasons.append("REPORT_TOTAL_MISMATCH")
            if map_total is None or int(map_total) != source_count:
                reasons.append("MAP_TOTAL_MISMATCH")
            if normalized_section(source.get("section_name")) != normalized_section(map_section):
                reasons.append("SECTION_LABEL_MISMATCH")

        if expected_count is None or expected_count != source_count:
            reasons.append("MASTER_EXPECTED_COUNT_MISMATCH")

        current_status = db_status.get((bundle_id, source_path), "NOT_LOADED")
        if current_status == "APPROVED":
            classification = "APPROVED_PILOT" if bundle_id in PILOT_BUNDLES else "APPROVED_ROLLOUT"
        elif bundle_id in PILOT_BUNDLES:
            classification = "PILOT_REVIEW_HOLD"
        elif current_status == "DRAFT" and not reasons:
            classification = "STAGED_DRAFT"
        elif reasons:
            classification = "REVIEW_REQUIRED"
        else:
            classification = "AUTO_APPROVAL_CANDIDATE"

        classified.append({
            "classification": classification,
            "reasons": ";".join(sorted(set(reasons))),
            "unit": unit,
            "equipment_code": equipment,
            "bundle_id": bundle_id,
            "bundle_code": source.get("bundle_code", ""),
            "scope_code": scope,
            "source_path": source_path,
            "source_tube_count": source_count,
            "master_expected_tube_count": expected_count if expected_count is not None else "",
            "report_total_tube_count": report_total if report_total is not None else "",
            "map_total_tube_count": map_total if map_total is not None else "",
            "expected_source_label": expected_label,
            "map_equipment_label": map_label,
            "mdb_section": source.get("section_name", ""),
            "map_section": map_section,
            "report_page": report_page,
            "map_page": map_page,
            "current_db_status": current_status,
        })

    output_csv = output_dir / "rollout_candidate_classification.csv"
    with output_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(classified[0]))
        writer.writeheader()
        writer.writerows(classified)

    class_counts = Counter(row["classification"] for row in classified)
    reason_counts = Counter(
        reason for row in classified for reason in row["reasons"].split(";") if reason
    )
    remaining = [row for row in classified if row["bundle_id"] not in PILOT_BUNDLES]
    remaining_bundle_counts = Counter()
    for row in remaining:
        remaining_bundle_counts[row["classification"]] += 1

    auto_bundle_ids = {
        row["bundle_id"] for row in classified if row["classification"] == "AUTO_APPROVAL_CANDIDATE"
    }
    with (output_dir / "tube_layout_candidates.csv").open(encoding="utf-8-sig", newline="") as stream:
        point_rows = [row for row in csv.DictReader(stream) if int(row["bundle_id"]) in auto_bundle_ids]
    auto_mapping_counts = Counter(row["mapping_status"] for row in point_rows)

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database_mode": "READ_ONLY",
        "database_changes": 0,
        "revision_count": len(classified),
        "unique_bundle_count": len({row["bundle_id"] for row in classified}),
        "classification_counts_by_revision": dict(sorted(class_counts.items())),
        "reason_counts_by_revision": dict(sorted(reason_counts.items())),
        "remaining_non_pilot_revision_count": len(remaining),
        "remaining_non_pilot_bundle_count": len({row["bundle_id"] for row in remaining}),
        "remaining_classification_counts_by_revision": dict(sorted(remaining_bundle_counts.items())),
        "auto_candidate_point_count": len(point_rows),
        "auto_candidate_mapping_counts": dict(sorted(auto_mapping_counts.items())),
        "approval_required_before_database_apply": True,
    }
    (output_dir / "rollout_classification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    review_rows = [row for row in classified if row["classification"] in {"REVIEW_REQUIRED", "PILOT_REVIEW_HOLD"}]
    lines = [
        "# Tube Layout rollout validation",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "This classification is read-only. No database rows were inserted or updated.",
        "",
        "## Result",
        "",
        f"- Source revisions: {len(classified)} across {summary['unique_bundle_count']} bundles",
        f"- Remaining non-pilot bundles: {summary['remaining_non_pilot_bundle_count']}",
        f"- Automatic approval candidates: {class_counts.get('AUTO_APPROVAL_CANDIDATE', 0)} revisions",
        f"- Automatic candidate points: {len(point_rows)} ({auto_mapping_counts.get('EXISTING_TUBE_MATCH', 0)} existing tube links, {auto_mapping_counts.get('NEW_TUBE_CANDIDATE', 0)} unlinked source points)",
        f"- Review required: {class_counts.get('REVIEW_REQUIRED', 0)} revisions",
        f"- Approved pilot: {class_counts.get('APPROVED_PILOT', 0)} revisions",
        f"- Approved rollout: {class_counts.get('APPROVED_ROLLOUT', 0)} revisions",
        f"- Pilot held: {class_counts.get('PILOT_REVIEW_HOLD', 0)} revisions",
        "",
        "## Automatic candidate batch",
        "",
        ", ".join(
            f"{row['unit']} {row['equipment_code']}"
            + (f"-{row['bundle_code']}" if row['bundle_code'] not in {"", "MAIN", "ALL"} else "")
            for row in classified if row["classification"] == "AUTO_APPROVAL_CANDIDATE"
        ),
        "",
        "## Review queue",
        "",
        "| Equipment | Bundle | Scope | Source / master / report / map totals | Reason |",
        "|---|---:|---|---|---|",
    ]
    for row in review_rows:
        totals = "/".join(str(row[key]) for key in (
            "source_tube_count", "master_expected_tube_count", "report_total_tube_count", "map_total_tube_count"
        ))
        lines.append(
            f"| {row['unit']} {row['equipment_code']} | {row['bundle_id']} | {row['scope_code']} | {totals} | {row['reasons'] or row['classification']} |"
        )
    lines.extend([
        "",
        "## Gate",
        "",
        "Automatic candidates may be prepared as a proposed batch, but database application requires explicit user confirmation.",
    ])
    (output_dir / "ROLLOUT_VALIDATION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
