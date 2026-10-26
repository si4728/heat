# IRIS v3 현재 코드 리뷰

- 작성일: 2026-08-16
- 대상: `C:\access\heat\iris2` 및 현재 운영에 사용되는 `C:\access\heat\tools`
- 기준 DB: schema 3.5.0
- 리뷰 방식: 핵심 실행 경로 정적 검토, 운영 DB 읽기 전용 확인, 전체 회귀 테스트 실행
- 테스트 결과: 57개 통과

> 개선 상태: 2026-08-16에 CR-01부터 CR-09까지 코드 반영 완료. 회귀 테스트는
> 59개로 확대되어 모두 통과했으며, 상세 결과는
> `CODE_REVIEW_IMPROVEMENTS_20260816.md`를 참조한다.

## 1. 종합 판정

DB 3.5 레이아웃과 JSON 적재 구조의 연계성은 양호하며, 공통 장비 식별자 처리,
원문 JSON 보존, 외래키 설정, SQLite WAL 및 회귀 테스트도 적절하게 구성되어 있다.

다만 현재 설정 그대로 외부 네트워크에 서비스를 노출하거나 관리자 upsert 도구를 다시
실행하는 것은 권장하지 않는다. 보안 3건과 데이터 재처리·파생이력 관련 3건을 먼저
보완해야 한다.

| 등급 | 건수 | 의미 |
|---|---:|---|
| Critical | 1 | 운영 노출 전 반드시 수정 |
| High | 4 | 다음 배포 전 수정 |
| Medium | 3 | 단기 개선 |
| Low | 1 | 예방적 개선 |

## 2. 주요 Findings

### CR-01 · Critical · 예측 가능한 세션 비밀키로 외부 인터페이스가 기동됨

**근거**

- `iris/hx_configuration.conf:7`: 기본 host가 `0.0.0.0`
- `iris/hx_configuration.conf:16`: `secret_key = iris-v3-local-system`
- `iris/app.py:66`: 해당 값을 Flask `SECRET_KEY`로 사용
- `iris/app.py:96-100`: 세션에는 인증 판단에 사용되는 `user_id`가 저장됨

**영향**

기본 비밀키를 아는 사용자가 Flask 세션 쿠키를 위조할 수 있다. 유효한 관리자 ID를
추측하면 관리자 세션으로 인식될 가능성이 있으며, 기본 host가 모든 인터페이스이므로
동일 네트워크에서도 공격 표면이 열린다.

**권고**

1. 비밀키를 환경변수 또는 별도 secret 파일에서만 읽는다.
2. 기본값·예제값·짧은 값이면 서버 시작을 거부한다.
3. 기본 host를 `127.0.0.1`로 변경한다.
4. 외부 서비스 시 TLS reverse proxy를 사용하고 `SESSION_COOKIE_SECURE=true`를 적용한다.

### CR-02 · High · 인증 사용 중에도 모든 `api_*` endpoint가 인증 검사를 우회함

**근거**

- `iris/app.py:92-109`: endpoint 이름이 `api_`로 시작하면 인증·권한 검사를 생략
- `iris/app.py:698-741`: 장비 목록과 검사 이력 API가 별도 인증 없이 조회 가능
- 검사 이력 응답에는 장비, 검사일, 공정, 업체 원문 정보가 포함됨

**영향**

화면 로그인을 활성화해도 `/api/v1/exchangers` 및 history API는 공개 상태다. 서버가
`0.0.0.0`으로 실행되면 비로그인 사용자가 검사·운영 정보를 조회할 수 있다.

**권고**

공개 endpoint는 `/api/health`만 명시적으로 허용하고, 읽기 API에는 로그인 세션 또는
별도의 read token/scope를 요구한다. 인증 활성 상태에서 비로그인 API 요청이 401/403인지
검증하는 테스트를 추가한다.

### CR-03 · High · 관리자 JSON upsert가 감육 평가 전체를 삭제하고 재생성하지 않음

**근거**

- `tools/upsert_iris_json_v31_to_db_v3.py:573`: `tube_degradation_assessment` 전체 삭제
- `tools/upsert_iris_json_v31_to_db_v3.py:695-705`: batch 완료 후 바로 commit
- 이 스크립트에는 감육 평가 재생성 호출 또는 INSERT가 없음

**영향**

현재 운영 DB에서 이 도구를 다시 실행하면 기존 감육 평가가 모두 사라진 상태로 commit될
수 있다. JSON 원본과 검사 결과는 남아도 잔여수명·추세 기능이 불완전해진다.

**권고**

감육 평가 삭제를 제거하거나 동일 트랜잭션/후속 필수 단계에서 재생성한다. commit 전에
기존·신규 평가 건수를 비교하고, 0건 또는 비정상 감소 시 rollback해야 한다.

### CR-04 · High · Master 누락으로 부분 적재된 동일 JSON을 정상 재시도할 수 없음

**근거**

- `iris/iris_v2_importer.py:673-683`: 적재 가능한 보고서가 없어도 `source_document` 생성
- `iris/iris_v2_importer.py:693-702`: Master 미존재 보고서는 건너뛰지만 페이지는 저장
- `iris/iris_v2_importer.py:735-741`: 0건 적재도 `COMPLETED_WITH_WARNINGS` 처리
- `iris/iris_v2_importer.py:657-660`: 같은 SHA가 있으면 상태·적재 건수와 무관하게 duplicate로 종료

**영향**

Master를 나중에 보완해도 원본 JSON SHA가 이미 등록되어 표준 importer는
`SKIPPED_DUPLICATE`를 반환한다. 실제로 보고서가 하나도 적재되지 않은 문서도 정상 완료된
중복 문서처럼 취급된다.

**권고**

`source_document`에 `load_status`, 기대/적재/누락 보고서 수를 관리하고, 완료 조건을
명확히 한다. `PARTIAL` 또는 적재 0건 문서는 누락 보고서만 재처리할 수 있어야 한다.

### CR-05 · High · 표준 import의 DB 적재와 후처리가 하나의 완료 단위가 아님

**근거**

- `iris/iris_v2_importer.py:654-741`: DB 적재 transaction이 먼저 commit
- `iris/iris_v2_importer.py:742-751`: 이후 보고서 파일 작성, 감육 평가 재계산, batch 경로 갱신
- `iris/app.py:669-680`: 후처리 예외가 발생하면 화면에는 전체 처리가 `FAILED`로 표시됨

**영향**

보고서 파일 쓰기 또는 감육 평가 재계산이 실패하면 DB 적재는 이미 완료됐지만 사용자는
실패로 인식한다. 재시도 시에는 SHA 중복으로 건너뛰어 후처리 복구가 어려워질 수 있다.

**권고**

DB 적재와 후처리 상태를 `LOADED`, `POSTPROCESSING`, `COMPLETED`, `POSTPROCESS_FAILED`로
분리한다. 후처리는 idempotent하게 만들고 batch ID를 기준으로 재실행할 수 있게 한다.

### CR-06 · Medium · 배포 빌더가 운영 DB와 고정 비밀키 설정을 배포본에 포함함

**근거**

- `tools/build_deployments_folder.py:22-39`: 백업·임시 폴더만 제외하고 운영 DB는 제외하지 않음
- `tools/build_deployments_folder.py:54`: `iris` 디렉터리 전체 복사
- 따라서 `iris/data/heat_exchanger_v3.db`와 `iris/hx_configuration.conf`가 포함됨

**영향**

배포본 전달 시 검사 데이터, 사용자 password hash, 운영 설정 및 알려진 세션 비밀키가 함께
전달될 수 있다.

**권고**

기본 배포에서는 `*.db`, `*.db-wal`, `*.db-shm`, 실제 `hx_configuration.conf`를 제외한다.
데이터 포함은 `--include-data` 같은 명시적 옵션으로만 허용하고, 신규 환경용 sanitized
설정 템플릿을 생성한다.

### CR-07 · Medium · 상태 변경 HTML form에 CSRF 방어가 없음

**근거**

- templates에 POST form이 26개 존재
- CSRF token, Flask-WTF 또는 요청 헤더 검증 구현이 없음
- 장비, 검사계획, 튜브 상태, 정비, 사용자 및 JSON import가 cookie 기반 세션으로 수행됨

**영향**

로그인 사용자가 공격자가 제어하는 페이지를 방문할 때 의도하지 않은 상태 변경 요청이
발생할 수 있다. `SameSite=Lax`가 위험을 일부 낮추지만 동일 site의 다른 origin과 운영
환경 구성까지 완전히 방어하지는 않는다.

**권고**

전역 CSRF middleware를 적용하고 모든 POST/PUT 요청에 token을 검증한다. API token 기반
endpoint는 정책에 따라 별도로 제외한다.

### CR-08 · Medium · 관리자 upsert가 기본적으로 실제 변경 모드이며 백업·사후검증이 없음

**근거**

- `tools/upsert_iris_json_v31_to_db_v3.py:729-735`: `--dry-run`을 지정하지 않으면 즉시 변경
- 도구 내부에 SQLite Backup API 호출이 없음
- commit 전에 `integrity_check`, `foreign_key_check`, 핵심 건수 비교 gate가 없음

**영향**

운영자가 옵션을 누락하면 바로 실제 DB가 변경된다. transaction rollback은 예외에는
효과적이지만, 논리적으로 잘못된 정상 commit은 보호하지 못한다.

**권고**

기본값을 dry-run으로 바꾸고 실제 변경에는 `--apply`를 요구한다. 자동 백업, 예상 건수,
외래키, 무결성, 검사 ID 보존 및 파생이력 건수 검사를 모두 통과해야 commit하도록 한다.

### CR-09 · Low · 감육 추세 기준일이 검사일이 아니라 보고서 작성일로 고정됨

**근거**

- `iris/iris_v2_history.py:287-299`: `report_date`로 필터·정렬·그룹화
- `iris/iris_v2_history.py:329-355`: 해당 날짜 차이로 연간 감육률 계산

**영향**

현재 운영 DB 435건은 `inspection_date`와 `report_date`가 모두 같아 실제 영향은 없다.
향후 보고서 작성일이 검사일보다 늦은 자료가 들어오면 검사 간 경과기간과 감육률이
왜곡될 수 있다.

**권고**

측정 기준일은 `COALESCE(inspection_date, report_date)`로 통일하고, 두 날짜가 다른 fixture로
추세 계산 테스트를 추가한다.

## 3. 테스트 및 품질 관찰

### 확인된 강점

- 전체 회귀 테스트 57개가 통과한다.
- JSON 식별자 규칙이 `iris_json_mapping.py`로 통합되어 validator와 importer 간 차이가 줄었다.
- SQLite 연결마다 외래키, WAL, busy timeout을 적용한다.
- JSON importer의 보고서 단위 적재는 하나의 DB transaction으로 처리된다.
- 원문 JSON과 구조화 필드를 함께 보존하여 재검증 가능성이 높다.
- 장비 Master 미존재 시 임의 장비를 생성하지 않고 적재를 차단한다.
- 현재 운영 DB는 `integrity_check=ok`, 외래키 위반 0건이다.

### 부족한 회귀 시나리오

다음 시나리오는 현재 자동 테스트에서 직접 보장되지 않는다.

1. 인증 활성 상태에서 읽기 API 비로그인 차단
2. CSRF token 누락 요청 차단
3. Master 누락으로 0건 적재된 동일 SHA 문서의 재처리
4. 표준 importer 후처리 실패 후 재개
5. 관리자 upsert 후 감육 평가 건수 보존
6. 배포 manifest에 DB·secret 파일이 포함되지 않는지 확인
7. 검사일과 보고일이 다른 경우의 감육률 계산

코드 coverage 도구가 개발 의존성에 포함되어 있지 않아 line/branch coverage 수치는 산출하지
못했다. 기능 테스트 통과와 별개로 위 위험 경로에 대한 테스트를 우선 추가해야 한다.

## 4. 권장 개선 순서

1. **즉시:** secret key 외부화, 기본 host 변경, 공개 API 범위 축소
2. **즉시:** upsert의 감육 평가 삭제 문제 수정 및 자동 백업·검증 gate 추가
3. **다음 배포 전:** 부분 적재 재시도와 후처리 재개 가능한 import 상태 모델 도입
4. **다음 배포 전:** 배포본에서 운영 DB·실제 설정 제외
5. **단기:** CSRF 보호와 관련 보안 테스트 추가
6. **단기:** 검사일 기준 추세 계산으로 통일

## 5. 최종 의견

현재 코드는 데이터 구조와 일반 조회·적재 기능 면에서는 안정적인 편이다. 그러나 보안 기본값과
관리자 upsert 경로는 운영 위험도가 높다. 특히 CR-01, CR-02, CR-03은 외부 배포 또는 JSON
재upsert 전에 반드시 해결해야 한다. 본 리뷰는 문제 식별만 수행했으며 코드 수정은 포함하지
않았다.
