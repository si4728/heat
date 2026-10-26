from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/exchangers/<int:exchanger_id>/api510")
    def api510_management(exchanger_id: int):
        data = services.api510_management_data(exchanger_id)
        if not data:
            return render_template("404.html"), 404
        return render_template("api510_management.html", **data)

    @app.post("/exchangers/<int:exchanger_id>/api510/components")
    def pressure_component_save(exchanger_id: int):
        try:
            services.save_pressure_boundary_component(exchanger_id, request.form.to_dict())
            flash("압력경계 부품 Master를 저장했습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"압력경계 부품 저장 실패: {exc}", "error")
        return redirect(url_for("api510_management", exchanger_id=exchanger_id))

    @app.post("/pressure-components/<int:component_id>/api510-calculations")
    def api510_calculation_create(component_id: int):
        exchanger_id = request.form.get("exchanger_id", type=int)
        try:
            profile = g.get("current_user") or {}
            services.create_api510_calculation(
                component_id,
                request.form.to_dict(),
                actor=profile.get("username"),
            )
            flash("API 510 계산서를 DRAFT 상태로 생성했습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"API 510 계산 실패: {exc}", "error")
        return redirect(url_for("api510_management", exchanger_id=exchanger_id))

    @app.post("/api510-calculations/<int:calculation_id>/status")
    def api510_calculation_transition(calculation_id: int):
        exchanger_id = request.form.get("exchanger_id", type=int)
        requested = str(request.form.get("status") or "").upper()
        profile = g.get("current_user") or {}
        if requested in {"APPROVED", "REJECTED"} and not (
            app.config.get("AUTH_DISABLED") or profile.get("is_admin")
        ):
            abort(403)
        try:
            if not services.transition_api510_calculation(
                calculation_id,
                requested,
                profile.get("username") or "test-admin",
                request.form.get("review_note"),
            ):
                abort(404)
            flash("API 510 계산서 상태를 변경했습니다.", "success")
        except ValueError as exc:
            flash(f"계산서 상태 변경 실패: {exc}", "error")
        return redirect(url_for("api510_management", exchanger_id=exchanger_id))
