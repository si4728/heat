"""Extract and classify Tube Sheet geometry evidence from IRIS report PDFs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pymupdf
from sqlalchemy import select

from .iris_v2_database import init_v2_db, session_scope
from .iris_v2_models import (
    IrisInspection,
    SourceDocument,
    TubeLayoutRevision,
    TubeSheetGeometryRevision,
)


ALGORITHM_VERSION = "pdf-tube-envelope-1.0"
PDF_NAME_BY_JSON = {
    "2020PE_IRIS2_all_tube_results.json": "2020_1P_PE.pdf",
    "2020VCM1_IRIS2_all_tube_results.json": "2020_1P_VCM1.pdf",
    "2020VCM2_IRIS2_all_tube_results.json": "2020_1P_VCM2.pdf",
    "2021VCM1_IRIS2_all_tube_results.json": "2021_1P_VCM1.pdf",
    "2021VCM2_IRIS2_all_tube_results.json": "2021_1P_VCM2.pdf",
    "2022VCM1_IRIS2_all_tube_results.json": "2022_1P_VCM1.pdf",
    "2022VCM2_IRIS2_all_tube_results.json": "2022_1P_VCM2.pdf",
    "2023VCM1_IRIS2_all_tube_results.json": "2023_1P_VCM1.pdf",
    "2023VCM2_IRIS2_all_tube_results.json": "2023_1P_VCM2.pdf",
    "2025VCM1_IRIS2_all_tube_results.json": "2025_1P_VCM1.pdf",
    "2025VCM2_IRIS2_all_tube_results.json": "2025_1P_VCM2.pdf",
}


@dataclass(frozen=True)
class GeometryAnalysis:
    source_json: str
    source_pdf: str
    source_pdf_sha256: str
    report_sequence: int
    source_page: int
    equipment_code: str
    orientation: str | None
    expected_tube_count: int | None
    extracted_tube_count: int
    tube_count_delta: int | None
    tube_count_match: bool
    shape_code: str
    shape_confidence: float
    geometry_source: str
    extraction_method: str
    explicit_boundary_detected: bool
    page_width: float
    page_height: float
    center_x: float | None
    center_y: float | None
    width: float | None
    height: float | None
    aspect_ratio: float | None
    hull_fill_ratio: float | None
    boundary_geometry_json: str
    verification_status: str
    review_status: str
    analysis_note: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected_tube_count(report: dict[str, Any]) -> int | None:
    candidates = (
        report.get("tube_map", {}).get("total_tubes"),
        report.get("tube_map", {}).get("legend_counts", {}).get("Total Tubes"),
        report.get("summary_reference", {}).get("total_tube_count"),
        report.get("report", {}).get("inspection_summary", {}).get("total_tube_count"),
    )
    for value in candidates:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return None


def _legend_cutoff(page: pymupdf.Page) -> float:
    words = page.get_text("words")
    wall_rows: dict[int, set[str]] = defaultdict(set)
    for word in words:
        token = str(word[4]).strip().upper()
        top_left = pymupdf.Point(float(word[0]), float(word[1])) * page.rotation_matrix
        y_key = round(float(top_left.y) / 4)
        if token in {"WALL", "LOSS"}:
            wall_rows[y_key].add(token)
    wall_loss_y = [key * 4 for key, tokens in wall_rows.items() if {"WALL", "LOSS"} <= tokens]
    if wall_loss_y:
        return min(wall_loss_y) - 4
    for word in words:
        token = str(word[4]).strip().upper()
        if token.startswith("PLG:") or token == "LEGEND":
            top_left = pymupdf.Point(float(word[0]), float(word[1])) * page.rotation_matrix
            return float(top_left.y) - 8
    return float(page.rect.height) * 0.82


def _is_circle_drawing(drawing: dict[str, Any]) -> bool:
    rect = drawing.get("rect")
    if not rect:
        return False
    width, height = float(rect.width), float(rect.height)
    item_types = [item[0] for item in drawing.get("items") or []]
    return (
        2.0 <= width <= 50.0
        and 2.0 <= height <= 50.0
        and abs(width - height) <= max(0.8, width * 0.12)
        and len(item_types) >= 4
        and all(item_type == "c" for item_type in item_types)
    )


def _largest_spatial_component(points: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    if len(points) < 3:
        return points
    nearest = []
    for index, (x, y, _diameter) in enumerate(points):
        distances = [
            math.hypot(x - other_x, y - other_y)
            for other_index, (other_x, other_y, _other_diameter) in enumerate(points)
            if other_index != index
        ]
        if distances:
            nearest.append(min(distances))
    threshold = max(median(nearest) * 2.8, median(item[2] for item in points) * 2.2)
    neighbours: list[list[int]] = [[] for _ in points]
    for index, (x, y, _diameter) in enumerate(points):
        for other_index in range(index + 1, len(points)):
            other_x, other_y, _other_diameter = points[other_index]
            if math.hypot(x - other_x, y - other_y) <= threshold:
                neighbours[index].append(other_index)
                neighbours[other_index].append(index)
    remaining = set(range(len(points)))
    components: list[list[int]] = []
    while remaining:
        seed = remaining.pop()
        queue = deque([seed])
        component = [seed]
        while queue:
            current = queue.popleft()
            for candidate in neighbours[current]:
                if candidate in remaining:
                    remaining.remove(candidate)
                    component.append(candidate)
                    queue.append(candidate)
        components.append(component)
    selected = max(components, key=len)
    return [points[index] for index in selected]


def extract_tube_centers(page: pymupdf.Page, expected_count: int | None) -> list[tuple[float, float]]:
    cutoff = _legend_cutoff(page)
    candidates: list[tuple[float, float, float]] = []
    for drawing in page.get_drawings():
        if not _is_circle_drawing(drawing):
            continue
        rect = drawing["rect"]
        center = pymupdf.Point(
            (float(rect.x0) + float(rect.x1)) / 2,
            (float(rect.y0) + float(rect.y1)) / 2,
        ) * page.rotation_matrix
        center_x, center_y = float(center.x), float(center.y)
        if center_y >= cutoff or center_y <= float(page.rect.height) * 0.10:
            continue
        candidates.append((center_x, center_y, (float(rect.width) + float(rect.height)) / 2))
    if not candidates:
        return []

    diameters = sorted({round(item[2], 2) for item in candidates})
    groups: list[list[tuple[float, float, float]]] = []
    seen_signatures: set[tuple[tuple[float, float], ...]] = set()
    for diameter in diameters:
        tolerance = max(0.45, diameter * 0.12)
        group = [item for item in candidates if abs(item[2] - diameter) <= tolerance]
        selected_group = group if expected_count else _largest_spatial_component(group)
        signature = tuple(sorted((round(item[0], 2), round(item[1], 2)) for item in selected_group))
        if signature and signature not in seen_signatures:
            seen_signatures.add(signature)
            groups.append(selected_group)
    if not groups:
        return []
    if expected_count:
        selected = min(groups, key=lambda group: (abs(len(group) - expected_count), -len(group)))
    else:
        selected = max(groups, key=len)
    return sorted(((item[0], item[1]) for item in selected), key=lambda point: (point[1], point[0]))


def _cross(origin: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - origin[0]) * (b[1] - origin[1]) - (a[1] - origin[1]) * (b[0] - origin[0])


def convex_hull(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted(set(points))
    if len(ordered) <= 1:
        return ordered
    lower: list[tuple[float, float]] = []
    for point in ordered:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[tuple[float, float]] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    return lower[:-1] + upper[:-1]


def polygon_area(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    return abs(sum(
        points[index][0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * points[index][1]
        for index in range(len(points))
    )) / 2


def _classify_shape(points: list[tuple[float, float]]) -> dict[str, Any]:
    if len(points) < 8:
        return {
            "shape_code": "UNKNOWN", "confidence": 0.0, "center_x": None,
            "center_y": None, "width": None, "height": None,
            "aspect_ratio": None, "hull_fill_ratio": None, "hull": [],
        }
    xs, ys = [point[0] for point in points], [point[1] for point in points]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    width, height = max_x - min_x, max_y - min_y
    hull = convex_hull(points)
    fill_ratio = polygon_area(hull) / max(width * height, 1e-9)
    aspect_ratio = max(width, height) / max(min(width, height), 1e-9)
    if fill_ratio >= 0.91:
        shape_code, base_confidence = "RECTANGULAR", 0.88
    elif fill_ratio >= 0.855:
        shape_code = "OBROUND" if aspect_ratio >= 1.25 else "ROUNDED_RECTANGLE"
        base_confidence = 0.82
    elif aspect_ratio >= 1.25:
        shape_code, base_confidence = "ELLIPTICAL", 0.84
    else:
        shape_code, base_confidence = "CIRCULAR", 0.90
    sample_factor = min(1.0, len(points) / 30)
    confidence = round(base_confidence * (0.75 + 0.25 * sample_factor), 4)
    return {
        "shape_code": shape_code,
        "confidence": confidence,
        "center_x": round((min_x + max_x) / 2, 4),
        "center_y": round((min_y + max_y) / 2, 4),
        "width": round(width, 4), "height": round(height, 4),
        "aspect_ratio": round(aspect_ratio, 6),
        "hull_fill_ratio": round(fill_ratio, 6),
        "hull": [[round(x, 3), round(y, 3)] for x, y in hull],
        "bounding_box": [round(min_x, 3), round(min_y, 3), round(max_x, 3), round(max_y, 3)],
    }


def _explicit_boundary_detected(page: pymupdf.Page, geometry: dict[str, Any]) -> bool:
    if not geometry.get("bounding_box"):
        return False
    min_x, min_y, max_x, max_y = geometry["bounding_box"]
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        if not rect or drawing.get("color") is None:
            continue
        boundary_width, boundary_height = float(rect.width), float(rect.height)
        population_width, population_height = max_x - min_x, max_y - min_y
        if boundary_width < population_width * 0.85 or boundary_height < population_height * 0.85:
            continue
        if boundary_width > population_width * 1.30 or boundary_height > population_height * 1.30:
            continue
        if float(rect.x0) <= min_x and float(rect.y0) <= min_y and float(rect.x1) >= max_x and float(rect.y1) >= max_y:
            item_types = [item[0] for item in drawing.get("items") or []]
            # A large stroked rectangle in these reports is the chart frame,
            # not a dimensioned Tube Sheet boundary. Only a closed curved
            # outline can be treated as explicit boundary evidence.
            if item_types and all(item == "c" for item in item_types):
                return True
    return False


def analyze_report_page(
    page: pymupdf.Page,
    *, source_json: Path,
    source_pdf: Path,
    source_pdf_sha256: str,
    report: dict[str, Any],
    report_sequence: int,
) -> GeometryAnalysis:
    tube_map = report.get("tube_map") or {}
    source_page = int(tube_map.get("source_page") or 0)
    expected_count = _expected_tube_count(report)
    points = extract_tube_centers(page, expected_count)
    geometry = _classify_shape(points)
    explicit_boundary = _explicit_boundary_detected(page, geometry)
    extracted_count = len(points)
    count_delta = extracted_count - expected_count if expected_count is not None else None
    count_match = expected_count is not None and count_delta == 0
    if not points:
        verification_status, review_status = "FAIL", "DRAFT"
        note = "PDF vector Tube centers could not be extracted. Manual image review is required."
    elif count_match and geometry["confidence"] >= 0.70:
        verification_status, review_status = "PASS", "REVIEWED"
        note = "Tube count matched the report; shape is inferred from the PDF tube-population envelope."
    else:
        verification_status, review_status = "WARNING", "CONFLICT"
        note = "Extracted Tube count differs from the report or shape confidence is insufficient."
    boundary_payload = {
        "coordinate_unit": "PDF_POINT",
        "evidence_scope": "TUBE_POPULATION_ENVELOPE",
        "mechanical_boundary_confirmed": explicit_boundary,
        "bounding_box": geometry.get("bounding_box"),
        "convex_hull": geometry.get("hull", []),
        "center": [geometry.get("center_x"), geometry.get("center_y")],
        "width": geometry.get("width"),
        "height": geometry.get("height"),
        "point_count": extracted_count,
    }
    report_data = report.get("report") or {}
    equipment_code = str(report_data.get("equipment_id") or "").strip()
    scope = report_data.get("inspection_scope")
    orientation = tube_map.get("orientation")
    if not orientation and isinstance(scope, dict):
        orientation = scope.get("orientation") or scope.get("scope_code")
    elif not orientation and isinstance(scope, str):
        orientation = scope
    return GeometryAnalysis(
        source_json=str(source_json.resolve()), source_pdf=str(source_pdf.resolve()),
        source_pdf_sha256=source_pdf_sha256, report_sequence=report_sequence,
        source_page=source_page, equipment_code=equipment_code,
        orientation=str(orientation).strip() if orientation else None,
        expected_tube_count=expected_count, extracted_tube_count=extracted_count,
        tube_count_delta=count_delta, tube_count_match=count_match,
        shape_code=geometry["shape_code"], shape_confidence=geometry["confidence"],
        geometry_source=("PDF_VECTOR_BOUNDARY" if explicit_boundary else "PDF_VECTOR_TUBE_ENVELOPE"),
        extraction_method="PYMUPDF_VECTOR_PATH",
        explicit_boundary_detected=explicit_boundary,
        page_width=round(float(page.rect.width), 4), page_height=round(float(page.rect.height), 4),
        center_x=geometry.get("center_x"), center_y=geometry.get("center_y"),
        width=geometry.get("width"), height=geometry.get("height"),
        aspect_ratio=geometry.get("aspect_ratio"), hull_fill_ratio=geometry.get("hull_fill_ratio"),
        boundary_geometry_json=json.dumps(boundary_payload, ensure_ascii=False, separators=(",", ":")),
        verification_status=verification_status, review_status=review_status,
        analysis_note=note,
    )


def analyze_all_pdfs(data_dir: Path, pdf_dir: Path) -> list[GeometryAnalysis]:
    analyses: list[GeometryAnalysis] = []
    for json_name, pdf_name in PDF_NAME_BY_JSON.items():
        json_path, pdf_path = data_dir / json_name, pdf_dir / pdf_name
        if not json_path.exists() or not pdf_path.exists():
            raise FileNotFoundError(f"Missing paired source: {json_path} / {pdf_path}")
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        pdf_sha256 = file_sha256(pdf_path)
        with pymupdf.open(pdf_path) as document:
            for index, report in enumerate(payload.get("inspection_reports") or [], 1):
                report_sequence = int(report.get("report", {}).get("report_sequence") or index)
                page_number = int((report.get("tube_map") or {}).get("source_page") or 0)
                if not 1 <= page_number <= document.page_count:
                    raise ValueError(f"Invalid Tube Map page {page_number}: {json_path.name} report {report_sequence}")
                analyses.append(analyze_report_page(
                    document[page_number - 1], source_json=json_path, source_pdf=pdf_path,
                    source_pdf_sha256=pdf_sha256, report=report,
                    report_sequence=report_sequence,
                ))
    return analyses


def persist_analyses(database_path: Path, analyses: list[GeometryAnalysis]) -> dict[str, Any]:
    init_v2_db(database_path)
    inserted = updated = 0
    with session_scope(database_path) as session:
        documents = {
            document.source_file: document
            for document in session.scalars(select(SourceDocument)).all()
        }
        inspections = {
            (inspection.source_document_id, inspection.report_sequence): inspection
            for inspection in session.scalars(select(IrisInspection)).all()
            if inspection.source_document_id is not None
        }
        approved_layouts: dict[int, int] = {}
        for revision in session.scalars(
            select(TubeLayoutRevision).where(TubeLayoutRevision.revision_status == "APPROVED")
        ).all():
            approved_layouts.setdefault(revision.bundle_id, revision.layout_revision_id)
        for analysis in analyses:
            source_file = Path(analysis.source_json).name
            document = documents.get(source_file)
            if not document:
                raise ValueError(f"Source document is not registered: {source_file}")
            inspection = inspections.get((document.source_document_id, analysis.report_sequence))
            if not inspection:
                raise ValueError(f"Inspection is not registered: {source_file} #{analysis.report_sequence}")
            existing = session.scalar(select(TubeSheetGeometryRevision).where(
                TubeSheetGeometryRevision.iris_inspection_id == inspection.iris_inspection_id,
                TubeSheetGeometryRevision.source_pdf_sha256 == analysis.source_pdf_sha256,
                TubeSheetGeometryRevision.source_page == analysis.source_page,
                TubeSheetGeometryRevision.algorithm_version == ALGORITHM_VERSION,
            ))
            values = {
                "heat_exchanger_id": inspection.heat_exchanger_id,
                "bundle_id": inspection.bundle_id,
                "iris_inspection_id": inspection.iris_inspection_id,
                "source_document_id": document.source_document_id,
                "layout_revision_id": approved_layouts.get(inspection.bundle_id),
                "source_pdf_path": analysis.source_pdf,
                "source_pdf_sha256": analysis.source_pdf_sha256,
                "source_page": analysis.source_page,
                "source_equipment_code": analysis.equipment_code,
                "source_orientation": analysis.orientation,
                "source_page_width": analysis.page_width,
                "source_page_height": analysis.page_height,
                "shape_code": analysis.shape_code,
                "geometry_source": analysis.geometry_source,
                "boundary_geometry_json": analysis.boundary_geometry_json,
                "center_x": analysis.center_x, "center_y": analysis.center_y,
                "width": analysis.width, "height": analysis.height,
                "rotation_degrees": 0, "aspect_ratio": analysis.aspect_ratio,
                "hull_fill_ratio": analysis.hull_fill_ratio,
                "shape_confidence": analysis.shape_confidence,
                "explicit_boundary_detected": analysis.explicit_boundary_detected,
                "expected_tube_count": analysis.expected_tube_count,
                "extracted_tube_count": analysis.extracted_tube_count,
                "tube_count_delta": analysis.tube_count_delta,
                "tube_count_match": analysis.tube_count_match,
                "extraction_method": analysis.extraction_method,
                "algorithm_version": ALGORITHM_VERSION,
                "verification_status": analysis.verification_status,
                "analysis_note": analysis.analysis_note,
            }
            if existing is None:
                session.add(TubeSheetGeometryRevision(
                    **values, review_status=analysis.review_status,
                ))
                inserted += 1
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
                if existing.review_status not in {"APPROVED", "REJECTED"}:
                    existing.review_status = analysis.review_status
                updated += 1
        session.flush()
        geometry_rows = session.scalars(select(TubeSheetGeometryRevision).where(
            TubeSheetGeometryRevision.algorithm_version == ALGORITHM_VERSION
        )).all()
        grouped: dict[tuple[int, int | None], list[TubeSheetGeometryRevision]] = defaultdict(list)
        for row in geometry_rows:
            grouped[(row.heat_exchanger_id, row.bundle_id)].append(row)
        for rows in grouped.values():
            eligible = [
                row for row in rows
                if row.tube_count_match and row.shape_code != "UNKNOWN"
            ]
            counts = Counter(row.shape_code for row in eligible)
            consensus_shape = counts.most_common(1)[0][0] if counts else None
            sample_count = len(eligible)
            consensus_confidence = (
                counts[consensus_shape] / sample_count
                if consensus_shape and sample_count else None
            )
            for row in rows:
                row.consensus_shape_code = consensus_shape
                row.consensus_sample_count = sample_count
                row.consensus_confidence = consensus_confidence
                row.cross_year_consistent = (
                    row.shape_code == consensus_shape if consensus_shape else None
                )
    return {
        "inserted": inserted, "updated": updated, "total": len(analyses),
        "consensus_group_count": len(grouped),
    }


def summarize_analyses(analyses: list[GeometryAnalysis]) -> dict[str, Any]:
    return {
        "algorithm_version": ALGORITHM_VERSION,
        "pdf_count": len({analysis.source_pdf for analysis in analyses}),
        "tube_map_page_count": len(analyses),
        "shape_counts": dict(sorted(Counter(item.shape_code for item in analyses).items())),
        "verification_counts": dict(sorted(Counter(item.verification_status for item in analyses).items())),
        "review_counts": dict(sorted(Counter(item.review_status for item in analyses).items())),
        "tube_count_match_count": sum(item.tube_count_match for item in analyses),
        "explicit_boundary_count": sum(item.explicit_boundary_detected for item in analyses),
        "zero_extraction_count": sum(item.extracted_tube_count == 0 for item in analyses),
        "mean_shape_confidence": round(
            sum(item.shape_confidence for item in analyses) / max(len(analyses), 1), 4
        ),
    }


def analysis_rows(analyses: list[GeometryAnalysis]) -> list[dict[str, Any]]:
    return [asdict(item) for item in analyses]
