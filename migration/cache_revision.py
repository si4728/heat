"""Transactional per-table export cache invalidation, including external SQL writers."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
from sqlalchemy import inspect
engine=engine_for(load_database_config(admin=True),'iris2')
tables=[name for name in inspect(engine).get_table_names() if name!='iris2_database_revision']
with engine.begin() as connection:
    connection.exec_driver_sql("CREATE TABLE IF NOT EXISTS iris2_database_revision (table_name VARCHAR(100) PRIMARY KEY, revision BIGINT UNSIGNED NOT NULL DEFAULT 0) ENGINE=InnoDB")
    for index,name in enumerate(tables):
        connection.exec_driver_sql("INSERT INTO iris2_database_revision(table_name,revision) VALUES (%s,0) ON DUPLICATE KEY UPDATE table_name=VALUES(table_name)",(name,))
        for operation in ['INSERT','UPDATE','DELETE']:
            trigger='iris2_cache_'+str(index)+'_'+operation.lower()
            connection.exec_driver_sql(f"CREATE OR REPLACE TRIGGER `{trigger}` AFTER {operation} ON `{name}` FOR EACH ROW UPDATE iris2_database_revision SET revision=revision+1 WHERE table_name='{name}'")
print(f'Installed transactional revision triggers for {len(tables)} tables')
