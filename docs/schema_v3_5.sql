-- IRIS Heat Exchanger db_v3 schema 3.5.0
-- Generated 2026-08-16 from ORM-initialized validation database.
PRAGMA foreign_keys=ON;
BEGIN;

-- table: app_user
CREATE TABLE app_user (
	user_id INTEGER NOT NULL, 
	username VARCHAR(50) NOT NULL, 
	display_name VARCHAR(100) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	is_admin BOOLEAN NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	last_login_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (username)
);

-- table: data_quality_issue
CREATE TABLE data_quality_issue (
	data_quality_issue_id INTEGER NOT NULL, 
	source_document_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER, 
	iris_tube_result_id INTEGER, 
	issue_fingerprint VARCHAR(64) NOT NULL, 
	issue_code VARCHAR(100) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	field_path VARCHAR(1000), 
	source_value_json TEXT, 
	calculated_value_json TEXT, 
	description TEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	reviewer VARCHAR(100), 
	reviewed_at DATETIME, 
	resolution_note TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (data_quality_issue_id), 
	CONSTRAINT uq_quality_issue_fingerprint UNIQUE (source_document_id, issue_fingerprint), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(iris_tube_result_id) REFERENCES iris_tube_result (iris_tube_result_id)
);

-- table: equipment
CREATE TABLE equipment (
	equipment_id INTEGER NOT NULL, 
	unit_id INTEGER NOT NULL, 
	equipment_code VARCHAR(100) NOT NULL, 
	equipment_name VARCHAR(200) NOT NULL, 
	equipment_type VARCHAR(80) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	criticality_grade VARCHAR(20), 
	owner_department VARCHAR(100), 
	owner_name VARCHAR(100), 
	commissioning_date DATETIME, 
	remarks TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, "location_desc" VARCHAR(300), "manufacturer" VARCHAR(200), "model_no" VARCHAR(100), "serial_no" VARCHAR(100), "install_date" DATETIME, "is_critical" BOOLEAN NOT NULL DEFAULT 0, "equipment_number" VARCHAR(100), "equipment_tag" VARCHAR(100), manufacturing_date DATETIME, 
	PRIMARY KEY (equipment_id), 
	CONSTRAINT uq_equipment_unit_code UNIQUE (unit_id, equipment_code), 
	FOREIGN KEY(unit_id) REFERENCES process_unit (unit_id)
);

-- table: equipment_alias
CREATE TABLE equipment_alias (
	alias_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	source_system VARCHAR(100) NOT NULL, 
	source_unit VARCHAR(100) NOT NULL, 
	alias_code VARCHAR(200) NOT NULL, 
	normalized_alias_code VARCHAR(200) NOT NULL, 
	is_approved BOOLEAN NOT NULL, 
	valid_from DATETIME, 
	valid_to DATETIME, 
	PRIMARY KEY (alias_id), 
	CONSTRAINT uq_equipment_alias_source UNIQUE (source_system, source_unit, normalized_alias_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
);

-- table: heat_exchanger
CREATE TABLE heat_exchanger (
	heat_exchanger_id INTEGER NOT NULL, 
	equipment_id INTEGER NOT NULL, 
	exchanger_type VARCHAR(80), 
	service_name VARCHAR(200), 
	iris_applicability VARCHAR(30) NOT NULL, 
	inspection_lifecycle_status VARCHAR(30) NOT NULL, 
	tube_master_status VARCHAR(30) NOT NULL, 
	remarks TEXT, "exchanger_type_code" VARCHAR(20), "exchanger_type_name" VARCHAR(100), "exchanger_type_raw" VARCHAR(200), "type_mapping_status" VARCHAR(20) NOT NULL DEFAULT 'UNMAPPED', 
	PRIMARY KEY (heat_exchanger_id), 
	CONSTRAINT ck_hx_iris_applicability CHECK (iris_applicability IN ('REQUIRED','OPTIONAL','NOT_APPLICABLE','UNKNOWN')), 
	CONSTRAINT ck_hx_inspection_status CHECK (inspection_lifecycle_status IN ('NEVER_INSPECTED','PLANNED','INSPECTED','OVERDUE','NOT_APPLICABLE','UNKNOWN')), 
	CONSTRAINT ck_hx_tube_master_status CHECK (tube_master_status IN ('NOT_AVAILABLE','PARTIAL','COMPLETE')), 
	UNIQUE (equipment_id), 
	FOREIGN KEY(equipment_id) REFERENCES equipment (equipment_id)
);

-- table: heat_exchanger_capacity
CREATE TABLE heat_exchanger_capacity (
	capacity_id INTEGER NOT NULL, 
	side_spec_id INTEGER NOT NULL, 
	capacity_type VARCHAR(20) NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	capacity_value FLOAT, 
	capacity_unit VARCHAR(30), 
	raw_value TEXT, 
	PRIMARY KEY (capacity_id), 
	CONSTRAINT uq_hx_capacity_side_type_seq UNIQUE (side_spec_id, capacity_type, sequence_no), 
	CONSTRAINT ck_hx_capacity_type CHECK (capacity_type IN ('DESIGN','OPERATING')), 
	FOREIGN KEY(side_spec_id) REFERENCES heat_exchanger_side_spec (side_spec_id)
);

-- table: heat_exchanger_compliance
CREATE TABLE heat_exchanger_compliance (
	compliance_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	management_change_code VARCHAR(100), 
	equipment_class_code VARCHAR(50), 
	equipment_class_name VARCHAR(100), 
	psm_type_code VARCHAR(50), 
	psm_type_name VARCHAR(100), 
	fabrication_standard VARCHAR(200), 
	related_pid_no VARCHAR(200), 
	insulation_required BOOLEAN, 
	rbi_target BOOLEAN, 
	remarks TEXT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (compliance_id), 
	UNIQUE (heat_exchanger_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
);

-- table: heat_exchanger_management_criteria
CREATE TABLE heat_exchanger_management_criteria (
	management_criteria_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	allowable_plugging_percent FLOAT, 
	warning_wall_loss_percent FLOAT, 
	critical_wall_loss_percent FLOAT, 
	minimum_wall_thickness_mm FLOAT, 
	inspection_cycle_months INTEGER, 
	turnaround_cycle_years INTEGER, 
	last_turnaround_year INTEGER, 
	next_turnaround_year INTEGER, 
	criteria_note TEXT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (management_criteria_id), 
	CONSTRAINT ck_criteria_plugging_percent CHECK (allowable_plugging_percent IS NULL OR (allowable_plugging_percent >= 0 AND allowable_plugging_percent <= 100)), 
	CONSTRAINT ck_criteria_warning_loss CHECK (warning_wall_loss_percent IS NULL OR (warning_wall_loss_percent >= 0 AND warning_wall_loss_percent <= 100)), 
	CONSTRAINT ck_criteria_critical_loss CHECK (critical_wall_loss_percent IS NULL OR (critical_wall_loss_percent >= 0 AND critical_wall_loss_percent <= 100)), 
	UNIQUE (heat_exchanger_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
);

-- table: heat_exchanger_side_spec
CREATE TABLE heat_exchanger_side_spec (
	side_spec_id INTEGER NOT NULL, 
	spec_revision_id INTEGER NOT NULL, 
	side_code VARCHAR(10) NOT NULL, 
	fluid VARCHAR(200), 
	concentration_wt_percent FLOAT, 
	material_state VARCHAR(80), 
	design_pressure_mpa FLOAT, 
	operating_pressure_mpa FLOAT, 
	design_temperature_c FLOAT, 
	operating_temperature_c FLOAT, 
	material VARCHAR(200), 
	part_material VARCHAR(200), 
	gasket_material VARCHAR(200), 
	pwht_required BOOLEAN, 
	nde_percent FLOAT, 
	welding_efficiency FLOAT, 
	calculated_thickness_mm FLOAT, 
	corrosion_allowance_mm FLOAT, 
	used_thickness_mm FLOAT, 
	raw_json TEXT, 
	PRIMARY KEY (side_spec_id), 
	CONSTRAINT uq_hx_side_spec_revision_side UNIQUE (spec_revision_id, side_code), 
	CONSTRAINT ck_hx_side_spec_side CHECK (side_code IN ('SHELL','HEAD','TUBE')), 
	FOREIGN KEY(spec_revision_id) REFERENCES heat_exchanger_spec_revision (spec_revision_id)
);

-- table: heat_exchanger_spec_revision
CREATE TABLE heat_exchanger_spec_revision (
	spec_revision_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	source_document_id INTEGER, 
	revision_no INTEGER NOT NULL, 
	effective_from DATETIME, 
	effective_to DATETIME, 
	is_current BOOLEAN NOT NULL, 
	design_pressure FLOAT, 
	design_temperature FLOAT, 
	operation_pressure FLOAT, 
	operation_temperature FLOAT, 
	shell_material VARCHAR(100), 
	tube_material VARCHAR(100), 
	tube_count INTEGER, 
	tube_outer_diameter_mm FLOAT, 
	tube_nominal_thickness_mm FLOAT, 
	tube_length_mm FLOAT, 
	bundle_type VARCHAR(80), 
	pass_count INTEGER, 
	tube_pitch_mm FLOAT, 
	drawing_no VARCHAR(100), 
	datasheet_no VARCHAR(100), 
	raw_json TEXT, "heat_transfer_area_m2" FLOAT, "shell_fluid" VARCHAR(200), "tube_fluid" VARCHAR(200), "installation_orientation" VARCHAR(30), "raw_size_text" TEXT, "master_etc" TEXT, revision_code VARCHAR(30), 
	PRIMARY KEY (spec_revision_id), 
	CONSTRAINT uq_hx_spec_revision UNIQUE (heat_exchanger_id, revision_no), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id)
);

-- table: heat_exchanger_tube
CREATE TABLE heat_exchanger_tube (
	tube_id INTEGER NOT NULL, 
	bundle_id INTEGER NOT NULL, 
	tube_no VARCHAR(100) NOT NULL, 
	row_no INTEGER, 
	column_no INTEGER, 
	layout_zone VARCHAR(100), 
	pass_no INTEGER, 
	position_x FLOAT, 
	position_y FLOAT, 
	position_z FLOAT, 
	lifecycle_no INTEGER NOT NULL, 
	current_status VARCHAR(30) NOT NULL, 
	installed_at DATETIME, 
	retired_at DATETIME, 
	source_tube_label VARCHAR(100), position_locked BOOLEAN NOT NULL DEFAULT 0, 
	PRIMARY KEY (tube_id), 
	CONSTRAINT uq_tube_bundle_number_lifecycle UNIQUE (bundle_id, tube_no, lifecycle_no), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
);

-- table: import_batch
CREATE TABLE import_batch (
	import_batch_id INTEGER NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	status VARCHAR(40) NOT NULL, 
	mode VARCHAR(30) NOT NULL, 
	importer_version VARCHAR(30) NOT NULL, 
	source_path VARCHAR(1000) NOT NULL, 
	source_file_count INTEGER NOT NULL, 
	report_count INTEGER NOT NULL, 
	loaded_report_count INTEGER NOT NULL, 
	warning_count INTEGER NOT NULL, 
	error_count INTEGER NOT NULL, 
	skipped_count INTEGER NOT NULL, 
	markdown_report_path VARCHAR(1000), 
	json_report_path VARCHAR(1000), 
	load_summary_path VARCHAR(1000), 
	message TEXT, 
	PRIMARY KEY (import_batch_id)
);

-- table: inspection_attachment
CREATE TABLE inspection_attachment (
	inspection_attachment_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	attachment_present BOOLEAN, 
	selected_value_raw VARCHAR(50), 
	attachment_types_json TEXT, 
	source_page INTEGER, 
	inference_confidence VARCHAR(30), 
	raw_json TEXT, 
	PRIMARY KEY (inspection_attachment_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: inspection_campaign
CREATE TABLE inspection_campaign (
	campaign_id INTEGER NOT NULL, 
	unit_id INTEGER NOT NULL, 
	campaign_year INTEGER NOT NULL, 
	campaign_name VARCHAR(300) NOT NULL, 
	project_name VARCHAR(300), 
	customer VARCHAR(300), 
	start_date DATETIME, 
	end_date DATETIME, 
	PRIMARY KEY (campaign_id), 
	CONSTRAINT uq_campaign_unit_year_name UNIQUE (unit_id, campaign_year, campaign_name), 
	FOREIGN KEY(unit_id) REFERENCES process_unit (unit_id)
);

-- table: inspection_execution_snapshot
CREATE TABLE inspection_execution_snapshot (
	inspection_execution_snapshot_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	inspection_provider_id INTEGER, 
	inspection_company_raw VARCHAR(300), 
	contract_no VARCHAR(100), 
	work_order_no VARCHAR(100), 
	procedure_no VARCHAR(100), 
	procedure_revision VARCHAR(50), 
	acquisition_software_name VARCHAR(200), 
	acquisition_software_version VARCHAR(100), 
	analysis_software_name VARCHAR(200), 
	analysis_software_version VARCHAR(100), 
	equipment_calibration_date DATETIME, 
	equipment_calibration_valid_until DATETIME, 
	remarks TEXT, 
	raw_json TEXT, 
	updated_at DATETIME NOT NULL, "inspection_company_source_text" VARCHAR(500), "inspection_company_brand" VARCHAR(200), "source_page" INTEGER, 
	PRIMARY KEY (inspection_execution_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(inspection_provider_id) REFERENCES inspection_provider (inspection_provider_id)
);

-- table: inspection_personnel
CREATE TABLE inspection_personnel (
	inspection_personnel_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	role VARCHAR(50) NOT NULL, 
	person_name VARCHAR(200), 
	organization VARCHAR(300), "source_page" INTEGER, "extraction_method" VARCHAR(100), "review_required" BOOLEAN NOT NULL DEFAULT 0, "raw_json" TEXT, 
	PRIMARY KEY (inspection_personnel_id), 
	CONSTRAINT uq_inspection_personnel_role UNIQUE (iris_inspection_id, role), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: inspection_plan_v2
CREATE TABLE inspection_plan_v2 (
	inspection_plan_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	planned_date DATETIME NOT NULL, 
	inspection_method VARCHAR(50) NOT NULL, 
	scope_code VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	completed_inspection_id INTEGER, 
	notes TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, application_date DATETIME, approval_date DATETIME, 
	PRIMARY KEY (inspection_plan_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(completed_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: inspection_provider
CREATE TABLE inspection_provider (
	inspection_provider_id INTEGER NOT NULL, 
	provider_code VARCHAR(50) NOT NULL, 
	provider_name VARCHAR(300) NOT NULL, 
	business_registration_no VARCHAR(50), 
	contact_name VARCHAR(100), 
	contact_phone VARCHAR(100), 
	contact_email VARCHAR(200), 
	is_active BOOLEAN NOT NULL, 
	remarks TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, "provider_local_name" VARCHAR(300), "address" VARCHAR(500), "fax" VARCHAR(100), 
	PRIMARY KEY (inspection_provider_id), 
	UNIQUE (provider_code)
);

-- table: inspection_scope
CREATE TABLE inspection_scope (
	inspection_scope_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	bundle_id INTEGER NOT NULL, 
	scope_code VARCHAR(100) NOT NULL, 
	raw_scope_code VARCHAR(100), 
	access_end VARCHAR(100), 
	orientation VARCHAR(100), 
	description TEXT, 
	PRIMARY KEY (inspection_scope_id), 
	CONSTRAINT uq_inspection_scope UNIQUE (heat_exchanger_id, bundle_id, scope_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
);

-- table: inspection_scope_direction
CREATE TABLE inspection_scope_direction (
	scope_direction_id INTEGER NOT NULL, 
	inspection_scope_id INTEGER NOT NULL, 
	direction_code VARCHAR(30) NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	PRIMARY KEY (scope_direction_id), 
	CONSTRAINT uq_scope_direction UNIQUE (inspection_scope_id, direction_code), 
	FOREIGN KEY(inspection_scope_id) REFERENCES inspection_scope (inspection_scope_id)
);

-- table: inspection_source_page
CREATE TABLE inspection_source_page (
	inspection_source_page_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	page_role VARCHAR(50) NOT NULL, 
	page_number INTEGER NOT NULL, 
	PRIMARY KEY (inspection_source_page_id), 
	CONSTRAINT uq_inspection_source_page UNIQUE (iris_inspection_id, page_role, page_number), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: inspection_validation
CREATE TABLE inspection_validation (
	inspection_validation_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	extracted_tube_result_count INTEGER NOT NULL, 
	reported_vs_extracted_match BOOLEAN, 
	calculated_minimum_thickness_mm FLOAT, 
	calculated_maximum_wall_loss_percent FLOAT, 
	calculated_average_wall_loss_percent FLOAT, 
	wall_loss_range_min_percent FLOAT, 
	wall_loss_range_max_percent FLOAT, 
	formula_check_passed BOOLEAN, 
	validation_status VARCHAR(30) NOT NULL, 
	validator_version VARCHAR(30) NOT NULL, 
	validated_at DATETIME NOT NULL, 
	raw_json TEXT, 
	PRIMARY KEY (inspection_validation_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_indication
CREATE TABLE iris_indication (
	iris_indication_id INTEGER NOT NULL, 
	iris_tube_result_id INTEGER NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	axial_position_mm FLOAT, 
	circumferential_angle_deg FLOAT, 
	defect_type VARCHAR(100), 
	defect_length_mm FLOAT, 
	measured_thickness_mm FLOAT, 
	wall_loss_depth_mm FLOAT, 
	wall_loss_percent FLOAT, 
	cscan_min_wall_thickness_mm FLOAT, 
	judgement VARCHAR(100), 
	raw_json TEXT, "source_page" INTEGER, "visual_page_role" VARCHAR(50), "source_image_xref" INTEGER, "source_data_path" VARCHAR(1000), "acquired_at" DATETIME, "theta_x_deg" FLOAT, "delta_x_mm" FLOAT, "theta_y_deg" FLOAT, "delta_y_mm" FLOAT, "prs_value" FLOAT, "ar_hz" FLOAT, "remaining_percent" FLOAT, 
	PRIMARY KEY (iris_indication_id), 
	CONSTRAINT uq_indication_sequence UNIQUE (iris_tube_result_id, sequence_no), 
	FOREIGN KEY(iris_tube_result_id) REFERENCES iris_tube_result (iris_tube_result_id)
);

-- table: iris_inspection
CREATE TABLE iris_inspection (
	iris_inspection_id INTEGER NOT NULL, 
	campaign_id INTEGER NOT NULL, 
	source_document_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER, 
	bundle_id INTEGER, 
	inspection_scope_id INTEGER, 
	superseded_by_inspection_id INTEGER, 
	report_sequence INTEGER NOT NULL, 
	report_number VARCHAR(200), 
	report_date DATETIME, 
	report_type VARCHAR(100), 
	inspection_method VARCHAR(50) NOT NULL, 
	original_equipment_id VARCHAR(200) NOT NULL, 
	canonical_equipment_code VARCHAR(100), 
	report_status VARCHAR(40) NOT NULL, 
	extraction_status VARCHAR(40), 
	report_available BOOLEAN, 
	tube_map_available BOOLEAN, 
	tube_results_table_available BOOLEAN, 
	extraction_reason TEXT, 
	total_tube_count_reported INTEGER, 
	inspected_tube_count_reported INTEGER, 
	extracted_tube_result_count INTEGER NOT NULL, 
	reported_minimum_thickness_mm FLOAT, 
	reported_maximum_wall_loss_percent FLOAT, 
	reported_average_wall_loss_percent FLOAT, 
	representative_corrosion_type VARCHAR(100), 
	raw_report_json TEXT NOT NULL, 
	created_at DATETIME NOT NULL, "inspection_date" DATETIME, "installation_or_replacement_date" DATETIME, "commissioning_date" DATETIME, "manufacturing_date" DATETIME, "source_equipment_label" VARCHAR(200), "source_bundle_code" VARCHAR(100), "source_scope_code" VARCHAR(100), "installation_or_replacement_date_raw" VARCHAR(100), "installation_or_replacement_year" INTEGER, "installation_or_replacement_date_precision" VARCHAR(20), 
	PRIMARY KEY (iris_inspection_id), 
	CONSTRAINT uq_inspection_source_sequence UNIQUE (source_document_id, report_sequence), 
	FOREIGN KEY(campaign_id) REFERENCES inspection_campaign (campaign_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id), 
	FOREIGN KEY(inspection_scope_id) REFERENCES inspection_scope (inspection_scope_id), 
	FOREIGN KEY(superseded_by_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_inspection_spec_snapshot
CREATE TABLE iris_inspection_spec_snapshot (
	spec_snapshot_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	report_material VARCHAR(100), 
	report_outer_diameter_mm FLOAT, 
	report_nominal_thickness_mm FLOAT, 
	report_tube_length_mm FLOAT, 
	summary_material VARCHAR(100), 
	summary_outer_diameter_mm FLOAT, 
	summary_design_thickness_mm FLOAT, 
	summary_length_mm FLOAT, 
	summary_total_tubes INTEGER, 
	summary_inspected_tubes INTEGER, 
	summary_page INTEGER, 
	raw_json TEXT, 
	PRIMARY KEY (spec_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_inspection_summary_history
CREATE TABLE iris_inspection_summary_history (
	summary_history_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	previous_inspection_date DATETIME, 
	previous_maximum_wall_loss_percent FLOAT, 
	plugged_tube_count_before INTEGER, 
	plugged_tube_count_after INTEGER, 
	summary_remarks TEXT, 
	raw_json TEXT, 
	PRIMARY KEY (summary_history_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_recommendation
CREATE TABLE iris_recommendation (
	recommendation_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	recommendation_text TEXT NOT NULL, 
	PRIMARY KEY (recommendation_id), 
	CONSTRAINT uq_recommendation_sequence UNIQUE (iris_inspection_id, sequence_no), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_representative_assessment
CREATE TABLE iris_representative_assessment (
	representative_assessment_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	target_tube VARCHAR(200), 
	minimum_thickness_mm FLOAT, 
	wall_loss_percent FLOAT, 
	defect_type VARCHAR(100), 
	start_point VARCHAR(200), 
	end_point VARCHAR(200), 
	direction_labels_json TEXT, 
	raw_json TEXT, 
	PRIMARY KEY (representative_assessment_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_setup_snapshot
CREATE TABLE iris_setup_snapshot (
	setup_snapshot_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	customer VARCHAR(300), 
	project_name VARCHAR(300), 
	equipment_name VARCHAR(200), 
	equipment_number VARCHAR(200), 
	equipment_maker VARCHAR(100), 
	equipment_model VARCHAR(100), 
	equipment_serial_number VARCHAR(100), 
	search_unit_maker VARCHAR(100), 
	search_unit_model VARCHAR(100), 
	frequency_mhz FLOAT, 
	out_diameter_mm FLOAT, 
	tube_length_m FLOAT, 
	material_velocity_meter_per_sec FLOAT, 
	scan_velocity_meter_per_min FLOAT, 
	water_pressure_kg_per_cm2 FLOAT, 
	water_temperature_celsius FLOAT, 
	raw_json TEXT, search_unit_serial_number VARCHAR(100), "process_code" VARCHAR(100), "production_line" VARCHAR(100), "shell_fluid" VARCHAR(200), "tube_fluid" VARCHAR(200), "tube_type" VARCHAR(100), 
	PRIMARY KEY (setup_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_tube_map
CREATE TABLE iris_tube_map (
	tube_map_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	source_page INTEGER, 
	map_date DATETIME, 
	mode VARCHAR(30), 
	raw_equipment_id VARCHAR(200), 
	orientation VARCHAR(100), 
	vertical_spacing FLOAT, 
	horizontal_spacing FLOAT, 
	total_tubes INTEGER, 
	unmarked_or_untested_tubes INTEGER, 
	raw_json TEXT, 
	PRIMARY KEY (tube_map_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: iris_tube_map_legend
CREATE TABLE iris_tube_map_legend (
	tube_map_legend_id INTEGER NOT NULL, 
	tube_map_id INTEGER NOT NULL, 
	legend_label VARCHAR(100) NOT NULL, 
	legend_code VARCHAR(100), 
	value_type VARCHAR(30) NOT NULL, 
	lower_bound_percent FLOAT, 
	upper_bound_percent FLOAT, 
	tube_count INTEGER NOT NULL, 
	PRIMARY KEY (tube_map_legend_id), 
	CONSTRAINT uq_tube_map_legend UNIQUE (tube_map_id, legend_label), 
	FOREIGN KEY(tube_map_id) REFERENCES iris_tube_map (tube_map_id)
);

-- table: iris_tube_result
CREATE TABLE iris_tube_result (
	iris_tube_result_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER NOT NULL, 
	tube_id INTEGER NOT NULL, 
	source_tube_id VARCHAR(100) NOT NULL, 
	source_row INTEGER, 
	source_column INTEGER, 
	minimum_wall_thickness_mm FLOAT, 
	location_mm FLOAT, 
	corrosion_type VARCHAR(100), 
	wall_loss_depth_mm FLOAT, 
	wall_loss_percent FLOAT, 
	source_page INTEGER, 
	result_status VARCHAR(30) NOT NULL, 
	quality_status VARCHAR(30) NOT NULL, 
	raw_json TEXT NOT NULL, "raw_side" VARCHAR(30), "analysis_v" FLOAT, "source_location_raw" VARCHAR(200), "location_source_unit" VARCHAR(30), "remark" TEXT, "design_wall_thickness_mm" FLOAT, "defect_code" VARCHAR(100), "reported_depth_percent" FLOAT, 
	PRIMARY KEY (iris_tube_result_id), 
	CONSTRAINT uq_iris_result_inspection_tube UNIQUE (iris_inspection_id, tube_id), 
	CONSTRAINT ck_result_loss_percent CHECK (wall_loss_percent IS NULL OR (wall_loss_percent >= 0 AND wall_loss_percent <= 100)), 
	CONSTRAINT ck_result_mwt CHECK (minimum_wall_thickness_mm IS NULL OR minimum_wall_thickness_mm >= 0), 
	CONSTRAINT ck_result_loss_depth CHECK (wall_loss_depth_mm IS NULL OR wall_loss_depth_mm >= 0), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id)
);

-- table: maintenance_record
CREATE TABLE maintenance_record (
	maintenance_record_id INTEGER NOT NULL, 
	work_order_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	tube_id INTEGER, 
	action_date DATETIME NOT NULL, 
	action_type VARCHAR(50) NOT NULL, 
	old_status VARCHAR(30), 
	new_status VARCHAR(30), 
	details TEXT, 
	PRIMARY KEY (maintenance_record_id), 
	FOREIGN KEY(work_order_id) REFERENCES work_order_v2 (work_order_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id)
);

-- table: master_heat_exchanger_staging
CREATE TABLE master_heat_exchanger_staging (
	staging_id INTEGER NOT NULL, 
	import_batch_id INTEGER NOT NULL, 
	source_row_no INTEGER NOT NULL, 
	process_code VARCHAR(50), 
	equipment_code VARCHAR(100), 
	raw_json TEXT NOT NULL, 
	validation_status VARCHAR(30), 
	validation_message TEXT, 
	matched_equipment_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (staging_id), 
	CONSTRAINT uq_master_staging_batch_row UNIQUE (import_batch_id, source_row_no), 
	FOREIGN KEY(import_batch_id) REFERENCES import_batch (import_batch_id), 
	FOREIGN KEY(matched_equipment_id) REFERENCES equipment (equipment_id)
);

-- table: plant
CREATE TABLE plant (
	plant_id INTEGER NOT NULL, 
	plant_code VARCHAR(50) NOT NULL, 
	plant_name VARCHAR(200) NOT NULL, 
	location VARCHAR(300), 
	description TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (plant_id), 
	UNIQUE (plant_code)
);

-- table: process_unit
CREATE TABLE process_unit (
	unit_id INTEGER NOT NULL, 
	plant_id INTEGER NOT NULL, 
	unit_code VARCHAR(50) NOT NULL, 
	unit_name VARCHAR(200) NOT NULL, 
	description TEXT, 
	PRIMARY KEY (unit_id), 
	CONSTRAINT uq_unit_plant_code UNIQUE (plant_id, unit_code), 
	FOREIGN KEY(plant_id) REFERENCES plant (plant_id)
);

-- table: schema_field_dictionary
CREATE TABLE schema_field_dictionary (
	mapping_key VARCHAR(200) NOT NULL, 
	table_name VARCHAR(100) NOT NULL, 
	column_name VARCHAR(100) NOT NULL, 
	csv_value_column VARCHAR(300), 
	csv_unit_column VARCHAR(300), 
	discriminator_column VARCHAR(100), 
	discriminator_value VARCHAR(100), 
	field_description TEXT NOT NULL, 
	canonical_unit VARCHAR(30), 
	transform_rule TEXT, 
	remark TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (mapping_key)
);

-- table: schema_table_dictionary
CREATE TABLE schema_table_dictionary (
	table_name VARCHAR(100) NOT NULL, 
	source_file VARCHAR(500), 
	table_description TEXT NOT NULL, 
	source_description TEXT, 
	remark TEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (table_name)
);

-- table: schema_version
CREATE TABLE schema_version (
	version_id INTEGER NOT NULL, 
	version VARCHAR(30) NOT NULL, 
	applied_at DATETIME NOT NULL, 
	description TEXT, 
	PRIMARY KEY (version_id), 
	UNIQUE (version)
);

-- table: source_document
CREATE TABLE source_document (
	source_document_id INTEGER NOT NULL, 
	import_batch_id INTEGER NOT NULL, 
	source_file VARCHAR(500) NOT NULL, 
	source_path VARCHAR(1000) NOT NULL, 
	title VARCHAR(500), 
	page_count INTEGER, 
	file_size INTEGER NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	schema_name VARCHAR(100) NOT NULL, 
	schema_version VARCHAR(30) NOT NULL, 
	source_modified_at DATETIME, 
	imported_at DATETIME NOT NULL, 
	document_json TEXT NOT NULL, 
	schema_json TEXT, 
	PRIMARY KEY (source_document_id), 
	FOREIGN KEY(import_batch_id) REFERENCES import_batch (import_batch_id), 
	UNIQUE (sha256)
);

-- table: source_document_page
CREATE TABLE source_document_page (
	source_document_page_id INTEGER NOT NULL, 
	source_document_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER, 
	page_number INTEGER NOT NULL, 
	page_role VARCHAR(50), 
	classification VARCHAR(80) NOT NULL, 
	extracted_text TEXT, 
	text_character_count INTEGER NOT NULL, 
	image_count INTEGER NOT NULL, 
	images_json TEXT, 
	visual_content_semantically_structured BOOLEAN, 
	raw_json TEXT, 
	PRIMARY KEY (source_document_page_id), 
	CONSTRAINT uq_source_document_page UNIQUE (source_document_id, page_number), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
);

-- table: tube_bundle
CREATE TABLE tube_bundle (
	bundle_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	bundle_code VARCHAR(100) NOT NULL, 
	lifecycle_no INTEGER NOT NULL, 
	orientation VARCHAR(100), 
	pass_no INTEGER, 
	section_name VARCHAR(100), 
	expected_tube_count INTEGER, 
	installed_at DATETIME, 
	retired_at DATETIME, 
	status VARCHAR(30) NOT NULL, 
	PRIMARY KEY (bundle_id), 
	CONSTRAINT uq_bundle_lifecycle UNIQUE (heat_exchanger_id, bundle_code, lifecycle_no), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
);

-- table: tube_degradation_assessment
CREATE TABLE tube_degradation_assessment (
	degradation_assessment_id INTEGER NOT NULL, 
	tube_id INTEGER NOT NULL, 
	previous_result_id INTEGER, 
	current_result_id INTEGER NOT NULL, 
	assessed_at DATETIME NOT NULL, 
	elapsed_years FLOAT, 
	thickness_change_mm FLOAT, 
	corrosion_rate_mm_per_year FLOAT, 
	wall_loss_rate_percent_per_year FLOAT, 
	minimum_allowable_thickness_mm FLOAT, 
	remaining_life_years FLOAT, 
	confidence VARCHAR(30), 
	status VARCHAR(30) NOT NULL, 
	algorithm_version VARCHAR(30) NOT NULL, 
	calculation_basis TEXT, 
	PRIMARY KEY (degradation_assessment_id), 
	CONSTRAINT uq_degradation_result_algorithm UNIQUE (tube_id, current_result_id, algorithm_version), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	FOREIGN KEY(previous_result_id) REFERENCES iris_tube_result (iris_tube_result_id), 
	FOREIGN KEY(current_result_id) REFERENCES iris_tube_result (iris_tube_result_id)
);

-- table: tube_lifecycle_event
CREATE TABLE tube_lifecycle_event (
	lifecycle_event_id INTEGER NOT NULL, 
	tube_id INTEGER NOT NULL, 
	event_date DATETIME NOT NULL, 
	event_type VARCHAR(40) NOT NULL, 
	reason TEXT, 
	source_document_id INTEGER, 
	PRIMARY KEY (lifecycle_event_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id)
);

-- table: tube_position_event
CREATE TABLE tube_position_event (
	position_event_id INTEGER NOT NULL, 
	tube_id INTEGER NOT NULL, 
	event_date DATETIME NOT NULL, 
	old_x FLOAT, 
	old_y FLOAT, 
	old_z FLOAT, 
	new_x FLOAT, 
	new_y FLOAT, 
	new_z FLOAT, 
	old_locked BOOLEAN NOT NULL, 
	new_locked BOOLEAN NOT NULL, 
	reason TEXT, 
	PRIMARY KEY (position_event_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id)
);

-- table: user_screen_permission
CREATE TABLE user_screen_permission (
	user_screen_permission_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	screen_key VARCHAR(50) NOT NULL, 
	can_view BOOLEAN NOT NULL, 
	can_edit BOOLEAN NOT NULL, 
	PRIMARY KEY (user_screen_permission_id), 
	CONSTRAINT uq_user_screen_permission UNIQUE (user_id, screen_key), 
	FOREIGN KEY(user_id) REFERENCES app_user (user_id) ON DELETE CASCADE
);

-- table: wall_loss_color_setting
CREATE TABLE wall_loss_color_setting (
	color_key VARCHAR(30) NOT NULL, 
	label VARCHAR(100) NOT NULL, 
	default_color VARCHAR(7) NOT NULL, 
	current_color VARCHAR(7) NOT NULL, 
	description VARCHAR(500), 
	display_order INTEGER NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (color_key)
);

-- table: work_order_v2
CREATE TABLE work_order_v2 (
	work_order_id INTEGER NOT NULL, 
	work_order_code VARCHAR(100) NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	work_type VARCHAR(50) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	planned_start DATETIME, 
	planned_end DATETIME, 
	completed_at DATETIME, 
	description TEXT, 
	result TEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (work_order_id), 
	UNIQUE (work_order_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
);

-- index: ix_iris_inspection_hx_date
CREATE INDEX ix_iris_inspection_hx_date ON iris_inspection (heat_exchanger_id, report_date);

-- index: ix_iris_tube_result_tube
CREATE INDEX ix_iris_tube_result_tube ON iris_tube_result (tube_id, iris_inspection_id);

-- index: ix_quality_issue_status_severity
CREATE INDEX ix_quality_issue_status_severity ON data_quality_issue (status, severity);

-- index: ix_source_document_page_classification
CREATE INDEX ix_source_document_page_classification ON source_document_page (classification);

-- index: ix_tube_bundle_row_col
CREATE INDEX ix_tube_bundle_row_col ON heat_exchanger_tube (bundle_id, row_no, column_no);

-- index: uq_current_spec_revision
CREATE UNIQUE INDEX uq_current_spec_revision ON heat_exchanger_spec_revision(heat_exchanger_id) WHERE is_current=1;

-- index: uq_inspection_plan_completed_inspection
CREATE UNIQUE INDEX uq_inspection_plan_completed_inspection ON inspection_plan_v2(completed_inspection_id) WHERE completed_inspection_id IS NOT NULL;

-- index: uq_spec_revision
CREATE UNIQUE INDEX uq_spec_revision ON heat_exchanger_spec_revision(heat_exchanger_id, revision_no);

-- index: uq_spec_revision_code
CREATE UNIQUE INDEX uq_spec_revision_code ON heat_exchanger_spec_revision(heat_exchanger_id, revision_code);

-- view: v_heat_exchanger_spec_summary
CREATE VIEW v_heat_exchanger_spec_summary AS
            SELECT r.spec_revision_id,
                   r.heat_exchanger_id,
                   r.revision_no,
                   r.revision_code,
                   r.effective_from,
                   r.effective_to,
                   r.is_current,
                   'MAX_ACROSS_SIDES' AS numeric_summary_policy,
                   COUNT(s.side_spec_id) AS side_spec_count,
                   MAX(s.design_pressure_mpa) AS design_pressure_mpa,
                   MAX(s.design_temperature_c) AS design_temperature_c,
                   MAX(s.operating_pressure_mpa) AS operation_pressure_mpa,
                   MAX(s.operating_temperature_c) AS operation_temperature_c,
                   MAX(CASE WHEN s.side_code='SHELL' THEN s.material END) AS shell_material,
                   MAX(CASE WHEN s.side_code='HEAD' THEN s.material END) AS head_material,
                   MAX(CASE WHEN s.side_code='TUBE' THEN s.material END) AS tube_material,
                   MAX(CASE WHEN s.side_code='SHELL' THEN s.fluid END) AS shell_fluid,
                   MAX(CASE WHEN s.side_code='HEAD' THEN s.fluid END) AS head_fluid,
                   MAX(CASE WHEN s.side_code='TUBE' THEN s.fluid END) AS tube_fluid
              FROM heat_exchanger_spec_revision r
              LEFT JOIN heat_exchanger_side_spec s
                ON s.spec_revision_id=r.spec_revision_id
             GROUP BY r.spec_revision_id;

-- trigger: trg_spec_revision_validate_insert
CREATE TRIGGER trg_spec_revision_validate_insert
            BEFORE INSERT ON heat_exchanger_spec_revision
            BEGIN
                SELECT CASE WHEN NEW.revision_code IS NULL OR TRIM(NEW.revision_code)=''
                    THEN RAISE(ABORT, 'revision_code is required') END;
                SELECT CASE WHEN NEW.effective_from IS NULL
                    THEN RAISE(ABORT, 'effective_from is required') END;
                SELECT CASE WHEN NEW.effective_to IS NOT NULL
                                  AND julianday(NEW.effective_to) < julianday(NEW.effective_from)
                    THEN RAISE(ABORT, 'effective_to must be >= effective_from') END;
                SELECT CASE WHEN NEW.is_current=1 AND NEW.effective_to IS NOT NULL
                    THEN RAISE(ABORT, 'current revision cannot have effective_to') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM heat_exchanger_spec_revision old
                     WHERE old.heat_exchanger_id=NEW.heat_exchanger_id
                       AND julianday(COALESCE(old.effective_to, '9999-12-31'))
                           > julianday(NEW.effective_from)
                       AND julianday(COALESCE(NEW.effective_to, '9999-12-31'))
                           > julianday(old.effective_from)
                ) THEN RAISE(ABORT, 'spec revision effective periods overlap') END;
            END;

-- trigger: trg_spec_revision_validate_update
CREATE TRIGGER trg_spec_revision_validate_update
            BEFORE UPDATE ON heat_exchanger_spec_revision
            BEGIN
                SELECT CASE WHEN NEW.revision_code IS NULL OR TRIM(NEW.revision_code)=''
                    THEN RAISE(ABORT, 'revision_code is required') END;
                SELECT CASE WHEN NEW.effective_from IS NULL
                    THEN RAISE(ABORT, 'effective_from is required') END;
                SELECT CASE WHEN NEW.effective_to IS NOT NULL
                                  AND julianday(NEW.effective_to) < julianday(NEW.effective_from)
                    THEN RAISE(ABORT, 'effective_to must be >= effective_from') END;
                SELECT CASE WHEN NEW.is_current=1 AND NEW.effective_to IS NOT NULL
                    THEN RAISE(ABORT, 'current revision cannot have effective_to') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM heat_exchanger_spec_revision other
                     WHERE other.heat_exchanger_id=NEW.heat_exchanger_id
                       AND other.spec_revision_id<>OLD.spec_revision_id
                       AND julianday(COALESCE(other.effective_to, '9999-12-31'))
                           > julianday(NEW.effective_from)
                       AND julianday(COALESCE(NEW.effective_to, '9999-12-31'))
                           > julianday(other.effective_from)
                ) THEN RAISE(ABORT, 'spec revision effective periods overlap') END;
                SELECT CASE WHEN
                    NEW.heat_exchanger_id IS NOT OLD.heat_exchanger_id OR
                    NEW.source_document_id IS NOT OLD.source_document_id OR
                    NEW.revision_no IS NOT OLD.revision_no OR
                    NEW.revision_code IS NOT OLD.revision_code OR
                    NEW.effective_from IS NOT OLD.effective_from OR
                    NEW.design_pressure IS NOT OLD.design_pressure OR
                    NEW.design_temperature IS NOT OLD.design_temperature OR
                    NEW.operation_pressure IS NOT OLD.operation_pressure OR
                    NEW.operation_temperature IS NOT OLD.operation_temperature OR
                    NEW.shell_material IS NOT OLD.shell_material OR
                    NEW.tube_material IS NOT OLD.tube_material OR
                    NEW.tube_count IS NOT OLD.tube_count OR
                    NEW.tube_outer_diameter_mm IS NOT OLD.tube_outer_diameter_mm OR
                    NEW.tube_nominal_thickness_mm IS NOT OLD.tube_nominal_thickness_mm OR
                    NEW.tube_length_mm IS NOT OLD.tube_length_mm OR
                    NEW.bundle_type IS NOT OLD.bundle_type OR
                    NEW.pass_count IS NOT OLD.pass_count OR
                    NEW.tube_pitch_mm IS NOT OLD.tube_pitch_mm OR
                    NEW.heat_transfer_area_m2 IS NOT OLD.heat_transfer_area_m2 OR
                    NEW.shell_fluid IS NOT OLD.shell_fluid OR
                    NEW.tube_fluid IS NOT OLD.tube_fluid OR
                    NEW.drawing_no IS NOT OLD.drawing_no OR
                    NEW.datasheet_no IS NOT OLD.datasheet_no OR
                    NEW.installation_orientation IS NOT OLD.installation_orientation OR
                    NEW.raw_size_text IS NOT OLD.raw_size_text OR
                    NEW.master_etc IS NOT OLD.master_etc OR
                    NEW.raw_json IS NOT OLD.raw_json
                    THEN RAISE(ABORT, 'persisted spec revision is immutable; insert a new revision')
                END;
            END;

COMMIT;
