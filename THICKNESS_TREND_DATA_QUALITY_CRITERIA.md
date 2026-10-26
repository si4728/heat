# IRIS 두께 추세 데이터 품질 판정 기준

- 문서 버전: 1.0
- 제정일: 2026-08-16
- 적용 대상: VCM1·VCM2 열교환기 IRIS 튜브 검사 이력
- 적용 목적: 부식속도 및 잔여수명 계산에 사용할 수 있는 두께 추세 데이터 선별
- 성격: 사내 데이터 품질 선별 기준(법정 합격·불합격 기준이 아님)

## 1. 제정 근거

최신 부식평가에서 이전 검사보다 최소두께가 증가한 튜브는 총 671개다.

| 구분 | VCM1 | VCM2 | 합계 |
|---|---:|---:|---:|
| 최신 두께 증가 튜브 | 275 | 396 | 671 |

- 두께 증가량 중앙값: 0.11 mm
- 90백분위: 0.23 mm
- 95백분위: 0.27 mm
- 최대값: 0.54 mm
- 검사 간격 중앙값: 1.97년
- 공칭두께 기준이 안정적인 건: 651개
- 공칭두께 기준이 변경되고 두께·감육률 방향도 모순인 건: 20개(모두 VCM2 E-105)

IRIS는 초음파 pulse-echo 방식으로 튜브 벽두께와 재료 손실을 측정한다. 초음파 두께 측정은 재질 음속 및 영점 교정, 표면 상태, 탐촉자 정렬, 커플링 조건의 영향을 받으므로 두께 증가를 실제 재료 회복으로 해석하지 않는다.

참고 자료:

- ASTM E797/E797M-21, Standard Practice for Measuring Thickness by Manual Ultrasonic Pulse-Echo Contact Method: https://store.astm.org/e0797_e0797m-21.html
- Evident IRIS Probes: https://ims.evidentscientific.com/en/probes/tube-inspection/iris
- Evident, Factors That Can Impact Ultrasonic Thickness Testing: https://ims.evidentscientific.com/en/learn/ndt-tutorials/thickness-gauge/factors
- Evident, Ultrasonic Thickness Gauge Calibration: https://ims.evidentscientific.com/en/learn/ndt-tutorials/thickness-gauge/calibration

## 2. 계산 정의

```text
두께 증가량 ΔT = 현재 최소두께 − 이전 최소두께
공칭두께 변화 ΔN = 현재 계산 공칭두께 − 이전 계산 공칭두께
감육률 변화 ΔWL = 현재 최대 감육률 − 이전 최대 감육률
부식속도 CR = (이전 최소두께 − 현재 최소두께) ÷ 경과연수
상대 두께 증가율 R = ΔT ÷ 이전 계산 공칭두께 × 100
```

- `ΔT > 0`: 최근 측정두께가 증가한 역방향 추세
- `CR > 0`: 잔여수명 계산에 사용할 수 있는 양의 부식속도
- `CR <= 0` 또는 `NULL`: 해당 평가구간을 잔여수명 계산에서 제외

## 3. 선행 유효성 Gate

다음 조건을 순서대로 확인한다. 하나라도 실패하면 증가량 등급보다 Gate 판정을 우선한다.

| Gate | 판정 기준 | 실패 시 처리 |
|---|---|---|
| G1 식별자 | 동일 공장·라인·교환기·Bundle lifecycle·Tube 번호 | `DQ-BLOCK` |
| G2 검사일 | 서로 다른 유효 검사일이며 경과일수 > 0 | `DQ-BLOCK` |
| G3 두께 완전성 | 두 검사일 모두 최소두께 존재 | `DQ-HOLD` |
| G4 공칭두께 일관성 | `abs(ΔN) <= max(0.05 mm, 이전 공칭두께의 2%)` | `DQ-BLOCK` |
| G5 공식 일관성 | 저장 감육률과 두께·감육깊이로 재계산한 감육률 차이 <= 1.0%p | `DQ-BLOCK` |
| G6 교차지표 | `ΔT > 0`일 때 `ΔWL <= 1.0%p` | 초과 시 `DQ-BLOCK` |
| G7 검사 간격 | 0.5년 이상 | 0.5년 미만은 `DQ-HOLD` |

E-105의 20개 데이터는 G4와 G6을 동시에 위반한다. 2023년 계산 공칭두께 약 2.11 mm와 2025년 약 2.77 mm를 동일 추세로 비교해서는 안 된다.

## 4. 두께 증가 등급

Gate를 통과한 `ΔT > 0` 데이터는 절대 증가량과 상대 증가율 중 더 높은 등급을 적용한다.

| 등급 | 절대 증가량 | 상대 증가율 | 처리 |
|---|---:|---:|---|
| `DQ-TOLERANCE` | 0 초과~0.05 mm 이하 | 2% 이하 | 음수 부식속도는 사용하지 않고 추세 관찰 |
| `DQ-REVIEW` | 0.05 초과~0.20 mm 이하 | 2% 초과~7.5% 이하 | 원본 C-scan·검사 위치·교정기록 검토 |
| `DQ-HIGH` | 0.20 초과~0.30 mm 이하 | 7.5% 초과~10% 이하 | 검사 책임자 확인 및 재평가 승인 필요 |
| `DQ-CRITICAL` | 0.30 mm 초과 | 10% 초과 | 원본 보고서·Tube mapping 직접 대조, 승인 전 계산 제외 |

두 조건의 등급이 다르면 더 엄격한 등급을 선택한다.

## 5. 현재 671개 적용 결과

| 판정 | VCM1 | VCM2 | 합계 |
|---|---:|---:|---:|
| `DQ-TOLERANCE` | 47 | 73 | 120 |
| `DQ-REVIEW` | 183 | 198 | 381 |
| `DQ-HIGH` | 35 | 30 | 65 |
| `DQ-CRITICAL` | 10 | 75 | 85 |
| `DQ-BLOCK` | 0 | 20 | 20 |
| 합계 | 275 | 396 | 671 |

## 6. 부식속도·잔여수명 적용 원칙

1. 음수 부식속도를 0 또는 양수로 자동 치환하지 않는다.
2. `DQ-BLOCK`, `DQ-HOLD`, `DQ-HIGH`, `DQ-CRITICAL` 평가구간은 승인 전 잔여수명 계산에서 제외한다.
3. `DQ-TOLERANCE`, `DQ-REVIEW`도 해당 음수 구간 자체는 부식속도 계산에 사용하지 않는다.
4. 과거의 유효한 양의 평가구간을 사용할 때에는 검사 책임자 승인과 적용 근거를 기록한다.
5. 검사일이 3개 이상이면 단순 최신 2점보다 이상치에 강한 다점 추세 회귀를 우선 검토한다.
6. 유효한 양의 부식속도가 없으면 잔여수명은 `산정 불가`로 유지한다.
7. 공칭두께가 변경된 경우 사양 변경인지 데이터 오류인지 확인하고, 실제 사양 변경이면 동일 lifecycle 추세를 분리한다.

## 7. 검토 우선순위

1. VCM2 E-105 20개: 공칭두께 기준 2.11 mm → 2.77 mm 변경 원인 확인
2. `DQ-CRITICAL` 85개: 원본 보고서와 Tube 번호·위치 직접 대조
3. `DQ-HIGH` 65개: 검사 책임자 검토 및 승인 상태 기록
4. 건수 집중 설비: VCM1 E-282, VCM2 E-223A, VCM2 E-206B, VCM2 E-262, VCM1 E-261
5. 동일 날짜 복수 결과 11개: 일일 최소두께·최대 감육률 대표값의 원천 결과 확인

## 8. 기준 확정 조건

0.05 mm 등의 수치는 현재 데이터 분포를 이용한 임시 선별 경계이며 장비 정확도 보증값이 아니다. 다음 Measurement System Analysis를 수행한 후 개정한다.

1. 재질·외경·공칭두께별 기준 시험편 준비
2. 동일 장비·동일 탐촉자·동일 교정으로 반복 측정
3. 검사자 간 및 검사자 내 반복성 확인
4. 표면 상태와 세척 전후 차이 확인
5. 기준 블록 전·후 교정값 및 수온·음속 설정 기록
6. 반복 측정 분포의 95% 한계를 현장 허용편차로 확정

현장 반복성 자료가 확보되면 `DQ-TOLERANCE`의 0.05 mm를 실제 검증된 측정불확도로 교체한다.

## 9. 필수 원인 코드

| 코드 | 의미 |
|---|---|
| `NOMINAL_CHANGED` | 검사 간 공칭두께 기준 변경 |
| `THICKNESS_WALLLOSS_CONFLICT` | 두께와 감육률 방향 모순 |
| `MEASUREMENT_VARIATION` | 위치·표면·커플링 등 측정 반복성 영향 |
| `CALIBRATION_MISMATCH` | 재질 음속 또는 영점 교정 불일치 |
| `TUBE_MAPPING_MISMATCH` | 동일 물리 튜브 연결 오류 |
| `MULTI_SCOPE_CONFLICT` | 동일 날짜 복수 검사범위 결과 불일치 |
| `MISSING_THICKNESS` | 비교 구간 두께값 누락 |
| `SHORT_INTERVAL` | 검사 간격 0.5년 미만 |
| `ENGINEERING_ACCEPTED` | 엔지니어 검토 후 예외 승인 |

모든 수동 승인에는 검토자, 검토일, 근거 문서, 원본 결과 ID와 적용 기간을 기록한다.
