# 로컬 Text-to-SQL 구현

작성일: 2026-11-07

## 구현 범위

`llm_integration/text_to_sql.py`는 로컬 모델이 실제 SQL JSON을 작성하고, 검증된 SQL을 MariaDB에서 실행하는 서비스다. 고정 SQL 템플릿을 선택하는 방식이 아니다. 서버가 확정한 설비·검사 회차의 `analysis_tubes` 관계에 대해 집계·조건·정렬 SQL을 생성한다.

현재 지원은 **단일 설비의 최신 유효 검사 또는 명시적으로 지정한 검사 회차**에 대한 요약·감육 상위 Tube·조건 검색이다. 검사 수량은 해당 회차의 Tube 상세 결과 수이며 보고서 기재 검사수량·설계 전체 수량과 구분한다. 평균은 유효 감육률의 산술평균이다. 이상 판정·Plugging 기술 판단·이력 비교·공정별 순위·수명·차기검사·종합의견 생성은 후속 구현이다. 현재 결과는 근거 메타데이터가 포함된 JSON 조회 초안이다.

최소두께·최대 감육률을 독립 집계하며 NULL은 0으로 바꾸지 않는다. 최신 검사일이 같은 복수 회차는 자동 선택하지 않고 검사 ID를 요구한다. 검사일이 없으면 보고일을 사용하며 응답에 원래 두 날짜를 포함한다. Tube 결과는 기존 UNIQUE(iris_inspection_id, tube_id)를 전제로 한다.

## 실행 경계

- 모델은 원본 테이블·자격증명·전체 데이터를 받지 않는다. 컬럼 설명과 질문을 받아 `sql`, `parameters` 두 필드의 JSON을 반환한다. llama.cpp의 JSON Schema 제약을 사용하며, 구문·질문 계약 불일치 시 오류 설명을 제공해 한 번만 재생성한다. 재생성도 실패하면 실행하지 않는다.
- sqlglot의 MySQL 구문 트리를 엄격한 노드 허용 목록으로 검사하고 다시 직렬화한다. MariaDB 전용 확장 SQL은 현 단계에서 허용하지 않는다.
- 단일 SELECT만 허용한다. 임의 함수·JOIN·하위쿼리·CTE·UNION·주석·파일 출력·잠금·변수·산술은 차단한다. 값은 WHERE의 물음표 바인딩만 허용한다. LIMIT은 최대 100행, 서버 측 실행시간은 5초다.
- 검증 후 유일한 가상 테이블 노드를 서버 소유 파생 테이블로 교체한다. 실제 조회는 지정 설비·검사 ID와 VCM1·VCM2로 제한된다. 단순 SQL 문자열 치환을 사용하지 않는다.
- 읽기 전용 접속, 일관된 스냅샷, 종료 시 rollback/close를 사용한다. SHOW GRANTS가 USAGE 또는 SELECT 이외 권한·역할·재부여 권한을 보이면 조회를 중단한다. 계정 권한 구성은 별도 운영 설정으로 관리한다.
- 서비스의 `authorized_exchanger_ids`는 호출자가 서버 권한 정책에서 산출해야 한다. 브라우저 입력이나 모델이 지정한 ID 목록을 그대로 넘기면 안 된다. CLI는 DB 설정에 접근할 수 있는 로컬 운영자용이며 웹 인증을 대신하지 않는다.
- 모델 제안 거절·모델 미설정·DB 실패 시 다른 설비 검색이나 규칙 기반 답변으로 조용히 대체하지 않는다.

## 로컬 실행

모든 명령은 iris2 디렉터리에서 실행한다.

```powershell
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

로컬 모델 환경에는 별도 `llm_integration/requirements.txt`의 llama-cpp-python이 필요하다. 승인된 GGUF 파일은 iris2 내부에 배치하고 `models.local.example.json`을 참고해 `llm_integration/models.local.json`을 만든다. CLI는 iris2 밖의 모델 설정·모델 경로를 거부한다. 외부 API 키는 사용하지 않는다.

Text-to-SQL은 전용 private `config/database-text-to-sql.conf`를 사용한다. 기존 `database-readonly.conf`와 다른 프로필이며 자동 대체하지 않는다. 자격증명을 저장소나 질문에 넣지 않는다. `tools/provision_text_to_sql_account.py --apply`는 새 계정에 필요한 5개 테이블의 SELECT만 부여한다. 기존 계정·기존 설정은 덮어쓰지 않는다. 조회 서비스 자체는 계정·권한·운영 데이터를 변경하지 않는다.

```powershell
.venv/Scripts/python.exe tools/run_text_to_sql.py --exchanger-id 123 --question "선택한 설비의 최근 검사 결과를 요약해 줘"
.venv/Scripts/python.exe tools/run_text_to_sql.py --exchanger-id 123 --question "감육이 가장 심한 Tube 5개를 알려줘"
```

123은 실제 확인한 설비 ID로 바꾼다. 질문에 쓴 설비 태그로 설비를 자동 선택하는 기능은 아직 없으며, `--exchanger-id`가 조회 대상을 결정한다. 응답의 equipment와 inspection을 반드시 확인한다. `--inspection-id`로 회차를 지정할 수 있다.

모델 없이도 검토된 SQL JSON의 검증·DB 실행을 확인할 수 있다.

```json
{"sql":"SELECT COUNT(*) AS inspected_tubes, MIN(minimum_wall_thickness_mm) AS minimum_mm, MAX(wall_loss_percent) AS maximum_loss, AVG(wall_loss_percent) AS average_loss FROM analysis_tubes", "parameters":[]}
```

위 내용을 iris2 내부 JSON 파일에 저장한 뒤 실행한다.

```powershell
.venv/Scripts/python.exe tools/run_text_to_sql.py --exchanger-id 123 --proposal-json data/text_to_sql_proposal.json
.venv/Scripts/python.exe -m unittest llm_integration.tests.test_text_to_sql -v
```

## 검증 상태와 후속 작업

구문 검증, 금지 SQL, 바인딩, 설비 권한, 서버 범위 주입, 동일 날짜 회차 중복, 과권한 DB 계정 거절, 오류 시 연결 정리를 단위 테스트로 검증한다. 모델·DB 테스트 대역을 사용하는 단위 테스트와 실제 연결 검증을 구분한다. 요약·상위 Tube·명시적 감육률 조건은 질문 계약도 검증하며, 문법이 맞더라도 집계·조건·정렬이 질문과 다르면 거절한다.

초기 환경 점검의 미설치·연결 실패 상태는 아래 독립 환경 구성으로 해소했다. 실제 모델 검증은 다음 명령으로 재현한다. 검사 수량이 있는 VCM1·VCM2 표본 회차를 선택하고, 생성 SQL 결과를 모델과 독립된 기준 SQL과 비교한다. 결과는 `reports/text_to_sql/live_validation.json`에 기록한다.

```powershell
.venv/Scripts/python.exe tools/verify_text_to_sql_live.py
```

이는 한 표본 회차의 기술 검증이다. 전체 설비·다양한 표현에 대한 정답률, 원본 보고서 대조, 현장 사용자 검수·모델 승인까지 완료했다는 뜻은 아니다.

2026-11-07 검증 결과: 단위 테스트 17개 통과. Gemma E4B 실제 모델과 MariaDB의 명시적 표본 회차(설비 ID 151, 검사 ID 389, Tube 결과 82개)에서 요약·감육 상위 5개·감육률 30% 이상 조회가 독립 기준 SQL과 일치했다. 세 질문의 실행시간은 각각 약 34초·16초·13초이며 첫 질문은 모델 로딩을 포함한다. 잔여수명 질문은 미지원 범위로 모델 호출·DB 실행 전에 차단했다. 최초 Qwen 파일럿은 질문 의미 불일치가 있어 기본 모델로 채택하지 않았다. 최근 날짜에 복수 검사 회차가 있는 실제 표본에서도 명시적 검사 ID 요청을 확인했다.

검증된 표본을 CLI에서 조회하려면 다음처럼 검사 회차를 명시한다.

```powershell
.venv/Scripts/python.exe tools/run_text_to_sql.py --exchanger-id 151 --inspection-id 389 --question "검사 결과를 요약해 줘"
```

기존 `/inspections/ai-search`는 변경하지 않았다. 별도 시스템 메뉴와 `/inspections/text-to-sql` 화면을 추가했다. 실제 MariaDB와 웹 사용자 권한 검증을 통과한 경로로 연결한다. 모델 동시 생성은 앱 프로세스당 1개이며 별도 추론 프로세스에 120초 제한을 적용한다. SQL·범위 검증만으로 모든 질문의 업무적 정답이 보장되지는 않는다.

다음 단계는 Tube 이력 비교용 승인 관계, 기존 수명·검사계획 계산 결과 연결, 공정별 우선순위 기준, 결과 기반 보고서 및 수치 일치 검증 순서다.

## 시스템 메뉴에서 사용하기

1. 로그인 후 왼쪽 **Text-to-SQL 분석** 메뉴를 연다. 주소는 `http://127.0.0.1:4824/inspections/text-to-sql`이다.
2. VCM1·VCM2 설비와 검사 회차를 선택한다. 최근 날짜에 여러 보고서가 있으면 회차를 명시해야 한다. 질문에 쓴 설비 태그로 대상을 자동 변경하지 않는다.
3. 질문을 입력하거나 검사 요약·감육 상위 5개·감육률 30% 이상 예시를 선택하고 **SQL 생성**을 누른다.
4. 생성 SQL과 바인딩 값을 확인하고 **SQL 실행 · 결과 보기**를 누른다. 결과 표에 단위·조회 회차·조회 시각을 표시하며 결측은 `—`, 실제 0은 `0`으로 표시한다. 빈 결과도 컬럼과 빈 결과 안내를 유지한다.

관리자는 바로 사용할 수 있다. 일반 사용자에게는 사용자·권한 관리에서 **Text-to-SQL 조회**와 **검사 관리 조회** 권한이 모두 필요하다. 생성·실행은 데이터 변경이 없는 POST 요청이므로 편집 권한을 요구하지 않지만 CSRF 검증은 적용한다. 인증 비활성 모드에서도 인증 프로필이 없으면 새 경로는 거절한다. DB 스키마 변경은 없다.

웹에서는 생성한 SQL을 읽고 복사할 수 있으며 임의 SQL 편집·직접 실행은 제공하지 않는다. 실행 요청은 서버가 서명한 사용자·질문·설비·회차·SQL·바인딩 값을 사용한다. 15분 만료, 다른 사용자, 토큰 변조, 회차 무효화는 실행을 차단한다. 실행 시 현재 권한과 설비·검사 소속도 다시 확인한다. 모델·DB 오류 응답에는 내부 경로나 자격증명을 포함하지 않는다.

관련 코드: `web/routes/text_to_sql.py`, `application/text_to_sql_service.py`, `templates/text_to_sql.html`, `static/text-to-sql.js`, `static/text-to-sql.css`. 추론 자식 프로세스는 `tools/generate_text_to_sql.py`이며 iris2의 Python·모델만 사용한다.

웹 검증 기록: `reports/text_to_sql/web_validation.json`, `reports/text_to_sql/browser/validation.json`. 실제 인증·MariaDB·모델의 생성→실행과 결과 표를 확인했다. 단위 테스트 28개와 실제 MariaDB 권한·조회·기존 DB 회귀 테스트 6개가 통과했다. 브라우저에서 1440/768/390px 가로 넘침 없음, 모바일 메뉴 접힘, 질문 변경 시 이전 SQL 무효화, JavaScript 오류 없음, 별도 UI 테스트 값의 0·NULL·빈 결과·HTML 문자열 표시를 확인했다. 테스트용 표시 값은 운영 데이터에 저장하지 않았다.

레이아웃은 기존 IRIS2 프레임·색상·서체를 유지했다. 디자인 스킬의 Framed sheet 방향(seed 348944553)을 적용했고, 선택 설비·회차 → 질문과 SQL → 결과 표가 화면의 핵심 흐름이다. 가짜 업무 데이터나 새 외부 이미지는 사용하지 않았다.

화면 검사기 최종 결과는 1440/768/390px에서 FAIL 0, WARN 0이다. 실제 결과 화면과 세 크기의 스크린샷도 확인했다. 모바일 메뉴·여백과 수량 컬럼의 정수 표시를 보정했으며 임시 브라우저 인증 파일은 검증 후 삭제했다.

## 독립 환경 구성 기록

- 기존 `C:/access/llm` 파일은 읽기만 했다. 해당 Python 환경을 실행하거나 import 경로에 추가하지 않았다.
- 설치된 패키지 파일을 독립 wheel로 재구성해 `data/llm/wheelhouse`에 저장한 후 iris2 `.venv`에 오프라인 설치했다. llama-cpp-python 0.3.33, diskcache 5.6.3이며 `pip check`로 의존성을 확인했다. 원본 환경과 DLL을 공유하지 않는다.
- Qwen3-1.7B-Q6_K와 Gemma E4B Q4_K_M을 `data/llm/models`로 실제 복사했다. 복사 전후 SHA-256을 대조했으며 원본 파일을 직접 로드하지 않는다. 기본 검증 모델은 Gemma E4B이고, 모델 설정은 비공개 `llm_integration/models.local.json`이다. 모델 사용은 파일럿이며 기술·라이선스 승인 완료를 의미하지 않는다.
- 패키지·모델 해시는 `data/llm/provenance.json`에 보관한다. Qwen3 SHA-256: `5542e724ad09a27d7be53446cb62dadc870df6a68da90b162dcc0d787b60ff25`. Gemma E4B SHA-256: `3f72a20a06f626c78e6c475ae07a64c88b2663149c0f6197b56bf7cf1f37585c`.
- 기존 시작 스크립트로 iris2 내부 datadir의 MariaDB만 3307에서 시작했다. 새 `iris2_textsql` 계정은 필요한 5개 테이블의 SELECT만 부여했다.
- 초기 MariaDB의 PUBLIC 역할에는 `test`와 `test\_%`의 쓰기 권한이 있어 새 계정에도 상속되었다. 실제 datadir·포트가 iris2 전용인지, 대상 test 영역에 테이블이 없는지 확인한 뒤 그 두 기본 권한만 제거했다. 복원 SQL은 `data/llm/public_test_grants_before.sql`에 기록했다. 업무 스키마의 기존 사용자 권한과 데이터는 변경하지 않았다. PUBLIC 권한 상속은 [MariaDB 공식 문서](https://mariadb.com/docs/server/security/user-account-management/roles/system-users-roles-and-privileges)를 참고한다.
# 복수 교환기·공정 조회 (2026-11-09)

화면의 조회 범위에서 **교환기 선택** 또는 **공정 전체**를 선택한다. 교환기는 검색 후 체크박스로 여러 대를 고를 수 있고, 공정은 VCM1·VCM2를 개별 또는 함께 선택할 수 있다.

단일 교환기는 기존 검사 회차 선택을 유지한다. 복수 교환기와 공정은 설비별 최근 유효 검사를 선택해 Tube 데이터를 합쳐 조회한다. 요약의 평균은 설비별 평균의 평균이 아니라 전체 유효 Tube의 산술평균이다. 공정 조회에서 검사 없음·날짜 없음·최신 날짜 회차 중복 설비는 제외하고, 생성 SQL 아래 실행 결과의 대상 상세 목록에 사유를 표시한다. 명시적으로 선택한 교환기에 문제가 있으면 회차 지정 또는 설비 선택 변경을 요청한다.

생성 API는 `exchanger_ids: [151, 152]` 또는 `unit_codes: ["VCM1", "VCM2"]`를 받는다. 단일 선택에만 `inspection_id`를 지정할 수 있다. 기존 `exchanger_id` 요청도 유지한다. 서버가 대상 설비·검사 ID를 확정하여 서명 토큰에 저장하고, 실행 시 현재 허용 설비·검사 유효성을 읽기 전용 트랜잭션 안에서 재확인한다. 실행 요청으로 범위를 바꿀 수 없다. 생성 이후 추가된 검사·설비는 자동으로 조회 범위에 편입되지 않는다.

복수 조회 결과는 `scopes`에 대상 목록을 담고 단일 대상 전용 `equipment`, `heat_exchanger_id`, `inspection`은 null이다. SELECT 전용 DB 계정, SQL 검증, 100행·5초 제한은 그대로 적용한다.

# 설비별 IRIS 검사 횟수 순위 (2026-11-09)

`최근 iris 검사를 제일 많이 수행한 열교환기를 리스트해줘`를 검사 회차 횟수 순위로 인식한다. 기본은 한국 날짜 기준 최근 5년·상위 20대이며 `최근 3년 ... 상위 5대`, `올해`, `작년`도 지원한다. 기간 시작일과 종료일을 포함한다. 기간·대상 범위를 생성 SQL 미리보기와 결과에 표시한다.

화면에서 선택한 교환기 또는 VCM1·VCM2 공정 범위 안에서 조회하고, 범위 미선택 시 VCM1·VCM2 전체를 사용한다. 최신 단일 회차 선택과 달리 기간 내 전체 IRIS 검사 ID를 세며, 대체된 검사는 제외한다. 검사일이 없으면 보고일을 사용하고 둘 다 없으면 집계하지 않는다. 같은 날짜의 서로 다른 유효 검사 ID는 각각 1회다. 결과는 검사 횟수 내림차순, 동률이면 최근 검사일 내림차순·설비 ID 오름차순이다. 조회 기간에 검사 이력이 없는 설비는 순위에 포함하지 않는다.

이 명확한 질문 유형은 서버의 검증된 SQL 템플릿을 사용하므로 GGUF 추론 결과에 의존하지 않는다. 기존 Tube 질문의 모델·SQL 허용 문법은 유지한다. 생성 시 설비 ID·기간·SQL을 서명하고 실행 시 권한·서명·유효시간·SQL 일치를 재확인한다. SELECT 전용 MariaDB 계정·읽기 전용 트랜잭션·5초·최대 100행 제한을 유지한다.
