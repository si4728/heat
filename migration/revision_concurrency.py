"""Serialize temporal revisions using a separate indexed interval guard table."""
from pathlib import Path
import sys,re
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
for schema in ['iris2','iris2_test_transition']:
    with engine_for(load_database_config(admin=True),schema).begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS iris2_spec_revision_guard (spec_revision_id INT PRIMARY KEY, heat_exchanger_id INT NOT NULL, effective_from DATETIME(6), effective_to DATETIME(6), INDEX ix_guard_exchanger(heat_exchanger_id)) ENGINE=InnoDB")
        conn.exec_driver_sql("INSERT INTO iris2_spec_revision_guard SELECT spec_revision_id,heat_exchanger_id,effective_from,effective_to FROM heat_exchanger_spec_revision ON DUPLICATE KEY UPDATE effective_from=VALUES(effective_from),effective_to=VALUES(effective_to)")
        for trigger in ['trg_spec_revision_validate_insert','trg_spec_revision_validate_update']:
            statement=conn.exec_driver_sql('SHOW CREATE TRIGGER `'+trigger+'`').mappings().first()['SQL Original Statement']
            if 'DECLARE overlap_count' not in statement:
                statement=statement.replace('DECLARE locked_exchanger INT;','DECLARE locked_exchanger INT; DECLARE overlap_count BIGINT;')
            def locking_query(match):
                query=match.group(1).replace('SELECT 1 FROM heat_exchanger_spec_revision','SELECT COUNT(*) INTO overlap_count FROM iris2_spec_revision_guard',1)
                return query+' FOR UPDATE; IF overlap_count > 0 THEN SIGNAL'
            statement=re.sub(r"IF EXISTS \(\s*(SELECT 1 FROM heat_exchanger_spec_revision .*?)\s*\) THEN SIGNAL",locking_query,statement,flags=re.S)
            statement=statement.replace('SELECT COUNT(*) INTO overlap_count FROM heat_exchanger_spec_revision','SELECT COUNT(*) INTO overlap_count FROM iris2_spec_revision_guard')
            statement=re.sub(r'CREATE(?: OR REPLACE)? DEFINER=.*? TRIGGER', 'CREATE OR REPLACE TRIGGER',statement,count=1)
            if not statement.startswith('CREATE OR REPLACE'):statement=statement.replace('CREATE TRIGGER','CREATE OR REPLACE TRIGGER',1)
            conn.exec_driver_sql(statement)
        for operation in ['INSERT','UPDATE']:
            conn.exec_driver_sql(f"CREATE OR REPLACE TRIGGER iris2_spec_guard_{operation.lower()} AFTER {operation} ON heat_exchanger_spec_revision FOR EACH ROW INSERT INTO iris2_spec_revision_guard(spec_revision_id,heat_exchanger_id,effective_from,effective_to) VALUES(NEW.spec_revision_id,NEW.heat_exchanger_id,NEW.effective_from,NEW.effective_to) ON DUPLICATE KEY UPDATE heat_exchanger_id=VALUES(heat_exchanger_id),effective_from=VALUES(effective_from),effective_to=VALUES(effective_to)")
        conn.exec_driver_sql("CREATE OR REPLACE TRIGGER iris2_spec_guard_delete AFTER DELETE ON heat_exchanger_spec_revision FOR EACH ROW DELETE FROM iris2_spec_revision_guard WHERE spec_revision_id=OLD.spec_revision_id")
print('Installed transactional revision interval guards without mutating-table reads')
