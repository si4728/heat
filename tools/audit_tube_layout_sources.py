from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable


EQUIPMENT_PATTERN = re.compile(r"(?<![A-Z0-9])((?:AE|E)-\d{3}[A-Z]?)")


def flatten(value: Iterable[Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in value or []:
        if isinstance(item, list):
            rows.extend(row for row in item if isinstance(row, dict))
        elif isinstance(item, dict):
            rows.append(item)
    return rows


def equipment_code(text: str) -> str | None:
    match = EQUIPMENT_PATTERN.search(text.upper().replace("_", "-"))
    return match.group(1) if match else None


def cardinal_rotation(orientation: str | None) -> int:
    normalized = re.sub(r"[^A-Z]+", " ", (orientation or "").upper()).strip()
    tokens = set(normalized.split())
    for token, degrees in (("NORTH", 0), ("EAST", 90), ("SOUTH", 180), ("WEST", 270)):
        if token in tokens:
            return degrees
    if "REAR" in tokens or "BOTTOM" in tokens:
        return 180
    return 0


def coordinate(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class InspectionMatch:
    inspection_id: int
    heat_exchanger_id: int
    bundle_id: int
    bundle_code: str
    scope_code: str
    equipment_code: str
    master_equipment_code: str
    campaign_year: int
    expected_tube_count: int | None


class LayoutAudit:
    def __init__(self, db_path: Path, mdb_json: Path, output_dir: Path):
        self.db_path = db_path.resolve()
        self.mdb_json = mdb_json.resolve()
        self.output_dir = output_dir.resolve()
        uri = self.db_path.as_uri() + "?mode=ro"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.row_factory = sqlite3.Row
        self.inspection_index: dict[tuple[str, int, str], list[InspectionMatch]] = defaultdict(list)
        self.existing_tubes: dict[tuple[int, int, int], sqlite3.Row] = {}
        self.conflicts: list[dict[str, Any]] = []
        self._load_database_index()

    def close(self) -> None:
        self.connection.close()

    def _load_database_index(self) -> None:
        query = """
            SELECT upper(pu.unit_code) AS unit_code,
                   ic.campaign_year,
                   ii.iris_inspection_id,
                   ii.heat_exchanger_id,
                   upper(ii.canonical_equipment_code) AS canonical_equipment_code,
                   upper(e.equipment_code) AS master_equipment_code,
                   ii.bundle_id,
                   coalesce(tb.bundle_code, '') AS bundle_code,
                   upper(coalesce(sc.scope_code, '')) AS scope_code,
                   tb.expected_tube_count
            FROM iris_inspection ii
            JOIN inspection_campaign ic ON ic.campaign_id=ii.campaign_id
            JOIN process_unit pu ON pu.unit_id=ic.unit_id
            JOIN heat_exchanger hx ON hx.heat_exchanger_id=ii.heat_exchanger_id
            JOIN equipment e ON e.equipment_id=hx.equipment_id
            LEFT JOIN tube_bundle tb ON tb.bundle_id=ii.bundle_id
            LEFT JOIN inspection_scope sc ON sc.inspection_scope_id=ii.inspection_scope_id
            WHERE upper(pu.unit_code) IN ('VCM1', 'VCM2')
        """
        for row in self.connection.execute(query):
            if row["bundle_id"] is None:
                continue
            match = InspectionMatch(
                inspection_id=int(row["iris_inspection_id"]),
                heat_exchanger_id=int(row["heat_exchanger_id"]),
                bundle_id=int(row["bundle_id"]),
                bundle_code=str(row["bundle_code"]),
                scope_code=str(row["scope_code"]),
                equipment_code=str(row["canonical_equipment_code"]),
                master_equipment_code=str(row["master_equipment_code"]),
                campaign_year=int(row["campaign_year"]),
                expected_tube_count=(
                    int(row["expected_tube_count"])
                    if row["expected_tube_count"] is not None else None
                ),
            )
            key = (str(row["unit_code"]), match.campaign_year, match.equipment_code)
            self.inspection_index[key].append(match)

        for row in self.connection.execute(
            """SELECT tube_id, bundle_id, tube_no, row_no, column_no,
                      position_x, position_y, position_locked
               FROM heat_exchanger_tube
               WHERE row_no IS NOT NULL AND column_no IS NOT NULL"""
        ):
            key = (int(row["bundle_id"]), int(row["row_no"]), int(row["column_no"]))
            self.existing_tubes[key] = row

    def resolve_document(self, relative_path: str) -> tuple[InspectionMatch | None, str | None]:
        parts = PureWindowsPath(relative_path).parts
        if len(parts) < 3 or parts[0].upper() not in {"VCM1", "VCM2"} or not parts[1].isdigit():
            return None, "PATH_SCOPE"
        unit, year, folder = parts[0].upper(), int(parts[1]), parts[2]
        code = equipment_code(folder)
        candidates = list(self.inspection_index.get((unit, year, code or ""), []))
        if not candidates:
            return None, "NO_INSPECTION_CANDIDATE"

        path_text = str(PureWindowsPath(relative_path)).upper().replace("_", "-")
        if len(candidates) > 1 and code:
            bundle_match = re.search(rf"{re.escape(code)}-?([12])(?:\D|$)", path_text)
            if bundle_match:
                narrowed = [item for item in candidates if item.bundle_code.upper() == bundle_match.group(1)]
                if len(narrowed) == 1:
                    candidates = narrowed
        if len(candidates) > 1:
            side = None
            if any(token in path_text for token in ("BOTTOM", "(BOM)", " BTM")):
                side = "BTM"
            elif "TOP" in path_text:
                side = "TOP"
            if side:
                narrowed = [item for item in candidates if side in item.scope_code]
                if len(narrowed) == 1:
                    candidates = narrowed
        if len(candidates) != 1:
            return None, "MULTIPLE_INSPECTION_CANDIDATES"
        return candidates[0], None

    def run(self) -> dict[str, Any]:
        payload = json.loads(self.mdb_json.read_text(encoding="utf-8"))
        candidates: dict[tuple[int, int, int], dict[str, Any]] = {}
        revisions: list[dict[str, Any]] = []
        orientation_rows: list[dict[str, Any]] = []

        for document in payload.get("documents", []):
            path = str(document.get("path") or "")
            match, error = self.resolve_document(path)
            if error or match is None:
                self.conflicts.append({
                    "code": error or "UNRESOLVED_DOCUMENT",
                    "source_path": path,
                    "bundle_id": "",
                    "row": "",
                    "column": "",
                    "detail": "MDB 문서를 단일 검사에 연결하지 못함",
                })
                continue

            tables = document.get("tables") or {}
            tube_rows = flatten(tables.get("tube"))
            sections = [row for row in flatten(tables.get("section")) if int(row.get("sectTubes") or 0) > 0]
            if not sections:
                self.conflicts.append({
                    "code": "NO_ACTIVE_SECTION",
                    "source_path": path,
                    "bundle_id": match.bundle_id,
                    "row": "",
                    "column": "",
                    "detail": "양수 튜브 수를 가진 Section이 없음",
                })
                continue

            for section in sections:
                section_id = int(section.get("sectId"))
                rows = [row for row in tube_rows if int(row.get("sectId")) == section_id]
                raw_orientation = str(section.get("sectName") or "").strip()
                seen_grid: set[tuple[int, int]] = set()
                seen_xy: set[tuple[float, float]] = set()
                missing_xy = 0
                for row in rows:
                    try:
                        row_no, column_no = int(row["tubeRow"]), int(row["tubeCol"])
                    except (KeyError, TypeError, ValueError):
                        self.conflicts.append({
                            "code": "INVALID_ROW_COLUMN", "source_path": path,
                            "bundle_id": match.bundle_id, "row": row.get("tubeRow", ""),
                            "column": row.get("tubeCol", ""), "detail": "Row/Column 변환 실패",
                        })
                        continue
                    source_x, source_y = coordinate(row.get("tubeXPos")), coordinate(row.get("tubeYPos"))
                    original_x = coordinate(row.get("tubeOrgXPos"))
                    original_y = coordinate(row.get("tubeOrgYPos"))
                    if source_x is None or source_y is None:
                        missing_xy += 1
                    grid_key = (row_no, column_no)
                    if grid_key in seen_grid:
                        self.conflicts.append({
                            "code": "DUPLICATE_ROW_COLUMN_IN_SECTION", "source_path": path,
                            "bundle_id": match.bundle_id, "row": row_no, "column": column_no,
                            "detail": f"section_id={section_id}",
                        })
                    seen_grid.add(grid_key)
                    if source_x is not None and source_y is not None:
                        xy_key = (source_x, source_y)
                        if xy_key in seen_xy:
                            self.conflicts.append({
                                "code": "DUPLICATE_XY_IN_SECTION", "source_path": path,
                                "bundle_id": match.bundle_id, "row": row_no, "column": column_no,
                                "detail": f"x={source_x}, y={source_y}, section_id={section_id}",
                            })
                        seen_xy.add(xy_key)

                    key = (match.bundle_id, row_no, column_no)
                    existing = self.existing_tubes.get(key)
                    value = {
                        "bundle_id": match.bundle_id,
                        "heat_exchanger_id": match.heat_exchanger_id,
                        "master_equipment_code": match.master_equipment_code,
                        "canonical_equipment_code": match.equipment_code,
                        "bundle_code": match.bundle_code,
                        "row": row_no,
                        "column": column_no,
                        "source_x": source_x,
                        "source_y": source_y,
                        "original_x": original_x,
                        "original_y": original_y,
                        "coordinate_unit": "SOURCE_NATIVE",
                        "source_paths": [path],
                        "source_section_ids": [section_id],
                        "source_orientations": [raw_orientation],
                        "existing_tube_id": int(existing["tube_id"]) if existing else "",
                        "existing_tube_no": str(existing["tube_no"]) if existing else "",
                        "existing_position_x": existing["position_x"] if existing else "",
                        "existing_position_y": existing["position_y"] if existing else "",
                        "mapping_status": "EXISTING_TUBE_MATCH" if existing else "NEW_TUBE_CANDIDATE",
                        "review_status": "PENDING",
                    }
                    previous = candidates.get(key)
                    if previous:
                        if (previous["source_x"], previous["source_y"]) != (source_x, source_y):
                            self.conflicts.append({
                                "code": "MULTIPLE_SOURCE_COORDINATES", "source_path": path,
                                "bundle_id": match.bundle_id, "row": row_no, "column": column_no,
                                "detail": (
                                    f"existing=({previous['source_x']},{previous['source_y']}), "
                                    f"candidate=({source_x},{source_y})"
                                ),
                            })
                            previous["review_status"] = "CONFLICT"
                        if path not in previous["source_paths"]:
                            previous["source_paths"].append(path)
                        if section_id not in previous["source_section_ids"]:
                            previous["source_section_ids"].append(section_id)
                        if raw_orientation not in previous["source_orientations"]:
                            previous["source_orientations"].append(raw_orientation)
                    else:
                        candidates[key] = value

                section_total = int(section.get("sectTubes") or 0)
                count_status = "MATCH" if section_total == len(rows) else "MISMATCH"
                if count_status == "MISMATCH":
                    self.conflicts.append({
                        "code": "SECTION_TUBE_COUNT_MISMATCH", "source_path": path,
                        "bundle_id": match.bundle_id, "row": "", "column": "",
                        "detail": f"reported={section_total}, extracted={len(rows)}",
                    })
                revisions.append({
                    "source_path": path,
                    "inspection_id": match.inspection_id,
                    "heat_exchanger_id": match.heat_exchanger_id,
                    "master_equipment_code": match.master_equipment_code,
                    "canonical_equipment_code": match.equipment_code,
                    "campaign_year": match.campaign_year,
                    "bundle_id": match.bundle_id,
                    "bundle_code": match.bundle_code,
                    "scope_code": match.scope_code,
                    "section_id": section_id,
                    "section_name": raw_orientation,
                    "source_tube_count": len(rows),
                    "section_reported_tube_count": section_total,
                    "bundle_expected_tube_count": match.expected_tube_count,
                    "count_status": count_status,
                    "missing_xy_count": missing_xy,
                    "row_spacing": section.get("sectRowSpacing"),
                    "column_spacing": section.get("sectColSpacing"),
                    "origin_code": section.get("sectOrigin"),
                    "scale_metric": section.get("sectScaleMetric"),
                    "grid_mode": section.get("sectGrid"),
                    "revision_status": "DRAFT_REVIEW",
                })
                orientation_rows.append({
                    "source_path": path,
                    "bundle_id": match.bundle_id,
                    "scope_code": match.scope_code,
                    "raw_orientation": raw_orientation,
                    "suggested_rotation_degrees": cardinal_rotation(raw_orientation),
                    "suggested_flip_x": "UNDECIDED",
                    "suggested_flip_y": "UNDECIDED",
                    "origin_code": section.get("sectOrigin"),
                    "review_status": "REVIEW_REQUIRED",
                    "review_reason": "Front/Rear/Top/Bottom 시점과 도면 축 기준 확인 필요",
                })

        self.output_dir.mkdir(parents=True, exist_ok=True)
        candidate_rows = sorted(candidates.values(), key=lambda row: (row["bundle_id"], row["row"], row["column"]))
        for row in candidate_rows:
            row["source_paths"] = " | ".join(row["source_paths"])
            row["source_section_ids"] = " | ".join(map(str, row["source_section_ids"]))
            row["source_orientations"] = " | ".join(row["source_orientations"])
        self._write_csv("tube_layout_candidates.csv", candidate_rows)
        self._write_csv("layout_revisions.csv", revisions)
        self._write_csv("orientation_review.csv", orientation_rows)
        self._write_csv("layout_conflicts.csv", self.conflicts)
        self._write_pilot_html(candidate_rows)

        mapping_counts = Counter(row["mapping_status"] for row in candidate_rows)
        conflict_counts = Counter(row["code"] for row in self.conflicts)
        revision_counts = Counter(row["count_status"] for row in revisions)
        summary = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "database": str(self.db_path),
            "database_mode": "READ_ONLY",
            "mdb_extract": str(self.mdb_json),
            "source_document_count": len(payload.get("documents", [])),
            "layout_revision_count": len(revisions),
            "unique_bundle_count": len({row["bundle_id"] for row in candidate_rows}),
            "unique_coordinate_count": len(candidate_rows),
            "mapping_counts": dict(mapping_counts),
            "revision_count_checks": dict(revision_counts),
            "conflict_count": len(self.conflicts),
            "conflicts_by_code": dict(conflict_counts),
            "orientation_review_count": len(orientation_rows),
            "database_changes": 0,
            "approval_required_before_database_apply": True,
            "outputs": [
                "tube_layout_candidates.csv", "layout_revisions.csv",
                "orientation_review.csv", "layout_conflicts.csv", "pilot_layout_review.html",
            ],
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.output_dir / "README.md").write_text(self._summary_markdown(summary), encoding="utf-8")
        return summary

    def _write_csv(self, name: str, rows: list[dict[str, Any]]) -> None:
        path = self.output_dir / name
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        fieldnames = list(rows[0])
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def _write_pilot_html(self, candidates: list[dict[str, Any]]) -> None:
        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            grouped[int(row["bundle_id"])].append(row)
        preferred = ("E-281B", "E-331A", "E-282", "E-106")
        selected: list[tuple[int, list[dict[str, Any]]]] = []
        used: set[int] = set()
        for code in preferred:
            for bundle_id, rows in grouped.items():
                if bundle_id not in used and rows[0]["canonical_equipment_code"] == code:
                    selected.append((bundle_id, rows)); used.add(bundle_id); break
        for bundle_id, rows in sorted(grouped.items(), key=lambda item: len(item[1])):
            if len(selected) >= 4:
                break
            if bundle_id not in used:
                selected.append((bundle_id, rows)); used.add(bundle_id)

        cards = []
        for bundle_id, rows in selected[:4]:
            cards.append(self._pilot_card(bundle_id, rows))
        body = "\n".join(cards)
        document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>Tube Layout Pilot Review</title>
<style>
body{{font-family:"Malgun Gothic",sans-serif;margin:24px;background:#f4f7fb;color:#172033}}
h1{{margin-bottom:8px}}.note{{color:#526173;margin-bottom:24px}}.card{{background:white;border:1px solid #d9e0e8;border-radius:12px;padding:18px;margin:18px 0}}
.meta{{color:#526173;margin-bottom:12px}}.panels{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}svg{{width:100%;height:420px;background:#0f172a;border-radius:8px}}
.legend{{font-size:13px;color:#526173}}@media(max-width:900px){{.panels{{grid-template-columns:1fr}}}}
</style></head><body><h1>Tube Layout Pilot Review</h1>
<p class="note">왼쪽은 MDB 원천 X/Y, 오른쪽은 현재 DB Row/Column입니다. 좌표 단위와 축 반전은 승인 전까지 확정하지 않습니다.</p>
{body}</body></html>"""
        (self.output_dir / "pilot_layout_review.html").write_text(document, encoding="utf-8")

    def _pilot_card(self, bundle_id: int, rows: list[dict[str, Any]]) -> str:
        title = f"{rows[0]['canonical_equipment_code']} · Bundle {rows[0]['bundle_code']}"
        source_svg = self._scatter_svg(rows, "source_x", "source_y")
        grid_svg = self._scatter_svg(rows, "column", "row")
        existing = sum(row["mapping_status"] == "EXISTING_TUBE_MATCH" for row in rows)
        return f"""<section class="card"><h2>{html.escape(title)}</h2>
<div class="meta">bundle_id {bundle_id} · 좌표 {len(rows):,}개 · 기존 튜브 연결 {existing:,}개 · 방향 {html.escape(rows[0]['source_orientations'])}</div>
<div class="panels"><div><h3>MDB 원천 X/Y</h3>{source_svg}</div><div><h3>현재 Row/Column</h3>{grid_svg}</div></div>
<p class="legend">초록: 기존 튜브와 연결 · 주황: 신규 튜브 마스터 후보</p></section>"""

    @staticmethod
    def _scatter_svg(rows: list[dict[str, Any]], x_key: str, y_key: str) -> str:
        points = [(float(row[x_key]), float(row[y_key]), row) for row in rows if row[x_key] not in (None, "") and row[y_key] not in (None, "")]
        if not points:
            return '<svg viewBox="0 0 640 420"><text x="320" y="210" fill="white" text-anchor="middle">좌표 없음</text></svg>'
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
        span_x, span_y = max(max_x - min_x, 1), max(max_y - min_y, 1)
        circles = []
        radius = max(1.2, min(5.0, 120 / max(len(points) ** 0.5, 1)))
        for x, y, row in points:
            sx = 35 + (x - min_x) / span_x * 570
            # CARTO/PDF Tube Map 화면은 X+가 오른쪽, Y+가 아래쪽이다.
            sy = 35 + (y - min_y) / span_y * 350
            color = "#14b8a6" if row["mapping_status"] == "EXISTING_TUBE_MATCH" else "#f59e0b"
            circles.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="{radius:.2f}" fill="{color}"/>')
        return '<svg viewBox="0 0 640 420" role="img">' + "".join(circles) + '<path d="M28 35H615M35 28V395" stroke="#94a3b8"/><text x="610" y="55" fill="#cbd5e1">X+</text><text x="8" y="395" fill="#cbd5e1">Y+</text></svg>'

    @staticmethod
    def _summary_markdown(summary: dict[str, Any]) -> str:
        mapping = summary["mapping_counts"]
        conflicts = summary["conflicts_by_code"]
        conflict_lines = "\n".join(f"- {code}: {count}건" for code, count in sorted(conflicts.items())) or "- 없음"
        return f"""# Tube Layout 원천 좌표 검토 결과

이 결과는 읽기 전용 DB 연결로 생성했으며 DB 변경 건수는 0건입니다.

## 요약

- MDB 문서: {summary['source_document_count']}개
- Layout Revision 후보: {summary['layout_revision_count']}개
- Bundle: {summary['unique_bundle_count']}개
- 고유 좌표: {summary['unique_coordinate_count']}개
- 기존 튜브 연결: {mapping.get('EXISTING_TUBE_MATCH', 0)}개
- 신규 튜브 후보: {mapping.get('NEW_TUBE_CANDIDATE', 0)}개
- 좌표 검토 필요: {summary['orientation_review_count']}개
- DB 변경: 0건

## 충돌

{conflict_lines}

## 승인 조건

좌표 단위, 원점, 방향, 축 반전과 Bundle 범위를 검증하고 사용자 승인을 받은 뒤에만 DB 반영을 수행합니다.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit MDB Tube Layout coordinates without modifying the database.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--mdb-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    audit = LayoutAudit(args.db, args.mdb_json, args.output_dir)
    try:
        summary = audit.run()
    finally:
        audit.close()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
