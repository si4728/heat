"""Gracefully stop only the isolated iris2 MariaDB instance."""
import sys
from pathlib import Path
import pymysql
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
from iris2.db_config import load_database_config
settings = load_database_config(admin=True)
with pymysql.connect(host=settings["host"], port=settings["port"], user=settings["user"], password=settings["password"], autocommit=True) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@datadir, @@port")
        path, port = cursor.fetchone()
        if Path(path).resolve() != (root / "data/mariadb").resolve() or port != 3307:
            raise RuntimeError("Refusing to stop another database instance")
        cursor.execute("SHUTDOWN")
print("IRIS2 MariaDB stopped")
