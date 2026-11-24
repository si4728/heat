"""Plan/apply the reviewed customer corrections and plugging ledger migration."""
import argparse
import json
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from iris2.application.customer_corrections_20261124 import correct
from iris2.db_config import load_database_config
from iris2.hx_configuration import PDF_REPORT_DIR
from iris2.migration.migrate_all import engine_for
from iris2.migration.plugging_operations import apply_migration


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--schema')
    p.add_argument('--backup',type=Path)
    p.add_argument('--output',type=Path,default=Path('reports/customer-completion-20261124/corrections.json'))
    args=p.parse_args()
    app=load_database_config();admin=load_database_config(admin=True)
    schema=args.schema or app['name']
    if (admin['host'],admin['port'])!=(app['host'],app['port']) or app['port']!=3307 or app['host'] not in ('localhost','127.0.0.1'):
        raise ValueError('Only the configured local iris2 MariaDB is permitted')
    if schema!=app['name'] and not re.fullmatch(r'iris2_test_customer_[0-9a-f]{12}',schema):
        raise ValueError('Unsupported correction target')
    if args.apply and schema==app['name']:
        if not args.backup or not args.backup.resolve().is_relative_to((Path(__file__).resolve().parents[1]/'backups').resolve()) or not args.backup.is_file() or args.backup.stat().st_size<1024:
            raise ValueError('A fresh iris2-local backup is required before production corrections')
    engine=engine_for(admin,schema)
    try:
        plan=correct(engine,PDF_REPORT_DIR,apply=False)
        if args.apply:
            apply_migration(engine)
            applied=correct(engine,PDF_REPORT_DIR,apply=True)
            if correct(engine,PDF_REPORT_DIR,apply=False):raise RuntimeError('Correction replay is not empty')
        else:applied=[]
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(dict(schema=schema,applied=args.apply,plan=plan,changes=applied),ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(applied=args.apply,planned_fields=len(plan),changed_fields=len(applied),report=str(args.output))))
    finally:engine.dispose()

if __name__=='__main__':main()
