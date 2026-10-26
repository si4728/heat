# IRIS2 independent application boundary

All executable source, dependencies, configuration, migrations, tests and documentation belong under C:/access/heat/iris2.
Do not import iris or load its Python environment, configuration, database, runtime, secrets, assets or source documents at runtime.
Do not change C:/access/heat/iris. Do not create junctions or symlinks to that directory.
The only active entry point is server.py and app.py. legacy_app.py and legacy_server.py are unported reference source, not launchers.
Use the local .venv. Web port 4824; database port 3307; schema/account prefix iris2; cookie iris2_session.
Only MariaDB is supported by the active runtime. There is no SQLite fallback.
Scope: VCM1 and VCM2 only; VCM3 and VCM4 excluded.
The active app registers secured MariaDB business routes. Validation evidence is in reports/mariadb_transition. Field UAT and engineering/model approval remain separate.
