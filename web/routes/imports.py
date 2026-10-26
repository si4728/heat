from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2 import pdf_ocr_review
from iris2.asset_paths import local_asset_path
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/quality-issues")
    def quality_issues():
        severity = request.args.get("severity", "")
        status = request.args.get("status", "OPEN")
        return render_template("quality_issues.html", rows=services.list_issues(severity, status),
                               severity=severity, status=status)

    @app.post("/quality-issues/<int:issue_id>/resolve")
    def quality_issue_resolve(issue_id: int):
        profile = g.get("current_user") or {}
        try:
            if not services.resolve_quality_issue(
                issue_id,
                profile.get("username") or "administrator",
                request.form.get("resolution_note", ""),
            ):
                abort(404)
            flash("품질 이슈를 근거와 함께 종결했습니다.", "success")
        except ValueError as exc:
            flash(f"품질 이슈 종결 실패: {exc}", "error")
        return redirect(url_for("quality_issues", status=request.form.get("return_status", "OPEN")))

    @app.get("/pdf-reports/<int:year>/<unit_code>")
    def pdf_report_view(year: int, unit_code: str):
        report_path = services.find_pdf_report(year, unit_code)
        if not report_path:
            abort(404)
        return send_file(
            report_path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=report_path.name,
            conditional=True,
        )

    @app.route("/imports", methods=["GET", "POST"])
    def imports():
        outcome = None
        plants = services.plant_choices()
        production_lines = services.production_line_choices()
        selected_plant_code = request.form.get("plant_code", "")
        selected_unit_code = request.form.get("unit_code", "")
        if request.method == "POST":
            uploaded = request.files.get("json_file")
            if not uploaded or not uploaded.filename:
                flash("JSON 파일을 선택해 주세요.", "error")
            elif not uploaded.filename.lower().endswith(".json"):
                flash(".json 파일만 업로드할 수 있습니다.", "error")
            else:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                filename = secure_filename(uploaded.filename) or f"iris_{stamp}.json"
                upload_run_dir = UPLOAD_DIR / stamp
                upload_run_dir.mkdir(parents=True, exist_ok=True)
                destination = upload_run_dir / filename
                uploaded.save(destination)
                try:
                    outcome = services.load_json(
                        destination,
                        dry_run=request.form.get("dry_run") == "1",
                        plant_code=selected_plant_code,
                        unit_code=selected_unit_code,
                    )
                    flash(f"처리 완료: {outcome['status']}", "success")
                except Exception as exc:
                    outcome = {
                        "status": "FAILED",
                        "source_file": uploaded.filename,
                        "message": str(exc),
                        "report_count": 0,
                        "loaded_report_count": 0,
                        "tube_result_count": 0,
                        "error_count": 1,
                        "warning_count": 0,
                    }
                    flash(f"처리 실패: {exc}", "error")
        return render_template("imports.html", outcome=outcome, plants=plants,
                               production_lines=production_lines,
                               selected_plant_code=selected_plant_code,
                               selected_unit_code=selected_unit_code)

    @app.get("/imports/pdf-review")
    def pdf_ocr_review_dashboard():
        return render_template("pdf_ocr_review.html", **pdf_ocr_review.dashboard_data())

    @app.get("/imports/pdf-review/<int:source_document_id>/source")
    def pdf_ocr_source(source_document_id: int):
        row = pdf_ocr_review.document_record(source_document_id)
        if not row:
            abort(404)
        source_path = local_asset_path(row["pdf_path"])
        if not source_path.is_file():
            abort(404)
        return send_file(source_path, mimetype="application/pdf", as_attachment=False,
                         download_name=source_path.name, conditional=True)

    @app.post("/imports/pdf-review/<int:source_document_id>/approve")
    def pdf_ocr_approve(source_document_id: int):
        profile = g.get("current_user") or {}
        if not services.user_can(profile, "PDF_OCR_REVIEW", edit=True):
            abort(403)
        actor = profile.get("username") or "administrator"
        try:
            pdf_ocr_review.approve_document(
                source_document_id, actor, request.form.get("note", "")
            )
            flash("PDF/OCR 검토 문서를 승인했습니다.", "success")
        except (LookupError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("pdf_ocr_review_dashboard"))
