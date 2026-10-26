from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path


REVIEWER = "SYSTEM_DATA_NORMALIZATION_20260910"
ROW_TOLERANCE_PERCENT_POINT = 0.25
EXPECTED = {"CURRENT_COUNT_MATCH": 2, "REPORT_NAME_ALIAS": 45, "ROUNDING_TOLERANCE": 304}


def logical_hash(path: Path) -> str:
    digest = hashlib.sha256()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        for line in connection.iterdump():
            digest.update((line + "\n").encode())
    finally:
        connection.close()
    return digest.hexdigest()


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def candidates(connection: sqlite3.Connection) -> list[dict]:
    connection.row_factory = sqlite3.Row
    selected: list[dict] = []
    count_rows = connection.execute(
        """SELECT q.data_quality_issue_id,i.inspected_tube_count_reported,
                  s.summary_inspected_tubes,COUNT(r.iris_tube_result_id) AS detail_count
           FROM data_quality_issue q
           JOIN iris_inspection i ON i.iris_inspection_id=q.iris_inspection_id
           JOIN iris_inspection_spec_snapshot s ON s.iris_inspection_id=i.iris_inspection_id
           LEFT JOIN iris_tube_result r ON r.iris_inspection_id=i.iris_inspection_id
           WHERE q.status='OPEN' AND q.issue_code='REPORTED_EXTRACTED_COUNT_MISMATCH'
           GROUP BY q.data_quality_issue_id"""
    ).fetchall()
    for row in count_rows:
        if row["inspected_tube_count_reported"] == row["detail_count"] and row["summary_inspected_tubes"] == row["detail_count"]:
            selected.append({"id": row["data_quality_issue_id"], "category": "CURRENT_COUNT_MATCH", "detail": dict(row)})

    for row in connection.execute(
        """SELECT q.data_quality_issue_id,q.source_value_json,q.calculated_value_json
           FROM data_quality_issue q
           WHERE q.status='OPEN' AND q.issue_code='REPORT_NUMBER_EQUIPMENT_MISMATCH'"""
    ):
        source = str(json.loads(row["source_value_json"]))
        canonical = str(json.loads(row["calculated_value_json"]))
        if compact(canonical) not in compact(source):
            raise RuntimeError(f"Report-name alias precheck failed for issue {row['data_quality_issue_id']}")
        selected.append({"id": row["data_quality_issue_id"], "category": "REPORT_NAME_ALIAS", "detail": {"source": source, "canonical": canonical}})

    for row in connection.execute(
        """SELECT data_quality_issue_id,source_value_json FROM data_quality_issue
           WHERE status='OPEN' AND issue_code='ROW_CALCULATION_MISMATCH'"""
    ):
        value = json.loads(row["source_value_json"] or "{}")
        reported = value.get("pdf_wall_loss_percent")
        calculated = value.get("recalculated_wall_loss_percent", value.get("calculated_wall_loss_percent"))
        if reported is None or calculated is None:
            continue
        delta = abs(float(reported) - float(calculated))
        if math.isfinite(delta) and delta <= ROW_TOLERANCE_PERCENT_POINT:
            selected.append({"id": row["data_quality_issue_id"], "category": "ROUNDING_TOLERANCE", "detail": {"delta_percent_point": delta}})
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve only mechanically verifiable IRIS data-quality issues.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    selected = candidates(connection)
    counts = {category: sum(item["category"] == category for item in selected) for category in EXPECTED}
    already_applied = not selected and connection.execute(
        "SELECT count(*) FROM data_quality_issue WHERE reviewer=? AND status='RESOLVED'", (REVIEWER,)
    ).fetchone()[0] == sum(EXPECTED.values())
    if selected and counts != EXPECTED:
        raise RuntimeError(f"Candidate counts changed: {counts} != {EXPECTED}")
    preview = {"database_apply": False, "candidate_counts": counts, "candidate_total": len(selected), "already_applied": already_applied}
    if not args.apply or already_applied:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        connection.close()
        return 0

    backup_path = workspace / "backups" / "files" / f"iris_db_before_quality_issue_normalization_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    before_hash = logical_hash(db_path)
    backup = sqlite3.connect(backup_path)
    connection.backup(backup); backup.close()
    if logical_hash(backup_path) != before_hash:
        raise RuntimeError("Backup logical hash mismatch")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    notes = {
        "CURRENT_COUNT_MATCH": "현재 운영 DB의 보고·요약·상세 수량이 일치하여 과거 경고를 종결함.",
        "REPORT_NAME_ALIAS": "보고서 번호의 접두어·구분자·Scope 접미사를 제거하면 정규 설비코드와 일치함. 원문은 보존함.",
        "ROUNDING_TOLERANCE": f"PDF 기재 감육률과 재계산값 차이가 승인 자동정리 기준 {ROW_TOLERANCE_PERCENT_POINT:.2f}%p 이하임. PDF 운영값과 계산 검증값은 모두 보존함.",
    }
    before_open = connection.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0]
    try:
        connection.execute("BEGIN IMMEDIATE")
        for item in selected:
            cursor = connection.execute(
                """UPDATE data_quality_issue SET status='RESOLVED',reviewer=?,reviewed_at=?,resolution_note=?
                   WHERE data_quality_issue_id=? AND status='OPEN'""",
                (REVIEWER, now, notes[item["category"]], item["id"]),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Issue update failed: {item['id']}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    after_open = connection.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0]
    result = {
        "database_apply": True, "completed_at": now, "reviewer": REVIEWER,
        "resolved_counts": counts, "resolved_total": len(selected),
        "open_before": before_open, "open_after": after_open,
        "backup_file": str(backup_path), "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": logical_hash(backup_path),
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }
    connection.close()
    output_dir = workspace / "outputs" / "data_quality_normalization_20260910"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "safe_issue_resolution_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
