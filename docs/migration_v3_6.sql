-- IRIS database schema 3.6.0
-- Track partial JSON loads and independently recoverable post-processing.

ALTER TABLE source_document ADD COLUMN load_status VARCHAR(30) NOT NULL DEFAULT 'RECEIVED';
ALTER TABLE source_document ADD COLUMN expected_report_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN loaded_report_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN missing_report_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE source_document ADD COLUMN postprocess_status VARCHAR(30) NOT NULL DEFAULT 'PENDING';
ALTER TABLE source_document ADD COLUMN postprocess_message TEXT;

-- The application migration additionally derives loaded/missing counts from
-- iris_inspection and open MASTER_EQUIPMENT_NOT_FOUND issues.
