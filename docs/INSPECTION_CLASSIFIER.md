# 검사 이력 분류 모델

현재 설비 특성으로 과거 검사 이력 유무를 분류하는 오프라인 모델이다. 검사 필요성·고장 확률·운전 승인 모델이 아니다. 운영 DB와 검사계획은 변경하지 않는다.

## 데이터 흐름

1. 사용자가 제공한 설치 마스터를 `data/import/inspection_classifier/master_install_source.xlsx`에 보존한다.
2. MariaDB 읽기 전용 일관 스냅샷에서 VCM1·VCM2의 설비 키와 검사기록 수를 수집한다. 검사기록 1건 이상은 1, 없으면 0이다.
3. 자산번호 일대일 매칭, 중복 키, 설치일 형식·범위, 공정 및 코드 누락을 검사한다.
4. 입력은 Excel 마스터에 실제 존재하는 값만 사용한다. I열 설치일에서 연도, F열 설비Tag에서 생산라인(US-VC→VCM1, US-EV→VCM2), E열 공정, H열 설비내역에서 용도를 얻는다. DB/JSON 값으로 보충하지 않는다. 용도를 추출하지 못하면 OTHER 및 검토 필요 표시를 남긴다. Tag 매핑 실패는 DB로 대체하지 않고 제외한다.
5. 공칭두께는 검사 시 입력된다는 사용자 확인에 따라 제외한다. 현재 Excel에는 재질·유체·두께·튜브 수량·길이 값이 없으므로 이들 JSON/DB 전용 값도 제외한다. 순번·자산번호·Item No.는 식별/결합/평가 그룹 구분용이며 입력 특징으로 학습하지 않는다. 생산팀은 대상 범위에서 상수이므로 제외한다.
6. E-201A/B와 교체·예비 코드처럼 같은 라인·같은 숫자 계열은 한 그룹으로 묶어 평가한다. 코드는 모델 입력이 아니다.
7. 5개 그룹 폴드·3개 고정 시드로 평가하며 표준화·원핫 인코딩은 학습 폴드 내부에서만 학습한다. 주 모델 로지스틱 회귀는 결과를 보기 전에 고정했다.
8. 전체 데이터로 학습한 배포용 로컬 모델과, 해당 행을 제외한 OOF 검토 점수를 구분해 저장한다.

## 실행

IRIS2 폴더에서 아래 명령을 실행한다. 출력 폴더는 실행마다 새 이름을 사용한다.

```powershell
.\.venv\Scripts\python.exe tools/run_inspection_classifier.py train --source data/import/inspection_classifier/master_install_source.xlsx --output reports/inspection_classifier/new_run --as-of 2026-10-29
```

`--as-of`는 설치일 범위 점검 기준일이다. 검사 이력 라벨은 수집 시 DB에 존재하는 모든 이력 기준이다. 새로운 원본 및 DB 조회 시점의 해시를 실행 기록에 남긴다.

생성한 로컬 모델을 다시 사용하려면:

```powershell
.\.venv\Scripts\python.exe tools/run_inspection_classifier.py predict --model reports/inspection_classifier/20261030_run03_excel_only/model.joblib --input reports/inspection_classifier/20261030_run03_excel_only/dataset.csv --output reports/inspection_classifier/20261030_run03_excel_only/new_predictions.csv
```

예측 CSV에는 `installation_year`, `unit_code`, `process_code`, `service_role` 열이 필요하다. 추가로 입력한 공칭두께·검사 결과·정답 열은 학습 및 예측 입력에서 사용하지 않는다. 전체 학습 모델의 재예측 점수를 검증 성능으로 보고하지 않는다. joblib 모델은 직접 생성한 신뢰 가능한 로컬 파일만 로드한다.

## 산출물

- `REPORT.md`: 수집·제외·성능·검토 후보와 한계.
- `dataset.csv`: 정리된 212대, 원본 행·설치일·식별정보·정답.
- `source_column_audit.csv`: 원본 열별 입력 결정과 양 그룹의 실제 값 유무.
- `feature_audit.csv`: 모델 항목별 포함/제외 사유.
- `feature_lineage.csv`: 모델 입력 4개의 Excel 열·헤더·변환 규칙 및 DB/JSON 대체 금지 정책.
- `data_quality.json`, `manifest.json`: 행 제외·날짜 대조·출처/데이터/코드 해시·환경.
- `evaluation.json`, `fold_assignments.csv`: 반복 성능과 설비별 평가 폴드.
- `subgroup_metrics.csv`: 생산라인·공정·설치연대별 오분류.
- `oof_predictions.csv`, `uninspected_review_candidates.csv`: 검증 점수와 미검사 검토 목록. 검토 상태·라벨·사유를 기록할 수 있다.
- `model.joblib`, `model_coefficients.csv`: 주 모델과 특징별 연관성 계수. 계수는 원인이나 안전 기준이 아니다.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_inspection_classifier -v
.\.venv\Scripts\python.exe tools/run_validation.py
```

실험 결과만으로 웹 UI의 검사 우선순위나 기존 관리 기준을 바꾸지 않는다. 담당자 검토 결과를 축적한 뒤 별도의 검사 필요성 정답과 외부 평가 자료로 확장한다.
