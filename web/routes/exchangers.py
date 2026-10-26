from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR
from iris2.llm_integration.report_workflow import latest_validated_summary
from iris2.application.organization_service import organization_catalog, save_organization_code


def register_routes(app) -> None:
    @app.get("/master-data/organization-codes")
    def organization_codes():
        data = organization_catalog()
        selected = request.args.get("edit", type=int)
        data["editing"] = next((e["node"] for e in data["entries"] if e["node"].organization_code_id == selected), None)
        return render_template("organization_codes.html", **data)

    @app.post("/master-data/organization-codes")
    def organization_code_create():
        try:
            save_organization_code(request.form.to_dict())
            flash("조직 코드가 등록되었습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("organization_codes"))

    @app.post("/master-data/organization-codes/<int:code_id>")
    def organization_code_update(code_id):
        try:
            save_organization_code(request.form.to_dict(), code_id)
            flash("Label(설명)이 저장되었습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("organization_codes"))

    @app.get("/exchangers")
    def exchangers():
        filters = {"search": request.args.get("search", ""),
                   "plant_code": "",
                   "unit_code": request.args.get("unit", ""),
                   "status": request.args.get("status", ""),
                   "criticality": "",
                   "sort_by": request.args.get("sort_by", "plant"),
                   "sort_dir": request.args.get("sort_dir", "asc"),
                   "team_code": request.args.get("team", ""),
                   "process_code": request.args.get("process", "")}
        return render_template("exchangers.html", filters=filters,
                               **services.list_exchangers(**filters))

    @app.get("/exchangers/wall-loss-ranking")
    def exchanger_wall_loss_ranking():
        return render_template(
            "exchanger_wall_loss_ranking.html",
            **services.exchanger_wall_loss_ranking(
                search=request.args.get("search", ""),
                plant_code=request.args.get("plant", ""),
                unit_code=request.args.get("unit", ""),
            ),
        )

    @app.get("/analysis")
    def precision_analysis():
        return render_template(
            "precision_analysis.html",
            **services.precision_analysis_data(
                request.args.get("exchanger_id", type=int),
                unit_code=request.args.get("unit", ""),
                search=request.args.get("search", ""),
                corrosion_rate_multiplier=1.0,
            ),
        )

    @app.get("/master-data/plants-lines")
    def plant_line_master():
        return render_template(
            "plant_line_master.html",
            **services.plant_line_master_data(
                request.args.get("plant_id", type=int),
                request.args.get("unit_id", type=int),
            ),
        )

    @app.route("/settings/wall-loss-colors", methods=["GET", "POST"])
    def wall_loss_colors():
        if request.method == "POST":
            try:
                updated = services.save_wall_loss_colors(request.form.to_dict())
                flash(f"Wall Loss 색상표를 저장했습니다. 변경 {updated}건", "success")
                return redirect(url_for("wall_loss_colors"))
            except ValueError as exc:
                flash(f"색상표 저장 실패: {exc}", "error")
        return render_template("wall_loss_colors.html", **services.wall_loss_color_settings_data())

    @app.post("/settings/wall-loss-colors/reset")
    def wall_loss_colors_reset():
        updated = services.reset_wall_loss_colors()
        flash(f"기본 색상으로 초기화했습니다. 복원 {updated}건", "success")
        return redirect(url_for("wall_loss_colors"))

    @app.route("/settings/system-theme", methods=["GET", "POST"])
    def system_theme_settings():
        if request.method == "POST":
            try:
                updated = services.save_system_theme_settings(request.form.to_dict())
                flash(f"화면 테마를 저장했습니다. 변경 {updated}건", "success")
                return redirect(url_for("system_theme_settings"))
            except ValueError as exc:
                flash(f"화면 테마 저장 실패: {exc}", "error")
        return render_template("system_theme_settings.html", **services.system_theme_settings_data())

    @app.post("/settings/system-theme/reset")
    def system_theme_settings_reset():
        updated = services.reset_system_theme_settings()
        flash(f"화면 테마 3종을 기본값으로 복원했습니다. 변경 {updated}건", "success")
        return redirect(url_for("system_theme_settings"))

    @app.post("/master-data/plants")
    def plant_create():
        try:
            services.save_plant(request.form.to_dict())
            flash("공장 코드가 등록되었습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"공장 등록 실패: {exc}", "error")
        return redirect(url_for("plant_line_master"))

    @app.post("/master-data/plants/<int:plant_id>")
    def plant_update(plant_id: int):
        try:
            services.save_plant(request.form.to_dict(), plant_id)
            flash("공장 정보가 수정되었습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"공장 수정 실패: {exc}", "error")
        return redirect(url_for("plant_line_master"))

    @app.post("/master-data/production-lines")
    def production_line_create():
        try:
            services.save_production_line(request.form.to_dict())
            flash("생산라인 코드가 등록되었습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"생산라인 등록 실패: {exc}", "error")
        return redirect(url_for("plant_line_master"))

    @app.post("/master-data/production-lines/<int:unit_id>")
    def production_line_update(unit_id: int):
        try:
            services.save_production_line(request.form.to_dict(), unit_id)
            flash("생산라인 정보가 수정되었습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"생산라인 수정 실패: {exc}", "error")
        return redirect(url_for("plant_line_master"))

    @app.route("/exchangers/new", methods=["GET", "POST"])
    def exchanger_new():
        form_data = services.exchanger_form_data()
        if request.method == "POST":
            try:
                result = services.save_exchanger(
                    request.form.to_dict(), enforce_master_mandatory=True
                )
                flash("열교환기 기본정보와 기술 사양이 등록되었습니다.", "success")
                return redirect(url_for("exchanger_detail", exchanger_id=result["heat_exchanger_id"]))
            except (ValueError, TypeError) as exc:
                flash(f"등록 실패: {exc}", "error")
        return render_template("exchanger_form.html", **form_data)

    @app.route("/exchangers/<int:exchanger_id>/edit", methods=["GET", "POST"])
    def exchanger_edit(exchanger_id: int):
        form_data = services.exchanger_form_data(exchanger_id)
        if not form_data:
            return render_template("404.html"), 404
        if request.method == "POST":
            try:
                result = services.save_exchanger(
                    request.form.to_dict(), exchanger_id,
                    enforce_master_mandatory=True,
                )
                revision_message = " 새 사양 revision이 생성되었습니다." if result["specification_revision_created"] else ""
                flash("열교환기 정보가 수정되었습니다." + revision_message, "success")
                return redirect(url_for("exchanger_detail", exchanger_id=exchanger_id))
            except (ValueError, TypeError) as exc:
                flash(f"수정 실패: {exc}", "error")
        return render_template("exchanger_form.html", **form_data)

    @app.post("/exchangers/<int:exchanger_id>/media-material")
    def exchanger_media_material_update(exchanger_id: int):
        try:
            result = services.save_exchanger_media_material(
                exchanger_id, request.form.to_dict()
            )
            if result["changed"]:
                flash(
                    f"유체·재질 정보가 저장되었습니다. 사양 Rev.{result['revision_no']}이 생성되었습니다.",
                    "success",
                )
            else:
                flash("유체·재질 정보에 변경사항이 없습니다.", "success")
        except (ValueError, TypeError) as exc:
            flash(f"유체·재질 저장 실패: {exc}", "error")
        return redirect(
            url_for("exchanger_detail", exchanger_id=exchanger_id)
            + "#fluid-material-management"
        )

    @app.get("/exchangers/<int:exchanger_id>")
    def exchanger_detail(exchanger_id: int):
        simulation_requested = request.args.get("simulate") == "1"
        simulation_limit = None
        simulation_rate_percent = 100.0
        try:
            if simulation_requested:
                simulation_limit = float(request.args.get("simulation_limit") or 20)
                simulation_rate_percent = float(
                    request.args.get("corrosion_rate_percent") or 100
                )
            data = services.exchanger_detail(
                exchanger_id,
                simulation_allowable_plugging_percent=simulation_limit,
                simulation_corrosion_rate_multiplier=simulation_rate_percent / 100.0,
            )
        except (ValueError, TypeError) as exc:
            flash(f"잔여수명 시뮬레이션 입력 오류: {exc}", "error")
            data = services.exchanger_detail(exchanger_id)
            simulation_requested = False
        if not data:
            return render_template("404.html"), 404
        return render_template(
            "exchanger_detail.html",
            plugging_unavailable_guide=services.plugging_unavailable_guide(),
            simulation_requested=simulation_requested,
            simulation_limit=simulation_limit,
            simulation_rate_percent=simulation_rate_percent,
            **data,
        )

    @app.get("/q/exchangers/<int:exchanger_id>")
    def qr_exchanger_lookup(exchanger_id: int):
        data = services.exchanger_detail(exchanger_id)
        if not data:
            return render_template("404.html"), 404
        inspection_pdf_links = {}
        for inspection, _scope in data["inspections"]:
            pdf = services.find_inspection_pdf(inspection.iris_inspection_id)
            if pdf:
                inspection_pdf_links[inspection.iris_inspection_id] = {
                    "page": pdf["page"],
                }
        return render_template(
            "qr_exchanger_lookup.html",
            inspection_pdf_links=inspection_pdf_links,
            inspection_priority=services.inspection_priority_for_exchanger(exchanger_id),
            ai_summary=latest_validated_summary(exchanger_id),
            **data,
        )
