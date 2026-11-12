# 대시보드 고객 개선 요청 2번 반영

VCM1·VCM2를 VCM 생산팀으로 합산한다. 조직 코드나 설비 소속을 변경하지 않으며 DB 테이블·필드 추가는 없다.

- 잔여수명 구간은 생산팀 한 행으로 합산한다. 구간 링크는 두 공정을 함께 조회하며 설비 목록에 생산팀과 공정을 각각 표시한다. 기존 공정 필터 URL은 호환한다.
- 연도별 검사 현황은 생산팀 합계와 공정별 내역을 같은 표에서 표시한다. 생산팀의 검사 설비 수는 같은 연도에 중복된 설비를 한 번만 집계한다. 원본 PDF는 공정별 기존 경로로 연결한다.
- 설비 수·검사 이력·사양 Tube 합계·등록 Tube·결과·계획 지표, 최근 검사와 예정 검사도 VCM1·VCM2 대상에 한정한다. 관리자 데이터 입력 현황 화면의 집계는 변경하지 않는다.
- 대시보드 QR 항목·스캐너·스크립트를 제거하여 QR 설정이 켜져 있어도 표시하지 않는다. 별도 설비 상세 QR 기능은 유지한다.
- 최초 튜브 예상일이 조회 기준일의 30년 후 같은 날짜보다 늦으면 ‘30년 이상’으로 표시한다. 정확히 30년이면 날짜를 유지하며 윤일은 30년 후 2월 28일을 경계로 한다. 예상 잔여수명도 값이 30보다 클 때 같은 문구로 표시한다. 원래 날짜·계산값·잔여수명 구간은 보존한다.
- 검사 시 이미 기준 도달·산정 불가·한도 미도달 상태를 장기 예상 표시로 바꾸지 않는다.

## 검증

Python 94건 통과. 개발 MariaDB에서 VCM1·VCM2 설비 212대, 검사 이력 425건, 연도별 5개 집계를 독립 SQL과 비교했다. QR 설정이 켜진 관리자 인증 GET과 미인증 차단을 확인했다. 실제 응답 HTML을 브라우저 1440/768/390px에서 확인하고 생산팀 합계·공정 열·목록 링크·장기 예상 표시와 문서 가로 넘침 없음을 검증했다. 넓은 표는 내부에서 스크롤한다. 30년 경계 전날·당일·다음날과 윤일을 시험했다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_life_dashboard tests.test_ui_usability tests.test_inspection_workspace tests.test_sample_wall_loss tests.test_short_term_corrosion test_latest_installation_prediction test_calculation_boundaries -q
.\.venv\Scripts\python.exe tools/verify_dashboard_team.py
node tools/verify_dashboard_team_browser.mjs
```

검증은 업무 DB 쓰기 없이 수행했다. 증거는 Git 제외 경로 `reports/dashboard-team-20261112/`에 보관한다. 운영 서버는 GitHub 코드 동기화와 기존 앱 재시작이 필요하며 이번 작업에서 운영 배포·재시작은 수행하지 않았다.
