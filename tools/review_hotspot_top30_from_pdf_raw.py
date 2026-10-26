"""Review the latest Top-30 spatial Hotspots against PDF and VCM raw evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from iris2.hx_configuration import DB_PATH, ML_ARTIFACT_ROOT  # noqa: E402
from iris2.ml.datasets import load_cohort_a  # noqa: E402
from iris2.ml.readonly_db import database_sha256  # noqa: E402
from iris2.ml.review import latest_run_directory  # noqa: E402
from iris2.ml.snapshots import canonical_rows_sha256  # noqa: E402


FULL_REVIEW = ROOT / "outputs" / "pdf_iris_expert_review_20260928" / "full_review.json"
RAW_REVIEW = ROOT / "outputs" / "pdf_iris_expert_review_20260928" / "raw_source_review.json"
RAW_MANIFEST = ROOT / "outputs" / "vcm_raw_expert_review_20260928" / "raw_file_manifest.csv"
REVIEWER = "AI_PDF_RAW_EVIDENCE_REVIEW_20260928"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_report(source_file: str, sequence: int) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = _load(ROOT / "data" / source_file)
    matches = [
        item for item in payload.get("inspection_reports") or []
        if int(item["report"]["report_sequence"]) == sequence
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one source report: {source_file} sequence {sequence}")
    return payload, matches[0]


def _source_row(report: dict[str, Any], row_no: int, column_no: int) -> dict[str, Any] | None:
    matches = [
        row for row in report["tube_results_table"]["records"]
        if int(row["row"]) == row_no and int(row["column"]) == column_no
    ]
    return matches[0] if len(matches) == 1 else None


def _same(left: Any, right: Any, tolerance: float = 0.011) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= tolerance


def main() -> int:
    run = latest_run_directory(ML_ARTIFACT_ROOT, "evaluation/spatial_pilot.json")
    if run is None:
        raise RuntimeError("No spatial Hotspot artifact is available")
    summary = _load(run / "run_summary.json")
    spatial = _load(run / "evaluation" / "spatial_pilot.json")
    snapshot = _load(run / "data" / "dataset_snapshot.json")
    rows = spatial.get("top_30") or []
    if len(rows) != 30:
        raise RuntimeError(f"Expected 30 Hotspot candidates, got {len(rows)}")
    current_hash = database_sha256(DB_PATH)
    if current_hash != summary.get("database_sha256_after"):
        current_rows_hash = canonical_rows_sha256(load_cohort_a(DB_PATH))
        if current_rows_hash != snapshot.get("rows_sha256"):
            raise RuntimeError("Operational dataset differs from the Hotspot run")

    full = _load(FULL_REVIEW)
    raw = _load(RAW_REVIEW)
    full_index = {(item["pair"], int(item["sequence"])): item for item in full["report_reviews"]}
    raw_index = {(item["pair"], int(item["sequence"])): item for item in raw["reports"]}
    manifest: dict[int, list[dict[str, str]]] = {}
    with RAW_MANIFEST.open(encoding="utf-8-sig", newline="") as source:
        for item in csv.DictReader(source):
            if item.get("tube_result_id"):
                manifest.setdefault(int(item["tube_result_id"]), []).append(item)

    connection = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    reviews = []
    try:
        for rank, candidate in enumerate(rows, 1):
            inspection = connection.execute(
                """SELECT i.report_sequence,i.canonical_equipment_code,i.original_equipment_id,
                          d.source_file
                     FROM iris_inspection i
                     JOIN source_document d ON d.source_document_id=i.source_document_id
                    WHERE i.iris_inspection_id=?""",
                (candidate["iris_inspection_id"],),
            ).fetchone()
            if inspection is None:
                raise RuntimeError(f"Inspection missing: {candidate['iris_inspection_id']}")
            pair = inspection["source_file"].replace("_IRIS2_all_tube_results.json", "")
            sequence = int(inspection["report_sequence"])
            payload, report = _source_report(inspection["source_file"], sequence)
            source = _source_row(report, int(candidate["row_no"]), int(candidate["column_no"]))
            pdf_row_exact = bool(
                source
                and _same(source.get("minimum_wall_thickness_mm"), candidate.get("minimum_wall_thickness_mm"))
                and _same(source.get("wall_loss_percent"), candidate.get("wall_loss_percent"))
            )
            layout_exact = all(
                candidate.get(key) == expected
                for key, expected in (
                    ("revision_status", "APPROVED"),
                    ("verification_status", "VERIFIED"),
                    ("mapping_status", "EXISTING_TUBE_MATCH"),
                )
            ) and candidate.get("canonical_x") is not None and candidate.get("canonical_y") is not None
            raw_files = manifest.get(int(candidate["iris_tube_result_id"]), [])
            direct_raw = [item for item in raw_files if item.get("mapping_status") == "MATCHED_RESULT"]
            report_review = full_index[(pair, sequence)]
            raw_review = raw_index[(pair, sequence)]
            limitations = []
            if report_review.get("status") == "REVIEW_REQUIRED":
                limitations.extend(report_review.get("issues") or [])
            raw_metadata = raw_review.get("raw_metadata_issues") or []
            limitations.extend(raw_metadata)
            if not direct_raw:
                limitations.append(f"RAW_{raw_review.get('raw_status') or 'NOT_MATCHED'}")

            if not pdf_row_exact or not layout_exact or not candidate.get("evidence_tubes"):
                decision = "RECHECK_REQUIRED"
                confidence = "LOW"
            elif direct_raw and not limitations:
                decision = "CONFIRMED_WITH_RAW"
                confidence = "HIGH"
            else:
                decision = "CONFIRMED_WITH_LIMITATION"
                confidence = "MEDIUM"

            reviews.append({
                "rank": rank,
                "decision": decision,
                "confidence": confidence,
                "pair": pair,
                "report_sequence": sequence,
                "equipment_code": inspection["canonical_equipment_code"],
                "source_equipment_id": inspection["original_equipment_id"],
                "inspection_year": int(candidate["inspection_year"]),
                "iris_inspection_id": int(candidate["iris_inspection_id"]),
                "iris_tube_result_id": int(candidate["iris_tube_result_id"]),
                "tube_id": int(candidate["tube_id"]),
                "tube_no": candidate["tube_no"],
                "source_page": int(candidate["source_page"]),
                "minimum_wall_thickness_mm": candidate.get("minimum_wall_thickness_mm"),
                "wall_loss_percent": candidate.get("wall_loss_percent"),
                "hotspot_score": candidate.get("hotspot_score"),
                "change_state": candidate.get("change_state"),
                "pdf_source_file": payload["document"]["source_file"],
                "pdf_row_exact": pdf_row_exact,
                "pdf_report_review_status": report_review.get("status"),
                "approved_layout_verified": layout_exact,
                "neighbor_evidence_count": len(candidate.get("evidence_tubes") or []),
                "raw_report_status": raw_review.get("raw_status"),
                "raw_direct_match_count": len(direct_raw),
                "raw_files": [item["relative_path"] for item in direct_raw],
                "limitations": sorted(set(limitations)),
                "review_note": (
                    "PDF Tube row, measurement values, approved layout, and neighbor evidence confirmed."
                    if decision == "CONFIRMED_WITH_RAW"
                    else "PDF Tube row and approved spatial evidence confirmed; listed source limitations remain."
                    if decision == "CONFIRMED_WITH_LIMITATION"
                    else "Source or spatial evidence mismatch requires recheck."
                ),
            })
    finally:
        connection.close()

    counts = Counter(item["decision"] for item in reviews)
    confirmed = sum(item["decision"].startswith("CONFIRMED") for item in reviews)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": REVIEWER,
        "review_type": "PDF_RAW_EVIDENCE_HOTSPOT_TOP30",
        "run_id": summary["run_id"],
        "model_version": spatial["model_version"],
        "database_sha256": current_hash,
        "dataset_rows_sha256": snapshot.get("rows_sha256"),
        "candidate_count": len(reviews),
        "reviewed_count": len(reviews),
        "confirmed_count": confirmed,
        "confirmation_rate": confirmed / len(reviews),
        "decision_counts": dict(sorted(counts.items())),
        "expert_top30_confirmation_ge_60_percent": confirmed / len(reviews) >= 0.60,
        "engineering_risk_grade_confirmed": False,
        "automatic_decision_enabled": False,
        "scope_note": (
            "Confirmation means that the reported measurement and approved-layout spatial evidence support retaining "
            "the item as an expert review candidate. It is not an automatic damage-mechanism or fitness-for-service decision."
        ),
        "reviews": reviews,
    }
    result["review_fingerprint"] = hashlib.sha256(
        json.dumps(result["reviews"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    output = run / "expert_review"
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / "hotspot_top30_review.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_path = output / "hotspot_top30_review.csv"
    fields = [
        "rank", "decision", "confidence", "pair", "report_sequence", "equipment_code",
        "source_equipment_id", "inspection_year", "tube_no", "source_page",
        "minimum_wall_thickness_mm", "wall_loss_percent", "hotspot_score", "change_state",
        "pdf_row_exact", "approved_layout_verified", "neighbor_evidence_count",
        "raw_report_status", "raw_direct_match_count", "limitations", "iris_inspection_id",
        "iris_tube_result_id", "tube_id",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for item in reviews:
            row = {key: item.get(key) for key in fields}
            row["limitations"] = ";".join(item["limitations"])
            writer.writerow(row)
    md_path = output / "HOTSPOT_TOP30_REVIEW.md"
    lines = [
        "# Hotspot Top-30 PDF/IRIS evidence review", "",
        f"- Run: `{result['run_id']}`", f"- Reviewer: `{REVIEWER}`",
        f"- Reviewed: {len(reviews)}/30", f"- Confirmed as review candidates: {confirmed}/30 ({result['confirmation_rate']:.0%})",
        f"- Decisions: {dict(sorted(counts.items()))}",
        "- Engineering risk grade confirmation: disabled", "",
        "|Rank|Decision|Confidence|Equipment|Tube|Year|PDF page|Wall loss|Raw match|Limitations|", "|---:|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for item in reviews:
        lines.append(
            f"|{item['rank']}|{item['decision']}|{item['confidence']}|{item['equipment_code']}|"
            f"{item['tube_no']}|{item['inspection_year']}|{item['source_page']}|{item['wall_loss_percent']:.2f}%|"
            f"{item['raw_direct_match_count']}|{', '.join(item['limitations']) or '-'}|"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        key: result[key] for key in (
            "run_id", "candidate_count", "reviewed_count", "confirmed_count", "confirmation_rate",
            "decision_counts", "expert_top30_confirmation_ge_60_percent", "engineering_risk_grade_confirmed",
        )
    } | {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0 if counts.get("RECHECK_REQUIRED", 0) == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
