-- IRIS database schema 3.4.0
-- Preserve partial installation/replacement dates and structure tube details.

ALTER TABLE iris_inspection
    ADD COLUMN installation_or_replacement_date_raw VARCHAR(100);
ALTER TABLE iris_inspection
    ADD COLUMN installation_or_replacement_year INTEGER;
ALTER TABLE iris_inspection
    ADD COLUMN installation_or_replacement_date_precision VARCHAR(20);

ALTER TABLE iris_tube_result ADD COLUMN location_source_unit VARCHAR(30);
ALTER TABLE iris_tube_result ADD COLUMN remark TEXT;
ALTER TABLE iris_tube_result ADD COLUMN design_wall_thickness_mm FLOAT;
ALTER TABLE iris_tube_result ADD COLUMN defect_code VARCHAR(100);
ALTER TABLE iris_tube_result ADD COLUMN reported_depth_percent FLOAT;
