"""Migrate iris2-local consistent snapshots into dedicated MariaDB schemas."""
from __future__ import annotations
import datetime, decimal, hashlib, json, sqlite3, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from sqlalchemy import create_engine, URL, MetaData, Text, String, Float, DateTime, Column, Computed, Integer, Index, text, inspect
from sqlalchemy.dialects.mysql import LONGTEXT, DOUBLE, DATETIME
from iris2.db_config import load_database_config

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {"heat_exchanger_db3.db":"iris2", "llm_report_review.db":"iris2_llm", "ml_review_feedback.db":"iris2_ml", "pdf_ocr_review.db":"iris2_pdf"}


def engine_for(config, schema):
    return create_engine(URL.create("mariadb+pymysql", username=config["user"], password=config["password"], host=config["host"], port=config["port"], database=schema, query={"charset":"utf8mb4"}), hide_parameters=True)


def normalized(value, column):
    if value is None: return None
    if isinstance(column.type, DateTime):
        if isinstance(value, str): value = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is not None: value=value.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="microseconds").replace("T", " ")
    if isinstance(column.type, Float): return float(value)
    if isinstance(value, decimal.Decimal): return float(value)
    if isinstance(value, bytes): return {"hex":value.hex()}
    return value


def digest(rows, columns):
    encoded = [json.dumps([normalized(v,c) for v,c in zip(row,columns)], ensure_ascii=False, separators=(",",":")) for row in rows]
    return hashlib.sha256("\n".join(sorted(encoded)).encode()).hexdigest()


def main():
    snapshot = Path((ROOT/"data/import/LATEST.txt").read_text().strip()).resolve()
    if not snapshot.is_relative_to((ROOT/"data/import").resolve()): raise ValueError("Snapshot outside iris2 import directory")
    manifest=json.loads((snapshot/"manifest.json").read_text(encoding="utf-8"))
    config=load_database_config(admin=True)
    admin=engine_for(config, "mysql")
    report=[]
    for item in manifest:
        path=Path(item["snapshot"])
        if not path.resolve().is_relative_to(snapshot): raise ValueError("Invalid snapshot path")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item["sha256"]: raise ValueError("Snapshot changed")
        schema=SCHEMAS[item["file"]]
        with admin.begin() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{schema}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
        engine=engine_for(config,schema)
        source=create_engine("sqlite:///"+path.as_posix())
        metadata=MetaData();metadata.reflect(bind=source,views=False)
        metadata.remove(metadata.tables["sqlite_sequence"]) if "sqlite_sequence" in metadata.tables else None
        raw=sqlite3.connect(path.as_uri()+"?mode=ro",uri=True)
        all_rows={name:raw.execute(f'SELECT * FROM "{name}"').fetchall() for name in metadata.tables}
        source_names={name:[row[1] for row in raw.execute(f'PRAGMA table_info("{name}")')] for name in metadata.tables}
        raw.close()
        for table in metadata.tables.values():
            indexed={c.name for c in table.primary_key.columns}
            indexed.update(c.name for idx in table.indexes for c in idx.columns)
            for constraint in table.constraints:
                if constraint.__class__.__name__=="UniqueConstraint": indexed.update(c.name for c in constraint.columns)
            for col in table.columns:
                if isinstance(col.type,Text):
                    if col.name in indexed:
                        offset=source_names[table.name].index(col.name)
                        length=max([len(str(row[offset])) for row in all_rows[table.name] if row[offset] is not None]+[191])
                        col.type=String(length)
                    else: col.type=LONGTEXT()
                elif isinstance(col.type,Float): col.type=DOUBLE()
                elif isinstance(col.type,DateTime): col.type=DATETIME(fsp=6)
            table.dialect_options["mysql"]["engine"]="InnoDB"
            table.dialect_options["mysql"]["charset"]="utf8mb4"
            table.dialect_options["mysql"]["collate"]="utf8mb4_bin"
            for idx in list(table.indexes):
                if idx.dialect_options["sqlite"].get("where") is None:continue
                table.indexes.remove(idx)
                if idx.name=="uq_organization_plant_code":
                    col=Column("plant_code_unique",String(100),Computed("CASE WHEN kind='PLANT' THEN code ELSE NULL END",persisted=True))
                elif idx.name=="uq_current_spec_revision":
                    col=Column("current_exchanger_unique",Integer,Computed("CASE WHEN is_current=1 THEN heat_exchanger_id ELSE NULL END",persisted=True))
                elif idx.name=="uq_tube_layout_approved_bundle":
                    col=Column("approved_bundle_unique",Integer,Computed("CASE WHEN revision_status='APPROVED' THEN bundle_id ELSE NULL END",persisted=True))
                elif idx.name=="uq_inspection_plan_completed_inspection":
                    Index(idx.name,table.c.completed_inspection_id,unique=True)
                    continue
                else: raise ValueError("Unknown partial index "+idx.name)
                table.append_column(col);Index(idx.name,col,unique=True)
        with engine.connect() as conn:
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
            metadata.create_all(conn);conn.commit()
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1");conn.commit()
        results=[]
        with engine.begin() as conn:
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
            for table in metadata.tables.values():
                names=source_names[table.name]; columns=[table.c[name] for name in names]
                rows=all_rows[table.name]
                quote=", ".join('`'+name+'`' for name in names)
                current=conn.exec_driver_sql(f"SELECT {quote} FROM `{table.name}`").fetchall()
                if current:
                    if len(current)!=len(rows) or digest(current,columns)!=digest(rows,columns):
                        raise ValueError("Nonmatching existing data: "+schema+"."+table.name)
                elif rows:
                    sql=f"INSERT INTO `{table.name}` ({quote}) VALUES ("+", ".join(["%s"]*len(names))+")"
                    prepared=[tuple(normalized(value,column) if isinstance(column.type,DateTime) else value for value,column in zip(row,columns)) for row in rows]
                    for offset in range(0,len(prepared),500):conn.exec_driver_sql(sql,prepared[offset:offset+500])
                actual=conn.exec_driver_sql(f"SELECT {quote} FROM `{table.name}`").fetchall()
                source_hash=digest(rows,columns);target_hash=digest(actual,columns)
                if len(actual)!=len(rows) or source_hash!=target_hash:raise ValueError("Data mismatch: "+schema+"."+table.name)
                results.append({"table":table.name,"rows":len(rows),"source_sha256":source_hash,"target_sha256":target_hash,"match":True})
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")
            for table in metadata.tables.values():
                for constraint in table.foreign_key_constraints:
                    local=[e.parent.name for e in constraint.elements];remote=[e.column.name for e in constraint.elements];parent=list(constraint.elements)[0].column.table.name
                    join=" AND ".join(f"c.`{a}`=p.`{b}`" for a,b in zip(local,remote))
                    nonnull=" AND ".join(f"c.`{a}` IS NOT NULL" for a in local)
                    count=conn.exec_driver_sql(f"SELECT COUNT(*) FROM `{table.name}` c LEFT JOIN `{parent}` p ON {join} WHERE {nonnull} AND p.`{remote[0]}` IS NULL").scalar()
                    if count:raise ValueError("Orphan reference: "+table.name)
            for obj in item['objects']:
                if obj['type']=='view':
                    conn.exec_driver_sql(obj['sql'].replace('CREATE VIEW','CREATE OR REPLACE VIEW',1))
        report.append({"source":item["file"],"schema":schema,"tables":results,"foreign_key_errors":0,"triggers_pending":[o['name'] for o in item['objects'] if o['type']=='trigger']})
        source.dispose();engine.dispose()
        (snapshot/"migration_result.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"schema":schema,"tables":len(results),"rows":sum(x['rows'] for x in results),"all_values_match":True}),flush=True)
    with admin.begin() as conn:
        for schema in SCHEMAS.values():
            for host in ['localhost','127.0.0.1']:
                conn.exec_driver_sql(f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{schema}`.* TO 'iris2_app'@'{host}'")
    print("All snapshot data migrated and reconciled. Business application cutover is not performed.")


if __name__=="__main__": main()
