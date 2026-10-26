from __future__ import annotations

import secrets
import time
from datetime import datetime

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from iris2 import services
from iris2.hx_configuration import DB_PATH, ENDPOINT_PERMISSIONS
from iris2.application.organization_service import organization_catalog


def register_security(app) -> None:
    @app.template_filter("comma")
    def comma_number(value):
        return f"{int(value or 0):,}"

    @app.template_filter("plant_display")
    def plant_display(value):
        return organization_label(value, "PLANT")

    def catalog():
        if "organization_catalog" not in g:
            g.organization_catalog = organization_catalog()
        return g.organization_catalog

    @app.template_filter("organization_label")
    def organization_label(value, kind, plant_code="", team_code=""):
        code = str(value or "").strip()
        root = code if kind == "PLANT" else str(plant_code or "")
        return catalog()["labels"].get((kind, root, team_code if kind == "PROCESS" else "", code), code or "-")

    endpoint_permissions = dict(ENDPOINT_PERMISSIONS)
    pdf_review_endpoints = {"pdf_ocr_review_dashboard", "pdf_ocr_source", "pdf_ocr_approve"}
    for endpoint in pdf_review_endpoints:
        endpoint_permissions[endpoint] = "PDF_OCR_REVIEW"
    for endpoint in ("organization_codes", "organization_code_create", "organization_code_update"):
        endpoint_permissions.setdefault(endpoint, "PLANT_LINES")
    edit_page_endpoints = {"exchanger_new", "exchanger_edit", "tube_management",
                           "work_order_new", "pressure_component_save",
                           "api510_calculation_create", "api510_calculation_transition"}
    public_endpoints = {"login", "setup_admin", "static",
                        "hanwha_solution_logo", "hanwha_solution_logo_legacy",
                        "api_health", "api_exchanger_create", "api_exchanger_update"}
    authenticated_only_endpoints = {"logout", "user_preferences"}
    csrf_exempt_endpoints = {"api_health", "api_exchanger_create", "api_exchanger_update"}

    def start_authenticated_session(user_id: int) -> None:
        session.clear()
        session.permanent = True
        session["user_id"] = user_id
        session["last_activity_at"] = time.time()

    @app.before_request
    def enforce_authentication_and_permissions():
        g.current_user = None
        if (
            app.config.get("CSRF_ENABLED")
            and request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
            and request.endpoint not in csrf_exempt_endpoints
        ):
            expected = session.get("csrf_token")
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not expected or not supplied or not secrets.compare_digest(expected, supplied):
                abort(400, description="Invalid or missing CSRF token")
        if app.config.get("AUTH_DISABLED"):
            if request.endpoint in pdf_review_endpoints:
                abort(403)
            return None
        endpoint = request.endpoint
        if endpoint is None or endpoint in public_endpoints:
            return None
        if services.user_count() == 0:
            return redirect(url_for("setup_admin"))
        if session.get("user_id"):
            now = time.time()
            last_activity = session.get("last_activity_at")
            try:
                idle_seconds = now - float(last_activity) if last_activity is not None else 0
            except (TypeError, ValueError):
                idle_seconds = app.config["SESSION_IDLE_TIMEOUT_SECONDS"]
            if idle_seconds >= app.config["SESSION_IDLE_TIMEOUT_SECONDS"]:
                session.clear()
                flash("30분 동안 사용이 없어 자동 로그아웃되었습니다.", "warning")
                next_path = request.full_path.rstrip("?")
                return redirect(url_for("login", next=next_path))
            session["last_activity_at"] = now
        profile = services.user_access_profile(session.get("user_id")) if session.get("user_id") else None
        if not profile:
            session.clear()
            next_path = request.full_path.rstrip("?")
            return redirect(url_for("login", next=next_path))
        g.current_user = profile
        if endpoint in {"users_admin", "database_monitor", "backup_manager"}:
            if not profile["is_admin"]:
                abort(403)
            return None
        if endpoint in authenticated_only_endpoints:
            return None
        screen_key = endpoint_permissions.get(endpoint)
        if not screen_key:
            # Fail closed when a newly added endpoint has no explicit access
            # classification.  Authentication alone is not authorization.
            abort(403)
        edit_required = request.method not in {"GET", "HEAD", "OPTIONS"} or endpoint in edit_page_endpoints
        if not services.user_can(profile, screen_key, edit=edit_required):
            abort(403)
        return None

    @app.context_processor
    def globals_for_templates():
        def can_screen(screen_key: str, action: str = "view") -> bool:
            if screen_key == "PDF_OCR_REVIEW":
                return services.user_can(g.get("current_user"), screen_key, edit=action == "edit")
            if app.config.get("AUTH_DISABLED"):
                return True
            return services.user_can(g.get("current_user"), screen_key, edit=action == "edit")
        csrf_token = session.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token
        return {"database_path": "MariaDB / iris2", "now": datetime.now(),
                "csrf_token": csrf_token,
                "current_user": g.get("current_user"), "can_screen": can_screen,
                "active_theme": services.active_theme_data(),
                "organization_choices": catalog()["entries"]}

    @app.route("/setup-admin", methods=["GET", "POST"])
    def setup_admin():
        if services.user_count() > 0:
            return redirect(url_for("login"))
        if request.method == "POST":
            try:
                user = services.create_initial_admin(request.form.to_dict())
                start_authenticated_session(user["user_id"])
                flash("초기 관리자 계정이 생성되었습니다.", "success")
                return redirect(url_for("dashboard"))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("setup_admin.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if services.user_count() == 0:
            return redirect(url_for("setup_admin"))
        if request.method == "POST":
            user = services.authenticate_user(
                request.form.get("username", ""), request.form.get("password", "")
            )
            if user:
                start_authenticated_session(user["user_id"])
                next_path = request.form.get("next", "")
                if not next_path.startswith("/") or next_path.startswith("//"):
                    next_path = url_for("dashboard")
                return redirect(next_path)
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")
        return render_template("login.html", next_path=request.args.get("next", ""))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/settings/preferences", methods=["GET", "POST"])
    def user_preferences():
        if not g.current_user:
            abort(403)
        if request.method == "POST":
            try:
                services.save_user_preferences(
                    g.current_user["user_id"], request.form.to_dict()
                )
                flash("사용자별 기본설정이 저장되었습니다.", "success")
                return redirect(url_for("user_preferences"))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("user_preferences.html")

    @app.route("/settings/users", methods=["GET", "POST"])
    def users_admin():
        edit_user_id = request.args.get("user_id", type=int)
        if request.method == "POST":
            edit_user_id = request.form.get("user_id", type=int)
            try:
                result = services.save_user(
                    request.form.to_dict(), edit_user_id,
                    actor_user_id=g.current_user["user_id"],
                )
                flash("사용자가 등록되었습니다." if result["created"] else "사용자와 화면 권한이 수정되었습니다.", "success")
                return redirect(url_for("users_admin", user_id=result["user_id"]))
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("users.html", **services.users_management_data(edit_user_id))

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("403.html"), 403
