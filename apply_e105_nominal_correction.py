"""Apply the approved VCM2 E-105 2025 nominal-thickness correction.

The source-document JSON and every tube result's raw_json are deliberately
immutable. Only operational/calculated columns are corrected.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(APP_DIR.parent))

from iris2.hx_configuration import DB_PATH, REPORT_DIR


UNIT_CODE = "VCM2"
EQUIPMENT_CODE = "E-105"
REPORT_DATE = "2025-11-01"
NOMINAL_THICKNESS_MM = 2.11
EXPECTED_RESULT_COUNT = 20
CORRECTION_VERSION = "e105-nominal-2.11-v1"


def _round_depth(minimum_thickness_mm: float) -> float:
    return round(max(NOMINAL_THICKNESS_MM - minimum_thickness_mm, 0.0), 2)


def _round_percent(depth_mm: float) -> float:
    return round(depth_mm / NOMINAL_THICKNESS_MM * 100.0, 2)


def apply_correction(*, apply: bool) -> dict:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        inspection_rows = connection.execute(
            """
            select i.iris_inspection_id, i.heat_exchanger_id,
                   i.reported_minimum_thickness_mm,
                   i.reported_maximum_wall_loss_percent,
                   i.reported_average_wall_loss_percent,
                   i.report_status
              from iris_inspection i
              join heat_exchanger h on h.heat_exchanger_id = i.heat_exchanger_id
              join equipment e on e.equipment_id = h.equipment_id
              join process_unit u on u.unit_id = e.unit_id
              left join heat_exchanger_spec_revision s
                on s.heat_exchanger_id=h.heat_exchanger_id and s.is_current=1
             where u.unit_code = ?
               and (e.equipment_code = ? or s.exchanger_code = ?)
               and date(i.report_date) = ?
            """,
            (UNIT_CODE, EQUIPMENT_CODE, EQUIPMENT_CODE, REPORT_DATE),
        ).fetchall()
        if len(inspection_rows) != 1:
            raise RuntimeError(
                f"Expected one {UNIT_CODE} {EQUIPMENT_CODE} inspection on "
                f"{REPORT_DATE}, found {len(inspection_rows)}"
            )
        inspection = inspection_rows[0]
        inspection_id = int(inspection["iris_inspection_id"])
        exchanger_id = int(inspection["heat_exchanger_id"])

        result_rows = connection.execute(
            """
            select r.iris_tube_result_id, r.source_tube_id,
                   r.minimum_wall_thickness_mm, r.wall_loss_depth_mm,
                   r.wall_loss_percent, r.raw_json
              from iris_tube_result r
             where r.iris_inspection_id = ?
             order by r.source_tube_id
            """,
            (inspection_id,),
        ).fetchall()
        if len(result_rows) != EXPECTED_RESULT_COUNT:
            raise RuntimeError(
                f"Expected {EXPECTED_RESULT_COUNT} E-105 results, "
                f"found {len(result_rows)}"
            )
        if any(row["minimum_wall_thickness_mm"] is None for row in result_rows):
            raise RuntimeError("All E-105 correction rows require minimum thickness")

        corrected = []
        for row in result_rows:
            minimum = float(row["minimum_wall_thickness_mm"])
            depth = _round_depth(minimum)
            percent = _round_percent(depth)
            corrected.append({
                "result_id": int(row["iris_tube_result_id"]),
                "tube_no": row["source_tube_id"],
                "minimum_thickness_mm": minimum,
                "before_depth_mm": row["wall_loss_depth_mm"],
                "before_percent": row["wall_loss_percent"],
                "after_depth_mm": depth,
                "after_percent": percent,
                "raw_json_preserved": row["raw_json"] is not None,
            })

        minimum = min(item["minimum_thickness_mm"] for item in corrected)
        maximum_percent = max(item["after_percent"] for item in corrected)
        average_percent = round(
            sum(item["after_percent"] for item in corrected) / len(corrected), 2
        )
        representative = max(
            corrected, key=lambda item: (item["after_percent"], item["tube_no"])
        )

        spec_rows = connection.execute(
            """
            select spec_revision_id, revision_no, is_current,
                   tube_nominal_thickness_mm
              from heat_exchanger_spec_revision
             where heat_exchanger_id = ?
             order by is_current desc, revision_no desc
            """,
            (exchanger_id,),
        ).fetchall()
        if not spec_rows:
            raise RuntimeError("E-105 requires an existing specification revision")
        current_spec = spec_rows[0]

        summary = {
            "status": "READY_TO_APPLY" if not apply else "APPLIED",
            "correction_version": CORRECTION_VERSION,
            "database": str(DB_PATH),
            "unit": UNIT_CODE,
            "equipment": EQUIPMENT_CODE,
            "report_date": REPORT_DATE,
            "inspection_id": inspection_id,
            "heat_exchanger_id": exchanger_id,
            "nominal_thickness_mm": NOMINAL_THICKNESS_MM,
            "result_count": len(corrected),
            "source_json_preserved": True,
            "tube_raw_json_preserved": all(
                item["raw_json_preserved"] for item in corrected
            ),
            "before": {
                "master_nominal_thickness_mm": current_spec[
                    "tube_nominal_thickness_mm"
                ],
                "reported_minimum_thickness_mm": inspection[
                    "reported_minimum_thickness_mm"
                ],
                "reported_maximum_wall_loss_percent": inspection[
                    "reported_maximum_wall_loss_percent"
                ],
                "reported_average_wall_loss_percent": inspection[
                    "reported_average_wall_loss_percent"
                ],
                "report_status": inspection["report_status"],
            },
            "after": {
                "master_nominal_thickness_mm": NOMINAL_THICKNESS_MM,
                "minimum_thickness_mm": minimum,
                "maximum_wall_loss_percent": maximum_percent,
                "average_wall_loss_percent": average_percent,
                "representative_tube": representative["tube_no"],
                "representative_wall_loss_percent": representative[
                    "after_percent"
                ],
            },
            "results": corrected,
        }
        if not apply:
            return summary

        connection.execute("begin immediate")
        for item in corrected:
            connection.execute(
                """
                update iris_tube_result
                   set wall_loss_depth_mm = ?, wall_loss_percent = ?,
                       quality_status = 'CORRECTED'
                 where iris_tube_result_id = ?
                """,
                (
                    item["after_depth_mm"], item["after_percent"],
                    item["result_id"],
                ),
            )
        connection.execute(
            """
            update iris_inspection
               set reported_minimum_thickness_mm = ?,
                   reported_maximum_wall_loss_percent = ?,
                   reported_average_wall_loss_percent = ?,
                   report_status = 'LOADED_WITH_CORRECTION'
             where iris_inspection_id = ?
            """,
            (minimum, maximum_percent, average_percent, inspection_id),
        )
        connection.execute(
            """
            update iris_inspection_spec_snapshot
               set report_nominal_thickness_mm = ?
             where iris_inspection_id = ?
            """,
            (NOMINAL_THICKNESS_MM, inspection_id),
        )
        connection.execute(
            """
            update heat_exchanger_spec_revision
               set tube_nominal_thickness_mm = ?
             where spec_revision_id = ?
            """,
            (NOMINAL_THICKNESS_MM, current_spec["spec_revision_id"]),
        )
        connection.execute(
            """
            update iris_representative_assessment
               set target_tube = ?, minimum_thickness_mm = ?,
                   wall_loss_percent = ?
             where iris_inspection_id = ?
            """,
            (
                representative["tube_no"],
                representative["minimum_thickness_mm"],
                representative["after_percent"], inspection_id,
            ),
        )
        connection.execute(
            """
            update inspection_validation
               set calculated_minimum_thickness_mm = ?,
                   calculated_maximum_wall_loss_percent = ?,
                   calculated_average_wall_loss_percent = ?,
                   formula_check_passed = 1,
                   validation_status = 'VALID_CORRECTED',
                   validator_version = ?
             where iris_inspection_id = ?
            """,
            (
                minimum, maximum_percent, average_percent,
                CORRECTION_VERSION, inspection_id,
            ),
        )
        connection.commit()
        return summary
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def write_report(summary: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"e105_nominal_correction_{timestamp}.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Correct 2025 VCM2 E-105 wall loss using 2.11 mm nominal thickness"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="commit the correction; without this flag only preview it",
    )
    args = parser.parse_args()
    summary = apply_correction(apply=args.apply)
    if args.apply:
        from iris2.iris_v2_history import rebuild_degradation_assessments

        summary["degradation_assessment_count"] = (
            rebuild_degradation_assessments()
        )
    report = write_report(summary)
    summary["report"] = str(report)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
