from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    project_dir = Path(__file__).resolve().parent.parent
    if str(project_dir) not in sys.path:
        sys.path.insert(0, str(project_dir))
    from iris2.hx_configuration import APP_DIR, DB_PATH
else:
    from .hx_configuration import APP_DIR, DB_PATH


COUNT_KEYS = {"tube_count", "total_tube_count", "total_tubes", "expected_tube_count"}
SPEC_COLUMNS = (
    "exchanger_code", "source_document_id", "effective_from", "effective_to", "design_pressure",
    "design_temperature", "operation_pressure", "operation_temperature",
    "shell_material", "tube_material", "tube_outer_diameter_mm",
    "tube_nominal_thickness_mm", "tube_length_mm", "bundle_type", "pass_count",
    "tube_pitch_mm", "drawing_no", "datasheet_no", "raw_json",
    "heat_transfer_area_m2", "shell_fluid", "tube_fluid",
    "installation_orientation", "raw_size_text", "master_etc",
)


def _positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number > 0 and number.is_integer() else None


def _json_counts(value: Any, path: str = "") -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in COUNT_KEYS:
                count = _positive_integer(child)
                if count is not None:
                    found.append((count, child_path))
            found.extend(_json_counts(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_json_counts(child, f"{path}[{index}]"))
    return found


def _key(unit_code: str, equipment_code: str) -> tuple[str, str]:
    return unit_code.strip().upper(), equipment_code.strip().upper()


def collect_resolutions(connection: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    identities: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for row in connection.execute("""
        SELECT hx.heat_exchanger_id, p.plant_code, u.unit_code, e.equipment_code
          FROM heat_exchanger hx
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
          JOIN plant p ON p.plant_id = u.plant_id
    """):
        identities[_key(row["unit_code"], row["equipment_code"])].append(row)

    for row in connection.execute("""
        SELECT u.unit_code, e.equipment_code, s.tube_count, s.spec_revision_id
          FROM heat_exchanger_spec_revision s
          JOIN heat_exchanger hx ON hx.heat_exchanger_id = s.heat_exchanger_id
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
         WHERE s.tube_count > 0
    """):
        candidates[_key(row["unit_code"], row["equipment_code"])].append({
            "count": int(row["tube_count"]), "source": "spec_revision",
            "source_id": row["spec_revision_id"],
        })

    for row in connection.execute("""
        SELECT u.unit_code, e.equipment_code, b.expected_tube_count, b.bundle_id
          FROM tube_bundle b
          JOIN heat_exchanger hx ON hx.heat_exchanger_id = b.heat_exchanger_id
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
         WHERE b.expected_tube_count > 0
    """):
        candidates[_key(row["unit_code"], row["equipment_code"])].append({
            "count": int(row["expected_tube_count"]), "source": "bundle",
            "source_id": row["bundle_id"],
        })

    for row in connection.execute("""
        SELECT u.unit_code, e.equipment_code, i.total_tube_count_reported,
               i.raw_report_json, i.iris_inspection_id
          FROM iris_inspection i
          JOIN heat_exchanger hx ON hx.heat_exchanger_id = i.heat_exchanger_id
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
    """):
        identity = _key(row["unit_code"], row["equipment_code"])
        reported = _positive_integer(row["total_tube_count_reported"])
        if reported is not None:
            candidates[identity].append({
                "count": reported, "source": "inspection_report",
                "source_id": row["iris_inspection_id"],
            })
        try:
            raw = json.loads(row["raw_report_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            raw = {}
        for count, path in _json_counts(raw):
            candidates[identity].append({
                "count": count, "source": f"inspection_json:{path}",
                "source_id": row["iris_inspection_id"],
            })

    for row in connection.execute("""
        SELECT u.unit_code, e.equipment_code, COUNT(t.tube_id) AS tube_count
          FROM heat_exchanger hx
          JOIN equipment e ON e.equipment_id = hx.equipment_id
          JOIN process_unit u ON u.unit_id = e.unit_id
          JOIN tube_bundle b ON b.heat_exchanger_id = hx.heat_exchanger_id
          JOIN heat_exchanger_tube t ON t.bundle_id = b.bundle_id
         GROUP BY u.unit_code, e.equipment_code
    """):
        candidates[_key(row["unit_code"], row["equipment_code"])].append({
            "count": int(row["tube_count"]), "source": "tube_master",
            "source_id": None,
        })

    resolutions: dict[int, dict[str, Any]] = {}
    for identity, exchanger_rows in identities.items():
        values = candidates.get(identity, [])
        if not values:
            continue
        maximum = max(item["count"] for item in values)
        maximum_sources = [item for item in values if item["count"] == maximum]
        for exchanger in exchanger_rows:
            resolutions[exchanger["heat_exchanger_id"]] = {
                "plant_code": exchanger["plant_code"],
                "unit_code": exchanger["unit_code"],
                "equipment_code": exchanger["equipment_code"],
                "tube_count": maximum,
                "sources": maximum_sources,
            }
    return resolutions


def _backup_database(connection: sqlite3.Connection, database_path: Path) -> Path:
    backup_dir = APP_DIR / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"pre_tube_count_reconcile_{datetime.now():%Y%m%d_%H%M%S}.db"
    backup_connection = sqlite3.connect(backup_path)
    try:
        connection.backup(backup_connection)
    finally:
        backup_connection.close()
    return backup_path


def apply_resolutions(connection: sqlite3.Connection,
                      resolutions: dict[int, dict[str, Any]]) -> dict[str, int]:
    now = datetime.now().isoformat(timespec="seconds")
    result = {
        "resolved_exchangers": len(resolutions), "new_spec_revisions": 0,
        "unchanged_specs": 0, "created_bundles": 0, "updated_bundles": 0,
    }
    connection.execute("BEGIN IMMEDIATE")
    try:
        for exchanger_id, resolution in resolutions.items():
            target = resolution["tube_count"]
            current = connection.execute("""
                SELECT * FROM heat_exchanger_spec_revision
                 WHERE heat_exchanger_id = ?
                 ORDER BY is_current DESC, revision_no DESC
                 LIMIT 1
            """, (exchanger_id,)).fetchone()
            if current is not None and current["tube_count"] == target and current["is_current"]:
                result["unchanged_specs"] += 1
            else:
                max_revision = connection.execute(
                    "SELECT COALESCE(MAX(revision_no), 0) FROM heat_exchanger_spec_revision WHERE heat_exchanger_id = ?",
                    (exchanger_id,),
                ).fetchone()[0]
                connection.execute("""
                    UPDATE heat_exchanger_spec_revision
                       SET is_current = 0,
                           effective_to = COALESCE(effective_to, ?)
                     WHERE heat_exchanger_id = ? AND is_current = 1
                """, (now, exchanger_id))
                copied = {column: current[column] if current is not None else None
                          for column in SPEC_COLUMNS}
                copied["effective_from"] = now
                copied["effective_to"] = None
                revision_code = f"TC-{datetime.now():%Y%m%d%H%M%S}-R{max_revision + 1}"
                columns = [
                    "heat_exchanger_id", "revision_no", "revision_code",
                    "is_current", "tube_count", *SPEC_COLUMNS,
                ]
                values = [exchanger_id, max_revision + 1, revision_code, 1, target,
                          *(copied[column] for column in SPEC_COLUMNS)]
                placeholders = ", ".join("?" for _ in columns)
                connection.execute(
                    f"INSERT INTO heat_exchanger_spec_revision ({', '.join(columns)}) VALUES ({placeholders})",
                    values,
                )
                result["new_spec_revisions"] += 1

            bundles = connection.execute("""
                SELECT bundle_id, expected_tube_count
                  FROM tube_bundle
                 WHERE heat_exchanger_id = ? AND retired_at IS NULL
                 ORDER BY lifecycle_no DESC, bundle_id DESC
            """, (exchanger_id,)).fetchall()
            if not bundles:
                lifecycle_no = connection.execute(
                    "SELECT COALESCE(MAX(lifecycle_no), 0) + 1 FROM tube_bundle WHERE heat_exchanger_id = ?",
                    (exchanger_id,),
                ).fetchone()[0]
                connection.execute("""
                    INSERT INTO tube_bundle
                        (heat_exchanger_id, bundle_code, lifecycle_no,
                         expected_tube_count, status)
                    VALUES (?, 'MAIN', ?, ?, 'ACTIVE')
                """, (exchanger_id, lifecycle_no, target))
                result["created_bundles"] += 1
            else:
                for bundle in bundles:
                    if bundle["expected_tube_count"] != target:
                        connection.execute(
                            "UPDATE tube_bundle SET expected_tube_count = ? WHERE bundle_id = ?",
                            (target, bundle["bundle_id"]),
                        )
                        result["updated_bundles"] += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile exchanger tube counts using the maximum explicit count per line/equipment."
    )
    parser.add_argument("--apply", action="store_true", help="Apply changes; otherwise preview only.")
    args = parser.parse_args()

    database_path = Path(DB_PATH).resolve()
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        resolutions = collect_resolutions(connection)
        preview = {
            "database": str(database_path),
            "resolved_exchangers": len(resolutions),
            "unresolved_exchangers": connection.execute(
                "SELECT COUNT(*) FROM heat_exchanger"
            ).fetchone()[0] - len(resolutions),
            "maximum_tube_count": max(
                (item["tube_count"] for item in resolutions.values()), default=0
            ),
        }
        if not args.apply:
            print(json.dumps({"mode": "preview", **preview}, ensure_ascii=False, indent=2))
            return 0
        backup_path = _backup_database(connection, database_path)
        result = apply_resolutions(connection, resolutions)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        print(json.dumps({
            "mode": "applied", **preview, **result,
            "backup": str(backup_path), "integrity_check": integrity,
        }, ensure_ascii=False, indent=2))
        return 0 if integrity == "ok" else 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
