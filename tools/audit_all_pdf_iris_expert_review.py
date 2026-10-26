from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "iris_test_report"
JSON_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs" / "pdf_iris_expert_review_20260928"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def source_pages(item: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    report = item.get("report") or {}
    table = item.get("tube_results_table") or {}
    for value in report.get("source_report_pages") or []:
        if isinstance(value, int):
            pages.add(value)
    for value in table.get("source_pages") or []:
        if isinstance(value, int):
            pages.add(value)
    for row in table.get("records") or []:
        value = row.get("source_page")
        if isinstance(value, int):
            pages.add(value)
    return pages


def dedicated_audit(pdf: Path) -> dict[str, Any] | None:
    stem = pdf.stem.lower().replace("_1p_", "_")
    candidates = [
        ROOT / "tools" / f"audit_{stem}_pdf_json_20260928.py",
        ROOT / "tools" / f"audit_{stem}_pdf_json_20260825.py",
    ]
    script = next((candidate for candidate in candidates if candidate.exists()), None)
    if script is None:
        return None
    child_env = dict(os.environ)
    child_env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=child_env,
    )
    return json.loads(completed.stdout)


def normalize_dedicated(result: dict[str, Any] | None) -> dict[str, Any]:
    if result is None:
        return {
            "available": False,
            "finding_group_count": 0,
            "finding_item_count": 0,
            "finding_counts": {},
            "findings": {},
        }
    findings = result.get("findings") or {}
    counts = {key: len(value or []) for key, value in findings.items()}
    item_count = 0
    for key, values in findings.items():
        for value in values or []:
            if key == "row_calculation_mismatches":
                item_count += int(value.get("row_count") or len(value.get("rows") or []))
            else:
                item_count += 1
    return {
        "available": True,
        "finding_group_count": sum(counts.values()),
        "finding_item_count": item_count,
        "finding_counts": counts,
        "findings": findings,
        "reported_report_count": result.get("report_count", result.get("reports")),
        "pdf_detail_rows": result.get("pdf_parsed_result_row_count", result.get("pdf_detail_rows")),
        "json_detail_rows": result.get("json_result_row_count", result.get("json_detail_rows")),
    }


def audit_pair(pdf: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    prefix = pdf.stem.replace("_1P_", "")
    json_path = JSON_DIR / f"{prefix}_IRIS2_all_tube_results.json"
    if not json_path.exists():
        return ({"pdf": pdf.name, "json": json_path.name, "status": "BLOCKED", "blocking": ["JSON_MISSING"]}, [])

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    document = payload.get("document") or {}
    reports = payload.get("inspection_reports") or []
    pdf_pages = len(PdfReader(str(pdf)).pages)
    pdf_hash = sha256(pdf)
    declared_hash = document.get("source_sha256")
    dedicated = normalize_dedicated(dedicated_audit(pdf))

    blocking: list[str] = []
    if document.get("page_count") != pdf_pages:
        blocking.append("PDF_PAGE_COUNT_MISMATCH")
    if declared_hash and declared_hash.lower() != pdf_hash.lower():
        blocking.append("PDF_SHA256_MISMATCH")
    if document.get("inspection_report_object_count") not in (None, len(reports)):
        blocking.append("REPORT_COUNT_MISMATCH")

    report_reviews: list[dict[str, Any]] = []
    all_keys: Counter[tuple[str, str]] = Counter()
    pair_counts = Counter()
    source_issue_categories: Counter[str] = Counter()

    for item in reports:
        report = item.get("report") or {}
        table = item.get("tube_results_table") or {}
        rows = table.get("records") or []
        validation = item.get("validation") or {}
        summary = report.get("inspection_summary") or {}
        spec = report.get("tube_spec") or {}
        sequence = report.get("report_sequence")
        equipment = str(report.get("equipment_id") or "")
        scope = str((report.get("inspection_scope") or {}).get("scope_code") or "ALL")
        all_keys[(equipment, scope)] += 1

        issues: list[str] = []
        notes: list[str] = []
        pages = source_pages(item)
        invalid_pages = sorted(page for page in pages if page < 1 or page > pdf_pages)
        if invalid_pages:
            issues.append("INVALID_SOURCE_PAGE")
            pair_counts["invalid_source_page"] += len(invalid_pages)
        if not report.get("source_report_pages"):
            issues.append("REPORT_PAGE_MISSING")
            pair_counts["report_page_missing"] += 1
        if not table.get("source_pages"):
            issues.append("DETAIL_PAGE_MISSING")
            pair_counts["detail_page_missing"] += 1

        inspected = summary.get("inspected_tube_count")
        if inspected is not None and int(inspected) != len(rows):
            issues.append("INSPECTED_COUNT_MISMATCH")
            pair_counts["inspected_count_mismatch"] += 1

        minima = [as_float(row.get("minimum_wall_thickness_mm")) for row in rows]
        losses = [as_float(row.get("wall_loss_percent")) for row in rows]
        minima = [value for value in minima if value is not None]
        losses = [value for value in losses if value is not None]
        summary_min = as_float(summary.get("minimum_remaining_thickness_mm"))
        summary_max = as_float(summary.get("maximum_wall_loss_percent"))
        if minima and summary_min is not None and abs(min(minima) - summary_min) > 0.011:
            issues.append("SUMMARY_MINIMUM_MISMATCH")
            pair_counts["summary_minimum_mismatch"] += 1
        if losses and summary_max is not None and abs(max(losses) - summary_max) > 0.011:
            issues.append("SUMMARY_MAXIMUM_MISMATCH")
            pair_counts["summary_maximum_mismatch"] += 1

        nominal = as_float(spec.get("design_thickness_mm"))
        length = as_float(spec.get("length_mm"))
        formula_mismatches = 0
        large_formula_mismatches = 0
        out_of_range_locations = 0
        max_loss_delta = 0.0
        for row in rows:
            minimum = as_float(row.get("minimum_wall_thickness_mm"))
            depth = as_float(row.get("wall_loss_depth_mm"))
            loss = as_float(row.get("wall_loss_percent"))
            if nominal and minimum is not None and depth is not None and loss is not None:
                expected_depth = round(nominal - minimum, 2)
                expected_loss = round(expected_depth / nominal * 100, 2)
                depth_delta = abs(depth - expected_depth)
                loss_delta = abs(loss - expected_loss)
                max_loss_delta = max(max_loss_delta, loss_delta)
                if depth_delta > 0.011 or loss_delta > 0.011:
                    formula_mismatches += 1
                    if depth_delta > 0.051 or loss_delta > 1.01:
                        large_formula_mismatches += 1
            location = as_float(row.get("location_mm"))
            if length and location is not None and location > length + 1:
                out_of_range_locations += 1

        if formula_mismatches:
            issues.append("ROW_FORMULA_MISMATCH")
            pair_counts["formula_mismatch_rows"] += formula_mismatches
        if large_formula_mismatches:
            issues.append("ROW_FORMULA_LARGE_DELTA")
            pair_counts["large_formula_mismatch_rows"] += large_formula_mismatches
        if out_of_range_locations:
            issues.append("LOCATION_EXCEEDS_REPORTED_LENGTH")
            pair_counts["location_exceeds_length_rows"] += out_of_range_locations

        source_issues = validation.get("source_pdf_inconsistencies") or []
        for issue in source_issues:
            source_issue_categories[str(issue.get("category") or "UNKNOWN")] += 1
        if source_issues:
            notes.append(f"DOCUMENTED_SOURCE_ISSUES={len(source_issues)}")
            pair_counts["documented_source_issues"] += len(source_issues)

        corrections = validation.get("normalization_corrections") or []
        if corrections:
            notes.append(f"NORMALIZATION_CORRECTIONS={len(corrections)}")

        report_status = "REVIEW_REQUIRED" if issues else ("PASS_WITH_NOTE" if notes else "PASS")
        report_reviews.append({
            "pair": prefix,
            "sequence": sequence,
            "equipment_id": equipment,
            "scope_code": scope,
            "status": report_status,
            "row_count": len(rows),
            "source_pages": sorted(pages),
            "issues": issues,
            "notes": notes,
            "formula_mismatch_rows": formula_mismatches,
            "large_formula_mismatch_rows": large_formula_mismatches,
            "maximum_formula_loss_delta_pp": round(max_loss_delta, 4),
            "location_exceeds_length_rows": out_of_range_locations,
            "documented_source_issue_count": len(source_issues),
        })

    duplicate_keys = [
        {"equipment_id": key[0], "scope_code": key[1], "count": count}
        for key, count in all_keys.items()
        if count > 1
    ]
    # Repeated equipment/scope may represent separate reports within the same annual
    # document, so it is disclosed as a review note rather than a hard failure.
    if duplicate_keys:
        pair_counts["repeated_equipment_scope_keys"] = len(duplicate_keys)

    reviews_by_sequence = {review["sequence"]: review for review in report_reviews}
    for finding_type, findings in dedicated.get("findings", {}).items():
        for finding in findings or []:
            sequence = finding.get("sequence")
            review = reviews_by_sequence.get(sequence)
            if review is None:
                continue
            issue_code = "PDF_" + finding_type.upper()
            if issue_code not in review["issues"]:
                review["issues"].append(issue_code)
            review["status"] = "REVIEW_REQUIRED"

    detail_rows = sum(review["row_count"] for review in report_reviews)
    declared_rows = document.get("total_extracted_tube_result_records")
    if declared_rows not in (None, detail_rows):
        blocking.append("DOCUMENT_DETAIL_ROW_COUNT_MISMATCH")
    if dedicated["available"] and dedicated.get("pdf_detail_rows") is not None:
        if dedicated.get("pdf_detail_rows") != dedicated.get("json_detail_rows"):
            blocking.append("PDF_JSON_DETAIL_ROW_COUNT_MISMATCH")

    report_status_counts = Counter(review["status"] for review in report_reviews)
    if blocking:
        status = "BLOCKED"
    elif dedicated["finding_group_count"] or report_status_counts["REVIEW_REQUIRED"]:
        status = "REVIEW_REQUIRED"
    elif report_status_counts["PASS_WITH_NOTE"] or not dedicated["available"]:
        status = "PASS_WITH_NOTE"
    else:
        status = "PASS"

    pair_summary = {
        "pair": prefix,
        "pdf": pdf.name,
        "json": json_path.name,
        "status": status,
        "pdf_page_count": pdf_pages,
        "json_declared_page_count": document.get("page_count"),
        "pdf_sha256": pdf_hash,
        "declared_pdf_sha256": declared_hash,
        "report_count": len(reports),
        "detail_row_count": detail_rows,
        "blocking": blocking,
        "report_status_counts": dict(report_status_counts),
        "common_check_counts": dict(pair_counts),
        "source_issue_categories": dict(source_issue_categories),
        "repeated_equipment_scope_keys": duplicate_keys,
        "dedicated_audit": dedicated,
    }
    return pair_summary, report_reviews


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        "# PDF-IRIS 전수 전문가 검토 결과",
        "",
        f"- 실행시각: {result['generated_at']}",
        f"- 대상: PDF-JSON {result['pair_count']}쌍, 보고서 {result['report_count']}건, 상세 결과 {result['detail_row_count']}행",
        f"- 전체 판정: {result['overall_status']}",
        "- 방식: 원본 불변 읽기 전용, PDF 해시·페이지·상세행·수량·요약 극값·계산식·위치·출처 페이지 대조",
        "",
        "## 파일별 결과",
        "",
        "| 대상 | 판정 | 페이지 | 보고서 | 상세행 | 전용 PDF 대조 | 검토 필요 보고서 | 주요 신호 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for pair in result["pairs"]:
        counts = pair["common_check_counts"]
        signals = []
        for key in (
            "formula_mismatch_rows",
            "large_formula_mismatch_rows",
            "inspected_count_mismatch",
            "location_exceeds_length_rows",
            "documented_source_issues",
        ):
            if counts.get(key):
                signals.append(f"{key}={counts[key]}")
        if pair["dedicated_audit"]["finding_counts"]:
            signals.extend(
                f"PDF:{key}={value}"
                for key, value in pair["dedicated_audit"]["finding_counts"].items()
                if value
            )
        lines.append(
            "| {pair} | {status} | {pages} | {reports} | {rows} | {dedicated} | {review} | {signals} |".format(
                pair=pair["pair"],
                status=pair["status"],
                pages=pair["pdf_page_count"],
                reports=pair["report_count"],
                rows=pair["detail_row_count"],
                dedicated="완료" if pair["dedicated_audit"]["available"] else "공통검사만",
                review=pair["report_status_counts"].get("REVIEW_REQUIRED", 0),
                signals="; ".join(signals) or "없음",
            )
        )
    lines.extend([
        "",
        "## 보고서별 검토 필요 대상",
        "",
        "| 대상 | 순번 | 설비 | Scope | 상세행 | 판정 | 신호 |",
        "|---|---:|---|---|---:|---|---|",
    ])
    for review in result["report_reviews"]:
        if review["status"] != "REVIEW_REQUIRED":
            continue
        lines.append(
            f"| {review['pair']} | {review['sequence']} | {review['equipment_id']} | {review['scope_code']} | "
            f"{review['row_count']} | {review['status']} | {', '.join(review['issues'])} |"
        )
    lines.extend([
        "",
        "## 판정 해석",
        "",
        "- PASS: 자동 점검에서 불일치 없음.",
        "- PASS_WITH_NOTE: 구조 검사는 통과했으나 원문 자체의 기록된 불일치 또는 전용 대조 미구현 등 주석이 있음.",
        "- REVIEW_REQUIRED: 계산식, 수량, 위치 또는 PDF 원문 표기 불일치 후보로 사람이 근거 페이지를 재확인해야 함.",
        "- BLOCKED: 원본 누락, 해시 불일치, 페이지·상세행 수 불일치 등으로 검토 신뢰성을 확보하지 못함.",
        "",
        "이 결과는 PDF 표와 구조화 IRIS 데이터의 정합성 검토이며, 원시 IRIS A/B/C-scan 신호의 결함 판독을 대체하지 않습니다.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pairs: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        print(f"AUDIT_START {pdf.name}", flush=True)
        pair, pair_reviews = audit_pair(pdf)
        pairs.append(pair)
        reviews.extend(pair_reviews)
        print(f"AUDIT_DONE {pdf.name} {pair['status']}", flush=True)

    pair_status_counts = Counter(pair["status"] for pair in pairs)
    report_status_counts = Counter(review["status"] for review in reviews)
    overall = "BLOCKED" if pair_status_counts["BLOCKED"] else (
        "REVIEW_REQUIRED" if pair_status_counts["REVIEW_REQUIRED"] else (
            "PASS_WITH_NOTE" if pair_status_counts["PASS_WITH_NOTE"] else "PASS"
        )
    )
    result = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "overall_status": overall,
        "read_only": True,
        "pair_count": len(pairs),
        "report_count": len(reviews),
        "detail_row_count": sum(review["row_count"] for review in reviews),
        "pair_status_counts": dict(pair_status_counts),
        "report_status_counts": dict(report_status_counts),
        "pairs": pairs,
        "report_reviews": reviews,
    }
    (OUTPUT_DIR / "full_review.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_markdown(result, OUTPUT_DIR / "full_review.md")
    print(json.dumps({
        "overall_status": overall,
        "pair_count": len(pairs),
        "report_count": len(reviews),
        "detail_row_count": result["detail_row_count"],
        "pair_status_counts": dict(pair_status_counts),
        "report_status_counts": dict(report_status_counts),
        "output": str(OUTPUT_DIR),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
