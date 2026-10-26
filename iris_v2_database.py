"""MariaDB persistence facade retaining historical application function names."""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from .database import connection_url, get_engine
from .db_config import APP_DIR

SCHEMA_VERSION="3.14.0"
DEFAULT_DB_PATH=APP_DIR/"data/heat_exchanger_db3.db"


def resolve_v2_db_path(db_path=None):
    path=Path(db_path or DEFAULT_DB_PATH).resolve()
    if not path.is_relative_to(APP_DIR):
        raise ValueError("Database selector must remain inside iris2")
    return path

resolve_v3_db_path=resolve_v2_db_path


def create_v2_engine(db_path=None, *, echo=False, poolclass=None):
    resolve_v2_db_path(db_path)
    return create_engine(connection_url(), pool_pre_ping=True, pool_recycle=1800,
        isolation_level="REPEATABLE READ", hide_parameters=True,
        connect_args={"connect_timeout":5,"read_timeout":30,"write_timeout":30})


def create_v2_session_factory(db_path=None):
    engine=create_v2_engine(db_path)
    return sessionmaker(bind=engine,autoflush=False,expire_on_commit=False),engine


@contextmanager
def session_scope(db_path=None):
    resolve_v2_db_path(db_path)
    factory=sessionmaker(bind=get_engine(),autoflush=False,expire_on_commit=False)
    with factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def init_v2_db(db_path=None):
    # Schema changes are explicit migrations, never SQLite startup migrations.
    with get_engine().connect() as connection:
        version=connection.scalar(text("SELECT version FROM schema_version WHERE version=:version"),{"version":SCHEMA_VERSION})
        if version is None:raise RuntimeError("MariaDB schema migration is required")
    return resolve_v2_db_path(db_path)


def verify_v2_db(db_path=None):
    engine=get_engine(); inspector=inspect(engine)
    issues=[]
    with engine.connect() as conn:
        for table in inspector.get_table_names():
            for fk in inspector.get_foreign_keys(table):
                local=fk['constrained_columns'];remote=fk['referred_columns'];parent=fk['referred_table']
                join=' AND '.join(f'c.`{a}`=p.`{b}`' for a,b in zip(local,remote))
                valid=' AND '.join(f'c.`{a}` IS NOT NULL' for a in local)
                count=conn.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}` c LEFT JOIN `{parent}` p ON {join} WHERE {valid} AND p.`{remote[0]}` IS NULL').scalar()
                if count:issues.append({'table':table,'constraint':fk['name'],'count':count})
        version=conn.scalar(text('SELECT VERSION()'))
        versions=list(conn.scalars(text('SELECT version FROM schema_version')))
    return {'backend':'mariadb','database_path':connection_url().render_as_string(hide_password=True).split('@')[-1],
        'schema_version':SCHEMA_VERSION,'recorded_schema_versions':versions,
        'table_count':len(inspector.get_table_names()),'tables':inspector.get_table_names(),
        'foreign_keys_enabled':True,'foreign_key_issue_count':sum(x['count'] for x in issues),
        'foreign_key_issues':issues,'integrity_check':'ok' if not issues else 'failed','mariadb_version':version}
