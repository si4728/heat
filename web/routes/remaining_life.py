from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/remaining-life/tubes")
    def remaining_life_tubes():
        default_year = services.remaining_life_as_of_date().year
        try:
            target_year = int(request.args.get("target_year") or default_year)
            data = services.remaining_life_tube_search(
                target_year=target_year,
                unit_code=request.args.get("unit_code", ""),
                search=request.args.get("search", ""),
            )
            return render_template("remaining_life_tubes.html", **data)
        except (ValueError, TypeError) as exc:
            flash(str(exc), "error")
            return redirect(url_for("remaining_life_tubes", target_year=default_year))

    @app.get("/exchangers/<int:exchanger_id>/remaining-life-simulation")
    def remaining_life_simulation(exchanger_id: int):
        simulation_requested = request.args.get("simulate") == "1"
        calculation_method = str(request.args.get("calculation_method") or "LEGACY").upper()
        if calculation_method not in {"LEGACY", "API510"}:
            calculation_method = "LEGACY"
        simulation_limit = None
        corrosion_rate_percent = 100.0
        plugging_wall_loss_percent = services.REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT
        forecast_end_year = services.REMAINING_LIFE_FORECAST_END_YEAR
        api510_result = None
        api510_values = {}
        try:
            if simulation_requested and calculation_method == "LEGACY":
                simulation_limit = float(request.args.get("simulation_limit") or 20)
                corrosion_rate_percent = float(
                    request.args.get("corrosion_rate_percent") or 100
                )
                plugging_wall_loss_percent = float(
                    request.args.get("plugging_wall_loss_percent")
                    or services.REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT
                )
                forecast_end_year = int(
                    request.args.get("forecast_end_year")
                    or services.REMAINING_LIFE_FORECAST_END_YEAR
                )
            data = services.exchanger_detail(
                exchanger_id,
                simulation_allowable_plugging_percent=simulation_limit,
                simulation_corrosion_rate_multiplier=corrosion_rate_percent / 100.0,
                simulation_plugging_wall_loss_percent=(
                    plugging_wall_loss_percent if simulation_requested else None
                ),
                simulation_forecast_end_year=(
                    forecast_end_year if simulation_requested else None
                ),
            )
            if simulation_requested and calculation_method == "API510":
                if request.args.get("api_confirm_required_thickness") != "1":
                    raise ValueError("API 510 필요두께의 설계근거 확인이 필요합니다.")
                defaults = data["api510_defaults"] if data else {}
                api510_values = {
                    "actual_thickness_mm": request.args.get("api_actual_thickness_mm") or defaults.get("actual_thickness_mm"),
                    "required_thickness_mm": request.args.get("api_required_thickness_mm") or defaults.get("required_thickness_mm"),
                    "corrosion_rate_mm_per_year": request.args.get("api_corrosion_rate_mm_per_year") or defaults.get("corrosion_rate_mm_per_year"),
                    "last_inspection_date": request.args.get("api_last_inspection_date") or defaults.get("last_inspection_date"),
                    "inspection_type": request.args.get("api_inspection_type") or "INTERNAL_ON_STREAM",
                }
                if any(value in (None, "") for value in api510_values.values()):
                    raise ValueError("API 510 계산에 필요한 실제두께, 필요두께, 부식속도 및 최근 검사일을 입력해 주세요.")
                api510_result = services.calculate_api510_inspection_interval(**api510_values)
                api510_values["last_inspection_date"] = api510_result["last_inspection_date"]
        except (ValueError, TypeError) as exc:
            flash(f"잔여수명 시뮬레이션 입력 오류: {exc}", "error")
            data = services.exchanger_detail(exchanger_id)
            api510_result = None
        if not data:
            return render_template("404.html"), 404
        return render_template(
            "remaining_life_simulation.html",
            simulation_requested=simulation_requested,
            simulation_limit=simulation_limit,
            corrosion_rate_percent=corrosion_rate_percent,
            plugging_wall_loss_percent=plugging_wall_loss_percent,
            forecast_end_year=forecast_end_year,
            calculation_method=calculation_method,
            api510_result=api510_result,
            api510_values=api510_values,
            **data,
        )
