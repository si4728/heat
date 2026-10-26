from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pdfplumber


PROJECT = Path(r"C:\access\heat\iris2")
TARGET = PROJECT / "data" / "2021VCM1_IRIS2_all_tube_results.json"
SOURCE_PDF = PROJECT / "iris_test_report" / "2021_1P_VCM1.pdf"
MANIFEST = (
    PROJECT
    / "outputs"
    / "json_pdf_finalization_2021_vcm1_20260825"
    / "20260825_114843"
    / "2021VCM1_PDF_FINALIZATION_MANIFEST_20260825.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_value(
    container: dict[str, Any],
    key: str,
    value: Any,
    changes: list[dict[str, Any]],
    sequence: int,
    field: str,
) -> None:
    old = container.get(key)
    if old == value:
        return
    container[key] = value
    changes.append(
        {
            "report_sequence": sequence,
            "field": field,
            "legacy_value": old,
            "normalized_value": value,
        }
    )


def parse_measurement_environment(text: str) -> tuple[float, float]:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s+Kg/Cm\s*2\s+(\d+(?:\.\d+)?)", text
    )
    if not match:
        raise AssertionError("Water pressure/temperature could not be parsed")
    return float(match.group(1)), float(match.group(2))


def parse_figure(text: str) -> tuple[str, float, float, str]:
    tube_line = next(line for line in text.splitlines() if "TUBE NO" in line)
    thickness_match = re.search(r"(\d+(?:\.\d+)?)mm", tube_line)
    if not thickness_match:
        raise AssertionError(f"Figure thickness could not be parsed: {tube_line}")
    before_thickness = tube_line[: thickness_match.start()]
    tube_ids = re.findall(r"\d+\s*-\s*\d+", before_thickness.split(":", 1)[1])
    if not tube_ids:
        raise AssertionError(f"Figure Tube ID could not be parsed: {tube_line}")
    target_tube = ",".join(re.sub(r"\s+", "", value) for value in tube_ids)

    defect_line = next(
        line
        for line in text.splitlines()
        if re.search(r"(?:INTERNAL|EXTERNAL)\s+(?:CORROSION|PITTING)", line)
        and "%" in line
    )
    defect_match = re.search(
        r"((?:INTERNAL|EXTERNAL)\s+(?:CORROSION|PITTING)).*?"
        r"(\d+(?:\.\d+)?)%",
        defect_line,
    )
    if not defect_match:
        raise AssertionError(f"Figure defect could not be parsed: {defect_line}")
    return (
        target_tube,
        float(thickness_match.group(1)),
        float(defect_match.group(2)),
        defect_match.group(1),
    )


def main() -> None:
    payload = json.loads(TARGET.read_text(encoding="utf-8"))
    changes: list[dict[str, Any]] = []
    with pdfplumber.open(SOURCE_PDF) as pdf:
        for item in payload["inspection_reports"]:
            report = item["report"]
            sequence = report["report_sequence"]
            page = report["source_report_pages"][0]
            text = pdf.pages[page - 1].extract_text(
                x_tolerance=2, y_tolerance=2
            ) or ""
            pressure, temperature = parse_measurement_environment(text)
            measurement = report["iris_report_details"]["measurement_conditions"]
            set_value(
                measurement,
                "water_pressure_kg_per_cm2",
                pressure,
                changes,
                sequence,
                "iris_report_details.measurement_conditions.water_pressure_kg_per_cm2",
            )
            set_value(
                measurement,
                "water_temperature_celsius",
                temperature,
                changes,
                sequence,
                "iris_report_details.measurement_conditions.water_temperature_celsius",
            )

            target_tube, minimum, wall_loss, defect_type = parse_figure(text)
            assessment = report["iris_report_details"][
                "representative_defect_assessment"
            ]
            for key, value in (
                ("target_tube", target_tube),
                ("minimum_thickness_mm", minimum),
                ("wall_loss_percent", wall_loss),
                ("defect_type", defect_type),
            ):
                set_value(
                    assessment,
                    key,
                    value,
                    changes,
                    sequence,
                    f"iris_report_details.representative_defect_assessment.{key}",
                )

    TARGET.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["changes"].extend(changes)
    manifest["field_change_count"] = len(manifest["changes"])
    manifest["sha256_after"] = sha256(TARGET)
    manifest["report_field_enrichment"] = {
        "applied_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "all 30 individual report pages",
        "fields": [
            "water_pressure_kg_per_cm2",
            "water_temperature_celsius",
            "representative_defect_assessment.target_tube",
            "representative_defect_assessment.minimum_thickness_mm",
            "representative_defect_assessment.wall_loss_percent",
            "representative_defect_assessment.defect_type",
        ],
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "target": str(TARGET),
                "manifest": str(MANIFEST),
                "added_changes": len(changes),
                "sha256_after": manifest["sha256_after"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
