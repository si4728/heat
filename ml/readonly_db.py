"""MariaDB read-only analysis snapshots with content fingerprints."""
from __future__ import annotations
import hashlib,json
from contextlib import contextmanager
from pathlib import Path
from iris2 import dbapi


def validate_database_path(database_path, data_root=None):
    dbapi.schema_for(database_path)
    return Path(database_path).resolve()


def database_sha256(database_path):
    digest=hashlib.sha256()
    with readonly_connection(database_path) as conn:
        names=[row[0] for row in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE' ORDER BY table_name")]
        for name in names:
            rows=[json.dumps(list(row),ensure_ascii=False,default=str,separators=(',',':')) for row in conn.execute(f'SELECT * FROM `{name}`')]
            digest.update(name.encode());digest.update('\n'.join(sorted(rows)).encode())
    return digest.hexdigest()


@contextmanager
def readonly_connection(database_path, *, data_root=None):
    validate_database_path(database_path,data_root)
    connection=dbapi.connect(database_path,readonly=True)
    try:
        connection.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
        yield connection
    finally:connection.close()
