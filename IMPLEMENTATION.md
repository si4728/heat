# 신규 DB 적용 시스템 구현 결과

작성일: 2026-08-05

## 적용 범위

`C:\access\heat\iris2`에 신규 Flask 시스템을 생성했다. 기본 연결 DB는 검증 및
적재 완료된 `C:\access\heat\heat_exchanger_v2.db`이며 기존 `app.py`와
`heat_exchanger.db`를 사용하지 않는다.

## 화면

| 경로 | 기능 |
|---|---|
| `/` | 교환기·검사·튜브·품질 이슈 현황과 최근 검사/적재 |
| `/exchangers` | 생산라인, 검사 상태, 설비번호 기준 교환기 조회 |
| `/exchangers/new` | IRIS 이력이 없는 교환기 등록 |
| `/master-data/plants-lines` | 공장 및 생산라인 코드 등록·수정과 연결 설비 수 조회 |
| `/exchangers/{id}` | 교환기 자산 정보 및 다년 검사 이력 |
| `/exchangers/{id}/tube-map` | 감육률 연속 색상, 선택 이동, 전체 회전을 지원하는 연도별 2D/3D Tube Map |
| `/exchangers/{id}/edit` | 기본정보·기술 사양·관리 기준 수정 |
| `/exchangers/{id}/tubes/manage` | 튜브 검색·필터·일괄 상태 및 좌표 잠금 관리 |
| `/exchangers/{id}/report` | 교환기 종합 인쇄 보고서 |
| `/inspections` | 전체 검사 검색 및 시스템 Grade |
| `/inspection-plans` | 검사계획 등록·상태·지연 일정 관리 |
| `/maintenance` | 작업지시 및 정비·교체 이력 관리 |
| `/inspections/{id}` | 검사별 전체 튜브 결과와 검증 이슈 |
| `/tubes/{id}` | 동일 물리 튜브의 연도별 결과 및 감육 추세 |
| `POST /tubes/{id}/status` | 튜브 운전 상태 변경 및 lifecycle 이력 저장 |
| `/imports` | 신규 JSON 검증·적재와 단계별 결과 표시 |
| `/quality-issues` | 원본별 품질 경고 검토 |
| `/api/health` | 스키마·외래키·DB 무결성 확인 |
| `/api/exchangers/{id}/tube-map` | 연도별 튜브 좌표·검사 상태·감육률 JSON |
| `/exports/heat-exchangers-tubes.xlsx` | 현재 DB의 교환기·튜브·검사 이력 Excel 다운로드 |
| `/api/v1/exchangers` | 외부 교환기 조회 및 토큰 보호 등록 API |
| `/api/v1/exchangers/{id}/history` | 외부 다년도 검사 이력 조회 API |

Tube Map은 같은 연도의 복수 검사 범위를 하나로 합치며, 동일 튜브에 결과가 여러
건이면 최대 감육률(보수적 값)을 사용한다. 정상·주의·위험 구간은 교환기별 관리
기준을 적용하고, 미검사 및 Plugged 튜브를 별도 상태로 관리한다.

감육 색상은 `녹색(0%) → 노란색(주의 임계값) → 빨간색(위험 임계값)`의 연속
보간을 사용한다. 2D는 포인터 드래그, 3D는 TransformControls로 선택 튜브를
이동하며 전체 배열은 공통 회전 각도와 OrbitControls로 회전한다. 이동은 관리 대상,
잠금 해제, 사유 입력 조건을 만족해야 하고 저장 API가 위치 변경 이력을 생성한다.

> 현재 구현에서는 사용자 요구에 따라 전체 튜브 수만큼 화면에 표시한다. 원본
> 좌표가 없는 튜브는 `CIRCULAR_ESTIMATE` 레이아웃의 시각화 전용 슬롯으로 생성하고
> `position_source=ESTIMATED`, `managed=false`로 반환한다. 따라서 추정 위치를 실제
> Tube Sheet 좌표나 자산 마스터로 저장하지 않는다.

튜브 상태는 운전 상태와 검사 상태를 분리한다. 운전 상태는 `IN_SERVICE`(사용 중),
`PLUGGED`(폐쇄)로 관리하며 변경 이벤트를
`tube_lifecycle_event`에 저장한다. 검사 상태는 선택 연도의 결과 유무에 따라
`INSPECTED` 또는 `NOT_INSPECTED`로 계산하므로, 폐쇄 튜브에도 과거 검사 이력을
그대로 유지할 수 있다.

Excel Export는 실제 물리 튜브 마스터만 내보낸다. 2D/3D 화면의 추정 위치 튜브는
DB 자산이 아니므로 Excel의 `튜브` 시트에 포함하지 않는다. 요약 수량은 각 데이터
시트를 참조하는 Excel 수식으로 구성하고, 파일을 열 때 자동 재계산한다.

생산공장(`plant`)과 생산라인(`process_unit`)은 별도 기준정보로 관리한다. P1·P2는
각각 생산공장 1·2를 의미하고 VCM1·VCM2는 생산라인 코드이다. 생산라인 코드가
VCM으로 시작해야 한다는 제약은 없다. 교환기 등록은
`unit_id` 외래키로 생산라인을 선택하므로 다른 공장에 같은 생산라인 코드가 있어도
혼동하지 않는다. 기존 코드 기반 호출은 이미 등록된 공장·생산라인 조합만 허용하고,
오타 코드를 자동 생성하지 않는다.

생산공장 코드는 `P[1-9][0-9]*` 규칙으로 검증하여 P1부터 필요한 Pn까지 등록할 수
있다. JSON에는 생산공장 코드가 없으므로 적재 화면에서 등록된 Pn을 먼저 명시적으로
선택한다. 기본값을 자동 선택하지 않으며, 파일명·본문에서 판별한 VCM 코드는 선택한 생산공장 아래의
생산라인으로 연결한다.

현재 운영 DB의 기존 데이터는 모두 P1(생산공장 1) 소속으로 확정하여 기존 공장
마스터 코드를 `HANWHA`에서 `P1`로 변경했다. 관계는 `plant_id` 외래키를 유지하므로
기존 VCM1·VCM2 교환기와 검사 이력의 식별자는 변경하지 않는다.

## 우선 기능 복원

- 검사계획과 예정·승인·진행·완료·취소 Workflow
- 튜브 번호 검색, 상태 필터, 선택 일괄 변경과 lifecycle event
- 튜브 X/Y/Z 보정, 위치 잠금 및 변경 사유 이력
- 교환기 종합 인쇄 화면
- 전체 검사 목록과 관리 임계값 기반 시스템 Grade
- 정비 작업지시와 튜브 정비·교체·폐쇄 이력
- 외부 조회 API 및 `hx_configuration.conf`의 `api_write_token` 기반 쓰기 보호

시스템 Grade는 회사 공식 Grade가 확정되기 전까지 A=주의/2 미만, B=주의 미만,
C=위험 미만, D=위험 이상 규칙을 사용하며 화면에 시스템 판정임을 표시한다.

## 검증 결과

- 신규 시스템 통합 테스트: 13개 통과
- v2 코어 및 적재 테스트: 5개 통과
- PDF 연결 테스트: 3개 통과
- 관련 테스트: 21개 통과
- 실제 데이터 화면 조회: 교환기 103개, 검사 229건, 물리 튜브 1,637개,
  튜브 결과 3,119건, 품질 경고 27건
- DB 스키마: 2.3.0 / 34개 테이블
- 외래키 위반: 0
- SQLite integrity check: `ok`

## 실행

```powershell
cd C:\access\heat
.\.venv\Scripts\python.exe iris\server.py
```

기본 접속 주소: `http://127.0.0.1:4823`
