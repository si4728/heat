"""Stage 5 PDF/OCR review staging and approval workflow.

The operational inspection database remains read-only.  Review decisions and
their evidence fingerprints are stored in a separate SQLite database.
"""

from __future__ import annotations

import csv
import hashlib
import json
from iris2 import dbapi as db
from datetime import datetime, timezone
from pathlib import Path

import pymupdf
from iris2.asset_paths import local_asset_path

from .hx_configuration import APP_DIR, DB_PATH


REVIEW_DB_PATH = APP_DIR / "data" / "pdf_ocr_review.db"
DEFAULT_PDF_DIR = APP_DIR / "data" / "pdf_reports"
DEFAULT_OUTPUT_DIR = APP_DIR / "outputs" / "pdf_ocr_workflow_20260928"


SCHEMA = """
CREATE TABLE IF NOT EXISTS pdf_document_review (
    source_document_id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    pdf_file TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    source_json_sha256 TEXT NOT NULL,
    expected_pdf_sha256 TEXT,
    actual_pdf_sha256 TEXT,
    pdf_hash_status TEXT NOT NULL,
    expected_page_count INTEGER NOT NULL,
    actual_page_count INTEGER,
    page_count_status TEXT NOT NULL,
    load_status TEXT NOT NULL,
    postprocess_status TEXT NOT NULL,
    expected_report_count INTEGER NOT NULL,
    loaded_report_count INTEGER NOT NULL,
    missing_report_count INTEGER NOT NULL,
    structured_page_count INTEGER NOT NULL,
    visual_evidence_page_count INTEGER NOT NULL,
    ocr_required_page_count INTEGER NOT NULL,
    gate_status TEXT NOT NULL,
    review_status TEXT NOT NULL,
    approval_status TEXT NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    staged_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    approval_note TEXT
);
CREATE TABLE IF NOT EXISTS pdf_page_review (
    source_document_id INTEGER NOT NULL,
    page_number INTEGER NOT NULL,
    iris_inspection_id INTEGER,
    source_classification TEXT NOT NULL,
    handling_class TEXT NOT NULL,
    review_status TEXT NOT NULL,
    review_reason TEXT NOT NULL,
    text_character_count INTEGER NOT NULL,
    image_count INTEGER NOT NULL,
    PRIMARY KEY (source_document_id, page_number)
);
CREATE INDEX IF NOT EXISTS ix_pdf_page_review_handling
ON pdf_page_review(handling_class, review_status);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _page_handling(row: db.Row) -> tuple[str, str, str]:
    if int(row["text_character_count"] or 0) > 0:
        return (
            "STRUCTURED_TEXT",
            "VERIFIED",
            "텍스트/표 구조가 추출되어 원문 대조가 가능한 페이지",
        )
    if row["iris_inspection_id"] is not None and int(row["image_count"] or 0) > 0:
        return (
            "VISUAL_EVIDENCE",
            "PRESERVED",
            "검사 이력에 연결된 IRIS 신호 이미지 원본; OCR 수치화 대상 아님",
        )
    return (
        "OCR_REQUIRED",
        "HOLD",
        "텍스트가 없고 검사 연결 이미지 근거가 없어 OCR 또는 수동 확인 필요",
    )


def build_review_queue(
    operational_db: Path = DB_PATH,
    review_db: Path = REVIEW_DB_PATH,
    pdf_dir: Path = DEFAULT_PDF_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict:
    """Rebuild the evidence queue without modifying the operational database."""
    review_db.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    source = db.connect(operational_db)
    source.row_factory = db.Row
    review = db.connect(review_db)
    review.row_factory = db.Row
    review.require_tables(SCHEMA)
    staged_at = _utc_now()
    documents: list[dict] = []
    try:
        for document in source.execute(
            "SELECT * FROM source_document ORDER BY source_document_id"
        ):
            metadata = json.loads(document["document_json"] or "{}")
            pdf_file = str(metadata.get("source_file") or "")
            pdf_path = (pdf_dir / pdf_file).resolve()
            expected_pdf_hash = str(metadata.get("source_pdf_sha256") or "")
            actual_pdf_hash = _sha256(pdf_path) if pdf_path.is_file() else ""
            if pdf_path.is_file():
                with pymupdf.open(pdf_path) as pdf_document:
                    actual_pages = pdf_document.page_count
            else:
                actual_pages = None
            pdf_hash_status = (
                "MATCH" if expected_pdf_hash and actual_pdf_hash == expected_pdf_hash else "MISMATCH"
            )
            page_count_status = (
                "MATCH" if actual_pages == int(document["page_count"] or 0) else "MISMATCH"
            )

            page_rows = list(source.execute(
                """SELECT page_number, iris_inspection_id, classification,
                          text_character_count, image_count
                     FROM source_document_page
                    WHERE source_document_id = ? ORDER BY page_number""",
                (document["source_document_id"],),
            ))
            counts = {"STRUCTURED_TEXT": 0, "VISUAL_EVIDENCE": 0, "OCR_REQUIRED": 0}
            review.execute(
                "DELETE FROM pdf_page_review WHERE source_document_id = ?",
                (document["source_document_id"],),
            )
            page_evidence = []
            for page in page_rows:
                handling, status, reason = _page_handling(page)
                counts[handling] += 1
                page_evidence.append(
                    [page["page_number"], handling, status, page["text_character_count"], page["image_count"]]
                )
                review.execute(
                    """INSERT INTO pdf_page_review (
                           source_document_id, page_number, iris_inspection_id,
                           source_classification, handling_class, review_status,
                           review_reason, text_character_count, image_count
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        document["source_document_id"], page["page_number"],
                        page["iris_inspection_id"], page["classification"], handling,
                        status, reason, int(page["text_character_count"] or 0),
                        int(page["image_count"] or 0),
                    ),
                )

            complete = all((
                pdf_hash_status == "MATCH",
                page_count_status == "MATCH",
                len(page_rows) == int(document["page_count"] or 0),
                document["load_status"] == "LOADED",
                document["postprocess_status"] == "COMPLETED",
                int(document["missing_report_count"] or 0) == 0,
                counts["OCR_REQUIRED"] == 0,
            ))
            gate_status = "READY_FOR_APPROVAL" if complete else "HOLD"
            fingerprint_payload = {
                "source_json_sha256": document["sha256"],
                "pdf_sha256": actual_pdf_hash,
                "pages": page_evidence,
            }
            fingerprint = hashlib.sha256(
                json.dumps(fingerprint_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            previous = review.execute(
                "SELECT evidence_fingerprint, approval_status, approved_by, approved_at, approval_note "
                "FROM pdf_document_review WHERE source_document_id = ?",
                (document["source_document_id"],),
            ).fetchone()
            preserve_approval = bool(
                previous and previous["evidence_fingerprint"] == fingerprint
                and previous["approval_status"] == "APPROVED"
            )
            approval_status = "APPROVED" if preserve_approval else "PENDING"
            approved_by = previous["approved_by"] if preserve_approval else None
            approved_at = previous["approved_at"] if preserve_approval else None
            approval_note = previous["approval_note"] if preserve_approval else None
            values = {
                "source_document_id": document["source_document_id"],
                "source_file": document["source_file"],
                "pdf_file": pdf_file,
                "pdf_path": str(pdf_path),
                "source_json_sha256": document["sha256"],
                "expected_pdf_sha256": expected_pdf_hash,
                "actual_pdf_sha256": actual_pdf_hash,
                "pdf_hash_status": pdf_hash_status,
                "expected_page_count": int(document["page_count"] or 0),
                "actual_page_count": actual_pages,
                "page_count_status": page_count_status,
                "load_status": document["load_status"],
                "postprocess_status": document["postprocess_status"],
                "expected_report_count": int(document["expected_report_count"] or 0),
                "loaded_report_count": int(document["loaded_report_count"] or 0),
                "missing_report_count": int(document["missing_report_count"] or 0),
                "structured_page_count": counts["STRUCTURED_TEXT"],
                "visual_evidence_page_count": counts["VISUAL_EVIDENCE"],
                "ocr_required_page_count": counts["OCR_REQUIRED"],
                "gate_status": gate_status,
                "review_status": "REVIEWED" if complete else "HOLD",
                "approval_status": approval_status,
                "evidence_fingerprint": fingerprint,
                "staged_at": staged_at,
                "approved_by": approved_by,
                "approved_at": approved_at,
                "approval_note": approval_note,
            }
            columns = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            updates = ", ".join(f"{name}=VALUES({name})" for name in values if name != "source_document_id")
            review.execute(
                f"INSERT INTO pdf_document_review ({columns}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}",
                tuple(values.values()),
            )
            documents.append(values)
        review.commit()
    finally:
        source.close()
        review.close()

    summary = {
        "stage": 5,
        "workflow": "PDF/OCR 적재·검토·승인",
        "generated_at": staged_at,
        "operational_database_modified": False,
        "document_count": len(documents),
        "page_count": sum(item["expected_page_count"] for item in documents),
        "structured_page_count": sum(item["structured_page_count"] for item in documents),
        "visual_evidence_page_count": sum(item["visual_evidence_page_count"] for item in documents),
        "ocr_required_page_count": sum(item["ocr_required_page_count"] for item in documents),
        "ready_for_approval_count": sum(item["gate_status"] == "READY_FOR_APPROVAL" for item in documents),
        "approved_count": sum(item["approval_status"] == "APPROVED" for item in documents),
        "documents": documents,
    }
    (output_dir / "review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "document_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(documents[0]) if documents else [])
        if documents:
            writer.writeheader()
            writer.writerows(documents)
    return summary


def dashboard_data(review_db: Path = REVIEW_DB_PATH) -> dict:
    if not db.exists(review_db):
        return {"documents": [], "totals": {}}
    connection = db.connect(review_db)
    connection.row_factory = db.Row
    try:
        documents = [dict(row) for row in connection.execute(
            "SELECT * FROM pdf_document_review ORDER BY source_document_id"
        )]
    finally:
        connection.close()
    totals = {
        "documents": len(documents),
        "pages": sum(row["expected_page_count"] for row in documents),
        "structured": sum(row["structured_page_count"] for row in documents),
        "visual": sum(row["visual_evidence_page_count"] for row in documents),
        "ocr_required": sum(row["ocr_required_page_count"] for row in documents),
        "ready": sum(row["gate_status"] == "READY_FOR_APPROVAL" for row in documents),
        "approved": sum(row["approval_status"] == "APPROVED" for row in documents),
    }
    return {"documents": documents, "totals": totals}


def document_record(source_document_id: int, review_db: Path = REVIEW_DB_PATH) -> dict | None:
    if not db.exists(review_db):
        return None
    connection = db.connect(review_db)
    connection.row_factory = db.Row
    try:
        row = connection.execute(
            "SELECT * FROM pdf_document_review WHERE source_document_id = ?",
            (source_document_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def approve_document(
    source_document_id: int,
    approved_by: str,
    note: str = "",
    review_db: Path = REVIEW_DB_PATH,
) -> dict:
    connection = db.connect(review_db)
    connection.row_factory = db.Row
    try:
        row = connection.execute(
            "SELECT * FROM pdf_document_review WHERE source_document_id = ?",
            (source_document_id,),
        ).fetchone()
        if not row:
            raise LookupError("PDF 검토 문서를 찾을 수 없습니다.")
        if row["gate_status"] != "READY_FOR_APPROVAL":
            raise ValueError("보류 항목이 있어 승인할 수 없습니다.")
        pdf_path = local_asset_path(row["pdf_path"])
        if not pdf_path.is_file() or _sha256(pdf_path) != row["actual_pdf_sha256"]:
            raise ValueError("원본 PDF가 검토 시점 이후 변경되어 재검토가 필요합니다.")
        approved_at = _utc_now()
        connection.execute(
            """UPDATE pdf_document_review
                  SET approval_status='APPROVED', approved_by=?, approved_at=?, approval_note=?
                WHERE source_document_id=?""",
            (approved_by, approved_at, note.strip(), source_document_id),
        )
        connection.commit()
        return {"source_document_id": source_document_id, "approved_at": approved_at}
    finally:
        connection.close()
