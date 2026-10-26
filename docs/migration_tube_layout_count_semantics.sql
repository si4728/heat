-- Proposal only: do not execute without explicit database approval.
-- Separates physical Tube count from Tube Sheet layout-point count.

ALTER TABLE tube_layout_revision
    ADD COLUMN physical_tube_count INTEGER
        CHECK(physical_tube_count IS NULL OR physical_tube_count >= 0);

ALTER TABLE tube_layout_revision
    ADD COLUMN layout_point_count INTEGER
        CHECK(layout_point_count IS NULL OR layout_point_count >= 0);

ALTER TABLE tube_layout_revision
    ADD COLUMN layout_count_basis VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN'
        CHECK(layout_count_basis IN ('PHYSICAL_TUBE', 'TUBE_END', 'MIXED', 'UNKNOWN'));

ALTER TABLE tube_layout_revision
    ADD COLUMN coverage_status VARCHAR(30) NOT NULL DEFAULT 'UNKNOWN'
        CHECK(coverage_status IN ('FULL', 'PARTIAL', 'CONFLICT', 'UNKNOWN'));

ALTER TABLE tube_layout_revision
    ADD COLUMN unresolved_count INTEGER NOT NULL DEFAULT 0
        CHECK(unresolved_count >= 0);

ALTER TABLE tube_layout_revision
    ADD COLUMN count_discrepancy_note TEXT;

-- Existing revisions intentionally remain UNKNOWN until their count basis is reviewed.
-- A later approved backfill should set layout_point_count from tube_layout_point,
-- physical_tube_count from the accepted report/master basis, and coverage_status
-- only after the two counts have been interpreted for the exchanger's Tube type.
