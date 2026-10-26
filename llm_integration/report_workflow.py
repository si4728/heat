"""Evidence-bound report generation and validation for local LLM output."""

from __future__ import annotations

import hashlib
import json
from iris2 import dbapi as db
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from iris2.hx_configuration import APP_DIR, DB_PATH


REPORT_DB_PATH = APP_DIR / "data" / "llm_report_review.db"
DEFAULT_MODEL_CONFIG = APP_DIR / "llm_integration" / "models.local.json"
DEFAULT_OUTPUT_DIR = APP_DIR / "outputs" / "llm_report_validation_20260928"

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_report_draft (
    report_id TEXT PRIMARY KEY,
    heat_exchanger_id INTEGER NOT NULL,
    equipment_code TEXT NOT NULL,
    generation_mode TEXT NOT NULL,
    model_key TEXT,
    model_sha256 TEXT,
    evidence_sha256 TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    report_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    approval_note TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collect_evidence(heat_exchanger_id: int, database: Path = DB_PATH) -> dict:
    """Collect a small, traceable fact catalog from the operational database."""
    connection = db.connect(f"file:{database.resolve()}?mode=ro", uri=True)
    connection.row_factory = db.Row
    try:
        equipment = connection.execute(
            """SELECT hx.heat_exchanger_id, e.equipment_code, e.equipment_name,
                      p.plant_code, u.unit_code, hx.service_name,
                      hx.inspection_lifecycle_status
                 FROM heat_exchanger hx
                 JOIN equipment e ON e.equipment_id = hx.equipment_id
                 JOIN process_unit u ON u.unit_id = e.unit_id
                 JOIN plant p ON p.plant_id = u.plant_id
                WHERE hx.heat_exchanger_id = ?""",
            (heat_exchanger_id,),
        ).fetchone()
        if not equipment:
            raise LookupError(f"Heat exchanger not found: {heat_exchanger_id}")
        aggregate = connection.execute(
            """SELECT COUNT(DISTINCT i.iris_inspection_id) AS inspection_count,
                      MAX(COALESCE(i.inspection_date, i.report_date)) AS latest_inspection_date,
                      MAX(r.wall_loss_percent) AS maximum_wall_loss_percent,
                      MIN(r.minimum_wall_thickness_mm) AS minimum_wall_thickness_mm
                 FROM iris_inspection i
                 LEFT JOIN iris_tube_result r ON r.iris_inspection_id = i.iris_inspection_id
                WHERE i.heat_exchanger_id = ? AND i.superseded_by_inspection_id IS NULL""",
            (heat_exchanger_id,),
        ).fetchone()
        maximum = connection.execute(
            """SELECT r.iris_tube_result_id, r.iris_inspection_id, r.tube_id,
                      r.source_tube_id, r.wall_loss_percent, r.minimum_wall_thickness_mm,
                      r.location_mm, r.source_page, i.source_document_id,
                      i.report_number, COALESCE(i.inspection_date, i.report_date) AS inspection_date,
                      d.source_file
                 FROM iris_tube_result r
                 JOIN iris_inspection i ON i.iris_inspection_id = r.iris_inspection_id
                 JOIN source_document d ON d.source_document_id = i.source_document_id
                WHERE i.heat_exchanger_id = ? AND i.superseded_by_inspection_id IS NULL
                  AND r.wall_loss_percent IS NOT NULL
                ORDER BY r.wall_loss_percent DESC, r.iris_tube_result_id LIMIT 1""",
            (heat_exchanger_id,),
        ).fetchone()
    finally:
        connection.close()

    equipment_dict = dict(equipment)
    maximum_dict = dict(maximum) if maximum else {}
    facts = {
        "equipment_code": {
            "value": equipment_dict["equipment_code"], "unit": None,
            "evidence_ref": f"db:heat_exchanger/{heat_exchanger_id}/equipment_code",
        },
        "inspection_count": {
            "value": int(aggregate["inspection_count"] or 0), "unit": "건",
            "evidence_ref": f"db:heat_exchanger/{heat_exchanger_id}/inspection_count",
        },
        "latest_inspection_date": {
            "value": aggregate["latest_inspection_date"], "unit": None,
            "evidence_ref": f"db:heat_exchanger/{heat_exchanger_id}/latest_inspection_date",
        },
        "maximum_wall_loss_percent": {
            "value": maximum_dict.get("wall_loss_percent"), "unit": "%",
            "evidence_ref": f"db:iris_tube_result/{maximum_dict.get('iris_tube_result_id')}/wall_loss_percent",
        },
        "minimum_wall_thickness_mm": {
            "value": maximum_dict.get("minimum_wall_thickness_mm"), "unit": "mm",
            "evidence_ref": f"db:iris_tube_result/{maximum_dict.get('iris_tube_result_id')}/minimum_wall_thickness_mm",
        },
        "maximum_loss_tube": {
            "value": maximum_dict.get("source_tube_id") or maximum_dict.get("tube_id"), "unit": None,
            "evidence_ref": f"db:iris_tube_result/{maximum_dict.get('iris_tube_result_id')}/tube_id",
        },
        "maximum_loss_location_mm": {
            "value": maximum_dict.get("location_mm"), "unit": "mm",
            "evidence_ref": f"db:iris_tube_result/{maximum_dict.get('iris_tube_result_id')}/location_mm",
        },
    }
    pdf_reference = None
    if maximum_dict:
        pdf_reference = {
            "source_document_id": maximum_dict.get("source_document_id"),
            "source_file": maximum_dict.get("source_file"),
            "page": maximum_dict.get("source_page"),
            "evidence_ref": (
                f"pdf:source_document/{maximum_dict.get('source_document_id')}"
                f"#page={maximum_dict.get('source_page')}"
            ),
        }
    return {
        "heat_exchanger_id": heat_exchanger_id,
        "equipment": equipment_dict,
        "facts": facts,
        "pdf_reference": pdf_reference,
        "collected_at": _now(),
        "database_path_exposed_to_model": False,
    }


def baseline_report(evidence: dict) -> dict:
    """Create a deterministic reference report used to prove the validation gate."""
    facts = evidence["facts"]
    ordered_keys = [
        "equipment_code", "inspection_count", "latest_inspection_date",
        "maximum_wall_loss_percent", "minimum_wall_thickness_mm",
        "maximum_loss_tube", "maximum_loss_location_mm",
    ]
    claims = []
    for index, key in enumerate(ordered_keys, start=1):
        fact = facts[key]
        claims.append({
            "claim_id": f"C{index:02d}", "fact_key": key,
            "value": fact["value"], "unit": fact["unit"],
            "evidence_refs": [fact["evidence_ref"]],
        })
    maximum_loss = facts["maximum_wall_loss_percent"]["value"]
    return {
        "schema_version": "1.0.0",
        "report_type": "IRIS2_EVIDENCE_SUMMARY",
        "heat_exchanger_id": evidence["heat_exchanger_id"],
        "equipment_code": facts["equipment_code"]["value"],
        "summary_claim_ids": [claim["claim_id"] for claim in claims],
        "claims": claims,
        "recommendations": [{
            "code": "ENGINEER_REVIEW_REQUIRED",
            "text": "검사 우선순위와 정비 조치는 현업 엔지니어가 원본 PDF 및 검사 이력과 함께 검토해야 합니다.",
            "decision_authority": "HUMAN_ONLY",
            "evidence_refs": [facts["maximum_wall_loss_percent"]["evidence_ref"]],
        }],
        "limitations": [
            "AI 또는 자동 생성 보고서는 검사·정비 의사결정을 자동 승인하지 않습니다.",
            "원본 PDF의 IRIS 신호 이미지는 별도 시각 증거로 확인해야 합니다.",
        ],
        "risk_band": "HIGH" if maximum_loss is not None and float(maximum_loss) >= 30 else "REVIEW",
    }


def selection_prompt(evidence: dict) -> str:
    """Return a constrained prompt that never asks the model to invent facts."""
    report = baseline_report(evidence)
    catalog = [
        {"claim_id": claim["claim_id"], "fact_key": claim["fact_key"], "value": claim["value"], "unit": claim["unit"]}
        for claim in report["claims"]
    ]
    return (
        "/no_think\n다음은 검증 완료된 IRIS 사실 목록입니다. 새로운 수치, 사실, 권고를 만들지 마세요. "
        "보고서 요약에 사용할 claim_id와 허용 권고 코드만 선택하세요. "
        "반드시 설명이나 Markdown 없이 아래 JSON 형식만 출력하세요.\n"
        '{"summary_claim_ids":["C01"],"recommendation_codes":["ENGINEER_REVIEW_REQUIRED"]}\n'
        f"허용 주장: {json.dumps(catalog, ensure_ascii=False)}\n"
        '허용 권고: ["ENGINEER_REVIEW_REQUIRED"]'
    )


def parse_model_selection(text: str) -> dict:
    cleaned = str(text or "").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Local model did not return a JSON object")
    try:
        value = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError("Local model returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("Local model selection must be an object")
    if set(value) != {"summary_claim_ids", "recommendation_codes"}:
        raise ValueError("Local model selection contains unexpected fields")
    claims = value.get("summary_claim_ids")
    recommendations = value.get("recommendation_codes")
    allowed_claims = {f"C{index:02d}" for index in range(1, 8)}
    if not isinstance(claims, list) or not claims or not set(claims) <= allowed_claims:
        raise ValueError("Local model selected an unknown or empty claim list")
    if recommendations != ["ENGINEER_REVIEW_REQUIRED"]:
        raise ValueError("Local model selected an unsupported recommendation")
    return {"summary_claim_ids": list(dict.fromkeys(claims)), "recommendation_codes": recommendations}


def grounded_model_report(evidence: dict, selection: dict, raw_output: str) -> dict:
    report = baseline_report(evidence)
    report["summary_claim_ids"] = selection["summary_claim_ids"]
    report["generation_metadata"] = {
        "mode": "LOCAL_LLM_GROUNDED",
        "model_selection": selection,
        "raw_output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
    }
    return report


def validate_report(report: dict, evidence: dict) -> dict:
    errors: list[str] = []
    facts = evidence.get("facts") or {}
    required = {"schema_version", "report_type", "heat_exchanger_id", "equipment_code", "claims", "recommendations", "limitations"}
    missing = sorted(required - set(report))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if report.get("heat_exchanger_id") != evidence.get("heat_exchanger_id"):
        errors.append("heat_exchanger_id does not match evidence")
    if report.get("equipment_code") != facts.get("equipment_code", {}).get("value"):
        errors.append("equipment_code does not match evidence")
    claims = report.get("claims") if isinstance(report.get("claims"), list) else []
    claim_ids: set[str] = set()
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            errors.append(f"claims[{index}] must be an object")
            continue
        claim_id = str(claim.get("claim_id") or "")
        if not claim_id or claim_id in claim_ids:
            errors.append(f"claims[{index}] has missing or duplicate claim_id")
        claim_ids.add(claim_id)
        key = claim.get("fact_key")
        fact = facts.get(key)
        if not fact:
            errors.append(f"claims[{index}] uses unknown fact_key: {key}")
            continue
        if claim.get("value") != fact.get("value") or claim.get("unit") != fact.get("unit"):
            errors.append(f"claims[{index}] value/unit differs from evidence")
        refs = claim.get("evidence_refs") or []
        if refs != [fact.get("evidence_ref")]:
            errors.append(f"claims[{index}] evidence reference is missing or altered")
    unknown_summary = sorted(set(report.get("summary_claim_ids") or []) - claim_ids)
    if unknown_summary:
        errors.append(f"summary references unknown claims: {', '.join(unknown_summary)}")
    for index, recommendation in enumerate(report.get("recommendations") or []):
        if recommendation.get("decision_authority") != "HUMAN_ONLY":
            errors.append(f"recommendations[{index}] must retain HUMAN_ONLY authority")
        for ref in recommendation.get("evidence_refs") or []:
            if ref not in {fact["evidence_ref"] for fact in facts.values()}:
                errors.append(f"recommendations[{index}] has unknown evidence reference")
    return {
        "status": "PASS" if not errors else "HOLD",
        "error_count": len(errors),
        "errors": errors,
        "claim_count": len(claims),
        "verified_claim_count": len(claims) if not errors else max(0, len(claims) - len(errors)),
        "automatic_engineering_decision": False,
    }


def save_draft(
    evidence: dict,
    report: dict,
    validation: dict,
    *,
    generation_mode: str,
    model_key: str | None = None,
    model_sha256: str | None = None,
    report_db: Path = REPORT_DB_PATH,
) -> dict:
    report_db.parent.mkdir(parents=True, exist_ok=True)
    evidence_hash = _canonical_hash(evidence)
    report_hash = _canonical_hash(report)
    report_id = f"HX{evidence['heat_exchanger_id']}-{report_hash[:12]}"
    connection = db.connect(report_db)
    connection.row_factory = db.Row
    connection.require_tables(SCHEMA)
    previous = connection.execute(
        "SELECT report_sha256, approval_status, approved_by, approved_at, approval_note FROM llm_report_draft WHERE report_id=?",
        (report_id,),
    ).fetchone()
    preserve = bool(previous and previous["report_sha256"] == report_hash and previous["approval_status"] == "APPROVED")
    values = (
        report_id, evidence["heat_exchanger_id"], evidence["facts"]["equipment_code"]["value"],
        generation_mode, model_key, model_sha256, evidence_hash, report_hash,
        json.dumps(evidence, ensure_ascii=False), json.dumps(report, ensure_ascii=False),
        json.dumps(validation, ensure_ascii=False), validation["status"],
        "APPROVED" if preserve else "PENDING", _now(),
        previous["approved_by"] if preserve else None,
        previous["approved_at"] if preserve else None,
        previous["approval_note"] if preserve else None,
    )
    connection.execute(
        """INSERT INTO llm_report_draft (
               report_id, heat_exchanger_id, equipment_code, generation_mode,
               model_key, model_sha256, evidence_sha256, report_sha256,
               evidence_json, report_json, validation_json, validation_status,
               approval_status, created_at, approved_by, approved_at, approval_note
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON DUPLICATE KEY UPDATE report_json=VALUES(report_json), evidence_json=VALUES(evidence_json), validation_json=VALUES(validation_json), validation_status=VALUES(validation_status), approval_status=VALUES(approval_status), approved_by=VALUES(approved_by), approved_at=VALUES(approved_at), approval_note=VALUES(approval_note)""",
        values,
    )
    connection.commit()
    connection.close()
    return {"report_id": report_id, "validation_status": validation["status"]}


def list_drafts(report_db: Path = REPORT_DB_PATH) -> dict:
    if not db.exists(report_db):
        return {"rows": [], "totals": {}}
    connection = db.connect(report_db)
    connection.row_factory = db.Row
    try:
        rows = [dict(row) for row in connection.execute(
            """SELECT * FROM (
                   SELECT d.*, ROW_NUMBER() OVER (
                       PARTITION BY heat_exchanger_id ORDER BY created_at DESC, report_id DESC
                   ) AS latest_rank
                   FROM llm_report_draft d
               ) latest_reports WHERE latest_rank = 1 ORDER BY equipment_code"""
        )]
    finally:
        connection.close()
    for row in rows:
        row["report"] = json.loads(row["report_json"])
        row["evidence"] = json.loads(row["evidence_json"])
        row["validation"] = json.loads(row["validation_json"])
    return {"rows": rows, "totals": {
        "drafts": len(rows),
        "passed": sum(row["validation_status"] == "PASS" for row in rows),
        "holds": sum(row["validation_status"] != "PASS" for row in rows),
        "approved": sum(row["approval_status"] == "APPROVED" for row in rows),
    }}


def latest_validated_summary(heat_exchanger_id: int, report_db: Path = REPORT_DB_PATH) -> dict | None:
    """Return a deterministic display summary from the latest grounded report."""
    if not db.exists(report_db):
        return None
    connection = db.connect(report_db)
    connection.row_factory = db.Row
    try:
        row = connection.execute(
            """SELECT * FROM llm_report_draft
                WHERE heat_exchanger_id=? AND generation_mode='LOCAL_LLM_GROUNDED'
                  AND validation_status='PASS'
                ORDER BY created_at DESC, report_id DESC LIMIT 1""",
            (int(heat_exchanger_id),),
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    report = json.loads(row["report_json"])
    evidence = json.loads(row["evidence_json"])
    claims = {claim["fact_key"]: claim for claim in report.get("claims", [])}
    loss = claims.get("maximum_wall_loss_percent", {}).get("value")
    tube = claims.get("maximum_loss_tube", {}).get("value")
    location = claims.get("maximum_loss_location_mm", {}).get("value")
    text = (
        f"검증된 검사 이력에서 최대 감육률은 {loss}%이며, "
        f"대상 Tube는 {tube}, 위치는 {location} mm입니다. "
        "검사 및 정비 여부는 현업 엔지니어가 원본 근거를 확인해 결정해야 합니다."
    )
    return {
        "report_id": row["report_id"], "text": text,
        "validation_status": row["validation_status"],
        "approval_status": row["approval_status"],
        "generation_mode": row["generation_mode"],
        "pdf_reference": evidence.get("pdf_reference"),
        "risk_band": report.get("risk_band"),
    }


def approve_draft(report_id: str, actor: str, note: str = "", report_db: Path = REPORT_DB_PATH) -> None:
    connection = db.connect(report_db)
    connection.row_factory = db.Row
    try:
        row = connection.execute("SELECT * FROM llm_report_draft WHERE report_id=?", (report_id,)).fetchone()
        if not row:
            raise LookupError("보고서 초안을 찾을 수 없습니다.")
        if row["validation_status"] != "PASS":
            raise ValueError("근거 검증을 통과하지 못한 보고서는 승인할 수 없습니다.")
        connection.execute(
            "UPDATE llm_report_draft SET approval_status='APPROVED', approved_by=?, approved_at=?, approval_note=? WHERE report_id=?",
            (actor, _now(), note.strip(), report_id),
        )
        connection.commit()
    finally:
        connection.close()
