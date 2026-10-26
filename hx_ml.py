"""VCM1/VCM2 Wall Loss anomaly detection.

The production database is always opened in SQLite read-only mode.  The model
creates review reports only; it never changes measurements or maintenance state.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from iris2 import dbapi as db
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import numpy as np
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler


if __package__ in (None, ""):
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    from iris2.hx_configuration import (
        DB_PATH,
        ML_CONTAMINATION,
        ML_ESTIMATORS,
        ML_RANDOM_STATE,
        ML_TOP_RESULTS,
        ML_UNITS,
        REPORT_DIR,
    )
else:
    from .hx_configuration import (
        DB_PATH,
        ML_CONTAMINATION,
        ML_ESTIMATORS,
        ML_RANDOM_STATE,
        ML_TOP_RESULTS,
        ML_UNITS,
        REPORT_DIR,
    )


MODEL_NAME = "IsolationForest"
MODEL_VERSION = "hx-wall-loss-iforest-1.0"
SUPPORTED_UNITS = ("VCM1", "VCM2")
DEFAULT_UNITS = ML_UNITS
FEATURE_COLUMNS = (
    "wall_loss_percent",
    "wall_loss_depth_mm",
    "minimum_wall_thickness_mm",
    "implied_nominal_mm",
    "formula_residual_pp",
    "unit_year_deviation_pp",
    "exchanger_year_deviation_pp",
    "previous_wall_loss_percent",
    "wall_loss_delta_pp",
    "absolute_delta_pp",
    "year_gap",
    "duplicate_scope_spread_pp",
    "minimum_thickness_missing",
    "wall_loss_depth_missing",
)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _readonly_connection(database_path: Path) -> db.Connection:
    resolved = database_path.resolve()
    if not db.exists(resolved):
        raise FileNotFoundError(f"Database not found: {resolved}")
    connection = db.connect(
        f"file:{resolved.as_posix()}?mode=ro",
        uri=True,
    )
    connection.row_factory = db.Row
    return connection


def load_wall_loss_rows(
    database_path: Path,
    units: Iterable[str] = DEFAULT_UNITS,
) -> list[dict[str, Any]]:
    selected_units = tuple(dict.fromkeys(unit.upper() for unit in units))
    if not selected_units:
        raise ValueError("At least one production line is required")
    unsupported = sorted(set(selected_units) - set(SUPPORTED_UNITS))
    if unsupported:
        raise ValueError(f"Unsupported production lines: {', '.join(unsupported)}")

    placeholders = ",".join("?" for _ in selected_units)
    query = f"""
        SELECT
            u.unit_code,
            c.campaign_year,
            e.equipment_code,
            i.iris_inspection_id,
            COALESCE(sc.scope_code, 'ALL') AS scope_code,
            r.iris_tube_result_id,
            r.tube_id,
            COALESCE(t.tube_no, r.source_tube_id) AS tube_no,
            r.wall_loss_percent,
            r.wall_loss_depth_mm,
            r.minimum_wall_thickness_mm,
            r.corrosion_type,
            r.quality_status
        FROM iris_tube_result r
        JOIN iris_inspection i
          ON i.iris_inspection_id = r.iris_inspection_id
        JOIN inspection_campaign c ON c.campaign_id = i.campaign_id
        JOIN process_unit u ON u.unit_id = c.unit_id
        JOIN heat_exchanger h ON h.heat_exchanger_id = i.heat_exchanger_id
        JOIN equipment e ON e.equipment_id = h.equipment_id
        LEFT JOIN inspection_scope sc
          ON sc.inspection_scope_id = i.inspection_scope_id
        LEFT JOIN heat_exchanger_tube t ON t.tube_id = r.tube_id
        WHERE u.unit_code IN ({placeholders})
          AND r.wall_loss_percent IS NOT NULL
        ORDER BY u.unit_code, c.campaign_year, e.equipment_code,
                 r.tube_id, i.iris_inspection_id
    """
    with _readonly_connection(database_path) as connection:
        rows = [dict(row) for row in connection.execute(query, selected_units)]
    if not rows:
        raise RuntimeError("No Wall Loss rows were found for the selected production lines")
    return rows


def _group_medians(
    rows: list[dict[str, Any]],
    key_fields: tuple[str, ...],
) -> dict[tuple[Any, ...], float]:
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = _finite(row["wall_loss_percent"])
        if value is not None:
            grouped[tuple(row[field] for field in key_fields)].append(value)
    return {key: float(median(values)) for key, values in grouped.items()}


def engineer_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unit_year_median = _group_medians(rows, ("unit_code", "campaign_year"))
    exchanger_year_median = _group_medians(
        rows, ("unit_code", "campaign_year", "equipment_code")
    )

    duplicate_values: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    tube_year_values: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in rows:
        value = float(row["wall_loss_percent"])
        duplicate_key = (
            row["unit_code"],
            row["campaign_year"],
            row["equipment_code"],
            row["tube_id"],
        )
        duplicate_values[duplicate_key].append(value)
        tube_year_values[
            (row["unit_code"], row["tube_id"], row["campaign_year"])
        ].append(value)

    tube_history: dict[tuple[Any, ...], list[tuple[int, float]]] = defaultdict(list)
    for (unit_code, tube_id, year), values in tube_year_values.items():
        if tube_id is not None:
            tube_history[(unit_code, tube_id)].append((int(year), max(values)))
    for history in tube_history.values():
        history.sort()

    previous_lookup: dict[tuple[Any, ...], tuple[int, float]] = {}
    for (unit_code, tube_id), history in tube_history.items():
        previous: tuple[int, float] | None = None
        for year, value in history:
            if previous is not None:
                previous_lookup[(unit_code, tube_id, year)] = previous
            previous = (year, value)

    engineered: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        loss = float(row["wall_loss_percent"])
        depth = _finite(row["wall_loss_depth_mm"])
        thickness = _finite(row["minimum_wall_thickness_mm"])
        implied_nominal = (
            depth + thickness if depth is not None and thickness is not None else None
        )
        calculated_loss = (
            100.0 * depth / implied_nominal
            if depth is not None and implied_nominal and implied_nominal > 0
            else None
        )
        formula_residual = (
            abs(calculated_loss - loss) if calculated_loss is not None else None
        )
        duplicate_key = (
            row["unit_code"],
            row["campaign_year"],
            row["equipment_code"],
            row["tube_id"],
        )
        duplicate_group = duplicate_values[duplicate_key]
        duplicate_spread = max(duplicate_group) - min(duplicate_group)

        previous = previous_lookup.get(
            (row["unit_code"], row["tube_id"], row["campaign_year"])
        )
        previous_loss = previous[1] if previous else None
        year_gap = int(row["campaign_year"]) - previous[0] if previous else None
        delta = loss - previous_loss if previous_loss is not None else None

        row.update(
            wall_loss_percent=loss,
            wall_loss_depth_mm=depth,
            minimum_wall_thickness_mm=thickness,
            implied_nominal_mm=implied_nominal,
            formula_residual_pp=formula_residual,
            unit_year_deviation_pp=(
                loss
                - unit_year_median[(row["unit_code"], row["campaign_year"])]
            ),
            exchanger_year_deviation_pp=(
                loss
                - exchanger_year_median[
                    (
                        row["unit_code"],
                        row["campaign_year"],
                        row["equipment_code"],
                    )
                ]
            ),
            previous_wall_loss_percent=previous_loss,
            wall_loss_delta_pp=delta,
            absolute_delta_pp=abs(delta) if delta is not None else None,
            year_gap=year_gap,
            duplicate_scope_spread_pp=duplicate_spread,
            minimum_thickness_missing=int(thickness is None),
            wall_loss_depth_missing=int(depth is None),
        )
        engineered.append(row)
    return engineered


def _rule_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    loss = row["wall_loss_percent"]
    if loss >= 40:
        flags.append("VERY_HIGH_WALL_LOSS_GE_40")
    elif loss >= 30:
        flags.append("HIGH_WALL_LOSS_GE_30")
    elif loss >= 20:
        flags.append("ELEVATED_WALL_LOSS_GE_20")
    if row["minimum_thickness_missing"]:
        flags.append("MINIMUM_THICKNESS_MISSING")
    if row["wall_loss_depth_missing"]:
        flags.append("WALL_LOSS_DEPTH_MISSING")
    residual = row["formula_residual_pp"]
    if residual is not None and residual > 1.0:
        flags.append("FORMULA_RESIDUAL_GT_1PP")
    delta = row["wall_loss_delta_pp"]
    if delta is not None and delta >= 10.0:
        flags.append("TEMPORAL_RISE_GE_10PP")
    elif delta is not None and delta <= -10.0:
        flags.append("TEMPORAL_DROP_GE_10PP")
    if row["duplicate_scope_spread_pp"] >= 5.0:
        flags.append("TOP_BTM_SPREAD_GE_5PP")
    return flags


def fit_isolation_forests(
    rows: list[dict[str, Any]],
    *,
    contamination: float = ML_CONTAMINATION,
    random_state: int = ML_RANDOM_STATE,
    estimators: int = ML_ESTIMATORS,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not 0 < contamination <= 0.5:
        raise ValueError("contamination must be greater than 0 and no more than 0.5")
    if estimators < 50:
        raise ValueError("estimators must be at least 50")

    unit_summaries: dict[str, dict[str, Any]] = {}
    for unit_code in sorted({row["unit_code"] for row in rows}):
        unit_rows = [row for row in rows if row["unit_code"] == unit_code]
        raw_matrix = np.array(
            [
                [
                    np.nan if row[column] is None else float(row[column])
                    for column in FEATURE_COLUMNS
                ]
                for row in unit_rows
            ],
            dtype=float,
        )
        imputer = SimpleImputer(strategy="median", add_indicator=True)
        scaler = RobustScaler()
        matrix = scaler.fit_transform(imputer.fit_transform(raw_matrix))
        model = IsolationForest(
            n_estimators=estimators,
            contamination=contamination,
            random_state=random_state,
            n_jobs=-1,
        )
        labels = model.fit_predict(matrix)
        scores = -model.score_samples(matrix)
        ranked_indices = sorted(
            range(len(unit_rows)), key=lambda index: scores[index], reverse=True
        )
        rank_lookup = {index: rank + 1 for rank, index in enumerate(ranked_indices)}

        for index, row in enumerate(unit_rows):
            rank = rank_lookup[index]
            row["ml_anomaly"] = bool(labels[index] == -1)
            row["ml_anomaly_score"] = float(scores[index])
            row["ml_anomaly_rank"] = rank
            row["ml_anomaly_percentile"] = 100.0 * (
                1.0 - (rank - 1) / max(len(unit_rows), 1)
            )
            row["review_flags"] = _rule_flags(row)

        anomaly_rows = [row for row in unit_rows if row["ml_anomaly"]]
        unit_summaries[unit_code] = {
            "total_rows": len(unit_rows),
            "model_anomalies": len(anomaly_rows),
            "model_anomaly_percent": round(100.0 * len(anomaly_rows) / len(unit_rows), 2),
            "wall_loss_ge_20": sum(row["wall_loss_percent"] >= 20 for row in unit_rows),
            "wall_loss_ge_30": sum(row["wall_loss_percent"] >= 30 for row in unit_rows),
            "wall_loss_ge_40": sum(row["wall_loss_percent"] >= 40 for row in unit_rows),
            "minimum_thickness_missing": sum(
                row["minimum_thickness_missing"] for row in unit_rows
            ),
            "formula_residual_gt_1pp": sum(
                row["formula_residual_pp"] is not None
                and row["formula_residual_pp"] > 1.0
                for row in unit_rows
            ),
            "temporal_change_ge_10pp": sum(
                row["absolute_delta_pp"] is not None
                and row["absolute_delta_pp"] >= 10.0
                for row in unit_rows
            ),
            "anomaly_and_wall_loss_ge_30": sum(
                row["ml_anomaly"] and row["wall_loss_percent"] >= 30
                for row in unit_rows
            ),
        }
    return rows, unit_summaries


CSV_FIELDS = (
    "unit_code",
    "campaign_year",
    "equipment_code",
    "tube_no",
    "scope_code",
    "iris_inspection_id",
    "iris_tube_result_id",
    "tube_id",
    "wall_loss_percent",
    "wall_loss_depth_mm",
    "minimum_wall_thickness_mm",
    "corrosion_type",
    "quality_status",
    "previous_wall_loss_percent",
    "wall_loss_delta_pp",
    "formula_residual_pp",
    "duplicate_scope_spread_pp",
    "ml_anomaly",
    "ml_anomaly_score",
    "ml_anomaly_rank",
    "ml_anomaly_percentile",
    "review_flags",
)


def _report_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (row for row in rows if row["ml_anomaly"]),
        key=lambda row: (row["unit_code"], row["ml_anomaly_rank"]),
    )


def _bar_chart(
    title: str,
    categories: list[str],
    series: list[tuple[str, list[float], str]],
) -> str:
    width, height = 900, 330
    left, right, top, bottom = 72, 24, 46, 64
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max((value for _, values, _ in series for value in values), default=1)
    maximum = max(maximum, 1)
    group_width = plot_width / max(len(categories), 1)
    bar_width = min(34, group_width * 0.72 / max(len(series), 1))
    elements = [f'<text x="{left}" y="25" class="chart-title">{html.escape(title)}</text>']
    for tick in range(5):
        value = maximum * tick / 4
        y = top + plot_height - plot_height * tick / 4
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" class="gridline"/>')
        elements.append(f'<text x="{left-9}" y="{y+4:.1f}" class="axis" text-anchor="end">{value:,.0f}</text>')
    for category_index, category in enumerate(categories):
        center = left + group_width * (category_index + 0.5)
        elements.append(f'<text x="{center:.1f}" y="{height-35}" class="axis" text-anchor="middle">{html.escape(category)}</text>')
        for series_index, (_, values, color) in enumerate(series):
            value = values[category_index]
            bar_height = plot_height * value / maximum
            x = center - (len(series) * bar_width) / 2 + series_index * bar_width
            y = top + plot_height - bar_height
            elements.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width-3:.1f}" height="{bar_height:.1f}" rx="3" fill="{color}"/>')
            elements.append(f'<text x="{x+(bar_width-3)/2:.1f}" y="{max(y-5, top+10):.1f}" class="value" text-anchor="middle">{value:,.0f}</text>')
    legend_x = left
    for name, _, color in series:
        elements.append(f'<rect x="{legend_x}" y="{height-18}" width="12" height="12" rx="2" fill="{color}"/>')
        elements.append(f'<text x="{legend_x+17}" y="{height-8}" class="axis">{html.escape(name)}</text>')
        legend_x += 135
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _horizontal_bar_chart(title: str, items: list[tuple[str, int]]) -> str:
    width = 900
    row_height = 28
    height = 65 + row_height * len(items)
    left, right, top = 145, 48, 45
    plot_width = width - left - right
    maximum = max((value for _, value in items), default=1)
    elements = [f'<text x="{left}" y="25" class="chart-title">{html.escape(title)}</text>']
    for index, (label, value) in enumerate(items):
        y = top + index * row_height
        bar_width = plot_width * value / maximum
        elements.append(f'<text x="{left-10}" y="{y+16}" class="axis" text-anchor="end">{html.escape(label)}</text>')
        elements.append(f'<rect x="{left}" y="{y}" width="{bar_width:.1f}" height="19" rx="4" fill="#7c3aed"/>')
        elements.append(f'<text x="{left+bar_width+7:.1f}" y="{y+15}" class="value">{value}</text>')
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _scatter_chart(title: str, rows: list[dict[str, Any]]) -> str:
    width, height = 900, 380
    left, right, top, bottom = 70, 25, 45, 52
    plot_width, plot_height = width - left - right, height - top - bottom
    maximum_loss = max((row["wall_loss_percent"] for row in rows), default=100)
    maximum_loss = max(100.0, maximum_loss)
    scores = [row["ml_anomaly_score"] for row in rows]
    minimum_score = min(scores, default=0)
    maximum_score = max(scores, default=1)
    score_range = max(maximum_score - minimum_score, 0.001)
    elements = [f'<text x="{left}" y="25" class="chart-title">{html.escape(title)}</text>']
    for tick in range(6):
        loss = maximum_loss * tick / 5
        x = left + plot_width * tick / 5
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+plot_height}" class="gridline"/>')
        elements.append(f'<text x="{x:.1f}" y="{height-25}" class="axis" text-anchor="middle">{loss:.0f}%</text>')
    for row in rows:
        x = left + plot_width * row["wall_loss_percent"] / maximum_loss
        y = top + plot_height * (maximum_score - row["ml_anomaly_score"]) / score_range
        color = "#ef4444" if row["unit_code"] == "VCM2" else "#2563eb"
        label = html.escape(f'{row["unit_code"]} {row["equipment_code"]} {row["tube_no"]}: {row["wall_loss_percent"]:.2f}%')
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{color}" fill-opacity="0.72"><title>{label}</title></circle>')
    elements.append(f'<text x="{left+plot_width/2:.1f}" y="{height-5}" class="axis" text-anchor="middle">Wall Loss (%)</text>')
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _write_graph_report(
    rows: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    graph_path: Path,
    *,
    contamination: float,
) -> None:
    units = sorted(summaries)
    anomalies = _report_rows(rows)
    severity_chart = _bar_chart(
        "Wall Loss severity and ML review targets",
        units,
        [
            ("ML anomalies", [summaries[u]["model_anomalies"] for u in units], "#7c3aed"),
            (">=20%", [summaries[u]["wall_loss_ge_20"] for u in units], "#f59e0b"),
            (">=30%", [summaries[u]["wall_loss_ge_30"] for u in units], "#f97316"),
            (">=40%", [summaries[u]["wall_loss_ge_40"] for u in units], "#dc2626"),
        ],
    )
    quality_chart = _bar_chart(
        "Data-quality review indicators",
        units,
        [
            ("Missing thickness", [summaries[u]["minimum_thickness_missing"] for u in units], "#0891b2"),
            ("Formula >1pp", [summaries[u]["formula_residual_gt_1pp"] for u in units], "#db2777"),
            ("Temporal >=10pp", [summaries[u]["temporal_change_ge_10pp"] for u in units], "#65a30d"),
        ],
    )
    exchanger_counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in anomalies:
        exchanger_counts[(row["unit_code"], row["equipment_code"])] += 1
    top_exchangers = sorted(exchanger_counts.items(), key=lambda item: (-item[1], item[0]))[:15]
    exchanger_chart = _horizontal_bar_chart(
        "Top exchangers by ML anomaly count",
        [(f"{unit} {equipment}", count) for (unit, equipment), count in top_exchangers],
    )
    cards = "".join(
        f'<div class="card"><span>{html.escape(unit)}</span><strong>{summaries[unit]["model_anomalies"]:,}</strong><small>ML review / {summaries[unit]["total_rows"]:,} rows</small></div>'
        for unit in units
    )
    document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VCM1/VCM2 Wall Loss ML 그래프 보고서</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--panel:#fff;--bg:#f4f7fb}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:"Malgun Gothic","Segoe UI",sans-serif}}main{{max-width:1180px;margin:auto;padding:32px}}h1{{margin:0 0 8px}}.note{{color:var(--muted);margin-bottom:22px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:18px}}.card,.chart{{background:var(--panel);border:1px solid #e2e8f0;border-radius:14px;box-shadow:0 4px 18px #0f172a0c}}.card{{padding:20px}}.card span,.card small{{display:block;color:var(--muted)}}.card strong{{display:block;font-size:34px;margin:5px 0}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(480px,1fr));gap:16px}}.chart{{padding:12px;overflow:auto}}svg{{width:100%;min-width:450px;height:auto}}.chart-title{{font-weight:700;font-size:16px;fill:var(--ink)}}.axis{{font-size:12px;fill:var(--muted)}}.value{{font-size:11px;font-weight:700;fill:var(--ink)}}.gridline{{stroke:#e2e8f0;stroke-width:1}}footer{{margin-top:20px;color:var(--muted);font-size:13px}}@media(max-width:600px){{main{{padding:16px}}.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>VCM1/VCM2 Wall Loss ML 그래프 보고서</h1>
<div class="note">IsolationForest · 라인별 검토비율 {contamination:.2%} · 결과는 결함 판정이 아닌 재검토 우선순위입니다.</div>
<section class="cards">{cards}</section>
<section class="grid"><div class="chart">{severity_chart}</div><div class="chart">{quality_chart}</div><div class="chart">{exchanger_chart}</div><div class="chart">{_scatter_chart("ML anomaly score vs Wall Loss", anomalies)}</div></section>
<footer>생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · 점에 마우스를 올리면 튜브 정보를 확인할 수 있습니다.</footer>
</main></body></html>"""
    graph_path.write_text(document, encoding="utf-8")


def write_reports(
    rows: list[dict[str, Any]],
    summaries: dict[str, dict[str, Any]],
    output_dir: Path,
    *,
    contamination: float,
    top: int = 30,
    prefix: str | None = None,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_prefix = prefix or f"hx_ml_wall_loss_anomalies_{stamp}"
    csv_path = output_dir / f"{report_prefix}.csv"
    markdown_path = output_dir / f"{report_prefix}.md"
    json_path = output_dir / f"{report_prefix}.json"
    graph_path = output_dir / f"{report_prefix}_graphs.html"
    anomalies = _report_rows(rows)

    with csv_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in anomalies:
            exported = {field: row.get(field) for field in CSV_FIELDS}
            exported["review_flags"] = "|".join(row["review_flags"])
            writer.writerow(exported)

    lines = [
        "# VCM1/VCM2 Wall Loss ML anomaly review",
        "",
        f"- Model: `{MODEL_NAME}` / `{MODEL_VERSION}`",
        f"- scikit-learn: `{sklearn.__version__}`",
        f"- Review ratio: `{contamination:.2%}` per production line",
        "- The result is a review priority, not a defect or maintenance decision.",
        "- 20/30/40% bands are analytical bands because exchanger criteria are not registered.",
        f"- [Open graph dashboard]({graph_path.name})",
        "",
        "## Summary",
        "",
        "| Line | Rows | ML anomalies | >=20% | >=30% | >=40% | Missing thickness | Formula >1pp | Temporal >=10pp |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for unit_code, summary in sorted(summaries.items()):
        lines.append(
            f"| {unit_code} | {summary['total_rows']:,} | "
            f"{summary['model_anomalies']:,} | {summary['wall_loss_ge_20']:,} | "
            f"{summary['wall_loss_ge_30']:,} | {summary['wall_loss_ge_40']:,} | "
            f"{summary['minimum_thickness_missing']:,} | "
            f"{summary['formula_residual_gt_1pp']:,} | "
            f"{summary['temporal_change_ge_10pp']:,} |"
        )

    lines.extend(
        [
            "",
            f"## Top {min(top, len(anomalies))} review targets",
            "",
            "| Line | Year | Exchanger | Tube | Scope | Wall Loss | ML score | Flags |",
            "|---|---:|---|---|---|---:|---:|---|",
        ]
    )
    global_top = sorted(
        anomalies, key=lambda row: row["ml_anomaly_score"], reverse=True
    )[:top]
    for row in global_top:
        flags = ", ".join(row["review_flags"]) or "ML_PATTERN_OUTLIER"
        lines.append(
            f"| {row['unit_code']} | {row['campaign_year']} | "
            f"{row['equipment_code']} | {row['tube_no'] or '-'} | "
            f"{row['scope_code']} | {row['wall_loss_percent']:.2f}% | "
            f"{row['ml_anomaly_score']:.5f} | {flags} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_graph_report(
        rows,
        summaries,
        graph_path,
        contamination=contamination,
    )

    payload = {
        "status": "COMPLETED",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "scikit_learn_version": sklearn.__version__,
        "contamination": contamination,
        "summaries": summaries,
        "files": {
            "csv": str(csv_path.resolve()),
            "markdown": str(markdown_path.resolve()),
            "json": str(json_path.resolve()),
            "graphs": str(graph_path.resolve()),
        },
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload["files"]


def run_analysis(
    database_path: Path,
    output_dir: Path,
    *,
    units: Iterable[str] = DEFAULT_UNITS,
    contamination: float = ML_CONTAMINATION,
    random_state: int = ML_RANDOM_STATE,
    estimators: int = ML_ESTIMATORS,
    top: int = ML_TOP_RESULTS,
    prefix: str | None = None,
) -> dict[str, Any]:
    rows = engineer_features(load_wall_loss_rows(database_path, units))
    rows, summaries = fit_isolation_forests(
        rows,
        contamination=contamination,
        random_state=random_state,
        estimators=estimators,
    )
    files = write_reports(
        rows,
        summaries,
        output_dir,
        contamination=contamination,
        top=top,
        prefix=prefix,
    )
    return {
        "status": "COMPLETED",
        "database": str(database_path.resolve()),
        "database_mode": "read-only",
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "scikit_learn_version": sklearn.__version__,
        "units": list(units),
        "contamination": contamination,
        "summaries": summaries,
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VCM1/VCM2 Wall Loss Isolation Forest anomaly review"
    )
    parser.add_argument("--database", type=Path, default=DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument(
        "--units", nargs="+", choices=SUPPORTED_UNITS, default=list(DEFAULT_UNITS)
    )
    parser.add_argument("--contamination", type=float, default=ML_CONTAMINATION)
    parser.add_argument("--random-state", type=int, default=ML_RANDOM_STATE)
    parser.add_argument("--estimators", type=int, default=ML_ESTIMATORS)
    parser.add_argument("--top", type=int, default=ML_TOP_RESULTS)
    parser.add_argument("--prefix")
    args = parser.parse_args()
    result = run_analysis(
        args.database,
        args.output_dir,
        units=args.units,
        contamination=args.contamination,
        random_state=args.random_state,
        estimators=args.estimators,
        top=args.top,
        prefix=args.prefix,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
