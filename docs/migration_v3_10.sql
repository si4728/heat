-- 지능형열교환시스템 3.10.0
-- 교환기 단위 검사일정 + 선택한 IN_SERVICE Tube 대상 + 신청/승인 감사정보

ALTER TABLE inspection_plan_v2 ADD COLUMN requested_by_user_id INTEGER REFERENCES app_user(user_id);
ALTER TABLE inspection_plan_v2 ADD COLUMN application_due_date DATETIME;
ALTER TABLE inspection_plan_v2 ADD COLUMN approved_by_user_id INTEGER REFERENCES app_user(user_id);
ALTER TABLE inspection_plan_v2 ADD COLUMN target_locked_at DATETIME;
ALTER TABLE inspection_plan_v2 ADD COLUMN inspection_started_at DATETIME;
ALTER TABLE inspection_plan_v2 ADD COLUMN inspection_completed_at DATETIME;
ALTER TABLE inspection_plan_v2 ADD COLUMN decision_note TEXT;
ALTER TABLE inspection_plan_v2 ADD COLUMN cancellation_reason TEXT;

CREATE TABLE inspection_plan_tube_target (
    inspection_plan_tube_target_id INTEGER NOT NULL PRIMARY KEY,
    inspection_plan_id INTEGER NOT NULL REFERENCES inspection_plan_v2(inspection_plan_id) ON DELETE CASCADE,
    tube_id INTEGER NOT NULL REFERENCES heat_exchanger_tube(tube_id),
    bundle_id_at_selection INTEGER NOT NULL REFERENCES tube_bundle(bundle_id),
    tube_no_at_selection VARCHAR(100) NOT NULL,
    row_no_at_selection INTEGER,
    column_no_at_selection INTEGER,
    tube_status_at_selection VARCHAR(30) NOT NULL,
    selected_by_user_id INTEGER REFERENCES app_user(user_id),
    selected_at DATETIME NOT NULL,
    target_status VARCHAR(30) NOT NULL,
    excluded_reason TEXT,
    inspected_at DATETIME,
    CONSTRAINT uq_inspection_plan_tube UNIQUE (inspection_plan_id, tube_id),
    CONSTRAINT ck_inspection_plan_tube_status CHECK (target_status IN ('TARGETED','INSPECTED','EXCLUDED'))
);

CREATE TABLE inspection_plan_event (
    inspection_plan_event_id INTEGER NOT NULL PRIMARY KEY,
    inspection_plan_id INTEGER NOT NULL REFERENCES inspection_plan_v2(inspection_plan_id) ON DELETE CASCADE,
    previous_status VARCHAR(30),
    new_status VARCHAR(30) NOT NULL,
    actor_user_id INTEGER REFERENCES app_user(user_id),
    actor_role VARCHAR(30) NOT NULL,
    reason TEXT,
    target_tube_count INTEGER NOT NULL,
    created_at DATETIME NOT NULL
);

CREATE INDEX ix_inspection_plan_tube_target_plan_status
    ON inspection_plan_tube_target(inspection_plan_id, target_status);
CREATE INDEX ix_inspection_plan_event_plan_created
    ON inspection_plan_event(inspection_plan_id, created_at);
