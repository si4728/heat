# 전체 요청 1:1 기능·코드·화면 점검

> 이후 사용자 요청으로 F01의 S:STEAM→STEAM 분류를 적용했다. 현재 Shell STEAM 37대·Tube STEAM 2대이며, 두 별칭 질문과 공정별 집계가 일치한다. [적용·검증 기록](STEAM_CLASSIFICATION_20261126.md)을 참고한다. 아래는 해당 분류 적용 전 기능 소스 `8ec41ce`의 점검 기록이며 F02·F03은 남아 있다.

2026-11-26 · 기능 소스 `8ec41ce` · PE·VCM1·VCM2 · 운영 위치 `C:\access\heat\iris2`

## 판정 요약

기존 완료 보고를 전제로 삼지 않고 요청을 기능·코드·화면에 대조했다. 아래 표는 대화에서 요청한 내용과 첨부 예시 8개, 이후 발견한 R1~R5를 연결한다. 같은 요청의 반복 지시는 해당 항목으로 모았으며, 이전 고객 분석 검토 문서의 8개 항목은 V01~V08에서 추가 대조했다.

**전체를 무조건 완료로 판정하지 않는다.** 주요 조회·보정·Plugging·대기열과 예시 8개는 동작했다. 남은 보완은 다음과 같다.

| 번호 | 남은 사항 | 실제 근거 | 적용 범위·주의 |
| --- | --- | --- | --- |
| F01 | STEAM 표기 정규화 | 정확히 `STEAM`인 Shell 15대·Tube 2대가 조회된다. VCM1의 `S:STEAM` 22대는 별도 그룹이어서 해당 질문에서 빠진다. | `S:`·`T:` 등 측 표기 정규화 정책이 필요하다. `HP STEAM`, `MEDIUM STEAM`, `STEAM CONDENSATE`를 같은 유체로 합칠지는 별도 분류 문제이며 임의 통합하지 않는다. |
| F02 | 유체 조건 목록의 설비별 행·이동 | ‘STEAM인 열교환기 목록’도 현재는 측/유체별 2행과 쉼표로 연결된 설비 목록이다. 설비별 분석 조회의 한 대당 한 행·설비 링크와 표시 방식이 다르다. | 집계 질문은 현 형식을 유지하고 목록 질문은 설비별 행으로 구분하는 보완이 필요하다. |
| F03 | AE-502A/B/D의 원본 검사·번들 식별 | 세 대 모두 표본 10본이지만 `AMBIGUOUS_INSPECTION`이며 수명은 산정 불가다. 실제 화면에도 번들 식별 필요 사유가 표시된다. | 안전하게 추정을 차단하는 코드는 정상이다. 그러나 고객의 ‘표본이 충분한데 미산정’이라는 자료 문제는 해결 완료가 아니다. 동일 날짜의 검사·번들·튜브 연결을 원본과 대조해야 한다. |

E-122A는 원본의 **Thickness 열이 공란**이다. 2.77mm는 설계/NDD 참고두께로, 실측으로 확정해 적재하지 않았다. 원본 제약과 기능 미구현을 구분한다. 잔여수명 DB 스냅샷 저장은 사용자가 이번 범위에서 제외하고 별도 진행하기로 답변한 항목이다.

이번 작업은 점검·근거 수집이다. 제품 기능이나 운영 업무 데이터를 수정하지 않았다. 운영 포트 4824는 계속 중지 상태이며, 화면 쓰기 검증은 복제 MariaDB에서만 수행했다.

## 근거 표기와 검증 범위

| 표기 | 실제 근거 | 확인 내용 |
| --- | --- | --- |
| D | `reports/all-requests-audit-20261126/readonly-data.json` | SELECT 전용 계정의 운영 데이터 점검 23개. 403대의 수명·구간·순위 대조, 보정값, 원본 해시, 보고서 파일·페이지, 권한·업무 revision 확인. ‘한계가 존재함’과 ‘안전하게 차단함’을 확인한 검사도 포함하므로 23개 통과를 요구 전체 완료로 해석하지 않는다. |
| A | `browser/advanced/checks.json` | 8개 예시를 실제 템플릿·JS·인증된 HTTP·복제 DB로 실행. 브라우저 의견 모델은 TEST_STUB. |
| F | `browser/followups/checks-all.json` | 생산팀 구간/합계 링크, E-111 27.44%, E-122A 실측/참고두께와 3개 화면 폭. |
| X | `browser/pdf-fluid-queue/checks.json` | 세 공정 PDF 응답, 유체·상태·30%·수명 조회, 실제 FIFO 대기/가득 참 안내·결과 표 유지. 모델 작업은 시험용 지연/대체 응답. |
| P | `browser/plugging/checks.json` | Map에서 2본 완료, 취소, 실제 수량 복원, 등록자·일자 이력. |
| S | `browser/single-plugging/checks.json` | 복수 선택 모드를 끈 상태의 1본 완료·취소·Map·수량 복원. |
| L | `browser/analysis-history/checks.json` | 무검사 설비 유지, 초기 Summary·선택 복귀, QR·명칭, 표본/번들 사유와 PE 6대의 실제 화면. |
| C | `browser/correction-screens/checks.json` | E-13·E-122A·E-341·E-222·E-811·E-331A를 각각 열어 최신 분석 입력·날짜·분모·보조 표시를 확인. |
| M | `native-model-queue.json` | 대체 없이 실제 로컬 Gemma SQL 생성·실행과 다른 사용자의 종합 의견. `running/queued → succeeded/running → succeeded/succeeded`, 대기 3건 뒤 추가 요청 429, 다른 사용자의 결과 조회 차단. |
| T | 이번 자동 시험 실행 | Python 284개 통과(42.509초). JavaScript 선택·두께 추이·차트·링크 4개 통과. 유효/무효·날짜·권한·CSRF·동시 완료·취소·서명·대기열 경계 포함. |

표의 `browser/...`와 M은 모두 로컬 `reports/all-requests-audit-20261126/` 아래다. 원본 PDF·화면·세션·설정·업무 데이터는 Git에 포함하지 않는다. 화면은 실제 Chrome/Edge에서 확인했고 1440/768/390px를 사용했다. 표 내부 가로 스크롤과 문서 전체 넘침을 구분했다.

PDF는 등록 검사 **435회 모두 파일과 시작 페이지 매핑**을 찾았다. PE·VCM1·VCM2 대표 링크는 인증된 브라우저에서 PDF MIME·`%PDF-` 본문을 확인했다. E-341·E-222·E-122A의 원본 페이지를 별도로 렌더링해 확인했다. PE 10대의 등록 날짜는 연결된 원본 페이지 주변의 일자와 재대조했다. 모든 435회 PDF의 측정표 전체를 재추출·전수 해석한 검사는 아니다.

## 운영·Git·기존 문서 요청

| ID | 요청 항목 | 기능·실행 근거 | 코드·문서 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| O01 | 현재 local 운영 위치 확인 | iris2 가상환경으로 실행, MariaDB health `ok`, FK 이상 0 | `APPLICATION_BOUNDARY.md`, `server.py`, `db_config.py` | 운영 경계 항목, 웹 화면 대상 아님 | 확인 |
| O02 | GitHub 변경 확인·local 반영 | 시작 시 fetch, local main/원격 main 모두 `8ec41ce`, 수신 누락 없음 | Git HEAD·origin/main 이력 | Git 상태 확인 | 완료 |
| O03 | 전체 변경 GitHub 게시·main 병합 | 선행 구현과 순차 보완 소스가 main에 포함됨 | `8ec41ce`까지 fast-forward 이력 | Git 상태 확인 | 완료 |
| O04 | 서버/서비스 중지 유지 | 포트 4824 listener 0, 임시 검증 서버만 사용 | `server.py`, 임시 `make_server`의 `finally` 종료 | 운영 화면은 띄우지 않음 | 완료 |
| O05 | 운영 필수 코드·삭제 후보 문서 | 문서 존재, 실제 health 경로 정상. 코드·DB·원문·모델의 보존과 캐시/개발 산출물 제외를 구분 | `docs/PRODUCTION_REQUIRED_FILES_AND_CLEANUP_20261117.md` | 문서 검토. 실제 삭제하지 않음 | 완료·기준일 주의 |
| O06 | Waitress queue 경고의 의미 | 요청 처리 스레드보다 대기 HTTP 작업이 생긴 상태를 뜻함. 숫자는 모델 대기 인원과 동일한 값이 아님 | `server.py`의 Waitress `threads=8`, 별도 `application/model_queue.py` | 로그 설명 항목. 부하량 전수 측정은 아님 | 설명 확인 |

O05 문서는 2026-11-17 소스·VCM 기준의 기록이다. 현재 실행 폴더 보존 규칙은 유효하지만 새 배포용 삭제 목록으로 사용할 때는 PE 포함 범위와 변경된 파일을 다시 대조해야 한다. 이 문서의 존재를 근거로 파일을 삭제하지 않았다.

## PDF·유체·Text-to-SQL 기본 결과

| ID | 요청 항목 | 기능·실행 근거 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| P01 | 열교환기별 IRIS 보고서 PDF 조회 | D: 435/435 파일·페이지 연결, 대표 PDF 응답 정상 | `services.find_inspection_pdf`, `web/routes/inspections.py` | X: PE·VCM1·VCM2 PDF 링크와 원본 렌더링 | 완료 |
| P02 | Text-to-SQL에서도 PDF 조회 | 설비/공정/검사 조건으로 검증된 보고서 링크 생성 | `application/text_to_sql_reports.py` | X: 3개 공정, 새 탭 링크·SQL 실행 비활성 확인 | 완료 |
| P03 | 유체명이 STEAM인 열교환기 목록 | 정확 일치 Shell 15·Tube 2. F01·F02 한계 확인 | `application/text_to_sql_fluids.py` | X: 설비별 행 대신 2개 집계 행 표시 | 보완 |
| P04 | 유체명으로 grouping | 현재 사양·측·공정별 집계, 미등록 별도, 그룹 내 설비 중복 제거 | 같은 모듈의 `proposal`·`execute` | X: 공정별 유체 그룹 표·차트 | 완료 |
| Q01 | PE까지 조회·검토 범위 확장 | D: PE 191·VCM1 81·VCM2 131 = 403대, 무검사 포함 | `text_to_sql_service.py`, `text_to_sql_scope.py` | A·X: PE 선택과 PE 결과, VCM3/4 제외 회귀 | 완료 |
| Q02 | 별도 화면을 만들지 않고 기존 Text-to-SQL 보완 | 기존 generate/execute/summarize 경로 유지 | `templates/text_to_sql.html`, `web/routes/text_to_sql.py` | A·X: 기존 질문 입력·결과 영역 | 완료 |
| Q03 | 기본 결과를 튜브가 아닌 열교환기당 한 행으로 | 기본 설비 결과의 ID 중복 없음. 생산팀·검사 회차 질문은 해당 집계 단위 | `application/text_to_sql_equipment.py`, `text_to_sql_advanced.py` | A·X: 설비/생산팀/회차 단위 표시 | 완료·유체 목록은 P03 |
| Q04 | 조건 해당 튜브 수를 설비별 표시 | 30% 이상인 설비의 해당 튜브 수가 양수이며 조건과 일치 | `text_to_sql_equipment.execute` | X: 30% 질문 표 | 완료 |
| Q05 | 열교환기별 최대 감육률·순위 | D: 403대의 순위 최대와 유효 분석 최대 일치 | `application/wall_loss_ranking.py`, `domain/current_measurements.py` | F: E-111 선택 목록 27.44% | 완료 |
| Q06 | 생산팀·공정·설비·설비명·최근 검사일 표시 | 설비 결과에 해당 열 존재, 검사일은 등록 근거 사용 | `text_to_sql_equipment.py`, `static/text-to-sql.js` | A·X: 헤더와 실제 표 확인 | 완료 |
| Q07 | 결과 표에서 내부 ID를 대신 노출하지 않기 | 설비 결과 열에 `_id` 필드 없음. 상세 링크용 키는 내부 유지 | 같은 모듈의 `columns`, `text-to-sql-links.js` | A·X: 표시 열 검사 | 완료 |
| Q08 | 설비 코드를 누르면 분석으로 이동 | 유효한 설비 키로 링크 구성, 집계 행은 대표 설비·회차 링크를 구분 | `static/text-to-sql-links.js` | A·F·X 링크 확인, T 링크 회귀 | 완료·유체 목록은 P03 |
| Q09 | 잔여수명은 분석 화면과 같은 값 | D: 대시보드·분석 공통 대표값 403대 대조, Text-to-SQL 공통 서비스 사용 | `application/equipment_summary.py`, `text_to_sql_equipment.execute` | A·X·L: 설비별 대표값·수명 조건 | 완료 |
| Q10 | 차기 검사 권고일도 분석과 같은 값 | 공통 `equipment_overview.recommendation_date`에서 조회 | `domain/inspection_recommendation.py`, 같은 조회 모듈 | A·X: 권고일 열, M: E-106 실제 의견 | 완료 |
| Q11 | 잔여수명 5년 이하 조건 조회 | 현재 조건 일치 14대. 산정 불가를 0년으로 치환하지 않음 | `text_to_sql_equipment.options`·`execute` | X: 14대 조회 | 완료 |

기본 설비 결과에서 검사일이 없는 설비는 공란을 다른 날짜로 꾸미지 않는다. ‘열교환기당 한 행’은 측정 튜브별 결과를 설비 결과로 집계한다는 뜻이다. 첨부 예시 수치와 현재 실제 DB 수치를 고정 일치시키지는 않는다.

## AI 종합 의견

| ID | 요청 항목 | 기능·실행 근거 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| A01 | 결과 아래 local LLM 종합 의견 | 실제 Gemma 의견 생성 성공. 생성 중·거절 상태에도 표 유지 | `text_to_sql_commentary.py`, `static/text-to-sql.js` | M 실제 모델, X 대기/거절 화면 | 완료 |
| A02 | 더 효과적·근거 있는 의견 생성 | 전체 집계·위험 순 후보·미산정·표본/비교 한계에서 사실 ID를 고르고 서버 문장으로 표시. 임의 숫자·설비는 차단 | `evidence`·`validate`, `text_to_sql_advanced.aggregate_evidence` | A 집계·회차 의견 단위, M 조회 요약·우선 확인 대상·해석의 한계 | 완료 |
| A03 | 현재 사용 모델명 회신 | 실제 모델명 `gemma-4-E4B-it-Q4_K_M` | `llm_integration/model_config.py`, 로컬 설정 로더 | M 실제 실행 모델·의견 표시 | 확인 |

예시 8개 정형 설비 질의는 서버가 지원 조건을 해석하고 분석 값을 조회한다. 일반 튜브 SQL 생성 및 종합 의견에는 로컬 모델을 사용한다. 임의 복합 조건·기간·운전조건까지 자유롭게 생성하는 기능으로 확대 해석하지 않는다. 이번 브라우저 일괄 검사는 TEST_STUB 의견을 사용했으며 실제 모델 검사는 M으로 분리했다. 유체 집계와 PDF 링크 결과에는 현재 설비 분석용 종합 의견을 붙이지 않는다.

## 잔여수명 구간·데이터 보정·표시

| ID | 요청 항목 | 기능·실행 근거 | 코드·원본 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| D01 | 검사 이력 없음은 IRIS 미실시로 분리 | D: 285대, Text-to-SQL도 285대 조건 일치 | `life_dashboard.life_band`, `equipment_summary.py` | X 상태 질문·P 대시보드 | 완료 |
| D02 | 한도 미도달을 산정 불가에 통합 | D: 산정 불가 29대, 별도 구간 없음 | `application/life_dashboard.py` | X 29대 질문·P 구간표 | 완료 |
| D03 | 표본 부족·감육 미검출·데이터 사유 표시 | 산정 불가 29대 모두 사유 존재 | `equipment_summary.build_equipment_summary` | P 대시보드, L 표본·번들 사유 | 완료 |
| D04 | E-13의 0%·미산정 처리 확인 | 유효 최대 0%, 산정 불가, 표본/양의 속도 부족 | D와 `application/equipment_summary.py` | C: 해당 설비 0%·산정 불가 표시 | 완료 |
| D05 | E-122A 최소두께 원본 확인·반영 | 원본 Thickness 공란, 실측 10본 NULL 보존. 설계/NDD 참고 2.77mm와 구분 | 원본 VCM1 36·38쪽, D | F: 실측 미등록·공칭 참고 2.770mm | 원본 제약 |
| D06 | E-341 최소두께 보정 | 검사 375의 10본 2.77mm, 원본 Thickness 열과 일치 | VCM1 142쪽, `customer_corrections_20261124.py`, D | 원본 렌더링·C 분석 입력 확인 | 완료 |
| D07 | E-222 수량 328→보고서 179본 | 현재 사양·활성 번들·해당 보고서 모두 179. 과거 328본 사양 보존 | VCM2 118쪽 Total Q'ty 179, 보정 원장, D | 원본 렌더링·C 분석 분모 확인 | 완료 |
| D08 | E-811 검사일 2020-10-24 | 이미 정상 등록된 값 재확인. 불필요한 재보정 없음 | D의 등록 검사일 | C 해당 설비 Summary의 2020-10-24 | 완료 |
| D09 | PE 2020 검사 10대 날짜·추정 입력 | 10대 모두 날짜 등록, 연결 원본의 일자 재대조 | D·`source-pdf/pe-dates.json` | L·P·A의 PE 분석/조회 | 완료 |
| D10 | 지정 PE 6대의 검사 시 기준 도달 표시 | E-131D·E-331B/C·E-341A/C·E-241B-1 모두 실측 도달 수량 양수. E-131D는 표본 5본이므로 설비 수명 0년을 강제하지 않음 | D·`equipment_summary.py` | L: 여섯 설비를 각각 열어 도달 표시와 2020년 일자 확인 | 완료 |
| D11 | E-331A 등의 2321년 보조 문구 정리 | D: 전체 대표/보조 표시에서 2321 미노출, 30년 상한 | `forecast_display`, `equipment_summary.py`, 분석 JS | C 해당 E-331A·F·L: 30년 이상 표시 | 완료 |
| D12 | 실측/NDD·공칭 참고두께 표시 구분 | 선택 검사의 공란을 이전 Map 값으로 채우지 않음. 현재 공란 검사에 가짜 추이 점 없음 | `static/precision-analysis.js`, `tube-thickness-trend.js` | F: E-122A 실측·공칭 분리, 실제 과거 이력 유지 | 완료 |

‘IRIS 미실시’는 시스템에 검사 이력이 등록되지 않았다는 뜻으로 안내한다. 실제 현장에서 한 번도 검사하지 않았음을 입증한 전수 자료 확인은 아니다. E-13·E-122A·E-341·E-222의 현재 최대 감육률 0%와 산정 불가도 D에서 각각 확인했다.

## Plugging 등록·취소·이력

| ID | 요청 항목 | 기능·실행 근거 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| G01 | Map에서 튜브 1개 선택·등록 | 단일 선택 후 완료 수량 +1, 취소 후 원복 | `static/analysis-plugging.js`, `application/plugging_operations.py` | S 단일 모드 실제 클릭 | 완료 |
| G02 | Map에서 여러 튜브 선택·등록 | 2본 선택·완료 후 실제 수량 +2 | 같은 모듈 | P 복수 선택 실제 클릭 | 완료 |
| G03 | Plugging 일자와 함께 저장 | 완료 일자·등록 일시를 구분. 잘못된 날짜 입력 거절 회귀 | `plugging_operations.apply` | P·S 입력 필드·저장 이력 | 완료 |
| G04 | 잘못 등록한 완료 취소 | 완료 이벤트를 지우지 않고 취소 이벤트 추가, 수량 원복 | 같은 모듈·`tube_plugging_event` | P·S 취소 버튼·취소 이력 | 완료 |
| G05 | Tube Map에 Plugged 표시 | 완료 직후 Map 데이터 `PLUGGED`, 취소 후 복원 | `services.tube_map_data`, `analysis-plugging.js` | P·S 실제 Map | 완료 |
| G06 | 잔여수명에 실제 완료 수량 반영 | 완료 전후 공통 분석의 실제 완료 수량 변화 확인 | `_remaining_life_projection`, `equipment_summary.py` | P·S 페이지 재조회·대표 수량 | 완료 |
| G07 | 누적 Plugging 예측에 실제 완료 반영 | 실제 완료는 미래 신규 도달과 구분하고 표본/미완료 모집단에서 제외 | `domain/plugging_summary.py`, `sample_wall_loss.py`, 분석 JS | P 수량 변화, T 예측·과거 기준일 회귀 | 완료 |
| G08 | 등록자·일자·취소 이력 보존 | 서버 로그인 사용자를 등록자로 기록, 일자·등록 일시 존재. 권한·CSRF·중복·경합·원장 불변 회귀 | `plugging_operations.py`, `web/routes/exchangers.py` | P 4개 완료/취소 이력, S 단일 이력 | 완료 |

운영 원장의 Plugging 이벤트는 점검 전후 0건이다. P·S의 완료/취소 이력은 시험 복제본에만 만들고 제거했다. 실제 완료가 전체 한도를 아직 넘지 않거나 수명 산정 자료가 부족하면 대표 수명 숫자가 반드시 변해야 하는 것은 아니다.

## 다중 사용자 대기열

| ID | 요청 항목 | 기능·실행 근거 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| M01 | 모델 요청을 순서대로 1개씩 실행 | M의 실제 SQL/의견 상태 전이, T FIFO·최대 동시 실행 1 | `application/model_queue.py`, `web/routes/text_to_sql.py` | X 대기 후 자동 완료 | 완료 |
| M02 | 앞 사용자가 끝날 때까지 대기 안내 | 실제 API position을 사용해 대기 순번·기다림 표시 | `static/text-to-sql.js`의 `modelRequest` | X ‘대기 3번’ 화면, M 두 번째 사용자 대기 1번 | 완료 |
| M03 | 첫 사용자 완료 후 다음 자동 진행 | 새 질문 제출 없이 queued→running→succeeded | 같은 모듈 | X 자동 의견 표시, M 실제 모델 | 완료 |
| M04 | 대기 3건이면 추가 요청 거절·나중 이용 안내 | 처리 중 1 + 대기 3 상태에서 추가 HTTP 429 | `ModelQueue.submit`, `QueueFull` 처리 | X 두 번째 탭 ‘나중에 다시 이용’ 및 결과 표 유지 | 완료 |
| M05 | 거절된 요청은 실행하지 않기 | T 거절 작업 미실행·소유자별 조회 제한·권한 회수, M 추가 요청 거절 | 같은 대기열·라우트 | X 가득 참 안내 후 접수 작업만 계속 | 완료 |

대기 3건을 수용하고 다음 추가 요청을 거절하는 정책이다. 현재 단일 웹 프로세스의 메모리 FIFO이며, 서버 재시작 후 대기 작업 복구나 여러 서버 전체의 전역 FIFO는 구현 범위가 아니다. 실제 다수 모델을 동시에 돌리는 부하 검사는 수행하지 않았다.

## 첨부 예시 질문 8개

| ID | 질문 | 기능 결과 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| E01 | 공정별 차기 검사 권고일이 2027년 이내 | 28대, 설비별 한 행 | `text_to_sql_equipment.py` | A 질문 1 | 완료 |
| E02 | 최근 두 검사 사이 최대 감육률 5%p 이상 증가 | 8대. 같은 설치·번들, 최근 두 유효 검사 날짜 비교. 모호한 비교는 제외 사유 표시 | `text_to_sql_equipment_history.latest_pair`, `text_to_sql_advanced.py` | A 질문 2 | 완료 |
| E03 | 감육속도 0.1mm/년 이상인 튜브 보유 | 22대, 해당 튜브 수·최대 적용 속도 | `text_to_sql_advanced.py`의 rate | A 질문 3 | 완료 |
| E04 | Plugging 20% 도달까지 10년 이내 생산팀별 집계 | 2개 팀·20대, 팀당 한 행. 이미 도달한 0년 포함·미산정은 제외 | 같은 모듈 team_limit, 공통 시뮬레이션 | A 질문 4 | 완료 |
| E05 | 검사 표본 10본 미만·검사 범위 확대 검토 | 29대, 표본 수·검토 사유. 자동 정비 결정 아님 | 같은 모듈 sample | A 질문 5 | 완료 |
| E06 | IRIS 적용 대상 중 최근 5년 무검사 | 16대. REQUIRED·OPTIONAL 대상, 날짜 미상·적용 여부 미확인 제외 | 같은 모듈 overdue_iris, `last_inspection` | A 질문 6 | 완료·자료 범위 제한 |
| E07 | Cu-Ni Tube 중 최대 감육률 상위 10대 | 현재 사양 일치 43대 중 10대 표시 | 같은 모듈 material | A 질문 7 | 완료 |
| E08 | E-106 검사 회차별 최대 감육률·Plugging 추이 | 5회. 보고서 수량과 실제 완료 누적을 구분, 미기록을 0으로 만들지 않음 | 같은 모듈 history, `cumulative_completed` | A 질문 8 | 완료 |

예시의 ‘도달’은 계산상 허용 Plugging 수량 초과 경계다. E02는 같은 튜브 집단의 동일 표본으로 보장된 속도 비교가 아니며 최대값 차이(%p)다. E06에서 대상 여부·검사일이 미확인인 설비를 임의로 ‘5년 무검사’라고 단정하지 않는다.

## 후속 결함 재검증 R1~R5

| ID | 후속 결함 | 기능·실행 근거 | 코드 근거 | 화면 근거 | 판정 |
| --- | --- | --- | --- | --- | --- |
| R01 | 상태 질문이 전체 403대로 바뀌는 문제 | IRIS 미실시 285·산정 불가 29로 실제 필터링 | `text_to_sql_equipment_intents.py`의 status | X | 해결 확인 |
| R02 | 이미 실측 한도 초과인데 양의 통계 수명 표시 | 실측 21/허용 20 경계에서 대표 0년 유지 | `equipment_summary.build_equipment_summary` | D 순수 경계 + T. 현재 운영에서 같은 결함 사례를 만들지는 않음 | 해결 확인 |
| R03 | 무검사+실제 완료 초과가 IRIS 미실시에서 이탈 | 이력 0·완료 21/20의 경계에서 uninspected 유지 | 같은 모듈·`life_band` | D 순수 경계 + T. 정비 사실은 별도 표시 | 해결 확인 |
| R04 | 생산팀 숫자를 눌러 전체 팀 목록 표시 | PE 5/191, VCM 9/212로 구간·합계와 목록 수 일치 | `group_life_rows`, `web/routes/dashboard.py`, `templates/dashboard.html` | F | 해결 확인 |
| R05 | E-111 순위 50.29%와 분석 27.44% 불일치 | D 403대 대조, 해당 부분 검사 제외 | `domain/current_measurements.py`, `wall_loss_ranking.py` | F: 27.44% | 해결 확인 |

## 이전 분석 검토 문서의 요청 8개 추가 대조

근거 문서는 `docs/REVIEW_20261117_IMPROVEMENT_PLAN.md`다. 문서에 적힌 실행 지시를 새 명령으로 수행하지 않았으며, 요청·화면 예시와 현재 구현을 대조했다.

| ID | 기존 요청 | 기능·코드 확인 | 실제 화면 | 판정 |
| --- | --- | --- | --- | --- |
| V01 | 분석 화면 30년 이상 표시 | `forecast_display`와 공통 대표값, 원시 예측일 보존 | F·L의 30년 이상 | 완료 |
| V02 | 상세 QR 숨김·CR 명칭 정리 | 상세 QR 링크 없음, 단기·장기·적용 감육속도(mm/년) 헤더 | L 상세 화면 | 완료 |
| V03 | U-tube 물리 수량 정정 | D: E-123 9·E-550 46·E-401 80본. `application/utube_correction.py` | L의 E-401 분모·분석, D 세 사양 값 | 완료 |
| V04 | 대시보드에 통계 추정 대표값 반영 | 403대 공통 Summary 대조. 유효 표본·현재 설치·이미 관측된 한도 우선 정책 | P 대시보드·L 설비 Summary | 완료 |
| V05 | E-111 부분 검사를 감육속도에서 제외 | `measurement_eligibility.exclusion_reason`와 공유 선택 함수. 원본 이력 보존 | F와 T의 제외/단기 측정 회귀 | 완료 |
| V06 | 무이력 설비가 다른 설비로 자동 전환되지 않기 | 요청 ID 106 유지·분석 detail 없음 | L E-230 화면 | 완료 |
| V07 | 표본 충분 설비 미산정 원인 해결 | E-105 승인 품질 20본은 ESTIMATED. AE-502A/B/D는 번들 모호성이 남아 차단 | L 세 대의 사유·E-105 추정 | 보완·F03 |
| V08 | 튜브 선택 전 설비 Summary·선택/복귀 | 초기 Summary 표시, 튜브 선택 후 상세, 복귀 동작 | L 실제 클릭 | 완료 |

## 명시적으로 별도 진행한 항목

| ID | 요청/제안 | 현재 상태 | 판정 |
| --- | --- | --- | --- |
| S01 | 계산 버전·원본 revision·기준일을 가진 잔여수명 DB 스냅샷 | 미구현. 현재 분석값 조회는 지원한다. 사용자가 ‘조회·화면 오류부터 해결하고 스냅샷은 별도 진행’을 선택했다. | 합의된 별도 작업 |

## 재현·운영 보존

```powershell
.\.venv\Scripts\python.exe tools/run_request_audit_tests.py
.\.venv\Scripts\python.exe tools/audit_all_requests_20261126.py
.\.venv\Scripts\python.exe tools/verify_all_requests_browser.py
.\.venv\Scripts\python.exe tools/verify_model_queue_live_20261126.py
```

각 도구는 역할이 다르다. 회귀 실행기는 지정된 자동 시험을 모아 실행하고, 데이터 점검기는 운영 데이터를 읽기 전용으로 확인한다. 브라우저 도구는 임시 복제본에서 완료·취소를 시험하고 제거한다. 실제 모델 도구는 별도 복제본에서 실제 추론·FIFO를 검증한다. 화면 대체 모델 검증과 실제 모델 검증을 혼합해 설명하지 않는다.

운영 업무 revision은 점검 전후 동일하고 실제 Plugging 원장은 0건이다. 포트 4824는 열지 않았다. 테스트 파일의 의도된 오류 분기에서 RuntimeError 경고가 출력됐으나 Python 284개는 모두 통과했다. 첫 보정 원장 시험의 ‘13건 이상’ 가정은 잘못된 것이어서 실제 변경 필드별 10+1+1건으로 수정했다. 이미 정상인 보고서 179본에 불필요한 보정 이벤트를 만들지 않았기 때문이다.

점검 결과의 ‘완료’는 확인한 기능·표시·데이터 일치 범위의 판정이다. 새 운전/검사 자료의 승인이나 임의 입력 전체에 대한 공학적 적합성 판정은 아니다. F01~F03은 이번 점검에서 제품을 임의 변경하지 않고 후속 보완 목록으로 남긴다.
