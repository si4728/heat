"""Explicit additive MariaDB migration; no business rows are updated or deleted."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy import inspect, text
from iris2.application.access_audit import AccessAuditEvent
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for

VERSION = '3.14.0-access-audit-1'
TRIGGERS = {'access_audit_no_update':'UPDATE','access_audit_no_delete':'DELETE'}


def apply_migration(engine):
    AccessAuditEvent.__table__.create(engine,checkfirst=True)
    with engine.begin() as connection:
        actual = {column['name'] for column in inspect(connection).get_columns('access_audit_event')}
        if actual != set(AccessAuditEvent.__table__.columns.keys()):
            raise RuntimeError('Existing audit schema differs; inspect before proceeding')
        for name, event in TRIGGERS.items():
            existing = connection.exec_driver_sql(
                'SELECT event_manipulation,action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name=%s',(name,)).first()
            if existing:
                if existing[0] != event or 'IRIS2 audit history is append-only' not in existing[1]:
                    raise RuntimeError('Existing audit trigger differs')
                continue
            connection.exec_driver_sql(f"CREATE TRIGGER `{name}` BEFORE {event} ON access_audit_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='IRIS2 audit history is append-only'")
        if inspect(connection).has_table('schema_version'):
            connection.execute(text('INSERT INTO schema_version (version,applied_at,description) '
                'SELECT :version,:now,:description WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version=:version)'),
                dict(version=VERSION,now=datetime.now(timezone.utc).replace(tzinfo=None),
                     description='Append-only authentication and screen/API access audit; no business row changes'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    app=load_database_config()
    admin=load_database_config(admin=True)
    if (app['host'],app['port']) != (admin['host'],admin['port']) or app['port'] != 3307 or app['host'] not in ('127.0.0.1','localhost'):
        raise ValueError('Migration requires the configured local iris2 MariaDB at port 3307')
    if not re.fullmatch('iris2[a-zA-Z0-9_]*',app['name']):
        raise ValueError('Invalid iris2 schema')
    if not args.apply:
        print('Plan: add access_audit_event, six indexes, two append-only triggers and schema marker '+VERSION)
        return
    engine=engine_for(admin,app['name'])
    try:
        apply_migration(engine)
        print('Applied '+VERSION+' to configured iris2 schema; business data unchanged')
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
