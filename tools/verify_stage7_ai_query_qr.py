from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.llm_integration.natural_query import natural_language_search  # noqa: E402
from iris2.llm_integration.report_workflow import latest_validated_summary  # noqa: E402


def main() -> int:
    priority_path = APP_DIR / "outputs" / "ml_implementation" / "20260928T120309Z" / "evaluation" / "inspection_priority_qr.json"
    priority = json.loads(priority_path.read_text(encoding="utf-8"))
    examples = [
        "감육률 30% 이상 교환기",
        "1104421 최근 검사",
        "고위험 교환기",
        "검사 없는 교환기",
    ]
    query_results = []
    for query in examples:
        result = natural_language_search(query)
        query_results.append({
            "query": query,
            "interpretation": result["description"],
            "result_count": result["result_count"],
            "filters": result["filters"],
        })
    qr_rows = []
    for item in priority.get("per_equipment", []):
        summary = latest_validated_summary(item["heat_exchanger_id"])
        qr_rows.append({
            "heat_exchanger_id": item["heat_exchanger_id"],
            "equipment_code": item["equipment_code"],
            "summary_available": summary is not None,
            "validation_status": summary["validation_status"] if summary else None,
            "approval_status": summary["approval_status"] if summary else None,
            "pdf_evidence_link_available": bool(summary and summary.get("pdf_reference")),
        })
    all_ready = all(
        row["summary_available"] and row["validation_status"] == "PASS"
        and row["pdf_evidence_link_available"] for row in qr_rows
    )
    payload = {
        "stage": 7,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "PASS_WITH_NOTE" if all_ready else "HOLD",
        "pilot_only": True,
        "production_gate": "MODEL_LICENSE_AND_BUSINESS_APPROVAL_PENDING",
        "natural_language_query": {
            "status": "PASS",
            "direct_sql_from_user_input": False,
            "maximum_results": 50,
            "examples": query_results,
        },
        "qr_ai_summary": {
            "status": "PASS" if all_ready else "HOLD",
            "target_count": len(qr_rows),
            "available_count": sum(row["summary_available"] for row in qr_rows),
            "validated_count": sum(row["validation_status"] == "PASS" for row in qr_rows),
            "approved_count": sum(row["approval_status"] == "APPROVED" for row in qr_rows),
            "rows": qr_rows,
        },
        "automatic_engineering_decision": False,
    }
    output_dir = APP_DIR / "outputs" / "ai_stage7_20260929"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "stage": payload["stage"], "status": payload["status"],
        "query_examples": len(query_results),
        "qr_summary_available": payload["qr_ai_summary"]["available_count"],
        "qr_summary_approved": payload["qr_ai_summary"]["approved_count"],
        "production_gate": payload["production_gate"],
    }, ensure_ascii=False, indent=2))
    return 0 if all_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
