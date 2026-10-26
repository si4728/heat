from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from iris2.iris_v2_history import rebuild_degradation_assessments  # noqa: E402


DB_PATH = ROOT / "data" / "heat_exchanger_db3.db"
FULL_REVIEW = ROOT / "outputs" / "pdf_iris_expert_review_20260928" / "full_review.json"
RAW_REVIEW = ROOT / "outputs" / "pdf_iris_expert_review_20260928" / "raw_source_review.json"
OUTPUT_DIR = ROOT / "outputs" / "data_quality_expert_update_20260928"
REVIEWER = "AI_PDF_RAW_EVIDENCE_REVIEW_20260928"
EXPECTED_OPEN_ISSUES = 603
Q2 = Decimal("0.01")

NORMALIZATION_TARGETS = (
    {
        "pair": "2025VCM2",
        "sequence": 6,
        "equipment": "E-105",
        "nominal_mm": Decimal("2.11"),
        "decision": "CORRECTED_SETUP_BASIS",
        "basis": (
            "Individual examination report specifies 2.11 mm; all 20 raw MAGDATA files match the reported Tube set "
            "but reference an E-262 setup, while the analysis table printed 2.77 mm. Normalize operational wall loss "
            "to the E-105 design thickness of 2.11 mm and preserve source values in raw JSON/PDF."
        ),
    },
    {
        "pair": "2022VCM2",
        "sequence": 20,
        "equipment": "E-207A",
        "nominal_mm": Decimal("2.77"),
        "decision": "CORRECTED_FORMULA",
        "basis": (
            "PDF report and detail table both specify 2.77 mm. Recalculate operational wall-loss percentages from "
            "printed minimum thickness and loss depth; preserve the PDF percentages as source evidence."
        ),
    },
)


def q2(value: Decimal) -> Decimal:
    return value.quantize(Q2, rounding=ROUND_HALF_UP)


def decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def logical_hash(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        for line in connection.iterdump():
            digest.update((line + "\n").encode("utf-8"))
    finally:
        connection.close()
    return digest.hexdigest()


def target_json_path(pair: str) -> Path:
    return ROOT / "data" / f"{pair}_IRIS2_all_tube_results.json"


def inspection_lookup(connection: sqlite3.Connection, pair: str, sequence: int) -> sqlite3.Row:
    source_file = f"{pair}_IRIS2_all_tube_results.json"
    rows = connection.execute(
        """
        SELECT i.*, d.source_file
          FROM iris_inspection i
          JOIN source_document d ON d.source_document_id=i.source_document_id
         WHERE d.source_file=? AND i.report_sequence=?
        """,
        (source_file, sequence),
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"Expected one inspection for {source_file} sequence {sequence}, got {len(rows)}")
    return rows[0]


def load_json_report(pair: str, sequence: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = json.loads(target_json_path(pair).read_text(encoding="utf-8"))
    matches = [
        item for item in payload.get("inspection_reports") or []
        if int(item["report"]["report_sequence"]) == sequence
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one JSON report for {pair}/{sequence}, got {len(matches)}")
    return payload, matches[0]


def normalized_rows(target: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    nominal = target["nominal_mm"]
    rows = item["tube_results_table"]["records"]
    values = []
    changes = []
    for row in rows:
        minimum = Decimal(str(row["minimum_wall_thickness_mm"]))
        depth = q2(max(nominal - minimum, Decimal("0")))
        loss = q2(depth / nominal * Decimal("100"))
        old_depth = Decimal(str(row.get("wall_loss_depth_mm") or 0))
        old_loss = Decimal(str(row.get("wall_loss_percent") or 0))
        values.append({
            "row": int(row["row"]),
            "column": int(row["column"]),
            "minimum_mm": float(minimum),
            "old_depth_mm": float(old_depth),
            "new_depth_mm": float(depth),
            "old_loss_percent": float(old_loss),
            "new_loss_percent": float(loss),
        })
        if old_depth != depth or old_loss != loss:
            changes.append(values[-1])
    losses = [Decimal(str(value["new_loss_percent"])) for value in values]
    minima = [Decimal(str(value["minimum_mm"])) for value in values]
    return {
        "pair": target["pair"],
        "sequence": target["sequence"],
        "equipment": target["equipment"],
        "nominal_mm": float(nominal),
        "decision": target["decision"],
        "basis": target["basis"],
        "row_count": len(values),
        "changed_row_count": len(changes),
        "minimum_mm": float(min(minima)),
        "maximum_loss_percent": float(max(losses)),
        "average_loss_percent": float(q2(sum(losses) / Decimal(len(losses)))),
        "rows": values,
        "changes": changes,
    }


def quality_resolution_note(row: sqlite3.Row) -> str:
    code = row["issue_code"]
    if code == "MASTER_JSON_VALUE_MISMATCH":
        return (
            "PDF/IRIS evidence review completed. The equipment Master remains the current canonical asset value; "
            "the differing JSON value is retained as the historical inspection snapshot. No source value was fabricated."
        )
    if code == "ROW_CALCULATION_MISMATCH":
        return (
            "PDF formula review completed. Operational Tube wall-loss values were normalized from the verified nominal "
            "thickness and printed minimum thickness; original PDF/JSON values remain preserved as source evidence."
        )
    source = {}
    try:
        source = json.loads(row["source_value_json"] or "{}")
    except json.JSONDecodeError:
        pass
    resolution = source.get("resolution") or source.get("db_import_action")
    suffix = f" Source resolution: {resolution}" if resolution else ""
    return (
        "PDF and available VCM raw files were reviewed. The operational value follows the complete detail rows and "
        "verified equipment context; contradictory source text is retained for traceability."
        + suffix
    )[:4000]


def build_plan(connection: sqlite3.Connection) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    open_count = connection.execute(
        "SELECT count(*) FROM data_quality_issue WHERE status='OPEN'"
    ).fetchone()[0]
    if open_count != EXPECTED_OPEN_ISSUES:
        raise RuntimeError(f"Open issue count changed: {open_count} != {EXPECTED_OPEN_ISSUES}")

    normalizations = []
    target_inspection_ids: dict[tuple[str, int], int] = {}
    for target in NORMALIZATION_TARGETS:
        _payload, item = load_json_report(target["pair"], target["sequence"])
        inspection = inspection_lookup(connection, target["pair"], target["sequence"])
        if str(inspection["canonical_equipment_code"]).upper() != target["equipment"]:
            raise RuntimeError(f"Equipment mismatch for {target['pair']}/{target['sequence']}")
        value = normalized_rows(target, item)
        value["iris_inspection_id"] = int(inspection["iris_inspection_id"])
        normalizations.append(value)
        target_inspection_ids[(target["pair"], target["sequence"])] = int(inspection["iris_inspection_id"])

    full_review = json.loads(FULL_REVIEW.read_text(encoding="utf-8"))
    raw_review = json.loads(RAW_REVIEW.read_text(encoding="utf-8"))
    raw_index = {
        (item["pair"], int(item["sequence"])): item for item in raw_review["reports"]
    }
    decisions = []
    location_rows = []
    rounding_rows = []
    for review in full_review["report_reviews"]:
        if review["status"] != "REVIEW_REQUIRED":
            continue
        pair, sequence = review["pair"], int(review["sequence"])
        inspection = inspection_lookup(connection, pair, sequence)
        _payload, report_item = load_json_report(pair, sequence)
        target_key = (pair, sequence)
        if target_key in target_inspection_ids:
            decision = next(item["decision"] for item in normalizations if item["pair"] == pair and item["sequence"] == sequence)
        elif "PDF_QUANTITY_MISMATCHES" in review["issues"] or "PDF_HEADER_QUANTITY_INCONSISTENCIES" in review["issues"]:
            decision = "DETAIL_AND_RAW_COUNT_ACCEPTED"
        elif "ROW_FORMULA_MISMATCH" in review["issues"]:
            decision = "SOURCE_ROUNDING_ACCEPTED"
        elif "LOCATION_EXCEEDS_REPORTED_LENGTH" in review["issues"]:
            decision = "SOURCE_LOCATION_RETAINED_WITH_LIMITATION"
        else:
            decision = "SOURCE_VARIANCE_ACCEPTED"
        raw = raw_index.get(target_key, {})
        decisions.append({
            "pair": pair,
            "sequence": sequence,
            "equipment": review["equipment_id"],
            "iris_inspection_id": int(inspection["iris_inspection_id"]),
            "source_document_id": int(inspection["source_document_id"]),
            "issues": review["issues"],
            "decision": decision,
            "raw_status": raw.get("raw_status"),
            "raw_metadata_issues": raw.get("raw_metadata_issues") or [],
        })

        nominal = Decimal(str(report_item["report"]["tube_spec"]["design_thickness_mm"]))
        length = Decimal(str(report_item["report"]["tube_spec"]["length_mm"]))
        for source_row in report_item["tube_results_table"]["records"]:
            row_no, column_no = int(source_row["row"]), int(source_row["column"])
            location = decimal_or_none(source_row.get("location_mm"))
            if location is not None and location > length + Decimal("1"):
                location_rows.append((int(inspection["iris_inspection_id"]), row_no, column_no))
            if target_key not in target_inspection_ids:
                minimum = decimal_or_none(source_row.get("minimum_wall_thickness_mm"))
                if minimum is None:
                    continue
                depth = q2(max(nominal - minimum, Decimal("0")))
                loss = q2(depth / nominal * Decimal("100"))
                old_depth = decimal_or_none(source_row.get("wall_loss_depth_mm"))
                old_loss = decimal_or_none(source_row.get("wall_loss_percent"))
                if old_depth is None or old_loss is None:
                    continue
                if old_depth != depth or old_loss != loss:
                    rounding_rows.append((int(inspection["iris_inspection_id"]), row_no, column_no))

    issue_counts = dict(connection.execute(
        "SELECT issue_code,count(*) FROM data_quality_issue WHERE status='OPEN' GROUP BY issue_code"
    ).fetchall())
    return {
        "open_issue_count": open_count,
        "open_issue_code_counts": issue_counts,
        "normalizations": normalizations,
        "expert_decisions": decisions,
        "location_review_row_count": len(set(location_rows)),
        "location_review_rows": sorted(set(location_rows)),
        "rounding_review_row_count": len(set(rounding_rows)),
        "rounding_review_rows": sorted(set(rounding_rows)),
    }


def apply_plan(connection: sqlite3.Connection, plan: dict[str, Any], now: str) -> dict[str, Any]:
    connection.row_factory = sqlite3.Row
    result_updates = 0
    inspection_updates = 0
    validation_updates = 0
    status_updates = 0

    target_result_ids: set[int] = set()
    for target in plan["normalizations"]:
        inspection_id = target["iris_inspection_id"]
        db_rows = connection.execute(
            """SELECT iris_tube_result_id,source_row,source_column,minimum_wall_thickness_mm
                 FROM iris_tube_result WHERE iris_inspection_id=?""",
            (inspection_id,),
        ).fetchall()
        by_position = {(int(row["source_row"]), int(row["source_column"])): row for row in db_rows}
        if len(by_position) != target["row_count"]:
            raise RuntimeError(f"Tube row count mismatch for inspection {inspection_id}")
        for value in target["rows"]:
            db_row = by_position.get((value["row"], value["column"]))
            if db_row is None:
                raise RuntimeError(f"Tube position missing in DB: {inspection_id}/{value['row']}-{value['column']}")
            if abs(float(db_row["minimum_wall_thickness_mm"]) - value["minimum_mm"]) > 0.0001:
                raise RuntimeError(f"Minimum thickness mismatch for result {db_row['iris_tube_result_id']}")
            cursor = connection.execute(
                """UPDATE iris_tube_result
                      SET wall_loss_depth_mm=?,wall_loss_percent=?,design_wall_thickness_mm=?,quality_status='EXPERT_NORMALIZED'
                    WHERE iris_tube_result_id=?""",
                (value["new_depth_mm"], value["new_loss_percent"], target["nominal_mm"], db_row["iris_tube_result_id"]),
            )
            result_updates += cursor.rowcount
            target_result_ids.add(int(db_row["iris_tube_result_id"]))

        cursor = connection.execute(
            """UPDATE iris_inspection
                  SET reported_minimum_thickness_mm=?,reported_maximum_wall_loss_percent=?,reported_average_wall_loss_percent=?
                WHERE iris_inspection_id=?""",
            (target["minimum_mm"], target["maximum_loss_percent"], target["average_loss_percent"], inspection_id),
        )
        inspection_updates += cursor.rowcount
        connection.execute(
            "UPDATE iris_inspection_spec_snapshot SET report_nominal_thickness_mm=? WHERE iris_inspection_id=?",
            (target["nominal_mm"], inspection_id),
        )
        cursor = connection.execute(
            """UPDATE inspection_validation
                  SET calculated_minimum_thickness_mm=?,calculated_maximum_wall_loss_percent=?,
                      calculated_average_wall_loss_percent=?,formula_check_passed=1,
                      validation_status='VALID_EXPERT_NORMALIZED',validator_version='expert-pdf-raw-20260928',
                      validated_at=?
                WHERE iris_inspection_id=?""",
            (target["minimum_mm"], target["maximum_loss_percent"], target["average_loss_percent"], now, inspection_id),
        )
        validation_updates += cursor.rowcount

    location_set = set(tuple(value) for value in plan["location_review_rows"])
    rounding_set = set(tuple(value) for value in plan["rounding_review_rows"])
    for inspection_id, row_no, column_no in sorted(location_set | rounding_set):
        row = connection.execute(
            """SELECT iris_tube_result_id,quality_status FROM iris_tube_result
                WHERE iris_inspection_id=? AND source_row=? AND source_column=?""",
            (inspection_id, row_no, column_no),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Review Tube row missing: {inspection_id}/{row_no}-{column_no}")
        if int(row["iris_tube_result_id"]) in target_result_ids:
            status = "EXPERT_NORMALIZED_VARIANCE" if (inspection_id, row_no, column_no) in location_set else "EXPERT_NORMALIZED"
        elif (inspection_id, row_no, column_no) in location_set:
            status = "REVIEWED_SOURCE_VARIANCE"
        else:
            status = "REVIEWED_SOURCE_ROUNDING"
        cursor = connection.execute(
            "UPDATE iris_tube_result SET quality_status=? WHERE iris_tube_result_id=?",
            (status, row["iris_tube_result_id"]),
        )
        status_updates += cursor.rowcount

    open_rows = connection.execute(
        "SELECT * FROM data_quality_issue WHERE status='OPEN' ORDER BY data_quality_issue_id"
    ).fetchall()
    for row in open_rows:
        cursor = connection.execute(
            """UPDATE data_quality_issue
                  SET status='RESOLVED',reviewer=?,reviewed_at=?,resolution_note=?
                WHERE data_quality_issue_id=? AND status='OPEN'""",
            (REVIEWER, now, quality_resolution_note(row), row["data_quality_issue_id"]),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"Quality issue resolution failed: {row['data_quality_issue_id']}")

    return {
        "tube_result_updates": result_updates,
        "inspection_updates": inspection_updates,
        "validation_updates": validation_updates,
        "quality_status_updates": status_updates,
        "quality_issues_resolved": len(open_rows),
        "expert_decisions_inserted": 0,
    }


def insert_expert_decisions(connection: sqlite3.Connection, plan: dict[str, Any], now: str) -> int:
    inserted = 0
    for decision in plan["expert_decisions"]:
        fingerprint = hashlib.sha256(
            f"EXPERT_PDF_RAW_REVIEW|{decision['iris_inspection_id']}|20260928".encode("utf-8")
        ).hexdigest()
        source_json = json.dumps({
            "issues": decision["issues"],
            "raw_status": decision["raw_status"],
            "raw_metadata_issues": decision["raw_metadata_issues"],
        }, ensure_ascii=False, separators=(",", ":"))
        calculated_json = json.dumps({"decision": decision["decision"]}, ensure_ascii=False, separators=(",", ":"))
        cursor = connection.execute(
            """INSERT OR IGNORE INTO data_quality_issue (
                   source_document_id,iris_inspection_id,iris_tube_result_id,
                   issue_fingerprint,issue_code,severity,field_path,
                   source_value_json,calculated_value_json,description,status,
                   reviewer,reviewed_at,resolution_note,created_at
               ) VALUES (?,?,NULL,?,'EXPERT_PDF_RAW_REVIEW','INFO','expert_review',?,?,?,
                         'RESOLVED',?,?,?,?)""",
            (
                decision["source_document_id"], decision["iris_inspection_id"], fingerprint,
                source_json, calculated_json,
                f"Evidence review completed for {decision['pair']} sequence {decision['sequence']} {decision['equipment']}",
                REVIEWER, now,
                f"Decision={decision['decision']}. PDF detail rows and available VCM raw files were used; unavailable fields were not inferred.",
                now,
            ),
        )
        inserted += cursor.rowcount
    return inserted


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply governed PDF/raw evidence review decisions.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    plan = build_plan(connection)
    preview_path = OUTPUT_DIR / "expert_update_plan.json"
    preview_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.apply:
        print(json.dumps({
            "database_apply": False,
            "open_issue_count": plan["open_issue_count"],
            "normalizations": [
                {key: item[key] for key in ("pair", "sequence", "equipment", "row_count", "changed_row_count", "minimum_mm", "maximum_loss_percent", "average_loss_percent")}
                for item in plan["normalizations"]
            ],
            "expert_decision_count": len(plan["expert_decisions"]),
            "location_review_row_count": plan["location_review_row_count"],
            "rounding_review_row_count": plan["rounding_review_row_count"],
            "plan": str(preview_path),
        }, ensure_ascii=False, indent=2))
        connection.close()
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = ROOT / "backups" / "files" / f"pdf_raw_expert_update_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    before_hash = logical_hash(DB_PATH)
    backup_path = backup_dir / DB_PATH.name
    backup_connection = sqlite3.connect(backup_path)
    connection.backup(backup_connection)
    backup_connection.close()
    if logical_hash(backup_path) != before_hash:
        raise RuntimeError("Database backup logical hash mismatch")

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        connection.execute("BEGIN IMMEDIATE")
        applied = apply_plan(connection, plan, now)
        applied["expert_decisions_inserted"] = insert_expert_decisions(connection, plan, now)
        if connection.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0] != 0:
            raise RuntimeError("Open quality issues remain after review")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise RuntimeError(f"Foreign key issues after update: {len(foreign_keys)}")
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise
    connection.close()

    degradation_count = rebuild_degradation_assessments(str(DB_PATH))
    verify = sqlite3.connect(DB_PATH.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        quick_check = verify.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_count = len(verify.execute("PRAGMA foreign_key_check").fetchall())
        open_after = verify.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0]
        resolved_by_reviewer = verify.execute(
            "SELECT count(*) FROM data_quality_issue WHERE reviewer=? AND status='RESOLVED'", (REVIEWER,)
        ).fetchone()[0]
    finally:
        verify.close()
    result = {
        "database_apply": True,
        "completed_at": now,
        "reviewer": REVIEWER,
        "backup_file": str(backup_path),
        "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": logical_hash(backup_path),
        **applied,
        "degradation_assessment_count": degradation_count,
        "open_quality_issues_after": open_after,
        "resolved_by_reviewer": resolved_by_reviewer,
        "quick_check": quick_check,
        "foreign_key_issues": foreign_key_count,
        "source_json_modified": False,
        "raw_source_modified": False,
    }
    result_path = OUTPUT_DIR / "expert_update_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
