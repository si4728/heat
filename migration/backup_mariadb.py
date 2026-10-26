"""Create a consistent logical backup without putting credentials on the command line."""
import datetime,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
ROOT=Path(__file__).resolve().parents[1]
config=load_database_config(admin=True)
backup=ROOT/"backups"/("mariadb_after_migration_"+datetime.datetime.now().strftime("%Y%m%d_%H%M%S")+".sql")
# Protected config directory inherits the restricted ACL.
with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=ROOT/"config",suffix=".cnf",delete=False) as stream:
    options=Path(stream.name)
    for key in ["password","user","host"]:
        if any(character in str(config[key]) for character in ['\n','\r','"','\\']):raise ValueError("Unsupported client option character")
    stream.write('[client]\n'+''.join(f'{key}="{config[key]}"\n' for key in ["host","user","password"])+f'port={config["port"]}\n')
try:
    with backup.open('wb') as target:
        result=subprocess.run([str(ROOT/"runtime/mariadb-11.4.12-winx64/bin/mariadb-dump.exe"),"--defaults-extra-file="+str(options),"--single-transaction","--routines","--triggers","--hex-blob","--databases","iris2","iris2_llm","iris2_ml","iris2_pdf"],stdout=target,stderr=subprocess.PIPE)
    if result.returncode:raise RuntimeError("MariaDB backup failed; credentials suppressed")
finally:options.unlink(missing_ok=True)
report={"file":str(backup),"bytes":backup.stat().st_size,"sha256":hashlib.sha256(backup.read_bytes()).hexdigest(),"restoration_tested":False}
backup.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
