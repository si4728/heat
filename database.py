"""MariaDB-only runtime. No dependency on the original iris package."""
from __future__ import annotations
from functools import lru_cache
from sqlalchemy import URL, create_engine, text, event
from sqlalchemy.orm import sessionmaker
from .db_config import load_database_config


def connection_url():
    config = load_database_config()
    return URL.create("mariadb+pymysql", username=config["user"], password=config["password"],
        host=config["host"], port=config["port"], database=config["name"],
        query={"charset": config["charset"]})



@lru_cache(maxsize=1)
def get_engine():
    engine = create_engine(connection_url(), pool_pre_ping=True, pool_recycle=1800,
        pool_size=5, max_overflow=5, pool_timeout=15,
        connect_args={"connect_timeout": 5, "read_timeout": 30, "write_timeout": 30},
        isolation_level="REPEATABLE READ", hide_parameters=True)
    @event.listens_for(engine, "handle_error")
    def record_lock(context):
        from .database_monitor import is_database_lock_error, record_database_lock
        from .db_config import APP_DIR
        if is_database_lock_error(context.original_exception):
            record_database_lock(APP_DIR/"data/heat_exchanger_db3.db",context.original_exception,context.statement)
    return engine


def session_factory():
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def database_status():
    with get_engine().connect() as connection:
        version = connection.scalar(text("SELECT VERSION()"))
        if "mariadb" not in str(version).lower():
            raise RuntimeError("A MariaDB server is required")
        tables = connection.scalar(text("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()"))
        return {"backend": "mariadb", "version": version, "tables": tables,
                "schema_ready": tables >= 57, "migration_status": "MARIADB_BUSINESS_ROUTES_ENABLED"}
