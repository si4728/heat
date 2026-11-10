# 잔여수명 산식 재적용

적용일: 2026-10-28

## 기본 계산

1. 잔여기간 = max(0, 공칭두께 × 0.4 − 최근 검사 감육량) ÷ 적용 부식속도
2. Tube별 예상일 = 현재 계산 기준일 + 잔여기간. 감육률 40% 이상은 기준일 도달로 취급. 이미 PLUGGED인 Tube는 실제 상태와 날짜를 유지
3. 일반 허용 한도 20%, Critical 10% 자동 적용. 허용 개수는 총수량 × 한도율의 소수점 버림
4. 누적 예상 수량이 허용 개수를 처음 초과하는 연도를 수명 도달 연도로 사용
5. 잔여수명 = max(0, 도달 예상 연도 − 현재 기준연도)

최근 검사 감육량을 기준일의 현재 감육량으로 간주하는 사용자 요청 산식이다. 검사 이후 미측정 기간의 추가 감육은 자동 보정하지 않는다. 검사일·실측두께·감육값 자체는 변경하지 않는다. 기준일이 바뀌면 같은 최근 검사값의 예상일도 이동할 수 있으므로, 실제 운전 허용기간으로 해석하지 않는다.

부식속도는 기존 설치 후 최근 검사 평균 산정 방식을 유지한다. 설치 이전 이력 제외와 연도만 알려진 설치일의 추정 처리도 유지한다. 날짜 범위 초과는 산정 불가로 처리한다.

## 예외

별도 What-if Simulation에서만 사용자 한도·판정 감육률·속도 배율을 변경할 수 있다. 기본 산식은 변경하지 않는다. API 510 검사주기 산식·검사일 기산 방식은 별개이며 수정하지 않았다.

## 수정 위치

- `life_prediction.py`: 기준일 기산, 일반/Critical 기본 한도, 음수 잔여수명 방지
- `services.py`: 대시보드·상세·정밀분석·예측 조회 공통 계산 연결, 저장 시 한도 자동 결정
- `templates/precision_analysis.html`: ①~④ 산식과 두 도움말
- `templates/exchanger_detail.html`, `remaining_life_simulation.html`: 공통 산식·가정·Simulation 안내
- `templates/dashboard.html`: 집계 기준 안내
- `templates/exchanger_form.html`, `static/plugging-limit-range.js`: 중요도에 따른 20%/10% 자동 표시
- `templates/base.html`: 변경된 JavaScript 캐시 버전
- `test_latest_installation_prediction.py`, `test_calculation_boundaries.py`, `tests/test_critical_limit.cjs`: 새 산식·한도 회귀검증

## 데이터 처리

기존 검사·설비 중요도 값은 일괄 수정하지 않는다. 기본 예측은 저장돼 있던 임의 허용비율 대신 중요도에 따른 20%/10%를 사용한다. 설비를 정상 저장할 때 관리기준 허용비율도 자동 한도로 저장한다.

## 적용 방법

웹 서버를 재시작하고 화면을 새로고침한다. DB 스키마 마이그레이션은 필요하지 않다.


## 최종 재점검

최신 수정 사항과 검증 결과는 `SYSTEM_RECHECK_20261028.md`를 따른다. 최초 기록 이후 Chrome 화면 및 서버·브라우저 날짜 일치 검증을 추가 완료했다.
