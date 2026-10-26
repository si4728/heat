from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/maintenance")
    def maintenance():
        return render_template("maintenance.html", **services.maintenance_data())

    @app.route("/maintenance/work-orders/new", methods=["GET", "POST"])
    def work_order_new():
        if request.method == "POST":
            try:
                order_id = services.save_work_order(request.form.to_dict())
                flash("작업지시가 등록되었습니다.", "success")
                return redirect(url_for("work_order_detail", order_id=order_id))
            except (ValueError, TypeError) as exc:
                flash(f"작업지시 등록 실패: {exc}", "error")
        return render_template("work_order_form.html", **services.maintenance_data())

    @app.get("/maintenance/work-orders/<int:order_id>")
    def work_order_detail(order_id: int):
        data = services.work_order_detail_data(order_id)
        if not data: abort(404)
        return render_template("work_order_detail.html", **data)

    @app.post("/maintenance/work-orders/<int:order_id>/status")
    def work_order_status(order_id: int):
        try:
            if not services.update_work_order(order_id, request.form.to_dict()): abort(404)
            flash("작업지시 상태가 변경되었습니다.", "success")
        except ValueError as exc: flash(str(exc), "error")
        return redirect(url_for("work_order_detail", order_id=order_id))

    @app.post("/maintenance/work-orders/<int:order_id>/records")
    def maintenance_record_create(order_id: int):
        try:
            services.add_maintenance_record(order_id, request.form.to_dict())
            flash("정비·교체 이력을 저장했습니다.", "success")
        except (ValueError, TypeError) as exc: flash(str(exc), "error")
        return redirect(url_for("work_order_detail", order_id=order_id))
