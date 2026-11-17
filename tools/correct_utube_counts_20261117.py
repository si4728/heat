"""Preview or apply only the three approved physical U-tube count corrections."""
import argparse,json,re,sys
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from sqlalchemy.orm import Session
from iris2.db_config import load_database_config
from iris2.migration.migrate_all import engine_for
from iris2.application.utube_correction import correct_counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    current=load_database_config()['name'];schema=args.schema or current
    if schema!=current and not re.fullmatch(r'iris2_test_[a-z0-9_]+',schema):
        parser.error('Only the configured application schema or an isolated iris2_test_* target is allowed')
    target=Path(__file__).resolve().parents[1]/'tmp/review_20261117'
    target.mkdir(parents=True,exist_ok=True)
    with Session(engine_for(load_database_config(admin=True),schema)) as session, session.begin():
        preview=correct_counts(session)
        report=dict(schema=schema,applied=args.apply,preview=preview)
        path=target/f'utube-{schema}-{datetime.now():%Y%m%d%H%M%S%f}.json'
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        if args.apply:
            report['result']=correct_counts(session,apply=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(schema=schema,applied=args.apply,changes=sum(i['changed'] for i in preview),report=str(path))))


if __name__=='__main__':main()
