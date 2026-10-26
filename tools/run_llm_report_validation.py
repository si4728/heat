from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.llm_integration.report_workflow import (  # noqa: E402
    DEFAULT_MODEL_CONFIG, DEFAULT_OUTPUT_DIR, REPORT_DB_PATH,
    baseline_report, collect_evidence, grounded_model_report, parse_model_selection,
    save_draft, selection_prompt, validate_report,
)
from iris2.llm_integration.local_llm import LocalLlmClient  # noqa: E402
from iris2.llm_integration.model_config import load_local_runtime_config  # noqa: E402


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="6단계 로컬 LLM 보고서 근거 검증")
    parser.add_argument("--priority-json", type=Path, default=APP_DIR / "outputs" / "ml_implementation" / "20260928T120309Z" / "evaluation" / "inspection_priority_qr.json")
    parser.add_argument("--model-config", type=Path, default=DEFAULT_MODEL_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report-db", type=Path, default=REPORT_DB_PATH)
    args = parser.parse_args()
    priority = json.loads(args.priority_json.read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    local_model_ready = args.model_config.is_file()
    runtime = load_local_runtime_config(args.model_config) if local_model_ready else None
    client = LocalLlmClient(runtime) if runtime else None
    model_spec = runtime.models[runtime.default_model_key] if runtime else None
    if model_spec and not model_spec.model_path.is_file():
        local_model_ready = False
        client = None
    model_hash = file_sha256(model_spec.model_path) if local_model_ready and model_spec else None
    results = []
    try:
        for item in priority.get("per_equipment", []):
            evidence = collect_evidence(int(item["heat_exchanger_id"]))
            raw_output = None
            generation_mode = "RULE_BASED_BASELINE"
            generation_error = None
            if client and model_spec:
                try:
                    raw_output = client.generate(
                        selection_prompt(evidence), model_key=model_spec.key,
                        system_prompt="검증된 ID만 선택하는 JSON 분류기입니다. JSON 외에는 출력하지 않습니다.",
                        temperature=0.0, max_tokens=768,
                    )
                    selection = parse_model_selection(raw_output)
                    report = grounded_model_report(evidence, selection, raw_output)
                    generation_mode = "LOCAL_LLM_GROUNDED"
                except Exception as exc:
                    report = baseline_report(evidence)
                    report["generation_metadata"] = {"mode": "LOCAL_LLM_FAILED", "error": str(exc)}
                    generation_mode = "LOCAL_LLM_FAILED_BASELINE"
                    generation_error = str(exc)
            else:
                report = baseline_report(evidence)
            validation = validate_report(report, evidence)
            if generation_error:
                validation["status"] = "HOLD"
                validation["error_count"] += 1
                validation["errors"].append(f"local model generation failed: {generation_error}")
            saved = save_draft(
                evidence, report, validation, generation_mode=generation_mode,
                model_key=model_spec.key if model_spec else None,
                model_sha256=model_hash, report_db=args.report_db,
            )
            payload = {**saved, "heat_exchanger_id": item["heat_exchanger_id"], "equipment_code": item["equipment_code"], "validation": validation}
            results.append(payload)
            (args.output_dir / f"{item['equipment_code']}_evidence_report.json").write_text(
                json.dumps({"evidence": evidence, "report": report, "validation": validation, "raw_model_output": raw_output}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    finally:
        if client:
            client.close()
    summary = {
        "stage": 6,
        "status": "PASS" if local_model_ready and all(row["validation"]["status"] == "PASS" for row in results) else "PASS_WITH_NOTE",
        "local_model_ready": local_model_ready,
        "local_model_execution": "COMPLETED" if local_model_ready else "NOT_RUN",
        "model_key": model_spec.key if model_spec else None,
        "model_sha256": model_hash,
        "note": None if local_model_ready else "IRIS 전용 모델 설정 또는 GGUF를 찾을 수 없어 기준 보고서만 생성했습니다.",
        "report_count": len(results),
        "validation_pass_count": sum(row["validation"]["status"] == "PASS" for row in results),
        "validation_hold_count": sum(row["validation"]["status"] != "PASS" for row in results),
        "approval_status": "PENDING",
        "automatic_engineering_decision": False,
        "results": results,
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}, ensure_ascii=False, indent=2))
    return 0 if summary["validation_hold_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
