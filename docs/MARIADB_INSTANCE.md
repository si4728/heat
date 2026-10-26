# IRIS2 MariaDB instance

Created 2026-10-17. MariaDB 11.4.12, 127.0.0.1:3307, database iris2, account iris2_app.
Runtime and data are under iris2/runtime and iris2/data/mariadb; no Windows service was installed or changed.
The existing MariaDB service on port 3306 remains unchanged.
The official ZIP SHA256 was verified; provenance is in runtime/mariadb_manifest.json.
Credentials are saved in ACL-restricted config/database.conf (application) and config/database-admin.conf (administration). Both files are excluded from Git. Do not publish them.
Both direct Python execution and run.ps1 use the shared db_config.py loader. Environment credential overrides are not used. Configuration changes take effect after application restart. Changing config values does not change MariaDB passwords or grants.
The application account has DML privileges on iris2 only; use the protected administrator credential for schema migrations.

Start the application after Windows restart with `run.cmd` (or `./run.ps1`); it starts the existing local MariaDB instance and waits for readiness before launching the web server.
Start only MariaDB: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_mariadb.ps1`.
Stop gracefully: `.\.venv\Scripts\python.exe tools/stop_mariadb.py`.
Health check: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 -HealthCheck`.
This is a manually started independent development process, not an automatically started service.

The database is empty: business DDL and all original data still need to be migrated and validated.
Creating this instance does not mean that the system or data migration is complete.
Existing source data must be fully preserved regardless of process code. VCM3/VCM4 exclusion applies only to new feature work/UAT, not deletion of existing records.


2026-10-17 update: active source databases migrated to MariaDB (62 tables, 78,120 rows); full field comparison passed. See docs/DATA_MIGRATION_RESULT.md for authoritative current status. Earlier empty-database statements are historical. Business cutover and linked-file relocation remain pending.
