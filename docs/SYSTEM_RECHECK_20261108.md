# IRIS2 재점검 — 2026-11-08

기존 SYSTEM_RECHECK_20261028.md와 이후 회귀시험을 기준으로 VCM1·VCM2를 재검증했다.

## 결과

- MariaDB 통합·계산·권한 등 공식 시험: 141건 통과, 실패·오류·건너뜀 0.
- Text-to-SQL 추가 단위시험: 14건 통과.
- 화면·API·정적자원 HTTP 검사: 156건 통과.
- 비로그인 접근 차단: 50건 통과.
- 설비 212대, 부식속도 배율 5개, 계산 시나리오 1,060개: 일관성 문제 0.
- 서버와 JavaScript 예측일 7,340개 일치.
- JavaScript 회귀시험 파일 9개 통과. 자체 static JavaScript 20개 구문 검사 통과.

## 확인 및 수정

최초 화면 검사에서 `/inspections/text-to-sql/inspections`가 400을 반환했다. 이 API는 `exchanger_id`가 필수이므로 정상적인 입력 검증 응답이었다. 점검 도구가 모든 GET 요청을 200으로 기대한 것이 원인이었다.

`tools/screen_recheck.py`에 필수값 누락 시 400 검사를 명시하고, VCM1·VCM2 각각의 실제 설비 ID를 전달하는 정상 조회 검사를 추가했다. 수정 후 전체 화면 검사를 재실행하여 모두 통과했다. 업무 애플리케이션 소스는 변경하지 않았다.

## 범위와 한계

iris2 전용 가상환경을 사용했다. 기본 권한에서 MariaDB 사전 확인이 실패했으며, 승인된 권한으로 비공개 설정을 읽어 검증을 완료했다. 자격 증명은 출력하지 않았다. 운영 검사값이나 중요도를 수정하지 않았으며, 업무 쓰기 시험은 기존 격리 시험 스키마를 사용했다. 운영 웹 서버는 재시작하지 않았다.

화면 검증은 Flask 시험 클라이언트의 HTTP·템플릿 응답 검증이다. 이번에는 실제 브라우저 반응형 배치, GPU 렌더링, 카메라, 외부 LLM 추론을 재검증하지 않았다. 운영 데이터에 작업지시 상세 표본이 없어 해당 HTTP 검사는 건너뛰었으며, 격리 통합시험의 작업지시 워크플로는 통과했다. 현장 UAT와 공학적 수명 승인도 별도다.

증거: `reports/system_recheck/20261108/`의 `validation.json`, `validation.log`, `screens.json`, `life_consistency.json`, `life_browser_parity.json`, `javascript-tests.json`, `text-to-sql-tests.log`.

과거 날짜가 고정된 계산 검증 도구는 `tmp/recheck_life_20261108.py`, `tmp/recheck_parity_20261108.cjs` 사본에서 보고서 경로만 바꾸어 실행해 과거 증거를 보존했다.
