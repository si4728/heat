"""Local operator CLI; not a substitute for web-user authorization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR.parent))

from iris2.llm_integration.local_llm import LocalLlmClient
from iris2.llm_integration.model_config import load_local_runtime_config
from iris2.llm_integration.text_to_sql import answer_question, execute_proposal


def main():
    parser = argparse.ArgumentParser(description="IRIS2 로컬 Text-to-SQL 조회 초안")
    parser.add_argument("--exchanger-id", type=int, required=True)
    parser.add_argument("--inspection-id", type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--question")
    mode.add_argument("--proposal-json", type=Path, help="검증·실행할 SQL JSON; 모델 호출 없음")
    parser.add_argument("--model-config", type=Path, default=APP_DIR / "llm_integration/models.local.json")
    args = parser.parse_args()
    client = None
    try:
        scope = dict(exchanger_id=args.exchanger_id,
                     authorized_exchanger_ids=frozenset({args.exchanger_id}),
                     inspection_id=args.inspection_id)
        if args.proposal_json:
            path = args.proposal_json.resolve()
            if not path.is_relative_to(APP_DIR):
                raise ValueError("SQL JSON은 iris2 내부 파일이어야 합니다.")
            result = execute_proposal(json.loads(path.read_text(encoding="utf-8")), **scope)
        else:
            path = args.model_config.resolve()
            if not path.is_relative_to(APP_DIR):
                raise ValueError("모델 설정은 iris2 내부 파일이어야 합니다.")
            config = load_local_runtime_config(path)
            if any(not spec.model_path.is_relative_to(APP_DIR) for spec in config.models.values()):
                raise ValueError("모든 모델 파일은 iris2 내부에 배치해야 합니다.")
            client = LocalLlmClient(config)
            result = answer_question(args.question, client, **scope)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        # Do not print raw connector errors, prompts or private configuration.
        from iris2.llm_integration.text_to_sql import QueryRejected
        message = str(exc) if isinstance(exc, (QueryRejected, PermissionError)) else "설정·모델·MariaDB 연결을 확인하세요."
        print(json.dumps({"status": "FAILED", "error": message}, ensure_ascii=False))
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
