from __future__ import annotations

from flask import flash, render_template, request

from iris2.llm_integration.natural_query import natural_language_search


def register_routes(app) -> None:
    @app.get("/inspections/ai-search")
    def ai_natural_query():
        query = request.args.get("q", "")
        result = None
        if query.strip():
            try:
                result = natural_language_search(query)
            except ValueError as exc:
                flash(str(exc), "error")
        return render_template("ai_natural_query.html", query=query, result=result)
