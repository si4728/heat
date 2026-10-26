from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, DB_PATH, ML_ARTIFACT_ROOT, ML_REVIEW_DB_PATH, UPLOAD_DIR
from iris2.ml.review import load_latest_ml_review, load_latest_pattern_review, load_latest_spatial_review
from iris2.ml.review_feedback import save_review_feedback


def register_routes(app) -> None:
    @app.get("/inspections/<int:inspection_id>/pdf")
    def inspection_pdf_view(inspection_id: int):
        pdf = services.find_inspection_pdf(inspection_id)
        if not pdf:
            abort(404)
        return send_file(
            pdf["path"],
            mimetype="application/pdf",
            as_attachment=False,
            download_name=pdf["path"].name,
            conditional=True,
        )

    @app.get("/inspections/<int:inspection_id>")
    def inspection_detail(inspection_id: int):
        data = services.inspection_detail(inspection_id)
        if not data:
            return render_template("404.html"), 404
        return render_template("inspection_detail.html", **data)

    @app.post("/inspections/<int:inspection_id>/execution")
    def inspection_execution_update(inspection_id: int):
        try:
            if not services.save_inspection_execution(
                inspection_id, request.form.to_dict()
            ):
                abort(404)
            flash("검사 수행업체·장비·소프트웨어 정보를 저장했습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"검사 수행정보 저장 실패: {exc}", "error")
        return redirect(url_for("inspection_detail", inspection_id=inspection_id))

    @app.get("/inspections")
    def inspections():
        return render_template("inspections.html", **services.inspections_data(
            request.args.get("search", ""), request.args.get("grade", "")))

    @app.get("/inspections/tubes")
    def tube_inspection_history():
        return render_template(
            "tube_inspection_history.html",
            **services.tube_inspection_history_data(
                exchanger_id=request.args.get("exchanger_id"),
                year=request.args.get("year"),
                tube_no=request.args.get("tube_no", ""),
                page=request.args.get("page", 1),
                sort_by=request.args.get("sort_by", "exchanger"),
                sort_dir=request.args.get("sort_dir", "asc"),
            ),
        )

    @app.route("/inspections/ml-review", methods=["GET", "POST"])
    def ml_review_targets():
        selected_unit = request.values.get("unit_code", "")
        selected_equipment = request.values.get("equipment_code", "")
        hard_only = request.values.get("hard_only", "") == "1"
        if request.method == "POST":
            review = load_latest_ml_review(
                DB_PATH,
                ML_ARTIFACT_ROOT,
                feedback_database_path=ML_REVIEW_DB_PATH,
            )
            try:
                result_id = int(request.form.get("iris_tube_result_id", ""))
                target = next(
                    (row for row in review.get("rows", []) if int(row["iris_tube_result_id"]) == result_id),
                    None,
                )
                if not review.get("enabled") or not target:
                    raise ValueError("현재 분석 실행의 검토대상을 찾을 수 없습니다.")
                submitted_run = request.form.get("run_id", "")
                if submitted_run != review.get("run_id"):
                    raise ValueError("분석 실행이 변경되었습니다. 화면을 새로고침해 주세요.")
                current_user = g.get("current_user") or {}
                save_review_feedback(
                    ML_REVIEW_DB_PATH,
                    run_id=review["run_id"],
                    model_version=review.get("model_version") or "UNKNOWN",
                    iris_tube_result_id=result_id,
                    iris_inspection_id=int(target["iris_inspection_id"]),
                    tube_id=int(target["tube_id"]),
                    label=request.form.get("label", ""),
                    note=request.form.get("note", ""),
                    reviewer_user_id=current_user.get("user_id"),
                    reviewer_name=current_user.get("username") or "SYSTEM_TEST",
                )
                flash("전문가 검토 라벨을 저장했습니다.", "success")
            except (TypeError, ValueError) as exc:
                flash(str(exc), "error")
            query = {}
            if selected_unit:
                query["unit_code"] = selected_unit
            if selected_equipment:
                query["equipment_code"] = selected_equipment
            if hard_only:
                query["hard_only"] = "1"
            return redirect(url_for("ml_review_targets", **query))
        return render_template(
            "ml_review_targets.html",
            **load_latest_ml_review(
                DB_PATH,
                ML_ARTIFACT_ROOT,
                unit_code=selected_unit,
                equipment_code=selected_equipment,
                hard_only=hard_only,
                feedback_database_path=ML_REVIEW_DB_PATH,
            ),
        )

    @app.get("/inspections/ml-hotspots")
    def ml_spatial_hotspots():
        return render_template(
            "ml_spatial_hotspots.html",
            **load_latest_spatial_review(
                DB_PATH,
                ML_ARTIFACT_ROOT,
                unit_code=request.args.get("unit_code", ""),
                equipment_code=request.args.get("equipment_code", ""),
                inspection_year=request.args.get("inspection_year", ""),
                feedback_database_path=ML_REVIEW_DB_PATH,
            ),
        )

    @app.get("/inspections/ml-patterns")
    def ml_degradation_patterns():
        return render_template(
            "ml_degradation_patterns.html",
            **load_latest_pattern_review(
                DB_PATH,
                ML_ARTIFACT_ROOT,
                pattern_code=request.args.get("pattern_code", ""),
                unit_code=request.args.get("unit_code", ""),
                equipment_code=request.args.get("equipment_code", ""),
                page=request.args.get("page", 1),
            ),
        )

    @app.route("/inspection-plans", methods=["GET", "POST"])
    def inspection_plans():
        if request.method == "POST":
            try:
                current_user = g.get("current_user") or {}
                payload = request.form.to_dict()
                payload["tube_ids"] = request.form.getlist("tube_ids")
                services.save_inspection_plan(payload, current_user.get("user_id"))
                flash("검사계획이 등록되었습니다.", "success")
                return redirect(url_for("inspection_plans"))
            except (ValueError, TypeError) as exc:
                flash(f"검사계획 등록 실패: {exc}", "error")
        return render_template("inspection_plans.html",
                               **services.inspection_plans_data(
                                   request.args.get("status", ""),
                                   request.args.get("heat_exchanger_id", ""),
                                   request.args.get("priority_source", ""),
                               ))

    @app.post("/inspection-plans/<int:plan_id>/status")
    def inspection_plan_status(plan_id: int):
        try:
            current_user = g.get("current_user") or {}
            if not services.update_inspection_plan_status(
                plan_id,
                request.form.get("status", ""),
                actor_user_id=current_user.get("user_id"),
                actor_is_admin=bool(current_user.get("is_admin") or app.config.get("AUTH_DISABLED")),
                reason=request.form.get("reason", ""),
            ):
                abort(404)
            flash("검사계획 상태가 변경되었습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("inspection_plans"))

    @app.post("/inspection-plans/<int:plan_id>/tubes/<int:target_id>/status")
    def inspection_plan_tube_status(plan_id: int, target_id: int):
        try:
            current_user = g.get("current_user") or {}
            if not services.update_inspection_plan_tube_target(
                plan_id,
                target_id,
                request.form.get("status", ""),
                actor_user_id=current_user.get("user_id"),
                reason=request.form.get("reason", ""),
            ):
                abort(404)
            flash("Tube 검사 상태가 변경되었습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("inspection_plans"))

    @app.get("/tubes/<int:tube_id>")
    def tube_detail(tube_id: int):
        data = services.tube_detail(tube_id)
        if not data:
            return render_template("404.html"), 404
        return render_template("tube_detail.html", **data)

    @app.post("/tubes/<int:tube_id>/status")
    def tube_status_update(tube_id: int):
        try:
            result = services.update_tube_status(
                tube_id, request.form.get("current_status", ""), request.form.get("reason", "")
            )
        except ValueError as exc:
            flash(f"상태 변경 실패: {exc}", "error")
            return redirect(url_for("tube_detail", tube_id=tube_id))
        if not result:
            return render_template("404.html"), 404
        if result["changed"]:
            flash("튜브 운전 상태가 변경되고 이력에 저장되었습니다.", "success")
        else:
            flash("현재 상태와 동일하여 변경된 내용이 없습니다.", "success")
        return redirect(url_for("tube_detail", tube_id=tube_id))

    @app.get("/exchangers/<int:exchanger_id>/tubes/manage")
    def tube_management(exchanger_id: int):
        data = services.tube_management_data(exchanger_id, request.args.get("search", ""),
                                             request.args.get("status", ""))
        if not data: abort(404)
        return render_template("tube_management.html", **data)

    @app.post("/exchangers/<int:exchanger_id>/tubes/batch-status")
    def tube_batch_status(exchanger_id: int):
        try:
            ids = [int(value) for value in request.form.getlist("tube_ids")]
            changed = services.batch_update_tube_status(exchanger_id, ids,
                request.form.get("status", ""), request.form.get("reason", ""))
            flash(f"튜브 {changed}개의 상태를 변경했습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"일괄 변경 실패: {exc}", "error")
        return redirect(url_for("tube_management", exchanger_id=exchanger_id))

    @app.post("/tubes/<int:tube_id>/position")
    def tube_position_update(tube_id: int):
        try:
            result = services.update_tube_position(tube_id, request.form.to_dict())
            if not result: abort(404)
            flash("튜브 좌표와 잠금 상태를 저장했습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"위치 변경 실패: {exc}", "error")
        return redirect(request.referrer or url_for("tube_detail", tube_id=tube_id))

    @app.get("/exchangers/<int:exchanger_id>/report")
    def exchanger_report(exchanger_id: int):
        data = services.exchanger_report_data(exchanger_id)
        if not data: abort(404)
        return render_template("exchanger_report.html", **data)
