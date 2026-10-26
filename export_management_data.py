from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path
from typing import Any


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR / "data" / "heat_exchanger_db3.db"
DEFAULT_OUTPUT = (
    APP_DIR
    / "outputs"
    / "heat_exchanger_management_data_20260814.csv"
)


HEADERS = [
    "공정",
    "설비명",
    "공정_설비명키",
    "동일키중복건수",
    "설비코드",
    "교환기코드",
    "공정_설비코드_고유키",
    "설비번호",
    "설비Tag",
    "설치일자",
    "가동_시운전일",
    "제작일자_제작연도",
    "제작사",
    "모델번호",
    "Serial번호",
    "설치위치",
    "담당부서",
    "담당자",
    "RBI대상여부",
    "Tube외경_mm",
    "Tube공칭두께_mm",
    "Tube길이_mm",
    "TubePitch_mm",
    "Pass수",
    "전열면적_m2",
    "설비도면번호",
    "Datasheet번호",
    "Tube교체이력건수",
    "Tube위치변경이력건수",
    "허용Plugging비율_pct",
    "주의감육률_pct",
    "위험감육률_pct",
    "최소허용두께_mm",
    "검사주기_개월",
    "정기보수주기_년",
    "최근정기보수연도",
    "차기정기보수예정연도",
    "PSM유형",
    "PSM유형코드",
    "Shell유체",
    "Head유체",
    "Tube유체",
    "Shell재질",
    "Head재질",
    "Tube재질",
    "열교환기형식_표준코드",
    "열교환기형식_표준명",
    "열교환기형식_원본값",
    "열교환기형식_매핑상태",
    "Tube수량",
    "설치방향",
    "관련P&ID",
    "제작규격",
    "보온여부",
    "변경관리코드",
    "미입력관리항목수",
    "관리항목입력률_pct",
]

MANAGEMENT_HEADERS = HEADERS[8:-2]


QUERY = """
WITH current_spec AS (
    SELECT *
      FROM heat_exchanger_spec_revision
     WHERE is_current=1
),
side_values AS (
    SELECT ss.spec_revision_id,
           MAX(CASE WHEN ss.side_code='SHELL' THEN ss.fluid END) AS shell_fluid,
           MAX(CASE WHEN ss.side_code='HEAD' THEN ss.fluid END) AS head_fluid,
           MAX(CASE WHEN ss.side_code='TUBE' THEN ss.fluid END) AS tube_fluid,
           MAX(CASE WHEN ss.side_code='SHELL' THEN ss.material END) AS shell_material,
           MAX(CASE WHEN ss.side_code='HEAD' THEN ss.material END) AS head_material,
           MAX(CASE WHEN ss.side_code='TUBE' THEN ss.material END) AS tube_material
      FROM heat_exchanger_side_spec ss
     GROUP BY ss.spec_revision_id
),
tube_events AS (
    SELECT b.heat_exchanger_id,
           COUNT(DISTINCT le.lifecycle_event_id) AS lifecycle_event_count,
           COUNT(DISTINCT pe.position_event_id) AS position_event_count
      FROM tube_bundle b
      LEFT JOIN heat_exchanger_tube t ON t.bundle_id=b.bundle_id
      LEFT JOIN tube_lifecycle_event le ON le.tube_id=t.tube_id
      LEFT JOIN tube_position_event pe ON pe.tube_id=t.tube_id
     GROUP BY b.heat_exchanger_id
),
key_counts AS (
    SELECT e.unit_id, e.equipment_name, COUNT(*) AS duplicate_count
      FROM equipment e
     GROUP BY e.unit_id, e.equipment_name
)
SELECT
    u.unit_code AS process_code,
    e.equipment_name,
    kc.duplicate_count,
    e.equipment_code,
    s.exchanger_code,
    e.equipment_number,
    e.equipment_tag,
    e.install_date,
    e.commissioning_date,
    e.manufacturing_date AS manufacturing_date_or_year,
    e.manufacturer,
    e.model_no,
    e.serial_no,
    e.location_desc,
    e.owner_department,
    e.owner_name,
    c.rbi_target,
    s.tube_outer_diameter_mm,
    s.tube_nominal_thickness_mm,
    s.tube_length_mm,
    s.tube_pitch_mm,
    s.pass_count,
    s.heat_transfer_area_m2,
    s.drawing_no,
    s.datasheet_no,
    COALESCE(te.lifecycle_event_count, 0) AS lifecycle_event_count,
    COALESCE(te.position_event_count, 0) AS position_event_count,
    mc.allowable_plugging_percent,
    mc.warning_wall_loss_percent,
    mc.critical_wall_loss_percent,
    mc.minimum_wall_thickness_mm,
    mc.inspection_cycle_months,
    mc.turnaround_cycle_years,
    mc.last_turnaround_year,
    mc.next_turnaround_year,
    c.psm_type_name,
    c.psm_type_code,
    COALESCE(sv.shell_fluid, s.shell_fluid) AS shell_fluid,
    sv.head_fluid,
    COALESCE(sv.tube_fluid, s.tube_fluid) AS tube_fluid,
    COALESCE(sv.shell_material, s.shell_material) AS shell_material,
    sv.head_material,
    COALESCE(sv.tube_material, s.tube_material) AS tube_material,
    h.exchanger_type_code,
    h.exchanger_type_name,
    h.exchanger_type_raw,
    h.type_mapping_status,
    COALESCE(h.exchanger_type_name, h.exchanger_type_raw, h.exchanger_type) AS exchanger_type,
    s.tube_count,
    s.installation_orientation,
    c.related_pid_no,
    c.fabrication_standard,
    c.insulation_required,
    c.management_change_code
FROM equipment e
JOIN process_unit u ON u.unit_id=e.unit_id
JOIN heat_exchanger h ON h.equipment_id=e.equipment_id
JOIN key_counts kc ON kc.unit_id=e.unit_id AND kc.equipment_name=e.equipment_name
LEFT JOIN current_spec s ON s.heat_exchanger_id=h.heat_exchanger_id
LEFT JOIN side_values sv ON sv.spec_revision_id=s.spec_revision_id
LEFT JOIN heat_exchanger_compliance c ON c.heat_exchanger_id=h.heat_exchanger_id
LEFT JOIN heat_exchanger_management_criteria mc
       ON mc.heat_exchanger_id=h.heat_exchanger_id
LEFT JOIN tube_events te ON te.heat_exchanger_id=h.heat_exchanger_id
ORDER BY u.unit_code, e.equipment_name COLLATE NOCASE, e.equipment_code COLLATE NOCASE
"""


def display_boolean(value: Any) -> str:
    if value is None:
        return ""
    return "Y" if bool(value) else "N"


def clean_value(value: Any) -> Any:
    return "" if value is None else value


def build_output_row(row: sqlite3.Row) -> dict[str, Any]:
    process = clean_value(row["process_code"])
    name = clean_value(row["equipment_name"])
    code = clean_value(row["equipment_code"])
    exchanger_code = clean_value(row["exchanger_code"])
    output = {
        "공정": process,
        "설비명": name,
        "공정_설비명키": f"{process}|{name}",
        "동일키중복건수": row["duplicate_count"],
        "설비코드": code,
        "교환기코드": exchanger_code,
        "공정_설비코드_고유키": f"{process}|{code}",
        "설비번호": clean_value(row["equipment_number"]),
        "설비Tag": clean_value(row["equipment_tag"]),
        "설치일자": clean_value(row["install_date"]),
        "가동_시운전일": clean_value(row["commissioning_date"]),
        "제작일자_제작연도": clean_value(row["manufacturing_date_or_year"]),
        "제작사": clean_value(row["manufacturer"]),
        "모델번호": clean_value(row["model_no"]),
        "Serial번호": clean_value(row["serial_no"]),
        "설치위치": clean_value(row["location_desc"]),
        "담당부서": clean_value(row["owner_department"]),
        "담당자": clean_value(row["owner_name"]),
        "RBI대상여부": display_boolean(row["rbi_target"]),
        "Tube외경_mm": clean_value(row["tube_outer_diameter_mm"]),
        "Tube공칭두께_mm": clean_value(row["tube_nominal_thickness_mm"]),
        "Tube길이_mm": clean_value(row["tube_length_mm"]),
        "TubePitch_mm": clean_value(row["tube_pitch_mm"]),
        "Pass수": clean_value(row["pass_count"]),
        "전열면적_m2": clean_value(row["heat_transfer_area_m2"]),
        "설비도면번호": clean_value(row["drawing_no"]),
        "Datasheet번호": clean_value(row["datasheet_no"]),
        "Tube교체이력건수": row["lifecycle_event_count"],
        "Tube위치변경이력건수": row["position_event_count"],
        "허용Plugging비율_pct": clean_value(row["allowable_plugging_percent"]),
        "주의감육률_pct": clean_value(row["warning_wall_loss_percent"]),
        "위험감육률_pct": clean_value(row["critical_wall_loss_percent"]),
        "최소허용두께_mm": clean_value(row["minimum_wall_thickness_mm"]),
        "검사주기_개월": clean_value(row["inspection_cycle_months"]),
        "정기보수주기_년": clean_value(row["turnaround_cycle_years"]),
        "최근정기보수연도": clean_value(row["last_turnaround_year"]),
        "차기정기보수예정연도": clean_value(row["next_turnaround_year"]),
        "PSM유형": clean_value(row["psm_type_name"]),
        "PSM유형코드": clean_value(row["psm_type_code"]),
        "Shell유체": clean_value(row["shell_fluid"]),
        "Head유체": clean_value(row["head_fluid"]),
        "Tube유체": clean_value(row["tube_fluid"]),
        "Shell재질": clean_value(row["shell_material"]),
        "Head재질": clean_value(row["head_material"]),
        "Tube재질": clean_value(row["tube_material"]),
        "열교환기형식_표준코드": clean_value(row["exchanger_type_code"]),
        "열교환기형식_표준명": clean_value(row["exchanger_type_name"]),
        "열교환기형식_원본값": clean_value(row["exchanger_type_raw"]),
        "열교환기형식_매핑상태": clean_value(row["type_mapping_status"]),
        "Tube수량": clean_value(row["tube_count"]),
        "설치방향": clean_value(row["installation_orientation"]),
        "관련P&ID": clean_value(row["related_pid_no"]),
        "제작규격": clean_value(row["fabrication_standard"]),
        "보온여부": display_boolean(row["insulation_required"]),
        "변경관리코드": clean_value(row["management_change_code"]),
    }
    missing = sum(output[header] == "" for header in MANAGEMENT_HEADERS)
    output["미입력관리항목수"] = missing
    output["관리항목입력률_pct"] = round(
        (len(MANAGEMENT_HEADERS) - missing) * 100 / len(MANAGEMENT_HEADERS), 1
    )
    return output


def export_management_data(db_path: Path, output_path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [build_output_row(row) for row in connection.execute(QUERY)]
    finally:
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, output_path)
    return {
        "output": str(output_path),
        "row_count": len(rows),
        "column_count": len(HEADERS),
        "duplicate_process_name_groups": len(
            {(row["공정"], row["설비명"]) for row in rows if row["동일키중복건수"] > 1}
        ),
        "unique_process_code_keys": len(
            {(row["공정"], row["설비코드"]) for row in rows}
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export heat exchanger management data to CSV")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(export_management_data(args.db.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
