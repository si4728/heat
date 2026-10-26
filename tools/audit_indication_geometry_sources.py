from __future__ import annotations

import argparse
import base64
import json
import math
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


def finite_nonzero(value) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number != 0
    except (TypeError, ValueError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit source availability for indication angle/length geometry.")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(r"C:\access\hanhwa\IRIS2_DATA"))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    connection = sqlite3.connect(workspace / "data" / "heat_exchanger_db3.db")
    db_counts = connection.execute(
        """SELECT count(*),sum(circumferential_angle_deg IS NOT NULL),
                  sum(defect_length_mm IS NOT NULL)
           FROM iris_indication"""
    ).fetchone()
    source_counts: Counter[str] = Counter()
    csv_explicit_angle = csv_explicit_length = 0
    for (raw_text,) in connection.execute("SELECT raw_json FROM iris_indication"):
        raw = json.loads(raw_text or "{}")
        source_counts[raw.get("source_type", "UNKNOWN")] += 1
        keys = {str(key).lower() for key in (raw.get("data") or {})}
        csv_explicit_angle += bool(keys & {"circumferentialangle", "circumferential_angle_deg", "angle", "degrees"})
        csv_explicit_length += bool(keys & {"defectlength", "defect_length_mm", "extentlength"})
    connection.close()

    extraction = json.loads((workspace / "tmp" / "vcm_raw_enrichment" / "mdb_extract.json").read_text(encoding="utf-8"))
    result_rows: list[dict] = []
    for document in extraction.get("documents", []):
        for table_name, rowsets in document.get("tables", {}).items():
            if table_name.lower() != "result":
                continue
            for rowset in rowsets:
                result_rows.extend(rowset if isinstance(rowset, list) else [rowset])
    candidates = {
        "resDegrees_nonzero": sum(finite_nonzero(row.get("resDegrees")) for row in result_rows),
        "resExtent_nonzero": sum(finite_nonzero(row.get("resExtent")) for row in result_rows),
        "resLength_nonzero": sum(finite_nonzero(row.get("resLength")) for row in result_rows),
        "resStart_present": sum(row.get("resStart") not in (None, "") for row in result_rows),
        "resEnd_present": sum(row.get("resEnd") not in (None, "") for row in result_rows),
    }
    nonzero_lengths = [float(row["resLength"]) for row in result_rows if finite_nonzero(row.get("resLength"))]
    scoped_files = [
        path for path in args.source_root.rglob("*")
        if path.is_file() and any(part.upper() in {"VCM1", "VCM2"} for part in path.parts)
    ]
    extension_counts = Counter(path.suffix.lower() or "[no extension]" for path in scoped_files)
    magsetup_files = [path for path in scoped_files if path.suffix.lower() == ".magsetup"]
    defect_length_enabled: Counter[str] = Counter()
    defect_angles: list[float] = []
    for path in magsetup_files:
        content = path.read_bytes()
        for token in re.findall(rb"[A-Za-z0-9+/=]{1000,}", content):
            try:
                decoded = base64.b64decode(token).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                continue
            if "<ConfigSerialization" not in decoded:
                continue
            for match in re.finditer(r"<ID>DefectLength</ID>(.*?)</Item>", decoded, re.S):
                enabled = re.search(r"<IsEnabled>(.*?)</IsEnabled>", match.group(1))
                defect_length_enabled[(enabled.group(1).lower() if enabled else "unknown")] += 1
            defect_angles.extend(float(value) for value in re.findall(r"<DefectAngle>([^<]+)</DefectAngle>", decoded))
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database": {
            "indication_count": db_counts[0],
            "circumferential_angle_populated": db_counts[1] or 0,
            "defect_length_populated": db_counts[2] or 0,
            "source_type_counts": dict(source_counts),
        },
        "csv_detail": {
            "rows": source_counts.get("CSV_DETAIL", 0),
            "explicit_angle_fields": csv_explicit_angle,
            "explicit_defect_length_fields": csv_explicit_length,
        },
        "mdb_result": {
            "documents_read": extraction.get("document_count"),
            "read_errors": extraction.get("error_count"),
            "result_rows": len(result_rows),
            **candidates,
            "resLength_min": min(nonzero_lengths) if nonzero_lengths else None,
            "resLength_max": max(nonzero_lengths) if nonzero_lengths else None,
            "resLength_semantic_status": "AMBIGUOUS_NOT_APPLIED",
        },
        "raw_waveform_sources": {
            "source_root": str(args.source_root),
            "vcm1_vcm2_file_count": len(scoped_files),
            "extension_counts": dict(extension_counts.most_common()),
            "tis2_files": extension_counts.get(".tis2", 0),
            "magdata_files": extension_counts.get(".magdata", 0),
            "magsetup_files": len(magsetup_files),
            "defect_length_calculator_enabled_counts": dict(defect_length_enabled),
            "defect_angle_configuration_count": len(defect_angles),
            "defect_angle_configuration_unique_values": sorted(set(defect_angles)),
            "interpretation": "DefectLength is disabled in every decoded VCM1/VCM2 Magnifi setup. DefectAngle is a repeated setup parameter, not a per-indication circumferential coordinate.",
        },
        "decision": {
            "database_update_performed": False,
            "circumferential_angle": "BLOCKED_NO_VALID_SOURCE_VALUES",
            "defect_length": "BLOCKED_UNVERIFIED_FIELD_SEMANTICS",
            "reason": "resDegrees/resExtent are zero; resLength is populated but lacks a verified field definition and behaves like acquisition/scan length. Fabricating or relabeling it as defect length would be unsafe.",
            "required_next_input": "Manufacturer SDK or validated TIS2/MAGDATA parser plus field definition/calibration, or an approved source export containing per-indication angle and defect length.",
        },
    }
    output_dir = workspace / "outputs" / "indication_geometry_audit_20260909"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "indication_geometry_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = f"""# 결함 형상 데이터 확보 감사 결과

- 결함 지시: {db_counts[0]:,}건
- 원주각 등록: {db_counts[1] or 0:,}건
- 결함 길이 등록: {db_counts[2] or 0:,}건
- MDB Result 검사: {len(result_rows):,}행 / 읽기 오류 {extraction.get('error_count', 0)}건
- `resDegrees` 비영값: {candidates['resDegrees_nonzero']:,}건
- `resExtent` 비영값: {candidates['resExtent_nonzero']:,}건
- `resLength` 비영값: {candidates['resLength_nonzero']:,}건 (최소 {report['mdb_result']['resLength_min']}, 최대 {report['mdb_result']['resLength_max']})
- TIS2 원시 파형: {extension_counts.get('.tis2', 0):,}개 / MAGDATA 원시 파형: {extension_counts.get('.magdata', 0):,}개
- Magnifi 설정: {len(magsetup_files):,}개, `DefectLength` 계산 활성화 true {defect_length_enabled.get('true', 0):,}건 / false {defect_length_enabled.get('false', 0):,}건

## 판정

원주각은 유효한 원천값이 없어 확보 불가입니다. 설정의 `DefectAngle`은 결함별 원주좌표가 아니라 76개 설정에 동일하게 반복된 장비 계산 파라미터입니다. `resLength`는 값은 있으나 필드 정의와 단위·교정 근거가 없고 검사별 거의 고정된 값이 반복되며, 76개 설정 모두 `DefectLength` 계산이 비활성화되어 결함 길이로 전용하지 않았습니다. DB에는 추정값을 기록하지 않았습니다.

실데이터 기반 2D 펼침도와 3D 국부 패치 검증을 완료하려면 제조사 SDK 또는 검증된 TIS2/MAGDATA 파서와 좌표·단위 교정 정보, 혹은 원주각/결함 길이가 명시된 승인 원천 export가 필요합니다.
"""
    (output_dir / "INDICATION_GEOMETRY_AUDIT.md").write_text(markdown, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
