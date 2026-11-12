# IRIS2 development rules
Read APPLICATION_BOUNDARY.md and docs/MARIADB_DEVELOPMENT_PLAN.md before changes.
Keep all work in iris2. Never modify iris. Do not import iris.
Run tests with iris2/.venv/Scripts/python.exe. Never use the parent environment.
Do not expose copied legacy routes until their MariaDB data access and authorization are verified.
Never use operational SQLite as a writable migration source. Accept only a separately provided snapshot within iris2/data/import.
Scope: VCM1 and VCM2. Do not add VCM3/VCM4 work.

## Two-PC GitHub workflow (effective 2026-11-12)
GitHub origin (si4728/heat) is the shared source of truth for the production and development PCs.
Before changes, fetch origin and inspect incoming commits; preserve local work and integrate remote changes before publishing.
Use a separate task branch per PC/task when both PCs are editing. Publish tested source, tests, tooling and documentation through GitHub.
Before pushing, fetch again and reconcile concurrent changes. Never force-push main or overwrite another PC's work.
Do not commit private config, credentials, session files, runtime data, model weights, generated reports or business source documents.
Keep PC-specific MariaDB accounts/config, virtual environments and model files local. A Git update does not provision DB accounts or deploy/restart the application.
For production updates, use a clean checkout and git pull --ff-only; if local edits exist, commit them on a task branch before integration.
