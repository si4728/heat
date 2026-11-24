"""Disposable MariaDB copy for customer-change writes; never writes source tables."""
from contextlib import contextmanager
import re
import uuid
from unittest.mock import patch
from sqlalchemy import inspect
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for


@contextmanager
def customer_clone():
    config=load_database_config();admin=load_database_config(admin=True)
    if config['port']!=3307 or config['host'] not in ('localhost','127.0.0.1'):
        raise ValueError('Only local iris2 MariaDB is permitted')
    source=config['name'];schema='iris2_test_customer_'+uuid.uuid4().hex[:12]
    if not re.fullmatch(r'iris2[a-zA-Z0-9_]*',source):raise ValueError('Invalid source schema')
    controller=engine_for(admin,'mysql');engine=None;grants=[]
    try:
        with controller.begin() as c:c.exec_driver_sql(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4')
        engine=engine_for(admin,schema)
        with engine.connect() as source_conn:
            tables=[r[0] for r in source_conn.exec_driver_sql('SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type=%s',(source,'BASE TABLE'))]
        with engine.begin() as c:
            for table in tables:
                if not re.fullmatch(r'[A-Za-z0-9_]+',table):raise ValueError('Invalid table identifier')
                c.exec_driver_sql(f'CREATE TABLE `{table}` LIKE `{source}`.`{table}`')
            views=[r[0] for r in c.exec_driver_sql('SELECT table_name FROM information_schema.views WHERE table_schema=%s',(source,))]
            for view in views:
                if not re.fullmatch(r'[A-Za-z0-9_]+',view):raise ValueError('Invalid view identifier')
                definition=c.exec_driver_sql(f'SHOW CREATE VIEW `{source}`.`{view}`').first()[1]
                definition=re.sub(r'DEFINER=`[^`]*`@`[^`]*`\s*','',definition)
                definition=definition.replace('`'+source+'`.','`'+schema+'`.')
                c.exec_driver_sql(definition)
        with engine.connect() as source_conn:
            source_conn.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            source_conn.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            with engine.begin() as target:
                for table in tables:
                    columns=[r['name'] for r in inspect(target).get_columns(table) if not r.get('computed')]
                    names=','.join('`'+n+'`' for n in columns)
                    rows=[tuple(r) for r in source_conn.exec_driver_sql(f'SELECT {names} FROM `{source}`.`{table}`')]
                    if rows:target.exec_driver_sql(f'INSERT INTO `{table}` ({names}) VALUES ({",".join(["%s"]*len(columns))})',rows)
            source_conn.rollback()
        for path in ('config/database-readonly.conf','config/database-text-to-sql.conf'):
            reader=load_database_config(path=path)
            with controller.begin() as c:
                for host in ('localhost','127.0.0.1'):
                    if c.exec_driver_sql('SELECT COUNT(*) FROM mysql.user WHERE User=%s AND Host=%s',(reader['user'],host)).scalar():
                        c.exec_driver_sql(f'GRANT SELECT ON `{schema}`.* TO %s@%s',(reader['user'],host))
                        grants.append((reader['user'],host))
        from iris2 import dbapi
        original=dbapi.schema_for
        def select_schema(selector):
            return schema if 'heat_exchanger_db3.db' in str(selector) else original(selector)
        with patch('iris2.database.get_engine',return_value=engine),patch('iris2.iris_v2_database.get_engine',return_value=engine),patch('iris2.dbapi.schema_for',side_effect=select_schema):
            yield engine,schema
    finally:
        if engine is not None:engine.dispose()
        if not re.fullmatch(r'iris2_test_customer_[0-9a-f]{12}',schema):raise RuntimeError('Unsafe cleanup target')
        with controller.begin() as c:
            for user,host in set(grants):
                c.exec_driver_sql(f'REVOKE SELECT ON `{schema}`.* FROM %s@%s',(user,host))
            c.exec_driver_sql(f'DROP DATABASE IF EXISTS `{schema}`')
        controller.dispose()
