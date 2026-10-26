from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .exchanger_type import standardize_exchanger_type
except ImportError:  # Allows direct execution from the iris directory.
    from exchanger_type import standardize_exchanger_type


APP_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = APP_DIR / "data" / "Master_HeatExchanger.csv"
DEFAULT_DB = APP_DIR / "data" / "heat_exchanger_db3.db"
IMPORTER_VERSION = "1.1.0"

MASTER_CHANGED_TABLES = {
    "import_batch",
    "plant",
    "process_unit",
    "equipment",
    "heat_exchanger",
    "heat_exchanger_spec_revision",
    "heat_exchanger_side_spec",
    "heat_exchanger_capacity",
    "heat_exchanger_compliance",
    "master_heat_exchanger_staging",
    "sqlite_sequence",
}

SIDE_MAPPINGS = {
    "SHELL": {
        "fluid": ("Shell 유체_val", "*내용물 - Shell_unit", "text"),
        "concentration_wt_percent": ("*농도(wt%) - Shell_val", "*농도(wt%) - Shell_unit", "number"),
        "material_state": ("Shell 물질상태_val", "*물질 상태 - Shell_unit", "text"),
        "design_pressure_mpa": ("Shell 설계압력_*설계압력 Mpa(㎏/㎠g)-SHELL", "*설계압력 Mpa(㎏/㎠g)-SHELL_unit", "pressure"),
        "operating_pressure_mpa": ("Shell 운전압력_val", "*운전압력 Mpa(㎏/㎠g)-SHELL_unit", "pressure"),
        "design_temperature_c": ("Shell 설계온도_val", "*설계온도(℃)-SHELL_unit", "temperature"),
        "operating_temperature_c": ("Shell 운전온도_val", "*운전온도(℃)-SHELL_unit", "temperature"),
        "material": ("Shell 재질_val", "*재질 - Shell_unit", "text"),
        "part_material": ("Shell Part 재질_val", "*재질 - 부속품(Shell)_unit", "text"),
        "gasket_material": ("Shell 개스켓 재질_val", "*재질 - 가스켓(Shell)_unit", "text"),
        "pwht_required": ("Shell 후열처리여부_val", "*후열처리여부 - Shell_unit", "boolean"),
        "nde_percent": ("SHELL 비파괴검사율_val", "*비파괴검사율(%)-SHELL_unit", "number"),
        "welding_efficiency": ("Shell 용접효율_val", "*용접효율 - Shell_unit", "number"),
        "calculated_thickness_mm": ("SHELL 계산두께_val", "*계산두께(mm) - SHELL_unit", "number"),
        "corrosion_allowance_mm": ("SHELL 부식여유_val", "*부식여유(mm) - SHELL_unit", "number"),
        "used_thickness_mm": ("SHELL 사용두께_val", "*사용두께(mm) - SHELL_unit", "number"),
    },
    "HEAD": {
        "fluid": ("내용물 - Head_val", "내용물 - Head_unit", "text"),
        "design_pressure_mpa": ("Head 설계압력_val", "설계압력 Mpa(㎏/㎠g)-HEAD_unit", "pressure"),
        "operating_pressure_mpa": ("Head 운전압력_val", "운전압력 Mpa(㎏/㎠g)-HEAD_unit", "pressure"),
        "design_temperature_c": ("Head 설계온도_val", "설계온도(℃)-HEAD_unit", "temperature"),
        "operating_temperature_c": ("Head 운전온도_val", "운전온도(℃)-HEAD_unit", "temperature"),
        "material": ("Head 재질_val", "재질 - Head_unit", "text"),
        "nde_percent": ("HEAD 비파괴검사율_val", "비파괴검사율(%)-HEAD_unit", "number"),
        "calculated_thickness_mm": ("HEAD 계산두께_val", "계산두께(mm) - HEAD_unit", "number"),
        "corrosion_allowance_mm": ("HEAD 부식여유_val", "부식여유(mm) - HEAD_unit", "number"),
        "used_thickness_mm": ("HEAD 사용두께_val", "사용두께(mm) - HEAD_unit", "number"),
    },
    "TUBE": {
        "fluid": ("Tube 유체_val", "*내용물 - Tube_unit", "text"),
        "concentration_wt_percent": ("*농도(wt%) - Tube_val", "*농도(wt%) - Tube_unit", "number"),
        "material_state": ("Tube 물질상태_val", "*물질 상태 - Tube_unit", "text"),
        "design_pressure_mpa": ("Tube 설계압력_val", "*설계압력 Mpa(㎏/㎠)-Tube_unit", "pressure"),
        "operating_pressure_mpa": ("Tube 운전압력_val", "*운전압력 Mpa(㎏/㎠)-Tube_unit", "pressure"),
        "design_temperature_c": ("Tube 설계온도_val", "*설계온도(℃) - Tube_unit", "temperature"),
        "operating_temperature_c": ("Tube 운전온도_val", "*운전온도(℃) - Tube_unit", "temperature"),
        "material": ("Tube 재질_val", "*재질 - Tube_unit", "text"),
        "part_material": ("Tube Part 재질_val", "*재질 - 부속품(Tube)_unit", "text"),
        "gasket_material": ("Tube 게스켓 재질_val", "*재질 - 가스켓(Tube)_unit", "text"),
        "pwht_required": ("Tube 후열처리부_val", "*후열처리여부 - Tube_unit", "boolean"),
        "nde_percent": ("Tube 비파괴검사율_val", "*비파괴검사율(%)-TUBE_unit", "number"),
        "welding_efficiency": ("Tube 용접효율_val", "*용접효율 - Tube_unit", "number"),
        "calculated_thickness_mm": ("Tube 계산두께_val", "*계산두께(mm) - Tube_unit", "number"),
        "corrosion_allowance_mm": ("Tube 부식여유_val", "*부식여유(mm) - Tube_unit", "number"),
        "used_thickness_mm": ("Tube 사용두께_val", "*사용두께(mm) - Tube_unit", "number"),
    },
}

CAPACITY_MAPPINGS = (
    ("SHELL", "DESIGN", "Shell 설계용량_val", "*설계용량(㎥) - Shell_unit"),
    ("TUBE", "DESIGN", "Tube 설계용량_val", "*설계용량(㎥) - Tube_unit"),
    ("SHELL", "OPERATING", "Shell 운전용량_val", "*운전용량(㎥) - Shell_unit"),
    ("TUBE", "OPERATING", "Tube 운전용량_val", "*운전용량(㎥) - Tube_unit"),
)

REQUIRED_HEADERS = {
    "공정", "설비코드", "설비명", "설비번호", "설비Tag", "설비등급", "설비상태",
    "Type_val", "Tube 개수_val", "Shell 유체_val", "Tube 유체_val",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat(sep=" ")


def raw_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def clean_text(value: Any) -> str | None:
    text = raw_text(value)
    return None if text in {"", "-", "None", "null", "NULL"} else text


def normalized_key(value: Any) -> str:
    return re.sub(r"\s+", "", raw_text(value)).upper()


def row_hash(row: dict[str, str]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def numeric_tokens(value: Any) -> list[float]:
    text = unicodedata.normalize("NFKC", raw_text(value))
    if not clean_text(text):
        return []
    tokens = re.findall(
        r"(?<![A-Za-z])[-+]?(?:\d+(?:,\d{3})*(?:\.\d+)?|\.\d+)",
        text,
    )
    result = []
    for token in tokens:
        try:
            result.append(float(token.replace(",", "")))
        except ValueError:
            pass
    return result


def parse_single_number(value: Any) -> float | None:
    tokens = numeric_tokens(value)
    return tokens[0] if len(tokens) == 1 else None


def parse_integer(value: Any) -> int | None:
    number = parse_single_number(value)
    if number is None or not float(number).is_integer():
        return None
    return int(number)


def parse_tube_count(value: Any) -> int | None:
    text = raw_text(value)
    direct = parse_integer(text)
    if direct is not None:
        return direct

    total = re.search(r"(?i)\bTOTAL\s*[:：]?\s*(\d[\d,]*)", text)
    if total:
        return int(total.group(1).replace(",", ""))

    drawing_sets = re.search(
        r"도면\s*[:：]?\s*(\d[\d,]*)\s*개?\s*[x×*]\s*(\d[\d,]*)\s*SET",
        text,
        re.IGNORECASE,
    )
    if drawing_sets:
        return int(drawing_sets.group(1).replace(",", "")) * int(
            drawing_sets.group(2).replace(",", "")
        )

    # A leading count followed by a parenthesized tube length, e.g. 208 (3710).
    leading_count = re.fullmatch(r"\s*(\d[\d,]*)\s*[\r\n ]*\(\s*\d[\d,.]*\s*\)\s*", text)
    if leading_count:
        return int(leading_count.group(1).replace(",", ""))
    return None


def _maximum_numeric_token(value: Any) -> float | None:
    tokens = numeric_tokens(value)
    if not tokens:
        return None
    return max(tokens)


def parse_pressure_mpa(value: Any, unit: Any) -> float | None:
    text = raw_text(value)
    tokens = numeric_tokens(text)
    if not tokens:
        return None
    combined = unicodedata.normalize("NFKC", f"{text} {raw_text(unit)}").lower()
    combined = combined.replace("²", "2")
    if re.search(r"(?<![\d.])\d+\.\d+\.\d+(?![\d.])", combined):
        return None
    compact_unit_text = combined.replace(" ", "")

    if "mmaq" in compact_unit_text or "mmh2o" in compact_unit_text:
        return max(tokens) * 9.80665e-6
    if "mmhg" in compact_unit_text:
        return max(tokens) * 0.000133322368
    if "psi" in compact_unit_text and "mpa" not in compact_unit_text:
        return max(tokens) * 0.006894757293

    # In the source, MPa values are often followed by equivalent kgf/cm2 values
    # in parentheses. Only the values before the first parenthesis are MPa.
    if "mpa" in compact_unit_text:
        before_parenthesis = text.split("(", 1)[0]
        mpa_tokens = numeric_tokens(before_parenthesis)
        if mpa_tokens:
            return max(mpa_tokens)
        return max(tokens)
    if "kg/cm2" in compact_unit_text or "kgf/cm2" in compact_unit_text:
        return max(tokens) * 0.0980665
    if len(tokens) == 1:
        return tokens[0]
    return None


def parse_temperature_c(value: Any) -> float | None:
    text = raw_text(value)
    if not clean_text(text):
        return None
    normalized = text.upper().replace(" ", "")
    if any(marker in normalized for marker in ("MPA", "KG/CM", "KGF/CM", "FV", "F.V", "월", "일")):
        return None
    tokens = numeric_tokens(text)
    if not tokens or any(number < -273.15 or number > 1000 for number in tokens):
        return None
    return max(tokens)


def parse_boolean(value: Any, *, insulation: bool = False) -> int | None:
    text = raw_text(value).strip().upper().replace(" ", "")
    if text in {"", "-", "N/A", "해당없음"}:
        return None
    if text in {"Y", "YES", "O", "○", "TRUE", "1"}:
        return 1
    if text in {"N", "NO", "X", "×", "Ｘ", "FALSE", "0"}:
        return 0
    if insulation and re.search(r"\d+(?:\.\d+)?MM", text):
        return 1
    return None


def infer_unit(value: Any, explicit_unit: Any) -> str | None:
    unit = clean_text(explicit_unit)
    if unit:
        return unit
    text = raw_text(value)
    patterns = (
        r"(?i)BTU\s*/\s*H(?:R)?", r"(?i)KCAL\s*/\s*H(?:R)?", r"(?i)M3\s*/\s*H(?:R)?",
        r"(?i)M\^?3", r"(?i)M2", r"(?i)KG\s*/\s*H(?:R)?", r"(?i)TON\s*/\s*H(?:R)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).replace(" ", "")
    return None


def parse_side(row: dict[str, str], side_code: str, warnings: list[str]) -> tuple[dict[str, Any], dict[str, str], bool]:
    values: dict[str, Any] = {}
    raw_side: dict[str, str] = {}
    meaningful = False
    for target, (value_col, unit_col, kind) in SIDE_MAPPINGS[side_code].items():
        raw_value = raw_text(row.get(value_col))
        raw_unit = raw_text(row.get(unit_col))
        raw_side[value_col] = raw_value
        raw_side[unit_col] = raw_unit
        if clean_text(raw_value) or clean_text(raw_unit):
            meaningful = True
        if kind == "text":
            parsed = clean_text(raw_value)
        elif kind == "boolean":
            parsed = parse_boolean(raw_value)
        elif kind == "pressure":
            parsed = parse_pressure_mpa(raw_value, raw_unit)
        elif kind == "temperature":
            parsed = parse_temperature_c(raw_value)
        else:
            parsed = parse_single_number(raw_value)
        values[target] = parsed
        if clean_text(raw_value) and parsed is None and kind != "text":
            warnings.append(f"{value_col}: 복합/비정형 값은 raw_json에 보존")
    return values, raw_side, meaningful


def table_digest(connection: sqlite3.Connection, table_name: str) -> str:
    digest = hashlib.sha256()
    for row in connection.execute(f'SELECT * FROM "{table_name}" ORDER BY rowid'):
        encoded = json.dumps(list(row), ensure_ascii=False, default=str, separators=(",", ":"))
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def protected_table_digests(connection: sqlite3.Connection) -> dict[str, str]:
    tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    return {
        table: table_digest(connection, table)
        for table in tables
        if table not in MASTER_CHANGED_TABLES
    }


def existing_inspection_state(connection: sqlite3.Connection) -> dict[int, tuple[Any, ...]]:
    return {
        row[0]: tuple(row[1:])
        for row in connection.execute(
            "SELECT heat_exchanger_id, iris_applicability, inspection_lifecycle_status, "
            "tube_master_status FROM heat_exchanger ORDER BY heat_exchanger_id"
        )
    }


def existing_master_keys(connection: sqlite3.Connection) -> dict[tuple[str, str, str], sqlite3.Row]:
    rows = connection.execute(
        """
        SELECT p.plant_id, p.plant_code, u.unit_id, u.unit_code,
               e.equipment_id, e.equipment_code, h.heat_exchanger_id,
               COALESCE(s.exchanger_code, e.equipment_code) AS exchanger_code
        FROM equipment e
        JOIN process_unit u ON u.unit_id=e.unit_id
        JOIN plant p ON p.plant_id=u.plant_id
        JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
        LEFT JOIN heat_exchanger_spec_revision s
          ON s.heat_exchanger_id=h.heat_exchanger_id AND s.is_current=1
        """
    ).fetchall()
    return {
        (
            normalized_key(r["plant_code"]),
            normalized_key(r["unit_code"]),
            normalized_key(r["exchanger_code"]),
        ): r
        for r in rows
    }


def insert_import_batch(connection: sqlite3.Connection, csv_path: Path, row_count: int, now: str) -> int:
    cursor = connection.execute(
        """
        INSERT INTO import_batch (
            started_at, status, mode, importer_version, source_path,
            source_file_count, report_count, loaded_report_count,
            warning_count, error_count, skipped_count, message
        ) VALUES (?, 'RUNNING', 'MASTER_CSV', ?, ?, 1, ?, 0, 0, 0, 0, ?)
        """,
        (now, IMPORTER_VERSION, str(csv_path), row_count, "CSV authoritative master merge; inspection history preserved"),
    )
    return int(cursor.lastrowid)


def get_or_create_units(
    connection: sqlite3.Connection, processes: list[str], now: str, source_name: str,
    plant_code: str,
) -> dict[str, int]:
    plant = connection.execute(
        "SELECT plant_id FROM plant WHERE UPPER(REPLACE(plant_code, ' ', ''))=?",
        (normalized_key(plant_code),),
    ).fetchone()
    if plant is None:
        cursor = connection.execute(
            "INSERT INTO plant (plant_code, plant_name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (plant_code, plant_code, now, now),
        )
        plant_id = int(cursor.lastrowid)
    else:
        plant_id = int(plant[0])
    units = {
        normalized_key(r["unit_code"]): int(r["unit_id"])
        for r in connection.execute("SELECT unit_id, unit_code FROM process_unit WHERE plant_id=?", (plant_id,))
    }
    for process in processes:
        key = normalized_key(process)
        if key in units:
            continue
        cursor = connection.execute(
            "INSERT INTO process_unit (plant_id, unit_code, unit_name, description) VALUES (?, ?, ?, ?)",
            (plant_id, process, process, f"Created from {source_name}"),
        )
        units[key] = int(cursor.lastrowid)
    return units


def upsert_equipment_and_exchanger(
    connection: sqlite3.Connection,
    row: dict[str, str],
    unit_id: int,
    now: str,
) -> tuple[int, int, bool]:
    exchanger_code = clean_text(row.get("설비코드"))
    if not exchanger_code:
        raise ValueError("설비코드 누락")
    asset_code = clean_text(row.get("설비번호")) or exchanger_code
    existing = connection.execute(
        """
        SELECT e.equipment_id
          FROM equipment e
          JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
         WHERE e.unit_id=?
           AND (
               UPPER(REPLACE(e.equipment_code, ' ', ''))=?
               OR EXISTS (
                   SELECT 1 FROM heat_exchanger_spec_revision s
                    WHERE s.heat_exchanger_id=h.heat_exchanger_id
                      AND s.is_current=1
                      AND UPPER(REPLACE(s.exchanger_code, ' ', ''))=?
               )
           )
         LIMIT 1
        """,
        (unit_id, normalized_key(asset_code), normalized_key(exchanger_code)),
    ).fetchone()
    name = clean_text(row.get("설비명")) or exchanger_code
    status = clean_text(row.get("설비상태")) or "UNKNOWN"
    if existing:
        equipment_id = int(existing[0])
        connection.execute(
            """
            UPDATE equipment
               SET equipment_code=?, equipment_name=?, equipment_number=?, equipment_tag=?,
                   equipment_type='HEAT_EXCHANGER', status=?, criticality_grade=?, updated_at=?
             WHERE equipment_id=?
            """,
            (
                asset_code, name, clean_text(row.get("설비번호")), clean_text(row.get("설비Tag")),
                status, clean_text(row.get("설비등급")), now, equipment_id,
            ),
        )
        inserted = False
    else:
        cursor = connection.execute(
            """
            INSERT INTO equipment (
                unit_id, equipment_code, equipment_name, equipment_number, equipment_tag,
                equipment_type, status, criticality_grade, is_critical, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'HEAT_EXCHANGER', ?, ?, 0, ?, ?)
            """,
            (
                unit_id, asset_code, name, clean_text(row.get("설비번호")), clean_text(row.get("설비Tag")),
                status, clean_text(row.get("설비등급")), now, now,
            ),
        )
        equipment_id = int(cursor.lastrowid)
        inserted = True

    exchanger = connection.execute(
        "SELECT heat_exchanger_id FROM heat_exchanger WHERE equipment_id=?", (equipment_id,)
    ).fetchone()
    exchanger_type = clean_text(row.get("Type_val"))
    type_mapping = standardize_exchanger_type(exchanger_type)
    if exchanger:
        heat_exchanger_id = int(exchanger[0])
        # Inspection governance fields are deliberately not updated.
        connection.execute(
            """
            UPDATE heat_exchanger
               SET exchanger_type=?, exchanger_type_code=?, exchanger_type_name=?,
                   exchanger_type_raw=?, type_mapping_status=?, service_name=?
             WHERE heat_exchanger_id=?
            """,
            (
                exchanger_type, type_mapping.code, type_mapping.name,
                type_mapping.raw, type_mapping.status, name, heat_exchanger_id,
            ),
        )
    else:
        cursor = connection.execute(
            """
            INSERT INTO heat_exchanger (
                equipment_id, exchanger_type, exchanger_type_code, exchanger_type_name,
                exchanger_type_raw, type_mapping_status, service_name, iris_applicability,
                inspection_lifecycle_status, tube_master_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'UNKNOWN', 'NEVER_INSPECTED', 'NOT_AVAILABLE')
            """,
            (
                equipment_id, exchanger_type, type_mapping.code, type_mapping.name,
                type_mapping.raw, type_mapping.status, name,
            ),
        )
        heat_exchanger_id = int(cursor.lastrowid)
    return equipment_id, heat_exchanger_id, inserted


def upsert_compliance(connection: sqlite3.Connection, heat_exchanger_id: int, row: dict[str, str], now: str, warnings: list[str]) -> None:
    insulation_raw = row.get("보온여부_val")
    rbi_raw = row.get("RBI 대상_val")
    insulation = parse_boolean(insulation_raw, insulation=True)
    rbi = parse_boolean(rbi_raw)
    if clean_text(insulation_raw) and insulation is None:
        warnings.append("보온여부_val: 비정형 값은 staging raw_json에 보존")
    if clean_text(rbi_raw) and rbi is None:
        warnings.append("RBI 대상_val: 비정형 값은 staging raw_json에 보존")
    values = (
        clean_text(row.get("변경관리코드")),
        clean_text(row.get("설비클래스(CODE)")),
        clean_text(row.get("설비클래스")),
        clean_text(row.get("PSM유형(CODE)")),
        clean_text(row.get("PSM유형")),
        clean_text(row.get("제작규격_val")),
        clean_text(row.get("Related P_ID No._val")),
        insulation,
        rbi,
        clean_text(row.get("Etc_val")),
        now,
    )
    existing = connection.execute(
        "SELECT compliance_id FROM heat_exchanger_compliance WHERE heat_exchanger_id=?",
        (heat_exchanger_id,),
    ).fetchone()
    if existing:
        connection.execute(
            """
            UPDATE heat_exchanger_compliance
               SET management_change_code=?, equipment_class_code=?, equipment_class_name=?,
                   psm_type_code=?, psm_type_name=?, fabrication_standard=?, related_pid_no=?,
                   insulation_required=?, rbi_target=?, remarks=?, updated_at=?
             WHERE heat_exchanger_id=?
            """,
            values + (heat_exchanger_id,),
        )
    else:
        connection.execute(
            """
            INSERT INTO heat_exchanger_compliance (
                management_change_code, equipment_class_code, equipment_class_name,
                psm_type_code, psm_type_name, fabrication_standard, related_pid_no,
                insulation_required, rbi_target, remarks, updated_at, heat_exchanger_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            values + (heat_exchanger_id,),
        )


def upsert_spec_revision(
    connection: sqlite3.Connection,
    heat_exchanger_id: int,
    row: dict[str, str],
    source_row_no: int,
    now: str,
    warnings: list[str],
    source_name: str,
) -> tuple[int, bool]:
    master_hash = row_hash(row)
    current_rows = connection.execute(
        "SELECT spec_revision_id, revision_no, raw_json FROM heat_exchanger_spec_revision "
        "WHERE heat_exchanger_id=? AND is_current=1 ORDER BY revision_no DESC",
        (heat_exchanger_id,),
    ).fetchall()
    reusable_id = None
    for current in current_rows:
        try:
            raw = json.loads(current["raw_json"] or "{}")
        except json.JSONDecodeError:
            raw = {}
        if raw.get("_master_row_sha256") == master_hash:
            reusable_id = int(current["spec_revision_id"])
            break

    shell_values, _, _ = parse_side(row, "SHELL", warnings)
    tube_count = parse_tube_count(row.get("Tube 개수_val"))
    if clean_text(row.get("Tube 개수_val")) and tube_count is None:
        warnings.append("Tube 개수_val: 복합/비정형 값은 raw_json에 보존")
    raw_payload = dict(row)
    raw_payload.update({
        "_master_import_source": source_name,
        "_master_import_row": source_row_no,
        "_master_row_sha256": master_hash,
    })
    fields = (
        shell_values.get("design_pressure_mpa"),
        shell_values.get("design_temperature_c"),
        shell_values.get("operating_pressure_mpa"),
        shell_values.get("operating_temperature_c"),
        clean_text(row.get("Shell 재질_val")),
        clean_text(row.get("Tube 재질_val")),
        tube_count,
        clean_text(row.get("Type_val")),
        clean_text(row.get("Shell 유체_val")),
        clean_text(row.get("Tube 유체_val")),
        clean_text(row.get("설치방향_val")),
        clean_text(row.get("*SIZE(mm, DxHxW)_val")),
        clean_text(row.get("Etc_val")),
        json.dumps(raw_payload, ensure_ascii=False, separators=(",", ":")),
    )
    if reusable_id is not None:
        # Identical source content is idempotent. Persisted revisions are never
        # rewritten; changed content is inserted below as a new revision.
        return reusable_id, False

    max_revision = connection.execute(
        "SELECT COALESCE(MAX(revision_no), 0) FROM heat_exchanger_spec_revision WHERE heat_exchanger_id=?",
        (heat_exchanger_id,),
    ).fetchone()[0]
    connection.execute(
        "UPDATE heat_exchanger_spec_revision SET is_current=0, effective_to=? "
        "WHERE heat_exchanger_id=? AND is_current=1",
        (now, heat_exchanger_id),
    )
    cursor = connection.execute(
        """
        INSERT INTO heat_exchanger_spec_revision (
            heat_exchanger_id, exchanger_code, revision_no, revision_code, effective_from, is_current,
            design_pressure, design_temperature, operation_pressure, operation_temperature,
            shell_material, tube_material, tube_count, bundle_type, shell_fluid, tube_fluid,
            installation_orientation, raw_size_text, master_etc, raw_json
        ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            heat_exchanger_id, clean_text(row.get("설비코드")), int(max_revision) + 1,
            str(int(max_revision) + 1), now,
        ) + fields,
    )
    return int(cursor.lastrowid), True


def upsert_side_specs_and_capacities(
    connection: sqlite3.Connection,
    spec_revision_id: int,
    row: dict[str, str],
    warnings: list[str],
) -> tuple[int, int]:
    capacity_by_side: dict[str, list[tuple[str, str, str]]] = {"SHELL": [], "HEAD": [], "TUBE": []}
    for side, capacity_type, value_col, unit_col in CAPACITY_MAPPINGS:
        capacity_by_side[side].append((capacity_type, value_col, unit_col))

    side_count = 0
    capacity_count = 0
    meaningful_sides: set[str] = set()
    for side_code in ("SHELL", "HEAD", "TUBE"):
        side_values, raw_side, meaningful = parse_side(row, side_code, warnings)
        capacity_meaningful = any(
            clean_text(row.get(value_col)) or clean_text(row.get(unit_col))
            for _, value_col, unit_col in capacity_by_side[side_code]
        )
        if not meaningful and not capacity_meaningful:
            continue
        meaningful_sides.add(side_code)
        existing = connection.execute(
            "SELECT side_spec_id FROM heat_exchanger_side_spec WHERE spec_revision_id=? AND side_code=?",
            (spec_revision_id, side_code),
        ).fetchone()
        columns = list(SIDE_MAPPINGS[side_code].keys())
        values = [side_values.get(column) for column in columns]
        raw_json = json.dumps(raw_side, ensure_ascii=False, separators=(",", ":"))
        if existing:
            side_spec_id = int(existing[0])
            assignments = ", ".join(f'"{column}"=?' for column in columns)
            connection.execute(
                f'UPDATE heat_exchanger_side_spec SET {assignments}, raw_json=? WHERE side_spec_id=?',
                values + [raw_json, side_spec_id],
            )
        else:
            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(f'"{column}"' for column in columns)
            cursor = connection.execute(
                f'INSERT INTO heat_exchanger_side_spec (spec_revision_id, side_code, {column_sql}, raw_json) '
                f'VALUES (?, ?, {placeholders}, ?)',
                [spec_revision_id, side_code] + values + [raw_json],
            )
            side_spec_id = int(cursor.lastrowid)
        side_count += 1

        # Capacities are master-only child data for the current master revision.
        connection.execute("DELETE FROM heat_exchanger_capacity WHERE side_spec_id=?", (side_spec_id,))
        for capacity_type, value_col, unit_col in capacity_by_side[side_code]:
            raw_value = raw_text(row.get(value_col))
            explicit_unit = raw_text(row.get(unit_col))
            if not clean_text(raw_value) and not clean_text(explicit_unit):
                continue
            parsed_value = parse_single_number(raw_value)
            parsed_unit = infer_unit(raw_value, explicit_unit)
            if clean_text(raw_value) and parsed_value is None:
                warnings.append(f"{value_col}: 복합/비정형 용량은 raw_value에 보존")
            connection.execute(
                """
                INSERT INTO heat_exchanger_capacity (
                    side_spec_id, capacity_type, sequence_no, capacity_value, capacity_unit, raw_value
                ) VALUES (?, ?, 1, ?, ?, ?)
                """,
                (side_spec_id, capacity_type, parsed_value, parsed_unit, raw_value or explicit_unit),
            )
            capacity_count += 1

    # Remove stale side rows only when the revision itself was previously loaded from this master.
    for stale in connection.execute(
        "SELECT side_spec_id, side_code FROM heat_exchanger_side_spec WHERE spec_revision_id=?",
        (spec_revision_id,),
    ).fetchall():
        if stale["side_code"] not in meaningful_sides:
            connection.execute("DELETE FROM heat_exchanger_capacity WHERE side_spec_id=?", (stale["side_spec_id"],))
            connection.execute("DELETE FROM heat_exchanger_side_spec WHERE side_spec_id=?", (stale["side_spec_id"],))
    return side_count, capacity_count


def _canonical_header(name: str, role: str) -> str:
    header = raw_text(name)
    role = raw_text(role)
    if not role:
        return header
    if role == "값":
        return f"{header}_val"
    if role == "단위":
        return f"{header}_unit"
    return f"{header}_{role}"


def load_csv(csv_path: Path) -> tuple[list[str], list[dict[str, str]], int]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.reader(handle))
    if not source_rows:
        raise ValueError("CSV가 비어 있습니다.")
    width = len(source_rows[0])
    if any(len(row) != width for row in source_rows):
        raise ValueError("CSV 행별 컬럼 수가 일치하지 않습니다.")

    has_role_row = len(source_rows) > 1 and any(
        raw_text(value) in {"값", "단위"} for value in source_rows[1]
    )
    if has_role_row:
        headers = [
            _canonical_header(name, role)
            for name, role in zip(source_rows[0], source_rows[1])
        ]
        data_rows = source_rows[2:]
        first_source_row = 3
    else:
        headers = [raw_text(value) for value in source_rows[0]]
        data_rows = source_rows[1:]
        first_source_row = 2
    if len(headers) != len(set(headers)):
        duplicates = [name for name, count in Counter(headers).items() if count > 1]
        raise ValueError(f"정규화 후 중복 CSV 컬럼: {', '.join(duplicates)}")
    rows = [dict(zip(headers, values)) for values in data_rows]
    missing = sorted(REQUIRED_HEADERS - set(headers))
    if missing:
        raise ValueError(f"필수 CSV 컬럼 누락: {', '.join(missing)}")
    keys = [(normalized_key(r.get("공정")), normalized_key(r.get("설비코드"))) for r in rows]
    if any(not process or not equipment for process, equipment in keys):
        raise ValueError("공정 또는 설비코드가 비어 있는 CSV 행이 있습니다.")
    duplicates = [key for key, count in Counter(keys).items() if count > 1]
    if duplicates:
        raise ValueError(f"중복 공정+설비코드 {len(duplicates)}건")
    return headers, rows, first_source_row


def create_backup(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{db_path.stem}_before_master_data_{stamp}{db_path.suffix}"
    source = sqlite3.connect(str(db_path))
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("백업 DB 무결성 검사 실패")
    finally:
        destination.close()
        source.close()
    return backup_path


def import_master(
    csv_path: Path, db_path: Path, *, apply: bool, backup_dir: Path,
    plant_code: str = "P1",
) -> dict[str, Any]:
    plant_code = normalized_key(plant_code)
    if not plant_code:
        raise ValueError("plant_code is required")
    headers, rows, first_source_row = load_csv(csv_path)
    backup_path = create_backup(db_path, backup_dir) if apply else None
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    now = utc_now()
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("반영 전 DB 무결성 검사 실패")
        before_protected = protected_table_digests(connection)
        before_inspection_state = existing_inspection_state(connection)
        before_keys = existing_master_keys(connection)
        plant_key = normalized_key(plant_code)
        csv_key_set = {
            (
                plant_key,
                normalized_key(row.get("공정")),
                normalized_key(row.get("설비코드")),
            )
            for row in rows
        }
        db_only_keys = set(before_keys) - csv_key_set
        db_only_snapshot = {
            key: tuple(connection.execute(
                """
                SELECT e.*, h.* FROM equipment e
                JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
                WHERE e.equipment_id=?
                """,
                (before_keys[key]["equipment_id"],),
            ).fetchone())
            for key in db_only_keys
        }

        connection.execute("BEGIN IMMEDIATE")
        batch_id = insert_import_batch(connection, csv_path, len(rows), now)
        source_name = csv_path.name
        unit_ids = get_or_create_units(
            connection, sorted({raw_text(r["공정"]) for r in rows}), now, source_name,
            plant_code,
        )
        counters = Counter()
        warning_rows = 0
        for source_row_no, row in enumerate(rows, start=first_source_row):
            warnings: list[str] = []
            unit_id = unit_ids[normalized_key(row["공정"])]
            equipment_id, heat_exchanger_id, inserted = upsert_equipment_and_exchanger(
                connection, row, unit_id, now
            )
            counters["equipment_inserted" if inserted else "equipment_updated"] += 1
            upsert_compliance(connection, heat_exchanger_id, row, now, warnings)
            spec_revision_id, spec_inserted = upsert_spec_revision(
                connection, heat_exchanger_id, row, source_row_no, now, warnings, source_name
            )
            counters["spec_revision_inserted" if spec_inserted else "spec_revision_reused"] += 1
            if spec_inserted:
                side_count, capacity_count = upsert_side_specs_and_capacities(
                    connection, spec_revision_id, row, warnings
                )
            else:
                side_count, capacity_count = 0, 0
            counters["side_specs_loaded"] += side_count
            counters["capacities_loaded"] += capacity_count
            warnings = sorted(set(warnings))
            if warnings:
                warning_rows += 1
            connection.execute(
                """
                INSERT INTO master_heat_exchanger_staging (
                    import_batch_id, source_row_no, process_code, equipment_code, raw_json,
                    validation_status, validation_message, matched_equipment_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    batch_id, source_row_no, raw_text(row["공정"]), raw_text(row["설비코드"]),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                    "LOADED_WITH_WARNINGS" if warnings else "LOADED",
                    "; ".join(warnings) if warnings else None,
                    equipment_id, now,
                ),
            )

        finished = utc_now()
        connection.execute(
            """
            UPDATE import_batch
               SET finished_at=?, status='COMPLETED', loaded_report_count=?, warning_count=?,
                   message=?
             WHERE import_batch_id=?
            """,
            (
                finished, len(rows), warning_rows,
                json.dumps(dict(counters), ensure_ascii=False, sort_keys=True), batch_id,
            ),
        )

        after_protected = protected_table_digests(connection)
        if after_protected != before_protected:
            changed = sorted(set(after_protected) | set(before_protected))
            changed = [name for name in changed if after_protected.get(name) != before_protected.get(name)]
            raise RuntimeError(f"보호 대상 테이블 변경 감지: {', '.join(changed)}")
        after_inspection_state = existing_inspection_state(connection)
        for heat_exchanger_id, state in before_inspection_state.items():
            if after_inspection_state.get(heat_exchanger_id) != state:
                raise RuntimeError(f"기존 검사 관리 상태 변경 감지: heat_exchanger_id={heat_exchanger_id}")
        for key, snapshot in db_only_snapshot.items():
            row_now = connection.execute(
                """
                SELECT e.*, h.* FROM equipment e
                JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
                WHERE e.equipment_id=?
                """,
                (before_keys[key]["equipment_id"],),
            ).fetchone()
            if row_now is None or tuple(row_now) != snapshot:
                raise RuntimeError(f"CSV 미매칭 기존 설비 변경 감지: {key}")
        fk_issues = [tuple(r) for r in connection.execute("PRAGMA foreign_key_check")]
        if fk_issues:
            raise RuntimeError(f"외래키 오류 {len(fk_issues)}건")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("반영 후 DB 무결성 검사 실패")

        result = {
            "mode": "APPLY" if apply else "DRY_RUN",
            "plant_code": plant_code,
            "csv_row_count": len(rows),
            "csv_header_count": len(headers),
            "batch_id": batch_id if apply else None,
            "backup_path": str(backup_path) if backup_path else None,
            "existing_exact_matches": len(csv_key_set & set(before_keys)),
            "new_csv_equipment": len(csv_key_set - set(before_keys)),
            "db_only_preserved": len(db_only_keys),
            "warning_row_count": warning_rows,
            **dict(counters),
            "final_counts": {
                table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                for table in (
                    "process_unit", "equipment", "heat_exchanger", "heat_exchanger_spec_revision",
                    "heat_exchanger_side_spec", "heat_exchanger_capacity",
                    "heat_exchanger_compliance", "master_heat_exchanger_staging", "iris_inspection",
                    "iris_inspection_spec_snapshot", "iris_tube_result",
                )
            },
            "foreign_key_issue_count": 0,
            "integrity_check": "ok",
            "protected_tables_unchanged": True,
            "existing_inspection_states_unchanged": True,
        }
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Master_HeatExchanger CSV while preserving inspection history")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--backup-dir", type=Path, default=APP_DIR / "backups")
    parser.add_argument("--plant-code", default="P1")
    parser.add_argument("--apply", action="store_true", help="Commit changes; default is transactional dry-run")
    args = parser.parse_args()
    result = import_master(
        args.csv.resolve(), args.db.resolve(), apply=args.apply,
        backup_dir=args.backup_dir.resolve(), plant_code=args.plant_code.strip().upper(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
