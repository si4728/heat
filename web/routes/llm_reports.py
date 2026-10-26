from __future__ import annotations

from flask import abort, flash, g, redirect, render_template, request, url_for

from iris2.llm_integration.report_workflow import approve_draft, list_drafts


def register_routes(app) -> None:
    @app.get("/reports/ai-review")
    def ai_report_review():
        return render_template("ai_report_review.html", **list_drafts())

    @app.post("/reports/ai-review/<report_id>/approve")
    def ai_report_approve(report_id: str):
        profile = g.get("current_user") or {}
        if not app.config.get("AUTH_DISABLED") and not profile.get("is_admin"):
            abort(403)
        try:
            approve_draft(report_id, profile.get("username") or "administrator", request.form.get("note", ""))
            flash("근거 검증 보고서를 승인했습니다.", "success")
        except (LookupError, ValueError) as exc:
            flash(str(exc), "error")
        return redirect(url_for("ai_report_review"))
