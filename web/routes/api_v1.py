from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from flask import abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename

from iris2 import services
from iris2.excel_export import get_heat_exchanger_export
from iris2.hx_configuration import API_WRITE_TOKEN, APP_DIR, DB_PATH, UPLOAD_DIR


def register_routes(app) -> None:
    @app.get("/api/health")
    def api_health():
        try:
            health = services.database_health()
        except Exception:
            return jsonify(status="unavailable",backend="mariadb"),503
        public_health = {
            "status": "ok" if health["integrity_check"] == "ok" else "error",
            "schema_version": health["schema_version"],
            "backend": "mariadb",
            "mariadb_version": health["mariadb_version"],
            "integrity_check": health["integrity_check"],
            "foreign_key_issue_count": health["foreign_key_issue_count"],
        }
        return jsonify(public_health), 200 if health["integrity_check"] == "ok" else 503

    def require_api_write_token():
        app_module = sys.modules.get("iris2.app")
        expected = getattr(app_module, "API_WRITE_TOKEN", API_WRITE_TOKEN)
        if not expected:
            abort(503, description="Write API is disabled until api_write_token is configured.")
        if request.headers.get("X-IRIS-API-Token") != expected:
            abort(401)

    @app.get("/api/v1/exchangers")
    def api_exchangers():
        data = services.list_exchangers(search=request.args.get("search", ""),
                                        plant_code=request.args.get("plant", ""),
                                        unit_code=request.args.get("unit", ""))
        return jsonify([{"heat_exchanger_id": hx.heat_exchanger_id,
                         "equipment_code": equipment.equipment_code,
                         "exchanger_code": data["exchanger_codes"].get(hx.heat_exchanger_id),
                         "equipment_name": equipment.equipment_name,
                         "plant_code": plant.plant_code,
                         "unit_code": unit.unit_code,
                         "inspection_status": hx.inspection_lifecycle_status}
                        for hx, equipment, unit, plant in data["rows"]])

    @app.get("/api/v1/exchangers/<int:exchanger_id>/history")
    def api_exchanger_history(exchanger_id: int):
        data = services.exchanger_detail(exchanger_id)
        if not data: abort(404)
        hx, equipment, unit, plant = data["master"]
        setups = data.get("inspection_setups", {})
        executions = data.get("inspection_executions", {})
        providers = data.get("inspection_providers", {})
        return jsonify({"heat_exchanger_id": hx.heat_exchanger_id,
            "plant_code": plant.plant_code, "unit_code": unit.unit_code,
            "equipment_code": equipment.equipment_code,
            "exchanger_code": data["spec"].exchanger_code if data.get("spec") else None,
            "inspections": [{"inspection_id": i.iris_inspection_id,
                "report_date": i.report_date.date().isoformat() if i.report_date else None,
                "inspection_date": i.inspection_date.date().isoformat() if i.inspection_date else None,
                "installation_or_replacement_date_raw": i.installation_or_replacement_date_raw,
                "installation_or_replacement_date_precision": i.installation_or_replacement_date_precision,
                "bundle_code": i.source_bundle_code,
                "scope_code": i.source_scope_code,
                "process_code": setups[i.iris_inspection_id].process_code if i.iris_inspection_id in setups else None,
                "production_line": setups[i.iris_inspection_id].production_line if i.iris_inspection_id in setups else None,
                "inspection_provider": (
                    providers[executions[i.iris_inspection_id].inspection_provider_id].provider_name
                    if i.iris_inspection_id in executions
                    and executions[i.iris_inspection_id].inspection_provider_id in providers else None
                ),
                "inspection_company_source_text": (
                    executions[i.iris_inspection_id].inspection_company_source_text
                    if i.iris_inspection_id in executions else None
                ),
                "maximum_wall_loss_percent": i.reported_maximum_wall_loss_percent}
                for i, _scope in data["inspections"]]})

    @app.post("/api/v1/exchangers")
    def api_exchanger_create():
        require_api_write_token()
        try: return jsonify(services.save_exchanger(request.get_json(silent=True) or {})), 201
        except (ValueError, TypeError) as exc: return jsonify({"error": str(exc)}), 400

    @app.put("/api/v1/exchangers/<int:exchanger_id>")
    def api_exchanger_update(exchanger_id: int):
        require_api_write_token()
        try: return jsonify(services.save_exchanger(request.get_json(silent=True) or {}, exchanger_id))
        except (ValueError, TypeError) as exc: return jsonify({"error": str(exc)}), 400

    @app.get("/exports/heat-exchangers-tubes.xlsx")
    def export_heat_exchangers_tubes():
        workbook = get_heat_exchanger_export(DB_PATH)
        filename = f"heat_exchangers_tubes_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        return send_file(
            workbook,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
            max_age=0,
        )
