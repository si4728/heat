-- DRAFT ONLY: needs live MariaDB validation and revision-overlap rules.


CREATE TABLE schema_version (
	version_id INTEGER NOT NULL AUTO_INCREMENT, 
	version VARCHAR(30) NOT NULL, 
	applied_at DATETIME NOT NULL, 
	description LONGTEXT, 
	PRIMARY KEY (version_id), 
	UNIQUE (version)
)

;


CREATE TABLE wall_loss_color_setting (
	color_key VARCHAR(30) NOT NULL, 
	label VARCHAR(100) NOT NULL, 
	default_color VARCHAR(7) NOT NULL, 
	current_color VARCHAR(7) NOT NULL, 
	description VARCHAR(500), 
	display_order INTEGER NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (color_key)
)

;


CREATE TABLE system_theme_preset (
	preset_key VARCHAR(30) NOT NULL, 
	preset_name VARCHAR(100) NOT NULL, 
	default_background_color VARCHAR(7) NOT NULL, 
	default_label_color VARCHAR(7) NOT NULL, 
	background_color VARCHAR(7) NOT NULL, 
	label_color VARCHAR(7) NOT NULL, 
	is_active BOOL NOT NULL, 
	is_system BOOL NOT NULL, 
	display_order INTEGER NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (preset_key)
)

;


CREATE TABLE app_user (
	user_id INTEGER NOT NULL AUTO_INCREMENT, 
	username VARCHAR(50) NOT NULL, 
	display_name VARCHAR(100) NOT NULL, 
	password_hash VARCHAR(300) NOT NULL, 
	is_admin BOOL NOT NULL, 
	is_active BOOL NOT NULL, 
	pdf_open_mode VARCHAR(20) NOT NULL, 
	last_login_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	UNIQUE (username)
)

;


CREATE TABLE user_screen_permission (
	user_screen_permission_id INTEGER NOT NULL AUTO_INCREMENT, 
	user_id INTEGER NOT NULL, 
	screen_key VARCHAR(50) NOT NULL, 
	can_view BOOL NOT NULL, 
	can_edit BOOL NOT NULL, 
	PRIMARY KEY (user_screen_permission_id), 
	FOREIGN KEY(user_id) REFERENCES app_user (user_id) ON DELETE CASCADE, 
	CONSTRAINT uq_user_screen_permission UNIQUE (user_id, screen_key)
)

;


CREATE TABLE import_batch (
	import_batch_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	message LONGTEXT, 
	PRIMARY KEY (import_batch_id)
)

;


CREATE TABLE source_document (
	source_document_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	document_json LONGTEXT NOT NULL, 
	schema_json LONGTEXT, 
	load_status VARCHAR(30) NOT NULL, 
	expected_report_count INTEGER NOT NULL, 
	loaded_report_count INTEGER NOT NULL, 
	missing_report_count INTEGER NOT NULL, 
	postprocess_status VARCHAR(30) NOT NULL, 
	postprocess_message LONGTEXT, 
	PRIMARY KEY (source_document_id), 
	UNIQUE (sha256), 
	FOREIGN KEY(import_batch_id) REFERENCES import_batch (import_batch_id)
)

;


CREATE TABLE source_document_page (
	source_document_page_id INTEGER NOT NULL AUTO_INCREMENT, 
	source_document_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER, 
	page_number INTEGER NOT NULL, 
	page_role VARCHAR(50), 
	classification VARCHAR(80) NOT NULL, 
	extracted_text LONGTEXT, 
	text_character_count INTEGER NOT NULL, 
	image_count INTEGER NOT NULL, 
	images_json LONGTEXT, 
	visual_content_semantically_structured BOOL, 
	raw_json LONGTEXT, 
	PRIMARY KEY (source_document_page_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	CONSTRAINT uq_source_document_page UNIQUE (source_document_id, page_number), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;

CREATE INDEX ix_source_document_page_classification ON source_document_page (classification);


CREATE TABLE plant (
	plant_id INTEGER NOT NULL AUTO_INCREMENT, 
	plant_code VARCHAR(50) NOT NULL, 
	plant_name VARCHAR(200) NOT NULL, 
	location VARCHAR(300), 
	description LONGTEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (plant_id), 
	UNIQUE (plant_code)
)

;


CREATE TABLE organization_code (
	organization_code_id INTEGER NOT NULL AUTO_INCREMENT, 
	parent_id INTEGER, 
	kind VARCHAR(20) NOT NULL, 
	code VARCHAR(100) NOT NULL, 
	label VARCHAR(200) NOT NULL, 
	description LONGTEXT, 
	plant_code_unique VARCHAR(100) GENERATED ALWAYS AS (CASE WHEN kind = 'PLANT' THEN code ELSE NULL END) STORED, 
	PRIMARY KEY (organization_code_id), 
	FOREIGN KEY(parent_id) REFERENCES organization_code (organization_code_id), 
	CONSTRAINT ck_organization_kind CHECK (kind IN ('PLANT','TEAM','PROCESS')), 
	CONSTRAINT uq_organization_parent_code UNIQUE (parent_id, code), 
	CONSTRAINT ck_organization_parent CHECK ((kind = 'PLANT' AND parent_id IS NULL) OR (kind != 'PLANT' AND parent_id IS NOT NULL))
)

;

CREATE UNIQUE INDEX uq_organization_plant_code ON organization_code (plant_code_unique);


CREATE TABLE process_unit (
	unit_id INTEGER NOT NULL AUTO_INCREMENT, 
	plant_id INTEGER NOT NULL, 
	unit_code VARCHAR(50) NOT NULL, 
	unit_name VARCHAR(200) NOT NULL, 
	description LONGTEXT, 
	PRIMARY KEY (unit_id), 
	CONSTRAINT uq_unit_plant_code UNIQUE (plant_id, unit_code), 
	FOREIGN KEY(plant_id) REFERENCES plant (plant_id)
)

;


CREATE TABLE equipment (
	equipment_id INTEGER NOT NULL AUTO_INCREMENT, 
	unit_id INTEGER NOT NULL, 
	equipment_code VARCHAR(100) NOT NULL, 
	equipment_name VARCHAR(200) NOT NULL, 
	production_team_code VARCHAR(50) COMMENT 'Production team from installation master column D', 
	process_code VARCHAR(100) COMMENT 'Process from installation master column E', 
	equipment_number VARCHAR(100) COMMENT 'CSV column: 설비번호', 
	equipment_tag VARCHAR(100) COMMENT 'CSV column: 설비Tag', 
	equipment_type VARCHAR(80) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	criticality_grade VARCHAR(20), 
	owner_department VARCHAR(100), 
	owner_name VARCHAR(100), 
	location_desc VARCHAR(300), 
	manufacturer VARCHAR(200), 
	model_no VARCHAR(100), 
	serial_no VARCHAR(100), 
	manufacturing_date DATETIME COMMENT 'Equipment manufacturing date', 
	install_date DATETIME, 
	is_critical BOOL NOT NULL, 
	commissioning_date DATETIME, 
	remarks LONGTEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (equipment_id), 
	FOREIGN KEY(unit_id) REFERENCES process_unit (unit_id), 
	CONSTRAINT uq_equipment_unit_code UNIQUE (unit_id, equipment_code)
)

;


CREATE TABLE heat_exchanger (
	heat_exchanger_id INTEGER NOT NULL AUTO_INCREMENT, 
	equipment_id INTEGER NOT NULL, 
	exchanger_type VARCHAR(80), 
	exchanger_type_code VARCHAR(20), 
	exchanger_type_name VARCHAR(100), 
	exchanger_type_raw VARCHAR(200), 
	type_mapping_status VARCHAR(20) NOT NULL, 
	service_name VARCHAR(200), 
	iris_applicability VARCHAR(30) NOT NULL, 
	inspection_lifecycle_status VARCHAR(30) NOT NULL, 
	tube_master_status VARCHAR(30) NOT NULL, 
	remarks LONGTEXT, 
	PRIMARY KEY (heat_exchanger_id), 
	UNIQUE (equipment_id), 
	CONSTRAINT ck_hx_iris_applicability CHECK (iris_applicability IN ('REQUIRED','OPTIONAL','NOT_APPLICABLE','UNKNOWN')), 
	FOREIGN KEY(equipment_id) REFERENCES equipment (equipment_id), 
	CONSTRAINT ck_hx_tube_master_status CHECK (tube_master_status IN ('NOT_AVAILABLE','PARTIAL','COMPLETE')), 
	CONSTRAINT ck_hx_inspection_status CHECK (inspection_lifecycle_status IN ('NEVER_INSPECTED','PLANNED','INSPECTED','OVERDUE','NOT_APPLICABLE','UNKNOWN'))
)

;


CREATE TABLE equipment_alias (
	alias_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	source_system VARCHAR(100) NOT NULL, 
	source_unit VARCHAR(100) NOT NULL, 
	alias_code VARCHAR(200) NOT NULL, 
	normalized_alias_code VARCHAR(200) NOT NULL, 
	is_approved BOOL NOT NULL, 
	valid_from DATETIME, 
	valid_to DATETIME, 
	PRIMARY KEY (alias_id), 
	CONSTRAINT uq_equipment_alias_source UNIQUE (source_system, source_unit, normalized_alias_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;


CREATE TABLE heat_exchanger_spec_revision (
	spec_revision_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	exchanger_code VARCHAR(100) COMMENT 'Stable exchanger/Item No. retained independently from equipment.equipment_code', 
	source_document_id INTEGER, 
	revision_no INTEGER NOT NULL, 
	revision_code VARCHAR(30) NOT NULL, 
	effective_from DATETIME NOT NULL, 
	effective_to DATETIME, 
	is_current BOOL NOT NULL, 
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
	heat_transfer_area_m2 FLOAT, 
	shell_fluid VARCHAR(200), 
	tube_fluid VARCHAR(200), 
	drawing_no VARCHAR(100), 
	datasheet_no VARCHAR(100), 
	installation_orientation VARCHAR(30) COMMENT 'CSV columns: 설치방향_val, 설치방향(H, V)_unit', 
	raw_size_text LONGTEXT COMMENT 'CSV columns: *SIZE(mm, DxHxW)_val, *SIZE(mm, DxHxW)_unit', 
	master_etc LONGTEXT COMMENT 'CSV columns: Etc_val, *기타_unit', 
	raw_json LONGTEXT, 
	current_exchanger_unique INTEGER GENERATED ALWAYS AS (CASE WHEN is_current = 1 THEN heat_exchanger_id ELSE NULL END) STORED, 
	PRIMARY KEY (spec_revision_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	CONSTRAINT uq_spec_revision_code UNIQUE (heat_exchanger_id, revision_code), 
	CONSTRAINT uq_spec_revision UNIQUE (heat_exchanger_id, revision_no), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	CONSTRAINT ck_spec_revision_effective_range CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from)
)

;

CREATE UNIQUE INDEX uq_current_spec_revision ON heat_exchanger_spec_revision (current_exchanger_unique);


CREATE TABLE heat_exchanger_side_spec (
	side_spec_id INTEGER NOT NULL COMMENT 'System key; no direct CSV column' AUTO_INCREMENT, 
	spec_revision_id INTEGER NOT NULL COMMENT 'System relationship to the imported CSV specification revision', 
	side_code VARCHAR(10) NOT NULL COMMENT 'Derived from CSV column prefix: Shell, Head, or Tube', 
	fluid VARCHAR(200) COMMENT 'CSV columns: Shell 유체_val, 내용물 - Head_val, Tube 유체_val', 
	concentration_wt_percent FLOAT COMMENT 'CSV columns: *농도(wt%%) - Shell_val, *농도(wt%%) - Tube_val', 
	material_state VARCHAR(80) COMMENT 'CSV columns: Shell 물질상태_val, Tube 물질상태_val', 
	design_pressure_mpa FLOAT COMMENT 'CSV columns: Shell/Head/Tube 설계압력 value; canonical unit MPa', 
	operating_pressure_mpa FLOAT COMMENT 'CSV columns: Shell/Head/Tube 운전압력_val; canonical unit MPa', 
	design_temperature_c FLOAT COMMENT 'CSV columns: Shell/Head/Tube 설계온도_val; canonical unit ℃', 
	operating_temperature_c FLOAT COMMENT 'CSV columns: Shell/Head/Tube 운전온도_val; canonical unit ℃', 
	material VARCHAR(200) COMMENT 'CSV columns: Shell 재질_val, Head 재질_val, Tube 재질_val', 
	part_material VARCHAR(200) COMMENT 'CSV columns: Shell Part 재질_val, Tube Part 재질_val', 
	gasket_material VARCHAR(200) COMMENT 'CSV columns: Shell 개스켓 재질_val, Tube 게스켓 재질_val', 
	pwht_required BOOL COMMENT 'CSV columns: Shell 후열처리여부_val, Tube 후열처리부_val', 
	nde_percent FLOAT COMMENT 'CSV columns: SHELL/HEAD/Tube 비파괴검사율_val; canonical unit %%', 
	welding_efficiency FLOAT COMMENT 'CSV columns: Shell 용접효율_val, Tube 용접효율_val', 
	calculated_thickness_mm FLOAT COMMENT 'CSV columns: SHELL/HEAD/Tube 계산두께_val; canonical unit mm', 
	corrosion_allowance_mm FLOAT COMMENT 'CSV columns: SHELL/HEAD/Tube 부식여유_val; canonical unit mm', 
	used_thickness_mm FLOAT COMMENT 'CSV columns: SHELL/HEAD/Tube 사용두께_val; canonical unit mm', 
	raw_json LONGTEXT COMMENT 'Raw CSV values and units for the side', 
	PRIMARY KEY (side_spec_id), 
	CONSTRAINT uq_hx_side_spec_revision_side UNIQUE (spec_revision_id, side_code), 
	CONSTRAINT ck_hx_side_spec_side CHECK (side_code IN ('SHELL','HEAD','TUBE')), 
	FOREIGN KEY(spec_revision_id) REFERENCES heat_exchanger_spec_revision (spec_revision_id)
)

;


CREATE TABLE heat_exchanger_capacity (
	capacity_id INTEGER NOT NULL COMMENT 'System key; no direct CSV column' AUTO_INCREMENT, 
	side_spec_id INTEGER NOT NULL COMMENT 'System relationship to Shell/Head/Tube CSV side', 
	capacity_type VARCHAR(20) NOT NULL COMMENT 'Derived from CSV column name: 설계용량=DESIGN, 운전용량=OPERATING', 
	sequence_no INTEGER NOT NULL COMMENT 'Order of multiple CSV value/unit pairs', 
	capacity_value FLOAT COMMENT 'CSV columns: Shell/Tube 설계용량_val or 운전용량_val', 
	capacity_unit VARCHAR(30) COMMENT 'CSV columns: Shell/Tube 설계용량_unit or 운전용량_unit', 
	raw_value LONGTEXT COMMENT 'Original CSV capacity text before parsing', 
	PRIMARY KEY (capacity_id), 
	FOREIGN KEY(side_spec_id) REFERENCES heat_exchanger_side_spec (side_spec_id), 
	CONSTRAINT uq_hx_capacity_side_type_seq UNIQUE (side_spec_id, capacity_type, sequence_no), 
	CONSTRAINT ck_hx_capacity_type CHECK (capacity_type IN ('DESIGN','OPERATING'))
)

;


CREATE TABLE heat_exchanger_compliance (
	compliance_id INTEGER NOT NULL COMMENT 'System key; no direct CSV column' AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL COMMENT 'System relationship resolved from CSV 공정 + 설비코드', 
	management_change_code VARCHAR(100) COMMENT 'CSV column: 변경관리코드', 
	equipment_class_code VARCHAR(50) COMMENT 'CSV column: 설비클래스(CODE)', 
	equipment_class_name VARCHAR(100) COMMENT 'CSV column: 설비클래스', 
	psm_type_code VARCHAR(50) COMMENT 'CSV column: PSM유형(CODE)', 
	psm_type_name VARCHAR(100) COMMENT 'CSV column: PSM유형', 
	fabrication_standard VARCHAR(200) COMMENT 'CSV columns: 제작규격_val, *제작규격_unit', 
	related_pid_no VARCHAR(200) COMMENT 'CSV columns: Related P_ID No._val, *연관 P&ID No._unit', 
	insulation_required BOOL COMMENT 'CSV columns: 보온여부_val, 보온여부_unit', 
	rbi_target BOOL COMMENT 'CSV columns: RBI 대상_val, RBI 대상_unit', 
	remarks LONGTEXT COMMENT 'CSV columns: Etc_val, *기타_unit', 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (compliance_id), 
	UNIQUE (heat_exchanger_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;


CREATE TABLE master_heat_exchanger_staging (
	staging_id INTEGER NOT NULL COMMENT 'System key; no direct CSV column' AUTO_INCREMENT, 
	import_batch_id INTEGER NOT NULL COMMENT 'Import batch for Master_HeatExchanger.csv', 
	source_row_no INTEGER NOT NULL COMMENT 'CSV physical row number', 
	process_code VARCHAR(50) COMMENT 'CSV column: 공정', 
	equipment_code VARCHAR(100) COMMENT 'CSV column: 설비코드', 
	raw_json LONGTEXT NOT NULL COMMENT 'All 124 CSV columns preserved as JSON', 
	validation_status VARCHAR(30) COMMENT 'System validation result for the CSV row', 
	validation_message LONGTEXT COMMENT 'System validation details for the CSV row', 
	matched_equipment_id INTEGER COMMENT 'Resolved using CSV columns 공정 + 설비코드', 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (staging_id), 
	FOREIGN KEY(matched_equipment_id) REFERENCES equipment (equipment_id), 
	FOREIGN KEY(import_batch_id) REFERENCES import_batch (import_batch_id), 
	CONSTRAINT uq_master_staging_batch_row UNIQUE (import_batch_id, source_row_no)
)

;


CREATE TABLE schema_table_dictionary (
	table_name VARCHAR(100) NOT NULL COMMENT 'DB table name', 
	source_file VARCHAR(500) COMMENT 'CSV source file name', 
	table_description LONGTEXT NOT NULL COMMENT 'Business purpose of the table', 
	source_description LONGTEXT COMMENT 'CSV source scope represented by the table', 
	remark LONGTEXT COMMENT 'Additional schema remark', 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (table_name)
)

;


CREATE TABLE schema_field_dictionary (
	mapping_key VARCHAR(200) NOT NULL COMMENT 'Stable mapping identifier', 
	table_name VARCHAR(100) NOT NULL COMMENT 'Target DB table', 
	column_name VARCHAR(100) NOT NULL COMMENT 'Target DB column', 
	csv_value_column VARCHAR(300) COMMENT 'Exact CSV value column name', 
	csv_unit_column VARCHAR(300) COMMENT 'Exact CSV unit column name', 
	discriminator_column VARCHAR(100) COMMENT 'Target discriminator such as side_code', 
	discriminator_value VARCHAR(100) COMMENT 'Discriminator value such as SHELL/HEAD/TUBE', 
	field_description LONGTEXT NOT NULL COMMENT 'Business meaning of the DB field', 
	canonical_unit VARCHAR(30) COMMENT 'Canonical DB unit', 
	transform_rule LONGTEXT COMMENT 'CSV-to-DB conversion and normalization rule', 
	remark LONGTEXT COMMENT 'CSV column provenance remark', 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (mapping_key)
)

;


CREATE TABLE heat_exchanger_management_criteria (
	management_criteria_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	allowable_plugging_percent FLOAT, 
	warning_wall_loss_percent FLOAT, 
	critical_wall_loss_percent FLOAT, 
	minimum_wall_thickness_mm FLOAT, 
	inspection_cycle_months INTEGER, 
	turnaround_cycle_years INTEGER, 
	last_turnaround_year INTEGER, 
	next_turnaround_year INTEGER, 
	criteria_note LONGTEXT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (management_criteria_id), 
	UNIQUE (heat_exchanger_id), 
	CONSTRAINT ck_criteria_warning_loss CHECK (warning_wall_loss_percent IS NULL OR (warning_wall_loss_percent >= 0 AND warning_wall_loss_percent <= 100)), 
	CONSTRAINT ck_criteria_critical_loss CHECK (critical_wall_loss_percent IS NULL OR (critical_wall_loss_percent >= 0 AND critical_wall_loss_percent <= 100)), 
	CONSTRAINT ck_criteria_plugging_percent CHECK (allowable_plugging_percent IS NULL OR (allowable_plugging_percent >= 0 AND allowable_plugging_percent <= 100)), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;


CREATE TABLE tube_bundle (
	bundle_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	bundle_code VARCHAR(100) NOT NULL, 
	lifecycle_no INTEGER NOT NULL, 
	orientation VARCHAR(100), 
	pass_no INTEGER, 
	section_name VARCHAR(100), 
	expected_tube_count INTEGER, 
	retired_at DATETIME, 
	status VARCHAR(30) NOT NULL, 
	PRIMARY KEY (bundle_id), 
	CONSTRAINT uq_bundle_lifecycle UNIQUE (heat_exchanger_id, bundle_code, lifecycle_no), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;


CREATE TABLE inspection_scope (
	inspection_scope_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	bundle_id INTEGER NOT NULL, 
	scope_code VARCHAR(100) NOT NULL, 
	raw_scope_code VARCHAR(100), 
	access_end VARCHAR(100), 
	orientation VARCHAR(100), 
	description LONGTEXT, 
	PRIMARY KEY (inspection_scope_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	CONSTRAINT uq_inspection_scope UNIQUE (heat_exchanger_id, bundle_id, scope_code)
)

;


CREATE TABLE inspection_scope_direction (
	scope_direction_id INTEGER NOT NULL AUTO_INCREMENT, 
	inspection_scope_id INTEGER NOT NULL, 
	direction_code VARCHAR(30) NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	PRIMARY KEY (scope_direction_id), 
	CONSTRAINT uq_scope_direction UNIQUE (inspection_scope_id, direction_code), 
	FOREIGN KEY(inspection_scope_id) REFERENCES inspection_scope (inspection_scope_id)
)

;


CREATE TABLE heat_exchanger_tube (
	tube_id INTEGER NOT NULL AUTO_INCREMENT, 
	bundle_id INTEGER NOT NULL, 
	tube_no VARCHAR(100) NOT NULL, 
	row_no INTEGER, 
	column_no INTEGER, 
	layout_zone VARCHAR(100), 
	pass_no INTEGER, 
	position_x FLOAT, 
	position_y FLOAT, 
	position_z FLOAT, 
	position_locked BOOL NOT NULL, 
	lifecycle_no INTEGER NOT NULL, 
	current_status VARCHAR(30) NOT NULL, 
	installed_at DATETIME, 
	plugging_date DATETIME, 
	source_tube_label VARCHAR(100), 
	PRIMARY KEY (tube_id), 
	CONSTRAINT uq_tube_bundle_number_lifecycle UNIQUE (bundle_id, tube_no, lifecycle_no), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
)

;

CREATE INDEX ix_tube_bundle_row_col ON heat_exchanger_tube (bundle_id, row_no, column_no);


CREATE TABLE tube_position_event (
	position_event_id INTEGER NOT NULL AUTO_INCREMENT, 
	tube_id INTEGER NOT NULL, 
	old_x FLOAT, 
	old_y FLOAT, 
	old_z FLOAT, 
	new_x FLOAT, 
	new_y FLOAT, 
	new_z FLOAT, 
	old_locked BOOL NOT NULL, 
	new_locked BOOL NOT NULL, 
	reason LONGTEXT, 
	PRIMARY KEY (position_event_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id)
)

;


CREATE TABLE tube_layout_revision (
	layout_revision_id INTEGER NOT NULL AUTO_INCREMENT, 
	bundle_id INTEGER NOT NULL, 
	inspection_id INTEGER, 
	source_path LONGTEXT NOT NULL, 
	source_checksum VARCHAR(64), 
	source_section_id INTEGER NOT NULL, 
	source_section_name VARCHAR(100), 
	source_coordinate_unit VARCHAR(30) NOT NULL, 
	source_origin_code INTEGER, 
	source_row_spacing FLOAT, 
	source_column_spacing FLOAT, 
	source_scale_metric BOOL, 
	normalized_view_direction VARCHAR(30), 
	rotation_degrees FLOAT, 
	flip_x BOOL, 
	flip_y BOOL, 
	scale_x FLOAT, 
	scale_y FLOAT, 
	offset_x FLOAT, 
	offset_y FLOAT, 
	physical_tube_count INTEGER, 
	layout_point_count INTEGER, 
	layout_count_basis VARCHAR(30) NOT NULL, 
	coverage_status VARCHAR(30) NOT NULL, 
	unresolved_count INTEGER NOT NULL, 
	count_discrepancy_note LONGTEXT, 
	revision_status VARCHAR(30) NOT NULL, 
	review_note LONGTEXT, 
	reviewed_by VARCHAR(100), 
	reviewed_at DATETIME, 
	approved_by VARCHAR(100), 
	approved_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (layout_revision_id), 
	CONSTRAINT ck_tube_layout_revision_status CHECK (revision_status IN ('DRAFT', 'REVIEWED', 'APPROVED', 'REJECTED')), 
	CONSTRAINT ck_tube_layout_revision_unit CHECK (source_coordinate_unit IN ('SOURCE_NATIVE', 'MM', 'INCH', 'GRID')), 
	CONSTRAINT ck_tube_layout_revision_count_basis CHECK (layout_count_basis IN ('PHYSICAL_TUBE', 'TUBE_END', 'MIXED', 'UNKNOWN')), 
	FOREIGN KEY(inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	CONSTRAINT ck_tube_layout_revision_coverage CHECK (coverage_status IN ('FULL', 'PARTIAL', 'CONFLICT', 'UNKNOWN')), 
	CONSTRAINT uq_tube_layout_revision_source UNIQUE (bundle_id, source_path, source_section_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
)

;

CREATE INDEX ix_tube_layout_revision_bundle_status ON tube_layout_revision (bundle_id, revision_status);


CREATE TABLE tube_sheet_geometry_revision (
	geometry_revision_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	bundle_id INTEGER, 
	iris_inspection_id INTEGER NOT NULL, 
	source_document_id INTEGER NOT NULL, 
	layout_revision_id INTEGER, 
	source_pdf_path LONGTEXT NOT NULL, 
	source_pdf_sha256 VARCHAR(64) NOT NULL, 
	source_page INTEGER NOT NULL, 
	source_equipment_code VARCHAR(100), 
	source_orientation VARCHAR(100), 
	source_page_width FLOAT, 
	source_page_height FLOAT, 
	shape_code VARCHAR(30) NOT NULL, 
	geometry_source VARCHAR(50) NOT NULL, 
	boundary_geometry_json LONGTEXT NOT NULL, 
	center_x FLOAT, 
	center_y FLOAT, 
	width FLOAT, 
	height FLOAT, 
	rotation_degrees FLOAT NOT NULL, 
	aspect_ratio FLOAT, 
	hull_fill_ratio FLOAT, 
	shape_confidence FLOAT, 
	consensus_shape_code VARCHAR(30), 
	consensus_confidence FLOAT, 
	consensus_sample_count INTEGER NOT NULL, 
	cross_year_consistent BOOL, 
	explicit_boundary_detected BOOL NOT NULL, 
	expected_tube_count INTEGER, 
	extracted_tube_count INTEGER NOT NULL, 
	tube_count_delta INTEGER, 
	tube_count_match BOOL NOT NULL, 
	extraction_method VARCHAR(50) NOT NULL, 
	algorithm_version VARCHAR(50) NOT NULL, 
	verification_status VARCHAR(20) NOT NULL, 
	review_status VARCHAR(20) NOT NULL, 
	analysis_note LONGTEXT, 
	reviewed_by VARCHAR(100), 
	reviewed_at DATETIME, 
	analyzed_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (geometry_revision_id), 
	CONSTRAINT uq_tube_sheet_geometry_source UNIQUE (iris_inspection_id, source_pdf_sha256, source_page, algorithm_version), 
	CONSTRAINT ck_tube_sheet_geometry_shape CHECK (shape_code IN ('CIRCULAR', 'ELLIPTICAL', 'RECTANGULAR', 'ROUNDED_RECTANGLE', 'OBROUND', 'SEGMENTED_CIRCLE', 'CUSTOM_POLYGON', 'UNKNOWN')), 
	FOREIGN KEY(layout_revision_id) REFERENCES tube_layout_revision (layout_revision_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	CONSTRAINT ck_tube_sheet_geometry_verification_status CHECK (verification_status IN ('PASS', 'WARNING', 'FAIL')), 
	CONSTRAINT ck_tube_sheet_geometry_review_status CHECK (review_status IN ('DRAFT', 'REVIEWED', 'APPROVED', 'REJECTED', 'CONFLICT')), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
)

;

CREATE INDEX ix_tube_sheet_geometry_exchanger_status ON tube_sheet_geometry_revision (heat_exchanger_id, review_status);

CREATE INDEX ix_tube_sheet_geometry_inspection ON tube_sheet_geometry_revision (iris_inspection_id, source_page);


CREATE TABLE tube_layout_point (
	layout_point_id INTEGER NOT NULL AUTO_INCREMENT, 
	layout_revision_id INTEGER NOT NULL, 
	tube_id INTEGER, 
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
	verification_status VARCHAR(30) NOT NULL, 
	conflict_code VARCHAR(100), 
	review_note LONGTEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (layout_point_id), 
	CONSTRAINT uq_tube_layout_point_grid UNIQUE (layout_revision_id, source_row, source_column), 
	CONSTRAINT ck_tube_layout_point_mapping_status CHECK (mapping_status IN ('EXISTING_TUBE_MATCH', 'NEW_TUBE_CANDIDATE', 'UNMAPPED', 'CONFLICT')), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	CONSTRAINT ck_tube_layout_point_verification_status CHECK (verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')), 
	FOREIGN KEY(layout_revision_id) REFERENCES tube_layout_revision (layout_revision_id) ON DELETE CASCADE
)

;

CREATE INDEX ix_tube_layout_point_revision_status ON tube_layout_point (layout_revision_id, verification_status);

CREATE INDEX ix_tube_layout_point_tube ON tube_layout_point (tube_id);


CREATE TABLE inspection_plan_v2 (
	inspection_plan_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	planned_date DATETIME NOT NULL, 
	application_date DATETIME NOT NULL, 
	application_due_date DATETIME, 
	approval_date DATETIME, 
	requested_by_user_id INTEGER, 
	approved_by_user_id INTEGER, 
	target_locked_at DATETIME, 
	inspection_started_at DATETIME, 
	inspection_completed_at DATETIME, 
	decision_note LONGTEXT, 
	cancellation_reason LONGTEXT, 
	inspection_method VARCHAR(50) NOT NULL, 
	scope_code VARCHAR(100) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	completed_inspection_id INTEGER, 
	notes LONGTEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (inspection_plan_id), 
	FOREIGN KEY(completed_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(requested_by_user_id) REFERENCES app_user (user_id), 
	FOREIGN KEY(approved_by_user_id) REFERENCES app_user (user_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	CONSTRAINT uq_inspection_plan_completed_inspection UNIQUE (completed_inspection_id)
)

;


CREATE TABLE inspection_plan_tube_target (
	inspection_plan_tube_target_id INTEGER NOT NULL AUTO_INCREMENT, 
	inspection_plan_id INTEGER NOT NULL, 
	tube_id INTEGER NOT NULL, 
	source_iris_tube_result_id INTEGER, 
	bundle_id_at_selection INTEGER NOT NULL, 
	tube_no_at_selection VARCHAR(100) NOT NULL, 
	row_no_at_selection INTEGER, 
	column_no_at_selection INTEGER, 
	tube_status_at_selection VARCHAR(30) NOT NULL, 
	selected_by_user_id INTEGER, 
	selected_at DATETIME NOT NULL, 
	target_status VARCHAR(30) NOT NULL, 
	excluded_reason LONGTEXT, 
	inspected_at DATETIME, 
	PRIMARY KEY (inspection_plan_tube_target_id), 
	CONSTRAINT ck_inspection_plan_tube_status CHECK (target_status IN ('TARGETED', 'INSPECTED', 'EXCLUDED')), 
	CONSTRAINT uq_inspection_plan_tube UNIQUE (inspection_plan_id, tube_id), 
	FOREIGN KEY(bundle_id_at_selection) REFERENCES tube_bundle (bundle_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	FOREIGN KEY(selected_by_user_id) REFERENCES app_user (user_id), 
	FOREIGN KEY(source_iris_tube_result_id) REFERENCES iris_tube_result (iris_tube_result_id), 
	FOREIGN KEY(inspection_plan_id) REFERENCES inspection_plan_v2 (inspection_plan_id) ON DELETE CASCADE
)

;

CREATE INDEX ix_inspection_plan_tube_target_plan_status ON inspection_plan_tube_target (inspection_plan_id, target_status);


CREATE TABLE inspection_plan_event (
	inspection_plan_event_id INTEGER NOT NULL AUTO_INCREMENT, 
	inspection_plan_id INTEGER NOT NULL, 
	previous_status VARCHAR(30), 
	new_status VARCHAR(30) NOT NULL, 
	actor_user_id INTEGER, 
	actor_role VARCHAR(30) NOT NULL, 
	reason LONGTEXT, 
	target_tube_count INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (inspection_plan_event_id), 
	FOREIGN KEY(actor_user_id) REFERENCES app_user (user_id), 
	FOREIGN KEY(inspection_plan_id) REFERENCES inspection_plan_v2 (inspection_plan_id) ON DELETE CASCADE
)

;

CREATE INDEX ix_inspection_plan_event_plan_created ON inspection_plan_event (inspection_plan_id, created_at);


CREATE TABLE work_order_v2 (
	work_order_id INTEGER NOT NULL AUTO_INCREMENT, 
	work_order_code VARCHAR(100) NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	work_type VARCHAR(50) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	planned_start DATETIME, 
	planned_end DATETIME, 
	completed_at DATETIME, 
	description LONGTEXT, 
	result LONGTEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (work_order_id), 
	UNIQUE (work_order_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;


CREATE TABLE maintenance_record (
	maintenance_record_id INTEGER NOT NULL AUTO_INCREMENT, 
	work_order_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER NOT NULL, 
	tube_id INTEGER, 
	action_date DATETIME NOT NULL, 
	action_type VARCHAR(50) NOT NULL, 
	old_status VARCHAR(30), 
	new_status VARCHAR(30), 
	details LONGTEXT, 
	PRIMARY KEY (maintenance_record_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	FOREIGN KEY(work_order_id) REFERENCES work_order_v2 (work_order_id)
)

;


CREATE TABLE tube_lifecycle_event (
	lifecycle_event_id INTEGER NOT NULL AUTO_INCREMENT, 
	tube_id INTEGER NOT NULL, 
	event_type VARCHAR(40) NOT NULL, 
	reason LONGTEXT, 
	source_document_id INTEGER, 
	PRIMARY KEY (lifecycle_event_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id)
)

;


CREATE TABLE inspection_campaign (
	campaign_id INTEGER NOT NULL AUTO_INCREMENT, 
	unit_id INTEGER NOT NULL, 
	campaign_year INTEGER NOT NULL, 
	campaign_name VARCHAR(300) NOT NULL, 
	project_name VARCHAR(300), 
	customer VARCHAR(300), 
	start_date DATETIME, 
	end_date DATETIME, 
	PRIMARY KEY (campaign_id), 
	FOREIGN KEY(unit_id) REFERENCES process_unit (unit_id), 
	CONSTRAINT uq_campaign_unit_year_name UNIQUE (unit_id, campaign_year, campaign_name)
)

;


CREATE TABLE iris_inspection (
	iris_inspection_id INTEGER NOT NULL AUTO_INCREMENT, 
	campaign_id INTEGER NOT NULL, 
	source_document_id INTEGER NOT NULL, 
	heat_exchanger_id INTEGER, 
	bundle_id INTEGER, 
	inspection_scope_id INTEGER, 
	superseded_by_inspection_id INTEGER, 
	report_sequence INTEGER NOT NULL, 
	report_number VARCHAR(200), 
	report_date DATETIME, 
	inspection_date DATETIME, 
	installation_or_replacement_date DATETIME, 
	installation_or_replacement_date_raw VARCHAR(100), 
	installation_or_replacement_year INTEGER, 
	installation_or_replacement_date_precision VARCHAR(20), 
	commissioning_date DATETIME, 
	manufacturing_date DATETIME, 
	report_type VARCHAR(100), 
	inspection_method VARCHAR(50) NOT NULL, 
	original_equipment_id VARCHAR(200) NOT NULL, 
	canonical_equipment_code VARCHAR(100), 
	source_equipment_label VARCHAR(200), 
	source_bundle_code VARCHAR(100), 
	source_scope_code VARCHAR(100), 
	report_status VARCHAR(40) NOT NULL, 
	extraction_status VARCHAR(40), 
	report_available BOOL, 
	tube_map_available BOOL, 
	tube_results_table_available BOOL, 
	extraction_reason LONGTEXT, 
	total_tube_count_reported INTEGER, 
	inspected_tube_count_reported INTEGER, 
	extracted_tube_result_count INTEGER NOT NULL, 
	reported_minimum_thickness_mm FLOAT, 
	reported_maximum_wall_loss_percent FLOAT, 
	reported_average_wall_loss_percent FLOAT, 
	representative_corrosion_type VARCHAR(100), 
	raw_report_json LONGTEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (iris_inspection_id), 
	FOREIGN KEY(campaign_id) REFERENCES inspection_campaign (campaign_id), 
	FOREIGN KEY(inspection_scope_id) REFERENCES inspection_scope (inspection_scope_id), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id), 
	CONSTRAINT uq_inspection_source_sequence UNIQUE (source_document_id, report_sequence), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	FOREIGN KEY(superseded_by_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	FOREIGN KEY(bundle_id) REFERENCES tube_bundle (bundle_id)
)

;

CREATE INDEX ix_iris_inspection_hx_date ON iris_inspection (heat_exchanger_id, report_date);


CREATE TABLE iris_inspection_spec_snapshot (
	spec_snapshot_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	raw_json LONGTEXT, 
	PRIMARY KEY (spec_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_inspection_summary_history (
	summary_history_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	previous_inspection_date DATETIME, 
	previous_maximum_wall_loss_percent FLOAT, 
	plugged_tube_count_before INTEGER, 
	plugged_tube_count_after INTEGER, 
	summary_remarks LONGTEXT, 
	raw_json LONGTEXT, 
	PRIMARY KEY (summary_history_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_setup_snapshot (
	setup_snapshot_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	customer VARCHAR(300), 
	project_name VARCHAR(300), 
	equipment_name VARCHAR(200), 
	equipment_number VARCHAR(200), 
	process_code VARCHAR(100), 
	production_line VARCHAR(100), 
	shell_fluid VARCHAR(200), 
	tube_fluid VARCHAR(200), 
	tube_type VARCHAR(100), 
	equipment_maker VARCHAR(100), 
	equipment_model VARCHAR(100), 
	equipment_serial_number VARCHAR(100), 
	search_unit_maker VARCHAR(100), 
	search_unit_model VARCHAR(100), 
	search_unit_serial_number VARCHAR(100), 
	frequency_mhz FLOAT, 
	out_diameter_mm FLOAT, 
	tube_length_m FLOAT, 
	material_velocity_meter_per_sec FLOAT, 
	scan_velocity_meter_per_min FLOAT, 
	water_pressure_kg_per_cm2 FLOAT, 
	water_temperature_celsius FLOAT, 
	raw_json LONGTEXT, 
	PRIMARY KEY (setup_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE inspection_provider (
	inspection_provider_id INTEGER NOT NULL AUTO_INCREMENT, 
	provider_code VARCHAR(50) NOT NULL, 
	provider_name VARCHAR(300) NOT NULL, 
	provider_local_name VARCHAR(300), 
	business_registration_no VARCHAR(50), 
	contact_name VARCHAR(100), 
	contact_phone VARCHAR(100), 
	contact_email VARCHAR(200), 
	address VARCHAR(500), 
	fax VARCHAR(100), 
	is_active BOOL NOT NULL, 
	remarks LONGTEXT, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (inspection_provider_id), 
	UNIQUE (provider_code)
)

;


CREATE TABLE inspection_execution_snapshot (
	inspection_execution_snapshot_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	inspection_provider_id INTEGER, 
	inspection_company_raw VARCHAR(300), 
	inspection_company_source_text VARCHAR(500), 
	inspection_company_brand VARCHAR(200), 
	source_page INTEGER, 
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
	remarks LONGTEXT, 
	raw_json LONGTEXT, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (inspection_execution_snapshot_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(inspection_provider_id) REFERENCES inspection_provider (inspection_provider_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_representative_assessment (
	representative_assessment_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	target_tube VARCHAR(200), 
	minimum_thickness_mm FLOAT, 
	wall_loss_percent FLOAT, 
	defect_type VARCHAR(100), 
	start_point VARCHAR(200), 
	end_point VARCHAR(200), 
	direction_labels_json LONGTEXT, 
	raw_json LONGTEXT, 
	PRIMARY KEY (representative_assessment_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_recommendation (
	recommendation_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	recommendation_text LONGTEXT NOT NULL, 
	PRIMARY KEY (recommendation_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	CONSTRAINT uq_recommendation_sequence UNIQUE (iris_inspection_id, sequence_no)
)

;


CREATE TABLE inspection_personnel (
	inspection_personnel_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	role VARCHAR(50) NOT NULL, 
	person_name VARCHAR(200), 
	organization VARCHAR(300), 
	source_page INTEGER, 
	extraction_method VARCHAR(100), 
	review_required BOOL NOT NULL, 
	raw_json LONGTEXT, 
	PRIMARY KEY (inspection_personnel_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	CONSTRAINT uq_inspection_personnel_role UNIQUE (iris_inspection_id, role)
)

;


CREATE TABLE inspection_source_page (
	inspection_source_page_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	page_role VARCHAR(50) NOT NULL, 
	page_number INTEGER NOT NULL, 
	PRIMARY KEY (inspection_source_page_id), 
	CONSTRAINT uq_inspection_source_page UNIQUE (iris_inspection_id, page_role, page_number), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE inspection_attachment (
	inspection_attachment_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	attachment_present BOOL, 
	selected_value_raw VARCHAR(50), 
	attachment_types_json LONGTEXT, 
	source_page INTEGER, 
	inference_confidence VARCHAR(30), 
	raw_json LONGTEXT, 
	PRIMARY KEY (inspection_attachment_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_tube_map (
	tube_map_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	raw_json LONGTEXT, 
	PRIMARY KEY (tube_map_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE iris_tube_map_legend (
	tube_map_legend_id INTEGER NOT NULL AUTO_INCREMENT, 
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
)

;


CREATE TABLE iris_tube_result (
	iris_tube_result_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	raw_side VARCHAR(30), 
	analysis_v FLOAT, 
	source_location_raw VARCHAR(200), 
	location_source_unit VARCHAR(30), 
	remark LONGTEXT, 
	design_wall_thickness_mm FLOAT, 
	defect_code VARCHAR(100), 
	reported_depth_percent FLOAT, 
	source_page INTEGER, 
	result_status VARCHAR(30) NOT NULL, 
	quality_status VARCHAR(30) NOT NULL, 
	raw_json LONGTEXT NOT NULL, 
	PRIMARY KEY (iris_tube_result_id), 
	CONSTRAINT ck_result_mwt CHECK (minimum_wall_thickness_mm IS NULL OR minimum_wall_thickness_mm >= 0), 
	CONSTRAINT uq_iris_result_inspection_tube UNIQUE (iris_inspection_id, tube_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	CONSTRAINT ck_result_loss_percent CHECK (wall_loss_percent IS NULL OR (wall_loss_percent >= 0 AND wall_loss_percent <= 100)), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id), 
	CONSTRAINT ck_result_loss_depth CHECK (wall_loss_depth_mm IS NULL OR wall_loss_depth_mm >= 0)
)

;

CREATE INDEX ix_iris_tube_result_tube ON iris_tube_result (tube_id, iris_inspection_id);


CREATE TABLE iris_indication (
	iris_indication_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_tube_result_id INTEGER NOT NULL, 
	sequence_no INTEGER NOT NULL, 
	source_page INTEGER, 
	visual_page_role VARCHAR(50), 
	source_image_xref INTEGER, 
	source_data_path VARCHAR(1000), 
	acquired_at DATETIME, 
	axial_position_mm FLOAT, 
	circumferential_angle_deg FLOAT, 
	theta_x_deg FLOAT, 
	delta_x_mm FLOAT, 
	theta_y_deg FLOAT, 
	delta_y_mm FLOAT, 
	prs_value FLOAT, 
	ar_hz FLOAT, 
	remaining_percent FLOAT, 
	defect_type VARCHAR(100), 
	defect_length_mm FLOAT, 
	measured_thickness_mm FLOAT, 
	wall_loss_depth_mm FLOAT, 
	wall_loss_percent FLOAT, 
	cscan_min_wall_thickness_mm FLOAT, 
	judgement VARCHAR(100), 
	raw_json LONGTEXT, 
	PRIMARY KEY (iris_indication_id), 
	FOREIGN KEY(iris_tube_result_id) REFERENCES iris_tube_result (iris_tube_result_id), 
	CONSTRAINT uq_indication_sequence UNIQUE (iris_tube_result_id, sequence_no)
)

;


CREATE TABLE inspection_validation (
	inspection_validation_id INTEGER NOT NULL AUTO_INCREMENT, 
	iris_inspection_id INTEGER NOT NULL, 
	extracted_tube_result_count INTEGER NOT NULL, 
	reported_vs_extracted_match BOOL, 
	calculated_minimum_thickness_mm FLOAT, 
	calculated_maximum_wall_loss_percent FLOAT, 
	calculated_average_wall_loss_percent FLOAT, 
	wall_loss_range_min_percent FLOAT, 
	wall_loss_range_max_percent FLOAT, 
	formula_check_passed BOOL, 
	validation_status VARCHAR(30) NOT NULL, 
	validator_version VARCHAR(30) NOT NULL, 
	validated_at DATETIME NOT NULL, 
	raw_json LONGTEXT, 
	PRIMARY KEY (inspection_validation_id), 
	UNIQUE (iris_inspection_id), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;


CREATE TABLE data_quality_issue (
	data_quality_issue_id INTEGER NOT NULL AUTO_INCREMENT, 
	source_document_id INTEGER NOT NULL, 
	iris_inspection_id INTEGER, 
	iris_tube_result_id INTEGER, 
	issue_fingerprint VARCHAR(64) NOT NULL, 
	issue_code VARCHAR(100) NOT NULL, 
	severity VARCHAR(20) NOT NULL, 
	field_path VARCHAR(1000), 
	source_value_json LONGTEXT, 
	calculated_value_json LONGTEXT, 
	description LONGTEXT NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	reviewer VARCHAR(100), 
	reviewed_at DATETIME, 
	resolution_note LONGTEXT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (data_quality_issue_id), 
	FOREIGN KEY(iris_tube_result_id) REFERENCES iris_tube_result (iris_tube_result_id), 
	FOREIGN KEY(source_document_id) REFERENCES source_document (source_document_id), 
	CONSTRAINT uq_quality_issue_fingerprint UNIQUE (source_document_id, issue_fingerprint), 
	FOREIGN KEY(iris_inspection_id) REFERENCES iris_inspection (iris_inspection_id)
)

;

CREATE INDEX ix_quality_issue_status_severity ON data_quality_issue (status, severity);


CREATE TABLE tube_degradation_assessment (
	degradation_assessment_id INTEGER NOT NULL AUTO_INCREMENT, 
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
	calculation_basis LONGTEXT, 
	PRIMARY KEY (degradation_assessment_id), 
	FOREIGN KEY(tube_id) REFERENCES heat_exchanger_tube (tube_id), 
	FOREIGN KEY(previous_result_id) REFERENCES iris_tube_result (iris_tube_result_id), 
	CONSTRAINT uq_degradation_result_algorithm UNIQUE (tube_id, current_result_id, algorithm_version), 
	FOREIGN KEY(current_result_id) REFERENCES iris_tube_result (iris_tube_result_id)
)

;


CREATE TABLE pressure_boundary_component (
	pressure_component_id INTEGER NOT NULL AUTO_INCREMENT, 
	heat_exchanger_id INTEGER NOT NULL, 
	component_code VARCHAR(100) NOT NULL, 
	component_type VARCHAR(40) NOT NULL, 
	side_code VARCHAR(10) NOT NULL, 
	description VARCHAR(300), 
	inside_diameter_mm FLOAT NOT NULL, 
	design_pressure_mpa FLOAT NOT NULL, 
	static_head_mpa FLOAT NOT NULL, 
	design_temperature_c FLOAT, 
	material VARCHAR(200), 
	allowable_stress_mpa FLOAT NOT NULL, 
	joint_efficiency FLOAT NOT NULL, 
	supplemental_thickness_mm FLOAT NOT NULL, 
	original_corrosion_allowance_mm FLOAT, 
	actual_thickness_mm FLOAT, 
	actual_thickness_date DATETIME, 
	design_basis_source VARCHAR(500) NOT NULL, 
	thickness_source VARCHAR(500), 
	code_edition VARCHAR(200) NOT NULL, 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (pressure_component_id), 
	CONSTRAINT uq_pressure_component_code UNIQUE (heat_exchanger_id, component_code), 
	FOREIGN KEY(heat_exchanger_id) REFERENCES heat_exchanger (heat_exchanger_id)
)

;

CREATE INDEX ix_pressure_component_hx_active ON pressure_boundary_component (heat_exchanger_id, is_active);


CREATE TABLE api510_calculation (
	api510_calculation_id INTEGER NOT NULL AUTO_INCREMENT, 
	pressure_component_id INTEGER NOT NULL, 
	calculation_date DATETIME NOT NULL, 
	inspection_type VARCHAR(30) NOT NULL, 
	actual_thickness_mm FLOAT NOT NULL, 
	required_thickness_mm FLOAT NOT NULL, 
	remaining_corrosion_allowance_mm FLOAT NOT NULL, 
	short_term_corrosion_rate_mm_per_year FLOAT, 
	long_term_corrosion_rate_mm_per_year FLOAT, 
	selected_corrosion_rate_mm_per_year FLOAT NOT NULL, 
	corrosion_rate_selection_basis VARCHAR(500) NOT NULL, 
	remaining_life_years FLOAT NOT NULL, 
	mawp_mpa FLOAT NOT NULL, 
	inspection_interval_years FLOAT NOT NULL, 
	last_inspection_date DATETIME NOT NULL, 
	next_inspection_date DATETIME NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	algorithm_version VARCHAR(30) NOT NULL, 
	code_edition VARCHAR(200) NOT NULL, 
	input_snapshot_json LONGTEXT NOT NULL, 
	result_snapshot_json LONGTEXT NOT NULL, 
	created_by VARCHAR(100), 
	created_at DATETIME NOT NULL, 
	submitted_at DATETIME, 
	reviewed_by VARCHAR(100), 
	reviewed_at DATETIME, 
	review_note LONGTEXT, 
	PRIMARY KEY (api510_calculation_id), 
	FOREIGN KEY(pressure_component_id) REFERENCES pressure_boundary_component (pressure_component_id)
)

;

CREATE INDEX ix_api510_component_created ON api510_calculation (pressure_component_id, created_at);

CREATE INDEX ix_api510_status ON api510_calculation (status);