"""Explicit MariaDB migration for immutable actual plugging operations."""
from datetime import datetime, timezone
from sqlalchemy import inspect, text
from ..iris_v2_models import TubePluggingEvent, CustomerCorrectionEvent

VERSION = '3.14.0-plugging-events-1'


def apply_migration(engine):
    TubePluggingEvent.__table__.create(engine, checkfirst=True)
    CustomerCorrectionEvent.__table__.create(engine, checkfirst=True)
    with engine.begin() as c:
        if {r['name'] for r in inspect(c).get_columns('tube_plugging_event')} != set(TubePluggingEvent.__table__.columns.keys()):
            raise RuntimeError('Plugging event schema mismatch')
        for name, operation in [('iris2_plugging_no_update','UPDATE'),('iris2_plugging_no_delete','DELETE')]:
            prior = c.exec_driver_sql('SELECT action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE() AND trigger_name=%s',(name,)).scalar()
            if prior:
                if 'IRIS2 plugging history is append-only' not in prior:
                    raise RuntimeError('Unexpected plugging trigger')
            else:
                c.exec_driver_sql(f"CREATE TRIGGER `{name}` BEFORE {operation} ON tube_plugging_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='IRIS2 plugging history is append-only'")
        for operation in ('UPDATE','DELETE'):
            c.exec_driver_sql(f"CREATE OR REPLACE TRIGGER iris2_correction_no_{operation.lower()} BEFORE {operation} ON customer_correction_event FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='IRIS2 correction history is append-only'")
        if inspect(c).has_table('iris2_database_revision'):
            c.exec_driver_sql("INSERT IGNORE INTO iris2_database_revision(table_name,revision) VALUES ('tube_plugging_event',0)")
            for operation in ('INSERT','UPDATE','DELETE'):
                c.exec_driver_sql(f"CREATE OR REPLACE TRIGGER iris2_plugging_revision_{operation.lower()} AFTER {operation} ON tube_plugging_event FOR EACH ROW UPDATE iris2_database_revision SET revision=revision+1 WHERE table_name='tube_plugging_event'")
        if inspect(c).has_table('schema_version'):
            c.execute(text('INSERT INTO schema_version(version,applied_at,description) SELECT :version,:now,:description WHERE NOT EXISTS (SELECT 1 FROM schema_version WHERE version=:version)'),
                dict(version=VERSION,now=datetime.now(timezone.utc).replace(tzinfo=None),description='Actual tube plugging completion/cancellation ledger'))
