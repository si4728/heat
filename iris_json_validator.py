"""Validation and normalization helpers for IRIS inspection JSON files.

This module never writes to the database.  It intentionally preserves source
values and reports discrepancies instead of guessing a correction.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from iris2.import_normalization import normalize_equipment_code
from iris2.iris_json_mapping import report_details, resolve_report_identity


VALIDATOR_VERSION = "2.0.0"


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    description: str
    field_path: str = ""
    source_value: Any = None
    calculated_value: Any = None
    report_sequence: int | None = None
    equipment_id: str | None = None
    tube_id: str | None = None

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            [self.code, self.field_path, self.report_sequence, self.equipment_id, self.tube_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["fingerprint"] = self.fingerprint
        return result


@dataclass
class ValidationResult:
    path: Path
    sha256: str
    size: int
    modified_at: datetime
    payload: dict[str, Any]
    issues: list[Issue]
    report_count: int
    tube_result_count: int

    @property
    def error_count(self) -> int:
        return sum(i.severity == "ERROR" for i in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(i.severity == "WARNING" for i in self.issues)

    @property
    def status(self) -> str:
        return "INVALID" if self.error_count else ("VALID_WITH_WARNINGS" if self.warning_count else "VALID")

    def summary(self) -> dict[str, Any]:
        return {
            "source_file": self.path.name,
            "source_path": str(self.path),
            "sha256": self.sha256,
            "validator_version": VALIDATOR_VERSION,
            "status": self.status,
            "report_count": self.report_count,
            "tube_result_count": self.tube_result_count,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def number(value: Any) -> float | None:
    """Convert a numeric value without losing a valid zero."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    converted = number(value)
    return int(converted) if converted is not None else None


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y.%m.%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m", "%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def tube_map_values(tube_map: dict[str, Any]) -> dict[str, Any]:
    spacing = tube_map.get("spacing") or {}
    legend = tube_map.get("legend_counts") or {}
    return {
        "map_date": tube_map.get("map_date") or tube_map.get("date"),
        "vertical_spacing": tube_map.get("vertical_spacing", spacing.get("vertical")),
        "horizontal_spacing": tube_map.get("horizontal_spacing", spacing.get("horizontal")),
        "total_tubes": tube_map.get("total_tubes", legend.get("Total Tubes")),
        "untested_tubes": tube_map.get(
            "unmarked_or_untested_tubes", tube_map.get("untested_tubes")
        ),
    }


def report_parts(report_object: dict[str, Any]) -> dict[str, Any]:
    report = report_object.get("report") or {}
    details = report_details(report)
    basic = details.get("basic_information") or {}
    summary = report.get("inspection_summary") or {}
    summary_ref = report_object.get("summary_reference") or {}
    conditions = details.get("measurement_conditions") or {}
    tube_spec = report.get("tube_spec") or {}
    table = report_object.get("tube_results_table") or {}
    records = table.get("records") or []
    identity = resolve_report_identity(report)
    equipment_raw = identity.source_label or report.get("equipment_id") or basic.get("equipment_number") or ""
    return {
        "report": report,
        "details": details,
        "basic": basic,
        "summary": summary,
        "summary_reference": summary_ref,
        "conditions": conditions,
        "tube_spec": tube_spec,
        "table": table,
        "records": records,
        "tube_map": report_object.get("tube_map") or {},
        "validation": report_object.get("validation") or {},
        "extraction_status": report_object.get("extraction_status") or {},
        "equipment_raw": equipment_raw,
        "equipment_code": identity.equipment_code,
        "bundle_code": identity.bundle_code,
        "scope_code": identity.scope_code,
        "directions": list(identity.directions),
    }


def _issue(issues: list[Issue], code: str, severity: str, description: str, *,
           path: str = "", source: Any = None, calculated: Any = None,
           sequence: int | None = None, equipment: str | None = None,
           tube_id: str | None = None) -> None:
    issues.append(Issue(code, severity, description, path, source, calculated, sequence, equipment, tube_id))


def _close(a: Any, b: Any, tolerance: float = 0.01) -> bool:
    left, right = number(a), number(b)
    return left is not None and right is not None and abs(left - right) <= tolerance


def _document_report_count(document: dict[str, Any]) -> int | None:
    for key in ("inspection_report_object_count", "heat_exchanger_report_count"):
        if document.get(key) is not None:
            return integer(document[key])
    return None


def validate_file(path: str | Path) -> ValidationResult:
    source = Path(path).resolve()
    raw = source.read_bytes()
    stat = source.stat()
    issues: list[Issue] = []
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _issue(issues, "JSON_PARSE_ERROR", "ERROR", str(exc), path="$")
        return ValidationResult(source, hashlib.sha256(raw).hexdigest(), len(raw),
                                datetime.fromtimestamp(stat.st_mtime), {}, issues, 0, 0)

    if not isinstance(payload, dict):
        _issue(issues, "ROOT_NOT_OBJECT", "ERROR", "JSON root must be an object.", path="$", source=type(payload).__name__)
        return ValidationResult(source, hashlib.sha256(raw).hexdigest(), len(raw),
                                datetime.fromtimestamp(stat.st_mtime), {}, issues, 0, 0)

    reports = payload.get("inspection_reports")
    if not isinstance(reports, list):
        _issue(issues, "REPORT_LIST_MISSING", "ERROR", "inspection_reports must be an array.", path="$.inspection_reports")
        reports = []
    document = payload.get("document") or {}
    declared_reports = _document_report_count(document)
    if declared_reports is not None and declared_reports != len(reports):
        _issue(issues, "DOCUMENT_REPORT_COUNT_MISMATCH", "ERROR", "Document report count differs from extracted objects.",
               path="$.document", source=declared_reports, calculated=len(reports))

    total_records = 0
    seen_sequences: set[int] = set()
    for idx, obj in enumerate(reports):
        root = f"$.inspection_reports[{idx}]"
        if not isinstance(obj, dict):
            _issue(issues, "REPORT_NOT_OBJECT", "ERROR", "Report entry must be an object.", path=root)
            continue
        p = report_parts(obj)
        report = p["report"]
        seq = integer(report.get("report_sequence"))
        equipment = str(p["equipment_raw"] or "")
        if seq is None:
            _issue(issues, "REPORT_SEQUENCE_MISSING", "ERROR", "report_sequence is required.", path=f"{root}.report.report_sequence", equipment=equipment)
        elif seq in seen_sequences:
            _issue(issues, "DUPLICATE_REPORT_SEQUENCE", "ERROR", "report_sequence is duplicated.", path=f"{root}.report.report_sequence", source=seq, sequence=seq, equipment=equipment)
        else:
            seen_sequences.add(seq)
        if not equipment or not p["equipment_code"]:
            _issue(issues, "EQUIPMENT_ID_MISSING", "ERROR", "Equipment identity is required.", path=f"{root}.report.equipment_id", sequence=seq)

        records = p["records"] if isinstance(p["records"], list) else []
        total_records += len(records)
        table_count = integer(p["table"].get("record_count"))
        validation_count = integer(p["validation"].get("extracted_tube_result_count"))
        for label, value, field in (
            ("table", table_count, "tube_results_table.record_count"),
            ("validation", validation_count, "validation.extracted_tube_result_count"),
        ):
            if value is not None and value != len(records):
                _issue(issues, "TUBE_RESULT_COUNT_MISMATCH", "ERROR", f"{label} count differs from record array.",
                       path=f"{root}.{field}", source=value, calculated=len(records), sequence=seq, equipment=equipment)

        extraction = p["extraction_status"]
        status = str(extraction.get("status") or "").lower()
        if "partial" in status or extraction.get("tube_results_table_available") is False:
            _issue(issues, "PARTIAL_REPORT", "WARNING", "Report is partial; raw data will be retained and missing details left null.",
                   path=f"{root}.extraction_status", source=extraction, sequence=seq, equipment=equipment)

        seen_tubes: set[str] = set()
        losses: list[float] = []
        thicknesses: list[float] = []
        for ridx, record in enumerate(records):
            tube_id = str(record.get("tube_id") or "").strip()
            rpath = f"{root}.tube_results_table.records[{ridx}]"
            if not tube_id:
                _issue(issues, "TUBE_ID_MISSING", "ERROR", "Tube result has no tube_id.", path=f"{rpath}.tube_id", sequence=seq, equipment=equipment)
                continue
            if tube_id in seen_tubes:
                _issue(issues, "DUPLICATE_TUBE_IN_REPORT", "ERROR", "Tube appears more than once in one inspection report.", path=f"{rpath}.tube_id", source=tube_id, sequence=seq, equipment=equipment, tube_id=tube_id)
            seen_tubes.add(tube_id)
            row, col = integer(record.get("row")), integer(record.get("column"))
            expected = f"{row}-{col}" if row is not None and col is not None else None
            if expected and tube_id.replace(" ", "") != expected:
                _issue(issues, "TUBE_COORDINATE_MISMATCH", "WARNING", "tube_id differs from row-column coordinates.", path=f"{rpath}.tube_id", source=tube_id, calculated=expected, sequence=seq, equipment=equipment, tube_id=tube_id)
            loss = number(record.get("wall_loss_percent"))
            mwt = number(record.get("minimum_wall_thickness_mm"))
            if loss is not None:
                losses.append(loss)
                if not 0 <= loss <= 100:
                    _issue(issues, "WALL_LOSS_OUT_OF_RANGE", "ERROR", "wall_loss_percent must be between 0 and 100.", path=f"{rpath}.wall_loss_percent", source=loss, sequence=seq, equipment=equipment, tube_id=tube_id)
            if mwt is not None:
                thicknesses.append(mwt)

        validation = p["validation"]
        table_range = p["table"].get("corrosion_depth_range_percent") or {}
        calculated = {
            "min_thickness": min(thicknesses) if thicknesses else None,
            "max_loss": max(losses) if losses else None,
            "avg_loss": fmean(losses) if losses else None,
            "min_loss": min(losses) if losses else None,
        }
        comparisons = (
            ("CALCULATED_MIN_THICKNESS_MISMATCH", validation.get("calculated_minimum_thickness_mm"), calculated["min_thickness"], "calculated_minimum_thickness_mm", 0.01),
            ("CALCULATED_MAX_LOSS_MISMATCH", validation.get("calculated_maximum_wall_loss_percent"), calculated["max_loss"], "calculated_maximum_wall_loss_percent", 0.01),
            ("CALCULATED_AVERAGE_LOSS_MISMATCH", validation.get("calculated_average_wall_loss_percent"), calculated["avg_loss"], "calculated_average_wall_loss_percent", 0.50),
            ("WALL_LOSS_RANGE_MIN_MISMATCH", table_range.get("min"), calculated["min_loss"], "wall_loss_range.min", 0.01),
            ("WALL_LOSS_RANGE_MAX_MISMATCH", table_range.get("max"), calculated["max_loss"], "wall_loss_range.max", 0.01),
        )
        for code, supplied, actual, field, tolerance in comparisons:
            if supplied is not None and actual is not None and not _close(supplied, actual, tolerance):
                _issue(issues, code, "WARNING", "Supplied calculated value differs from records.", path=f"{root}.{field}", source=supplied, calculated=round(actual, 4), sequence=seq, equipment=equipment)

        if validation.get("reported_vs_extracted_count_match") is False:
            _issue(
                issues, "REPORTED_EXTRACTED_COUNT_MISMATCH", "WARNING",
                "Reported inspected tube count differs from extracted result rows.",
                path=f"{root}.validation.reported_vs_extracted_count_match",
                source=validation.get("reported_inspected_tube_count"),
                calculated=validation.get("extracted_tube_result_count", len(records)),
                sequence=seq, equipment=equipment,
            )
        for item_index, item in enumerate(validation.get("source_pdf_inconsistencies") or []):
            category = re.sub(
                r"[^A-Z0-9]+", "_",
                str(item.get("category") or "INCONSISTENCY").upper(),
            ).strip("_")
            _issue(
                issues, f"SOURCE_PDF_{category}"[:100], "WARNING",
                "Source PDF inconsistency retained for review.",
                path=f"{root}.validation.source_pdf_inconsistencies[{item_index}]",
                source=item, sequence=seq, equipment=equipment,
            )
        for item_index, item in enumerate(validation.get("row_calculation_mismatches") or []):
            _issue(
                issues, "ROW_CALCULATION_MISMATCH", "WARNING",
                "PDF tube-row values differ from recalculated values.",
                path=f"{root}.validation.row_calculation_mismatches[{item_index}]",
                source=item,
                calculated={
                    "wall_loss_depth_mm": item.get("calculated_wall_loss_depth_mm"),
                    "wall_loss_percent": item.get("calculated_wall_loss_percent"),
                },
                sequence=seq, equipment=equipment,
                tube_id=str(item.get("tube_id") or "") or None,
            )
        for item_index, item in enumerate(validation.get("invalid_source_page_references") or []):
            _issue(
                issues, "INVALID_SOURCE_PAGE_REFERENCE", "WARNING",
                "A source page reference is outside the document page inventory.",
                path=f"{root}.validation.invalid_source_page_references[{item_index}]",
                source=item, sequence=seq, equipment=equipment,
            )

        report_no = str(p["basic"].get("report_number") or "")
        if report_no:
            token = re.search(r"E[-_]?\d+[A-Z]?", report_no.upper())
            if token:
                report_code = token.group(0).replace("_", "-")
                if report_code != p["equipment_code"]:
                    _issue(issues, "REPORT_NUMBER_EQUIPMENT_MISMATCH", "WARNING", "Report number equipment token differs from report equipment_id; source identity is not auto-corrected.", path=f"{root}.report.*_report_details.basic_information.report_number", source=report_no, calculated=p["equipment_code"], sequence=seq, equipment=equipment)

    declared_total = integer(document.get("total_extracted_tube_result_records"))
    if declared_total is not None and declared_total != total_records:
        _issue(issues, "DOCUMENT_TUBE_COUNT_MISMATCH", "ERROR", "Document tube result total differs from record arrays.", path="$.document.total_extracted_tube_result_records", source=declared_total, calculated=total_records)

    return ValidationResult(source, hashlib.sha256(raw).hexdigest(), len(raw),
                            datetime.fromtimestamp(stat.st_mtime), payload, issues,
                            len(reports), total_records)


def validate_files(paths: Iterable[str | Path]) -> list[ValidationResult]:
    return [validate_file(path) for path in paths]
