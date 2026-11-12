# 열교환기 통합 분석

고객 개선 요청 3번과 차기 검사 권고일의 실측 기준 확정을 반영했다. 범위는 VCM1·VCM2이며 DB 테이블·필드 변경은 없다.

- 설비 정보, Tube Map, 실제 두께 추이, 선택 튜브 표, 전체 측정표, 잔여수명·통계 추정, PDF 목록과 계산 설명을 같은 화면에서 펼쳐 표시한다.
- Map과 측정표 선택을 양방향으로 연결한다. 그래프는 실제 측정일·두께를 사용하며 설치 이전 이력은 회색 점으로 구분한다.
- 적용 CR을 감육속도(mm/년)로 변경했다. 단기 감육속도는 `(직전 두께 − 최근 두께) / (실제 경과일 / 365.2425)`이다. 현재 설치 이후의 대체되지 않은 유효 측정만 사용한다.
- 같은 직전 날짜의 측정이 여러 개면 최소 두께를 사용한다. 음수와 0은 그대로 표시하고 측정 편차 확인 대상으로 안내한다. 두 유효 날짜가 없거나 값이 유효하지 않으면 산정하지 않는다. 실제 0mm 두께를 누락값으로 취급하지 않는다.
- 기존 예측의 장기 평균 × 배율 선정은 유지한다. 단기 속도를 자동 적용하거나 미확정 회귀·최댓값 선정 기준을 도입하지 않는다. 배율은 적용 속도·예측만 변경하며 측정·단기·장기 원값은 유지한다.
- 차기 검사 권고일은 실측 튜브의 최초 도달일만 사용한다. 통계 추정일로 대체하지 않으며 이전 기준으로 제출된 등록 요청은 새로고침을 요구한다.

## 검증

Python 78건 및 단기 추이·연도별 예상·선택 연동 JavaScript 시험을 통과했다. 개발 MariaDB의 인증된 E-111 분석 GET을 확인하고 저장된 실제 HTML을 1440/768/390px 브라우저에서 검증했다. Map과 표 양쪽에서 그래프·선택 표·선택 표시가 일치했으며 문서 가로 넘침과 분석 본문 탭·접힘·팝업은 없었다. 그래프와 넓은 측정표는 내부 가로 스크롤을 제공한다.

실측 기준의 권고 목록은 개발 데이터 기준 17대이다. 인증·조회 권한과 별도 `iris2_test_transition` DB에서 등록·대상·이벤트 저장, 중복·다른 설비 대상 차단 후 롤백을 확인했다. 업무 DB 쓰기는 수행하지 않았다. 화면 증거는 Git 제외 경로 `reports/exchanger-analysis-20261112/`에 보관한다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_short_term_corrosion tests.test_inspection_workspace tests.test_sample_wall_loss tests.test_life_dashboard tests.test_inspection_lifecycle test_latest_installation_prediction test_calculation_boundaries -q
node tests/test_tube_thickness_trend.cjs
node tests/test_precision_selection.cjs
node tests/test_annual_plugging.cjs
.\.venv\Scripts\python.exe tools/verify_exchanger_analysis.py
node tools/verify_exchanger_analysis_browser.mjs
.\.venv\Scripts\python.exe tools/verify_inspection_workspace.py --integration
```

운영 서버 적용에는 GitHub 코드 동기화와 기존 앱 재시작 절차가 필요하다. 운영 배포·서버 재시작은 수행하지 않았다.
