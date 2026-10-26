# IRIS2 MariaDB 전환 결과

2026년 10월 17일 기준, 단계별 구현·시험·결함 수정·재시험을 수행하고 IRIS2의 업무 화면을 MariaDB에 연결했다. 기존 `C:\access\heat\iris`는 변경하지 않았다. 현장 사용자 인수와 엔지니어 승인은 기술 전환 결과와 별도로 진행한다.

## 단계별 결과

| 단계 | 작업 | 결과 |
|---|---|---|
| 1 | 원본 기준선·전체 데이터 대사 | 원본 62개 테이블, 78,120행 필드 대사 일치 |
| 2 | ORM·업무 화면 연결 | SQLite 초기화·마이그레이션을 분리하고 MariaDB 세션 사용 |
| 3 | 보조 저장소·분석 연결 | LLM·ML·PDF 검토 데이터 연결, 분석 전용 SELECT 계정의 쓰기 차단 검증 |
| 4 | 원본 파일·Excel | PDF 11개·JSON 11개를 독립 복사하고 해시 검증, 3명 동시 Excel 다운로드 시험 통과 |
| 5 | 등록·수정·권한·동시성 | 별도 시험 DB에서 업무 Workflow·CSRF·권한·중복·롤백·동시 사양 개정 검증 |
| 6 | 백업·복원·회귀·실행 전환 | 4개 스키마 별도 복원 후 데이터·뷰·트리거 비교 일치, 테스트 57개·조회 경로 48개 통과 |

## 수정한 주요 문제

- MariaDB가 반환하는 날짜 객체를 문자열처럼 자르던 화면 오류를 수정했다.
- 상태 점검·Excel·ML에서 SQLite PRAGMA와 직접 파일 연결을 제거했다.
- MariaDB의 파생 테이블 별칭과 Upsert 문법을 적용했다.
- SQLite에서 제한되지 않던 정비 이벤트 코드 길이를 MariaDB에 맞게 확장했다.
- 설비 수정 화면의 갱신 시각을 확인하고, 오래된 화면에서 저장하면 재조회를 요구한다.
- 사양 기간 중복 검사는 별도 기간 검증 테이블과 트랜잭션 잠금으로 보호한다. 이전 스냅샷을 가진 연결과 동시 작성자 시험을 모두 통과했다.
- Excel은 테이블별 트랜잭션 변경 카운터로 캐시를 무효화한다. 외부 SQL 수정도 감지한다.
- DB 충돌·입력 오류·접속 장애를 비밀정보 없는 HTTP 오류로 처리한다.
- PDF의 원본 경로는 근거 보존을 위해 DB에 유지하되 실제 열람은 IRIS2 내부 복사본만 사용한다.

## 데이터와 스키마

| 스키마 | 원본 테이블 | 현재 테이블 |
|---|---:|---:|
| iris2 | 57 | 59 |
| iris2_llm | 1 | 1 |
| iris2_ml | 2 | 2 |
| iris2_pdf | 2 | 2 |
| 합계 | 62 | 64 |

추가된 두 테이블은 `iris2_database_revision`과 `iris2_spec_revision_guard`이며, 원본 업무 데이터를 대체하지 않는 운영 보조 테이블이다. 기존 업무 행과 ID는 유지했다. 명시적인 시간대가 있는 날짜는 UTC로 정규화했고, 원래 시간대가 없는 값은 기존 시각을 유지했다. 원본 표기와 스키마는 SQLite 백업본에 보존되어 있다.

이관 대상은 공정별 필터 없이 기존 활성 DB 전체이다. VCM3·VCM4 제외 조건은 신규 개발·현장 검수 범위에만 적용하며 기존 행을 삭제하지 않는다. 과거 백업 DB와 구형 중복 DB는 원래 위치에 보존한다.

## 실행과 설정

```powershell
cd C:\access\heat\iris2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_mariadb.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

접속 주소는 `http://127.0.0.1:4824`이다. 로그인 후 기존 계정·권한으로 업무 화면을 사용한다. DB는 `127.0.0.1:3307`의 독립 MariaDB 11.4.12이다. 기존 3306 서비스와 IRIS 서버는 변경하지 않는다.

접속정보는 `config/database.conf`, 관리자 정보는 `config/database-admin.conf`, 분석 전용 정보는 `config/database-readonly.conf`에 저장한다. 업무용 설정의 `[schemas]`에서 네 저장소의 연결 대상을 지정한다. 실제 설정 파일은 Git에서 제외되며 접근 권한이 제한되어 있다. 설정 변경 후 앱을 재시작한다.

## 백업과 복구

백업 관리 화면은 네 스키마를 하나의 일관된 논리 백업으로 저장한다. 백업에는 업무 테이블·뷰·트리거·앱 사용자·권한이 포함된다. MariaDB 서버 계정·비밀번호와 PDF·JSON 파일은 포함하지 않는다. 설정 파일과 원본 파일은 별도로 보존해야 한다.

화면의 복원 검증은 별도 스키마를 생성하며 현재 업무 DB를 덮어쓰지 않는다. 운영 복구 시에는 입력 중지, 복원본 대사, 업무용 `[database]`·`[schemas]` 설정 변경과 앱 재시작, 연결 검증 순서로 진행한다. 원본 SQLite는 과거 시점이므로 새 업무 입력 이후 단순히 되돌리면 안 된다.

## 검증 재실행

```powershell
.\.venv\Scripts\python.exe tools/run_validation.py
.\.venv\Scripts\python.exe tools/transition_smoke.py
```

`tools/run_validation.py`는 MariaDB 전용 통합시험과 계산·정규화 회귀시험을 실행한다. 쓰기 시험은 `iris2_test_transition`에만 반영한다. 기존 SQLite 임시 DB 생성을 전제로 작성된 과거 시험과 일회성 SQLite 정정 도구는 MariaDB 운영 경로가 아니다.

상세 증거는 `reports/mariadb_transition`에 있다. 주요 파일은 `progress.json`, `validation.json`, `route_smoke.json`, `final_restore_drill.json`, `final_summary.json`, `live_http.json`이다.

## 남은 현장 확인

- 현장 사용자 업무 시나리오·실제 장치·장시간 LAN 부하에 대한 인수 확인
- 기존 API 510 계산의 엔지니어 검산·승인 절차
- 로컬 LLM 모델 파일·추론 라이브러리의 독립 설치와 대상 PC 성능 검증

ML 이상치 및 공간·패턴 분석은 MariaDB에서 재실행해 `PASS_WITH_NOTE`를 받았다. 이 상태는 모델의 자동 공학 판정이나 운영 승인 완료를 뜻하지 않는다. 기존 데이터가 추가로 입력되는 IRIS와 IRIS2는 자동 동기화하지 않는다.
