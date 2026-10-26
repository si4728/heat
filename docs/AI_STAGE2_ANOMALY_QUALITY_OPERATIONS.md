# AI 적용 2단계 이상치·품질 탐지 운영화

## 운영 범위

2단계는 VCM1·VCM2 IRIS 결과를 읽기 전용으로 분석하여 검토 우선순위와 데이터 품질 신호를 생성한다. 결과는 전문가 검토를 지원하며 원본 측정값, Tube 상태, 정비 상태 또는 API 510 판정을 변경하지 않는다.

## 실행 경로

프로젝트 디렉터리에서 다음 명령을 실행한다. Windows PowerShell 실행 정책의 영향을 받지 않는 기본 운영 명령이다.

```powershell
.\.venv-ml\Scripts\python.exe .\tools\run_ml_anomaly_quality.py
```

PowerShell 스크립트 실행이 허용된 환경에서는 `.\tools\run_ml_anomaly_quality.ps1`도 사용할 수 있다.

스크립트는 검증된 `.venv-ml` Python 3.13 환경과 `requirements-ml-lock.txt` 버전을 사용한다. 직접 실행 시 다음 명령을 사용할 수 있다.

```powershell
.\.venv-ml\Scripts\python.exe -m iris2.ml.cli run-anomaly-quality `
  --database iris\data\heat_exchanger_db3.db `
  --artifacts iris\outputs\ml_implementation `
  --review-database iris\data\ml_review_feedback.db
```

## 실행 안전장치

- 운영 DB는 SQLite `mode=ro` 및 `query_only=ON`으로 조회한다.
- 실행 전후 DB SHA-256을 비교하며 변경 감지 시 `FAIL` 처리한다.
- `.anomaly-quality.lock`으로 중복 실행을 차단한다.
- 결과는 Run ID별 디렉터리에 atomic write한다.
- 전문가 라벨이 30건 미만이면 제한된 `PASS_WITH_NOTE` 검토 모드를 유지한다.
- Hard Gate는 ML 점수보다 우선하며 ML이 해제할 수 없다.
- 자동 원천 수정과 자동 엔지니어링 판정은 항상 비활성이다.

## 산출물

각 실행은 `outputs/ml_implementation/<run_id>/` 아래에 다음을 생성한다.

- `run_summary.json`: 실행 상태, DB Hash, Gate
- `stage_2_result.json`: 2단계 결과
- `data/dataset_snapshot.json`: 데이터셋 버전, 건수, 논리 Hash
- `evaluation/anomaly_pilot.json`: Top-30 검토 우선순위
- `evaluation/quality_detection.json`: Hard Gate, 품질 신호, ML 이상치 집계

## 화면 확인

`검사 관리 → ML 검토대상`에서 다음을 확인한다.

- 최신 Top-30 검토대상
- 품질 신호 행, ML 이상치, Hard Gate 건수
- 전문가 검토 진행률과 Precision@30
- 최근 탐지 실행 이력과 운영 DB 변경 여부

## 운영 주기 권고

초기에는 신규 IRIS 데이터 적재 후 관리자가 수동 실행한다. 현업 검토와 실행시간이 안정된 뒤 Windows 작업 스케줄러 등으로 주기 실행할 수 있다. 자동 스케줄을 등록하더라도 동시 실행 차단과 DB 불변성 Gate는 유지한다.

## 장애 및 복구

- 의존성 누락: `.venv-ml`과 잠금 파일을 재구성한 뒤 재실행한다.
- 중복 실행: 기존 프로세스 종료 여부를 확인한다. 프로세스가 없을 때만 잔존 lock 파일을 제거한다.
- `FAIL`: 해당 Run 결과를 운영 화면의 승인 결과로 사용하지 않고 DB Hash 및 Gate를 확인한다.
- Artifact 손상: 손상된 Run을 사용하지 않으며 이전 정상 Run은 그대로 보존한다.
