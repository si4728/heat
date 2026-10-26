# MariaDB snapshot — 2026-10-26

`iris2_20261026.sql.gz` contains the four application schemas: `iris2`,
`iris2_llm`, `iris2_ml`, and `iris2_pdf`, including tables, data, triggers and
routines. It was exported with `--single-transaction`. Test schemas and MariaDB
system accounts are excluded. See `manifest.json` for size and SHA-256.

All three application login password hashes were replaced with the invalid value
`!DISABLED_PUBLIC_EXPORT!`. Existing IDs and account relationships are retained.
The original local database and its passwords were not changed. Configure new
passwords after restoring. Private connection files, API keys and session secrets
are excluded from Git.

## Restore on a separate MariaDB 11.4 instance

Restore only into a new, isolated instance: the dump contains DROP TABLE statements
for the four named schemas. Do not import over a running installation.

1. Verify the archive SHA-256 against `manifest.json`.
2. Decompress using Python from the project directory:

   ```powershell
   .\.venv\Scripts\python.exe -c "import gzip,pathlib; p=pathlib.Path('database_snapshot/iris2_20261026.sql.gz'); p.with_suffix('').write_bytes(gzip.decompress(p.read_bytes()))"
   ```

3. Open the MariaDB client against the new instance, with an administrative account
   and an interactive password prompt, then run:

   ```sql
   SOURCE C:/access/heat/iris2/database_snapshot/iris2_20261026.sql;
   ```

   Adjust the path to the actual checkout. The runtime expects the checkout
   directory to be named `iris2` (for example, `git clone URL iris2`).

4. Create new `iris2_app` and `iris2_readonly` database accounts. Grant the app
   SELECT/INSERT/UPDATE/DELETE on each application schema, and the read-only account
   SELECT only. Configure both applicable host entries for your installation.
   Account creation and passwords are intentionally not included in the dump.
5. Copy `config/database.example.conf` to `config/database.conf`, and create
   `config/database-readonly.conf` with the new read-only credentials. If migration
   administration is required, create `config/database-admin.conf` separately.
6. Reset application login passwords locally using Werkzeug's
   `generate_password_hash` and a parameterized UPDATE of `iris2.app_user`.
   Never publish the new password or hash. Existing accounts mean that the initial
   setup page will redirect to login until this password reset is completed.
7. Install the local Python requirements and configure MariaDB before starting
   `server.py`. The bundled-machine `start_mariadb.ps1` expects an independently
   installed runtime and `data/mariadb/my.ini`; these machine files are excluded.

The compressed archive was checked by a full compression/decompression round trip.
This sanitized snapshot has not been restored into a fresh server during upload.
The original integration test results are in `verification/20261026`.

Raw source JSON and PDF evidence are excluded from this public upload.
PDF links and operations requiring those files need separately supplied evidence.
Historical absolute file references in restored data may need relocation on a
different machine.
