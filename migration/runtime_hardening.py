"""Explicit runtime compatibility improvements after live workflow tests."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
for schema in ['iris2','iris2_test_transition']:
    with engine_for(load_database_config(admin=True),schema).begin() as connection:
        connection.exec_driver_sql('ALTER TABLE tube_lifecycle_event MODIFY event_type VARCHAR(128) NOT NULL')
print('Expanded lifecycle event codes without truncating data')
