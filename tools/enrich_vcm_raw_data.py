from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


MAG_KEYS = (
    "RequestedAcquisitionRate",
    "DataRecordDateTime",
    "DataSoftwareVersion",
    "InstrumentType",
    "InstrumentModel",
    "InstrumentSerialNumber",
    "InstrumentLastCalibrationDate",
)
MAG_PATTERNS = {
    key: re.compile(rb'Name="' + key.encode() + rb'"[^>]*>(.*?)</Item>', re.S)
    for key in MAG_KEYS
}
ATTACHMENT_EXTENSIONS = {".pdf", ".png", ".bmp", ".jpg", ".jpeg", ".xlsx"}
IGNORED_SCALAR_VALUES = {"", "0", "0`", "eeprom", "undefined"}


def flatten(value: Iterable[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, list):
            result.extend(item)
        else:
            result.append(item)
    return result


def equipment_code(text: str) -> str | None:
    match = re.search(
        r"(?<![A-Z0-9])((?:AE|E)-\d{3}[A-Z]?)",
        text.upper().replace("_", "-"),
    )
    return match.group(1) if match else None


def excel_row_number(value: str) -> int:
    value = value.upper()
    if value.isdigit():
        return int(value)
    number = 0
    for char in value:
        number = number * 26 + ord(char) - 64
    return number


def tube_label_to_rc(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([A-Z]+|\d+)-(\d+)", value.strip().upper())
    if not match:
        return None
    return excel_row_number(match.group(1)), int(match.group(2))


def raw_filename_to_rc(path: Path) -> tuple[int, int, str] | None:
    stem = path.stem.upper()
    match = re.fullmatch(r"(\d{3})(\d{3})(?:\.(\d{3}))?", stem)
    if match:
        return int(match.group(1)), int(match.group(2)), match.group(3) or "0"
    match = re.fullmatch(r"(\d{2})(\d{3})([A-Z])", stem)
    if match:
        return int(match.group(1)), int(match.group(2)), match.group(3)
    return None


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9+\-.]", "", str(value).replace("\u202d", "").replace("\u202c", ""))
    if cleaned in {"", "+", "-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def normalize_date(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    return match.group(1) if match else None


def normalize_software(value: str) -> tuple[str | None, str | None]:
    cleaned = value.replace("\ufffd", "").replace("®", "").strip()
    match = re.search(r"(?i)\bMagnifi\s*([0-9][^\s]*)?", cleaned)
    if not match:
        return None, None
    return "Magnifi", (match.group(1) or "").strip() or None


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    for encoding in ("utf-8-sig", "cp949", "utf-16", "latin1"):
        try:
            with path.open("r", encoding=encoding, newline="") as stream:
                reader = csv.DictReader(stream)
                return reader.fieldnames or [], list(reader)
        except (UnicodeError, csv.Error):
            continue
    return [], []


def parse_magdata(path: Path) -> dict[str, str]:
    with path.open("rb") as stream:
        data = stream.read(2 * 1024 * 1024)
    values: dict[str, str] = {}
    for key, pattern in MAG_PATTERNS.items():
        match = pattern.search(data)
        if match:
            raw = re.sub(rb"<[^>]+>", b"", match.group(1))
            values[key] = raw.decode("utf-8", "replace").strip()
    return values


def fingerprint(*parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Enricher:
    def __init__(self, db_path: Path, source_root: Path, mdb_json: Path, output_dir: Path):
        self.db_path = db_path
        self.source_root = source_root
        self.mdb_json = mdb_json
        self.output_dir = output_dir
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.changes: list[dict[str, Any]] = []
        self.conflicts: list[dict[str, Any]] = []
        self.indications: list[dict[str, Any]] = []
        self.manifest: list[dict[str, Any]] = []
        self.counters: Counter[str] = Counter()
        self.inspection_index: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
        self.results_by_rc: dict[tuple[int, int, int], sqlite3.Row] = {}
        self.results_by_id: dict[int, sqlite3.Row] = {}
        self.tubes_by_bundle_rc: dict[tuple[int, int, int], sqlite3.Row] = {}
        self.existing_indication_fingerprints: set[str] = set()
        self.next_sequence: dict[int, int] = defaultdict(int)
        self._load_database_index()

    def _load_database_index(self) -> None:
        query = """
            SELECT upper(pu.unit_code) AS unit_code, ic.campaign_year,
                   ii.iris_inspection_id, upper(ii.canonical_equipment_code) AS equipment_code,
                   coalesce(tb.bundle_code, '') AS bundle_code,
                   upper(coalesce(sc.scope_code, '')) AS scope_code,
                   ii.bundle_id, date(ii.inspection_date) AS inspection_date
            FROM iris_inspection ii
            JOIN inspection_campaign ic ON ic.campaign_id=ii.campaign_id
            JOIN process_unit pu ON pu.unit_id=ic.unit_id
            LEFT JOIN tube_bundle tb ON tb.bundle_id=ii.bundle_id
            LEFT JOIN inspection_scope sc ON sc.inspection_scope_id=ii.inspection_scope_id
            WHERE upper(pu.unit_code) IN ('VCM1','VCM2')
        """
        for row in self.connection.execute(query):
            self.inspection_index[(row["unit_code"], row["campaign_year"], row["equipment_code"])].append(dict(row))
        for row in self.connection.execute("SELECT * FROM iris_tube_result"):
            self.results_by_id[row["iris_tube_result_id"]] = row
            if row["source_row"] is not None and row["source_column"] is not None:
                self.results_by_rc[(row["iris_inspection_id"], int(row["source_row"]), int(row["source_column"]))] = row
        for row in self.connection.execute("SELECT * FROM heat_exchanger_tube WHERE row_no IS NOT NULL AND column_no IS NOT NULL"):
            self.tubes_by_bundle_rc[(row["bundle_id"], int(row["row_no"]), int(row["column_no"]))] = row
        for row in self.connection.execute("SELECT iris_tube_result_id, sequence_no, raw_json FROM iris_indication"):
            self.next_sequence[row["iris_tube_result_id"]] = max(
                self.next_sequence[row["iris_tube_result_id"]], int(row["sequence_no"]) + 1
            )
            try:
                raw = json.loads(row["raw_json"] or "{}")
                if raw.get("fingerprint"):
                    self.existing_indication_fingerprints.add(raw["fingerprint"])
            except json.JSONDecodeError:
                pass

    def resolve_path(self, path: Path) -> tuple[dict[str, Any] | None, str | None]:
        try:
            relative = path.relative_to(self.source_root)
        except ValueError:
            relative = path
        parts = relative.parts
        if len(parts) < 3 or parts[0].upper() not in {"VCM1", "VCM2"} or not parts[1].isdigit():
            return None, "PATH_SCOPE"
        unit, year, top_folder = parts[0].upper(), int(parts[1]), parts[2]
        code = equipment_code(top_folder)
        candidates = list(self.inspection_index.get((unit, year, code or ""), []))
        if not candidates:
            return None, "NO_INSPECTION_CANDIDATE"
        text = str(relative).upper().replace("_", "-")
        if len(candidates) > 1 and code:
            bundle_match = re.search(rf"{re.escape(code)}-?([12])(?:\D|$)", text)
            if bundle_match:
                narrowed = [item for item in candidates if str(item["bundle_code"]).upper() == bundle_match.group(1)]
                if len(narrowed) == 1:
                    candidates = narrowed
        if len(candidates) > 1:
            side = None
            if any(token in text for token in ("BOTTOM", "(BOM)", " BTM")):
                side = "BTM"
            elif "TOP" in text:
                side = "TOP"
            if side:
                narrowed = [item for item in candidates if side in item["scope_code"]]
                if len(narrowed) == 1:
                    candidates = narrowed
        if len(candidates) != 1:
            return None, "MULTIPLE_INSPECTION_CANDIDATES"
        return candidates[0], None

    def add_change(self, table: str, key_column: str, key_value: int, column: str, before: Any, after: Any, source: str, confidence: str = "HIGH") -> None:
        if after is None or str(after).strip() == "" or before not in (None, ""):
            return
        self.changes.append({
            "table": table,
            "key_column": key_column,
            "key_value": key_value,
            "column": column,
            "before": before,
            "after": after,
            "source": source,
            "confidence": confidence,
        })

    def add_conflict(self, code: str, source: str, detail: str, inspection_id: int | None = None) -> None:
        self.conflicts.append({
            "code": code,
            "inspection_id": inspection_id,
            "source": source,
            "detail": detail,
        })

    def scan_files(self) -> dict[int, dict[str, set[str]]]:
        metadata: dict[int, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        attachment_types: dict[int, set[str]] = defaultdict(set)
        for unit in ("VCM1", "VCM2"):
            for path in sorted((self.source_root / unit).rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(self.source_root)
                inspection, error = self.resolve_path(path)
                raw_rc = raw_filename_to_rc(path) if path.suffix.lower() in {".magdata", ".tis2"} else None
                status = "MAPPED" if inspection else error or "UNMAPPED"
                tube_id = result_id = None
                if inspection and raw_rc:
                    row_no, column_no, _rescan = raw_rc
                    tube = self.tubes_by_bundle_rc.get((inspection["bundle_id"], row_no, column_no))
                    result = self.results_by_rc.get((inspection["iris_inspection_id"], row_no, column_no))
                    tube_id = tube["tube_id"] if tube else None
                    result_id = result["iris_tube_result_id"] if result else None
                    status = "MATCHED_RESULT" if result else "MATCHED_TUBE" if tube else "UNMATCHED_TUBE"
                if path.name.upper().startswith("CAL-"):
                    status = "CALIBRATION"
                self.manifest.append({
                    "relative_path": str(relative),
                    "extension": path.suffix.lower(),
                    "size": path.stat().st_size,
                    "inspection_id": inspection["iris_inspection_id"] if inspection else None,
                    "tube_id": tube_id,
                    "tube_result_id": result_id,
                    "row": raw_rc[0] if raw_rc else None,
                    "column": raw_rc[1] if raw_rc else None,
                    "rescan": raw_rc[2] if raw_rc else None,
                    "mapping_status": status,
                })
                if error:
                    self.add_conflict(error, str(relative), "파일을 단일 검사 레코드에 연결하지 못함")
                if not inspection:
                    continue
                iid = inspection["iris_inspection_id"]
                if path.suffix.lower() == ".magdata" and status != "CALIBRATION":
                    try:
                        values = parse_magdata(path)
                    except OSError as exc:
                        self.add_conflict("MAGDATA_READ_ERROR", str(relative), str(exc), iid)
                        continue
                    for key, value in values.items():
                        if value.strip().lower() not in IGNORED_SCALAR_VALUES:
                            metadata[iid][key].add(value.strip())
                if path.suffix.lower() in ATTACHMENT_EXTENSIONS:
                    attachment_types[iid].add(path.suffix.lower().lstrip("."))
        self._plan_magdata_metadata(metadata)
        self._plan_attachments(attachment_types)
        return metadata

    def _plan_magdata_metadata(self, metadata: dict[int, dict[str, set[str]]]) -> None:
        for iid, values in metadata.items():
            execution = self.connection.execute(
                "SELECT * FROM inspection_execution_snapshot WHERE iris_inspection_id=?", (iid,)
            ).fetchone()
            setup = self.connection.execute(
                "SELECT * FROM iris_setup_snapshot WHERE iris_inspection_id=?", (iid,)
            ).fetchone()
            if not execution or not setup:
                continue
            versions = values.get("DataSoftwareVersion", set())
            if len(versions) == 1:
                name, version = normalize_software(next(iter(versions)))
                self.add_change("inspection_execution_snapshot", "iris_inspection_id", iid, "acquisition_software_name", execution["acquisition_software_name"], name, "magdata:DataSoftwareVersion")
                self.add_change("inspection_execution_snapshot", "iris_inspection_id", iid, "acquisition_software_version", execution["acquisition_software_version"], version, "magdata:DataSoftwareVersion")
            elif len(versions) > 1:
                self.add_conflict("MULTIPLE_SOFTWARE_VERSIONS", "magdata", json.dumps(sorted(versions), ensure_ascii=False), iid)
            calibration_dates = {normalize_date(value) for value in values.get("InstrumentLastCalibrationDate", set())}
            calibration_dates.discard(None)
            if len(calibration_dates) == 1:
                self.add_change("inspection_execution_snapshot", "iris_inspection_id", iid, "equipment_calibration_date", execution["equipment_calibration_date"], next(iter(calibration_dates)), "magdata:InstrumentLastCalibrationDate")
            elif len(calibration_dates) > 1:
                self.add_conflict("MULTIPLE_CALIBRATION_DATES", "magdata", json.dumps(sorted(calibration_dates)), iid)
            serials = values.get("InstrumentSerialNumber", set())
            if len(serials) == 1:
                self.add_change("iris_setup_snapshot", "iris_inspection_id", iid, "equipment_serial_number", setup["equipment_serial_number"], next(iter(serials)), "magdata:InstrumentSerialNumber")
            elif len(serials) > 1:
                self.add_conflict("MULTIPLE_INSTRUMENT_SERIALS", "magdata", json.dumps(sorted(serials)), iid)
            models = values.get("InstrumentModel", set())
            if len(models) == 1:
                self.add_change("iris_setup_snapshot", "iris_inspection_id", iid, "equipment_model", setup["equipment_model"], next(iter(models)), "magdata:InstrumentModel")

    def _plan_attachments(self, attachment_types: dict[int, set[str]]) -> None:
        for iid, types in attachment_types.items():
            row = self.connection.execute(
                "SELECT * FROM inspection_attachment WHERE iris_inspection_id=?", (iid,)
            ).fetchone()
            if row and types and not row["attachment_present"]:
                self.changes.append({
                    "table": "inspection_attachment",
                    "key_column": "iris_inspection_id",
                    "key_value": iid,
                    "column": "attachment_present",
                    "before": row["attachment_present"],
                    "after": 1,
                    "source": "physical_files:" + ",".join(sorted(types)),
                    "confidence": "HIGH",
                })

    def scan_csv(self) -> None:
        for unit in ("VCM1", "VCM2"):
            for path in sorted((self.source_root / unit).rglob("*.csv")):
                header, rows = read_csv(path)
                inspection, error = self.resolve_path(path)
                if not inspection:
                    if error:
                        self.add_conflict(error, str(path.relative_to(self.source_root)), "CSV 검사 매핑 실패")
                    continue
                if header[:3] == ["Row", "Col", "Pos"]:
                    self._scan_csv_detail(path, inspection, rows)
                elif header[:2] == ["Tube", "MWT"]:
                    self._scan_csv_results(path, inspection, rows)

    def _scan_csv_detail(self, path: Path, inspection: dict[str, Any], rows: list[dict[str, str]]) -> None:
        relative = str(path.relative_to(self.source_root))
        for index, raw in enumerate(rows, start=1):
            try:
                row_no, column_no = int(float(raw["Row"])), int(float(raw["Col"]))
            except (KeyError, TypeError, ValueError):
                self.add_conflict("CSV_DETAIL_BAD_TUBE", relative, json.dumps(raw, ensure_ascii=False), inspection["iris_inspection_id"])
                continue
            result = self.results_by_rc.get((inspection["iris_inspection_id"], row_no, column_no))
            if not result:
                self.add_conflict("CSV_DETAIL_NO_RESULT", relative, f"row={row_no}, column={column_no}", inspection["iris_inspection_id"])
                continue
            mwt_m = parse_float(raw.get("MinWallThickness"))
            location_m = parse_float(raw.get("Location"))
            measured_mm = mwt_m * 1000 if mwt_m is not None else None
            location_mm = location_m * 1000 if location_m is not None else None
            self.add_change("iris_tube_result", "iris_tube_result_id", result["iris_tube_result_id"], "minimum_wall_thickness_mm", result["minimum_wall_thickness_mm"], measured_mm, relative)
            self.add_change("iris_tube_result", "iris_tube_result_id", result["iris_tube_result_id"], "location_mm", result["location_mm"], location_mm, relative)
            canonical = ("csv_detail", inspection["iris_inspection_id"], row_no, column_no, raw.get("TubeDataId"), raw.get("ImageIndex"), raw.get("Pos"))
            fp = fingerprint(*canonical)
            self._add_indication({
                "fingerprint": fp,
                "iris_tube_result_id": result["iris_tube_result_id"],
                "axial_position_mm": location_mm,
                "measured_thickness_mm": measured_mm,
                "source_data_path": relative,
                "raw": {"source_type": "CSV_DETAIL", "source_row": index, "data": raw},
            })

    def _scan_csv_results(self, path: Path, inspection: dict[str, Any], rows: list[dict[str, str]]) -> None:
        relative = str(path.relative_to(self.source_root))
        for raw in rows:
            rc = tube_label_to_rc(raw.get("Tube", ""))
            if not rc:
                continue
            result = self.results_by_rc.get((inspection["iris_inspection_id"], rc[0], rc[1]))
            damage = (raw.get("DamageType") or "").strip()
            if not result:
                if damage:
                    self.add_conflict("CSV_RESULT_NO_EXISTING_RESULT", relative, f"tube={raw.get('Tube')}, status={damage}", inspection["iris_inspection_id"])
                continue
            if damage and result["corrosion_type"] and damage.casefold() != str(result["corrosion_type"]).casefold():
                self.add_conflict("CSV_DAMAGE_TYPE_CONFLICT", relative, f"tube={raw.get('Tube')}, csv={damage}, db={result['corrosion_type']}", inspection["iris_inspection_id"])

    def scan_mdb(self) -> None:
        payload = json.loads(self.mdb_json.read_text(encoding="utf-8"))
        indication_candidates: dict[str, dict[str, Any]] = {}
        map_candidates: dict[int, dict[str, set[Any]]] = defaultdict(lambda: defaultdict(set))
        for document in payload["documents"]:
            relative = document["path"]
            inspection, error = self.resolve_path(self.source_root / relative)
            if not inspection:
                self.add_conflict(error or "MDB_MAP_ERROR", relative, "MDB 검사 매핑 실패")
                continue
            iid = inspection["iris_inspection_id"]
            tables = document["tables"]
            tubes = {row["tubeId"]: row for row in flatten(tables.get("tube", []))}
            for row in flatten(tables.get("result", [])):
                tube = tubes.get(row.get("tubeId"))
                if not tube:
                    self.add_conflict("MDB_RESULT_NO_TUBE", relative, f"resId={row.get('resId')}", iid)
                    continue
                row_no, column_no = int(tube["tubeRow"]), int(tube["tubeCol"])
                result = self.results_by_rc.get((iid, row_no, column_no))
                if not result:
                    self.add_conflict("MDB_RESULT_NO_EXISTING_RESULT", relative, f"row={row_no}, column={column_no}, resId={row.get('resId')}", iid)
                    continue
                depth = parse_float(row.get("resDepth"))
                acquired = str(row.get("resTime") or "").strip() or None
                defect_type = str(row.get("resEval") or "").strip() or None
                canonical = ("mdb_result", iid, row_no, column_no, acquired, round(depth, 6) if depth is not None else None, defect_type, round(parse_float(row.get("resLength")) or 0.0, 6))
                fp = fingerprint(*canonical)
                indication_candidates.setdefault(fp, {
                    "fingerprint": fp,
                    "iris_tube_result_id": result["iris_tube_result_id"],
                    "defect_type": defect_type,
                    "acquired_at": acquired,
                    "source_data_path": relative,
                    "raw": {"source_type": "MDB_RESULT", "data": row, "tube": {"row": row_no, "column": column_no}},
                })
                comment = str(row.get("resComment") or "").strip()
                self.add_change("iris_tube_result", "iris_tube_result_id", result["iris_tube_result_id"], "remark", result["remark"], comment or None, relative)
            for section in flatten(tables.get("section", [])):
                name = str(section.get("sectName") or "").strip()
                total = section.get("sectTubes")
                # MAP/CARTO files commonly contain an unused default Section2 row.
                # It must not override the actual bundle section metadata.
                if total in (None, "") or int(total) <= 0 or name.casefold() == "section2":
                    continue
                if name:
                    map_candidates[iid]["orientation"].add(name)
                map_candidates[iid]["total_tubes"].add(int(total))
                inspected = section.get("sectNbrInspected")
                if total not in (None, "") and inspected not in (None, ""):
                    map_candidates[iid]["unmarked_or_untested_tubes"].add(max(int(total) - int(inspected), 0))
        for candidate in indication_candidates.values():
            self._add_indication(candidate)
        self._plan_tube_maps(map_candidates)

    def _plan_tube_maps(self, candidates: dict[int, dict[str, set[Any]]]) -> None:
        for iid, fields in candidates.items():
            row = self.connection.execute("SELECT * FROM iris_tube_map WHERE iris_inspection_id=?", (iid,)).fetchone()
            if not row:
                continue
            for column in ("orientation", "total_tubes", "unmarked_or_untested_tubes"):
                values = fields.get(column, set())
                if len(values) == 1:
                    self.add_change("iris_tube_map", "iris_inspection_id", iid, column, row[column], next(iter(values)), "MAP/CARTO MDB")
                elif len(values) > 1:
                    self.add_conflict("MULTIPLE_MAP_VALUES", "MAP/CARTO MDB", f"{column}={sorted(values, key=str)}", iid)

    def _add_indication(self, candidate: dict[str, Any]) -> None:
        fp = candidate["fingerprint"]
        if fp in self.existing_indication_fingerprints:
            self.counters["indication_existing"] += 1
            return
        self.existing_indication_fingerprints.add(fp)
        result_id = candidate["iris_tube_result_id"]
        candidate["sequence_no"] = self.next_sequence[result_id]
        self.next_sequence[result_id] += 1
        self.indications.append(candidate)

    def deduplicate_changes(self) -> None:
        unique: dict[tuple[str, str, int, str], dict[str, Any]] = {}
        blocked: set[tuple[str, str, int, str]] = set()
        for change in self.changes:
            key = (change["table"], change["key_column"], int(change["key_value"]), change["column"])
            if key in blocked:
                continue
            existing = unique.get(key)
            if existing and str(existing["after"]) != str(change["after"]):
                self.add_conflict("MULTIPLE_CANDIDATE_VALUES", change["source"], f"{key}: {existing['after']} vs {change['after']}", change["key_value"] if change["key_column"] == "iris_inspection_id" else None)
                unique.pop(key, None)
                blocked.add(key)
                continue
            if key not in unique:
                unique[key] = change
        self.changes = sorted(unique.values(), key=lambda item: (item["table"], int(item["key_value"]), item["column"]))

    def write_outputs(self, applied: bool) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._write_csv(self.output_dir / "raw_file_manifest.csv", self.manifest)
        self._write_csv(self.output_dir / "field_change_dry_run.csv", self.changes)
        self._write_csv(self.output_dir / "mapping_conflicts.csv", self.conflicts)
        indication_rows = []
        for item in self.indications:
            row = dict(item)
            row["raw"] = json.dumps(row["raw"], ensure_ascii=False, default=str)
            indication_rows.append(row)
        self._write_csv(self.output_dir / "indication_insert_dry_run.csv", indication_rows)
        summary = {
            "generated_at": datetime.now().astimezone().isoformat(),
            "db_path": str(self.db_path),
            "source_root": str(self.source_root),
            "applied": applied,
            "manifest_files": len(self.manifest),
            "manifest_status": dict(Counter(row["mapping_status"] for row in self.manifest)),
            "field_changes": len(self.changes),
            "field_changes_by_table": dict(Counter(row["table"] for row in self.changes)),
            "indication_inserts": len(self.indications),
            "indication_inserts_by_source": dict(Counter(row["raw"]["source_type"] for row in self.indications)),
            "conflicts": len(self.conflicts),
            "conflicts_by_code": dict(Counter(row["code"] for row in self.conflicts)),
        }
        (self.output_dir / "extraction_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        if not rows:
            path.write_text("", encoding="utf-8-sig")
            return
        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def apply(self) -> None:
        allowed = {
            "iris_tube_result",
            "iris_inspection",
            "inspection_execution_snapshot",
            "iris_setup_snapshot",
            "inspection_personnel",
            "iris_tube_map",
            "inspection_attachment",
            "iris_recommendation",
            "tube_degradation_assessment",
            "inspection_plan_v2",
            "work_order_v2",
            "maintenance_record",
        }
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            for change in self.changes:
                if change["table"] not in allowed:
                    raise ValueError(f"Table is not allowed: {change['table']}")
                sql = f'UPDATE "{change["table"]}" SET "{change["column"]}"=? WHERE "{change["key_column"]}"=? AND "{change["column"]}" IS ?'
                cursor = self.connection.execute(sql, (change["after"], change["key_value"], change["before"]))
                if cursor.rowcount != 1:
                    raise RuntimeError(f"Expected one updated row for {change}, got {cursor.rowcount}")
            for item in self.indications:
                raw_payload = dict(item["raw"])
                raw_payload["fingerprint"] = item["fingerprint"]
                self.connection.execute(
                    """
                    INSERT INTO iris_indication (
                        iris_tube_result_id, sequence_no, axial_position_mm,
                        defect_type, measured_thickness_mm, wall_loss_percent,
                        source_data_path, acquired_at, remaining_percent, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["iris_tube_result_id"], item["sequence_no"], item.get("axial_position_mm"),
                        item.get("defect_type"), item.get("measured_thickness_mm"), item.get("wall_loss_percent"),
                        item.get("source_data_path"), item.get("acquired_at"), item.get("remaining_percent"),
                        json.dumps(raw_payload, ensure_ascii=False, default=str, separators=(",", ":")),
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich IRIS inspection history from VCM1/VCM2 raw data.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mdb-json", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    enricher = Enricher(args.db.resolve(), args.source.resolve(), args.mdb_json.resolve(), args.output_dir.resolve())
    try:
        enricher.scan_files()
        enricher.scan_csv()
        enricher.scan_mdb()
        enricher.deduplicate_changes()
        if args.apply:
            enricher.apply()
        summary = enricher.write_outputs(args.apply)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        enricher.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
