from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from resolve_safe_data_quality_issues import logical_hash


REVIEWER = "SYSTEM_DATA_NORMALIZATION_20260910"
EXPECTED = {"MATERIAL_ALIAS": 58, "LENGTH_ROUNDING": 49}


def normalized_material(value: object) -> str:
    text = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    text = text.replace("COPPERNICKEL", "CUNI").replace("STAINLESS", "SUS")
    if text in {"CUNI7030", "7030CUNI"}:
        return "CUNI7030"
    return text


def candidates(connection: sqlite3.Connection) -> list[tuple[int, str]]:
    connection.row_factory = sqlite3.Row
    selected: list[tuple[int, str]] = []
    rows = connection.execute(
        """SELECT data_quality_issue_id,field_path,source_value_json,calculated_value_json
           FROM data_quality_issue
           WHERE status='OPEN' AND issue_code='MASTER_JSON_VALUE_MISMATCH'"""
    )
    for row in rows:
        source = json.loads(row["source_value_json"])
        compared = json.loads(row["calculated_value_json"])
        if row["field_path"] == "master_vs_json.tube_material":
            if normalized_material(source) == normalized_material(compared):
                selected.append((row["data_quality_issue_id"], "MATERIAL_ALIAS"))
        elif row["field_path"] == "master_vs_json.tube_length_mm":
            source_number, compared_number = float(source), float(compared)
            relative_difference = abs(source_number - compared_number) / max(abs(source_number), abs(compared_number))
            if relative_difference <= 0.001:
                selected.append((row["data_quality_issue_id"], "LENGTH_ROUNDING"))
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve conservative Master/source notation variances.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    db_path = workspace / "data" / "heat_exchanger_db3.db"
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    selected = candidates(connection)
    counts = {category: sum(item[1] == category for item in selected) for category in EXPECTED}
    already_applied = not selected and connection.execute(
        """SELECT count(*) FROM data_quality_issue
           WHERE reviewer=? AND status='RESOLVED' AND resolution_note LIKE 'Master/source%'""",
        (REVIEWER,),
    ).fetchone()[0] == sum(EXPECTED.values())
    if selected and counts != EXPECTED:
        raise RuntimeError(f"Candidate counts changed: {counts} != {EXPECTED}")
    if not args.apply or already_applied:
        print(json.dumps({"database_apply": False, "candidate_counts": counts, "already_applied": already_applied}, ensure_ascii=False, indent=2))
        connection.close()
        return 0
    backup_path = workspace / "backups" / "files" / f"iris_db_before_master_variance_normalization_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    before_hash = logical_hash(db_path)
    backup = sqlite3.connect(backup_path); connection.backup(backup); backup.close()
    if logical_hash(backup_path) != before_hash:
        raise RuntimeError("Backup logical hash mismatch")
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    notes = {
        "MATERIAL_ALIAS": "Master/source 재질값이 Cu-Ni 70/30 또는 Stainless/SUS316의 표기 동의어로 확인됨. 양쪽 원문을 보존하고 비교 경고만 종결함.",
        "LENGTH_ROUNDING": "Master/source Tube 길이의 상대 차이가 0.1% 이하로 단위 환산·반올림 범위임. 양쪽 원문을 보존하고 비교 경고만 종결함.",
    }
    before_open = connection.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0]
    try:
        connection.execute("BEGIN IMMEDIATE")
        for issue_id, category in selected:
            cursor = connection.execute(
                """UPDATE data_quality_issue SET status='RESOLVED',reviewer=?,reviewed_at=?,resolution_note=?
                   WHERE data_quality_issue_id=? AND status='OPEN'""",
                (REVIEWER, now, f"Master/source {notes[category]}", issue_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Issue update failed: {issue_id}")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Foreign-key validation failed")
        connection.commit()
    except Exception:
        connection.rollback(); raise
    result = {
        "database_apply": True, "completed_at": now, "resolved_counts": counts,
        "resolved_total": len(selected), "open_before": before_open,
        "open_after": connection.execute("SELECT count(*) FROM data_quality_issue WHERE status='OPEN'").fetchone()[0],
        "backup_file": str(backup_path), "database_logical_sha256_before": before_hash,
        "backup_logical_sha256": logical_hash(backup_path),
        "quick_check": connection.execute("PRAGMA quick_check").fetchone()[0],
        "foreign_key_issues": len(connection.execute("PRAGMA foreign_key_check").fetchall()),
    }
    connection.close()
    output_dir = workspace / "outputs" / "data_quality_normalization_20260910"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "safe_master_variance_resolution_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
