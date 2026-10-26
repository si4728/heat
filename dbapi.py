"""MariaDB-only DB-API for existing parameterized analysis queries.

Logical legacy filenames select a configured MariaDB schema; no file is opened.
Only qmark parameter binding is adapted. SQLite SQL is not silently emulated.
"""
from __future__ import annotations
import datetime, re
from pathlib import Path
from urllib.parse import unquote, urlparse
import pymysql
from .db_config import APP_DIR, load_database_config

SCHEMAS={"heat_exchanger_db3.db":"iris2","ml_review_feedback.db":"iris2_ml","llm_report_review.db":"iris2_llm","pdf_ocr_review.db":"iris2_pdf"}
Error=pymysql.Error
DatabaseError=pymysql.DatabaseError
OperationalError=pymysql.OperationalError
IntegrityError=pymysql.IntegrityError


def schema_for(selector):
    raw=str(selector)
    path=unquote(raw.split('?',1)[0])
    if path.startswith('file:'):path=path[5:].lstrip('/')
    resolved=Path(path).resolve()
    if not resolved.is_relative_to(APP_DIR) or resolved.name not in SCHEMAS:
        raise ValueError("Unknown or external iris2 database selector")
    base = load_database_config()["name"]
    configured = load_database_config_schemas()
    return configured.get(resolved.name, base if resolved.name=="heat_exchanger_db3.db" else SCHEMAS[resolved.name])


def load_database_config_schemas():
    import configparser
    from .db_config import APP_CONFIG
    parser=configparser.ConfigParser(interpolation=None)
    parser.read(APP_CONFIG,encoding='utf-8-sig')
    values=dict(parser['schemas']) if parser.has_section('schemas') else {}
    if any(key not in SCHEMAS or not value.startswith('iris2') for key,value in values.items()):
        raise ValueError('Invalid MariaDB schema mapping')
    return values


def exists(selector):
    schema_for(selector)
    return True


class Row:
    def __init__(self,names,values):self._names=names;self._values=values
    def keys(self):return self._names
    def __getitem__(self,key):return self._values[key] if isinstance(key,(int,slice)) else self._values[self._names.index(key)]
    def __iter__(self):return iter(self._values)
    def __len__(self):return len(self._values)


class Result:
    def __init__(self,cursor):self.cursor=cursor;self.lastrowid=cursor.lastrowid;self.rowcount=cursor.rowcount
    @property
    def description(self):return self.cursor.description
    def _row(self,values):
        if values is None:return None
        values=tuple(v.isoformat(sep=' ') if isinstance(v,datetime.datetime) else v.isoformat() if isinstance(v,datetime.date) else v for v in values)
        return Row(tuple(d[0] for d in self.cursor.description),values)
    def fetchone(self):return self._row(self.cursor.fetchone())
    def fetchall(self):return [self._row(row) for row in self.cursor.fetchall()]
    def fetchmany(self,size=1):return [self._row(row) for row in self.cursor.fetchmany(size)]
    def __iter__(self):
        while True:
            row=self.fetchone()
            if row is None:return
            yield row
    def close(self):self.cursor.close()


def bind_qmarks(sql):
    # Respect quoted literals and escaped quotes; do not interpolate values into SQL.
    result=[];quote=None;index=0
    while index<len(sql):
        char=sql[index]
        if quote:
            result.append(char)
            if char=='\\' and index+1<len(sql):index+=1;result.append(sql[index])
            elif char==quote:
                if index+1<len(sql) and sql[index+1]==quote:index+=1;result.append(sql[index])
                else:quote=None
        elif char in "'\"`":quote=char;result.append(char)
        elif char=='?':result.append('%s')
        else:result.append(char)
        index+=1
    return ''.join(result)


class Connection:
    row_factory=Row
    def __init__(self,selector,readonly=False):
        self.schema=schema_for(selector)
        self.readonly=readonly
        config=load_database_config(path=APP_DIR/'config/database-readonly.conf') if readonly else load_database_config()
        self.raw=pymysql.connect(host=config['host'],port=config['port'],user=config['user'],password=config['password'],database=self.schema,charset=config['charset'],autocommit=False,connect_timeout=5,read_timeout=60)
        if readonly:
            with self.raw.cursor() as cursor:cursor.execute('SET SESSION TRANSACTION READ ONLY')
    def execute(self,sql,parameters=()):
        if re.search(r'\b(PRAGMA|sqlite_master|ON CONFLICT|INSERT OR)\b',sql,re.I):
            raise ValueError('SQLite SQL must be explicitly ported to MariaDB')
        cursor=self.raw.cursor()
        cursor.execute(bind_qmarks(sql.replace("%","%%")) if parameters else sql,tuple(parameters) if parameters else None)
        return Result(cursor)
    def executemany(self,sql,parameters):
        cursor=self.raw.cursor();cursor.executemany(bind_qmarks(sql),parameters);return Result(cursor)
    def require_tables(self,script):
        names=re.findall(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)',script,re.I)
        for name in names:
            if not self.execute('SELECT 1 FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=?',(name,)).fetchone():
                raise RuntimeError('Explicit MariaDB schema migration required: '+name)
    def commit(self):self.raw.commit()
    def rollback(self):self.raw.rollback()
    def close(self):self.raw.close()
    def __enter__(self):return self
    def __exit__(self,kind,value,tb):
        try:self.rollback() if kind else self.commit()
        finally:self.close()


def connect(database, *, uri=False, readonly=False, **kwargs):
    return Connection(database,readonly=readonly or 'mode=ro' in str(database))
