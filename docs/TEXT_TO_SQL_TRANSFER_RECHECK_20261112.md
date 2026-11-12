# Text-to-SQL 운영 이관 재점검 (2026-11-12)

판정: **관련 파일이 모두 포함된 상태가 아니다.** 최신 안내가 지정한 `이관/20261101_20261110_통합_r2/manifest.json`, 실제 소스 사본·ZIP 및 `이관/로컬모델_20261111/manifest.json`을 대조했다. 기존 패키지와 운영 환경은 변경하지 않았다.

GitHub 작업 전환 후 추가 확인: 아래 누락은 이전 ZIP에 대한 판정이다. 두 필수 파일은 GitHub 저장소에는 이미 추적되어 있으므로 전체 checkout을 동기화하면 받는다. 2026-11-12 이후 두 PC의 작업 기준은 [GitHub 작업 절차](TWO_PC_GITHUB_WORKFLOW.md)이며, PC별 전용 DB 설정은 별도로 준비한다.

## 실행 필수 누락

| 파일 | 확인 근거와 영향 |
|---|---|
| `tools/generate_text_to_sql.py` | `application/text_to_sql_service.py`의 `generate_in_worker()`가 이 파일을 별도 Python 프로세스로 실행한다. 운영에 파일이 없으면 SQL 생성에 실패한다. 패키지 생성기의 허용 디렉터리에 tools가 없어 선정에서 제외된다. |
| `llm_integration/model_config.py` | 포함된 `local_llm.py`와 생성 워커가 모델 설정 클래스·로더를 import한다. 운영에 호환 파일이 없으면 import 또는 모델 로딩에 실패한다. 수정일 기준 선정만으로 실행 의존성을 보장할 수 없다. |

두 파일은 소스 통합본과 별도 모델 묶음 모두에 없다. 운영에 이미 같은 파일이 존재하는지는 이번 로컬 점검으로 확인할 수 없으므로, 운영 존재를 가정하여 이관 완료로 처리하면 안 된다.

## 포함 확인

Text-to-SQL 직접 관련 실행 파일 16개 중 14개 포함: `application/auth_service.py`, `application/inspection_frequency.py`, `application/text_to_sql_service.py`, `dbapi.py`, `llm_integration/local_llm.py`, `llm_integration/text_to_sql.py`, `static/text-to-sql-links.js`, `static/text-to-sql.css`, `static/text-to-sql.js`, `templates/base.html`, `templates/text_to_sql.html`, `web/routes/__init__.py`, `web/routes/text_to_sql.py`, `web/security.py`.

전체 소스 50개를 원본·사본·manifest·ZIP과 SHA-256 대조했다. 패키지 및 ZIP은 manifest와 일치하고 ZIP CRC도 통과했다. 현재 원본과는 `templates/base.html` 한 파일만 다르며 차이는 빈 줄의 공백 제거뿐이다. Text-to-SQL 기능 코드 차이는 없다.

루트 `requirements.txt` 및 `llm_integration/requirements.txt`는 의존성 검토용으로 분리되어 있다. 필요한 `sqlglot==27.29.0`, `llama-cpp-python==0.3.33` 설치 여부와 대상 CPU/GPU 환경 호환성은 운영에서 확인해야 한다.

별도 모델 묶음에는 Qwen·Gemma GGUF 2개와 검토용 `models.local.json`, LLM requirements가 있다. 파일 존재와 manifest 기재 크기 일치를 확인했다. 이번 점검에서 약 7GB 모델의 SHA-256은 재계산하지 않았다. 설정 검토 파일은 자동 적용 대상이 아니다.

## 운영 선행 파일 및 별도 지원 목록

기존 IRIS2의 `__init__.py`, `application/__init__.py`, `web/__init__.py`, `llm_integration/__init__.py`, `db_config.py`, `hx_configuration.py`도 이번 패키지에 없다. 기존 앱에 있는 기반 파일이라는 점과 Text-to-SQL 추가 파일 누락을 구별해야 한다. 특히 `llm_integration/__init__.py`가 모델 설정 모듈을 import하므로 운영 파일의 존재·호환성을 확인해야 한다. 이 목록은 전체 앱의 모든 공통 의존 파일을 새로 설치하는 목록은 아니다.

다음은 실행 웹 경로의 필수 파일과 구별되는 운영 지원·검증 자료이며 현재 소스 패키지에 없다. 관련 자료까지 모두 전달하려면 별도 지원 묶음에 포함할 항목이다.

- 계정 준비: `tools/provision_text_to_sql_account.py`. 현재 도구는 loopback:3307 및 iris2 스키마 제한이 있어 운영 주소에 무조건 실행할 수 없다. 이번에는 실행하지 않았다.
- CLI: `tools/run_text_to_sql.py`.
- 검증: `tools/verify_text_to_sql_live.py`, `tools/verify_text_to_sql_web.py`, `tools/verify_text_to_sql_browser.mjs`, `tools/verify_text_to_sql_links_browser.mjs`.
- 시험: `llm_integration/tests/test_text_to_sql.py`, `llm_integration/tests/test_model_config.py`, `tests/test_text_to_sql_web.py`, `tests/test_text_to_sql_scope.py`, `tests/test_text_to_sql_mariadb.py`, `tests/test_text_to_sql_links.cjs`, `tests/test_inspection_frequency.py`.
- 문서: `docs/TEXT_TO_SQL.md`, `docs/TEXT_TO_SQL_SCOPE_20261109.md`, `docs/TEXT_TO_SQL_FREQUENCY_20261109.md`.

`config/database-text-to-sql.conf`와 DB 계정·비밀번호는 기존 이관 정책에 따라 의도적으로 제외한다. 개발 설정을 복사하지 말고 운영 전용 SELECT 계정과 필요한 5개 테이블의 권한을 준비·검증해야 한다. 이번에는 config 디렉터리를 읽을 수 없어 로컬 설정 내용도 검사하지 않았다. 일반 사용자에게는 TEXT_TO_SQL 및 INSPECTIONS 조회 권한이 모두 필요하다.

## 검증 및 후속 조치

IRIS2 전용 `.venv/Scripts/python.exe`로 SQL 검증·웹 권한·복수 범위·검사 빈도 관련 단위시험 **67건 통과**. 실제 운영 DB 조회, 계정 생성, GGUF 추론, 서버 재시작은 수행하지 않았다.

이관 완료 판단 전 누락된 필수 2개 파일을 새 통합본에 포함하고 manifest·checksums·ZIP을 재생성해야 한다. 기반 모듈의 운영 호환성 및 전용 계정·의존성·모델 설정을 확인한 뒤 VCM1·VCM2의 로그인 → SQL 생성 → 읽기 전용 실행 → 상세 링크를 검증해야 한다.

기계 판독 증거: [inventory.json](../reports/text_to_sql/transfer-audit-20261112/inventory.json). 재대조 도구: `tools/audit_text_to_sql_transfer.py` (패키지는 읽기만 하고 보고서만 저장).
