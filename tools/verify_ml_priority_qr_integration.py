"""Verify Stage 4 confirmed-Hotspot inspection priority and QR integration."""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from iris2.hx_configuration import DB_PATH, ML_ARTIFACT_ROOT, ML_REVIEW_DB_PATH  # noqa: E402
from iris2.ml.inspection_priority import confirmed_hotspot_priorities  # noqa: E402
from iris2.ml.review import latest_run_directory  # noqa: E402


def main() -> int:
    run = latest_run_directory(ML_ARTIFACT_ROOT, "expert_review/hotspot_db_apply_result.json")
    if run is None:
        raise RuntimeError("No DB-confirmed Hotspot run is available")
    priority = confirmed_hotspot_priorities(DB_PATH, ML_REVIEW_DB_PATH)
    equipment_ids = sorted({int(row["heat_exchanger_id"]) for row in priority["rows"]})
    per_equipment = []
    for exchanger_id in equipment_ids:
        item = confirmed_hotspot_priorities(
            DB_PATH,
            ML_REVIEW_DB_PATH,
            heat_exchanger_id=exchanger_id,
        )
        per_equipment.append({
            "heat_exchanger_id": exchanger_id,
            "equipment_code": item["rows"][0]["equipment_code"],
            "priority": item["priority"],
            "confirmed_record_count": item["confirmed_count"],
            "candidate_tube_count": item["candidate_tube_count"],
            "in_service_count": item["in_service_count"],
            "tube_ids": [row["tube_id"] for row in item["rows"] if row["is_in_service"]],
        })
    gates = {
        "db_confirmed_records_present": priority["confirmed_count"] > 0,
        "physical_tubes_deduplicated": priority["candidate_tube_count"] == len({row["tube_id"] for row in priority["rows"]}),
        "only_in_service_tubes_preselected": priority["candidate_tube_count"] == priority["in_service_count"],
        "equipment_qr_targets_present": bool(per_equipment),
        "automatic_plan_creation_disabled": not priority["automatic_plan_creation_enabled"],
        "automatic_engineering_decision_disabled": not priority["automatic_engineering_decision_enabled"],
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": priority["run_id"],
        "stage": 4,
        "status": "PASS" if all(gates.values()) else "HOLD",
        "confirmed_record_count": priority["confirmed_count"],
        "candidate_tube_count": priority["candidate_tube_count"],
        "duplicate_history_count": priority["confirmed_count"] - priority["candidate_tube_count"],
        "equipment_count": len(per_equipment),
        "priority_counts": dict(sorted(Counter(row["priority"] for row in priority["rows"]).items())),
        "maximum_wall_loss_percent": priority["maximum_wall_loss_percent"],
        "gates": gates,
        "per_equipment": per_equipment,
        "qr_route_pattern": "/q/exchangers/<heat_exchanger_id>",
        "inspection_plan_route_pattern": "/inspection-plans?heat_exchanger_id=<id>&priority_source=confirmed_hotspot",
    }
    output = run / "evaluation" / "inspection_priority_qr.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    stage = run / "stage_4_result.json"
    stage.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "output": str(output)}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
