# 운영 DB 변경 확인·적용 안내

작성일: 2026-11-20 (KST) · 대상: IRIS2 / MariaDB 3307

이 문서는 운영 PC에서 DB 변경이 필요한지 판단하고, 적용 후 정상 여부를 확인하기 위한 안내입니다. 문서 작성 과정에서 원격 운영 DB에 접속하거나 변경하지 않았습니다. 개발 PC에서 적용됐다는 사실만으로 운영 PC에도 적용됐다고 판단하면 안 됩니다.

## 1. 이번 GitHub 변경 중 DB 적용 대상

| 변경 | 운영 DB 작업 |
| --- | --- |
| 대시보드 상단 집계 제거, 전체 생산팀 집계 통일 | 스키마·데이터 이관 없음. 새 소스의 조회 기준 적용 |
| 열교환기 목록의 분석 화면 이동, 분석 화면 구성·범례·표·그래프 개선 | 스키마 변경 없음 |
| 추세/단기와 장기 감육속도 중 큰 양수 선택 | 계산 소스 변경. 기존 검사 측정값을 일괄 수정하는 작업 없음 |
| 로그온·화면 접근 이력 | 아래 신규 테이블·인덱스·트리거·버전 표식 적용 필요 |

**코드 받기와 DB 마이그레이션, 웹 서버 재시작은 각각 별도 작업입니다.** Git에는 DB 파일·개인별 접속 이력·운영 설정·계정 비밀번호를 올리지 않았습니다.

소스 기준: `task/devpc-access-audit-20261119` 브랜치. 감사 기능 커밋 `3194180`, 대시보드·분석 변경 커밋 `3ae05a0`을 포함합니다. 이 문서 게시 시점에 main으로 병합됐다고 가정하지 말고 대상 브랜치를 확인하세요.

## 2. DB 변경 명세

마이그레이션 파일: [`migration/access_audit.py`](../migration/access_audit.py)

### 신규 테이블: `access_audit_event`

InnoDB / utf8mb4, 총 17개 컬럼입니다. 사용자 삭제 후에도 이력이 보존되도록 `user_id`에 FK를 두지 않았습니다.

| 컬럼 | 형식 | NULL | 용도 |
| --- | --- | --- | --- |
| `audit_event_id` | BIGINT, AUTO_INCREMENT, PK | 불가 | 이력 ID |
| `created_at` | DATETIME(6) | 불가 | 발생 시각, UTC |
| `request_id` | VARCHAR(32) | 불가 | HTTP 요청 식별자 |
| `audit_session_id` | VARCHAR(32) | 허용 | 로그인 접속별 추적 식별자, 인증 쿠키가 아님 |
| `user_id` | INT | 허용 | 사용자 ID, 비로그인·실패 시 없을 수 있음 |
| `username` | VARCHAR(100) | 불가 | 로그인 ID 스냅샷, 로그인 실패 시 제출 ID |
| `event_type` | VARCHAR(24) | 불가 | 접근·로그인·로그아웃·만료 등 |
| `result` | VARCHAR(16) | 불가 | 허용·거부·오류·이동·성공·실패 |
| `reason` | VARCHAR(40) | 불가 | 사유 코드 |
| `method` | VARCHAR(12) | 불가 | HTTP 메서드 |
| `path` | VARCHAR(1024) | 불가 | 접근 경로, 쿼리 문자열 제외 |
| `endpoint` | VARCHAR(120) | 불가 | 앱 엔드포인트 |
| `screen_key` | VARCHAR(60) | 불가 | 화면 코드 |
| `status_code` | INT | 불가 | HTTP 상태 |
| `client_ip` | VARCHAR(45) | 불가 | 직접 연결 IP |
| `user_agent` | VARCHAR(512) | 불가 | 브라우저 정보 |
| `duration_ms` | INT | 불가 | 응답 생성 처리시간(ms) |

### 인덱스·트리거·적용 표식

| 구분 | 이름 | 구성 / 동작 |
| --- | --- | --- |
| 기본키 | `PRIMARY` | `audit_event_id` |
| 인덱스 | `ix_access_audit_created` | `created_at, audit_event_id` |
| 인덱스 | `ix_access_audit_user_time` | `user_id, created_at` |
| 인덱스 | `ix_access_audit_session_time` | `audit_session_id, created_at` |
| 인덱스 | `ix_access_audit_event_time` | `event_type, created_at` |
| 인덱스 | `ix_access_audit_result_time` | `result, created_at` |
| 인덱스 | `ix_access_audit_request` | `request_id` |
| 트리거 | `access_audit_no_update` | BEFORE UPDATE → SQLSTATE 45000으로 차단 |
| 트리거 | `access_audit_no_delete` | BEFORE DELETE → SQLSTATE 45000으로 차단 |
| 적용 표식 | `schema_version.version` | `3.14.0-access-audit-1` 1행 추가 |

기존 기본 스키마 버전 `3.14.0`은 유지합니다. 기존 열교환기·검사·튜브 데이터를 이관·덮어쓰기·삭제하지 않습니다. 이후 실제 로그인에 따른 기존 `app_user.last_login_at` 갱신과 신규 감사 행의 누적은 정상 동작입니다.

## 3. 운영 DB의 현재 상태 확인 — 읽기 전용 SQL

운영 PC의 승인된 DB 클라이언트로 **운영 IRIS2 스키마를 선택한 후** 실행하세요. 아래 SQL에는 비밀번호나 특정 PC 계정명을 넣을 필요가 없습니다. 트리거 메타데이터는 조회 권한에 따라 보이지 않을 수 있으므로 누락으로 판단하기 전에 해당 스키마의 관리자 계정으로 재확인하세요.

### A. 대상 서버·스키마 확인

```sql
SELECT DATABASE() AS selected_schema,
       @@hostname AS database_host,
       @@port AS database_port,
       VERSION() AS database_version;
```

`selected_schema`가 운영 설정의 `iris2` 또는 `iris2` 접두 스키마와 일치하고, 해당 PC의 IRIS2 전용 MariaDB 3307인지 확인합니다. NULL이거나 다른 시스템 DB라면 이후 절차를 실행하지 말고 연결 대상을 바로잡으세요.

### B. 테이블·컬럼·인덱스·트리거 유무 확인

테이블이 아직 없어도 실행 가능한 메타데이터 조회입니다.

```sql
SELECT
  (SELECT COUNT(*) FROM information_schema.tables
   WHERE table_schema=DATABASE() AND table_name='access_audit_event') AS audit_table_count,
  (SELECT COUNT(*) FROM information_schema.columns
   WHERE table_schema=DATABASE() AND table_name='access_audit_event') AS audit_column_count,
  (SELECT COUNT(DISTINCT index_name) FROM information_schema.statistics
   WHERE table_schema=DATABASE() AND table_name='access_audit_event') AS audit_index_count,
  (SELECT COUNT(*) FROM information_schema.triggers
   WHERE trigger_schema=DATABASE() AND event_object_table='access_audit_event'
     AND trigger_name IN ('access_audit_no_update','access_audit_no_delete')) AS audit_trigger_count;
```

정상 적용 기대값: **1 / 17 / 7 / 2**. 인덱스 7개에는 기본키가 포함됩니다. 수량만으로 완전한 일치를 판단하지 말고 아래 정의도 대조하세요.

```sql
SELECT column_name, column_type, is_nullable, column_key, extra
FROM information_schema.columns
WHERE table_schema=DATABASE() AND table_name='access_audit_event'
ORDER BY ordinal_position;

SELECT index_name, non_unique,
       GROUP_CONCAT(column_name ORDER BY seq_in_index SEPARATOR ', ') AS index_columns
FROM information_schema.statistics
WHERE table_schema=DATABASE() AND table_name='access_audit_event'
GROUP BY index_name, non_unique
ORDER BY index_name;

SELECT trigger_name, action_timing, event_manipulation, action_statement
FROM information_schema.triggers
WHERE trigger_schema=DATABASE() AND event_object_table='access_audit_event'
ORDER BY trigger_name;
```

두 트리거의 본문에 `SIGNAL SQLSTATE '45000'`과 `IRIS2 audit history is append-only`가 있어야 합니다. 운영 이력에 실제 UPDATE·DELETE·TRUNCATE를 실행하여 시험하지 마세요. DB 관리자 권한으로 트리거를 제거하거나 테이블을 TRUNCATE하는 행위까지 이 기능이 막는 것은 아닙니다.

### C. 마이그레이션 표식 확인

```sql
SELECT version, applied_at, description
FROM schema_version
WHERE version IN ('3.14.0', '3.14.0-access-audit-1')
ORDER BY version;
```

판단 기준:

- **미적용:** 감사 테이블과 확장 표식이 없음 → 4절의 적용 절차 진행.
- **적용 완료:** B절의 정의·수량이 일치하고 확장 표식이 정확히 1행 있음 → 재생성할 필요 없이 5절 기능 확인.
- **부분 적용·상이한 정의:** 표식만 있거나, 컬럼·인덱스·트리거가 다르거나 일부만 있음 → 삭제·초기화하지 말고 원인을 확인. 아래 스크립트는 같은 정상 구조에는 재실행 가능하지만 모든 잘못된 기존 구조를 자동 수리하는 도구는 아님.

## 4. 운영 PC 적용 순서

### A. 소스·설정·백업 준비

운영 PC의 IRIS2 작업 폴더에서 실행합니다. 경로가 다르면 해당 PC의 IRIS2 경로로 바꾸세요.

```powershell
Set-Location -LiteralPath C:\access\heat\iris2
git status --short
git fetch origin
```

로컬 수정이 있으면 별도 작업 브랜치에 먼저 보존합니다. `reset --hard`나 강제 덮어쓰기를 사용하지 않습니다.

**소스를 교체하기 전에** 기존 백업 관리 기능으로 최신 MariaDB 백업이 정상 생성됐는지 확인하고, 원래 웹 앱의 실행 인자·LAN 접속 여부를 기록합니다. 기존 운영 절차로 **IRIS2 웹 앱만 중지**하여 소스·DB 변경 도중 접속하지 않게 하고 MariaDB는 유지합니다. 그 후 깨끗한 작업 폴더에서 대상 브랜치로 이동하고 fast-forward로만 갱신하세요. 실행 중인 이전 앱에 새 템플릿만 먼저 노출하지 않기 위한 순서입니다.

```powershell
git switch task/devpc-access-audit-20261119
git pull --ff-only origin task/devpc-access-audit-20261119
git log -3 --oneline
```

운영 PC의 `config/database.conf`와 `config/database-admin.conf`를 그대로 사용합니다. 개발 PC의 설정·계정·비밀번호·가상환경·DB 파일을 복사하지 않습니다. 두 설정의 서버·포트가 같은 운영 PC의 `127.0.0.1` 또는 `localhost`, 3307이어야 합니다. 앱 설정의 DB 이름은 `iris2` 접두 스키마여야 합니다.

### B. 계획 확인 및 명시적 적용

```powershell
.\.venv\Scripts\python.exe migration/access_audit.py
.\.venv\Scripts\python.exe migration/access_audit.py --apply
```

첫 명령은 예상 작업을 출력할 뿐 실제 DB 구조를 검증하거나 변경하지 않습니다. 실제 사전 확인은 3절 SQL로 수행합니다. 두 번째 명령이 DB에 적용합니다. 실행에는 운영 PC의 비공개 관리자 설정을 사용하고 비밀번호를 명령줄에 넣지 않습니다.

마이그레이션 계정은 대상 스키마의 테이블·인덱스 생성, 트리거 생성, 버전 표식 INSERT에 필요한 권한이 있어야 합니다. 앱 계정은 신규 테이블에 SELECT·INSERT 권한이 있어야 합니다. 다른 PC의 계정 생성·권한 부여는 Git 업데이트로 자동 처리되지 않으므로 운영 DBA가 해당 PC 권한을 확인합니다.

기대 메시지:

```text
Applied 3.14.0-access-audit-1 to configured iris2 schema; business data unchanged
```

명령이 실패하면 오류를 해결하기 전 적용 완료로 표시하지 않습니다. 테이블 생성·트리거 생성 도중 실패하면 일부 DDL이 남을 수 있습니다. `Existing audit schema differs` 또는 `Existing audit trigger differs`이면 정의를 대조하고 별도 검토하세요. 감사 테이블·기존 이력 삭제로 해결하지 않습니다.

### C. 검증 후 웹 앱 시작

3절 B·C의 SQL을 다시 실행해 **1 / 17 / 7 / 2**, 정상 정의 및 확장 표식 1행을 확인한 뒤, 운영 PC의 기존 시작 절차로 웹 앱을 시작합니다. LAN 접속을 사용하는 PC의 예시는 다음과 같습니다.

```powershell
.\.venv\Scripts\python.exe server.py --host 0.0.0.0 --port 4824 --no-browser
```

기존 예약 작업·서비스로 운영 중이면 해당 관리 절차를 이용해 중복 실행하지 않습니다. DB 계정 오류·포트 점유가 발생했을 때 다른 시스템이나 MariaDB 프로세스를 임의로 종료하지 않습니다.

## 5. 운영 적용 후 확인

### 웹 화면·기록 확인

1. `http://127.0.0.1:4824/api/health`에서 IRIS2 / MariaDB / status `ok` 확인.
2. 정상 계정으로 새로 로그인하고 대시보드·열교환기 목록·분석 등 업무 화면 방문 후 로그아웃.
3. 관리자로 다시 로그인 → 관리자 설정 → **로그온·화면 접근 이력** (`/settings/access-logs`). 로그인·화면 접근·로그아웃 기록과 접속 식별자 연결 확인.
4. 기간·이벤트·사용자 검색, CSV 다운로드 확인. 화면은 KST이며 CSV는 같은 조건의 최신 10,000건까지 제공.
5. 일반 사용자로 이력 화면·CSV 접근 시 403, 비로그인 시 로그인 화면 이동 확인. 인증을 비활성화한 개발 설정에서도 이력 화면·CSV는 공개되지 않음.
6. 브라우저 개발자 도구의 실제 업무 응답에서 `X-Audit-Recorded: 1` 확인. `0`이면 감사 저장 실패이며 서버 오류 로그·앱 DB 권한을 점검. 관리자 화면의 이력 저장 실패 경고도 확인.

상태 점검·정적 파일은 기록 대상이 아니므로 health 호출만으로 감사 행이 늘지 않는 것은 정상입니다. 이력이 처음에는 0건일 수 있으며 과거 로그인 이력을 소급 생성하지 않습니다. 서버 프로세스 시작만으로 로그인 성공 이력이 생성되지는 않습니다.

### DB에서 누적·최근 기록 확인 — 개인정보를 출력하지 않는 SQL

신규 테이블 존재 확인 후 실행하세요.

```sql
SELECT COUNT(*) AS total_events,
       MIN(created_at) AS first_event_utc,
       MAX(created_at) AS latest_event_utc,
       DATE_ADD(MAX(created_at), INTERVAL 9 HOUR) AS latest_event_kst
FROM access_audit_event;

SELECT event_type, result, status_code, COUNT(*) AS event_count
FROM access_audit_event
GROUP BY event_type, result, status_code
ORDER BY event_type, result, status_code;
```

로그인 성공·실패 이벤트와 HTTP 접근 이벤트는 별도 행입니다. 따라서 전체 행 수를 로그인 횟수나 사용자 수로 해석하면 안 됩니다. 새 로그인에서 생긴 접속 식별자를 기준으로 화면 이동을 묶어 추적할 수 있습니다.

## 6. 적용 범위와 운영 기록

비밀번호·쿠키·토큰·쿼리 문자열·요청 본문은 저장하지 않습니다. 브라우저 종료는 감지하지 않으며, 미사용 만료는 다음 요청에서 확인될 때 기록합니다. 저장 실패 요청은 누락될 수 있고 실패 횟수 표시는 서버 재시작 시 초기화됩니다. 자동 삭제·무기한 무결성 보증·DB 필드별 변경 전후 비교 기능은 포함하지 않습니다. 자세한 기능·검증 내역은 [`log_improve.md`](../log_improve.md)를 참고하세요.

운영 담당자는 적용 일시(KST), 대상 스키마·서버, 적용 소스 커밋, B절 확인 결과, 버전 표식, 웹 동작·감사 저장 결과와 적용자를 내부 운영 기록에 남깁니다. 개인별 접속 로그·계정·비공개 설정은 GitHub 문서에 첨부하지 않습니다.

이번 문서 게시로 운영 DB가 자동 변경되지는 않습니다. 운영 측에서 위 절차를 수행한 뒤 실제 결과로 적용 완료 여부를 판단하세요.

문서 검증: 위 SQL 8문장을 개발 PC MariaDB에서 읽기 전용 트랜잭션으로 실행해 구문과 메타데이터 기대값을 확인했습니다. 운영 DB의 적용 완료를 대신하는 검증은 아닙니다.
