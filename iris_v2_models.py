"""Normalized IRIS history schema.

The v2 schema is deliberately isolated from the legacy application schema so a
new database can be built and verified before the existing database is retired.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import text as sql_text

from .hx_configuration import REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT


BaseV2 = declarative_base()


DEFAULT_WALL_LOSS_COLOR_SETTINGS = (
    ("NORMAL", "정상 시작", "#14b8a6", "감육률 0% 및 정상 구간의 시작 색상", 10),
    ("WARNING", "주의", "#f59e0b", "교환기별 주의 임계값에 도달했을 때의 색상", 20),
    ("CRITICAL", "위험", "#ef4444", "교환기별 위험 임계값에 도달했을 때의 색상", 30),
    ("NOT_INSPECTED", "미검사", "#64748b", "선택 연도에 검사 결과가 없는 튜브 색상", 40),
    ("PLUGGED", "폐쇄", "#334155", "폐쇄(Plugged) 튜브의 고정 상태 색상", 50),
)

DEFAULT_SYSTEM_THEME_PRESETS = (
    ("DARK", "기본 다크", "#060e15", "#6a8494", 10),
    ("NAVY", "딥 네이비", "#071722", "#8fa9ba", 20),
    ("CHARCOAL", "차콜", "#101417", "#9aa4ab", 30),
    ("ORANGE", "사내 오렌지 · 큰 글씨", "#f4f4f4", "#595959", 40),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SchemaVersion(BaseV2):
    __tablename__ = "schema_version"

    version_id = Column(Integer, primary_key=True)
    version = Column(String(30), nullable=False, unique=True)
    applied_at = Column(DateTime, nullable=False, default=utcnow)
    description = Column(Text)


class WallLossColorSetting(BaseV2):
    __tablename__ = "wall_loss_color_setting"

    color_key = Column(String(30), primary_key=True)
    label = Column(String(100), nullable=False)
    default_color = Column(String(7), nullable=False)
    current_color = Column(String(7), nullable=False)
    description = Column(String(500))
    display_order = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class SystemThemePreset(BaseV2):
    __tablename__ = "system_theme_preset"

    preset_key = Column(String(30), primary_key=True)
    preset_name = Column(String(100), nullable=False)
    default_background_color = Column(String(7), nullable=False)
    default_label_color = Column(String(7), nullable=False)
    background_color = Column(String(7), nullable=False)
    label_color = Column(String(7), nullable=False)
    is_active = Column(Boolean, nullable=False, default=False)
    is_system = Column(Boolean, nullable=False, default=True)
    display_order = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class AppUser(BaseV2):
    __tablename__ = "app_user"

    user_id = Column(Integer, primary_key=True)
    username = Column(String(50), nullable=False, unique=True)
    display_name = Column(String(100), nullable=False)
    password_hash = Column(String(300), nullable=False)
    is_admin = Column(Boolean, nullable=False, default=False)
    is_active = Column(Boolean, nullable=False, default=True)
    pdf_open_mode = Column(String(20), nullable=False, default="NEW")
    last_login_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    permissions = relationship(
        "UserScreenPermission",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserScreenPermission(BaseV2):
    __tablename__ = "user_screen_permission"
    __table_args__ = (
        UniqueConstraint("user_id", "screen_key", name="uq_user_screen_permission"),
    )

    user_screen_permission_id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("app_user.user_id", ondelete="CASCADE"), nullable=False)
    screen_key = Column(String(50), nullable=False)
    can_view = Column(Boolean, nullable=False, default=False)
    can_edit = Column(Boolean, nullable=False, default=False)

    user = relationship("AppUser", back_populates="permissions")


class ImportBatch(BaseV2):
    __tablename__ = "import_batch"

    import_batch_id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False, default=utcnow)
    finished_at = Column(DateTime)
    status = Column(String(40), nullable=False, default="RECEIVED")
    mode = Column(String(30), nullable=False, default="load-with-warnings")
    importer_version = Column(String(30), nullable=False)
    source_path = Column(String(1000), nullable=False)
    source_file_count = Column(Integer, nullable=False, default=1)
    report_count = Column(Integer, nullable=False, default=0)
    loaded_report_count = Column(Integer, nullable=False, default=0)
    warning_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    markdown_report_path = Column(String(1000))
    json_report_path = Column(String(1000))
    load_summary_path = Column(String(1000))
    message = Column(Text)

    source_documents = relationship("SourceDocument", back_populates="import_batch")


class SourceDocument(BaseV2):
    __tablename__ = "source_document"

    source_document_id = Column(Integer, primary_key=True)
    import_batch_id = Column(Integer, ForeignKey("import_batch.import_batch_id"), nullable=False)
    source_file = Column(String(500), nullable=False)
    source_path = Column(String(1000), nullable=False)
    title = Column(String(500))
    page_count = Column(Integer)
    file_size = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, unique=True)
    schema_name = Column(String(100), nullable=False, default="iris-inspection-report")
    schema_version = Column(String(30), nullable=False, default="1.0.0")
    source_modified_at = Column(DateTime)
    imported_at = Column(DateTime, nullable=False, default=utcnow)
    document_json = Column(Text, nullable=False)
    schema_json = Column(Text)
    load_status = Column(String(30), nullable=False, default="RECEIVED")
    expected_report_count = Column(Integer, nullable=False, default=0)
    loaded_report_count = Column(Integer, nullable=False, default=0)
    missing_report_count = Column(Integer, nullable=False, default=0)
    postprocess_status = Column(String(30), nullable=False, default="PENDING")
    postprocess_message = Column(Text)

    import_batch = relationship("ImportBatch", back_populates="source_documents")
    inspections = relationship("IrisInspection", back_populates="source_document")
    pages = relationship("SourceDocumentPage", back_populates="source_document", cascade="all, delete-orphan")


class SourceDocumentPage(BaseV2):
    """Page-level PDF text and image metadata retained independently of report rows."""

    __tablename__ = "source_document_page"
    __table_args__ = (
        UniqueConstraint("source_document_id", "page_number", name="uq_source_document_page"),
        Index("ix_source_document_page_classification", "classification"),
    )

    source_document_page_id = Column(Integer, primary_key=True)
    source_document_id = Column(Integer, ForeignKey("source_document.source_document_id"), nullable=False)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"))
    page_number = Column(Integer, nullable=False)
    page_role = Column(String(50))
    classification = Column(String(80), nullable=False)
    extracted_text = Column(Text)
    text_character_count = Column(Integer, nullable=False, default=0)
    image_count = Column(Integer, nullable=False, default=0)
    images_json = Column(Text)
    visual_content_semantically_structured = Column(Boolean)
    raw_json = Column(Text)

    source_document = relationship("SourceDocument", back_populates="pages")


class Plant(BaseV2):
    __tablename__ = "plant"

    plant_id = Column(Integer, primary_key=True)
    plant_code = Column(String(50), nullable=False, unique=True)
    plant_name = Column(String(200), nullable=False)
    location = Column(String(300))
    description = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    units = relationship("ProcessUnit", back_populates="plant")


class OrganizationCode(BaseV2):
    """Display labels for the factory → production team → process hierarchy."""

    __tablename__ = "organization_code"
    __table_args__ = (
        Index("uq_organization_plant_code", "code", unique=True, sqlite_where=sql_text("kind = 'PLANT'")),
        UniqueConstraint("parent_id", "code", name="uq_organization_parent_code"),
        CheckConstraint("kind IN ('PLANT','TEAM','PROCESS')", name="ck_organization_kind"),
        CheckConstraint("(kind = 'PLANT' AND parent_id IS NULL) OR (kind != 'PLANT' AND parent_id IS NOT NULL)", name="ck_organization_parent"),
    )
    organization_code_id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("organization_code.organization_code_id"))
    kind = Column(String(20), nullable=False)
    code = Column(String(100), nullable=False)
    label = Column(String(200), nullable=False)
    description = Column(Text)


class ProcessUnit(BaseV2):
    __tablename__ = "process_unit"
    __table_args__ = (UniqueConstraint("plant_id", "unit_code", name="uq_unit_plant_code"),)

    unit_id = Column(Integer, primary_key=True)
    plant_id = Column(Integer, ForeignKey("plant.plant_id"), nullable=False)
    unit_code = Column(String(50), nullable=False)
    unit_name = Column(String(200), nullable=False)
    description = Column(Text)

    plant = relationship("Plant", back_populates="units")
    equipments = relationship("Equipment", back_populates="unit")


class Equipment(BaseV2):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("unit_id", "equipment_code", name="uq_equipment_unit_code"),)

    equipment_id = Column(Integer, primary_key=True)
    unit_id = Column(Integer, ForeignKey("process_unit.unit_id"), nullable=False)
    equipment_code = Column(String(100), nullable=False)
    equipment_name = Column(String(200), nullable=False)
    production_team_code = Column(String(50), comment="Production team from installation master column D")
    process_code = Column(String(100), comment="Process from installation master column E")
    equipment_number = Column(
        String(100),
        comment="CSV column: 설비번호",
        info={"csv_columns": ["설비번호"]},
    )
    equipment_tag = Column(
        String(100),
        comment="CSV column: 설비Tag",
        info={"csv_columns": ["설비Tag"]},
    )
    equipment_type = Column(String(80), nullable=False, default="HEAT_EXCHANGER")
    status = Column(String(40), nullable=False, default="OPERATING")
    criticality_grade = Column(String(20))
    owner_department = Column(String(100))
    owner_name = Column(String(100))
    location_desc = Column(String(300))
    manufacturer = Column(String(200))
    model_no = Column(String(100))
    serial_no = Column(String(100))
    manufacturing_date = Column(DateTime, comment="Equipment manufacturing date")
    install_date = Column(DateTime)
    is_critical = Column(Boolean, nullable=False, default=False)
    commissioning_date = Column(DateTime)
    remarks = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    unit = relationship("ProcessUnit", back_populates="equipments")
    heat_exchanger = relationship("HeatExchanger", back_populates="equipment", uselist=False)


class HeatExchanger(BaseV2):
    __tablename__ = "heat_exchanger"
    __table_args__ = (
        CheckConstraint(
            "iris_applicability IN ('REQUIRED','OPTIONAL','NOT_APPLICABLE','UNKNOWN')",
            name="ck_hx_iris_applicability",
        ),
        CheckConstraint(
            "inspection_lifecycle_status IN "
            "('NEVER_INSPECTED','PLANNED','INSPECTED','OVERDUE','NOT_APPLICABLE','UNKNOWN')",
            name="ck_hx_inspection_status",
        ),
        CheckConstraint(
            "tube_master_status IN ('NOT_AVAILABLE','PARTIAL','COMPLETE')",
            name="ck_hx_tube_master_status",
        ),
    )

    heat_exchanger_id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.equipment_id"), nullable=False, unique=True)
    exchanger_type = Column(String(80), default="SHELL_AND_TUBE")
    exchanger_type_code = Column(String(20))
    exchanger_type_name = Column(String(100))
    exchanger_type_raw = Column(String(200))
    type_mapping_status = Column(String(20), nullable=False, default="UNMAPPED")
    service_name = Column(String(200))
    iris_applicability = Column(String(30), nullable=False, default="UNKNOWN")
    inspection_lifecycle_status = Column(String(30), nullable=False, default="NEVER_INSPECTED")
    tube_master_status = Column(String(30), nullable=False, default="NOT_AVAILABLE")
    remarks = Column(Text)

    equipment = relationship("Equipment", back_populates="heat_exchanger")
    aliases = relationship("EquipmentAlias", back_populates="heat_exchanger")
    spec_revisions = relationship("HeatExchangerSpecRevision", back_populates="heat_exchanger")
    bundles = relationship("TubeBundle", back_populates="heat_exchanger")
    scopes = relationship("InspectionScope", back_populates="heat_exchanger")
    inspections = relationship("IrisInspection", back_populates="heat_exchanger")
    management_criteria = relationship(
        "HeatExchangerManagementCriteria", back_populates="heat_exchanger", uselist=False
    )
    compliance = relationship(
        "HeatExchangerCompliance", back_populates="heat_exchanger", uselist=False
    )


class EquipmentAlias(BaseV2):
    __tablename__ = "equipment_alias"
    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_unit", "normalized_alias_code",
            name="uq_equipment_alias_source",
        ),
    )

    alias_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    source_system = Column(String(100), nullable=False)
    source_unit = Column(String(100), nullable=False)
    alias_code = Column(String(200), nullable=False)
    normalized_alias_code = Column(String(200), nullable=False)
    is_approved = Column(Boolean, nullable=False, default=True)
    valid_from = Column(DateTime)
    valid_to = Column(DateTime)

    heat_exchanger = relationship("HeatExchanger", back_populates="aliases")


class HeatExchangerSpecRevision(BaseV2):
    __tablename__ = "heat_exchanger_spec_revision"
    __table_args__ = (
        UniqueConstraint("heat_exchanger_id", "revision_no", name="uq_spec_revision"),
        UniqueConstraint("heat_exchanger_id", "revision_code", name="uq_spec_revision_code"),
        Index(
            "uq_current_spec_revision", "heat_exchanger_id", unique=True,
            sqlite_where=sql_text("is_current = 1"),
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_spec_revision_effective_range",
        ),
    )

    spec_revision_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    exchanger_code = Column(
        String(100),
        comment="Stable exchanger/Item No. retained independently from equipment.equipment_code",
    )
    source_document_id = Column(Integer, ForeignKey("source_document.source_document_id"))
    revision_no = Column(Integer, nullable=False, default=1)
    revision_code = Column(String(30), nullable=False, default="1")
    effective_from = Column(DateTime, nullable=False, default=utcnow)
    effective_to = Column(DateTime)
    is_current = Column(Boolean, nullable=False, default=True)
    design_pressure = Column(Float)
    design_temperature = Column(Float)
    operation_pressure = Column(Float)
    operation_temperature = Column(Float)
    shell_material = Column(String(100))
    tube_material = Column(String(100))
    tube_count = Column(Integer)
    tube_outer_diameter_mm = Column(Float)
    tube_nominal_thickness_mm = Column(Float)
    tube_length_mm = Column(Float)
    bundle_type = Column(String(80))
    pass_count = Column(Integer)
    tube_pitch_mm = Column(Float)
    heat_transfer_area_m2 = Column(Float)
    shell_fluid = Column(String(200))
    tube_fluid = Column(String(200))
    drawing_no = Column(String(100))
    datasheet_no = Column(String(100))
    installation_orientation = Column(
        String(30),
        comment="CSV columns: 설치방향_val, 설치방향(H, V)_unit",
        info={"csv_value_column": "설치방향_val", "csv_unit_column": "설치방향(H, V)_unit"},
    )
    raw_size_text = Column(
        Text,
        comment="CSV columns: *SIZE(mm, DxHxW)_val, *SIZE(mm, DxHxW)_unit",
        info={"csv_value_column": "*SIZE(mm, DxHxW)_val", "csv_unit_column": "*SIZE(mm, DxHxW)_unit"},
    )
    master_etc = Column(
        Text,
        comment="CSV columns: Etc_val, *기타_unit",
        info={"csv_value_column": "Etc_val", "csv_unit_column": "*기타_unit"},
    )
    raw_json = Column(Text)

    heat_exchanger = relationship("HeatExchanger", back_populates="spec_revisions")
    side_specs = relationship(
        "HeatExchangerSideSpec", back_populates="spec_revision", cascade="all, delete-orphan"
    )


class HeatExchangerSideSpec(BaseV2):
    """CSV Shell/Head/Tube columns normalized by side and specification revision."""

    __tablename__ = "heat_exchanger_side_spec"
    __table_args__ = (
        UniqueConstraint("spec_revision_id", "side_code", name="uq_hx_side_spec_revision_side"),
        CheckConstraint("side_code IN ('SHELL','HEAD','TUBE')", name="ck_hx_side_spec_side"),
    )

    side_spec_id = Column(
        Integer, primary_key=True,
        comment="System key; no direct CSV column",
        info={"csv_columns": []},
    )
    spec_revision_id = Column(
        Integer, ForeignKey("heat_exchanger_spec_revision.spec_revision_id"), nullable=False,
        comment="System relationship to the imported CSV specification revision",
        info={"csv_columns": []},
    )
    side_code = Column(
        String(10), nullable=False,
        comment="Derived from CSV column prefix: Shell, Head, or Tube",
        info={"csv_columns": ["Shell/*", "Head/*", "Tube/*"]},
    )
    fluid = Column(String(200), comment="CSV columns: Shell 유체_val, 내용물 - Head_val, Tube 유체_val")
    concentration_wt_percent = Column(Float, comment="CSV columns: *농도(wt%) - Shell_val, *농도(wt%) - Tube_val")
    material_state = Column(String(80), comment="CSV columns: Shell 물질상태_val, Tube 물질상태_val")
    design_pressure_mpa = Column(Float, comment="CSV columns: Shell/Head/Tube 설계압력 value; canonical unit MPa")
    operating_pressure_mpa = Column(Float, comment="CSV columns: Shell/Head/Tube 운전압력_val; canonical unit MPa")
    design_temperature_c = Column(Float, comment="CSV columns: Shell/Head/Tube 설계온도_val; canonical unit ℃")
    operating_temperature_c = Column(Float, comment="CSV columns: Shell/Head/Tube 운전온도_val; canonical unit ℃")
    material = Column(String(200), comment="CSV columns: Shell 재질_val, Head 재질_val, Tube 재질_val")
    part_material = Column(String(200), comment="CSV columns: Shell Part 재질_val, Tube Part 재질_val")
    gasket_material = Column(String(200), comment="CSV columns: Shell 개스켓 재질_val, Tube 게스켓 재질_val")
    pwht_required = Column(Boolean, comment="CSV columns: Shell 후열처리여부_val, Tube 후열처리부_val")
    nde_percent = Column(Float, comment="CSV columns: SHELL/HEAD/Tube 비파괴검사율_val; canonical unit %")
    welding_efficiency = Column(Float, comment="CSV columns: Shell 용접효율_val, Tube 용접효율_val")
    calculated_thickness_mm = Column(Float, comment="CSV columns: SHELL/HEAD/Tube 계산두께_val; canonical unit mm")
    corrosion_allowance_mm = Column(Float, comment="CSV columns: SHELL/HEAD/Tube 부식여유_val; canonical unit mm")
    used_thickness_mm = Column(Float, comment="CSV columns: SHELL/HEAD/Tube 사용두께_val; canonical unit mm")
    raw_json = Column(Text, comment="Raw CSV values and units for the side")

    spec_revision = relationship("HeatExchangerSpecRevision", back_populates="side_specs")
    capacities = relationship(
        "HeatExchangerCapacity", back_populates="side_spec", cascade="all, delete-orphan"
    )


class HeatExchangerCapacity(BaseV2):
    """One-to-many capacity values parsed from CSV design/operating capacity cells."""

    __tablename__ = "heat_exchanger_capacity"
    __table_args__ = (
        UniqueConstraint(
            "side_spec_id", "capacity_type", "sequence_no", name="uq_hx_capacity_side_type_seq"
        ),
        CheckConstraint("capacity_type IN ('DESIGN','OPERATING')", name="ck_hx_capacity_type"),
    )

    capacity_id = Column(Integer, primary_key=True, comment="System key; no direct CSV column")
    side_spec_id = Column(
        Integer, ForeignKey("heat_exchanger_side_spec.side_spec_id"), nullable=False,
        comment="System relationship to Shell/Head/Tube CSV side",
    )
    capacity_type = Column(
        String(20), nullable=False,
        comment="Derived from CSV column name: 설계용량=DESIGN, 운전용량=OPERATING",
    )
    sequence_no = Column(Integer, nullable=False, default=1, comment="Order of multiple CSV value/unit pairs")
    capacity_value = Column(Float, comment="CSV columns: Shell/Tube 설계용량_val or 운전용량_val")
    capacity_unit = Column(String(30), comment="CSV columns: Shell/Tube 설계용량_unit or 운전용량_unit")
    raw_value = Column(Text, comment="Original CSV capacity text before parsing")

    side_spec = relationship("HeatExchangerSideSpec", back_populates="capacities")


class HeatExchangerCompliance(BaseV2):
    """Master governance, regulatory, and document attributes from the CSV."""

    __tablename__ = "heat_exchanger_compliance"

    compliance_id = Column(Integer, primary_key=True, comment="System key; no direct CSV column")
    heat_exchanger_id = Column(
        Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False, unique=True,
        comment="System relationship resolved from CSV 공정 + 설비코드",
    )
    management_change_code = Column(String(100), comment="CSV column: 변경관리코드")
    equipment_class_code = Column(String(50), comment="CSV column: 설비클래스(CODE)")
    equipment_class_name = Column(String(100), comment="CSV column: 설비클래스")
    psm_type_code = Column(String(50), comment="CSV column: PSM유형(CODE)")
    psm_type_name = Column(String(100), comment="CSV column: PSM유형")
    fabrication_standard = Column(String(200), comment="CSV columns: 제작규격_val, *제작규격_unit")
    related_pid_no = Column(String(200), comment="CSV columns: Related P_ID No._val, *연관 P&ID No._unit")
    insulation_required = Column(Boolean, comment="CSV columns: 보온여부_val, 보온여부_unit")
    rbi_target = Column(Boolean, comment="CSV columns: RBI 대상_val, RBI 대상_unit")
    remarks = Column(Text, comment="CSV columns: Etc_val, *기타_unit")
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    heat_exchanger = relationship("HeatExchanger", back_populates="compliance")


class MasterHeatExchangerStaging(BaseV2):
    """Validation-first landing area for Master_HeatExchanger CSV rows."""

    __tablename__ = "master_heat_exchanger_staging"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "source_row_no", name="uq_master_staging_batch_row"),
    )

    staging_id = Column(Integer, primary_key=True, comment="System key; no direct CSV column")
    import_batch_id = Column(
        Integer, ForeignKey("import_batch.import_batch_id"), nullable=False,
        comment="Import batch for Master_HeatExchanger.csv",
    )
    source_row_no = Column(Integer, nullable=False, comment="CSV physical row number")
    process_code = Column(String(50), comment="CSV column: 공정")
    equipment_code = Column(String(100), comment="CSV column: 설비코드")
    raw_json = Column(Text, nullable=False, comment="All 124 CSV columns preserved as JSON")
    validation_status = Column(String(30), comment="System validation result for the CSV row")
    validation_message = Column(Text, comment="System validation details for the CSV row")
    matched_equipment_id = Column(
        Integer, ForeignKey("equipment.equipment_id"),
        comment="Resolved using CSV columns 공정 + 설비코드",
    )
    created_at = Column(DateTime, nullable=False, default=utcnow)


class SchemaTableDictionary(BaseV2):
    """Queryable SQLite replacement for table comments."""

    __tablename__ = "schema_table_dictionary"

    table_name = Column(String(100), primary_key=True, comment="DB table name")
    source_file = Column(String(500), comment="CSV source file name")
    table_description = Column(Text, nullable=False, comment="Business purpose of the table")
    source_description = Column(Text, comment="CSV source scope represented by the table")
    remark = Column(Text, comment="Additional schema remark")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class SchemaFieldDictionary(BaseV2):
    """Persistent CSV-to-DB field remarks and transformation rules."""

    __tablename__ = "schema_field_dictionary"

    mapping_key = Column(String(200), primary_key=True, comment="Stable mapping identifier")
    table_name = Column(String(100), nullable=False, comment="Target DB table")
    column_name = Column(String(100), nullable=False, comment="Target DB column")
    csv_value_column = Column(String(300), comment="Exact CSV value column name")
    csv_unit_column = Column(String(300), comment="Exact CSV unit column name")
    discriminator_column = Column(String(100), comment="Target discriminator such as side_code")
    discriminator_value = Column(String(100), comment="Discriminator value such as SHELL/HEAD/TUBE")
    field_description = Column(Text, nullable=False, comment="Business meaning of the DB field")
    canonical_unit = Column(String(30), comment="Canonical DB unit")
    transform_rule = Column(Text, comment="CSV-to-DB conversion and normalization rule")
    remark = Column(Text, comment="CSV column provenance remark")
    created_at = Column(DateTime, nullable=False, default=utcnow)


class HeatExchangerManagementCriteria(BaseV2):
    __tablename__ = "heat_exchanger_management_criteria"
    __table_args__ = (
        CheckConstraint(
            "allowable_plugging_percent IS NULL OR "
            "(allowable_plugging_percent >= 0 AND allowable_plugging_percent <= 100)",
            name="ck_criteria_plugging_percent",
        ),
        CheckConstraint(
            "warning_wall_loss_percent IS NULL OR "
            "(warning_wall_loss_percent >= 0 AND warning_wall_loss_percent <= 100)",
            name="ck_criteria_warning_loss",
        ),
        CheckConstraint(
            "critical_wall_loss_percent IS NULL OR "
            "(critical_wall_loss_percent >= 0 AND critical_wall_loss_percent <= 100)",
            name="ck_criteria_critical_loss",
        ),
    )

    management_criteria_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(
        Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False, unique=True
    )
    allowable_plugging_percent = Column(
        Float, default=REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT
    )
    warning_wall_loss_percent = Column(Float, default=20.0)
    critical_wall_loss_percent = Column(Float, default=40.0)
    minimum_wall_thickness_mm = Column(Float)
    inspection_cycle_months = Column(Integer)
    turnaround_cycle_years = Column(Integer)
    last_turnaround_year = Column(Integer)
    next_turnaround_year = Column(Integer)
    criteria_note = Column(Text)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    heat_exchanger = relationship("HeatExchanger", back_populates="management_criteria")


class TubeBundle(BaseV2):
    __tablename__ = "tube_bundle"
    __table_args__ = (
        UniqueConstraint("heat_exchanger_id", "bundle_code", "lifecycle_no", name="uq_bundle_lifecycle"),
    )

    bundle_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    bundle_code = Column(String(100), nullable=False, default="MAIN")
    lifecycle_no = Column(Integer, nullable=False, default=1)
    orientation = Column(String(100))
    pass_no = Column(Integer)
    section_name = Column(String(100))
    expected_tube_count = Column(Integer)
    retired_at = Column(DateTime)
    status = Column(String(30), nullable=False, default="ACTIVE")

    heat_exchanger = relationship("HeatExchanger", back_populates="bundles")
    tubes = relationship("HeatExchangerTube", back_populates="bundle")
    scopes = relationship("InspectionScope", back_populates="bundle")


class InspectionScope(BaseV2):
    __tablename__ = "inspection_scope"
    __table_args__ = (
        UniqueConstraint("heat_exchanger_id", "bundle_id", "scope_code", name="uq_inspection_scope"),
    )

    inspection_scope_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    bundle_id = Column(Integer, ForeignKey("tube_bundle.bundle_id"), nullable=False)
    scope_code = Column(String(100), nullable=False, default="ALL")
    raw_scope_code = Column(String(100))
    access_end = Column(String(100))
    orientation = Column(String(100))
    description = Column(Text)

    heat_exchanger = relationship("HeatExchanger", back_populates="scopes")
    bundle = relationship("TubeBundle", back_populates="scopes")
    directions = relationship("InspectionScopeDirection", back_populates="scope", cascade="all, delete-orphan")
    inspections = relationship("IrisInspection", back_populates="inspection_scope")


class InspectionScopeDirection(BaseV2):
    __tablename__ = "inspection_scope_direction"
    __table_args__ = (
        UniqueConstraint("inspection_scope_id", "direction_code", name="uq_scope_direction"),
    )

    scope_direction_id = Column(Integer, primary_key=True)
    inspection_scope_id = Column(Integer, ForeignKey("inspection_scope.inspection_scope_id"), nullable=False)
    direction_code = Column(String(30), nullable=False)
    sequence_no = Column(Integer, nullable=False, default=1)

    scope = relationship("InspectionScope", back_populates="directions")


class HeatExchangerTube(BaseV2):
    __tablename__ = "heat_exchanger_tube"
    __table_args__ = (
        UniqueConstraint("bundle_id", "tube_no", "lifecycle_no", name="uq_tube_bundle_number_lifecycle"),
        Index("ix_tube_bundle_row_col", "bundle_id", "row_no", "column_no"),
    )

    tube_id = Column(Integer, primary_key=True)
    bundle_id = Column(Integer, ForeignKey("tube_bundle.bundle_id"), nullable=False)
    tube_no = Column(String(100), nullable=False)
    row_no = Column(Integer)
    column_no = Column(Integer)
    layout_zone = Column(String(100))
    pass_no = Column(Integer)
    position_x = Column(Float)
    position_y = Column(Float)
    position_z = Column(Float)
    position_locked = Column(Boolean, nullable=False, default=False)
    lifecycle_no = Column(Integer, nullable=False, default=1)
    current_status = Column(String(30), nullable=False, default="IN_SERVICE")
    installed_at = Column(DateTime)
    plugging_date = Column(DateTime)
    source_tube_label = Column(String(100))

    bundle = relationship("TubeBundle", back_populates="tubes")
    inspection_results = relationship("IrisTubeResult", back_populates="tube")
    lifecycle_events = relationship("TubeLifecycleEvent", back_populates="tube")


class TubePositionEvent(BaseV2):
    __tablename__ = "tube_position_event"

    position_event_id = Column(Integer, primary_key=True)
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"), nullable=False)
    old_x = Column(Float); old_y = Column(Float); old_z = Column(Float)
    new_x = Column(Float); new_y = Column(Float); new_z = Column(Float)
    old_locked = Column(Boolean, nullable=False, default=False)
    new_locked = Column(Boolean, nullable=False, default=False)
    reason = Column(Text)


class TubeLayoutRevision(BaseV2):
    """Versioned source layout kept separate from the physical tube master."""

    __tablename__ = "tube_layout_revision"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id", "source_path", "source_section_id",
            name="uq_tube_layout_revision_source",
        ),
        CheckConstraint(
            "revision_status IN ('DRAFT', 'REVIEWED', 'APPROVED', 'REJECTED')",
            name="ck_tube_layout_revision_status",
        ),
        CheckConstraint(
            "source_coordinate_unit IN ('SOURCE_NATIVE', 'MM', 'INCH', 'GRID')",
            name="ck_tube_layout_revision_unit",
        ),
        CheckConstraint(
            "layout_count_basis IN ('PHYSICAL_TUBE', 'TUBE_END', 'MIXED', 'UNKNOWN')",
            name="ck_tube_layout_revision_count_basis",
        ),
        CheckConstraint(
            "coverage_status IN ('FULL', 'PARTIAL', 'CONFLICT', 'UNKNOWN')",
            name="ck_tube_layout_revision_coverage",
        ),
        Index("ix_tube_layout_revision_bundle_status", "bundle_id", "revision_status"),
    )

    layout_revision_id = Column(Integer, primary_key=True)
    bundle_id = Column(Integer, ForeignKey("tube_bundle.bundle_id"), nullable=False)
    inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"))
    source_path = Column(Text, nullable=False)
    source_checksum = Column(String(64))
    source_section_id = Column(Integer, nullable=False)
    source_section_name = Column(String(100))
    source_coordinate_unit = Column(String(30), nullable=False, default="SOURCE_NATIVE")
    source_origin_code = Column(Integer)
    source_row_spacing = Column(Float)
    source_column_spacing = Column(Float)
    source_scale_metric = Column(Boolean)
    normalized_view_direction = Column(String(30))
    rotation_degrees = Column(Float)
    flip_x = Column(Boolean)
    flip_y = Column(Boolean)
    scale_x = Column(Float)
    scale_y = Column(Float)
    offset_x = Column(Float)
    offset_y = Column(Float)
    physical_tube_count = Column(Integer)
    layout_point_count = Column(Integer)
    layout_count_basis = Column(String(30), nullable=False, default="UNKNOWN")
    coverage_status = Column(String(30), nullable=False, default="UNKNOWN")
    unresolved_count = Column(Integer, nullable=False, default=0)
    count_discrepancy_note = Column(Text)
    revision_status = Column(String(30), nullable=False, default="DRAFT")
    review_note = Column(Text)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    approved_by = Column(String(100))
    approved_at = Column(DateTime)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class TubeSheetGeometryRevision(BaseV2):
    """Versioned Tube Sheet boundary evidence derived from a source document.

    The geometry is intentionally separate from ``TubeLayoutRevision`` because
    an inspection PDF usually exposes the tube population envelope, not a
    dimensioned mechanical Tube Sheet boundary.
    """

    __tablename__ = "tube_sheet_geometry_revision"
    __table_args__ = (
        UniqueConstraint(
            "iris_inspection_id", "source_pdf_sha256", "source_page",
            "algorithm_version", name="uq_tube_sheet_geometry_source",
        ),
        CheckConstraint(
            "shape_code IN ('CIRCULAR', 'ELLIPTICAL', 'RECTANGULAR', "
            "'ROUNDED_RECTANGLE', 'OBROUND', 'SEGMENTED_CIRCLE', "
            "'CUSTOM_POLYGON', 'UNKNOWN')",
            name="ck_tube_sheet_geometry_shape",
        ),
        CheckConstraint(
            "review_status IN ('DRAFT', 'REVIEWED', 'APPROVED', 'REJECTED', 'CONFLICT')",
            name="ck_tube_sheet_geometry_review_status",
        ),
        CheckConstraint(
            "verification_status IN ('PASS', 'WARNING', 'FAIL')",
            name="ck_tube_sheet_geometry_verification_status",
        ),
        Index(
            "ix_tube_sheet_geometry_exchanger_status",
            "heat_exchanger_id", "review_status",
        ),
        Index(
            "ix_tube_sheet_geometry_inspection",
            "iris_inspection_id", "source_page",
        ),
    )

    geometry_revision_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(
        Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False,
    )
    bundle_id = Column(Integer, ForeignKey("tube_bundle.bundle_id"))
    iris_inspection_id = Column(
        Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False,
    )
    source_document_id = Column(
        Integer, ForeignKey("source_document.source_document_id"), nullable=False,
    )
    layout_revision_id = Column(
        Integer, ForeignKey("tube_layout_revision.layout_revision_id"),
    )
    source_pdf_path = Column(Text, nullable=False)
    source_pdf_sha256 = Column(String(64), nullable=False)
    source_page = Column(Integer, nullable=False)
    source_equipment_code = Column(String(100))
    source_orientation = Column(String(100))
    source_page_width = Column(Float)
    source_page_height = Column(Float)
    shape_code = Column(String(30), nullable=False, default="UNKNOWN")
    geometry_source = Column(String(50), nullable=False)
    boundary_geometry_json = Column(Text, nullable=False)
    center_x = Column(Float)
    center_y = Column(Float)
    width = Column(Float)
    height = Column(Float)
    rotation_degrees = Column(Float, nullable=False, default=0)
    aspect_ratio = Column(Float)
    hull_fill_ratio = Column(Float)
    shape_confidence = Column(Float)
    consensus_shape_code = Column(String(30))
    consensus_confidence = Column(Float)
    consensus_sample_count = Column(Integer, nullable=False, default=0)
    cross_year_consistent = Column(Boolean)
    explicit_boundary_detected = Column(Boolean, nullable=False, default=False)
    expected_tube_count = Column(Integer)
    extracted_tube_count = Column(Integer, nullable=False, default=0)
    tube_count_delta = Column(Integer)
    tube_count_match = Column(Boolean, nullable=False, default=False)
    extraction_method = Column(String(50), nullable=False)
    algorithm_version = Column(String(50), nullable=False)
    verification_status = Column(String(20), nullable=False, default="WARNING")
    review_status = Column(String(20), nullable=False, default="DRAFT")
    analysis_note = Column(Text)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    analyzed_at = Column(DateTime, nullable=False, default=utcnow)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class TubeLayoutPoint(BaseV2):
    """One source-grid point belonging to a versioned Tube Layout."""

    __tablename__ = "tube_layout_point"
    __table_args__ = (
        UniqueConstraint(
            "layout_revision_id", "source_row", "source_column",
            name="uq_tube_layout_point_grid",
        ),
        CheckConstraint(
            "mapping_status IN ('EXISTING_TUBE_MATCH', 'NEW_TUBE_CANDIDATE', 'UNMAPPED', 'CONFLICT')",
            name="ck_tube_layout_point_mapping_status",
        ),
        CheckConstraint(
            "verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')",
            name="ck_tube_layout_point_verification_status",
        ),
        Index("ix_tube_layout_point_tube", "tube_id"),
        Index(
            "ix_tube_layout_point_revision_status",
            "layout_revision_id", "verification_status",
        ),
    )

    layout_point_id = Column(Integer, primary_key=True)
    layout_revision_id = Column(
        Integer, ForeignKey("tube_layout_revision.layout_revision_id", ondelete="CASCADE"),
        nullable=False,
    )
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"))
    source_tube_id = Column(String(100))
    source_row = Column(Integer, nullable=False)
    source_column = Column(Integer, nullable=False)
    source_x = Column(Float, nullable=False)
    source_y = Column(Float, nullable=False)
    source_original_x = Column(Float)
    source_original_y = Column(Float)
    canonical_x = Column(Float)
    canonical_y = Column(Float)
    mapping_status = Column(String(30), nullable=False)
    verification_status = Column(String(30), nullable=False, default="PENDING")
    conflict_code = Column(String(100))
    review_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class InspectionPlan(BaseV2):
    __tablename__ = "inspection_plan_v2"
    __table_args__ = (
        UniqueConstraint("completed_inspection_id", name="uq_inspection_plan_completed_inspection"),
    )

    inspection_plan_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    planned_date = Column(DateTime, nullable=False)
    application_date = Column(DateTime, nullable=False, default=utcnow)
    application_due_date = Column(DateTime)
    approval_date = Column(DateTime)
    requested_by_user_id = Column(Integer, ForeignKey("app_user.user_id"))
    approved_by_user_id = Column(Integer, ForeignKey("app_user.user_id"))
    target_locked_at = Column(DateTime)
    inspection_started_at = Column(DateTime)
    inspection_completed_at = Column(DateTime)
    decision_note = Column(Text)
    cancellation_reason = Column(Text)
    inspection_method = Column(String(50), nullable=False, default="IRIS")
    scope_code = Column(String(100), nullable=False, default="ALL")
    status = Column(String(30), nullable=False, default="SCHEDULED")
    priority = Column(String(20), nullable=False, default="NORMAL")
    completed_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"))
    notes = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class InspectionPlanTubeTarget(BaseV2):
    """Tube selected for one exchanger-level inspection schedule."""

    __tablename__ = "inspection_plan_tube_target"
    __table_args__ = (
        UniqueConstraint("inspection_plan_id", "tube_id", name="uq_inspection_plan_tube"),
        Index(
            "ix_inspection_plan_tube_target_plan_status",
            "inspection_plan_id",
            "target_status",
        ),
        CheckConstraint(
            "target_status IN ('TARGETED', 'INSPECTED', 'EXCLUDED')",
            name="ck_inspection_plan_tube_status",
        ),
    )

    inspection_plan_tube_target_id = Column(Integer, primary_key=True)
    inspection_plan_id = Column(
        Integer, ForeignKey("inspection_plan_v2.inspection_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"), nullable=False)
    source_iris_tube_result_id = Column(
        Integer, ForeignKey("iris_tube_result.iris_tube_result_id")
    )
    bundle_id_at_selection = Column(Integer, ForeignKey("tube_bundle.bundle_id"), nullable=False)
    tube_no_at_selection = Column(String(100), nullable=False)
    row_no_at_selection = Column(Integer)
    column_no_at_selection = Column(Integer)
    tube_status_at_selection = Column(String(30), nullable=False)
    selected_by_user_id = Column(Integer, ForeignKey("app_user.user_id"))
    selected_at = Column(DateTime, nullable=False, default=utcnow)
    target_status = Column(String(30), nullable=False, default="TARGETED")
    excluded_reason = Column(Text)
    inspected_at = Column(DateTime)


class InspectionPlanEvent(BaseV2):
    """Auditable status and target changes for an inspection schedule."""

    __tablename__ = "inspection_plan_event"
    __table_args__ = (
        Index("ix_inspection_plan_event_plan_created", "inspection_plan_id", "created_at"),
    )

    inspection_plan_event_id = Column(Integer, primary_key=True)
    inspection_plan_id = Column(
        Integer, ForeignKey("inspection_plan_v2.inspection_plan_id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_status = Column(String(30))
    new_status = Column(String(30), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("app_user.user_id"))
    actor_role = Column(String(30), nullable=False)
    reason = Column(Text)
    target_tube_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class WorkOrder(BaseV2):
    __tablename__ = "work_order_v2"

    work_order_id = Column(Integer, primary_key=True)
    work_order_code = Column(String(100), nullable=False, unique=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    title = Column(String(300), nullable=False)
    work_type = Column(String(50), nullable=False, default="MAINTENANCE")
    status = Column(String(30), nullable=False, default="REQUESTED")
    priority = Column(String(20), nullable=False, default="NORMAL")
    planned_start = Column(DateTime)
    planned_end = Column(DateTime)
    completed_at = Column(DateTime)
    description = Column(Text)
    result = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class MaintenanceRecord(BaseV2):
    __tablename__ = "maintenance_record"

    maintenance_record_id = Column(Integer, primary_key=True)
    work_order_id = Column(Integer, ForeignKey("work_order_v2.work_order_id"), nullable=False)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"))
    action_date = Column(DateTime, nullable=False, default=utcnow)
    action_type = Column(String(50), nullable=False, default="MAINTENANCE")
    old_status = Column(String(30))
    new_status = Column(String(30))
    details = Column(Text)


class TubeLifecycleEvent(BaseV2):
    __tablename__ = "tube_lifecycle_event"

    lifecycle_event_id = Column(Integer, primary_key=True)
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"), nullable=False)
    event_type = Column(String(128), nullable=False)
    reason = Column(Text)
    source_document_id = Column(Integer, ForeignKey("source_document.source_document_id"))

    tube = relationship("HeatExchangerTube", back_populates="lifecycle_events")


class InspectionCampaign(BaseV2):
    __tablename__ = "inspection_campaign"
    __table_args__ = (
        UniqueConstraint("unit_id", "campaign_year", "campaign_name", name="uq_campaign_unit_year_name"),
    )

    campaign_id = Column(Integer, primary_key=True)
    unit_id = Column(Integer, ForeignKey("process_unit.unit_id"), nullable=False)
    campaign_year = Column(Integer, nullable=False)
    campaign_name = Column(String(300), nullable=False)
    project_name = Column(String(300))
    customer = Column(String(300))
    start_date = Column(DateTime)
    end_date = Column(DateTime)


class IrisInspection(BaseV2):
    __tablename__ = "iris_inspection"
    __table_args__ = (
        UniqueConstraint("source_document_id", "report_sequence", name="uq_inspection_source_sequence"),
        Index("ix_iris_inspection_hx_date", "heat_exchanger_id", "report_date"),
    )

    iris_inspection_id = Column(Integer, primary_key=True)
    campaign_id = Column(Integer, ForeignKey("inspection_campaign.campaign_id"), nullable=False)
    source_document_id = Column(Integer, ForeignKey("source_document.source_document_id"), nullable=False)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"))
    bundle_id = Column(Integer, ForeignKey("tube_bundle.bundle_id"))
    inspection_scope_id = Column(Integer, ForeignKey("inspection_scope.inspection_scope_id"))
    superseded_by_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"))
    report_sequence = Column(Integer, nullable=False)
    report_number = Column(String(200))
    report_date = Column(DateTime)
    inspection_date = Column(DateTime)
    installation_or_replacement_date = Column(DateTime)
    installation_or_replacement_date_raw = Column(String(100))
    installation_or_replacement_year = Column(Integer)
    installation_or_replacement_date_precision = Column(String(20))
    commissioning_date = Column(DateTime)
    manufacturing_date = Column(DateTime)
    report_type = Column(String(100))
    inspection_method = Column(String(50), nullable=False, default="IRIS")
    original_equipment_id = Column(String(200), nullable=False)
    canonical_equipment_code = Column(String(100))
    source_equipment_label = Column(String(200))
    source_bundle_code = Column(String(100))
    source_scope_code = Column(String(100))
    report_status = Column(String(40), nullable=False, default="READY_TO_LOAD")
    extraction_status = Column(String(40))
    report_available = Column(Boolean)
    tube_map_available = Column(Boolean)
    tube_results_table_available = Column(Boolean)
    extraction_reason = Column(Text)
    total_tube_count_reported = Column(Integer)
    inspected_tube_count_reported = Column(Integer)
    extracted_tube_result_count = Column(Integer, nullable=False, default=0)
    reported_minimum_thickness_mm = Column(Float)
    reported_maximum_wall_loss_percent = Column(Float)
    reported_average_wall_loss_percent = Column(Float)
    representative_corrosion_type = Column(String(100))
    raw_report_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow)

    source_document = relationship("SourceDocument", back_populates="inspections")
    heat_exchanger = relationship("HeatExchanger", back_populates="inspections")
    inspection_scope = relationship("InspectionScope", back_populates="inspections")
    tube_results = relationship("IrisTubeResult", back_populates="inspection", cascade="all, delete-orphan")
    validation = relationship("InspectionValidation", back_populates="inspection", uselist=False)


class IrisInspectionSpecSnapshot(BaseV2):
    __tablename__ = "iris_inspection_spec_snapshot"

    spec_snapshot_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True)
    report_material = Column(String(100))
    report_outer_diameter_mm = Column(Float)
    report_nominal_thickness_mm = Column(Float)
    report_tube_length_mm = Column(Float)
    summary_material = Column(String(100))
    summary_outer_diameter_mm = Column(Float)
    summary_design_thickness_mm = Column(Float)
    summary_length_mm = Column(Float)
    summary_total_tubes = Column(Integer)
    summary_inspected_tubes = Column(Integer)
    summary_page = Column(Integer)
    raw_json = Column(Text)


class IrisInspectionSummaryHistory(BaseV2):
    """Prior-result and plugging fields printed in document summary tables."""

    __tablename__ = "iris_inspection_summary_history"

    summary_history_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(
        Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True
    )
    previous_inspection_date = Column(DateTime)
    previous_maximum_wall_loss_percent = Column(Float)
    plugged_tube_count_before = Column(Integer)
    plugged_tube_count_after = Column(Integer)
    summary_remarks = Column(Text)
    raw_json = Column(Text)


class IrisSetupSnapshot(BaseV2):
    __tablename__ = "iris_setup_snapshot"

    setup_snapshot_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True)
    customer = Column(String(300))
    project_name = Column(String(300))
    equipment_name = Column(String(200))
    equipment_number = Column(String(200))
    process_code = Column(String(100))
    production_line = Column(String(100))
    shell_fluid = Column(String(200))
    tube_fluid = Column(String(200))
    tube_type = Column(String(100))
    equipment_maker = Column(String(100))
    equipment_model = Column(String(100))
    equipment_serial_number = Column(String(100))
    search_unit_maker = Column(String(100))
    search_unit_model = Column(String(100))
    search_unit_serial_number = Column(String(100))
    frequency_mhz = Column(Float)
    out_diameter_mm = Column(Float)
    tube_length_m = Column(Float)
    material_velocity_meter_per_sec = Column(Float)
    scan_velocity_meter_per_min = Column(Float)
    water_pressure_kg_per_cm2 = Column(Float)
    water_temperature_celsius = Column(Float)
    raw_json = Column(Text)


class InspectionProvider(BaseV2):
    """Company master for external or internal inspection providers."""

    __tablename__ = "inspection_provider"

    inspection_provider_id = Column(Integer, primary_key=True)
    provider_code = Column(String(50), nullable=False, unique=True)
    provider_name = Column(String(300), nullable=False)
    provider_local_name = Column(String(300))
    business_registration_no = Column(String(50))
    contact_name = Column(String(100))
    contact_phone = Column(String(100))
    contact_email = Column(String(200))
    address = Column(String(500))
    fax = Column(String(100))
    is_active = Column(Boolean, nullable=False, default=True)
    remarks = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class InspectionExecutionSnapshot(BaseV2):
    """Inspection-contract, procedure, software, and calibration snapshot."""

    __tablename__ = "inspection_execution_snapshot"

    inspection_execution_snapshot_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(
        Integer, ForeignKey("iris_inspection.iris_inspection_id"),
        nullable=False, unique=True,
    )
    inspection_provider_id = Column(
        Integer, ForeignKey("inspection_provider.inspection_provider_id")
    )
    inspection_company_raw = Column(String(300))
    inspection_company_source_text = Column(String(500))
    inspection_company_brand = Column(String(200))
    source_page = Column(Integer)
    contract_no = Column(String(100))
    work_order_no = Column(String(100))
    procedure_no = Column(String(100))
    procedure_revision = Column(String(50))
    acquisition_software_name = Column(String(200))
    acquisition_software_version = Column(String(100))
    analysis_software_name = Column(String(200))
    analysis_software_version = Column(String(100))
    equipment_calibration_date = Column(DateTime)
    equipment_calibration_valid_until = Column(DateTime)
    remarks = Column(Text)
    raw_json = Column(Text)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class IrisRepresentativeAssessment(BaseV2):
    __tablename__ = "iris_representative_assessment"

    representative_assessment_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True)
    target_tube = Column(String(200))
    minimum_thickness_mm = Column(Float)
    wall_loss_percent = Column(Float)
    defect_type = Column(String(100))
    start_point = Column(String(200))
    end_point = Column(String(200))
    direction_labels_json = Column(Text)
    raw_json = Column(Text)


class IrisRecommendation(BaseV2):
    __tablename__ = "iris_recommendation"
    __table_args__ = (
        UniqueConstraint("iris_inspection_id", "sequence_no", name="uq_recommendation_sequence"),
    )

    recommendation_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    recommendation_text = Column(Text, nullable=False)


class InspectionPersonnel(BaseV2):
    __tablename__ = "inspection_personnel"
    __table_args__ = (
        UniqueConstraint("iris_inspection_id", "role", name="uq_inspection_personnel_role"),
    )

    inspection_personnel_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False)
    role = Column(String(50), nullable=False)
    person_name = Column(String(200))
    organization = Column(String(300))
    source_page = Column(Integer)
    extraction_method = Column(String(100))
    review_required = Column(Boolean, nullable=False, default=False)
    raw_json = Column(Text)


class InspectionSourcePage(BaseV2):
    __tablename__ = "inspection_source_page"
    __table_args__ = (
        UniqueConstraint("iris_inspection_id", "page_role", "page_number", name="uq_inspection_source_page"),
    )

    inspection_source_page_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False)
    page_role = Column(String(50), nullable=False)
    page_number = Column(Integer, nullable=False)


class InspectionAttachment(BaseV2):
    """Attachment checkbox and attachment-type snapshot for one inspection report."""

    __tablename__ = "inspection_attachment"

    inspection_attachment_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(
        Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True
    )
    attachment_present = Column(Boolean)
    selected_value_raw = Column(String(50))
    attachment_types_json = Column(Text)
    source_page = Column(Integer)
    inference_confidence = Column(String(30))
    raw_json = Column(Text)


class IrisTubeMap(BaseV2):
    __tablename__ = "iris_tube_map"

    tube_map_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True)
    source_page = Column(Integer)
    map_date = Column(DateTime)
    mode = Column(String(30))
    raw_equipment_id = Column(String(200))
    orientation = Column(String(100))
    vertical_spacing = Column(Float)
    horizontal_spacing = Column(Float)
    total_tubes = Column(Integer)
    unmarked_or_untested_tubes = Column(Integer)
    raw_json = Column(Text)

    legends = relationship("IrisTubeMapLegend", back_populates="tube_map", cascade="all, delete-orphan")


class IrisTubeMapLegend(BaseV2):
    __tablename__ = "iris_tube_map_legend"
    __table_args__ = (
        UniqueConstraint("tube_map_id", "legend_label", name="uq_tube_map_legend"),
    )

    tube_map_legend_id = Column(Integer, primary_key=True)
    tube_map_id = Column(Integer, ForeignKey("iris_tube_map.tube_map_id"), nullable=False)
    legend_label = Column(String(100), nullable=False)
    legend_code = Column(String(100))
    value_type = Column(String(30), nullable=False)
    lower_bound_percent = Column(Float)
    upper_bound_percent = Column(Float)
    tube_count = Column(Integer, nullable=False, default=0)

    tube_map = relationship("IrisTubeMap", back_populates="legends")


class IrisTubeResult(BaseV2):
    __tablename__ = "iris_tube_result"
    __table_args__ = (
        UniqueConstraint("iris_inspection_id", "tube_id", name="uq_iris_result_inspection_tube"),
        CheckConstraint("wall_loss_percent IS NULL OR (wall_loss_percent >= 0 AND wall_loss_percent <= 100)", name="ck_result_loss_percent"),
        CheckConstraint("minimum_wall_thickness_mm IS NULL OR minimum_wall_thickness_mm >= 0", name="ck_result_mwt"),
        CheckConstraint("wall_loss_depth_mm IS NULL OR wall_loss_depth_mm >= 0", name="ck_result_loss_depth"),
        Index("ix_iris_tube_result_tube", "tube_id", "iris_inspection_id"),
    )

    iris_tube_result_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False)
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"), nullable=False)
    source_tube_id = Column(String(100), nullable=False)
    source_row = Column(Integer)
    source_column = Column(Integer)
    minimum_wall_thickness_mm = Column(Float)
    location_mm = Column(Float)
    corrosion_type = Column(String(100))
    wall_loss_depth_mm = Column(Float)
    wall_loss_percent = Column(Float)
    raw_side = Column(String(30))
    analysis_v = Column(Float)
    source_location_raw = Column(String(200))
    location_source_unit = Column(String(30))
    remark = Column(Text)
    design_wall_thickness_mm = Column(Float)
    defect_code = Column(String(100))
    reported_depth_percent = Column(Float)
    source_page = Column(Integer)
    result_status = Column(String(30), nullable=False, default="VALID")
    quality_status = Column(String(30), nullable=False, default="VALID")
    raw_json = Column(Text, nullable=False)

    inspection = relationship("IrisInspection", back_populates="tube_results")
    tube = relationship("HeatExchangerTube", back_populates="inspection_results")
    indications = relationship("IrisIndication", back_populates="tube_result", cascade="all, delete-orphan")


class IrisIndication(BaseV2):
    __tablename__ = "iris_indication"
    __table_args__ = (
        UniqueConstraint("iris_tube_result_id", "sequence_no", name="uq_indication_sequence"),
    )

    iris_indication_id = Column(Integer, primary_key=True)
    iris_tube_result_id = Column(Integer, ForeignKey("iris_tube_result.iris_tube_result_id"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    source_page = Column(Integer)
    visual_page_role = Column(String(50))
    source_image_xref = Column(Integer)
    source_data_path = Column(String(1000))
    acquired_at = Column(DateTime)
    axial_position_mm = Column(Float)
    circumferential_angle_deg = Column(Float)
    theta_x_deg = Column(Float)
    delta_x_mm = Column(Float)
    theta_y_deg = Column(Float)
    delta_y_mm = Column(Float)
    prs_value = Column(Float)
    ar_hz = Column(Float)
    remaining_percent = Column(Float)
    defect_type = Column(String(100))
    defect_length_mm = Column(Float)
    measured_thickness_mm = Column(Float)
    wall_loss_depth_mm = Column(Float)
    wall_loss_percent = Column(Float)
    cscan_min_wall_thickness_mm = Column(Float)
    judgement = Column(String(100))
    raw_json = Column(Text)

    tube_result = relationship("IrisTubeResult", back_populates="indications")


class InspectionValidation(BaseV2):
    __tablename__ = "inspection_validation"

    inspection_validation_id = Column(Integer, primary_key=True)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"), nullable=False, unique=True)
    extracted_tube_result_count = Column(Integer, nullable=False, default=0)
    reported_vs_extracted_match = Column(Boolean)
    calculated_minimum_thickness_mm = Column(Float)
    calculated_maximum_wall_loss_percent = Column(Float)
    calculated_average_wall_loss_percent = Column(Float)
    wall_loss_range_min_percent = Column(Float)
    wall_loss_range_max_percent = Column(Float)
    formula_check_passed = Column(Boolean)
    validation_status = Column(String(30), nullable=False, default="VALID")
    validator_version = Column(String(30), nullable=False)
    validated_at = Column(DateTime, nullable=False, default=utcnow)
    raw_json = Column(Text)

    inspection = relationship("IrisInspection", back_populates="validation")


class DataQualityIssue(BaseV2):
    __tablename__ = "data_quality_issue"
    __table_args__ = (
        UniqueConstraint("source_document_id", "issue_fingerprint", name="uq_quality_issue_fingerprint"),
        Index("ix_quality_issue_status_severity", "status", "severity"),
    )

    data_quality_issue_id = Column(Integer, primary_key=True)
    source_document_id = Column(Integer, ForeignKey("source_document.source_document_id"), nullable=False)
    iris_inspection_id = Column(Integer, ForeignKey("iris_inspection.iris_inspection_id"))
    iris_tube_result_id = Column(Integer, ForeignKey("iris_tube_result.iris_tube_result_id"))
    issue_fingerprint = Column(String(64), nullable=False)
    issue_code = Column(String(100), nullable=False)
    severity = Column(String(20), nullable=False)
    field_path = Column(String(1000))
    source_value_json = Column(Text)
    calculated_value_json = Column(Text)
    description = Column(Text, nullable=False)
    status = Column(String(30), nullable=False, default="OPEN")
    reviewer = Column(String(100))
    reviewed_at = Column(DateTime)
    resolution_note = Column(Text)
    created_at = Column(DateTime, nullable=False, default=utcnow)


class TubeDegradationAssessment(BaseV2):
    __tablename__ = "tube_degradation_assessment"
    __table_args__ = (
        UniqueConstraint("tube_id", "current_result_id", "algorithm_version", name="uq_degradation_result_algorithm"),
    )

    degradation_assessment_id = Column(Integer, primary_key=True)
    tube_id = Column(Integer, ForeignKey("heat_exchanger_tube.tube_id"), nullable=False)
    previous_result_id = Column(Integer, ForeignKey("iris_tube_result.iris_tube_result_id"))
    current_result_id = Column(Integer, ForeignKey("iris_tube_result.iris_tube_result_id"), nullable=False)
    assessed_at = Column(DateTime, nullable=False, default=utcnow)
    elapsed_years = Column(Float)
    thickness_change_mm = Column(Float)
    corrosion_rate_mm_per_year = Column(Float)
    wall_loss_rate_percent_per_year = Column(Float)
    minimum_allowable_thickness_mm = Column(Float)
    remaining_life_years = Column(Float)
    confidence = Column(String(30))
    status = Column(String(30), nullable=False, default="CALCULATED")
    algorithm_version = Column(String(30), nullable=False)
    calculation_basis = Column(Text)


class PressureBoundaryComponent(BaseV2):
    """Owner/user-controlled pressure-boundary design and thickness basis."""
    __tablename__ = "pressure_boundary_component"
    __table_args__ = (
        UniqueConstraint("heat_exchanger_id", "component_code", name="uq_pressure_component_code"),
        Index("ix_pressure_component_hx_active", "heat_exchanger_id", "is_active"),
    )

    pressure_component_id = Column(Integer, primary_key=True)
    heat_exchanger_id = Column(Integer, ForeignKey("heat_exchanger.heat_exchanger_id"), nullable=False)
    component_code = Column(String(100), nullable=False)
    component_type = Column(String(40), nullable=False)
    side_code = Column(String(10), nullable=False, default="SHELL")
    description = Column(String(300))
    inside_diameter_mm = Column(Float, nullable=False)
    design_pressure_mpa = Column(Float, nullable=False)
    static_head_mpa = Column(Float, nullable=False, default=0.0)
    design_temperature_c = Column(Float)
    material = Column(String(200))
    allowable_stress_mpa = Column(Float, nullable=False)
    joint_efficiency = Column(Float, nullable=False)
    supplemental_thickness_mm = Column(Float, nullable=False, default=0.0)
    original_corrosion_allowance_mm = Column(Float)
    actual_thickness_mm = Column(Float)
    actual_thickness_date = Column(DateTime)
    design_basis_source = Column(String(500), nullable=False)
    thickness_source = Column(String(500))
    code_edition = Column(String(200), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=utcnow)
    updated_at = Column(DateTime, nullable=False, default=utcnow, onupdate=utcnow)


class Api510Calculation(BaseV2):
    """Immutable-input calculation record with controlled review/approval state."""
    __tablename__ = "api510_calculation"
    __table_args__ = (
        Index("ix_api510_component_created", "pressure_component_id", "created_at"),
        Index("ix_api510_status", "status"),
    )

    api510_calculation_id = Column(Integer, primary_key=True)
    pressure_component_id = Column(Integer, ForeignKey("pressure_boundary_component.pressure_component_id"), nullable=False)
    calculation_date = Column(DateTime, nullable=False)
    inspection_type = Column(String(30), nullable=False)
    actual_thickness_mm = Column(Float, nullable=False)
    required_thickness_mm = Column(Float, nullable=False)
    remaining_corrosion_allowance_mm = Column(Float, nullable=False)
    short_term_corrosion_rate_mm_per_year = Column(Float)
    long_term_corrosion_rate_mm_per_year = Column(Float)
    selected_corrosion_rate_mm_per_year = Column(Float, nullable=False)
    corrosion_rate_selection_basis = Column(String(500), nullable=False)
    remaining_life_years = Column(Float, nullable=False)
    mawp_mpa = Column(Float, nullable=False)
    inspection_interval_years = Column(Float, nullable=False)
    last_inspection_date = Column(DateTime, nullable=False)
    next_inspection_date = Column(DateTime, nullable=False)
    status = Column(String(30), nullable=False, default="DRAFT")
    algorithm_version = Column(String(30), nullable=False)
    code_edition = Column(String(200), nullable=False)
    input_snapshot_json = Column(Text, nullable=False)
    result_snapshot_json = Column(Text, nullable=False)
    created_by = Column(String(100))
    created_at = Column(DateTime, nullable=False, default=utcnow)
    submitted_at = Column(DateTime)
    reviewed_by = Column(String(100))
    reviewed_at = Column(DateTime)
    review_note = Column(Text)
