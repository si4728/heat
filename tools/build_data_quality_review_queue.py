"""Build a review queue for unresolved operational data-quality issues.

This script is intentionally read-only. It does not infer or overwrite source data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "heat_exchanger_db3.db"
DEFAULT_OUTPUT = ROOT / "outputs" / "data_quality_normalization_20260910"


def classify(issue_code: str, field_path: str) -> tuple[str, str, str]:
    if issue_code == "ROW_CALCULATION_MISMATCH":
        return (
            "P1_ENGINEERING_REVIEW",
            "CALCULATION_BASIS",
            "PDF 기재값과 재계산값의 기준·반올림·단위를 공학 검토하고 양쪽 근거를 보존",
        )

    if issue_code == "MASTER_JSON_VALUE_MISMATCH":
        field = field_path.lower()
        if any(token in field for token in ("tube_count", "outer_diameter", "nominal_thickness", "equipment_name")):
            priority = "P1_SOURCE_CONFIRMATION"
        else:
            priority = "P2_SOURCE_CONFIRMATION"
        return (
            priority,
            "MASTER_SOURCE_CONFLICT",
            "승인 도면·원본 보고서·설비 마스터를 대조한 뒤 승인자 기록과 함께 단일 값 확정",
        )

    if issue_code.startswith("SOURCE_PDF_"):
        urgent_tokens = ("INVALID", "ERROR", "TYPO", "CONTRADICTION", "EQUIPMENT")
        priority = "P1_SOURCE_CONFIRMATION" if any(token in issue_code for token in urgent_tokens) else "P2_SOURCE_VARIANCE_REVIEW"
        return (
            priority,
            "SOURCE_DOCUMENT_VARIANCE",
            "원본 PDF 내 표기 충돌을 확인하고 운영값 유지·수정 사유를 검토 이력에 기록",
        )

    return (
        "P3_MANUAL_REVIEW",
        "OTHER",
        "원본 근거를 확인한 후 개별 검토 화면에서 처리 사유와 함께 종결",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    db_path = args.database.resolve()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT q.data_quality_issue_id AS issue_id,
                   COALESCE(i.canonical_equipment_code, i.original_equipment_id, '') AS equipment_id,
                   d.source_file,
                   q.issue_code, q.field_path,
                   q.source_value_json AS source_value,
                   q.calculated_value_json AS calculated_value,
                   q.description, q.status
            FROM data_quality_issue AS q
            JOIN source_document AS d
              ON d.source_document_id = q.source_document_id
            LEFT JOIN iris_inspection AS i
              ON i.iris_inspection_id = q.iris_inspection_id
            WHERE q.status = 'OPEN'
            ORDER BY q.data_quality_issue_id
            """
        ).fetchall()
        status_counts = dict(
            conn.execute(
                "SELECT status, COUNT(*) FROM data_quality_issue GROUP BY status"
            ).fetchall()
        )

    queue_rows = []
    priority_counts: Counter[str] = Counter()
    code_counts: Counter[str] = Counter()
    equipment_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    priority_codes: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        priority, category, action = classify(row["issue_code"], row["field_path"] or "")
        queue_row = {
            "issue_id": row["issue_id"],
            "priority": priority,
            "category": category,
            "equipment_id": row["equipment_id"] or "",
            "source_file": row["source_file"] or "",
            "issue_code": row["issue_code"],
            "field_path": row["field_path"] or "",
            "source_value": row["source_value"] or "",
            "calculated_value": row["calculated_value"] or "",
            "description": row["description"] or "",
            "recommended_action": action,
        }
        queue_rows.append(queue_row)
        priority_counts[priority] += 1
        code_counts[row["issue_code"]] += 1
        equipment_counts[row["equipment_id"] or "(미지정)"] += 1
        category_counts[category] += 1
        priority_codes[priority][row["issue_code"]] += 1

    priority_order = {
        "P1_ENGINEERING_REVIEW": 1,
        "P1_SOURCE_CONFIRMATION": 2,
        "P2_SOURCE_CONFIRMATION": 3,
        "P2_SOURCE_VARIANCE_REVIEW": 4,
        "P3_MANUAL_REVIEW": 5,
    }
    queue_rows.sort(key=lambda row: (priority_order.get(row["priority"], 99), row["equipment_id"], row["issue_id"]))

    csv_path = output_dir / "remaining_quality_issue_review_queue.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(queue_rows[0].keys()) if queue_rows else ["issue_id"])
        writer.writeheader()
        writer.writerows(queue_rows)

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    summary = {
        "generated_at": generated_at,
        "database": str(db_path),
        "read_only": True,
        "status_counts": status_counts,
        "open_queue_count": len(queue_rows),
        "priority_counts": dict(sorted(priority_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "issue_code_counts": dict(sorted(code_counts.items())),
        "priority_issue_code_counts": {
            priority: dict(sorted(counts.items())) for priority, counts in sorted(priority_codes.items())
        },
        "top_equipment": equipment_counts.most_common(20),
        "source_coverage_gaps": {
            "summary_page_null": 10,
            "summary_all_spec_null": 121,
            "circumferential_angle_missing": 1149,
            "defect_length_missing": 1149,
            "physical_xy_missing_by_design": 2253,
            "unresolved_layout_sources_held": 10,
        },
        "policy": [
            "원본 근거 없이 값을 추정하거나 자동 생성하지 않는다.",
            "운영값 수정 또는 이슈 종결은 승인 근거와 검토자·처리 사유를 남긴다.",
            "결함 원주각·길이가 확보될 때까지 실제 2D/3D 결함 위치 검증은 보류한다.",
        ],
    }
    json_path = output_dir / "remaining_quality_issue_review_summary.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = output_dir / "NORMALIZATION_RESULT.md"
    md_lines = [
        "# 데이터 정상화 결과 및 잔여 검토 큐",
        "",
        f"- 생성 시각: {generated_at}",
        f"- 대상 DB: `{db_path}`",
        f"- 자동·근거 기반 종결: {status_counts.get('RESOLVED', 0):,}건",
        f"- 잔여 OPEN: {status_counts.get('OPEN', 0):,}건",
        "- DB 값 변경: 없음(본 큐 생성은 읽기 전용)",
        "",
        "## 잔여 우선순위",
        "",
        "| 우선순위 | 건수 | 처리 원칙 |",
        "|---|---:|---|",
    ]
    for priority, count in sorted(priority_counts.items(), key=lambda item: priority_order.get(item[0], 99)):
        md_lines.append(f"| {priority} | {count:,} | 원본 근거 확인 후 개별 승인·종결 |")
    md_lines.extend(
        [
            "",
            "## 이슈 코드별 잔여 건수",
            "",
            "| 이슈 코드 | 건수 |",
            "|---|---:|",
        ]
    )
    for code, count in sorted(code_counts.items()):
        md_lines.append(f"| {code} | {count:,} |")
    md_lines.extend(
        [
            "",
            "## 자동 보정 제외 항목",
            "",
            "- 결함 원주각 및 결함 길이: 각 1,149건 미확보. 실제 2D 펼침도·3D 국부 패치 검증 보류.",
            "- Tube physical X/Y: 2,253건 미등록(현재 설계상 좌표 미제공). 임의 생성 금지.",
            "- Source layout: 충돌이 해소되지 않은 10건은 운영 반영에서 계속 제외.",
            "- 검사 요약 페이지 10건 및 전체 사양 121건의 원본 필드 공백은 원본 자료 확보 전까지 유지.",
            "",
            "상세 행 단위 검토 대상은 `remaining_quality_issue_review_queue.csv`에 정리했습니다.",
        ]
    )
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(json.dumps({"csv": str(csv_path), "json": str(json_path), "markdown": str(md_path), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
