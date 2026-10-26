"""Copy referenced evidence into iris2 without changing source records."""
import hashlib,json,shutil,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
ROOT=Path(__file__).resolve().parents[1]
PDF=ROOT/'data/pdf_reports';JSON=ROOT/'data/source_json'
PDF.mkdir(parents=True,exist_ok=True);JSON.mkdir(parents=True,exist_ok=True)
mapping={};results=[]

def copy(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if not source.is_file():results.append({'source':str(source),'status':'MISSING'});return
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,destination)
    before=hashlib.sha256(source.read_bytes()).hexdigest();after=hashlib.sha256(destination.read_bytes()).hexdigest()
    if before!=after:raise RuntimeError('Asset hash mismatch')
    mapping[str(source)]=str(destination)
    results.append({'source':str(source),'destination':str(destination),'bytes':destination.stat().st_size,'sha256':after,'status':'COPIED'})

config=load_database_config()
with engine_for(config,'iris2_pdf').connect() as c:
    for path in c.exec_driver_sql('SELECT pdf_path FROM pdf_document_review').scalars():copy(path,PDF/Path(path).name)
with engine_for(config,'iris2').connect() as c:
    for filename,path in c.exec_driver_sql('SELECT source_file,source_path FROM source_document'):
        candidate=Path(path)
        if not candidate.is_file():candidate=Path(r'C:\access\heat\iris\data')/filename
        copy(candidate,JSON/filename)
# Copy governed artifacts only, no original runtime database/configuration.
source=Path(r'C:\access\heat\iris\outputs\ml_implementation')
count=0
if source.is_dir():
    for path in source.rglob('*'):
        if path.is_file() and path.suffix.lower() in {'.json','.md','.csv','.html','.txt'}:
            target=ROOT/'outputs/ml_implementation'/path.relative_to(source)
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target);count+=1
(ROOT/'data/asset_path_map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'reports/mariadb_transition/assets.json').write_text(json.dumps({'files':results,'governed_artifact_files':count},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'copied':sum(x['status']=='COPIED' for x in results),'missing':sum(x['status']=='MISSING' for x in results),'artifact_files':count,'bytes':sum(x.get('bytes',0) for x in results)}))
