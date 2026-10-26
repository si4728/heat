from __future__ import annotations

from .domain.tube_status import normalize_tube_status

from datetime import datetime
from io import BytesIO
from pathlib import Path
from collections import OrderedDict
import subprocess
import sys
import tempfile
from threading import RLock
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.table import Table, TableStyleInfo
from sqlalchemy import text

from .iris_v2_database import create_v2_engine


NAVY = "102B36"
TEAL = "007B78"
LIGHT_TEAL = "D9F2EF"
LIGHT_BLUE = "EAF2F5"
LIGHT_GRAY = "F3F6F7"
WHITE = "FFFFFF"
WARNING = "FDE8C8"
DANGER = "FDE2E1"
PURPLE = "EFE8FF"
THIN_GRAY = Side(style="thin", color="DCE4E8")

STATUS_LABELS = {
    "IN_SERVICE": "사용 중",
    "ACTIVE": "사용 중",
    "PLUGGED": "폐쇄",
}


EXCHANGER_SQL = """
WITH spec AS (
  SELECT * FROM (
    SELECT s.*, ROW_NUMBER() OVER (
      PARTITION BY s.heat_exchanger_id ORDER BY s.is_current DESC, s.revision_no DESC
    ) AS rn
    FROM heat_exchanger_spec_revision s
  ) ranked_specs WHERE rn = 1
), tube_stats AS (
  SELECT b.heat_exchanger_id,
         MAX(b.expected_tube_count) AS expected_tube_count,
         COUNT(t.tube_id) AS managed_tube_count,
         SUM(CASE WHEN UPPER(COALESCE(t.current_status, 'IN_SERVICE')) IN ('ACTIVE','IN_SERVICE','UNUSED') THEN 1 ELSE 0 END) AS in_service_count,
         SUM(CASE WHEN UPPER(t.current_status) = 'PLUGGED' THEN 1 ELSE 0 END) AS plugged_count
  FROM tube_bundle b LEFT JOIN heat_exchanger_tube t ON t.bundle_id = b.bundle_id
  GROUP BY b.heat_exchanger_id
), inspection_stats AS (
  SELECT heat_exchanger_id, COUNT(*) AS inspection_count,
         MIN(report_date) AS first_inspection_date, MAX(report_date) AS latest_inspection_date,
         MAX(total_tube_count_reported) AS reported_total_tubes
  FROM iris_inspection WHERE heat_exchanger_id IS NOT NULL GROUP BY heat_exchanger_id
), result_stats AS (
  SELECT i.heat_exchanger_id, COUNT(r.iris_tube_result_id) AS result_count,
         MAX(r.wall_loss_percent) AS max_wall_loss_percent,
         MIN(r.minimum_wall_thickness_mm) AS min_wall_thickness_mm
  FROM iris_inspection i JOIN iris_tube_result r ON r.iris_inspection_id = i.iris_inspection_id
  GROUP BY i.heat_exchanger_id
)
SELECT hx.heat_exchanger_id, p.plant_code, u.unit_code, e.equipment_code, e.equipment_name,
       e.status AS equipment_status, hx.exchanger_type_code, hx.exchanger_type_name,
       hx.exchanger_type_raw, hx.type_mapping_status, hx.service_name,
       hx.iris_applicability, hx.inspection_lifecycle_status, hx.tube_master_status,
       e.location_desc, e.manufacturer, e.model_no, e.serial_no, e.install_date,
       e.criticality_grade, e.is_critical, e.owner_department, e.owner_name,
       s.revision_no, s.tube_material, s.tube_count AS design_tube_count,
       s.tube_outer_diameter_mm, s.tube_nominal_thickness_mm, s.tube_length_mm,
       s.bundle_type, s.pass_count, s.tube_pitch_mm,
       COALESCE(ts.expected_tube_count, ist.reported_total_tubes, s.tube_count) AS expected_tube_count,
       COALESCE(ts.managed_tube_count, 0) AS managed_tube_count,
       COALESCE(ts.in_service_count, 0) AS in_service_count,
       COALESCE(ts.plugged_count, 0) AS plugged_count,
       COALESCE(ist.inspection_count, 0) AS inspection_count,
       ist.first_inspection_date, ist.latest_inspection_date,
       COALESCE(rs.result_count, 0) AS tube_result_count,
       rs.max_wall_loss_percent, rs.min_wall_thickness_mm,
       mc.allowable_plugging_percent, mc.warning_wall_loss_percent,
       mc.critical_wall_loss_percent, mc.inspection_cycle_months,
       e.manufacturing_date, e.commissioning_date,
       hx.remarks, s.exchanger_code
FROM heat_exchanger hx
JOIN equipment e ON e.equipment_id = hx.equipment_id
JOIN process_unit u ON u.unit_id = e.unit_id
JOIN plant p ON p.plant_id = u.plant_id
LEFT JOIN spec s ON s.heat_exchanger_id = hx.heat_exchanger_id
LEFT JOIN tube_stats ts ON ts.heat_exchanger_id = hx.heat_exchanger_id
LEFT JOIN inspection_stats ist ON ist.heat_exchanger_id = hx.heat_exchanger_id
LEFT JOIN result_stats rs ON rs.heat_exchanger_id = hx.heat_exchanger_id
LEFT JOIN heat_exchanger_management_criteria mc ON mc.heat_exchanger_id = hx.heat_exchanger_id
ORDER BY p.plant_code, u.unit_code, e.equipment_code
"""


TUBE_SQL = """
WITH result_agg AS (
  SELECT r.tube_id, COUNT(*) AS inspection_result_count,
         MIN(i.report_date) AS first_inspection_date, MAX(i.report_date) AS latest_inspection_date,
         MAX(r.wall_loss_percent) AS max_wall_loss_percent,
         MIN(r.minimum_wall_thickness_mm) AS minimum_wall_thickness_mm
  FROM iris_tube_result r JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
  GROUP BY r.tube_id
), latest_result AS (
  SELECT * FROM (
    SELECT r.tube_id, i.report_date, c.campaign_year, r.minimum_wall_thickness_mm AS latest_thickness_mm,
           r.wall_loss_percent AS latest_wall_loss_percent, r.wall_loss_depth_mm AS latest_wall_loss_depth_mm,
           r.corrosion_type AS latest_corrosion_type,
           ROW_NUMBER() OVER (PARTITION BY r.tube_id ORDER BY i.report_date DESC, r.iris_tube_result_id DESC) AS rn
    FROM iris_tube_result r
    JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
    JOIN inspection_campaign c ON c.campaign_id = i.campaign_id
  ) ranked_specs WHERE rn = 1
), event_stats AS (
  SELECT tube_id, COUNT(*) AS status_change_count
  FROM tube_lifecycle_event GROUP BY tube_id
)
SELECT t.tube_id, p.plant_code, u.unit_code, e.equipment_code, b.bundle_code,
       b.lifecycle_no AS bundle_lifecycle_no, t.tube_no, t.row_no, t.column_no,
       t.layout_zone, t.pass_no, t.position_x, t.position_y, t.position_z,
       t.lifecycle_no AS tube_lifecycle_no, t.current_status, t.installed_at, t.plugging_date,
       CASE WHEN COALESCE(ra.inspection_result_count, 0) > 0 THEN '검사' ELSE '미검사' END AS inspection_status,
       COALESCE(ra.inspection_result_count, 0) AS inspection_result_count,
       ra.first_inspection_date, ra.latest_inspection_date,
       lr.campaign_year AS latest_inspection_year, lr.latest_thickness_mm,
       lr.latest_wall_loss_percent, lr.latest_wall_loss_depth_mm, lr.latest_corrosion_type,
       ra.minimum_wall_thickness_mm AS historical_minimum_thickness_mm,
       ra.max_wall_loss_percent AS historical_max_wall_loss_percent,
       COALESCE(es.status_change_count, 0) AS status_change_count,
       t.source_tube_label,
       (SELECT s.exchanger_code FROM heat_exchanger_spec_revision s
         WHERE s.heat_exchanger_id=hx.heat_exchanger_id AND s.is_current=1) AS exchanger_code
FROM heat_exchanger_tube t
JOIN tube_bundle b ON b.bundle_id = t.bundle_id
JOIN heat_exchanger hx ON hx.heat_exchanger_id = b.heat_exchanger_id
JOIN equipment e ON e.equipment_id = hx.equipment_id
JOIN process_unit u ON u.unit_id = e.unit_id
JOIN plant p ON p.plant_id = u.plant_id
LEFT JOIN result_agg ra ON ra.tube_id = t.tube_id
LEFT JOIN latest_result lr ON lr.tube_id = t.tube_id
LEFT JOIN event_stats es ON es.tube_id = t.tube_id
ORDER BY p.plant_code, u.unit_code, e.equipment_code, b.bundle_code, t.row_no, t.column_no, t.tube_no
"""


RESULT_SQL = """
SELECT r.iris_tube_result_id, p.plant_code, u.unit_code, e.equipment_code,
       c.campaign_year, i.report_date, i.report_number, COALESCE(s.scope_code, 'ALL') AS inspection_scope,
       t.tube_id, t.tube_no, t.row_no, t.column_no, t.current_status,
       r.minimum_wall_thickness_mm, r.wall_loss_percent, r.wall_loss_depth_mm,
       r.location_mm, r.location_source_unit, r.corrosion_type,
       r.design_wall_thickness_mm, r.defect_code, r.reported_depth_percent,
       r.remark, r.result_status, r.quality_status, r.source_page,
       (SELECT sr.exchanger_code FROM heat_exchanger_spec_revision sr
         WHERE sr.heat_exchanger_id=hx.heat_exchanger_id AND sr.is_current=1) AS exchanger_code
FROM iris_tube_result r
JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
JOIN inspection_campaign c ON c.campaign_id = i.campaign_id
LEFT JOIN inspection_scope s ON s.inspection_scope_id = i.inspection_scope_id
JOIN heat_exchanger_tube t ON t.tube_id = r.tube_id
JOIN tube_bundle b ON b.bundle_id = t.bundle_id
JOIN heat_exchanger hx ON hx.heat_exchanger_id = b.heat_exchanger_id
JOIN equipment e ON e.equipment_id = hx.equipment_id
JOIN process_unit u ON u.unit_id = e.unit_id
JOIN plant p ON p.plant_id = u.plant_id
ORDER BY c.campaign_year, u.unit_code, e.equipment_code, i.report_date, t.tube_no
"""


INSPECTION_SQL = """
SELECT i.iris_inspection_id, p.plant_code, u.unit_code, e.equipment_code,
       c.campaign_year, i.inspection_date, i.report_date, i.report_number,
       COALESCE(b.bundle_code, i.source_bundle_code, 'MAIN') AS bundle_code,
       COALESCE(s.scope_code, i.source_scope_code, 'ALL') AS scope_code,
       i.installation_or_replacement_date_raw,
       i.installation_or_replacement_date_precision,
       setup.process_code, setup.production_line, setup.shell_fluid,
       setup.tube_fluid, setup.tube_type,
       provider.provider_code, provider.provider_name, provider.provider_local_name,
       execution.inspection_company_source_text,
       execution.inspection_company_brand, execution.source_page AS provider_source_page,
       i.total_tube_count_reported, i.inspected_tube_count_reported,
       i.extracted_tube_result_count, i.reported_minimum_thickness_mm,
       i.reported_maximum_wall_loss_percent, i.reported_average_wall_loss_percent,
       i.report_status, i.extraction_status,
       (SELECT sr.exchanger_code FROM heat_exchanger_spec_revision sr
         WHERE sr.heat_exchanger_id=hx.heat_exchanger_id AND sr.is_current=1) AS exchanger_code
FROM iris_inspection i
JOIN inspection_campaign c ON c.campaign_id = i.campaign_id
JOIN heat_exchanger hx ON hx.heat_exchanger_id = i.heat_exchanger_id
JOIN equipment e ON e.equipment_id = hx.equipment_id
JOIN process_unit u ON u.unit_id = e.unit_id
JOIN plant p ON p.plant_id = u.plant_id
LEFT JOIN tube_bundle b ON b.bundle_id = i.bundle_id
LEFT JOIN inspection_scope s ON s.inspection_scope_id = i.inspection_scope_id
LEFT JOIN iris_setup_snapshot setup ON setup.iris_inspection_id = i.iris_inspection_id
LEFT JOIN inspection_execution_snapshot execution
       ON execution.iris_inspection_id = i.iris_inspection_id
LEFT JOIN inspection_provider provider
       ON provider.inspection_provider_id = execution.inspection_provider_id
ORDER BY c.campaign_year, u.unit_code, e.equipment_code, i.report_sequence
"""


EVENT_SQL = """
SELECT ev.lifecycle_event_id, p.plant_code, u.unit_code, e.equipment_code,
       t.tube_id, t.tube_no, ev.event_type, ev.reason,
       (SELECT sr.exchanger_code FROM heat_exchanger_spec_revision sr
         WHERE sr.heat_exchanger_id=hx.heat_exchanger_id AND sr.is_current=1) AS exchanger_code
FROM tube_lifecycle_event ev
JOIN heat_exchanger_tube t ON t.tube_id = ev.tube_id
JOIN tube_bundle b ON b.bundle_id = t.bundle_id
JOIN heat_exchanger hx ON hx.heat_exchanger_id = b.heat_exchanger_id
JOIN equipment e ON e.equipment_id = hx.equipment_id
JOIN process_unit u ON u.unit_id = e.unit_id
JOIN plant p ON p.plant_id = u.plant_id
ORDER BY ev.lifecycle_event_id DESC
"""


EXCHANGER_HEADERS = [
    "열교환기 ID", "공장", "공정", "설비번호", "설비명", "설비 상태",
    "형식 표준코드", "형식 표준명", "형식 원본값", "형식 매핑상태", "서비스",
    "IRIS 적용", "검사 생애주기", "튜브 마스터", "설치 위치", "제조사", "모델", "Serial No.",
    "설치일", "중요도", "중요설비", "담당부서", "담당자", "사양 Revision", "튜브 재질",
    "설계 튜브 수", "외경(mm)", "공칭두께(mm)", "길이(mm)", "Bundle 유형", "Pass 수",
    "Tube Pitch(mm)", "전체/예상 튜브", "DB 튜브", "사용 중", "폐쇄", "검사 횟수",
    "최초 검사일", "최근 검사일", "튜브 결과 수", "최대 감육률(%)", "최소 두께(mm)",
    "허용 Plugging(%)", "주의 감육률(%)", "위험 감육률(%)", "검사 주기(개월)", "비고",
]
EXCHANGER_HEADERS[-1:-1] = ["제작일자", "최초 가동일"]
EXCHANGER_HEADERS.append("열교환기코드")

TUBE_HEADERS = [
    "Tube ID", "공장", "공정", "설비번호", "Bundle", "Bundle Lifecycle", "튜브번호", "Row", "Column",
    "Layout Zone", "Pass", "X", "Y", "Z", "Tube Lifecycle", "운전상태 코드", "운전상태", "설치일",
    "Plugging date", "검사상태", "검사 결과 수", "최초 검사일", "최근 검사일", "최근 검사연도",
    "최근 최소두께(mm)", "최근 감육률(%)", "최근 감육깊이(mm)", "최근 부식유형",
    "이력 최소두께(mm)", "이력 최대감육률(%)", "상태 변경 수", "원본 튜브 라벨",
]
TUBE_HEADERS.append("열교환기코드")

RESULT_HEADERS = [
    "결과 ID", "공장", "공정", "설비번호", "검사연도", "검사일", "보고서번호", "검사범위",
    "Tube ID", "튜브번호", "Row", "Column", "운전상태", "최소두께(mm)", "감육률(%)",
    "감육깊이(mm)", "위치(mm)", "위치 원문단위", "부식유형", "설계두께(mm)",
    "결함코드", "보고 손상률(%)", "튜브 비고", "결과상태", "품질상태", "원본 페이지",
]
RESULT_HEADERS.append("열교환기코드")

INSPECTION_HEADERS = [
    "검사 ID", "공장", "공정", "설비번호", "검사연도", "검사일", "보고일",
    "보고서번호", "Bundle", "Scope", "설치·교체일자 원문", "날짜 정밀도",
    "보고 공정코드", "보고 생산라인", "Shell 유체", "Tube 유체", "Tube 형식",
    "업체코드", "업체명", "업체 현지명", "업체 원문", "업체 브랜드", "업체 출처 페이지",
    "보고 전체튜브", "보고 검사튜브", "추출 결과", "최소두께(mm)", "최대 감육률(%)",
    "평균 감육률(%)", "보고서 상태", "추출 상태",
]
INSPECTION_HEADERS.append("열교환기코드")

EVENT_HEADERS = ["이력 ID", "공장", "공정", "설비번호", "Tube ID", "튜브번호", "변경유형", "변경사유"]
EVENT_HEADERS.append("열교환기코드")


def _rows(connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(text(sql)).mappings()]


def _excel_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return value
    return value


def _style_data_sheet(ws, title: str, headers: list[str], rows: Iterable[list[Any]], table_name: str) -> None:
    ws.sheet_view.showGridLines = False
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    title_cell = ws.cell(1, 1, title)
    title_cell.fill = PatternFill("solid", fgColor=NAVY)
    title_cell.font = Font(color=WHITE, bold=True, size=16)
    title_cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 32
    ws.cell(2, 1, f"생성일시: {datetime.now():%Y-%m-%d %H:%M:%S}")
    ws.cell(2, 1).font = Font(color="647581", italic=True, size=10)
    for column, header in enumerate(headers, 1):
        cell = ws.cell(4, column, header)
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(color=WHITE, bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(bottom=THIN_GRAY)
    row_count = 0
    top_alignment = Alignment(vertical="top", wrap_text=False)
    wrapped_alignment = Alignment(vertical="top", wrap_text=True)
    stripe_fill = PatternFill("solid", fgColor="F8FAFB")
    for row_count, values in enumerate(rows, 1):
        for column, value in enumerate(values, 1):
            cell = ws.cell(row_count + 4, column, _excel_value(value))
            cell.alignment = wrapped_alignment if column in (8, 28, len(headers)) else top_alignment
            if row_count % 2 == 0:
                cell.fill = stripe_fill
    last_row = max(row_count + 4, 4)
    if row_count:
        table = Table(displayName=table_name, ref=f"A4:{ws.cell(4, len(headers)).column_letter}{last_row}")
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False)
        ws.add_table(table)
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{ws.cell(4, len(headers)).column_letter}{last_row}"
    for column in range(1, len(headers) + 1):
        values = [str(ws.cell(row, column).value or "") for row in range(4, min(last_row, 80) + 1)]
        width = min(max(max((len(value) for value in values), default=8) + 2, 10), 32)
        if headers[column - 1] in ("비고", "최근 부식유형", "변경사유"):
            width = 38
        ws.column_dimensions[ws.cell(4, column).column_letter].width = width


def _apply_formats(wb: Workbook) -> None:
    date_headers = {"설치일", "최초 검사일", "최근 검사일", "Plugging date", "검사일", "보고일"}
    date_headers.update({"제작일자", "최초 가동일"})
    number2_headers = {"외경(mm)", "공칭두께(mm)", "Tube Pitch(mm)", "최대 감육률(%)", "최소 두께(mm)",
                       "허용 Plugging(%)", "주의 감육률(%)", "위험 감육률(%)", "최근 최소두께(mm)",
                       "최근 감육률(%)", "최근 감육깊이(mm)", "이력 최소두께(mm)", "이력 최대감육률(%)",
                       "감육률(%)", "감육깊이(mm)", "위치(mm)"}
    number2_headers.update({"설계두께(mm)", "보고 손상률(%)", "평균 감육률(%)"})
    for ws in [wb["열교환기"], wb["튜브"], wb["검사보고서"], wb["검사이력"], wb["상태변경이력"]]:
        headers = {cell.value: cell.column for cell in ws[4]}
        for header in date_headers & headers.keys():
            for cell in ws.iter_cols(min_col=headers[header], max_col=headers[header], min_row=5, max_row=ws.max_row):
                for item in cell:
                    item.number_format = "yyyy-mm-dd"
        for header in number2_headers & headers.keys():
            for cell in ws.iter_cols(min_col=headers[header], max_col=headers[header], min_row=5, max_row=ws.max_row):
                for item in cell:
                    item.number_format = "0.00"

    tube = wb["튜브"]
    status_col = next(cell.column_letter for cell in tube[4] if cell.value == "운전상태")
    inspection_col = next(cell.column_letter for cell in tube[4] if cell.value == "검사상태")
    loss_col = next(cell.column_letter for cell in tube[4] if cell.value == "최근 감육률(%)")
    status_range = f"{status_col}5:{status_col}{tube.max_row}"
    tube.conditional_formatting.add(status_range, FormulaRule(formula=[f'${status_col}5="폐쇄"'], fill=PatternFill("solid", fgColor="D9DEE1")))
    tube.conditional_formatting.add(status_range, FormulaRule(formula=[f'${status_col}5="사용 중"'], fill=PatternFill("solid", fgColor=LIGHT_TEAL)))
    tube.conditional_formatting.add(f"{inspection_col}5:{inspection_col}{tube.max_row}",
                                    FormulaRule(formula=[f'${inspection_col}5="미검사"'], fill=PatternFill("solid", fgColor=LIGHT_GRAY)))
    tube.conditional_formatting.add(f"{loss_col}5:{loss_col}{tube.max_row}",
                                    CellIsRule(operator="greaterThanOrEqual", formula=["40"], fill=PatternFill("solid", fgColor=DANGER)))
    tube.conditional_formatting.add(f"{loss_col}5:{loss_col}{tube.max_row}",
                                    CellIsRule(operator="between", formula=["20", "39.9999"], fill=PatternFill("solid", fgColor=WARNING)))


def _build_summary(wb: Workbook) -> None:
    ws = wb["요약"]
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:F1")
    ws["A1"] = "IRIS 열교환기·튜브 DB Export"
    ws["A1"].fill = PatternFill("solid", fgColor=NAVY)
    ws["A1"].font = Font(color=WHITE, bold=True, size=18)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 38
    ws["A2"] = f"DB 기준 생성일시: {datetime.now():%Y-%m-%d %H:%M:%S}"
    ws["A2"].font = Font(color="647581", italic=True)
    ws["A4"], ws["B4"] = "구분", "수량"
    for row, label in enumerate(
        ["열교환기", "DB 튜브", "튜브 검사 결과", "사용 중", "폐쇄", "미검사 튜브"], 5
    ):
        ws.cell(row, 1, label)
    ws["B5"] = "=COUNTA('열교환기'!$A$5:$A$2000)"
    ws["B6"] = "=COUNTA('튜브'!$A$5:$A$50000)"
    ws["B7"] = "=COUNTA('검사이력'!$A$5:$A$100000)"
    ws["B8"] = '=COUNTIF(\'튜브\'!$Q$5:$Q$50000,"사용 중")'
    ws["B9"] = '=COUNTIF(\'튜브\'!$Q$5:$Q$50000,"폐쇄")'
    ws["B10"] = '=COUNTIF(\'튜브\'!$T$5:$T$50000,"미검사")'
    for cell in ws["A4:B4"][0]:
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(color=WHITE, bold=True)
    for row in range(5, 11):
        ws.cell(row, 1).fill = PatternFill("solid", fgColor=LIGHT_BLUE)
        ws.cell(row, 2).number_format = "#,##0"
        ws.cell(row, 1).border = ws.cell(row, 2).border = Border(bottom=THIN_GRAY)
    for column, value in enumerate(["상태 기준", "코드", "설명"], 4):
        ws.cell(4, column, value)
    status_rows = [
        ["운전", "IN_SERVICE", "현재 사용 중인 물리 튜브"],
        ["운전", "PLUGGED", "폐쇄 처리된 튜브"],
        ["검사", "검사/미검사", "검사 결과 존재 여부로 자동 판정"],
    ]
    for row, values in enumerate(status_rows, 5):
        for column, value in enumerate(values, 4):
            ws.cell(row, column, value)
    for cell in ws["D4:F4"][0]:
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.font = Font(color=WHITE, bold=True)
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 4
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 18
    ws.column_dimensions["F"].width = 34
    chart = BarChart()
    chart.type = "col"
    chart.title = "튜브 운전 상태"
    chart.y_axis.title = "튜브 수"
    chart.add_data(Reference(ws, min_col=2, min_row=8, max_row=10), titles_from_data=False)
    chart.set_categories(Reference(ws, min_col=1, min_row=8, max_row=10))
    chart.height = 7
    chart.width = 12
    chart.legend = None
    ws.add_chart(chart, "A14")
    ws.freeze_panes = "A4"


def build_heat_exchanger_export(db_path: str | Path) -> BytesIO:
    engine = create_v2_engine(db_path)
    try:
        with engine.connect() as connection:
            # sqlite3 legacy mode does not start a transaction for SELECT.
            # Pin all five sheets to one snapshot, then release it before formatting.
            connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            exchangers = _rows(connection, EXCHANGER_SQL)
            tubes = _rows(connection, TUBE_SQL)
            inspections = _rows(connection, INSPECTION_SQL)
            results = _rows(connection, RESULT_SQL)
            events = _rows(connection, EVENT_SQL)
    finally:
        engine.dispose()

    wb = Workbook()
    summary = wb.active
    summary.title = "요약"
    exchanger_sheet = wb.create_sheet("열교환기")
    tube_sheet = wb.create_sheet("튜브")
    inspection_sheet = wb.create_sheet("검사보고서")
    result_sheet = wb.create_sheet("검사이력")
    event_sheet = wb.create_sheet("상태변경이력")
    wb.calculation.fullCalcOnLoad = True
    wb.calculation.forceFullCalc = True
    wb.calculation.calcMode = "auto"

    exchanger_rows = [[row[key] for key in row] for row in exchangers]
    tube_rows = []
    for row in tubes:
        values = list(row.values())
        status_code = normalize_tube_status(row["current_status"])
        if status_code == "ACTIVE":
            status_code = "IN_SERVICE"
        values[15] = status_code
        values.insert(16, STATUS_LABELS.get(status_code, status_code))
        tube_rows.append(values)
    result_rows = []
    for row in results:
        values = list(row.values())
        status_code = normalize_tube_status(row["current_status"])
        values[12] = STATUS_LABELS.get(status_code, status_code)
        result_rows.append(values)
    event_rows = [list(row.values()) for row in events]
    inspection_rows = [list(row.values()) for row in inspections]

    _style_data_sheet(exchanger_sheet, "열교환기 마스터 및 검사 요약", EXCHANGER_HEADERS, exchanger_rows, "ExchangerTable")
    _style_data_sheet(tube_sheet, "열교환기별 물리 튜브 및 최신 검사 상태", TUBE_HEADERS, tube_rows, "TubeTable")
    _style_data_sheet(inspection_sheet, "IRIS 검사보고서 및 수행정보", INSPECTION_HEADERS, inspection_rows, "InspectionTable")
    _style_data_sheet(result_sheet, "튜브별 전체 IRIS 검사 이력", RESULT_HEADERS, result_rows, "InspectionResultTable")
    _style_data_sheet(event_sheet, "튜브 운전 상태 변경 이력", EVENT_HEADERS, event_rows, "TubeStatusEventTable")
    _apply_formats(wb)
    _build_summary(wb)

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


_export_lock = RLock()
_export_cache = OrderedDict()


def _generate_export_workbook(path: Path) -> BytesIO:
    """Keep CPU-heavy openpyxl work outside the web server's Python process."""
    with tempfile.TemporaryDirectory(prefix='iris_excel_') as directory:
        destination = Path(directory) / 'export.xlsx'
        subprocess.run([sys.executable, '-m', 'iris2.excel_export_worker',
                        '--db', str(path), '--output', str(destination)],
                       cwd=Path(__file__).resolve().parent.parent,
                       check=True, timeout=300, capture_output=True,
                       **({'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}))
        return BytesIO(destination.read_bytes())


def clear_heat_exchanger_export_cache() -> None:
    with _export_lock:
        _export_cache.clear()


def _database_revision():
    from .database import get_engine
    with get_engine().connect() as connection:
        return int(connection.exec_driver_sql("SELECT COALESCE(SUM(revision),0) FROM iris2_database_revision").scalar())


def get_heat_exchanger_export(db_path: str | Path) -> BytesIO:
    """Independent streams, one generator, transactional DB-trigger revision invalidation."""
    with _export_lock:
        version=_database_revision()
        entry=_export_cache.get('mariadb')
        if entry is not None and entry['version']==version:
            return BytesIO(entry['payload'])
        _export_cache.clear()
        output=_generate_export_workbook(Path(db_path))
        payload=output.getvalue()
        if _database_revision()==version:
            _export_cache['mariadb']={'version':version,'payload':payload}
        return BytesIO(payload)
