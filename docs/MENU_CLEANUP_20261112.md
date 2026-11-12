# 메뉴 정리 — 고객 요청 1번

일반 메뉴는 고객 요청서 그림 1의 대시보드, 열교환기 목록, 열교환기 분석, 검사 이력, 검사계획 다섯 항목이다. 검사 이력의 하위 화면은 연도별·공정별이다. 권한이 없는 항목은 기존 규칙에 따라 숨긴다.

관리 기능은 모든 업무 화면의 상단 **⚙ 관리자 설정**에서 열도록 이동했다. 관리자에게만 표시하며 데이터 적재(JSON/PDF), 품질·입력 현황, 사용자·권한, 조직 코드·기준값, DB 점검·백업으로 묶었다. 메뉴 이동은 서버의 기존 인증·권한·CSRF 규칙을 변경하지 않는다. 내 기본 설정은 사용자명 링크로 접근한다.

열교환기 목록의 코드와 설비명은 해당 설비 ID·공정을 지정한 분석 화면으로 연결한다. 적용 범위는 VCM1·VCM2이며 분석 조회 권한이 없거나 범위 밖인 설비는 기존 상세 화면으로 연결한다. 등록·Excel은 목록 화면 버튼에 두며 편집·내보내기 권한을 각각 확인한다. Text-to-SQL·정비 관리는 분석 화면의 보조 버튼으로 유지한다. 기존 상세·정비·관리 URL과 기능은 보존한다. DB 스키마 변경이나 업무 DB 쓰기는 없다.

## 검증

- 관련 Python 97건 통과: 템플릿 파싱, 일반 메뉴 5개, 관리자 상단 배치, 일반 사용자에게 숨김, 일부 권한에 따른 메뉴 축소 및 기존 화면 회귀.
- 개발 MariaDB의 인증된 대시보드·목록·분석 GET과 목록 링크의 실제 대상 GET을 확인했다. 읽기 권한 사용자에게 등록·Excel 버튼이 없고 관리자 설정이 숨겨지며 적재·사용자·백업·DB 점검 직접 GET은 403인 것을 검증했다.
- 실제 HTML의 관리자 3화면과 일반 사용자 목록을 1440/768/390px, 총 12조합에서 확인했다. 메뉴 5개, 분석 링크, 가로 넘침 없음, 설정 목록의 화면 안 배치, Escape·바깥 클릭 닫힘을 검증했다. 증거는 Git 제외 경로 `reports/menu-cleanup-20261112/`에 보관한다.
- 추가 실행한 기존 `test_pdf_ocr_permissions` 2건은 실패한다. 이 테스트는 특정 이메일의 일반 사용자 허용·다른 관리자 차단을 기대하지만 현재 `application/auth_service.py`와 `web/security.py`는 활성 관리자만 허용한다. 이번 작업에서 두 권한 구현 파일은 변경하지 않았으며 기존 정책과 테스트 기대값의 불일치로 기록한다.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_menu_cleanup tests.test_ui_usability tests.test_life_dashboard tests.test_inspection_workspace tests.test_sample_wall_loss tests.test_short_term_corrosion test_latest_installation_prediction test_calculation_boundaries -q
.\.venv\Scripts\python.exe tools/verify_menu_cleanup.py
node tools/verify_menu_cleanup_browser.mjs
```

운영 서버에는 GitHub 코드 동기화와 앱 재시작이 필요하다. 운영 배포·재시작은 수행하지 않았다.
