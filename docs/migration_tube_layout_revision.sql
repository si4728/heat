-- Tube Layout 원천 좌표와 승인 좌표를 기존 튜브 마스터와 분리해 관리한다.
-- 사용자 승인 후 백업과 트랜잭션 검증을 거쳐 적용할 것.

CREATE TABLE IF NOT EXISTS tube_layout_revision (
    layout_revision_id INTEGER PRIMARY KEY,
    bundle_id INTEGER NOT NULL REFERENCES tube_bundle(bundle_id),
    inspection_id INTEGER REFERENCES iris_inspection(iris_inspection_id),
    source_path TEXT NOT NULL,
    source_checksum VARCHAR(64),
    source_section_id INTEGER NOT NULL,
    source_section_name VARCHAR(100),
    source_coordinate_unit VARCHAR(30) NOT NULL DEFAULT 'SOURCE_NATIVE',
    source_origin_code INTEGER,
    source_row_spacing FLOAT,
    source_column_spacing FLOAT,
    source_scale_metric BOOLEAN,
    normalized_view_direction VARCHAR(30),
    rotation_degrees FLOAT,
    flip_x BOOLEAN,
    flip_y BOOLEAN,
    scale_x FLOAT,
    scale_y FLOAT,
    offset_x FLOAT,
    offset_y FLOAT,
    revision_status VARCHAR(30) NOT NULL DEFAULT 'DRAFT',
    review_note TEXT,
    reviewed_by VARCHAR(100),
    reviewed_at DATETIME,
    approved_by VARCHAR(100),
    approved_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bundle_id, source_path, source_section_id),
    CHECK(revision_status IN ('DRAFT', 'REVIEWED', 'APPROVED', 'REJECTED')),
    CHECK(source_coordinate_unit IN ('SOURCE_NATIVE', 'MM', 'INCH', 'GRID'))
);

CREATE INDEX IF NOT EXISTS ix_tube_layout_revision_bundle_status
    ON tube_layout_revision(bundle_id, revision_status);

CREATE TABLE IF NOT EXISTS tube_layout_point (
    layout_point_id INTEGER PRIMARY KEY,
    layout_revision_id INTEGER NOT NULL
        REFERENCES tube_layout_revision(layout_revision_id) ON DELETE CASCADE,
    tube_id INTEGER REFERENCES heat_exchanger_tube(tube_id),
    source_tube_id VARCHAR(100),
    source_row INTEGER NOT NULL,
    source_column INTEGER NOT NULL,
    source_x FLOAT NOT NULL,
    source_y FLOAT NOT NULL,
    source_original_x FLOAT,
    source_original_y FLOAT,
    canonical_x FLOAT,
    canonical_y FLOAT,
    mapping_status VARCHAR(30) NOT NULL,
    verification_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    conflict_code VARCHAR(100),
    review_note TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(layout_revision_id, source_row, source_column),
    CHECK(mapping_status IN ('EXISTING_TUBE_MATCH', 'NEW_TUBE_CANDIDATE', 'UNMAPPED', 'CONFLICT')),
    CHECK(verification_status IN ('PENDING', 'VERIFIED', 'REJECTED'))
);

CREATE INDEX IF NOT EXISTS ix_tube_layout_point_tube
    ON tube_layout_point(tube_id);

CREATE INDEX IF NOT EXISTS ix_tube_layout_point_revision_status
    ON tube_layout_point(layout_revision_id, verification_status);

-- 승인된 Layout은 Bundle별로 하나만 활성화한다.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tube_layout_approved_bundle
    ON tube_layout_revision(bundle_id)
    WHERE revision_status = 'APPROVED';
