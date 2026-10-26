-- 지능형열교환시스템 3.11.0
-- 기존 검사결과를 검사계획 대상 Tube 및 전체 상태 이력과 연결한다.
-- 실제 실행은 iris_v2_database.py의 idempotent migration을 사용한다.

ALTER TABLE inspection_plan_tube_target
    ADD COLUMN source_iris_tube_result_id INTEGER
    REFERENCES iris_tube_result(iris_tube_result_id);

CREATE INDEX ix_inspection_plan_tube_target_source_result
    ON inspection_plan_tube_target(source_iris_tube_result_id);

-- 백필 원칙
-- 1. completed_inspection_id로 연결된 검사결과만 처리한다.
-- 2. 실제 iris_tube_result가 있는 Tube만 과거 계획 대상으로 등록한다.
-- 3. 결과가 없는 Tube는 검사제외로 추정하지 않는다.
-- 4. 대상 상태는 INSPECTED, inspected_at은 검사일/보고일/계획일 순으로 기록한다.
-- 5. 신청→승인→검사진행→완료 이벤트를 순서대로 생성한다.
-- 6. 실제 사용자를 추정하지 않고 비활성 이관 전용 신청자·관리자 계정을 사용한다.
