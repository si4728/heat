"""Safely prepare or apply missing IRIS report-level total tube counts.

The default mode is read-only. Only candidates backed by at least one summary
field and consistent with every other reported source are eligible for apply.
Tube-map-only values and conflicting values remain review items.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
if __package__ in {None, ""}:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.iris_json_validator import integer, report_parts, tube_map_values


DEFAULT_DB = APP_DIR / "data" / "heat_exchanger_db3.db"
DEFAULT_BACKUP_DIR = APP_DIR / "backups"
MAX_PLAUSIBLE_TUBE_COUNT = 100_000


def _candidate(inspection_id: int, source_file: str, raw_json: str) -> dict[str, Any]:
    parts = report_parts(json.loads(raw_json))
    detail_summary = parts["details"].get("inspection_summary") or {}
    summary_ref = parts["summary_reference"]
    sources = {
        "report_summary": integer(parts["summary"].get("total_tube_count")),
        "detail_summary": integer(detail_summary.get("total_tube_count")),
        "summary_reference": integer(summary_ref.get("total_tube_count")),
        "summary_total_tubes": integer(summary_ref.get("total_tubes_summary")),
        "summary_total_raw": integer(summary_ref.get("total_tubes_summary_raw")),
        "tube_map": integer(tube_map_values(parts["tube_map"])["total_tubes"]),
    }
    present = {key: value for key, value in sources.items() if value is not None}
    summary_values = [
        value for key, value in present.items() if key != "tube_map"
    ]
    all_values = list(present.values())
    chosen = summary_values[0] if summary_values else present.get("tube_map")
    plausible = chosen is not None and 0 < chosen <= MAX_PLAUSIBLE_TUBE_COUNT
    if not present:
        classification = "NO_SOURCE"
    elif not plausible:
        classification = "INVALID_VALUE"
    elif not summary_values:
        classification = "MAP_ONLY_REVIEW"
    elif len(set(all_values)) > 1:
        classification = "SOURCE_CONFLICT_REVIEW"
    else:
        classification = "SAFE_SUMMARY_AGREED"
    return {
        "inspection_id": inspection_id,
        "source_file": source_file,
        "equipment_raw": parts["equipment_raw"],
        "equipment_code": parts["equipment_code"],
        "scope_code": parts["scope_code"],
        "candidate_value": chosen,
        "classification": classification,
        "sources": present,
    }


def prepare_backfill(db_path: Path, *, apply: bool = False,
                     backup_dir: Path | None = None) -> dict[str, Any]:
    db_path = db_path.resolve()
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    backup_path: Path | None = None
    try:
        rows = connection.execute(
            """
            SELECT i.iris_inspection_id, d.source_file, i.raw_report_json
              FROM iris_inspection i
              JOIN source_document d
                ON d.source_document_id = i.source_document_id
             WHERE i.total_tube_count_reported IS NULL
             ORDER BY i.iris_inspection_id
            """
        ).fetchall()
        candidates = [
            _candidate(row["iris_inspection_id"], row["source_file"],
                       row["raw_report_json"])
            for row in rows
        ]
        safe = [
            row for row in candidates
            if row["classification"] == "SAFE_SUMMARY_AGREED"
        ]
        if apply and safe:
            target_dir = (backup_dir or DEFAULT_BACKUP_DIR).resolve()
            target_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = target_dir / (
                f"{db_path.stem}_before_total_tube_backfill_{stamp}{db_path.suffix}"
            )
            shutil.copy2(db_path, backup_path)
            connection.execute("BEGIN IMMEDIATE")
            for row in safe:
                cursor = connection.execute(
                    """
                    UPDATE iris_inspection
                       SET total_tube_count_reported = ?
                     WHERE iris_inspection_id = ?
                       AND total_tube_count_reported IS NULL
                    """,
                    (row["candidate_value"], row["inspection_id"]),
                )
                if cursor.rowcount != 1:
                    raise RuntimeError(
                        f"Inspection {row['inspection_id']} was not updated exactly once."
                    )
            connection.commit()
        counts = Counter(row["classification"] for row in candidates)
        return {
            "mode": "APPLY" if apply else "DRY_RUN",
            "db_path": str(db_path),
            "backup_path": str(backup_path) if backup_path else None,
            "db_null_count": len(candidates),
            "classification_counts": dict(sorted(counts.items())),
            "eligible_update_count": len(safe),
            "applied_update_count": len(safe) if apply else 0,
            "candidates": candidates,
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill only agreed JSON summary tube totals; "
            "default is a read-only dry-run"
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()
    result = prepare_backfill(
        args.db, apply=args.apply, backup_dir=args.backup_dir,
    )
    if not args.details:
        result.pop("candidates", None)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
