# 로컬 모델 이관 정리 — 2026-11-11

별도 이관 위치: 이관/로컬모델_20261111/

모델 2개 총 7,008,296,928바이트(약 7.01GB / 6.53GiB)를 실제 복사하고 원본·사본 SHA-256 일치를 확인했다.

| 파일 | 크기 | 운영 iris2 기준 위치 |
|---|---:|---|
| gemma-4-E4B-it-Q4_K_M.gguf | 5,335,289,664바이트 | data/llm/models/ |
| Qwen3-1.7B-Q6_K.gguf | 1,673,007,264바이트 | data/llm/models/ |

기본 모델은 iris2_text_to_sql_gemma이다. 설정 검토본은 설정_검토용/llm_integration/models.local.json에 분리했으며, 운영 llm_integration/models.local.json과 비교한 후 필요한 항목을 반영한다. 자동 덮어쓰기는 하지 않는다. model_path는 설정 파일 폴더를 기준으로 ../data/llm/models/ 아래 GGUF를 가리킨다.

의존성 검토본 llm_integration/requirements.txt와 읽기 전용 전달본 해시 검사 스크립트 검증.ps1, 파일별 manifest.json, 모델_이관안내.md를 포함했다. 대상 CPU/GPU·Python에 맞는 wheel 설치 및 실제 추론 검증은 별도이다. GGUF 단일 파일이 4GB를 넘으므로 복사 매체는 해당 크기를 지원해야 한다.

운영 서버 적용, 코드 변경 배포, DB/config 계정 설정·비밀번호·세션 키 복사는 수행하지 않았다. models.local.json은 기존 비밀 설정 전체가 아니라 검증된 모델/캐시 항목만 담은 별도 검토본이다. 이관/는 Git 제외 대상이다.
