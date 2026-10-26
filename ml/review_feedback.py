"""Append-only expert review labels stored outside the operational database."""

from __future__ import annotations

from iris2 import dbapi as db
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .anomaly import REVIEW_LABELS, VALID_ISSUE_LABELS


LABEL_DEFINITIONS = (
    ("CONFIRMED_SOURCE_ERROR", "원천자료 오류"),
    ("CONFIRMED_MAPPING_ERROR", "설비·Tube 매핑 오류"),
    ("CONFIRMED_FORMULA_ERROR", "계산식 오류"),
    ("CONFIRMED_MEASUREMENT_VARIATION", "측정 변동 확인"),
    ("VALID_EXTREME_VALUE", "유효한 극단값"),
    ("ENGINEERING_ACCEPTED", "엔지니어링 수용"),
    ("INSUFFICIENT_EVIDENCE", "근거 부족"),
    ("RECHECK_REQUIRED", "재검사 필요"),
)
LABEL_NAMES = dict(LABEL_DEFINITIONS)
EVALUATION_CRITERIA = {
    "minimum_reviewed_top30": 30,
    "minimum_top30_coverage": 1.0,
    "minimum_precision_at_30": 0.60,
    "maximum_hard_gate_critical_omissions": 0,
    "automatic_decision_enabled": False,
}


def _connect(path: str | Path) -> db.Connection:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = db.connect(target)
    connection.row_factory = db.Row
    return connection


def initialize_review_database(path: str | Path) -> None:
    labels = ",".join(f"'{label}'" for label in sorted(REVIEW_LABELS))
    with closing(_connect(path)) as connection:
        connection.require_tables(f"""
            CREATE TABLE IF NOT EXISTS ml_review_feedback (
                feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_type TEXT NOT NULL CHECK (analysis_type = 'ANOMALY'),
                run_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                iris_tube_result_id INTEGER NOT NULL,
                iris_inspection_id INTEGER NOT NULL,
                tube_id INTEGER NOT NULL,
                label TEXT NOT NULL CHECK (label IN ({labels})),
                note TEXT,
                reviewer_user_id INTEGER,
                reviewer_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_ml_review_feedback_run_result
                ON ml_review_feedback(run_id, iris_tube_result_id, feedback_id);
            CREATE INDEX IF NOT EXISTS ix_ml_review_feedback_created
                ON ml_review_feedback(created_at, feedback_id);
        """)
        connection.commit()


def initialize_hotspot_review_database(path: str | Path) -> None:
    """Create append-only Hotspot evidence-review storage outside the operational DB."""
    with closing(_connect(path)) as connection:
        connection.require_tables("""
            CREATE TABLE IF NOT EXISTS ml_hotspot_review_feedback (
                hotspot_feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_type TEXT NOT NULL CHECK (analysis_type = 'HOTSPOT'),
                run_id TEXT NOT NULL,
                model_version TEXT NOT NULL,
                iris_tube_result_id INTEGER NOT NULL,
                iris_inspection_id INTEGER NOT NULL,
                tube_id INTEGER NOT NULL,
                decision TEXT NOT NULL CHECK (decision = 'CONFIRMED_WITH_RAW'),
                confirmation_status TEXT NOT NULL CHECK (confirmation_status = 'CONFIRMED'),
                confidence TEXT NOT NULL CHECK (confidence = 'HIGH'),
                hotspot_score REAL NOT NULL,
                pdf_source_file TEXT NOT NULL,
                pdf_source_page INTEGER NOT NULL,
                raw_files_json TEXT NOT NULL,
                evidence_fingerprint TEXT NOT NULL UNIQUE,
                reviewer_name TEXT NOT NULL,
                reviewed_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_ml_hotspot_feedback_run_result
                ON ml_hotspot_review_feedback(run_id, iris_tube_result_id, hotspot_feedback_id);
        """)
        connection.commit()


def latest_hotspot_review_feedback(path: str | Path, run_id: str) -> dict[int, dict[str, Any]]:
    initialize_hotspot_review_database(path)
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT * FROM ml_hotspot_review_feedback
             WHERE run_id=?
             ORDER BY hotspot_feedback_id
            """,
            (str(run_id),),
        ).fetchall()
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        latest[int(row["iris_tube_result_id"])] = dict(row)
    return latest


def save_review_feedback(
    path: str | Path,
    *,
    run_id: str,
    model_version: str,
    iris_tube_result_id: int,
    iris_inspection_id: int,
    tube_id: int,
    label: str,
    note: str = "",
    reviewer_user_id: int | None = None,
    reviewer_name: str,
) -> int:
    selected_label = str(label or "").strip().upper()
    if selected_label not in REVIEW_LABELS:
        raise ValueError("지원하지 않는 전문가 검토 라벨입니다.")
    identifiers = (int(iris_tube_result_id), int(iris_inspection_id), int(tube_id))
    if any(value <= 0 for value in identifiers):
        raise ValueError("검사·Tube 식별자가 올바르지 않습니다.")
    selected_run = str(run_id or "").strip()
    selected_model = str(model_version or "").strip()
    reviewer = str(reviewer_name or "").strip()
    selected_note = str(note or "").strip()
    if not selected_run or not selected_model or not reviewer:
        raise ValueError("분석 실행·모델·검토자 정보는 필수입니다.")
    if len(selected_note) > 1000:
        raise ValueError("검토 의견은 1,000자 이내로 입력해 주세요.")
    if not selected_note:
        raise ValueError("판단 근거를 검토 의견에 입력해 주세요.")
    initialize_review_database(path)
    with closing(_connect(path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO ml_review_feedback (
                analysis_type, run_id, model_version, iris_tube_result_id,
                iris_inspection_id, tube_id, label, note,
                reviewer_user_id, reviewer_name, created_at
            ) VALUES ('ANOMALY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                selected_run, selected_model, *identifiers, selected_label,
                selected_note, reviewer_user_id, reviewer,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def latest_review_feedback(path: str | Path, run_id: str) -> dict[int, dict[str, Any]]:
    initialize_review_database(path)
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT feedback_id, run_id, model_version, iris_tube_result_id,
                   iris_inspection_id, tube_id, label, note,
                   reviewer_user_id, reviewer_name, created_at
              FROM ml_review_feedback
             WHERE run_id = ?
             ORDER BY feedback_id
            """,
            (str(run_id),),
        ).fetchall()
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        value = dict(row)
        value["label_name"] = LABEL_NAMES.get(value["label"], value["label"])
        latest[int(row["iris_tube_result_id"])] = value
    return latest


def latest_labels_by_result(path: str | Path) -> dict[int, str]:
    """Return the latest expert label for each result across completed review runs."""
    initialize_review_database(path)
    with closing(_connect(path)) as connection:
        rows = connection.execute(
            """
            SELECT iris_tube_result_id, label
              FROM ml_review_feedback
             ORDER BY feedback_id
            """
        ).fetchall()
    return {int(row["iris_tube_result_id"]): str(row["label"]) for row in rows}


def evaluate_expert_feedback(
    rows: list[dict[str, Any]],
    feedback: dict[int, dict[str, Any]],
    *,
    hard_gate_critical_omissions: int = 0,
) -> dict[str, Any]:
    top_rows = sorted(
        rows,
        key=lambda row: (int(row.get("review_priority_rank") or 10**9), int(row["iris_tube_result_id"])),
    )[:30]
    labels = [
        feedback[int(row["iris_tube_result_id"])]["label"]
        for row in top_rows
        if int(row["iris_tube_result_id"]) in feedback
    ]
    reviewed_count = len(labels)
    target_count = len(top_rows)
    coverage = reviewed_count / target_count if target_count else 0.0
    precision = (
        sum(label in VALID_ISSUE_LABELS for label in labels) / reviewed_count
        if reviewed_count else None
    )
    enough = (
        reviewed_count >= EVALUATION_CRITERIA["minimum_reviewed_top30"]
        and coverage >= EVALUATION_CRITERIA["minimum_top30_coverage"]
    )
    if not enough:
        status = "COLLECTING"
    elif (
        hard_gate_critical_omissions
        <= EVALUATION_CRITERIA["maximum_hard_gate_critical_omissions"]
        and precision is not None
        and precision >= EVALUATION_CRITERIA["minimum_precision_at_30"]
    ):
        status = "PASS"
    else:
        status = "HOLD"
    return {
        "status": status,
        "reviewed_top30_count": reviewed_count,
        "top30_target_count": target_count,
        "top30_coverage": coverage,
        "precision_at_30_reviewed": precision,
        "hard_gate_critical_omissions": int(hard_gate_critical_omissions),
        "label_counts": dict(sorted(Counter(labels).items())),
        "criteria": dict(EVALUATION_CRITERIA),
        "automatic_decision_enabled": False,
    }
