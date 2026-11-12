# Text-to-SQL DB verification — 2026-11-12

The second-PC runtime was missing config/database-text-to-sql.conf. Create a separate local SELECT-only account/config on each PC; never copy or commit credentials.

MariaDB on loopback:3307 also inherited default PUBLIC write privileges on test and test\_% schemas. The Text-to-SQL SHOW GRANTS check correctly refused execution. Business data was not modified. The repair tool only removes these default test-schema grants; it preserves business grants and fails for non-local database endpoints.

From the iris2 directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe tools/provision_text_to_sql_account.py --apply
.\.venv\Scripts\python.exe tools/repair_text_to_sql_public_grants.py --apply
.\.venv\Scripts\python.exe tools/verify_text_to_sql_web.py
.\.venv\Scripts\python.exe tools/verify_text_to_sql_live.py
```

The provisioner leaves an existing private configuration unchanged and refuses to replace an existing account without matching configuration. No application restart is required for new DB connections. Launch remains run.cmd.

Authenticated web checks passed after repair: anonymous redirect, page/menu, CSRF enforcement, real inspection catalog, actual local-model SQL generation and MariaDB execution. Live summary and threshold queries matched direct DB results, and unsupported lifetime analysis was rejected. The top-five check needed updating because detail results now include server-attached equipment identity; it now verifies both source values and identity.

Evidence is stored locally under reports/text_to_sql (ignored by Git). The private DB configuration is ignored by GitHub main's .gitignore. Git is unavailable on this PC's PATH; repository updates were made through the GitHub connector with the current file SHA, preserving remote edits. Synchronize this PC's checkout after installing Git before further collaborative commits.
