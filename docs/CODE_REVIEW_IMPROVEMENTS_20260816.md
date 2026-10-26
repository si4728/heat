# IRIS v3 코드 리뷰 개선 결과

- 반영일: 2026-08-16
- 대상 리뷰: `CODE_REVIEW_20260816.md`
- 적용 schema: 3.6.0

## 반영 결과

| Review ID | 상태 | 개선 내용 |
|---|---|---|
| CR-01 | 완료 | 기본 host를 localhost로 변경하고 예측 가능한 비밀키를 제거. 환경변수 또는 로컬 난수 secret 사용 |
| CR-02 | 완료 | health와 token 보호 write API만 공개 예외로 두고 읽기 API에 로그인·화면 권한 적용 |
| CR-03 | 완료 | 관리자 upsert 후 감육 평가를 필수 재생성하고 실패 상태·복구 백업 경로 기록 |
| CR-04 | 완료 | Source 문서에 PARTIAL 상태와 기대/적재/누락 건수를 관리하고 동일 SHA 재시도 지원 |
| CR-05 | 완료 | 적재와 후처리 상태를 분리하고 후처리 실패 문서를 동일 SHA로 재실행 가능하게 변경 |
| CR-06 | 완료 | 배포본에서 운영 DB, WAL/SHM, session secret과 실제 설정을 제외하고 sanitized 설정 생성 |
| CR-07 | 완료 | 모든 cookie 기반 POST form에 CSRF token 추가 및 서버 검증 적용 |
| CR-08 | 완료 | upsert 기본 모드를 dry-run으로 변경하고 `--apply`, 자동 백업, FK·건수·무결성 gate 추가 |
| CR-09 | 완료 | 감육 알고리즘 1.3.0에서 검사일 우선, 보고일 fallback으로 측정 기준일 통일 |

## DB 3.6 변경

`source_document`에 다음 필드를 추가했다.

- `load_status`
- `expected_report_count`
- `loaded_report_count`
- `missing_report_count`
- `postprocess_status`
- `postprocess_message`

기존 11개 문서는 모두 `LOADED / COMPLETED`로 backfill되었으며 검사·튜브 결과 ID와
건수는 변경되지 않았다.

## 검증 결과

- 전체 회귀 테스트: 59개 통과
- 관리자 upsert dry-run: 보고서 435건, 튜브 결과 6,067건
- 관리자 upsert 복제 DB 실제 적용: 검사 ID 435건 보존, 신규 ID 0건
- 감육 평가 재생성: 3,835건, algorithm 1.3.0
- 운영 DB: 검사 435건, 튜브 결과 6,067건
- 운영 source 문서: 11개 모두 `LOADED / COMPLETED`
- SQLite 무결성: `ok`
- 외래키 위반: 0건

## 백업

운영 DB 변경 전 다음 백업을 생성했다.

`iris/backups/heat_exchanger_v3_before_security_import_state_20260816.db`
