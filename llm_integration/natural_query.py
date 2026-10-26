"""Safe Korean natural-language lookup over an allowlisted read-only query."""

from __future__ import annotations

import re
from iris2 import dbapi as db
from pathlib import Path
from typing import Any

from iris2.hx_configuration import DB_PATH


MAX_QUERY_LENGTH = 200
MAX_RESULTS = 50


def parse_query(text: str) -> dict[str, Any]:
    query = " ".join(str(text or "").strip().split())
    if not query:
        return {"query": "", "intent": "HELP", "filters": {}, "description": "조회 문장을 입력하세요."}
    if len(query) > MAX_QUERY_LENGTH:
        raise ValueError(f"조회 문장은 {MAX_QUERY_LENGTH}자 이하여야 합니다.")
    filters: dict[str, Any] = {}
    code_match = re.search(r"(?<!\d)(\d{6,10})(?!\d)", query)
    if code_match:
        filters["equipment_code"] = code_match.group(1)
    loss_match = re.search(
        r"(?:감육률?|wall\s*loss)[^\d]{0,12}(\d+(?:\.\d+)?)\s*%?\s*(이상|초과|이하|미만)?",
        query, re.IGNORECASE,
    )
    if loss_match:
        value = float(loss_match.group(1))
        if not 0 <= value <= 100:
            raise ValueError("감육률 조건은 0~100% 범위여야 합니다.")
        filters["wall_loss_percent"] = value
        filters["comparison"] = loss_match.group(2) or "이상"
    if any(word in query.lower() for word in ("고위험", "위험", "우선", "hotspot", "핫스팟")):
        filters["high_risk"] = True
    if "검사" in query and any(word in query for word in ("없", "미검사", "미실시")):
        filters["never_inspected"] = True
    filters["latest_first"] = any(word in query for word in ("최근", "최신", "마지막"))
    if not filters:
        return {"query": query, "intent": "EQUIPMENT_SEARCH", "filters": {"keyword": query}, "description": f"설비코드·설비명에서 ‘{query}’ 검색"}
    parts = []
    if filters.get("equipment_code"):
        parts.append(f"설비코드 {filters['equipment_code']}")
    if "wall_loss_percent" in filters:
        parts.append(f"최대 감육률 {filters['wall_loss_percent']:g}% {filters['comparison']}")
    if filters.get("high_risk"):
        parts.append("고위험(최대 감육률 30% 이상)")
    if filters.get("never_inspected"):
        parts.append("검사 이력 없음")
    return {"query": query, "intent": "FILTERED_SEARCH", "filters": filters, "description": " · ".join(parts)}


def execute_query(parsed: dict[str, Any], database: Path = DB_PATH) -> list[dict[str, Any]]:
    filters = parsed.get("filters") or {}
    if parsed.get("intent") == "HELP":
        return []
    sql = """
        SELECT hx.heat_exchanger_id, e.equipment_code, e.equipment_name,
               p.plant_code, u.unit_code, hx.service_name,
               hx.inspection_lifecycle_status,
               COUNT(DISTINCT i.iris_inspection_id) AS inspection_count,
               MAX(COALESCE(i.inspection_date, i.report_date)) AS latest_inspection_date,
               MAX(r.wall_loss_percent) AS maximum_wall_loss_percent
          FROM heat_exchanger hx
          JOIN equipment e ON e.equipment_id=hx.equipment_id
          JOIN process_unit u ON u.unit_id=e.unit_id
          JOIN plant p ON p.plant_id=u.plant_id
          LEFT JOIN iris_inspection i ON i.heat_exchanger_id=hx.heat_exchanger_id
                                     AND i.superseded_by_inspection_id IS NULL
          LEFT JOIN iris_tube_result r ON r.iris_inspection_id=i.iris_inspection_id
         WHERE 1=1
    """
    parameters: list[Any] = []
    if filters.get("equipment_code"):
        sql += " AND e.equipment_code=?"
        parameters.append(filters["equipment_code"])
    if filters.get("keyword"):
        sql += " AND (e.equipment_code LIKE ? OR e.equipment_name LIKE ? OR hx.service_name LIKE ?)"
        pattern = f"%{filters['keyword']}%"
        parameters.extend([pattern, pattern, pattern])
    sql += " GROUP BY hx.heat_exchanger_id, e.equipment_code, e.equipment_name, p.plant_code, u.unit_code, hx.service_name, hx.inspection_lifecycle_status"
    having = []
    if filters.get("never_inspected"):
        having.append("COUNT(DISTINCT i.iris_inspection_id)=0")
    if "wall_loss_percent" in filters:
        operators = {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}
        having.append(f"MAX(r.wall_loss_percent) {operators[filters['comparison']]} ?")
        parameters.append(filters["wall_loss_percent"])
    if filters.get("high_risk"):
        having.append("MAX(r.wall_loss_percent) >= 30")
    if having:
        sql += " HAVING " + " AND ".join(having)
    sql += " ORDER BY " + (
        "latest_inspection_date DESC, maximum_wall_loss_percent DESC" if filters.get("latest_first")
        else "maximum_wall_loss_percent DESC, e.equipment_code"
    ) + " LIMIT ?"
    parameters.append(MAX_RESULTS)
    connection = db.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = db.Row
    try:
        return [dict(row) for row in connection.execute(sql, parameters)]
    finally:
        connection.close()


def natural_language_search(text: str, database: Path = DB_PATH) -> dict[str, Any]:
    parsed = parse_query(text)
    rows = execute_query(parsed, database)
    return {**parsed, "rows": rows, "result_count": len(rows), "truncated": len(rows) == MAX_RESULTS}
