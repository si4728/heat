# IRIS 비JSON Load 기능 테스트 결과 보고서

- 시험일: 2026-08-16 (Asia/Seoul)
- 대상 프로젝트: `C:\access\heat\iris2`
- 운영 데이터베이스: `C:\access\heat\iris2\data\heat_exchanger_v3.db`
- 판정: **PASS**

## 1. 시험 목적과 범위

개선된 DB layout을 사용하는 현재 코드에서 JSON Load 기능을 제외한 웹 화면, API, 계산, 조회, 등록·수정 workflow, Excel 출력, 보안 경계 및 DB 무결성을 회귀 시험하였다.

이번 시험에서 의도적으로 제외한 범위는 다음과 같다.

- JSON 파일 업로드, 구문·스키마 검증, dry-run, 실제 import
- JSON 중복 판정, 부분 실패 재처리, upsert 및 load-result modal
- JSON 장비명 정규화와 `scope_code` 매핑
- `/imports`의 JSON Load POST 동작

대시보드와 메뉴에서 JSON Load 화면으로 이동 가능한지는 일반 UI 구성의 일부로 확인했지만, Load 실행 및 운영 DB 쓰기는 수행하지 않았다.

## 2. 종합 결과

| 구분 | 결과 | 비고 |
|---|---:|---|
| 비JSON 자동화 회귀 시험 | 42/42 통과 | 실패 0, 오류 0, 건너뜀 0 |
| 프로젝트 공식 가상환경 health check | 통과 | schema 3.6.0, integrity ok |
| 운영 DB 읽기 전용 route smoke test | 26/26 통과 | 모두 HTTP 200 |
| 브라우저 핵심 화면 렌더링 | 12/12 통과 | 화면 오류 표시 및 console 오류 0 |
| 로그인 화면 브라우저 검사 | 통과 | redirect, 입력 필드, CSRF 확인 |
| Excel 출력 검증 | 통과 | 6개 worksheet와 행 수 검증 |
| 운영 DB 무결성 | 통과 | FK 위반·고아 결과·중복 current spec 0 |
| 운영 DB 무변경 확인 | 통과 | 핵심 5개 테이블 시험 전후 건수 동일 |

자동화 시험은 프로젝트 공식 Python 환경인 `.venv\Scripts\python.exe`에서 실행했으며 총 21.364초가 소요되었다. 별도의 시스템 Python 교차 실행도 42/42 통과하였다.

## 3. 기능별 자동화 시험 결과

| 기능군 | 주요 검증 내용 | 결과 |
|---|---|---:|
| 인증·권한 | 로그인/로그아웃, 비밀번호, 역할 권한, 인증 필요 route | PASS |
| 요청 보안 | CSRF, API token, application boundary, 404 처리 | PASS |
| 대시보드 | 통계와 주요 조회 화면 응답 | PASS |
| 열교환기 | 목록, 정렬, 상세, 신규 등록, 수정, media 처리 | PASS |
| Master Data | plant/unit, 열교환기 master import, natural key, type mapping | PASS |
| 검사 | 검사 목록·상세·이력, 검사 업체·software, tube result | PASS |
| 검사 계획 | 계획일, 미검사 설비, 계획 조회·처리 | PASS |
| Tube | tube 관리, tube map, 상태와 벽감소율 색상 | PASS |
| 잔여수명 | 계산, 검색, simulation, spec revision·side summary | PASS |
| 정비·작업지시 | maintenance 및 work-order workflow | PASS |
| 문서·출력 | 개별 report, PDF 목록, Excel export | PASS |
| DB schema | provenance/context 컬럼, schema dictionary, server settings | PASS |

등록·수정·작업지시 등 쓰기 기능은 임시 시험 DB fixture에서 실행하였다. 운영 DB에는 GET과 읽기 전용 검증만 수행하였다.

## 4. 운영 DB 읽기 전용 route 시험

아래 26개 URL은 실제 운영 DB를 연결한 Flask test client에서 모두 HTTP 200을 반환했다.

| 영역 | 확인 route |
|---|---|
| 대시보드·목록 | `/`, `/exchangers`, `/inspections`, `/inspection-plans`, `/maintenance`, `/quality-issues` |
| Master·설정 | `/master-data/plants-lines`, `/settings/wall-loss-colors` |
| 열교환기·검사·Tube 상세 | `/exchangers/14`, `/inspections/1`, `/tubes/1`, `/exchangers/14/tubes/manage`, `/exchangers/14/report` |
| Tube map·잔여수명 | `/exchangers/14/tube-map`, `/api/exchangers/14/tube-map`, `/remaining-life/tubes`, `/exchangers/14/remaining-life-simulation` |
| PDF | `/pdf-reports/2020/VCM1` |
| API | `/api/health`, `/api/v1/exchangers`, `/api/v1/exchangers/14/history` |
| Excel | `/exports/heat-exchangers-tubes.xlsx` |
| 정적 자산 | `/assets/hanhwa_solution2.jpg` 및 three.js 관련 자산 2건 |

운영 DB에는 작업지시 데이터가 0건이어서 실제 작업지시 상세 페이지를 열 수 없었다. 다만 임시 DB 통합 시험에서 작업지시 생성, 상세 열람, 상태 변경, maintenance 연계까지 통과했다.

## 5. 브라우저 UI 시험

인증을 비활성화한 읽기 전용 로컬 시험 인스턴스에서 다음 12개 핵심 화면을 Chrome으로 직접 렌더링했다.

- 대시보드
- 열교환기 목록 및 상세
- 검사 목록 및 상세
- Tube 상세 및 Tube map
- 잔여수명
- 검사 계획
- 정비
- 품질 이슈
- Plant/Unit master

모든 화면에서 제목, H1, 본문 데이터가 정상 출력되었으며 화면 내 오류 문구와 browser console warning/error는 없었다. Tube map은 2D 화면뿐 아니라 3D 전환 후 canvas 렌더링까지 확인했다.

인증 활성 인스턴스에서는 `/` 접근 시 `/login?next=/`로 정상 redirect되었고, 로그인 제목, 이메일·비밀번호 입력란, CSRF hidden field가 정상 표시되었다. 실제 사용자 자격증명 입력은 수행하지 않았다.

브라우저 대시보드에 표시된 주요 값은 다음과 같다.

- 열교환기 900건
- 검사 435건
- 물리 Tube 2,251건
- Tube 검사 결과 6,067건
- 미해결 품질 이슈 434건

## 6. Excel 출력 검증

`/exports/heat-exchangers-tubes.xlsx` 결과를 workbook으로 다시 열어 구조와 행 수를 검증했다.

| Worksheet | 검증 결과 |
|---|---:|
| 요약 | 존재 및 열기 성공 |
| 교환기 | 900 data rows |
| 튜브 | 2,251 data rows |
| 검사보고서 | 435 data rows |
| 검사이력 | 6,067 data rows |
| 상태변경이력 | 존재 및 열기 성공 |

총 6개 worksheet가 모두 생성되었고 파일 파싱 오류는 없었다.

## 7. 운영 DB 상태와 무결성

| 점검 항목 | 결과 |
|---|---:|
| schema version | 3.6.0 |
| SQLite integrity check | ok |
| Foreign key 위반 | 0 |
| source document | 11건, 전부 `LOADED / COMPLETED` |
| Plant / Unit | 1 / 6 |
| Equipment / Heat exchanger | 900 / 900 |
| Inspection | 435 |
| Tube result | 6,067 |
| Tube degradation assessment | 3,835, 전부 algorithm 1.3.0 |
| Inspection plan | 319 |
| Inspection provider | 2 |
| 업체가 누락된 execution | 0 |
| 중복 current specification | 0 |
| 고아 tube result | 0 |

운영 DB read-only 시험 전후 핵심 건수는 아래와 같이 동일했다.

```text
(inspection, tube_result, tube_degradation_assessment, inspection_plan, maintenance)
시험 전: (435, 6067, 3835, 319, 0)
시험 후: (435, 6067, 3835, 319, 0)
```

## 8. 제한 사항

- 요청에 따라 JSON Load 전 과정은 시험하지 않았다.
- 운영 DB의 안전을 위해 등록·수정·삭제 동작은 임시 DB에서만 검증했다.
- 실제 사용자 계정으로 로그인하지 않았으며 인증·권한은 자동화 시험과 로그인 화면에서 검증했다.
- 부하, 장시간 안정성, 동시 사용자 경쟁 조건, TLS 및 외부망 보안 침투 시험은 본 범위에 포함하지 않았다.
- 운영 DB에 작업지시가 없어 실제 데이터 기반 작업지시 상세 화면은 확인하지 못했으나 임시 DB workflow 시험으로 보완했다.

## 9. 최종 판정

JSON Load 기능을 제외한 현재 시험 범위에서 기능 실패는 발견되지 않았다. 자동화 42건, 운영 데이터 route 26건, 브라우저 핵심 화면 12건, Excel 출력 및 DB 무결성 검증이 모두 통과했으므로 현재 버전의 비JSON 기능은 **PASS**로 판정한다.
