# IRIS2 MariaDB application

GitHub checkout: clone this repository into a directory named `iris2`.
The database snapshot and restore instructions are in
[database_snapshot](database_snapshot/README.md). Application login passwords
are disabled in the published snapshot and must be reset locally after restore.
Raw source JSON and PDF evidence are excluded from this public upload.
Latest automated verification: [2026-10-26](verification/20261026/RECHECK.md).

Independent development root: C:/access/heat/iris2. Original iris is preserved.

Run `./setup.ps1`, configure `config/database.conf`, then `./run.ps1`. Direct Python and PowerShell launchers use the same config file.
`run.cmd` and `run.ps1` start the existing independent local MariaDB instance and wait for it before starting the web server. `-HealthCheck` only checks the current state. Direct `server.py` execution requires MariaDB to be started separately with `./start_mariadb.ps1`.
Open http://127.0.0.1:4824. Missing MariaDB returns health HTTP 503, never a SQLite fallback.
The installed local MariaDB instance uses config/database.conf. compose.yaml is an alternative deployment template and is not used by the installed instance.
The compose deployment uses port 3307 and its own named volume. Pin a validated image digest before production.
Tests: `.venv/Scripts/python.exe tools/run_validation.py`.
Schema draft: `.venv/Scripts/python.exe migration/schema_draft.py`.

The secured MariaDB business routes are enabled. Sign in with the migrated application account.
Existing iris is preserved. Original data, PDF and JSON evidence have independent iris2 copies.
Private database settings are config/database.conf, config/database-admin.conf and config/database-readonly.conf.
The application config [schemas] section maps all four data stores. Restart after config changes.
See [transition results](docs/MARIADB_TRANSITION_RESULT.md) for current status and operations.


2026-10-17: 62 original tables and 78,120 rows reconciled. Two runtime support tables bring the total to 64 across four schemas. Automated tests 57/57; authenticated GET checks 48/48; isolated restore parity passed.
Field UAT, engineering approval and independent local LLM runtime validation remain separate acceptance items.
Backups restore into isolated schemas for validation; promotion requires a maintenance window and explicit config updates.
Historical SQLite-specific tests and one-off correction tools are not MariaDB runtime entry points.
