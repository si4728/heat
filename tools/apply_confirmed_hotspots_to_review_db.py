"""Persist only high-confidence PDF/raw-confirmed Hotspots to the ML review DB."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from iris2.hx_configuration import ML_ARTIFACT_ROOT, ML_REVIEW_DB_PATH  # noqa: E402
from iris2.ml.review import latest_run_directory  # noqa: E402
from iris2.ml.review_feedback import initialize_hotspot_review_database  # noqa: E402


REVIEWER = "AI_PDF_RAW_EVIDENCE_REVIEW_20260928"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    run = latest_run_directory(ML_ARTIFACT_ROOT, "expert_review/hotspot_top30_review.json")
    if run is None:
        raise RuntimeError("No reviewed Hotspot artifact is available")
    source = json.loads((run / "expert_review" / "hotspot_top30_review.json").read_text(encoding="utf-8"))
    confirmed = [
        item for item in source["reviews"]
        if item["decision"] == "CONFIRMED_WITH_RAW"
        and item["confidence"] == "HIGH"
        and item["pdf_row_exact"]
        and item["approved_layout_verified"]
        and item["raw_direct_match_count"] > 0
        and not item["limitations"]
    ]
    if len(confirmed) != 10:
        raise RuntimeError(f"Expected 10 high-confidence confirmations, got {len(confirmed)}")
    preview = {
        "database_apply": bool(args.apply),
        "run_id": source["run_id"],
        "confirmed_count": len(confirmed),
        "result_ids": [item["iris_tube_result_id"] for item in confirmed],
    }
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    database = Path(ML_REVIEW_DB_PATH).resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_dir = ROOT / "backups" / "files" / f"hotspot_review_db_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup = backup_dir / database.name
    if database.exists():
        source_db = sqlite3.connect(database)
        backup_db = sqlite3.connect(backup)
        source_db.backup(backup_db)
        backup_db.close()
        source_db.close()
    else:
        backup.write_bytes(b"")
    backup_hash = file_sha256(backup)

    initialize_hotspot_review_database(database)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    connection = sqlite3.connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        inserted = 0
        for item in confirmed:
            evidence_fingerprint = hashlib.sha256(
                json.dumps({
                    "run_id": source["run_id"],
                    "result_id": item["iris_tube_result_id"],
                    "pdf": item["pdf_source_file"],
                    "page": item["source_page"],
                    "raw_files": item["raw_files"],
                }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ml_hotspot_review_feedback (
                    analysis_type,run_id,model_version,iris_tube_result_id,
                    iris_inspection_id,tube_id,decision,confirmation_status,
                    confidence,hotspot_score,pdf_source_file,pdf_source_page,
                    raw_files_json,evidence_fingerprint,reviewer_name,reviewed_at,created_at
                ) VALUES ('HOTSPOT',?,?,?,?,?,'CONFIRMED_WITH_RAW','CONFIRMED','HIGH',
                          ?,?,?,?,?,?,?,?)
                """,
                (
                    source["run_id"], source["model_version"], item["iris_tube_result_id"],
                    item["iris_inspection_id"], item["tube_id"], item["hotspot_score"],
                    item["pdf_source_file"], item["source_page"],
                    json.dumps(item["raw_files"], ensure_ascii=False, separators=(",", ":")),
                    evidence_fingerprint, REVIEWER, now, now,
                ),
            )
            inserted += cursor.rowcount
        stored = connection.execute(
            "SELECT count(*) FROM ml_hotspot_review_feedback WHERE run_id=? AND confirmation_status='CONFIRMED'",
            (source["run_id"],),
        ).fetchone()[0]
        if stored != 10:
            raise RuntimeError(f"Stored confirmation count mismatch: {stored}")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Review database integrity check failed")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    result = {
        **preview,
        "inserted_count": inserted,
        "stored_confirmed_count": stored,
        "review_database": str(database),
        "backup_file": str(backup),
        "backup_sha256": backup_hash,
        "integrity_check": "ok",
        "operational_measurements_changed": False,
        "conditional_items_persisted_as_confirmed": 0,
    }
    result_path = run / "expert_review" / "hotspot_db_apply_result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
