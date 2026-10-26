-- IRIS database schema 3.5.0
-- Structure report process context and inspection-company provenance.

ALTER TABLE iris_setup_snapshot ADD COLUMN process_code VARCHAR(100);
ALTER TABLE iris_setup_snapshot ADD COLUMN production_line VARCHAR(100);
ALTER TABLE iris_setup_snapshot ADD COLUMN shell_fluid VARCHAR(200);
ALTER TABLE iris_setup_snapshot ADD COLUMN tube_fluid VARCHAR(200);
ALTER TABLE iris_setup_snapshot ADD COLUMN tube_type VARCHAR(100);

ALTER TABLE inspection_execution_snapshot
    ADD COLUMN inspection_company_source_text VARCHAR(500);
ALTER TABLE inspection_execution_snapshot
    ADD COLUMN inspection_company_brand VARCHAR(200);
ALTER TABLE inspection_execution_snapshot ADD COLUMN source_page INTEGER;
