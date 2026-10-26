# 개선 DB Layout 코드 반영 결과

- 기준일: 2026-08-16
- 대상 애플리케이션: `C:\access\heat\iris2`
- 대상 스키마: db_v3 3.6.0

## 반영 범위

| 영역 | 반영 내용 |
|---|---|
| DB 경로 | 환경변수 우선순위를 보존하고 importer·이력 재계산에 명시적 DB 경로 전달 |
| 식별자 | 공통 resolver에서 장비 alias, bundle, scope, 원문 label을 분리 관리 |
| JSON 호환 | `iris_report_details`와 `iris_9000_report_details`를 모두 지원 |
| 적재 | 보고서 문맥, 업체 원문·브랜드·페이지, 페이지 inventory, 첨부, 요약 이력을 정규 테이블에 저장 |
| 날짜 | 연도형 설치·교체일자를 원문·연도·정밀도로 보존 |
| 튜브 | 설계두께, 보고 깊이, 결함코드, 원문 단위, 비고를 전용 필드로 저장 |
| 중복 방지 | SHA 중복과 동일 논리 파일명의 상이한 SHA를 구분하여 차단 |
| 화면/API | 검사일자, bundle/scope, 공정·유체·업체 출처 및 튜브 상세정보 노출 |
| Excel | `검사보고서` 시트와 신규 튜브 상세 컬럼 추가 |
| 스키마 사전 | IRIS 핵심 테이블과 3.4/3.5 필드를 `schema_*_dictionary` 관리 대상으로 확대 |
| 감사 도구 | 실제 importer와 같은 공통 resolver를 사용하는 읽기 전용 감사 도구로 교체 |
| 배포 | legacy 루트 앱 대신 정식 `iris` 앱을 패키징하도록 빌더 수정 |

## 장비 식별 규칙

- `E-331A(BTM)` → `equipment_code=E-331A`, `scope_code=BTM`
- `E-241B(NORTH)` → `equipment_code=E-241B`, `scope_code=NORTH`
- `E-201B + FRONT` → `equipment_code=E-201B`, `scope_code=FRONT`
- `AE-332` → 승인 alias `E-332`
- `E-332-1`, `E-332-2` → `equipment_code=E-332`, `bundle_code=1/2`

명시적인 JSON `bundle_code`와 `scope_code`가 있으면 suffix 추정보다 우선한다.

## 운영 검증 기준

1. 전체 단위·통합 테스트가 통과해야 한다.
2. 복제 DB에서 JSON upsert 후 건수, 외래키, 무결성을 확인한다.
3. 감사 도구는 DB를 읽기 전용으로 열고 Master 미연결 및 필수 컬럼 누락을 보고한다.
4. 운영 DB 변경 전 SQLite Backup API로 백업한다.
5. 정식 실행 진입점은 `iris/server.py`, 데이터 경계는 `iris/data/heat_exchanger_v3.db`다.

## 검증 결과

- 전체 회귀 테스트: 59개 통과
- 표준 importer 최신 JSON 검증: 11개 파일, 보고서 435건, 튜브 결과 6,067건
- `PE` 생산라인 자동 판별: 보고서 10건, 튜브 결과 79건 정상 적재
- 보고서 부가 문맥: 93건 구조화 확인
- 검사 업체 원문·출처: 435건 구조화 확인
- 첨부 및 요약 이력: 각 435건 생성 확인
- 잘못된 `*_EXTRACTION` 인력 role: 0건
- 복제 DB upsert: 기존 검사 ID 435건 전부 보존, 신규 ID 0건
- SQLite: `integrity_check=ok`, 외래키 위반 0건
- 운영 DB 핵심 건수 유지: 검사 435건, 튜브 결과 6,067건, 원문 페이지 2,456건
- 읽기 전용 매핑 감사: 필수 컬럼 누락 0, Master 미연결 0

## 관련 파일

- `iris/iris_json_mapping.py`
- `iris/iris_json_validator.py`
- `iris/iris_v2_importer.py`
- `iris/iris_v2_database.py`
- `iris/iris_v2_history.py`
- `iris/services.py`
- `iris/app.py`
- `iris/excel_export.py`
- `tools/audit_db_v3_json_mapping.py`
- `tools/build_deployments_folder.py`
- `iris/docs/schema_v3_6.sql`
