# IRIS2 운영 필수 파일과 삭제 후보 정리

기준일: 2026-11-17 · 기준 소스: `d3f125b` · 위치: `C:\access\heat\iris2` · 범위: VCM1·VCM2

현재 운영 기능을 유지하려면 실행 코드뿐 아니라 MariaDB 실행 파일·실데이터·비공개 설정·PDF 원문·모델과 검토 산출물을 함께 보존해야 한다. 우선 정리할 대상은 Python 캐시와 사용이 끝난 임시 산출물이다. 개발·시험·이관 자료는 Git 또는 별도 보관본을 확보한 뒤 운영 배포본에서 제외할 수 있다.

이 문서는 삭제 기준이며 삭제 실행 기록이 아니다. 이번 점검에서는 파일 삭제, DB 변경, 서버 시작·중지를 하지 않았다. 웹 서버 가동 시에는 아래 실행 절차를 사용한다. 점검 중 기존 중지 시점 이후 다시 실행된 `server.py --host 0.0.0.0 --port 4824` 프로세스를 확인했으며, 이번 작업에서는 해당 프로세스를 변경하지 않았다.

## 1. 운영 실행 경로

```text
run.cmd → run.ps1 → start_mariadb.ps1
                       └─ runtime/mariadb-11.4.12-winx64/bin/mariadbd.exe
                          + data/mariadb/my.ini + data/mariadb 실데이터
           └─ .venv/Scripts/python.exe server.py --host 0.0.0.0 --port 4824
                 └─ app.py → services.py + web/security.py + web/routes
                      ├─ application / domain / ml / llm_integration
                      ├─ templates / static
                      ├─ config/database*.conf → MariaDB 3307
                      └─ 기능 실행 시 추가 모듈·파일·자식 프로세스 사용
```

`run.cmd`는 외부 접속을 허용하는 `0.0.0.0:4824`로 실행한다. `run.ps1`의 기본 주소는 `127.0.0.1`이다. `server.py`를 직접 실행하면 MariaDB를 자동 시작하지 않는다. `restart_iris2.ps1` 역시 현재는 `127.0.0.1`로 재시작하므로 LAN 접속을 유지할 때 실행 방식을 확인해야 한다.

정상 운영 시작 예:

```powershell
Set-Location -LiteralPath C:\access\heat\iris2
.\run.ps1 -ListenHost 0.0.0.0 -Port 4824 -NoBrowser
```

MariaDB가 이미 실행 중인 경우:

```powershell
.\.venv\Scripts\python.exe server.py --host 0.0.0.0 --port 4824 --no-browser
```

상태 확인:

```powershell
# DB 상태 검사. 웹 서버를 상주시켜 시작하는 명령은 아니다.
.\.venv\Scripts\python.exe server.py --health-check
# 웹 서버를 시작한 뒤 확인
Invoke-RestMethod http://127.0.0.1:4824/api/health
```

정상 응답의 주요 항목은 `application=iris2`, `status=ok`, `backend=mariadb`다. 새 PC에서는 DB 복원·계정·권한·모델 설정을 별도로 준비해야 하며 Git 업데이트만으로 준비되지 않는다.

## 2. 반드시 보존할 실행 코드와 설정

| 항목 | 역할과 보존 이유 |
| --- | --- |
| `server.py`, `app.py`, `__init__.py` | 현재 실행 진입점과 애플리케이션 구성. `legacy_*`는 실행 진입점이 아니다. |
| `services.py` | 대시보드·설비·검사·분석 서비스와 여러 하위 모듈의 연결점. |
| `web/`, `application/`, `domain/` | 라우트·권한·업무 서비스·계산 규칙. 폴더 전체 보존. |
| `templates/`, `static/` | 화면·PDF/인쇄 템플릿·JS·CSS·이미지·사용 중인 정적자원. 생성 파일처럼 보여도 화면이 참조할 수 있으므로 전체 삭제 불가. |
| `ml/` | 검사 우선순위·검토 화면 등이 실제 사용. 학습을 수동 실행하지 않는다는 이유로 삭제할 수 없다. |
| `llm_integration/` | AI 질의·Text-to-SQL·보고서 검토 코드. 모델 추론이 선택 기능이어도 코드 일부는 웹 라우트에서 시작 시 import한다. |
| `migration/` | 이관 자료만 있는 폴더가 아니다. 백업·복원에서 `migration/migrate_all.py`의 `engine_for`를 사용하므로 보존. |
| `hx_configuration.py`, `hx_configuration.conf` | 경로·접속 정책·권한 매핑·세션·계산 설정. 현재 설정 파일 형식과 필수 섹션 유지. |
| `database.py`, `db_config.py`, `dbapi.py`, `database_monitor.py` | MariaDB 연결·전용 읽기 계정·스키마 선택·DB 오류 기록. |
| `iris_v2_database.py`, `iris_v2_models.py`, `iris_v2_history.py` | 이름에 v2가 있어도 현재 MariaDB 런타임이 사용하는 코드. |
| `iris_v2_importer.py`, `iris_json_mapping.py`, `iris_json_validator.py`, `import_normalization.py` | JSON 적재와 서비스 초기 import에 사용. |
| `life_prediction.py`, `pressure_vessel_calculations.py`, `inspection_plan_rules.py`, `exchanger_type.py` | 잔여수명·압력 계산·검사계획·설비 분류. |
| `backup_manager.py`, `mariadb_operations.py` | 스케줄 백업·백업 관리·독립 복원. 서버가 백업 스케줄러도 시작한다. |
| `excel_export.py`, `excel_export_worker.py` | Excel 내보내기. worker는 시작 시 import되지 않아도 실제 요청에서 별도 Python 프로세스로 실행된다. |
| `asset_paths.py`, `pdf_ocr_review.py`, `pdf_tube_sheet_geometry.py` | 증빙 경로·PDF 검토·PDF 기반 Map 좌표 추출. 일부는 기능 실행 시 지연 import한다. |
| `hx_ml.py` | `ml/anomaly.py`에서 지연 import하는 분석 코드. 독립 실행 예제라고 보고 삭제하지 않는다. |
| `tools/generate_text_to_sql.py` | 일반 Text-to-SQL 질문의 로컬 모델 추론 자식 프로세스. **tools 폴더 전체 삭제 불가.** |
| `.venv/` | 현재 운영 Python 패키지. 재설치·검증된 대체 환경 없이 삭제 불가. |
| `runtime/mariadb-11.4.12-winx64/` | DB 서버와 백업·복원용 MariaDB 클라이언트 실행 파일. |
| `config/database.conf` | 앱 DB 계정·스키마 설정. |
| `config/database-readonly.conf` | ML 및 일반 읽기 전용 DB 기능. |
| `config/database-text-to-sql.conf` | Text-to-SQL 전용 SELECT 계정. 보고서·유체별 집계 기능도 사용한다. |
| `config/database-admin.conf` | 백업·복원·관리 도구용 로컬 계정. 기본 웹 읽기와 별개지만 전체 운영 기능 유지에 필요하다. |
| `run.cmd`, `run.ps1`, `start_mariadb.ps1` | 현재 DB·웹 시작 절차. 직접 실행만 사용할 경우에도 운영 복구를 위해 보관 권장. |
| `requirements-lock.txt`, `requirements.txt`, `requirements-ml*.txt`, `llm_integration/requirements.txt`, `setup.ps1` | 환경 재구성 자료. 현재 `.venv`를 대체하는 파일은 아니며 설치 후 별도 검증 필요. |

`.venv/pyvenv.cfg`는 이 PC의 Python 3.14.10 설치를 가리킨다. `.venv`만 남기고 기반 Python 설치를 지우면 실행이 깨질 수 있다. 운영 명령과 시험은 항상 iris2의 `.venv/Scripts/python.exe`를 사용한다.

위 표는 폴더 정리 시 보존할 핵심 항목이다. 표에 없는 Python 파일이 곧 삭제 가능하다는 뜻은 아니다. 기능별 지연 import와 예약 작업 호출을 함께 확인해야 한다.

## 3. 삭제하면 안 되는 운영 데이터

| 항목 | 보존 기준 |
| --- | --- |
| `data/mariadb/` 전체와 `my.ini` | 실제 MariaDB 데이터·시스템 테이블·설정. 웹 서버를 중지해도 DB가 별도로 실행 중일 수 있다. 파일을 임의로 삭제하거나 실행 중인 디렉터리를 단순 복사하지 않는다. |
| MariaDB의 `iris2`, `iris2_ml`, `iris2_llm`, `iris2_pdf` | 업무·ML 검토·LLM 보고서·PDF 검토 스키마. 실제 매핑은 로컬 설정 기준. 기존 복원/시험 스키마 정리는 별도 DB 작업이다. |
| `data/.session_secret` 및 사용 중인 비밀 설정 | 기존 세션·서명 토큰의 기준. 삭제 시 새 키가 생성되거나 설정에 따라 접속·검증이 달라진다. |
| `data/pdf_reports/` | 열교환기별 검사 보고서 조회의 원본 PDF. Text-to-SQL 보고서 링크에도 필요하다. |
| `data/source_json/`, `data/asset_path_map.json` | 증빙 원본과 이전 절대 경로를 iris2 내부 파일에 연결하는 매핑. DB 참조와 대조 전 삭제 불가. |
| `data/uploads/`, `data/reports/` | 현재 설정상 업로드·보고서 위치. 첨부·사용자 생성 자료는 보존. |
| `outputs/ml_implementation/` | 현재 `artifact_root`. ML 검토 화면이 읽는 실행 결과·모델·지문 자료. outputs 전체를 임시 결과로 보고 삭제하지 않는다. |
| `outputs/`의 LLM 보고서 자료 | `llm_integration/report_workflow.py`에서 보고서 산출 경로를 사용. 검토/승인·추적 자료인지 확인 후 개별 정리. |
| `llm_integration/models.local.json`, 사용 중인 GGUF 모델·네이티브 라이브러리 | 일반 자연어 SQL·AI 모델 추론 유지에 필요. 유체 집계·PDF 링크 요청이 모델 없이 된다는 이유로 일반 SQL용 모델까지 삭제하면 안 된다. |
| `backups/config/backup_settings.json` | 백업 시간·보관 정책. 지우면 기존 정책을 잃고 기본 설정이 생성될 수 있다. |
| `backups/files/`, 백업 로그 | 복구본과 검증 이력. 설정된 보관 정책과 독립 복원 확인 후 오래된 것만 정리. |
| `logs/text_to_sql/` | 질의·범위·SQL·결과 상태 사용 이력. 감사 기록이므로 캐시와 구분한다. |
| `reports/checking_report.md` | 현재 설정의 `cumulative_report` 경로. reports 폴더 전체 삭제 전에 이 경로도 확인한다. |

`data/heat_exchanger_db3.db`, `data/ml_review_feedback.db`처럼 설정·코드에 남은 `.db` 명칭은 현재 MariaDB 스키마를 선택하기 위한 호환 식별자로 쓰인다. 이 명칭만 보고 SQLite가 현재 운영 저장소라고 판단하지 않는다. 실제 `.db` 파일이 남아 있다면 별도 원본/스냅샷 여부를 확인하고 보존 결정을 내린다. 운영 SQLite를 쓰기 가능한 이관 원본으로 사용하지 않는다.

## 4. 정리 가능한 폴더와 파일

### 재생성 가능한 캐시

| 대상 | 조건과 영향 |
| --- | --- |
| 프로젝트 코드의 `__pycache__/`, `*.pyc` | 소스 `.py`가 보존된 경우 정리 가능. 다음 실행에서 재생성된다. `.venv`까지 일괄 정리할 필요는 없다. |
| `tmp/`의 사용 완료된 브라우저 캡처·검증 결과·임시 HTML | 관련 작업 종료와 미보관 결과 여부를 확인한 뒤 개별 정리. 세션 파일은 Git에 올리지 않는다. |

### 별도 보관 후 운영 배포본에서 제외 가능한 항목

| 대상 | 삭제 또는 제외 조건 |
| --- | --- |
| `tests/`, 루트 `test_*.py`, `llm_integration/tests/` | 웹 요청 처리에는 불필요. 회귀시험은 개발 PC/Git에 유지한다. 시험을 실행하는 예약 작업이 없는지 확인한다. |
| `test_data/` | API 510 검증 사례 등 시험 자료. 시험 보관본을 확보한 경우 운영 배포본에서 제외 가능. |
| `verification/` | 과거 검증 산출물. 인수·감사 증빙을 별도 보관한 경우 제외 가능. |
| `.taste-skill/` | 개발·UI 검증 자료. 보존할 화면 증빙이 없다면 정리 후보. |
| `.agents/`, `skills-lock.json` | 개발 에이전트·브라우저 검사 도구. 웹 런타임에는 불필요하나 현재 브라우저 검증 도구가 `.agents`의 CDP 모듈을 사용한다. 삭제보다는 운영 배포본에서 제외하는 방식 권장. |
| `dist/`의 배포 ZIP | 실행 중인 앱이 ZIP을 직접 읽지 않는다. 외부 보관본과 복구 경로가 확보되면 로컬 중복본 정리 가능. `*private*.zip`은 비공개 설정·업무 데이터를 포함할 수 있으므로 일반 소스와 분리 보관한다. |
| `runtime/mariadb-11.4.12-winx64.zip` | 압축 해제된 런타임과 재설치용 보관본을 확인한 뒤 중복 ZIP만 정리 가능. 압축 해제 폴더는 삭제 금지. |
| `database_snapshot/` | 현재 웹 런타임은 읽지 않는 과거 복원 자료. 유일한 복구본이 아닌지 확인하고 백업·검증 기록과 함께 별도 보관한 뒤 제외. |
| `data/import/`의 과거 이관 스냅샷 | 현재 DB와 별개인 이관 재현 자료. `LATEST.txt`와 연결된 자료·유일 원본·재현 필요성을 확인한 뒤 보관/정리한다. data 전체 삭제 근거가 되지 않는다. |
| `llm_integration/reference/` | 원본 참고 코드와 출처 자료. 현재 실행 코드와 구분해 Git 보관 후 배포본에서 제외 가능. |
| `legacy_app.py`, `legacy_server.py` | 미이식 참고 코드. 현재 런처가 아니므로 배포본에서 제외 가능. Git의 참고 이력은 유지한다. |
| `server_v3.py` | `iris2.server.main`을 호출하는 호환 런처. 표준 실행에는 불필요하지만 예약 작업/바로가기가 사용하면 보존한다. |
| 루트 `hx_v6.html` | 현재 Flask 화면은 `templates/`에서 로드한다. 디자인 참고 파일은 배포본에서 제외 가능하되 직접 열어 쓰는 사용자 자료인지 확인한다. |
| 1회성 보정·적재 스크립트 | 아래 항목 참고. 실행 경로·예약 작업에서 사용하지 않으면 배포본 제외 가능. 데이터 정정 근거와 재현 이력은 Git/문서에 보존한다. |

1회성 스크립트 후보에는 `apply_e105_nominal_correction.py`, `backfill_reported_total_tube_counts.py`, `reconcile_tube_counts.py`, `load_inspection_history_existing_only.py`, `backfill_inspection_plans.py`, `master_heat_exchanger_import.py`, `export_management_data.py`가 있다. 현재 `server.py` 시작 경로의 필수 파일은 아니지만 수동 정비·적재·외부 작업에서의 사용 여부를 확인해야 한다. `load_inspection_history_existing_only.py`는 `backfill_inspection_plans.py`도 호출하므로 관련 도구를 일부만 남기는 방식은 피한다.

## 5. 폴더 전체를 삭제하면 안 되는 예외

| 폴더 | 일부 정리 가능하더라도 보존할 항목 |
| --- | --- |
| `tools/` | `generate_text_to_sql.py` 필수. 설치·복구를 위해 `provision_text_to_sql_account.py`, `grant_text_to_sql_tube_history.py`, `grant_text_to_sql_fluids.py`, 권한 복구 도구도 보관한다. 자동 시작/백업/보고서 예약 작업이 참조하는 스크립트는 유지한다. |
| `docs/` | `services.plugging_unavailable_guide()`가 `PLUGGING_UNCALCULABLE_GUIDE_20260807.md`를 읽는다. 삭제 시 도움말이 대체 문구로 바뀐다. 운영·복구·DB 전환 문서도 보관 권장. 원본 업무 DOCX/PDF는 Git 대상과 구분한다. |
| `outputs/`, `reports/`, `logs/`, `backups/` | 화면·검토·감사·복구 자료가 섞여 있다. 디렉터리명만 보고 생성 결과 전체를 삭제하지 않는다. |
| 루트 `uploads/`와 `data/uploads/` | 현재 설정은 `data/uploads`지만 기존 DB 증빙 경로·매핑·예약 작업이 루트 uploads를 참조할 수 있다. 비어 있거나 미참조임을 확인한 경우만 정리한다. |
| `config/` | DB 설정·실행 시 잠시 생성하는 MariaDB 클라이언트 옵션 파일이 있다. 현재 작업 중인 임시 파일까지 지우지 않는다. 파일 내용을 외부 공개하거나 Git에 추가하지 않는다. |
| `migration/` | `mariadb_operations.py`에서 `migrate_all.engine_for`를 import한다. 폴더명만 보고 이관 완료 후 불필요하다고 판단하면 백업·복원이 손상된다. |
| `.git/` | 웹 실행에는 직접 필요하지 않아도 두 PC 소스 동기화·이력·복구에 사용한다. 현재 Git 기반 운영 checkout에서는 삭제하지 않는다. |

`compose.yaml`은 현재 `run.cmd`의 로컬 MariaDB 실행 경로에서 사용하지 않는다. 별도 컨테이너 배포를 운영하는 경우를 확인한 뒤 배포본 포함 여부를 정한다. `README.md`, `AGENTS.md`, `APPLICATION_BOUNDARY.md`, requirements/설치 문서는 용량 절감 효과가 작고 운영 기준이므로 보관을 권장한다.

## 6. 실제 정리 시 적용 순서

1. 정리 범위를 iris2 내부의 구체적인 파일/폴더 목록으로 확정한다. 원본 `C:\access\heat\iris`와 부모 환경은 건드리지 않는다.
2. `git status`로 소스 변경을 보존하고, 비공개 설정·업무 파일·모델·감사/복구 자료는 별도 백업한다. Git에 올린 코드만으로 이 자료가 복원되지는 않는다.
3. Python 캐시와 종료된 임시 작업부터 정리한다. 개발 파일은 저장소 자체에서 지우기보다 별도 운영 배포본에서 제외한다.
4. 예약 작업의 Action, 바로가기, 시작 스크립트, DB 파일 경로/매핑을 대조한다. 이 문서는 설치된 모든 Windows 예약 작업의 미사용 여부를 보증하지 않는다.
5. 운영 DB 디렉터리와 계정은 코드 청소 대상에서 제외한다. DB 백업·복원은 검증된 논리 백업 절차를 사용한다.
6. 정리한 파일 목록과 복구 위치를 남긴다. 웹 서버 재가동은 정리 작업과 구분해 수행한다.

삭제 후 재가동을 승인해 수행할 때는 상태 API 외에 로그인·VCM1/VCM2 조회·Tube Map·Excel·검사 PDF·일반 Text-to-SQL·유체별 집계·백업을 확인한다. 시작 시 import 성공만으로 이 기능들이 모두 보존됐다고 판단하지 않는다.

## 7. 점검 근거와 배포 시 주의점

- `server.py`를 import해 iris2 내부 모듈 79개의 시작 시 로드 경로를 확인했다. 실제 서버를 시작하지 않았다. 이 목록은 지연 import·자식 프로세스·예약 작업의 전체 목록을 대신하지 않는다.
- `web/routes/__init__.py`, `services.py`, `hx_configuration.py`, `dbapi.py`, `asset_paths.py`에서 라우트·업무·설정·증빙 연결을 확인했다.
- `excel_export.py`의 별도 worker 실행, `application/text_to_sql_service.py`의 `tools/generate_text_to_sql.py` 실행, `mariadb_operations.py`의 migration 의존성, `ml/anomaly.py`의 hx_ml 지연 import를 별도로 확인했다.
- `tools/build_production_zip.py`는 날짜가 고정된 기존 패키징 도구다. 현재 소스에서는 필수인 `tools/generate_text_to_sql.py`를 패키지에 넣는 처리가 없으므로, 해당 ZIP 생성만으로 최신 Text-to-SQL이 모두 포함된다고 판단하지 않는다. 기존 `dist` ZIP을 최신 운영 코드의 대체본으로 취급하지 않는다.
- `tools/start_iris_background.ps1`는 `server.py --no-browser`를 실행하며 기본 loopback 주소를 사용한다. 설치된 예약 작업이 이 스크립트를 참조하는지, LAN 공개가 필요한지 확인해야 한다.

이번 작업 범위는 점검과 문서 작성이다. 패키징 코드 수정, 실제 삭제, 모델/데이터 이동, 예약 작업 수정, 웹 서버 재시작은 포함하지 않는다.
