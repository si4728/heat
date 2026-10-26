# 열교환기 튜브 건전성 관리시스템 개발 현황 정밀 검토

- 문서명: `system_review_260824.md`
- 검토 기준일: 2026-08-24 (Asia/Seoul)
- 대상 프로젝트: 열교환기 튜브 건전성 관리시스템
- 대상 애플리케이션: `C:\access\heat\iris2`
- 대상 운영 DB: `C:\access\heat\iris2\data\heat_exchanger_v3.db`
- DB 스키마: 3.8.0
- 검토 성격: 소스코드·설정·DB·시험자료 기반 정적/동적 점검

## 0. 확정 의사결정

### 2026-08-24 JSON 업로드 기능 동결

프로젝트 의사결정에 따라 JSON 업로드 기능은 시스템 전체 완료 시점까지 현재 기능으로
보류한다. 본 단계에서는 다음 현행 범위를 기준선으로 유지한다.

- 지정 JSON 단일 파일 업로드
- 공장·생산라인 명시적 선택
- 구조 및 데이터 검증
- Dry-run
- SHA-256 중복 방지
- 트랜잭션 적재
- 품질 경고 및 적재 결과 표시
- 적재 후 감육 평가 갱신

시스템 완료 전 JSON 업로드 모듈에는 운영 장애, 보안 취약점 또는 데이터 무결성 결함을
해결하기 위한 수정만 적용한다. 다중 파일·폴더·ZIP 업로드, 작업 Queue, 진행률,
재처리 UI, 범용 IRIS Raw 어댑터 및 관리자 Upsert UI는 시스템 완료 이후 Backlog로
이관한다. 이 동결 결정은 PDF 보고서 일괄 등록, Dashboard, Tube Map, API 510 운영
적용 및 로컬 LLM 개발 범위를 변경하지 않는다.

다만 다음 데이터 추출·검증·반영 품질 개선은 JSON 업로드 동결 대상에 포함하지 않으며,
시스템 개발 기간에도 계속 검토하고 개선한다.

- 표 구조와 Tube Map 추출
- 설비번호·검사일·튜브번호·두께·감육률 자동 매핑
- 추출 신뢰도와 원문 페이지 근거 표시
- 원문/추출값 나란히 검토·수정하는 화면
- 검토·승인 후 DB 반영
- 다양한 보고서 Layout용 파서 회귀시험
- 실패 파일 재처리 및 작업 통계

여기서 동결되는 대상은 JSON 파일의 업로드 방식과 사용자 기능 확장이다. 위 항목은
원천 보고서에서 구조화 데이터를 생성하고 검증해 DB에 안전하게 반영하는 핵심 품질
기능이므로 별도 개선 Track으로 유지한다.

### 2026-08-24 Dashboard 추가 개발 범위 확정

다음 항목은 운영 Dashboard의 확정 추가 개발 범위로 반영한다.

- 공장·공정·기간 복합 필터
- 검사율, 평균/최대 감육률, 위험도 추세 그래프
- 잔여수명 임박 설비 목록
- KPI 클릭 Drill-down
- 품질 이슈와 지연 검사 알림
- 최근 갱신 시각과 자동 갱신
- 사용자별 Dashboard
- Dashboard PDF/Excel 출력
- 고객 KPI 정의 및 승인

각 기능은 단순 화면 표시가 아니라 조회조건, 집계 기준, 권한, 상세 이동 경로,
출력 결과 및 갱신주기를 포함해 시험한다. 고객 KPI 정의·승인을 선행하여 화면과
출력물에서 동일한 산식과 기준일을 사용한다.

### 2026-08-24 로컬 LLM 참조 구현 지정

LLM 연동 설계와 구현 시 `C:\access\llm`을 우선 참조한다. 해당 프로젝트에서 확인된
다음 요소를 IRIS 보고서 생성 기능의 재사용 후보로 검토한다.

- `llama-cpp-python`을 이용한 로컬 GGUF 모델 직접 로딩
- 모델 경로, Context 크기 및 기본 모델의 JSON 설정
- `LLAMA_N_THREADS`, `LLAMA_N_BATCH`, `LLAMA_N_GPU_LAYERS` 실행환경 설정
- 로컬 모델 Keep-loaded Cache와 최대 적재 모델 수 제한
- 동시 추론 요청 직렬화
- Chat Completion 형식의 System/User Prompt 호출
- 모델 선택, 사용자별 기본 모델 및 생성 이력 저장 구조
- 사용자 인증, CSRF, 로그인 잠금 및 감사로그 구현 사례
- Prompt/응답/오류/소요시간 저장 구조
- 테스트와 운영 Hardening 자료

단, `C:\access\llm`에는 로컬 `llama_cpp` 모델뿐 아니라 Gemini API 및 기타 외부 모델
연동 코드도 함께 존재한다. 고객 요구사항은 외부 통신이 없는 사내 PC 처리를 요구하므로
IRIS 통합 시 다음 원칙을 적용한다.

1. 운영 설정에서 허용 Provider를 `llama_cpp`로 제한한다.
2. Gemini/OpenAI/Mistral 등 외부 Provider 코드와 API Key 의존성을 배포본에서 제외한다.
3. 사용자 홈의 LM Studio 절대경로를 사용하지 않고 현장 설치용 모델 디렉터리를 사용한다.
4. 모델 파일명, SHA-256, 라이선스, 양자화 형식 및 Context 크기를 Release Manifest로 관리한다.
5. 모델 자동 다운로드, Telemetry 및 자동 업데이트를 차단한다.
6. 방화벽 차단과 패킷 캡처를 통해 외부 통신 0건을 검증한다.
7. `C:\access\llm` 전체 애플리케이션을 결합하지 않고 로컬 추론 Client와 필요한
   보안·감사 패턴만 IRIS 경계 안으로 분리 이식한다.
8. 계산값은 IRIS 계산 엔진에서 확정하고 LLM에는 검증된 구조화 JSON만 전달한다.

참조 파일은 `C:\access\llm\multi_model_dialogue.py`, `C:\access\llm\models.json`,
`C:\access\llm\app.py`, `C:\access\llm\tests` 및 `C:\access\llm\reports`이다.

### 2026-08-24 기본 서버 포트 확정

IRIS 시스템의 기본 서버 포트를 `4823`으로 확정하여 `hx_configuration.conf`, 실행 문서
및 회귀시험에 반영하였다. 기본 접속주소는 `http://127.0.0.1:4823`이다. 설정 반영 후
Health Check와 전체 자동화 시험 73건이 통과했다.

#### 2026-08-24 참조 모듈 반입 결과

재사용 후보를 `C:\access\heat\iris2\llm_integration`에 반입하였다.

- `local_llm.py`: `llama_cpp` GGUF 지연 로딩, Cache, 직렬화 및 Chat Completion Client
- `model_config.py`: `llama_cpp`만 허용하고 외부 Provider를 거부하는 설정 로더
- `models.local.example.json`: 현장 전용 모델 경로 설정 예시
- `requirements.txt`: 로컬 추론 별도 의존성
- `reference/multi_model_dialogue.py`: 원본 참고 사본
- `reference/PRODUCTION_HARDENING_CHECKLIST.md`: 운영 보안 참고 사본
- `reference/PROVENANCE.md`: 원본 경로, SHA-256 및 채택/제외 범위
- `tests/test_model_config.py`: 로컬 설정, 외부 Provider 거부, Thinking Block 제거 시험

반입 모듈 단위시험 3건과 Python Compile을 통과하였다. 현재 IRIS Flask Route와 운영
DB에는 연결하지 않았으므로 기존 시스템 동작에는 영향을 주지 않는다. 모델 파일 자체는
용량·라이선스·현장 사양 확정 전이므로 반입하지 않았다.

## 1. 검토 목적

본 문서는 2026-08-24 현재 개발된 시스템을 고객 요구사항과 대조하고, 다음 항목을
사실 기반으로 재평가하기 위해 작성하였다.

1. 구현된 기능과 실제 운영 적용 상태의 구분
2. IRIS/PDF 데이터 처리, Dashboard, Tube Sheet Map, 잔여수명 및 API 510 기능 검토
3. 로컬 LLM 보고 기능의 구현 여부 확인
4. 데이터 품질, 시험, 보안, 배포 및 현장 구축 준비도 검토
5. 2026-11-30 구축 완료 및 2026-12-31 테스트 완료를 위한 우선조치 도출

이전 분석에서 API 510 Sec.7 및 자체 Tube Plugging 계산이 미반영된 것처럼 해석될
여지가 있었으나, 재검토 결과 두 계산 로직은 모두 구현되어 있다. 남은 핵심은 신규
수식 개발이 아니라 실제 설계자료 적용, 독립 검산, 승인 계산서 생성 및 고객 UAT이다.

## 2. 검토 범위와 방법

### 2.1 검토 대상

- Flask 애플리케이션과 서비스 계층
- SQLite 정규화 DB 및 3.8.0 마이그레이션
- JSON 검증·적재 모듈
- Tube Map, 잔여수명, API 510/ASME 계산 모듈
- 사용자·권한·CSRF·세션 설정
- Excel/PDF 조회 및 보고 화면
- 기존 자동화 시험 70건과 신규 LLM 모듈 시험 3건의 구성 및 실행 가능 여부
- 실행 스크립트, 의존성 목록, 배포 생성 도구 및 백업 자료

### 2.2 수행한 검증

- Python 전체 소스 `compileall`: 성공
- 운영 DB `PRAGMA integrity_check`: `ok`
- 운영 DB `PRAGMA foreign_key_check`: 위반 0건
- 운영 DB 주요 테이블 정량 조회
- `server.py --health-check`: 성공
- 기존 애플리케이션 70건과 신규 LLM 독립 모듈 3건, 총 73건: 전부 통과
- 코드의 외부 URL 및 외부 통신 라이브러리 참조 검색
- 보안 미들웨어, 권한, CSRF, 업로드 및 API 토큰 로직 점검

### 2.3 검토 한계

- Health Check와 자동화 시험은 통과했으나 실제 브라우저 End-to-End 시각 검수는 수행하지 않았다.
- 고객의 실제 IRIS 장비 Raw 파일 형식과 전체 과년도 PDF 모집단이 제공되지 않았다.
- API 510 원문은 라이선스 문서이므로 고객 적용 판본의 독립 계산서 검산은 수행하지 않았다.
- 실제 현장 PC, 네트워크, GPU, 방화벽 및 백업 저장소를 이용한 시험은 수행하지 않았다.
- 부하·성능·장시간 연속운전 시험은 수행하지 않았다.

## 3. 종합 결론

현재 시스템은 열교환기 기준정보, 다년 검사 이력, 튜브 단위 결과, Tube Map,
자체 Plugging 예측, API 510/ASME 계산 프레임, 권한 및 업무 Workflow의 기반을
상당 부분 확보하였다. 특히 API 510 Sec.7 계열 잔여수명과 자체 Tube Plugging
예측은 별도 계산 방식으로 구현되어 있으며, 혼용 방지를 위한 화면 안내도 존재한다.

다만 현재 상태를 곧바로 현장 구축 완료본으로 볼 수는 없다. 주요 이유는 다음과 같다.

- 기본 서버 포트 `4823` 적용 후 Health Check와 전체 자동화 시험 73건이 통과했다.
- 웹 IRIS 적재는 범용 Raw 임포트가 아니라 지정 구조의 JSON 단일 파일 처리이다.
- PDF 11건은 열람 및 이미 변환된 페이지 메타데이터를 보유하지만 PDF 직접 일괄 추출기는 없다.
- Dashboard는 현황표 중심이며 운영 KPI 필터·위험 추세·Drill-down이 부족하다.
- Tube Map 실제 X/Y 좌표가 0건이어서 현재 배열은 실제 Tube Sheet 도면과 동일하다고 보장할 수 없다.
- API 510 계산 코드와 승인 Workflow는 있으나 운영 부품/계산서 데이터가 각각 0건이다.
- 로컬 LLM 기반 요약·보고서 초안 생성은 구현되지 않았다.
- 운영 DB 품질 이슈 434건이 전부 OPEN 상태이다.
- 최신 애플리케이션에 대한 재현 가능한 배포본과 현장 설치 검증이 완료되지 않았다.

따라서 현 단계의 판단은 **핵심 업무 기반 구축 완료, 고객 요구 전체 기준 통합 개발 진행 중,
현장 배포 기준선은 미완료**이다.

## 4. 시스템 기준선

### 4.1 기술 구성

| 구분 | 현재 구성 |
|---|---|
| 서버 | Python Flask 3.1.3 + Waitress 3.0.2 |
| ORM/DB | SQLAlchemy 2.0.49 + SQLite WAL |
| Excel | openpyxl 3.1.5 |
| ML | scikit-learn 1.9.0, Isolation Forest |
| 프론트엔드 | Jinja HTML, 자체 CSS/JavaScript, 로컬 Three.js |
| 인증 | 로컬 사용자, Werkzeug password hash, 화면별 조회/편집 권한 |
| 실행 | `iris/run.ps1`, `iris/run.cmd`, `iris/server.py` |
| DB 스키마 | 3.8.0 |

최초 검토 시 Python 파일은 33개, 약 13,564행이었다. Route/Application/Domain 및
로컬 LLM 참조 모듈을 반영한 현재 기준은 Python 파일 58개, 약 14,590행이다.
`app.py`의 Route 집중과 인증·정비·API 510·시스템 서비스 책임은 1차 해소했으나,
`services.py`의 잔여수명·Tube Map·설비 저장 로직은 2차 책임 분리가 필요하다.

### 4.2 운영 DB 현황

| 항목 | 금일 조회값 | 해석 |
|---|---:|---|
| 열교환기 | 900 | Master 기준 전체 대상 |
| 검사 이력 보유 열교환기 | 118 | 전체의 약 13.1% |
| 미검사 열교환기 | 782 | 검사 이력 미보유 |
| 검사 객체 | 435 | 범위별 검사 포함 |
| 검사 Campaign | 11 | 연도/라인별 원천 묶음 |
| 물리 튜브 | 2,251 | DB 자산으로 등록된 튜브 |
| 실제 X/Y 좌표 보유 튜브 | 0 | 도면 동일성 확보 전 |
| 튜브 검사 결과 | 6,067 | 정규화 측정 결과 |
| 감육 평가 | 3,835 | 비교 가능/불가 평가 포함 |
| 양의 부식속도 평가 | 397 | 계산 레코드 기준 |
| 양의 부식속도 보유 튜브 | 344 | Plugging 시점 산출 가능 후보 |
| 양의 부식속도 보유 열교환기 | 71 | 운영 예측 가능 후보 |
| 품질 이슈 | 434 | 전체 OPEN |
| 원본문서 | 11 | 현재 JSON/PDF 출처 단위 |
| 원문 페이지 | 2,456 | 페이지 추적 메타데이터 |
| Import Batch | 15 | 적재 실행 이력 |
| 검사계획 | 319 | 계획 Workflow 데이터 |
| 작업지시 | 0 | 운영 실적 없음 |
| 정비이력 | 0 | 운영 실적 없음 |
| 사용자 | 1 | 초기 운영계정 수준 |
| 압력경계 부품 | 0 | API 510 운영 입력 미등록 |
| API 510 계산서 | 0 | 승인 계산서 운영 실적 없음 |

DB 자체 무결성은 양호하다. 다만 데이터 수량이 많다는 사실과 분석에 사용할 수 있는
비교 가능 데이터가 충분하다는 사실은 구분해야 한다. 양의 부식속도를 가진 대상은
71대·344개 튜브이므로 나머지는 예측 불가 사유를 명시해야 한다.

## 5. 고객 요구사항별 정밀 검토

### 5.1 IRIS 검사 원본 데이터 임포트

#### 구현된 내용

- 지정 JSON 스키마 검증
- 공장·생산라인·교환기 Master 매칭
- 공장과 생산라인의 명시적 선택
- Dry-run
- SHA-256 동일 파일 중복 방지
- 같은 파일명의 변경본 감지
- 트랜잭션 기반 적재
- 검사·튜브·측정결과·원문 페이지·검사 실행정보 저장
- 품질 경고 및 적재 결과 보고서 생성
- 부분 적재 상태 및 후처리 실패 상태 기록
- 감육 평가 재생성
- CLI에서는 복수 JSON 인자를 순차 처리 가능

#### 엄밀한 판정

웹 화면은 `request.files.get("json_file")`로 JSON 파일 하나만 처리하며 `.json` 확장자만
허용한다. 따라서 현재의 “IRIS 원본”은 IRIS 장비 Raw 신호 파일이 아니라 PDF에서
사전 구조화된 지정 JSON으로 보는 것이 정확하다.

#### 부족한 내용

- 실제 장비 Raw 형식 파서
- 웹 다중 파일, 폴더 및 ZIP 업로드
- 비동기 작업 Queue와 진행률
- 파일별 중지·재개·재처리
- 관리자 Upsert의 웹 Workflow
- 적재 전후 수량 대조와 승인 확정
- 고객별/벤더별 포맷 어댑터
- 악성 ZIP, 압축폭탄, 대량 파일에 대한 방어

위 항목은 기능 부족사항으로 식별하되, 2026-08-24 의사결정에 따라 시스템 완료 전
개발 범위에서는 제외하고 완료 이후 Backlog로 관리한다. 현재 모듈은 회귀시험과
데이터 무결성 검증을 통해 동결 기준선을 유지한다.

#### 판정

**현행 기준선 동결.** 지정 JSON 적재기는 현재 합의된 범위에서 유지한다. 범용 IRIS Raw
원본 지원 여부는 시스템 완료 이후 별도 범위로 재협의하며, 현재 단계의 완료 판정은
현행 단일 JSON의 검증·중복방지·트랜잭션 적재 회귀시험 통과를 기준으로 한다.

### 5.2 기존 PDF 보고서 일괄 등록

#### 구현된 내용

- 규칙에 맞는 PDF 11개 보관 및 Dashboard 링크
- 브라우저 인라인 열람
- JSON에 포함된 출처 PDF 정보 저장
- 11개 원본문서 및 2,456개 페이지 메타데이터 저장
- PDF 요약/상세 불일치와 행 계산 불일치 경고 저장

#### 엄밀한 판정

현재 PDF 기능은 `{연도}_1P_{생산라인}.pdf` 파일을 정해진 폴더에서 찾아 열람하는 기능이다.
운영 DB의 페이지 정보도 현재 제공 JSON의 `page_inventory`를 적재한 결과이지, 웹에서
임의 PDF를 업로드해 OCR·표·Tube Map을 자동 추출한 결과가 아니다.

#### 부족한 내용

- PDF 다중 업로드 및 영구 원본 보존 정책
- 스캔/텍스트 PDF 판별
- 로컬 OCR
- 표 구조와 Tube Map 추출
- 설비번호·검사일·튜브번호·두께·감육률 자동 매핑
- 추출 신뢰도와 원문 페이지 근거 표시
- 원문/추출값 나란히 검토·수정하는 화면
- 검토·승인 후 DB 반영
- 다양한 보고서 Layout용 파서 회귀시험
- 실패 파일 재처리 및 작업 통계

위 항목 중 표/Tube Map 추출, 핵심 필드 자동 매핑, 신뢰도·페이지 근거, 원문 대조
검토 화면, 승인 후 DB 반영, Layout별 회귀시험, 실패 재처리·통계는 2026-08-24
확정 의사결정에 따라 지속 검토·개선 대상이다. JSON 업로드 UI 동결과 별개로 개발한다.

#### 판정

**미충족에 가까운 부분 충족.** 원문 조회와 추적용 DB 구조는 준비됐으나 고객이 요구한
과년도 PDF 일괄 등록 업무는 별도 개발이 필요하다.

### 5.3 운영 Dashboard

#### 구현된 내용

- 열교환기, 검사, 튜브, 결과, 품질 이슈, 검사계획 KPI
- 미검사 설비 및 지연 계획 수량
- 생산라인별·연도별 검사 객체/교환기/튜브결과 현황
- PDF 링크
- 최근 검사, 최근 적재, 예정 검사

#### 부족한 내용

- 공장·공정·기간 복합 필터
- 검사율, 평균/최대 감육률, 위험도 추세 그래프
- 잔여수명 임박 설비 목록
- KPI 클릭 Drill-down
- 품질 이슈와 지연 검사 알림
- 최근 갱신 시각과 자동 갱신
- 사용자별 Dashboard
- Dashboard PDF/Excel 출력
- 고객 KPI 정의 및 승인

위 9개 항목은 2026-08-24 확정 의사결정에 따라 Dashboard 추가 개발 범위로 승인한다.
요구사항 추적표, 구현 일정 및 UAT 시나리오에서 개별 항목으로 관리한다.

#### 판정

**부분 충족.** 운영 현황판의 기본 기능은 있으나 의사결정 Dashboard로는 보완이 필요하다.

### 5.4 Tube Sheet Map

#### 구현된 내용

- 검사연도/Campaign 선택
- 같은 연도의 복수 검사 범위 병합
- 동일 튜브 복수 결과 중 보수적 최대 감육률 사용
- 0% 정상에서 주의·위험 기준까지 연속 색상
- 미검사·폐쇄·미사용 별도 표시
- 2D/3D 전환
- 전체 회전 및 3D Orbit 제어
- 튜브 선택 상세정보와 다년 이력 연결
- 위치 보정·잠금·변경 사유 및 위치 변경 이벤트
- 좌표 없는 전체 튜브를 추정 위치로 표시하되 DB 자산과 구분

#### 중요한 데이터 제약

운영 DB의 실제 X/Y 좌표 보유 튜브는 0건이다. 따라서 현재 Map은 Row/Column 또는
추정 원형 배치이며 실제 제작도면의 Tube Sheet 위치와 동일함을 보증할 수 없다.

#### 부족한 내용

- 제작도면/CAD/Excel 좌표 적재
- 도면 이미지 기준점 Calibration
- 기준연도와 비교연도 Side-by-side
- 연도 간 감육 증가량 색상 모드
- Map 이미지/PDF 출력
- 좌표 및 전체 튜브 수 충돌 승인 Workflow
- 실제 좌표 적용률 KPI

#### 판정

**기능 기반 대부분 충족, 현장 데이터 적용 미완료.** 실제 좌표 확보가 납품 승인 조건이다.

### 5.5 자체 Tube Plugging 및 잔여수명

#### 구현된 자체 수식

튜브별 Plugging 예상시점은 다음 개념으로 계산한다.

```text
검사일 + ((공칭두께 × Plugging 판정 감육률 - 현재 감육량) ÷ 적용 부식속도)
```

교환기 수명 도달연도는 연도별 예상 Plugging 튜브를 누적하여 전체 튜브의 허용
Plugging 한도 10% 또는 20%를 초과하는 최초 연도로 계산한다.

#### 구현된 기능

- 기본 Plugging 판정 감육률 40%
- 허용 Plugging 10%/20%
- 튜브별 Plugging 예상일/연도
- 연도별 신규 및 누적 Plugging 그래프
- 부식속도 50~300% What-if
- Plugging 감육률과 예측 종료연도 변경
- 측정일 기준 기산
- 예측 불가 원인 표시 Guide

#### 데이터 제약

- 양의 부식속도 보유 대상은 71대·344개 튜브이다.
- 위치 비교가 불가능하거나 부식속도가 0/음수/미산출이면 Plugging 예상시점을 산출하지 않는다.
- 자체 수식은 회사 관리기준이며 API 510 계산으로 표시하지 않도록 화면에서 분리한다.

#### 판정

**로직 구현 완료, 운영 데이터 커버리지 제한.** 고객 관리기준 값과 계산 불가 처리에 대한
UAT가 남아 있다.

### 5.6 API 510 Sec.7, Sec.6 및 ASME VIII

#### 구현된 API 510 Sec.7 계열 로직

- 단기 부식속도
- 장기 부식속도
- 단기/장기 중 보수적인 적용 부식속도 선택
- 잔여 부식여유 `t_actual - t_required`
- 잔여수명 `(t_actual - t_required) / corrosion rate`
- 실제두께가 필요두께 이하일 때 즉시 조치 상태

#### 구현된 API 510 Sec.6 검사주기 로직

```text
min(잔여수명 × 검사주기 계수, 검사유형별 최대주기)
```

- 내부/가동중 검사와 외부검사 구분
- 마지막 검사일 기준 다음 검사일 계산
- 기한 경과 상태 표시
- 현재 기본값은 잔여수명의 0.5, 내부 10년, 외부 5년 상한

#### 구현된 설계/승인 기능

- ASME VIII 내부압력 기준 필요두께와 MAWP 계산
- 원통 Shell, 구형 Shell, 2:1 타원형 Head, 반구형 Head 지원
- 압력경계 부품 Master
- 실제두께와 설계근거 출처
- 코드 판본
- 입력/결과 JSON Snapshot
- 알고리즘 버전
- `DRAFT → SUBMITTED → APPROVED/REJECTED` Workflow
- 승인/반려는 관리자 권한으로 제한
- 승인 계산서의 교환기 종합보고서 연결
- 공식 계산서 대조를 위한 Golden Case fixture

#### 엄밀한 판정

API 510과 자체 Plugging 로직은 모두 반영되어 있고 화면에서도 별도 계산 방식으로
선택한다. 따라서 이 부분은 신규 로직 개발 항목이 아니다.

그러나 운영 DB의 압력경계 부품과 API 510 계산서는 각각 0건이며, 내부 회귀시험 외
공인검사자 또는 압력용기 책임 엔지니어의 독립 검산은 승인 대기 상태이다. 또한 고객의
“API 510 Sec.7 기준 plugging rate” 표현은 API 510 부식속도/잔여수명과 회사의 튜브
Plugging 비율을 혼합한 표현일 수 있으므로 요구사항 추적표에서 두 결과를 분리해야 한다.

#### 남은 조치

1. 고객 적용 API 510 판본·Errata·관할 규정 확정
2. 실제 설계자료와 압력경계 부품 입력
3. 승인 설계계산서와 `t_required`, MAWP 대조
4. 고객 Golden Case 오차 기준 합의
5. 공인검사자/책임 엔지니어 검토·승인
6. 실제 대상 설비 계산서 일괄 생성
7. 승인 결과의 Dashboard 및 AI 보고서 연계

#### 판정

**계산·승인 기능 구현 완료, 엔지니어링 검증 및 운영 적용 미완료.**

### 5.7 로컬 LLM 기반 AI 보고

#### 현재 상태

- 정적 교환기 종합 HTML 보고서가 있다.
- 승인된 API 510 계산 결과를 보고서에 표시할 수 있다.
- `hx_ml.py`의 Isolation Forest는 이상치 검토 기능이며 LLM이 아니다.
- 코드와 웹 자산에서 OpenAI/Ollama/llama.cpp 등 LLM 런타임 연계는 확인되지 않았다.
- 현재 웹 자산에서는 외부 CDN/API 참조가 확인되지 않아 기본 애플리케이션은 로컬 동작 구조이다.

#### 필요한 개발

- `C:\access\llm`의 `llama_cpp` Client 및 모델 Cache 구조를 분리·재사용
- IRIS 전용 로컬 Provider Allowlist와 외부 Provider 차단
- 로컬 LLM 런타임과 모델 선정
- 검사 요약용 검증된 구조화 JSON 생성
- 주요 감육, 전년 대비 변화, Plugging 전망, 품질 이슈 요약
- 수치 계산과 LLM 문장 생성을 분리
- 문장별 검사연도·Tube ID·계산서 근거 연결
- JSON Schema 기반 출력 검증
- 초안 편집, 검토, 승인, 버전 관리
- 모델명·모델 해시·Prompt 버전·생성자 저장
- 승인 전 “AI 생성 초안” 표시
- DOCX/PDF 출력
- 방화벽 및 패킷 캡처 기반 외부 통신 0건 시험
- 환각·누락·수치 불일치 평가세트

#### 참조 구현 적용 원칙

`C:\access\llm`은 구현 참고자료이며 IRIS 운영 의존 애플리케이션으로 직접 연결하지
않는다. IRIS 내부에 작은 로컬 추론 Adapter를 두고, 모델 설정·Cache·요청 직렬화·생성
이력 패턴만 이식한다. 이를 통해 두 시스템의 사용자 DB, 세션, 설정 및 장애영역을
분리하고 IRIS 배포본 자체만으로 오프라인 실행 가능하게 한다.

#### 판정

**미구현.** 기존 데이터 구조가 LLM 입력 기반으로 활용 가능하나 별도 신규 개발이 필요하다.

## 6. 기존 부가 기능 검토

고객이 명시한 개발 범위 외에도 다음 기반 기능이 구현되어 있다.

- 공장·생산라인 기준정보 등록/수정
- 열교환기 등록/수정 및 사양 Revision
- 검사계획 신청·승인·진행·완료 Workflow
- 검사 업체, 소프트웨어, 절차 및 교정 정보
- 튜브 운전 상태와 검사 상태 분리
- 튜브 일괄 상태 변경과 Lifecycle 이력
- 작업지시 및 정비 기록 구조
- 품질 이슈 조회
- 교환기/튜브/검사/상태이력 Excel Export
- 조회 API와 토큰 보호 쓰기 API
- DB Health API
- 사용자별 화면 조회/편집 권한

단, 작업지시와 정비이력은 운영 DB에 0건이므로 현재 평가는 시험 fixture 기반 기능 구현에
한정된다. 공식 시스템 Grade도 고객 확정 기준이 아니라 임시 시스템 판정 규칙이다.

## 7. 코드·데이터 구조 평가

### 7.1 강점

- 기준정보, 검사 Snapshot, 원문 출처, 튜브 결과와 이력을 분리한 정규화 구조
- 원본값과 정규화값을 함께 보존하는 추적성
- SHA-256 중복 방지와 트랜잭션 적재
- DB 외래키 강제, WAL, 30초 busy timeout
- 스키마 3.8.0까지 단계별 Migration
- Master 반영 전 백업과 반영 전후 DB 무결성 검사
- 사양 Revision 및 튜브 Lifecycle/위치 변경 이벤트
- API 510 계산 입력·결과 Snapshot과 승인 상태
- 계산 로직 단위시험 및 Golden Case fixture

### 7.2 구조적 보완점

- `services.py`가 약 136KB로 조회, 계산, 사용자, 정비, 적재 등 다수 책임을 가진다.
- `app.py`도 약 42KB로 인증 미들웨어와 모든 화면 Route가 한 모듈에 집중되어 있다.
- PDF/OCR/LLM 추가 전 `import`, `analytics`, `api510`, `reporting`, `auth` 서비스 분리가 필요하다.
- 스키마 Migration이 애플리케이션 초기화 코드에 누적되어 향후 실패 복구와 버전 통제가 어려워질 수 있다.
- 구조화 Logging과 업무 Audit Log가 부족하다.
- 자동 백업은 일부 관리 스크립트에 있으나 운영 스케줄, 보존주기 및 복구 리허설이 없다.

### 7.3 `app.py`·`services.py` 책임 집중 상세 검토

#### 정량 분석

| 항목 | 분리 전 | 2026-08-24 분리 후 |
|---|---:|---:|
| `app.py` | 900행 | 115행 |
| Flask Route | 56개 | 56개, Endpoint 이름 유지 |
| `create_app()` | 808행 | Application Factory와 등록 호출만 유지 |
| Route 모듈 | 0개 | 기능별 9개 + `web/security.py` |
| `services.py` | 2,705행, 약 136KB | 2,228행, 약 110KB |
| `services.py` 최상위 함수 | 64개 | 45개 |
| `services.py` DB Session 경계 | 45개 | 30개, 분리 모듈 15개 |
| `_remaining_life_projection()` | 338행, 인자 10개 |
| `tube_map_data()` | 230행 |
| `save_exchanger()` | 214행 |
| `exchanger_detail()` | 125행 |
| `_resolve_tube_length()` | 117행 |

최초 검토 시 `services.py`에는 인증·사용자, 색상설정, Dashboard, 설비 Master, 검사,
튜브, Tube Map, 잔여수명, API 510, 정비, JSON 적재, PDF 조회 및 DB Health가 모두
포함돼 있었다. 2026-08-24 1차 분리에서 인증·권한, 정비, API 510 계산·승인,
JSON 적재·DB Health와 튜브 상태 규칙을 별도 모듈로 이동했다. 다만 잔여수명,
Tube Map, 설비 저장 Command는 아직 `services.py`에 남아 후속 분리가 필요하다.

#### 구체적인 결합 문제

1. **HTTP와 업무 입력 검증의 혼재**
   - `remaining_life_simulation()` Route가 Query String 해석, 기본값, 유효성 검사,
     계산 호출, 오류 Flash 및 Template 데이터 조립을 함께 수행한다.
   - `imports()` Route가 업로드 저장경로, 파일명, 확장자, 저장, 실행 및 결과표현을 함께 처리한다.

2. **조회·도메인 계산·화면 표현의 혼재**
   - `_remaining_life_projection()`은 DB 조회, 최신 결과 선정, 부식속도 선택, Plugging
     계산, 그래프 Series 및 화면용 Summary 생성을 한 함수에서 수행한다.
   - `tube_map_data()`는 Campaign 조회, 결과 병합, 실제/추정 위치 생성, 색상 상태,
     운영 상태, Summary 및 API JSON 표현을 함께 만든다.

3. **대형 쓰기 Transaction의 복잡성**
   - `save_exchanger()`가 입력 정규화, Master 생성/수정, 사양 Revision, 부속 테이블,
     관리기준 갱신을 한 함수에서 수행한다.
   - Transaction을 한곳에서 유지하는 장점은 있으나 개별 규칙 시험과 변경 영향 분석이 어렵다.

4. **ORM 객체의 화면 노출**
   - 서비스가 ORM 객체 또는 ORM Tuple을 반환하고 Jinja Template가 속성을 직접 읽는다.
   - Session은 `expire_on_commit=False`로 보완돼 있지만, 화면이 DB Schema에 강하게 결합되고
     관계 Lazy-loading이나 Schema 변경 시 오류가 실행 시점에 나타날 수 있다.

5. **전역 설정·DB 경로 결합**
   - 다수 함수가 모듈 전역 `DB_PATH`와 설정 상수를 직접 사용한다.
   - 테스트 DB, 현장별 정책, Background Worker를 도입할 때 설정 주입이 어렵다.

6. **Application import 부작용**
   - `app.py` 하단의 `app = create_app()`가 Import 시 DB 초기화와 설정 검증을 실행한다.
   - 포트 공란 당시 시험 전체가 Import 단계에서 차단된 사례가 이 결합의 실제 영향이다.

7. **Endpoint 이름 의존성**
   - 권한 설정과 Template의 `url_for()`가 현재 Endpoint 이름을 사용한다.
   - Route를 Blueprint로 단순 이동하면 `blueprint.endpoint`로 이름이 바뀌어 권한과 링크가
     동시에 깨질 수 있으므로 Endpoint 호환 전략이 필요하다.

#### 개선 원칙

1. 전면 재작성하지 않고 현재 73개 통과 시험을 Characterization Test로 사용한다.
2. 기능별 수직 Slice로 분리하되 DB Transaction은 Use Case 단위로 유지한다.
3. 도메인 계산은 Flask와 SQLAlchemy를 모르는 순수 함수로 유지한다.
4. 조회 전용 Query와 변경 Command를 분리하되 형식적인 Repository 계층을 과도하게 만들지 않는다.
5. 기존 `services.py` 공개 함수는 당분간 호환 Facade로 남겨 Route와 시험을 보호한다.
6. 기계적 파일 이동과 업무 로직 변경을 같은 단계에서 수행하지 않는다.
7. 새 PDF/OCR/LLM 기능은 처음부터 분리 구조로 작성하고 기존 대형 파일에 추가하지 않는다.

### 7.4 권장 목표 구조

```text
iris/
  app.py                         # 100~150행의 Application Factory
  server.py
  web/
    security.py                  # 인증, CSRF, Session, Permission Hook
    routes/
      dashboard.py
      exchangers.py
      inspections.py
      tubes.py
      remaining_life.py
      api510.py
      maintenance.py
      imports.py
      reports.py
      api_v1.py
  application/
    dashboard_service.py
    exchanger_service.py
    inspection_service.py
    tube_service.py
    remaining_life_service.py
    api510_service.py
    maintenance_service.py
    import_service.py
    report_service.py
  domain/
    remaining_life.py            # 기존 life_prediction.py의 순수 계산
    pressure_vessel.py           # 기존 pressure_vessel_calculations.py
    tube_map.py                  # 상태·색상·Layout 순수 규칙
    models.py                    # 필요한 입력/결과 Dataclass
  queries/
    dashboard_queries.py
    exchanger_queries.py
    inspection_queries.py
    tube_queries.py
    tube_map_queries.py
  infrastructure/
    database.py                  # Session Factory/Unit of Work
    pdf/
      storage.py
      classifier.py
      extractor.py
      parser_registry.py
    reporting/
      excel.py
      pdf.py
  llm_integration/               # 이미 반입한 Offline 전용 모듈
  services.py                    # 한시적 호환 Facade
```

`application`은 업무 Use Case와 Transaction을 조정하고, `domain`은 순수 규칙,
`queries`는 SQL 조회와 화면용 Read Model 생성, `infrastructure`는 파일·DB·OCR 등 외부
기술을 담당한다. 작은 프로젝트에서 모든 테이블별 Repository를 만드는 것은 오히려
복잡성을 높이므로 권장하지 않는다.

### 7.5 우선 분리 대상

#### 1순위: `app.py` Route 등록 분리

- 초기에는 Blueprint보다 `register_routes(app)`와 명시적 Endpoint 이름을 사용한다.
- 기존 `dashboard`, `exchanger_detail` 등의 Endpoint 이름을 그대로 보존한다.
- `[permissions]`, `url_for()`, CSRF 예외 및 56개 Route 계약을 전부 회귀시험한다.
- `create_app()`에는 설정, Extension, 보안 Hook 및 Route 등록만 남긴다.
- 이후 권한 체계를 Screen Key 중심으로 바꾼 뒤 Blueprint 도입을 검토한다.

이 순서는 Blueprint Prefix로 인한 Endpoint 이름 변경 위험을 피한다.

#### 2순위: 잔여수명 조회와 계산 분리

현재 순수 계산 함수는 이미 `life_prediction.py`에 있으므로 다음 세 부분으로 분리한다.

```text
RemainingLifeQuery
  └─ 최신 측정값, 사양 Snapshot, 감육 평가 조회

RemainingLifeCalculator
  └─ 부식속도 선정, 튜브 Plugging 시점, 누적 한도 계산

RemainingLifePresenter
  └─ Summary, Chart Series, 계산 불가 사유 구성
```

`_remaining_life_projection()`의 인자 10개는 `RemainingLifePolicy`와
`RemainingLifeRequest` Dataclass로 묶는다. 계산 함수에는 ORM 객체 대신 숫자·날짜로
구성된 불변 입력 DTO를 전달한다.

#### 3순위: Tube Map 분리

```text
TubeMapQuery       # Campaign, Tube, Result, Lifecycle 조회
TubeMapMerger      # 동일 연도/튜브의 보수적 결과 병합
TubeLayoutPolicy   # 실제 좌표/Row-Column/추정 원형 배치
TubeMapPresenter   # API JSON, Summary, 범례와 색상 상태
```

실제 좌표와 추정 좌표를 다른 Type으로 표현하여 추정 Slot이 DB 자산으로 저장되는 것을
구조적으로 방지한다. 향후 연도 비교는 `TubeMapComparisonService`로 별도 추가한다.

#### 4순위: 설비 저장 Command 분리

`save_exchanger()`의 Transaction은 유지하면서 내부 단계를 작은 함수로 분리한다.

```text
validate_exchanger_command()
resolve_or_create_equipment()
apply_heat_exchanger_master()
create_spec_revision_if_changed()
apply_side_specs()
apply_management_criteria()
```

모든 단계는 하나의 Session을 전달받아 실행하며 중간 Commit을 금지한다. 이를 통해
가독성을 높이면서 현재 원자성은 유지할 수 있다.

#### 5순위: 인증·권한 분리

- `web/security.py`에 Session 시작, Idle Timeout, CSRF 및 Permission Hook을 이동한다.
- 업무 사용자 CRUD는 `application/user_service.py`로 이동한다.
- Endpoint 이름이 아니라 Screen Key/Action을 Route 등록 시 Metadata로 지정하는 방향을 검토한다.
- 로그인 Rate Limit과 감사로그는 이 분리 이후 추가한다.

### 7.6 신규 기능을 위한 독립 Pipeline

#### PDF/OCR

```text
UPLOAD
 → ARCHIVED
 → CLASSIFIED
 → EXTRACTED
 → MAPPED
 → VALIDATED
 → REVIEWED
 → APPROVED
 → COMMITTED
```

각 단계는 `job_id`, 상태, 입력/출력 Hash, 오류, 경고, 시작/종료시각 및 재시도 횟수를
저장한다. Parser는 보고서 Layout별 Plugin Registry로 구성하고, DB 반영은 승인 후
별도 Commit Service가 수행한다. 이 구조는 현재 JSON 업로드 동결 결정과 충돌하지 않는다.

#### Dashboard

- KPI 정의를 `KpiDefinition`으로 중앙화하여 화면·Excel·PDF가 같은 산식을 사용한다.
- `DashboardQueryService`가 공장·공정·기간 Filter와 Drill-down 조건을 동일 객체로 받는다.
- 초기에는 실시간 SQL로 구현하고 성능 측정 후에만 Snapshot/Cache를 도입한다.
- 자동 갱신은 전체 페이지가 아니라 KPI JSON Endpoint를 사용한다.
- 출력은 화면 HTML을 재해석하지 않고 동일 Read Model을 사용한다.

#### 로컬 LLM 보고

```text
ReportInputBuilder
 → 검증된 구조화 JSON
 → OfflineLlmAdapter
 → JSON Output Validator
 → Evidence Checker
 → DraftRepository
 → Review/Approval
 → DOCX/PDF Renderer
```

- LLM 추론은 Waitress 요청 Thread에서 직접 장시간 수행하지 않는다.
- 로컬 Worker와 영속 Job 상태를 사용하여 요청은 `job_id`를 즉시 반환한다.
- 모델은 계산하지 않고 IRIS 계산 엔진 결과를 문장화만 한다.
- `llm_integration`은 Flask·ORM을 import하지 않는 Adapter로 유지한다.
- 외부 Provider Allowlist 차단과 모델 Hash 검증을 시작 단계에서 수행한다.

### 7.7 단계적 전환 계획

| 단계 | 작업 | 기능 변경 | 완료 기준 |
|---|---|---|---|
| A | Route 계약·응답·권한 Characterization 보강 | 없음 | 73개 시험 + 56개 Route 계약 통과 |
| B | Route 등록 모듈 분리, Endpoint 이름 보존 | 없음 | URL/권한/Template 결과 동일 |
| C | `services.py`를 기능별 모듈로 이동하고 Facade Re-export | 없음 | 기존 Import와 시험 무변경 |
| D | 잔여수명·Tube Map의 Query/계산/Presenter 분리 | 없음 | Golden Case와 API JSON 동일 |
| E | 설비 저장 Command 세분화 | 없음 | Transaction Rollback/Revision 시험 통과 |
| F | Dashboard 신규 기능을 새 구조에서 개발 | 있음 | 고객 KPI·필터·출력 UAT |
| G | PDF/OCR Pipeline 신규 개발 | 있음 | 단계별 재처리·승인·근거 시험 |
| H | 로컬 LLM Job/승인 Pipeline 연결 | 있음 | 근거 검증·외부통신 0건 시험 |

단계 B~E는 Schema 변경 없이 수행하고 각 단계별로 독립 Commit/Release 후보를 만든다.
대규모 파일 이동과 신규 기능을 한 Branch에서 동시에 수행하지 않는다.

### 7.8 코드 품질 목표

- `app.py`: Application Factory 중심 150행 이하 목표
- Route 모듈: 파일당 250행 이하 권장
- Application Service: 하나의 Use Case/Transaction 책임
- 신규 함수: 일반적으로 80행 이하, 150행 초과 금지 원칙
- 도메인 계산: Flask/SQLAlchemy Import 0건
- ORM 객체의 신규 Template/API 직접 반환 금지, 명시적 Read Model 사용
- 새 기능의 `Any`/무정형 Dict 사용 최소화, Dataclass·TypedDict 활용
- 공개 API JSON, Excel Sheet 및 Tube Map JSON에 Contract Test 적용
- DB Migration과 알고리즘 버전을 Release Manifest에 기록

행 수는 절대 규칙이 아니라 책임 집중을 조기에 발견하기 위한 경보값으로 사용한다.

### 7.9 피해야 할 접근

- 현재 `services.py`를 한 번에 삭제하거나 전면 재작성
- 모든 ORM Model마다 형식적인 Repository 생성
- Route 분리와 Endpoint 이름 변경을 동시에 수행
- Refactoring과 DB Schema Migration을 한 작업으로 결합
- PDF/OCR/LLM 로직을 다시 `services.py`에 직접 추가
- LLM 추론을 동기 HTTP 요청 안에서 실행
- 화면별로 KPI 계산식과 Export 계산식을 중복 구현
- 시험 통과만 확인하고 실제 Excel/PDF/Tube Map 시각 결과를 비교하지 않는 방식

### 7.10 2026-08-24 코드 분리 적용 결과

이번 작업은 DB Schema와 업무 계산식을 변경하지 않고 기존 공개 함수와 Endpoint 계약을
유지하는 구조 개선으로 수행했다.

- `app.py`를 115행 Application Factory로 축소했다.
- 보안 Hook과 로그인·사용자 관리 Route를 `web/security.py`로 이동했다.
- Dashboard, 설비, 잔여수명, API 510, 검사, 정비, Tube Map, Import, API/Export Route를
  `web/routes` 아래 9개 모듈로 분리했다.
- Blueprint Prefix를 사용하지 않고 기존 Endpoint 이름을 유지해 권한표와 `url_for()` 계약을 보호했다.
- 인증·권한은 `application/auth_service.py`, 정비는 `application/maintenance_service.py`,
  API 510 계산·승인은 `application/api510_service.py`, JSON 적재·DB Health는
  `application/system_service.py`로 이동했다.
- 튜브 운전 상태 정규화는 `domain/tube_status.py`로 이동했다.
- `services.py`는 기존 Route와 시험을 위한 호환 Facade로 해당 함수를 재수출한다.
- 기존 `iris2.app.API_WRITE_TOKEN` 및 `services.import_file` Mock/Patch 지점도 유지했다.
- JSON 업로드는 현재 기능을 그대로 유지했으며 신규 확장이나 Schema 변경은 하지 않았다.

검증 결과는 다음과 같다.

- Python 3.13 최종 전체 회귀시험: 73건, 94.062초, 전부 통과
- Route: 업무 Route 56개와 기존 Endpoint 이름 유지
- Health Check: `status=ok`, Schema `3.8.0`, Integrity `ok`, FK Issue `0`
- 전체 Python Source `compileall` 성공
- `app.py`: 900행에서 115행으로 감소
- `services.py`: 2,705행에서 2,228행, 최상위 함수 64개에서 45개로 감소

남은 구조 개선 우선순위는 `_remaining_life_projection()`의 Query/계산/Presenter 분리,
`tube_map_data()`의 Query/Layout/색상 Presenter 분리, `save_exchanger()` Command 세분화이다.
PDF/OCR과 LLM 신규 기능은 이번에 만든 분리 모듈 경계 밖으로 다시 합치지 않는다.

## 8. 보안 검토

### 8.1 구현된 통제

- 예측 가능한 고정 비밀키를 사용하지 않고 로컬 난수 Secret 생성
- 비밀번호 Hash 저장
- 관리자와 화면별 조회/편집 권한
- Cookie 인증 Form에 CSRF 검증
- 30분 Idle Timeout
- HttpOnly 및 SameSite Cookie
- 초기 관리자 1명 보장
- 쓰기 API Token 미설정 시 HTTP 503으로 차단
- 업로드 용량 50MB 제한
- `secure_filename` 사용
- PDF 경로 Traversal 방지
- 배포 생성 시 운영 DB, Secret, Upload, Report 및 Backup 제외 로직

### 8.2 위험 및 보완점

| 위험 | 현재 상태 | 조치 |
|---|---|---|
| 평문 HTTP 가능 | `host=0.0.0.0`, Secure Cookie=false | 현장망 정책 확정, TLS Reverse Proxy 또는 localhost 한정 |
| 로그인 무차별 대입 방어 없음 | 실패 횟수/잠금/지연 없음 | 계정 잠금 또는 Rate Limit, 실패 감사로그 |
| 보안 응답 Header 없음 | CSP/HSTS/X-Frame-Options 미설정 | 공통 `after_request` 보안 Header |
| 구조화 보안 로그 없음 | 로그인/권한거부/API 실패 추적 부족 | Rotating Log 및 감사 이벤트 테이블 |
| API Token 단일 공유값 | 사용자별 식별·회수 어려움 | Token Hash, 식별자, 만료, 회수, 호출 이력 |
| 백업 암호화/접근통제 미정 | 로컬 DB 백업 다수 | 보관 위치, ACL, 암호화, 보존·파기 정책 |
| PDF/OCR/LLM 보안 미정 | 기능 미구현 | 파일 Sandbox, 모델 공급망·Hash·라이선스 검증 |

현재 애플리케이션 코드에서는 외부 HTTP API나 CDN 호출을 확인하지 않았다. 다만 향후
로컬 LLM 기능은 런타임의 모델 다운로드, Telemetry 및 자동 업데이트를 차단한 상태로
패킷 시험해야 한다.

## 9. 실행·시험·배포 준비도

### 9.1 금일 실행 결과

`hx_configuration.conf`의 기본 포트를 `4823`으로 확정하고 다음 검증을 완료했다.

```text
기본 접속주소: http://127.0.0.1:4823
Health Check: status=ok
Schema: 3.8.0
Integrity Check: ok
Foreign Key Issues: 0
```

기존 포트 공란으로 발생했던 애플리케이션 Import, Health Check 및 회귀시험 Blocker는
해소되었다. 실제 브라우저 시각 검수와 현장 PC 설치시험은 별도로 남아 있다.

### 9.2 시험 현황

- 기존 애플리케이션 자동화 시험 함수: 70건
- 신규 LLM 독립 모듈 시험: 3건 통과
- Python 문법 Compile: 성공
- 운영 DB 무결성: 성공
- 외래키 검사: 성공
- 전체 회귀시험: 총 73건, 77.150초, 전부 통과
- Health Check: 성공

후속 검증 항목은 다음과 같다.

1. 실제 브라우저 핵심 Workflow Smoke Test
2. Excel/PDF/Tube Map 시각 검수
3. 대량 업로드, 동시 사용자 및 장시간 실행시험
4. 현장 PC 오프라인 설치 및 재기동 시험

### 9.3 의존성 및 재현성

루트 `requirements.txt`에는 Flask, SQLAlchemy, Waitress, openpyxl이 고정되어 있다.
ML용 scikit-learn은 `iris/requirements-ml.txt`에 별도로 있으나 `setup_dev.ps1`은
기본적으로 `requirements-dev.txt`만 설치한다. 현재 가상환경에는 필요한 패키지가
설치돼 있으나 신규 PC 재설치 시 ML 의존성 포함 여부를 명확히 해야 한다.

향후 PDF/OCR/LLM 의존성은 아직 정의되지 않았다. 오프라인 설치를 위해 Wheelhouse,
모델 파일, 라이선스, SHA-256 Manifest가 필요하다.

### 9.4 배포본 상태

- 최신 배포 생성 도구는 운영 DB와 Secret을 제외하고 SHA-256 Manifest를 생성하도록 개선되어 있다.
- 현재 `deployments/HeatExchangerSystem`은 2026-07-21 생성본으로 최신 `iris` 3.8.0 구조 이전 자료이다.
- 최신 코드 기준 배포 생성·설치·실행 검증이 필요하다.
- 검사한 `.git` 디렉터리는 유효한 Git Repository로 인식되지 않아 현재 Workspace에서 변경 이력과 Release Tag를 확인할 수 없다.

납품 전에는 정상 Git Repository 또는 동등한 형상관리에서 Release Tag, Commit ID,
DB Schema, 알고리즘 버전, 설치파일 Manifest를 하나의 Release Record로 묶어야 한다.

## 10. 우선순위별 발견사항

### P0 — 즉시 조치

해소 완료:

- 기본 포트 `4823` 설정 및 문서 반영
- Health Check 성공
- 기존 70건과 신규 LLM 3건을 포함한 전체 자동화 시험 73건 통과

| ID | 발견사항 | 영향 | 완료 기준 |
|---|---|---|---|
| P0-01 | API 510 고객 계산 기준 미승인 | 계산 결과 업무 사용 불가 | 판본/Errata/Golden Case/검산자 승인 |
| P0-02 | 현장 PC·네트워크·LLM 사양 미확정 | AI 일정·성능 예측 불가 | CPU/GPU/RAM/OS/망 정책 확정 |

### P1 — 구축 완료 전 필수

| ID | 발견사항 | 완료 기준 |
|---|---|---|
| P1-01 | PDF 일괄 업로드/OCR/검토 미구현 | 고객 표본 전체 처리 및 승인 Workflow 통과 |
| P1-02 | 실제 Tube Sheet X/Y 좌표 0건 | 대상 도면 좌표 적용 및 Map 검수 |
| P1-03 | API 510 운영 계산서 0건 | 지정 설비 계산서 생성·승인 |
| P1-04 | 품질 이슈 434건 전부 OPEN | 분류·담당·처리·면책 승인 |
| P1-05 | 로컬 LLM 미구현 | 근거 기반 초안·승인·외부통신 0건 시험 |
| P1-06 | Dashboard 운영 분석 부족 | 필터·추세·위험목록·Drill-down UAT |
| P1-07 | 최신 배포본 부재 | 깨끗한 PC에서 설치·기동·복구 검증 |

### P2 — 안정화 및 운영성

- 로그인 Rate Limit과 실패 감사로그
- 보안 Header와 TLS 적용
- 잔여수명·Tube Map·설비 저장 Command의 2차 서비스 모듈 분리
- 구조화 로그와 장애 진단 화면
- 자동 백업, 보존, 암호화 및 복구 리허설
- 성능 기준과 장시간 연속운전 시험
- 사용자/관리자/운영자 매뉴얼과 교육

## 11. 수정된 개발 계획

API 510 및 자체 Plugging 수식은 이미 구현됐으므로 계획을 “신규 수식 개발”이 아니라
“검산·운영 적용·통합”으로 수정한다.

JSON 업로드 기능은 현행 기준선으로 동결하며 아래 일정에는 기능 확장을 포함하지 않는다.
해당 기간의 JSON 관련 작업은 회귀시험, 장애 수정 및 데이터 무결성 확인에 한정한다.
단, 보고서 표/Tube Map 추출부터 자동 매핑, 원문 근거, 검토·승인, 파서 회귀시험,
실패 재처리·통계까지의 데이터 품질 Pipeline은 별도 개선 Track으로 계속 수행한다.

| 기간 | 단계 | 주요 산출물 |
|---|---|---|
| 08.24~08.28 | 기준선 복구·요구 확정 | 포트/시험 정상화, JSON 동결 회귀기준, PDF/API 510/현장 PC 명세 |
| 08.31~09.11 | PDF 적재 기반 | PDF 원본 보존, 작업 관리, 진행률, 재처리, 승인/감사 구조 |
| 09.07~10.02 | PDF 처리 | OCR/표 추출, 원문 대조·수정·승인 화면 |
| 09.14~10.09 | API 510 운영 적용 | 실설계 데이터, Golden Case, 공인 검산, 승인 계산서 |
| 09.21~10.23 | Dashboard/Tube Map | 필터·추세·Drill-down, 실제 좌표, 연도 비교, 출력 |
| 10.05~11.06 | 로컬 LLM | 구조화 초안, 근거 연결, 편집·승인, DOCX/PDF |
| 11.02~11.20 | 통합·보안·성능 | 전체 회귀, 대량 적재, 권한, 로그, 백업/복구, 통신 차단 |
| 11.23~11.30 | 현장 구축 | 설치, 데이터 이관, 계정, 교육, 구축 완료 확인 |
| 12.01~12.11 | SIT | 요구사항 추적표 기반 시스템 통합시험 |
| 12.14~12.24 | UAT | 고객 업무 시나리오, 엔지니어 검산, AI 품질 평가 |
| 12.28~12.31 | 인수 | 잔여 결함 확인, 시험성적서·소스·설치본·매뉴얼 인계 |

## 12. 권장 인수 기준

### 12.1 데이터 처리

- 현행 단일 JSON 검증·중복방지·트랜잭션 적재 회귀시험 통과
- 동결 기간 중 기존 JSON Schema 및 적재 결과의 하위 호환성 유지
- PDF 파일별 성공/경고/실패 및 재처리 이력 100% 추적
- 원본 Hash, 페이지 근거, 수정자, 승인자 추적 가능
- PDF 핵심 수치 추출 정확도 목표와 표본검사 기준 고객 승인

### 12.2 분석

- 자체 Plugging과 API 510 결과가 화면/DB/보고서에서 명확히 분리
- API 510 Golden Case가 합의 오차 이내
- 계산 불가 설비는 임의 보간하지 않고 사유 표시
- 실제 좌표 적용 대상 Tube Map이 제작도면과 일치
- 연도별 이력 및 비교 그래프 UAT 통과
- 공장·공정·기간 복합 필터의 조회 결과가 원천 DB 집계와 일치
- 검사율, 평균/최대 감육률 및 위험도 추세 산식이 고객 승인 KPI 정의와 일치
- 잔여수명 임박 목록과 KPI Drill-down 상세 건수가 일치
- 품질 이슈·지연 검사 알림의 발생 및 해제 조건이 정상 동작
- 최근 갱신 시각과 자동 갱신주기가 화면에 명시되고 정상 동작
- 사용자별 Dashboard 구성과 화면 권한이 서로 일치
- Dashboard PDF/Excel 출력값이 동일 조회조건의 화면값과 일치

### 12.3 AI 보고

- 모든 수치가 구조화 데이터 또는 승인 계산 결과와 일치
- 문장별 근거 설비/검사/Tube ID 확인 가능
- 승인 전 초안과 승인본 명확히 구분
- 모델/Prompt/생성/수정/승인 버전 추적
- 외부 통신 0건 시험 통과

### 12.4 운영·보안

- 깨끗한 현장 PC에서 오프라인 설치 및 Health Check 성공
- 전체 자동화 시험 통과
- 사용자 권한, CSRF, 세션 만료, API Token 시험 통과
- 백업에서 신규 PC로 복구 성공
- 성능 및 연속운전 기준 통과
- 설치본 SHA-256 Manifest와 Release Record 인계

## 13. 최종 판단

1. API 510 Sec.7, Sec.6 검사주기 및 자체 Tube Plugging 수식은 구현되어 있다.
2. 현재 API 510의 핵심 미완료는 수식 개발이 아니라 실제 설계자료 등록, 독립 검산,
   승인 계산서 운영 적용이다.
3. Tube Map은 기능적으로 성숙했으나 실제 좌표가 없어 현장 도면 일치성은 미확보 상태이다.
4. JSON 적재는 현행 단일 파일 기능으로 동결하며 기능 확장은 시스템 완료 이후 Backlog로 관리한다.
   PDF 일괄 등록은 동결 대상이 아니므로 별도 개발을 계속한다.
5. 로컬 LLM 보고 기능은 신규 개발 대상이다.
6. 기본 포트 `4823`, Health Check 및 전체 자동화 시험 73건은 정상화됐다. 다음 우선과제는
   API 510 고객 검산기준과 현장 PC·네트워크·LLM 사양 확정이다.
7. 2026-11-30 구축 완료 일정은 가능하나 PDF/OCR, 실제 좌표, 로컬 LLM을 병렬 개발하고
   API 510 검산자 및 고객 의사결정을 즉시 확보해야 한다.

---

### 주요 코드 근거

- Application Factory: `app.py`
- Route 및 보안 미들웨어: `web/security.py`, `web/routes/`
- 기존 업무 API 호환 Facade와 잔여 집중 로직: `services.py`
- 분리된 Application Service: `application/auth_service.py`, `application/maintenance_service.py`,
  `application/api510_service.py`, `application/system_service.py`
- 튜브 상태 Domain 규칙: `domain/tube_status.py`
- 자체 Plugging/API 510 계산: `life_prediction.py`
- ASME VIII 계산: `pressure_vessel_calculations.py`
- JSON 적재: `iris_v2_importer.py`
- JSON 검증: `iris_json_validator.py`
- DB 스키마/마이그레이션: `iris_v2_database.py`, `iris_v2_models.py`
- Tube Map: `templates/tube_map.html`, `static/tube-map.js`
- 계산 선택 화면: `templates/remaining_life_simulation.html`
- API 510 관리: `templates/api510_management.html`
- API 510 검산 상태: `docs/API510_ENGINEERING_VALIDATION.md`
- 실행 설정: `hx_configuration.conf`, `hx_configuration.py`
