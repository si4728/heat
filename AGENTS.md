# IRIS2 development rules
Read APPLICATION_BOUNDARY.md and docs/MARIADB_DEVELOPMENT_PLAN.md before changes.
Keep all work in iris2. Never modify iris. Do not import iris.
Run tests with iris2/.venv/Scripts/python.exe. Never use the parent environment.
Do not expose copied legacy routes until their MariaDB data access and authorization are verified.
Never use operational SQLite as a writable migration source. Accept only a separately provided snapshot within iris2/data/import.
Scope: VCM1 and VCM2. Do not add VCM3/VCM4 work.
