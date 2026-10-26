# AI 적용 1단계 완료 기준

## 목적과 범위

1단계는 AI가 설비 상태를 자동 판정하는 단계가 아니다. 운영 DB를 변경하지 않고, 기존 이상치 분석 결과를 전문가가 검토할 수 있도록 품질 Gate, 전문가 라벨, 정량 평가 기준을 고정하는 단계다.

## 1. 품질 Gate 확정

두 검사 시점의 감육 추세 비교에는 `thickness-trend-g1-g7-1.0`을 적용한다.

| Gate | 검증 항목 | 실패 처리 |
|---|---|---|
| G1 | 공장·라인·교환기·Bundle·Tube 동일성 | DQ-BLOCK |
| G2 | 검사일 존재 및 시간 순서 | DQ-BLOCK |
| G3 | 최소 두께 존재 | DQ-HOLD |
| G4 | 공칭두께 근거 존재 및 허용 범위 내 일관성 | 누락 DQ-HOLD, 변경 DQ-BLOCK |
| G5 | 감육률 계산식 재계산 일치(허용차 1.0%p) | 누락 DQ-HOLD, 불일치 DQ-BLOCK |
| G6 | 두께 증가와 감육률 증가의 방향 충돌 여부 | DQ-BLOCK |
| G7 | 검사 간격 0.5년 이상 | DQ-HOLD |

`DQ-BLOCK`은 모델 입력에서 제외하고 원천·매핑·계산식 정정 대상으로 보낸다. `DQ-HOLD`는 근거 보완 또는 재검사 전까지 평가에 사용하지 않는다.

## 2. 전문가 라벨 확정

| 라벨 | 의미 | Precision 정답 포함 |
|---|---|---|
| CONFIRMED_SOURCE_ERROR | 원천자료 오류 | 예 |
| CONFIRMED_MAPPING_ERROR | 설비·Tube 매핑 오류 | 예 |
| CONFIRMED_FORMULA_ERROR | 계산식 오류 | 예 |
| CONFIRMED_MEASUREMENT_VARIATION | 측정 변동 확인 | 예 |
| RECHECK_REQUIRED | 재검사 필요 | 예 |
| VALID_EXTREME_VALUE | 유효한 극단값 | 아니오 |
| ENGINEERING_ACCEPTED | 엔지니어링 수용 | 아니오 |
| INSUFFICIENT_EVIDENCE | 근거 부족 | 아니오 |

모든 라벨에는 판단 근거를 필수 입력한다. 수정 시 기존 행을 덮어쓰지 않고 새 이력을 추가하며, 화면과 평가는 가장 최근 라벨을 사용한다.

## 3. 평가 기준 확정

| 지표 | 통과 기준 |
|---|---|
| Top-30 검토 커버리지 | 30/30, 100% |
| Precision@30 | 60% 이상 |
| Hard Gate 치명 누락 | 0건 |
| 자동 판정 | 비활성 유지 |

30건 검토 전 상태는 `COLLECTING`, 기준 충족은 `PASS`, 전건 검토 후 기준 미달은 `HOLD`로 표시한다. `PASS`도 자동 안전 판정이나 운전 의사결정을 허용하지 않는다.

## 4. 운영 방식

- 화면: `/inspections/ml-review`
- 조회 권한: INSPECTIONS 조회 권한
- 라벨 저장: INSPECTIONS 편집 권한 및 CSRF 검증
- 저장소: `data/ml_review_feedback.db` 별도 분석 DB
- 추적 필드: 분석 run, 모델 버전, 결과·검사·Tube ID, 라벨, 근거, 검토자, UTC 시각
- 운영 DB: 읽기 전용으로 유지하며 전문가 라벨 저장 시 변경하지 않음

## 5. 완료 조건

- G1~G7 단위 테스트 통과
- 라벨 허용값·근거 필수·추가 이력·최신값 조회 테스트 통과
- `COLLECTING`·`PASS`·`HOLD` 평가 테스트 통과
- 검토 화면에서 원본 검사와 Tube로 역추적 가능
- 자동 판정 비활성 표시 유지
