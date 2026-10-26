from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = Path(r"C:\access\hanhwa\IRIS2_DATA")
REVIEW_DIR = ROOT / "outputs" / "pdf_iris_expert_review_20260928"
MANIFEST = ROOT / "outputs" / "vcm_raw_expert_review_20260928" / "raw_file_manifest.csv"
DB_PATH = ROOT / "data" / "heat_exchanger_db3.db"
RAW_EXTENSIONS = {".magdata", ".tis2"}


def magdata_metadata(path: Path) -> dict[str, str]:
    if path.suffix.lower() != ".magdata" or not path.exists():
        return {}
    data = path.read_bytes()[:8 * 1024 * 1024]
    result: dict[str, str] = {}
    for match in re.finditer(rb'<Item\s+Name="([^"]+)"[^>]*>(.*?)</Item>', data, re.S):
        name = match.group(1).decode("utf-8", "replace")
        if name not in {
            "DataRecordDateTime", "RecordDateTime", "DataSetupFile", "SetupFile",
            "DataSoftwareVersion", "SoftwareVersion", "InstrumentModel",
            "InstrumentSerialNumber", "InstrumentLastCalibrationDate",
        }:
            continue
        raw = re.sub(rb"<[^>]+>", b"", match.group(2)).strip()
        result[name] = raw.decode("utf-8", "replace")
    return result


def equipment_code(value: str) -> str | None:
    match = re.search(r"(?<![A-Z0-9])((?:AE|E)-\d{3}[A-Z]?)", value.upper().replace("_", "-"))
    return match.group(1) if match else None


def load_manifest() -> tuple[dict[int, list[dict[str, str]]], dict[str, set[int]], int]:
    by_inspection: dict[int, list[dict[str, str]]] = defaultdict(list)
    years: dict[str, set[int]] = defaultdict(set)
    total = 0
    with MANIFEST.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            total += 1
            parts = Path(row["relative_path"]).parts
            if len(parts) >= 2 and parts[0].upper() in {"VCM1", "VCM2"} and parts[1].isdigit():
                years[parts[0].upper()].add(int(parts[1]))
            if row.get("inspection_id"):
                by_inspection[int(row["inspection_id"])].append(row)
    return by_inspection, years, total


def load_inspections() -> dict[tuple[str, int, str], list[dict[str, Any]]]:
    result: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT upper(pu.unit_code) unit_code, ic.campaign_year,
                   ii.iris_inspection_id, upper(ii.canonical_equipment_code) equipment_code,
                   upper(coalesce(sc.scope_code, 'ALL')) scope_code
              FROM iris_inspection ii
              JOIN inspection_campaign ic ON ic.campaign_id=ii.campaign_id
              JOIN process_unit pu ON pu.unit_id=ic.unit_id
              LEFT JOIN inspection_scope sc ON sc.inspection_scope_id=ii.inspection_scope_id
             WHERE upper(pu.unit_code) IN ('VCM1','VCM2')
            """
        )
        for row in rows:
            item = dict(row)
            result[(item["unit_code"], int(item["campaign_year"]), item["equipment_code"])].append(item)
    finally:
        connection.close()
    return result


def report_rows(pair: str, sequence: int) -> set[tuple[int, int]]:
    path = ROOT / "data" / f"{pair}_IRIS2_all_tube_results.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    for item in payload.get("inspection_reports") or []:
        if int(item["report"]["report_sequence"]) != int(sequence):
            continue
        return {
            (int(row["row"]), int(row["column"]))
            for row in item["tube_results_table"]["records"]
        }
    return set()


def choose_inspection(
    index: dict[tuple[str, int, str], list[dict[str, Any]]],
    unit: str,
    year: int,
    equipment: str,
    scope: str,
) -> tuple[dict[str, Any] | None, str | None]:
    candidates = list(index.get((unit, year, equipment.upper()), []))
    if not candidates:
        return None, "NO_INSPECTION_MATCH"
    if len(candidates) == 1:
        return candidates[0], None
    exact = [item for item in candidates if item["scope_code"] == scope.upper()]
    if len(exact) == 1:
        return exact[0], None
    contains = [item for item in candidates if scope.upper() in item["scope_code"]]
    if len(contains) == 1:
        return contains[0], None
    return None, "MULTIPLE_INSPECTION_MATCHES"


def main() -> None:
    review = json.loads((REVIEW_DIR / "full_review.json").read_text(encoding="utf-8"))
    manifest_by_inspection, available_years, manifest_file_count = load_manifest()
    inspection_index = load_inspections()
    results: list[dict[str, Any]] = []

    for item in review["report_reviews"]:
        match = re.fullmatch(r"(\d{4})(VCM[12]|PE)", item["pair"])
        if not match or match.group(2) == "PE":
            results.append({**item, "raw_status": "SOURCE_NOT_IN_VCM1_VCM2", "raw_file_count": 0})
            continue
        year, unit = int(match.group(1)), match.group(2)
        if year not in available_years.get(unit, set()):
            results.append({**item, "raw_status": "SOURCE_YEAR_NOT_AVAILABLE", "raw_file_count": 0})
            continue
        inspection, error = choose_inspection(
            inspection_index, unit, year, item["equipment_id"], item["scope_code"]
        )
        if error or inspection is None:
            results.append({**item, "raw_status": error, "raw_file_count": 0})
            continue

        inspection_id = int(inspection["iris_inspection_id"])
        manifest_rows = manifest_by_inspection.get(inspection_id, [])
        raw_files = [row for row in manifest_rows if row["extension"].lower() in RAW_EXTENSIONS]
        raw_positions = {
            (int(row["row"]), int(row["column"]))
            for row in raw_files
            if row.get("row") and row.get("column") and row["mapping_status"] == "MATCHED_RESULT"
        }
        expected_positions = report_rows(item["pair"], int(item["sequence"]))
        report_only = sorted(expected_positions - raw_positions)
        raw_only = sorted(raw_positions - expected_positions)
        if expected_positions and expected_positions == raw_positions:
            status = "FULL_TUBE_MATCH"
        elif raw_positions and raw_positions < expected_positions:
            status = "PARTIAL_TUBE_MATCH"
        elif expected_positions and expected_positions < raw_positions:
            status = "RAW_HAS_ADDITIONAL_TUBES"
        elif raw_positions:
            status = "TUBE_SET_DIFFERENCE"
        else:
            status = "NO_MATCHED_RAW_TUBES"

        first_mag = next((row for row in raw_files if row["extension"].lower() == ".magdata"), None)
        metadata = {}
        if first_mag:
            metadata = magdata_metadata(SOURCE_ROOT / first_mag["relative_path"])
        metadata_issues: list[str] = []
        setup_reference_counts: Counter[str] = Counter()
        setup_value = metadata.get("SetupFile") or metadata.get("DataSetupFile") or ""
        setup_equipment = equipment_code(setup_value)
        if setup_equipment and setup_equipment != item["equipment_id"].upper():
            metadata_issues.append("RAW_SETUP_EQUIPMENT_MISMATCH")
            for row in raw_files:
                if row["extension"].lower() != ".magdata":
                    continue
                values = magdata_metadata(SOURCE_ROOT / row["relative_path"])
                setup_reference = values.get("SetupFile") or values.get("DataSetupFile") or ""
                if setup_reference:
                    setup_reference_counts[setup_reference] += 1
        results.append({
            **item,
            "raw_status": status,
            "inspection_id": inspection_id,
            "raw_file_count": len(raw_files),
            "raw_distinct_tube_count": len(raw_positions),
            "report_tube_count": len(expected_positions),
            "report_only_tubes": [f"{row}-{column}" for row, column in report_only],
            "raw_only_tubes": [f"{row}-{column}" for row, column in raw_only],
            "raw_folder_samples": [row["relative_path"] for row in raw_files[:3]],
            "raw_metadata_sample": metadata,
            "raw_metadata_issues": metadata_issues,
            "raw_setup_reference_counts": dict(setup_reference_counts),
        })

    status_counts = Counter(item["raw_status"] for item in results)
    flagged = [item for item in results if item["status"] == "REVIEW_REQUIRED"]
    flagged_counts = Counter(item["raw_status"] for item in flagged)
    exact_flagged = [item for item in flagged if item["raw_status"] == "FULL_TUBE_MATCH"]
    metadata_issue_counts = Counter(
        issue for item in results for issue in item.get("raw_metadata_issues", [])
    )
    result = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(SOURCE_ROOT),
        "read_only": True,
        "manifest_file_count": manifest_file_count,
        "available_years": {key: sorted(value) for key, value in available_years.items()},
        "report_count": len(results),
        "raw_status_counts": dict(status_counts),
        "review_required_count": len(flagged),
        "review_required_raw_status_counts": dict(flagged_counts),
        "review_required_full_tube_match_count": len(exact_flagged),
        "raw_metadata_issue_counts": dict(metadata_issue_counts),
        "reports": results,
    }
    output_json = REVIEW_DIR / "raw_source_review.json"
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# VCM1·VCM2 IRIS 원시파일 추가 대조",
        "",
        f"- 원본 위치: `{SOURCE_ROOT}`",
        f"- 원본 매니페스트: {result['manifest_file_count']}개",
        f"- 대상 보고서: {len(results)}건",
        f"- REVIEW_REQUIRED: {len(flagged)}건",
        f"- REVIEW_REQUIRED 중 원시 Tube 집합 완전 일치: {len(exact_flagged)}건",
        f"- 원시자료 보유 연도: VCM1 {sorted(available_years.get('VCM1', set()))}, VCM2 {sorted(available_years.get('VCM2', set()))}",
        "",
        "## 재검토 대상별 원시파일 연결",
        "",
        "| 대상 | 순번 | 설비/Scope | 기존 신호 | 원시파일 판정 | 원시 메타데이터 | 보고 Tube | 원시 Tube | 원시파일 |",
        "|---|---:|---|---|---|---|---:|---:|---:|",
    ]
    for item in flagged:
        lines.append(
            f"| {item['pair']} | {item['sequence']} | {item['equipment_id']}/{item['scope_code']} | "
            f"{', '.join(item['issues'])} | {item['raw_status']} | {', '.join(item.get('raw_metadata_issues', [])) or '-'} | {item.get('report_tube_count', item['row_count'])} | "
            f"{item.get('raw_distinct_tube_count', 0)} | {item['raw_file_count']} |"
        )
    lines.extend([
        "",
        "## 해석",
        "",
        "- FULL_TUBE_MATCH: 보고서의 Row/Column Tube 집합과 원시 획득파일의 Tube 집합이 일치합니다.",
        "- SOURCE_YEAR_NOT_AVAILABLE: 해당 연도 원시 폴더가 없어 PDF·JSON만으로 검토했습니다.",
        "- NO_INSPECTION_MATCH/NO_MATCHED_RAW_TUBES: 원시 폴더 또는 DB 검사 객체 연결을 추가 확인해야 합니다.",
        "- 원시파일 존재는 검사 Tube와 취득 시점을 입증하지만, 전용 Magnifi/Ectane 신호 해석기 없이 결함 깊이를 독립 재계산한 것은 아닙니다.",
    ])
    (REVIEW_DIR / "raw_source_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "manifest_file_count", "available_years", "report_count", "raw_status_counts",
        "review_required_count", "review_required_raw_status_counts",
        "review_required_full_tube_match_count", "raw_metadata_issue_counts",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
