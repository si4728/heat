from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.application.api510_service import pending_api510_reviews
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/")
    def dashboard():
        profile = g.get('current_user') or {}
        reviews = pending_api510_reviews() if profile.get('is_admin') else None
        return render_template("dashboard.html", api510_reviews=reviews,
            **services.dashboard_data(request.args.get('life_unit', ''), request.args.get('life_band', '')))

    @app.get("/master-data/data-entry-status")
    def data_entry_status():
        return render_template("data_entry_status.html", data_entry_coverage=services.data_entry_status_data())
