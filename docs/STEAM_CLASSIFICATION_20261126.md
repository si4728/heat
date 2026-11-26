# S:STEAM의 STEAM 분류 적용

2026-11-26 · PE·VCM1·VCM2 · 사용자 요청: `S:STEAM`도 `STEAM`으로 분류

Text-to-SQL의 현재 유체 조회·집계에서 `S:STEAM`을 `STEAM`으로 분류한다. 질문의 유체 조건에도 같은 별칭을 적용하므로 `유체명이 STEAM인 열교환기 목록`과 `유체명이 S:STEAM인 열교환기 목록`은 동일한 결과다. 공정별 grouping에서도 별도 `S:STEAM` 행을 만들지 않는다. 결과 아래에 분류 기준을 표시했다.

원본 사양의 유체 문자열은 보존한다. 사양 상세 화면의 원본 표기나 PDF를 변경하는 데이터 보정이 아니다. `HP STEAM`, `H.P. STEAM`, `MEDIUM STEAM`, `LOW STEAM`, `STEAM CONDENSATE`는 각각 유지한다. 이번 별칭은 명시 요청한 `S:STEAM`이며, 다른 접두어나 유체를 일괄 제거하지 않는다.

## 검증 결과

| 항목 | 결과 |
| --- | --- |
| 전체 대상 | PE 191·VCM1 81·VCM2 131 = 403대, 미검사 포함 |
| STEAM Shell | 기존 15대 + S:STEAM 22대 = 37대 |
| STEAM Tube | 2대 |
| VCM1 공정별 집계 | Shell STEAM 22대, S:STEAM 별도 행 없음 |
| 두 질문의 결과 | 행·설비 목록·수량 일치 |
| 공정·측별 전체 집계 | 원래 403대 모집단과 일치, 별칭으로 중복 증가 없음 |
| 다른 증기 이름 | HP 10·H.P. 1·MEDIUM 3·LOW 1·CONDENSATE 1건의 기존 그룹 유지 |
| 원본 보존 | 전체 사양 revision의 shell_fluid·tube_fluid 조회 전후 동일 |
| 자동 시험 | Python 286개 통과. 필터 별칭·기존 권한/서명·MariaDB 실제 집계와 원본 보존 포함 |
| 실제 화면 | 인증된 복제 DB·임시 서버에서 세 질문, 1440/768/390px 모두 확인 |

Shell과 Tube는 별도의 측별 집계이므로 일반적으로 두 수량을 더해 고유 설비 총수로 해석하지 않는다. 실제 운영 DB 검증도 기존 Text-to-SQL SELECT 전용 계정으로 실행했다. DB migration·추가 권한·서비스 재시작은 필요하지 않다. 운영 웹 서비스의 중지 요청을 유지했다.

## 코드와 재현

- `application/text_to_sql_fluids.py`: 질문 별칭 정규화와 현재 유체 SQL의 분류 CASE. 사용자 입력은 계속 바인딩 파라미터로 전달한다.
- `static/text-to-sql.js`, `templates/text_to_sql.html`: 결과 분류 안내와 정적 파일 버전 갱신.
- `tests/test_text_to_sql_fluids.py`, `tests/test_text_to_sql_steam_mariadb.py`: 별칭·다른 유체 분리·공정 합계·원본 보존.

```powershell
.\.venv\Scripts\python.exe tools/run_request_audit_tests.py
.\.venv\Scripts\python.exe tools/verify_steam_classification.py
.\.venv\Scripts\python.exe tools/verify_all_requests_browser.py --stages steam
```

로컬 근거는 `reports/steam-classification-20261126/operational-check.json` 및 `reports/all-requests-audit-20261126/browser/steam/`에 보관하며 Git에는 포함하지 않는다.

[전체 요청 점검](ALL_REQUESTS_1_TO_1_AUDIT_20261126.md)의 F01은 이번에 해결했다. F02의 유체 목록 설비별 행·분석 링크와 F03의 AE-502A/B/D 원본 식별은 별도 보완 사항이다.
