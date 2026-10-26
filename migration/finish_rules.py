"""Translate source revision guards and retain SQLite AUTOINCREMENT high-water marks."""
import json,re,sys,sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for,SCHEMAS
ROOT=Path(__file__).resolve().parents[1]
snapshot=Path((ROOT/"data/import/LATEST.txt").read_text().strip())
manifest=json.loads((snapshot/"manifest.json").read_text(encoding="utf-8"))
config=load_database_config(admin=True)
converted=[]
engine=engine_for(config,"iris2")
with engine.begin() as conn:
    for obj in manifest[0]['objects']:
        if obj['type']!='trigger' or 'validate' not in obj['name']:continue
        sql=obj['sql']
        sql=re.sub(r"julianday\(([A-Za-z_]+\.[a-z_0-9]+)\)",r"\1",sql)
        sql=re.sub(r"julianday\((COALESCE\([^)]*\))\)",r"\1",sql)
        sql=re.sub(r"(NEW\.[a-z_0-9]+) IS NOT (OLD\.[a-z_0-9]+)",r"NOT (\1 <=> \2)",sql)
        sql=re.sub(r"SELECT CASE WHEN\s+(.*?)\s+THEN RAISE\(ABORT, '([^']*)'\)\s*END;",r"IF \1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='\2'; END IF;",sql,flags=re.S)
        if 'RAISE' in sql or 'julianday' in sql:
            (snapshot/'untranslated.sql').write_text(sql)
            raise ValueError('Untranslated trigger')
        lock="DECLARE locked_exchanger INT; SELECT heat_exchanger_id INTO locked_exchanger FROM heat_exchanger WHERE heat_exchanger_id=NEW.heat_exchanger_id FOR UPDATE;"
        sql=sql.replace('BEGIN','FOR EACH ROW BEGIN '+lock,1)
        # Validation subqueries use locking/current reads after the per-exchanger lock.
        if 'insert' in obj['name']:
            fill="""IF NEW.exchanger_code IS NULL THEN
            SET NEW.exchanger_code=COALESCE(
              (SELECT old.exchanger_code FROM heat_exchanger_spec_revision old
               WHERE old.heat_exchanger_id=NEW.heat_exchanger_id AND old.spec_revision_id<>NEW.spec_revision_id AND old.exchanger_code IS NOT NULL ORDER BY old.revision_no DESC LIMIT 1),
              (SELECT e.equipment_code FROM heat_exchanger h JOIN equipment e ON e.equipment_id=h.equipment_id WHERE h.heat_exchanger_id=NEW.heat_exchanger_id));
            END IF;"""
            sql=sql.rsplit('END',1)[0]+fill+' END'
        sql=re.sub(r'\bold\b','prior_revision',sql)
        sql=sql.replace('CREATE TRIGGER','CREATE OR REPLACE TRIGGER',1)
        conn.exec_driver_sql(sql);converted.append(obj['name'])
    view=next(o for o in manifest[0]['objects'] if o['type']=='view')
    count=conn.exec_driver_sql('SELECT COUNT(*) FROM v_heat_exchanger_spec_summary').scalar()
    # Immutable data rejection must work without persisting a change.
    rejected=False
    transaction=conn.begin_nested()
    try:
        conn.exec_driver_sql("UPDATE heat_exchanger_spec_revision SET revision_code=CONCAT(revision_code,'_MIGRATION_TEST') ORDER BY spec_revision_id LIMIT 1")
    except Exception as exc:
        if 'immutable' not in str(exc):raise
        rejected=True
    finally:transaction.rollback()
    if not rejected:raise ValueError('Immutable revision guard did not reject update')
for item in manifest:
    src=sqlite3.connect(Path(item['snapshot']).as_uri()+'?mode=ro',uri=True)
    exists=src.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sqlite_sequence'").fetchone()[0]
    if exists:
        with engine_for(config,SCHEMAS[item['file']]).begin() as conn:
            for table,seq in src.execute('SELECT name,seq FROM sqlite_sequence'):
                if table not in item['tables']:continue
                conn.exec_driver_sql(f'ALTER TABLE `{table}` AUTO_INCREMENT={int(seq)+1}')
    src.close()
result={'triggers_created':converted,'legacy_fill_trigger':'MERGED_INTO_BEFORE_INSERT','view_rows':count,'immutable_guard_test':'PASS','sqlite_autoincrement_high_watermarks':'PRESERVED','concurrent_revision_uat':'PENDING'}
(snapshot/'rules_result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
