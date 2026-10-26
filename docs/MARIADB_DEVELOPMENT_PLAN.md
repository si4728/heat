# IRIS2 MariaDB development and migration plan

Date: 2026-10-17. Scope: VCM1 and VCM2 only.
Original iris remains unchanged. iris2 is a separate application, not a production replacement yet.

1. Foundation: isolated source/package/environment/config/ports/schema/accounts; no fallback or shared secrets.
2. Schema: inventory actual baseline schema and triggers; convert types and conditional uniqueness, revision overlap rules, indexes and constraints. Generate versioned DDL and test against MariaDB.
3. Data access: replace SQLite PRAGMA, ON CONFLICT, INSERT OR IGNORE, date SQL, direct sqlite3 usage, and SQLite exception handling. Port all administration/AI/ML stores.
4. Business routes: register only after authorization, transactions, query parity and concurrency tests pass. Port master data, inspections, Tube Map, calculations, maintenance and reporting in that order.
5. Operations: database revision counter for Excel cache; consistent export snapshot; account-enforced ML read-only access; extraction fingerprints; mariadb-dump backup and independent restore drill.
6. Migration: accept an iris2-local snapshot only; preserve IDs and history; copy in FK order; compare normalized field values and counts; preserve file evidence with copied local assets.
7. Acceptance: regression and MariaDB integration tests, VCM1/VCM2 UAT, concurrency, outages, permission and restore tests.
8. Cutover: stop all writes and jobs; final snapshot, migrate and reconcile; switch endpoints; verify read-only; resume writes. After writes resume, do not restore stale SQLite without reconciling new data.

## Current status

Technical transition complete: MariaDB business routes enabled after 57 automated tests, 48 authenticated GET checks, four-schema restore parity and full original-data reconciliation. See MARIADB_TRANSITION_RESULT.md for current status. Field-user acceptance and engineering/model approvals remain separate.

## Independence rules

Local .venv, config, data, uploads, backups, reports, logs, model paths, scripts and docs.
No iris imports, junctions, hard links, shared DB files, parent virtual environment or inherited IRIS_* configuration.
Historical references can retain old concepts, but must not be interpreted as active runtime configuration.

## Acceptance gates

Original source manifest unchanged; active app imports no iris modules.
MariaDB unavailable: health/readiness indicate failure safely; no database created implicitly.
All schema constraints and computed-column replacements verified on MariaDB.
All field comparisons and ID relationships match; no unapproved data loss or numeric changes.
Final operational approval requires working business routes, live DB tests and UAT.

Full existing database content must be migrated without filtering rows by production line. VCM3/VCM4 exclusion concerns new development/UAT only.


2026-10-17 update: active source databases migrated to MariaDB (62 tables, 78,120 rows); full field comparison passed. See docs/DATA_MIGRATION_RESULT.md for authoritative current status. Earlier empty-database statements are historical. Business cutover and linked-file relocation remain pending.
