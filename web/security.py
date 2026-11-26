from __future__ import annotations

import secrets
import ipaddress
import time
from datetime import datetime
from urllib.parse import urlsplit

from flask import abort, flash, g, redirect, render_template, request, session, url_for

from iris2 import services
from iris2.hx_configuration import DB_PATH, ENDPOINT_PERMISSIONS
from iris2.application.organization_service import organization_catalog
from iris2.application.login_guard import LoginGuard
from iris2.web.access_audit import auth_event, register_access_audit
from iris2.web.safe_urls import local_redirect_path


def register_security(app) -> None:
    app.config.setdefault('LOGIN_MAX_ATTEMPTS', 5)
    app.config.setdefault('LOGIN_MAX_SOURCE_ATTEMPTS', 30)
    app.config.setdefault('LOGIN_WINDOW_SECONDS', 300)
    app.config.setdefault('AUTH_MAX_CONTENT_LENGTH', 16384)
    login_guard = LoginGuard(attempts=app.config['LOGIN_MAX_ATTEMPTS'],
        source_attempts=app.config['LOGIN_MAX_SOURCE_ATTEMPTS'], window=app.config['LOGIN_WINDOW_SECONDS'])
    app.extensions['login_guard'] = login_guard
    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        response.headers.setdefault('Referrer-Policy', 'same-origin')
        response.headers.setdefault('Content-Security-Policy', "frame-ancestors 'self'; base-uri 'self'; form-action 'self'")
        if request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
        if request.endpoint not in {'static', 'api_health', 'hanwha_solution_logo', 'hanwha_solution_logo_legacy'}:
            response.headers['Cache-Control'] = 'no-store'
        return response
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
    for endpoint in ('inspection_history_yearly', 'inspection_history_process', 'inspection_recommendation_tubes'):
        endpoint_permissions[endpoint] = 'INSPECTIONS'
    for endpoint in ('text_to_sql', 'text_to_sql_inspections', 'text_to_sql_generate', 'text_to_sql_execute'):
        endpoint_permissions[endpoint] = 'TEXT_TO_SQL'
    endpoint_permissions['text_to_sql_summarize'] = 'TEXT_TO_SQL'
    endpoint_permissions['text_to_sql_model_job'] = 'TEXT_TO_SQL'
    endpoint_permissions['analysis_plugging'] = 'EXCHANGERS'
    read_only_post_endpoints = {'text_to_sql_generate', 'text_to_sql_execute', 'text_to_sql_summarize'}
    endpoint_permissions["api510_settings"] = endpoint_permissions.get("api510_management", "REMAINING_LIFE")
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
    register_access_audit(app, endpoint_permissions)

    def start_authenticated_session(user: dict) -> None:
        session.clear()
        session.permanent = True
        session["user_id"] = user['user_id']
        # Initial setup returns the created identity, while login returns a stamp.
        profile = user if user.get('auth_stamp') else services.user_access_profile(user['user_id'])
        session['auth_stamp'] = profile['auth_stamp']
        session["last_activity_at"] = time.time()
        session['audit_session_id'] = secrets.token_hex(16)

    @app.before_request
    def enforce_authentication_and_permissions():
        g.current_user = None
        if app.config.get('REQUIRE_HTTPS') and not request.is_secure and request.endpoint != 'api_health':
            abort(400, description='HTTPS is required.')
        if request.endpoint in {'login', 'setup_admin'}:
            request.max_content_length = app.config['AUTH_MAX_CONTENT_LENGTH']
        if (
            app.config.get("CSRF_ENABLED")
            and request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}
            and request.endpoint not in csrf_exempt_endpoints
        ):
            expected = session.get("csrf_token")
            supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if (not isinstance(expected, str) or not isinstance(supplied, str) or not expected or not supplied
                    or not secrets.compare_digest(expected.encode('utf-8'), supplied.encode('utf-8'))):
                g.audit_reason = 'CSRF_REJECTED'
                if request.endpoint == 'login' and request.method == 'POST':
                    g.audit_username = request.form.get('username','')
                    g.audit_user_id = None
                    auth_event('LOGIN_FAILURE','FAILURE','CSRF_REJECTED')
                abort(400, description="Invalid or missing CSRF token")
        if app.config.get("AUTH_DISABLED"):
            if request.endpoint in pdf_review_endpoints or request.endpoint in {'access_logs','access_logs_export'}:
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
                g.audit_reason = 'SESSION_EXPIRED'
                auth_event('SESSION_EXPIRED','SUCCESS','SESSION_EXPIRED')
                session.clear()
                flash("30분 동안 사용이 없어 자동 로그아웃되었습니다.", "warning")
                next_path = request.full_path.rstrip("?")
                return redirect(url_for("login", next=next_path))
            session["last_activity_at"] = now
        profile = services.user_access_profile(session.get("user_id")) if session.get("user_id") else None
        if not profile:
            g.audit_reason = 'SESSION_INVALID' if session.get('user_id') else 'AUTH_REQUIRED'
            if session.get('user_id'):
                auth_event('SESSION_INVALID','SUCCESS','SESSION_INVALID')
            session.clear()
            next_path = request.full_path.rstrip("?")
            return redirect(url_for("login", next=next_path))
        expected_stamp = profile.get('auth_stamp')
        supplied_stamp = session.get('auth_stamp')
        if (not isinstance(expected_stamp, str) or not isinstance(supplied_stamp, str)
                or not expected_stamp or not secrets.compare_digest(expected_stamp.encode('utf-8'), supplied_stamp.encode('utf-8'))):
            g.audit_reason = 'SESSION_INVALID'
            auth_event('SESSION_INVALID', 'SUCCESS', 'SESSION_INVALID')
            session.clear()
            return redirect(url_for('login', next=request.full_path.rstrip('?')))
        g.current_user = profile
        if not session.get('audit_session_id'):
            session['audit_session_id'] = secrets.token_hex(16)
        session['audit_username'] = profile.get('username','')
        g.audit_session_id = session['audit_session_id']
        if endpoint in pdf_review_endpoints and not profile["is_admin"]:
            abort(403)
        if endpoint in {"users_admin", "database_monitor", "backup_manager", "data_entry_status", "imports", "access_logs", "access_logs_export"}:
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
        edit_required = (request.method not in {"GET", "HEAD", "OPTIONS"} and endpoint not in read_only_post_endpoints) or endpoint in edit_page_endpoints
        if not services.user_can(profile, screen_key, edit=edit_required):
            abort(403)
        return None

    @app.context_processor
    def globals_for_templates():
        def can_screen(screen_key: str, action: str = "view") -> bool:
            if screen_key == "PDF_OCR_REVIEW":
                return bool(g.get("current_user") and g.current_user.get("is_admin")) and services.user_can(g.get("current_user"), screen_key, edit=action == "edit")
            if app.config.get("AUTH_DISABLED"):
                return True
            return services.user_can(g.get("current_user"), screen_key, edit=action == "edit")
        display_codes = {}
        def exchanger_display_code(exchanger_id):
            if exchanger_id not in display_codes:
                display_codes[exchanger_id] = services.exchanger_display_code(exchanger_id)
            return display_codes[exchanger_id]
        csrf_token = session.get("csrf_token")
        if not csrf_token:
            csrf_token = secrets.token_urlsafe(32)
            session["csrf_token"] = csrf_token
        return {"database_path": "MariaDB / iris2", "now": datetime.now(),
                "csrf_token": csrf_token,
                "current_user": g.get("current_user"), "can_screen": can_screen,
                "exchanger_display_code": exchanger_display_code,
                "active_theme": services.active_theme_data(),
                "organization_choices": catalog()["entries"]}

    @app.route("/setup-admin", methods=["GET", "POST"])
    def setup_admin():
        if services.user_count() > 0:
            return redirect(url_for("login"))
        try:
            local_client = ipaddress.ip_address(request.remote_addr or '').is_loopback
        except ValueError:
            local_client = False
        if not local_client or urlsplit(request.host_url).hostname not in {'localhost', '127.0.0.1', '::1'}:
            abort(403)
        if request.method == "POST":
            try:
                user = services.create_initial_admin(request.form.to_dict())
                start_authenticated_session(user)
                session['audit_username'] = user['username']
                auth_event('INITIAL_ADMIN','SUCCESS','INITIAL_ADMIN',user)
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
            ticket, retry_after = login_guard.begin(request.remote_addr or 'unknown', request.form.get('username', ''))
            if ticket is None:
                g.audit_username = request.form.get('username', '')
                g.audit_user_id = None
                auth_event('LOGIN_FAILURE', 'FAILURE', 'LOGIN_RATE_LIMITED')
                flash('로그인 시도가 많습니다. 잠시 후 다시 시도해 주세요.', 'warning')
                return render_template('login.html', next_path=request.form.get('next', '')), 429, {'Retry-After': str(retry_after)}
            user = services.authenticate_user(request.form.get('username', ''), request.form.get('password', ''))
            login_guard.finish(ticket, success=bool(user))
            if user:
                start_authenticated_session(user)
                session['audit_username'] = user['username']
                auth_event('LOGIN_SUCCESS','SUCCESS','AUTHENTICATED',user)
                next_path = local_redirect_path(request.form.get('next', ''), url_for('dashboard'))
                return redirect(next_path)
            g.audit_username = request.form.get('username','')
            g.audit_user_id = None
            auth_event('LOGIN_FAILURE','FAILURE','INVALID_CREDENTIALS')
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")
        return render_template("login.html", next_path=request.args.get("next", ""))

    @app.post("/logout")
    def logout():
        auth_event('LOGOUT','SUCCESS','USER_LOGOUT',g.current_user)
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
