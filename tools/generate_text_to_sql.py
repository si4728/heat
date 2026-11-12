"""Single inference child process; JSON stdin/stdout, no database access."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from iris2.llm_integration.local_llm import LocalLlmClient
from iris2.llm_integration.model_config import load_local_runtime_config
from iris2.llm_integration.text_to_sql import QueryRejected, generate_proposal


def main():
    client = None
    try:
        data = json.load(sys.stdin)
        config = load_local_runtime_config(ROOT/'llm_integration/models.local.json')
        if any(not spec.model_path.is_relative_to(ROOT) for spec in config.models.values()):
            raise ValueError('External model path')
        client = LocalLlmClient(config)
        proposal = generate_proposal(data['question'], client)
        print(json.dumps({'proposal': proposal}, ensure_ascii=False))
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, QueryRejected) else '로컬 모델 설정·파일을 확인하세요.'
        print(json.dumps({'error': message}, ensure_ascii=False))
        return 1
    finally:
        if client:
            client.close()


if __name__ == '__main__':
    raise SystemExit(main())
