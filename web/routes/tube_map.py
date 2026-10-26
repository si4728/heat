from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import build_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/exchangers/<int:exchanger_id>/tube-map")
    def exchanger_tube_map(exchanger_id: int):
        data = services.exchanger_detail(exchanger_id)
        if not data:
            return render_template("404.html"), 404
        hx, equipment, _unit, _plant = data["master"]
        return render_template("tube_map.html", hx=hx, equipment=equipment)

    @app.get("/api/exchangers/<int:exchanger_id>/tube-map")
    def api_exchanger_tube_map(exchanger_id: int):
        campaign_id = request.args.get("campaign_id", type=int)
        try:
            data = services.tube_map_data(exchanger_id, campaign_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 404
        if not data:
            return jsonify({"error": "not_found"}), 404
        return jsonify(data)

    @app.get("/assets/three.min.js")
    def three_vendor():
        return send_file(APP_DIR / "static" / "vendor" / "three" / "three.min.js",
                         mimetype="application/javascript", conditional=True)

    @app.get("/assets/OrbitControls.js")
    def orbit_controls_vendor():
        return send_file(APP_DIR / "static" / "vendor" / "three" / "OrbitControls.js",
                         mimetype="application/javascript", conditional=True)

    @app.get("/assets/TransformControls.js")
    def transform_controls_vendor():
        return send_file(APP_DIR / "static" / "vendor" / "three" / "TransformControls.js",
                         mimetype="application/javascript", conditional=True)

    @app.post("/api/tubes/<int:tube_id>/position")
    def api_tube_position_update(tube_id: int):
        try:
            result = services.update_tube_position(tube_id, request.get_json(silent=True) or {})
            if not result:
                return jsonify({"error": "not_found"}), 404
            return jsonify(result)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/assets/hanhwa_solution2.jpg")
    def hanwha_solution_logo():
        return send_file(APP_DIR / "static" / "hanwha_solution2.jpg",
                         mimetype="image/jpeg", conditional=True)

    @app.get("/assets/hanwha_solution.png")
    def hanwha_solution_logo_legacy():
        return redirect(url_for("hanwha_solution_logo"), code=301)
