"""Private logical backups and verified isolated restore targets."""
from __future__ import annotations
import datetime,hashlib,json,re,subprocess,tempfile,zipfile
from contextlib import contextmanager
from pathlib import Path
from .db_config import APP_DIR,load_database_config
from .migration.migrate_all import engine_for

SCHEMAS=('iris2','iris2_llm','iris2_ml','iris2_pdf')
BIN=APP_DIR/'runtime/mariadb-11.4.12-winx64/bin'


@contextmanager
def client_options():
    config=load_database_config(admin=True)
    if config['port']!=3307 or config['host'] not in {'127.0.0.1','localhost'}:
        raise ValueError('Local MariaDB administration requires the iris2 instance at port 3307')
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=APP_DIR/'config',suffix='.cnf',delete=False) as stream:
        path=Path(stream.name)
        stream.write('[client]\n')
        for key in ['host','user','password','port']:
            value=str(config[key]).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','\\r')
            stream.write(f'{key}="{value}"\n')
    try:yield path
    finally:path.unlink(missing_ok=True)


def configured_schema_roles():
    from .dbapi import load_database_config_schemas
    mapping=load_database_config_schemas()
    from .dbapi import SCHEMAS as selectors
    config=load_database_config()
    roles={canonical:mapping.get(selector,canonical) for selector,canonical in selectors.items()}
    if roles['iris2']!=config['name']:raise ValueError('Primary database and schema mapping disagree')
    if len(set(roles.values()))!=4 or any(not re.fullmatch(r'iris2[a-zA-Z0-9_]{0,59}',name) for name in roles.values()):
        raise ValueError('Invalid or duplicate configured schema names')
    admin=load_database_config(admin=True)
    if (admin['host'],admin['port'])!=(config['host'],config['port']):raise ValueError('Application and backup administrator use different servers')
    return roles


def _normalized_definition(value,aliases):
    for actual,canonical in sorted(aliases.items(),key=lambda item:-len(item[0])):
        value=value.replace('`'+actual+'`.','`'+canonical+'`.')
    return value


def schema_fingerprint(schema,aliases=None):
    if not re.fullmatch(r'iris2[a-zA-Z0-9_]{0,59}',schema):raise ValueError('Invalid schema name')
    if aliases is None:aliases={actual:canonical for canonical,actual in configured_schema_roles().items()}
    engine=engine_for(load_database_config(admin=True),schema)
    from sqlalchemy import inspect
    results={};definitions={};views={};triggers={}
    try:
        with engine.connect() as connection:
            inspector=inspect(connection)
            tables=inspector.get_table_names();view_names=inspector.get_view_names()
            connection.exec_driver_sql('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
            for name in tables:
                rows=connection.exec_driver_sql(f'SELECT * FROM `{name}`').fetchall()
                encoded=sorted(json.dumps(list(row),ensure_ascii=False,default=str,separators=(',',':')) for row in rows)
                results[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest()}
                ddl=connection.exec_driver_sql(f'SHOW CREATE TABLE `{name}`').first()[1]
                definitions[name]=hashlib.sha256(_normalized_definition(ddl,aliases).encode()).hexdigest()
            for name in view_names:
                ddl=connection.exec_driver_sql(f'SHOW CREATE VIEW `{name}`').first()[1]
                rows=connection.exec_driver_sql(f'SELECT * FROM `{name}`').fetchall()
                encoded=sorted(json.dumps(list(row),ensure_ascii=False,default=str,separators=(',',':')) for row in rows)
                views[name]={'rows':len(rows),'sha256':hashlib.sha256('\n'.join(encoded).encode()).hexdigest(),'definition_sha256':hashlib.sha256(_normalized_definition(ddl,aliases).encode()).hexdigest()}
            for name,body in connection.exec_driver_sql("SELECT trigger_name,action_statement FROM information_schema.triggers WHERE trigger_schema=DATABASE() ORDER BY trigger_name"):
                triggers[name]=hashlib.sha256(_normalized_definition(body,aliases).encode()).hexdigest()
            routines={name:hashlib.sha256(_normalized_definition(body or '',aliases).encode()).hexdigest() for name,body in connection.exec_driver_sql("SELECT routine_name,routine_definition FROM information_schema.routines WHERE routine_schema=DATABASE() ORDER BY routine_name")}
        return {'tables':results,'table_definitions':definitions,'views':views,'triggers':triggers,'routines':routines}
    finally:engine.dispose()


def create_backup(destination):
    destination=Path(destination).resolve()
    if not destination.is_relative_to((APP_DIR/'backups').resolve()):raise ValueError('Backup must be inside iris2/backups')
    destination.parent.mkdir(parents=True,exist_ok=True)
    roles=configured_schema_roles();aliases={actual:canonical for canonical,actual in roles.items()}
    before={canonical:schema_fingerprint(actual,aliases) for canonical,actual in roles.items()}
    partial=destination.with_name(destination.name+'.partial')
    try:
        with tempfile.TemporaryDirectory(dir=APP_DIR/'backups') as temporary:
            sql=Path(temporary)/'database.sql'
            with client_options() as options,sql.open('wb') as output:
                result=subprocess.run([str(BIN/'mariadb-dump.exe'),'--defaults-extra-file='+str(options),'--single-transaction','--routines','--triggers','--hex-blob','--databases',*roles.values()],stdout=output,stderr=subprocess.PIPE,timeout=180)
                if result.returncode:raise RuntimeError('MariaDB dump failed; credentials suppressed')
            after={canonical:schema_fingerprint(actual,aliases) for canonical,actual in roles.items()}
            # Never attach an unrelated live-data baseline to a dump made during writes.
            stable=before==after
            manifest={'format':'iris2-mariadb-backup-v2','schemas':list(roles.values()),'schema_roles':roles,'sql_sha256':hashlib.sha256(sql.read_bytes()).hexdigest(),'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_stable_during_capture':stable,'fingerprints':before if stable else None,'structure':{canonical:{'tables':list(value['tables']),'views':list(value['views']),'triggers':list(value['triggers']),'routines':list(value['routines'])} for canonical,value in before.items()}}
            with zipfile.ZipFile(partial,'w',zipfile.ZIP_DEFLATED) as archive:
                archive.write(sql,'database.sql');archive.writestr('manifest.json',json.dumps(manifest))
            partial.replace(destination)
        return manifest
    finally:partial.unlink(missing_ok=True)


def read_backup_manifest(backup):
    with zipfile.ZipFile(backup) as archive:
        if set(archive.namelist())!={'manifest.json','database.sql'}:raise ValueError('Unexpected backup members')
        manifest=json.loads(archive.read('manifest.json'));sql=archive.read('database.sql')
    if manifest.get('format') not in {'iris2-mariadb-backup-v1','iris2-mariadb-backup-v2'}:raise ValueError('Unrecognized backup')
    roles=manifest.get('schema_roles') or {name:name for name in SCHEMAS}
    if set(roles)!=set(SCHEMAS) or len(set(roles.values()))!=4 or list(roles.values())!=manifest.get('schemas'):
        raise ValueError('Invalid backup schema roles')
    if any(not re.fullmatch(r'iris2[a-zA-Z0-9_]{0,59}',name) for name in roles.values()):raise ValueError('Invalid backup schema names')
    if hashlib.sha256(sql).hexdigest()!=manifest.get('sql_sha256'):raise ValueError('Backup hash mismatch')
    return manifest,roles,sql


def restore_to_isolated_schemas(backup,suffix):
    if not re.fullmatch(r'_(?:restore|test)_[a-z0-9_]{1,32}',suffix):raise ValueError('A dedicated restore/test suffix is required')
    manifest,roles,sql=read_backup_manifest(backup)
    targets={source:canonical+suffix for canonical,source in roles.items()}
    admin=engine_for(load_database_config(admin=True),'mysql')
    try:
        with admin.connect() as connection:
            for target in targets.values():
                if connection.exec_driver_sql('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s',(target,)).scalar():
                    raise ValueError('Restore target already exists; never overwrite it')
    finally:admin.dispose()
    rewritten=[]
    for line in sql.decode('utf-8').splitlines(keepends=True):
        if not line.lstrip().upper().startswith(('INSERT INTO','REPLACE INTO')):
            for source,target in sorted(targets.items(),key=lambda item:-len(item[0])):
                line=line.replace('`'+source+'`','`'+target+'`')
        rewritten.append(line)
    with client_options() as options:
        result=subprocess.run([str(BIN/'mariadb.exe'),'--defaults-extra-file='+str(options),'--binary-mode=1'],input=''.join(rewritten).encode('utf-8'),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=240)
        if result.returncode:
            (APP_DIR/'logs/restore_error.log').write_bytes(result.stderr)
            raise RuntimeError('Restore failed; see private restore error log')
    return targets


def _legacy_structure(sql,roles):
    inventory={canonical:{kind:set() for kind in ['tables','views','triggers','routines']} for canonical in roles}
    inverse={actual:canonical for canonical,actual in roles.items()};current=None
    for line in sql.decode('utf-8').splitlines():
        switch=re.match(r'USE `([^`]+)`;',line)
        if switch:current=inverse.get(switch.group(1))
        if current is None or line.lstrip().startswith(('INSERT INTO','REPLACE INTO')):continue
        table=re.search(r'CREATE TABLE `([^`]+)`',line)
        if table:inventory[current]['tables'].add(table.group(1))
        view=re.search(r'\bVIEW `([^`]+)` AS',line,re.I)
        if view:inventory[current]['views'].add(view.group(1));inventory[current]['tables'].discard(view.group(1))
        trigger=re.search(r'\bTRIGGER\s+`?([a-zA-Z0-9_]+)`?',line,re.I)
        if trigger:inventory[current]['triggers'].add(trigger.group(1))
        routine=re.search(r'\b(?:PROCEDURE|FUNCTION)\s+`?([a-zA-Z0-9_]+)`?',line,re.I)
        if routine:inventory[current]['routines'].add(routine.group(1))
    if any(not value['tables'] for value in inventory.values()):raise ValueError('Cannot establish legacy backup inventory')
    return {canonical:{kind:sorted(names) for kind,names in value.items()} for canonical,value in inventory.items()}


def verify_restored_backup(backup,targets):
    manifest,roles,sql=read_backup_manifest(backup)
    if manifest.get('format')=='iris2-mariadb-backup-v1':manifest['structure']=_legacy_structure(sql,roles)
    if set(targets)!=set(roles.values()):raise ValueError('Restored schema set differs from backup')
    aliases={targets[source]:canonical for canonical,source in roles.items()}
    results={}
    for canonical,source in roles.items():
        target=targets[source]
        if target==source:raise ValueError('Restore verification must not target a live schema')
        actual=schema_fingerprint(target,aliases)
        expected=(manifest.get('fingerprints') or {}).get(canonical)
        if expected is not None:
            if actual!=expected:raise ValueError('Restored data or definition mismatch: '+canonical)
            mode='FULL_DATA_AND_DEFINITIONS'
        else:
            structure=(manifest.get('structure') or {}).get(canonical)
            if not structure:raise ValueError('Legacy backup has no verification baseline; explicit comparison required')
            for kind in ['tables','views','triggers','routines']:
                if sorted(actual[kind])!=sorted(structure[kind]):raise ValueError('Restored object inventory mismatch: '+canonical)
            mode='LEGACY_STRUCTURE_ONLY' if manifest.get('format')=='iris2-mariadb-backup-v1' else 'STRUCTURE_ONLY_SOURCE_WAS_CHANGING'
        results[canonical]={'target':target,'mode':mode,'table_count':len(actual['tables']),'row_count':sum(value['rows'] for value in actual['tables'].values())}
    return results


def grant_restored_application_access(targets):
    """Make a verified standby usable with the existing dedicated application roles."""
    app=load_database_config()
    readonly=load_database_config(path=APP_DIR/'config/database-readonly.conf')
    admin=engine_for(load_database_config(admin=True),'mysql')
    try:
        with admin.begin() as connection:
            for source,target in targets.items():
                if target==source or not re.fullmatch(r'iris2[a-zA-Z0-9_]{0,59}',target):raise ValueError('Invalid standby access target')
                for settings,privileges in [(app,'SELECT,INSERT,UPDATE,DELETE'),(readonly,'SELECT')]:
                    hosts=list(connection.exec_driver_sql("SELECT Host FROM mysql.user WHERE User=%s AND Host IN ('localhost','127.0.0.1')",(settings['user'],)).scalars())
                    if not hosts:raise ValueError('Configured database account does not exist')
                    for host in hosts:connection.exec_driver_sql(f"GRANT {privileges} ON `{target}`.* TO %s@%s",(settings['user'],host))
    finally:admin.dispose()
    for target in targets.values():
        for settings in [app,readonly]:
            engine=engine_for(settings,target)
            try:
                with engine.connect() as connection:
                    connection.exec_driver_sql('SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()').scalar()
                    table=connection.exec_driver_sql("SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_type='BASE TABLE' LIMIT 1").scalar()
                    if table:connection.exec_driver_sql(f'SELECT COUNT(*) FROM `{table}`').scalar()
            finally:engine.dispose()
    return True
