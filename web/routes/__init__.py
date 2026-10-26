from .api510 import register_routes as register_api510_routes
from .api_v1 import register_routes as register_api_v1_routes
from .dashboard import register_routes as register_dashboard_routes
from .exchangers import register_routes as register_exchanger_routes
from .imports import register_routes as register_import_routes
from .inspections import register_routes as register_inspection_routes
from .maintenance import register_routes as register_maintenance_routes
from .remaining_life import register_routes as register_remaining_life_routes
from .tube_map import register_routes as register_tube_map_routes
from .system import register_routes as register_system_routes
from .layouts import register_routes as register_layout_routes
from .llm_reports import register_routes as register_llm_report_routes
from .ai_query import register_routes as register_ai_query_routes

ROUTE_REGISTRARS = (
    register_dashboard_routes,
    register_exchanger_routes,
    register_remaining_life_routes,
    register_api510_routes,
    register_inspection_routes,
    register_maintenance_routes,
    register_tube_map_routes,
    register_import_routes,
    register_system_routes,
    register_layout_routes,
    register_llm_report_routes,
    register_ai_query_routes,
    register_api_v1_routes,
)
