# MariaDB data migration results

62 source tables and 78,120 original rows were migrated without filtering production lines.
All original columns matched after explicit datetime normalization; foreign-key orphan count was zero.
The original iris source and operational database were preserved.

The current runtime additionally has two support tables (64 tables across four schemas).
See [current transition report](MARIADB_TRANSITION_RESULT.md) for the authoritative current status, stage results, tests, deployment and remaining acceptance items.
Detailed data evidence: DATA_MIGRATION_RESULT.json and the immutable snapshots under iris2/data/import.
