from __future__ import annotations

from flask import render_template, request

from iris2 import services


def register_routes(app) -> None:
    @app.get("/settings/tube-layout-revisions")
    def tube_layout_revisions():
        return render_template(
            "tube_layout_revisions.html",
            **services.tube_layout_revision_management_data(
                request.args.get("status", ""),
                request.args.get("equipment", ""),
            ),
        )
