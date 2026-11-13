"""Run current IRIS2 regression tests in separate local-venv processes.

Unported SQLite suites are reported explicitly, never counted as passing.
Writable workflow tests require an existing, separately restored test schema.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
LEGACY={
    'test_app.py':'Archived fixture reads the separate iris application',
    'test_iris_v2.py':'SQLite fixtures do not select an isolated MariaDB schema',
    'test_server_settings.py':'Archived separate-iris launcher fixture',
    'test_export_concurrency.py':'Imports archived test_app fixtures',
    'test_organization_codes.py':'Imports archived test_app fixtures',
    'test_backup_manager.py':'SQLite backup/restore assumptions; current coverage: tests/test_backup_automation.py',
    'test_ml_governance.py':'Temporary SQLite selector not supported by MariaDB runtime',
    'test_ml_operations.py':'Temporary SQLite selector not supported by MariaDB runtime',
    'test_ml_pipeline.py':'Temporary SQLite selector not supported by MariaDB runtime',
    'test_ml_review.py':'Temporary SQLite selector not supported by MariaDB runtime',
    'test_ml_review_feedback.py':'Temporary SQLite feedback store requires porting',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workflow-schema',help='Existing iris2_test_* snapshot for writable workflow tests')
    parser.add_argument('--output',type=Path,default=ROOT/'tmp/full-validation/current')
    args=parser.parse_args()
    if Path(sys.executable).resolve()!= (ROOT/'.venv/Scripts/python.exe').resolve():
        parser.error('Use iris2/.venv/Scripts/python.exe')
    output=args.output.resolve()
    if not output.is_relative_to(ROOT):parser.error('Output must stay within iris2')
    if args.workflow_schema and not re.fullmatch(r'iris2_test_[a-z0-9_]+',args.workflow_schema):
        parser.error('Workflow schema must be an isolated iris2_test_* target')
    output.mkdir(parents=True,exist_ok=True)
    tracked=subprocess.run(['git','ls-files','*.py'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.splitlines()
    syntax_errors=[]
    for name in tracked:
        try:ast.parse((ROOT/name).read_text(encoding='utf-8-sig'),filename=name)
        except (SyntaxError,UnicodeError) as exc:syntax_errors.append(dict(file=name,error=type(exc).__name__))
    environment=dict(os.environ,PYTHONPATH=str(ROOT.parent),PYTHONIOENCODING='utf-8')
    if args.workflow_schema:environment['IRIS2_TEST_SCHEMA']=args.workflow_schema
    else:environment.pop('IRIS2_TEST_SCHEMA',None)
    paths=sorted([*ROOT.glob('test_*.py'),*ROOT.joinpath('tests').glob('test_*.py'),
                  *ROOT.joinpath('llm_integration/tests').glob('test_*.py')])
    results=[]
    for path in paths:
        relative=path.relative_to(ROOT)
        reason=LEGACY.get(str(relative))
        if relative==Path('tests/test_mariadb_workflows.py') and not args.workflow_schema:
            reason='No isolated writable workflow schema supplied'
        if reason:
            record=dict(file=str(relative),status='NOT_PORTED' if path.name in LEGACY else 'NOT_RUN',reason=reason)
        else:
            module='iris2.'+'.'.join(relative.with_suffix('').parts)
            start=time.monotonic()
            try:
                process=subprocess.run([sys.executable,'-m','unittest',module],cwd=ROOT,env=environment,
                    capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                logs=process.stdout+'\n'+process.stderr
                (output/(str(relative).replace('\\','_').replace('/','_')+'.txt')).write_text(logs,encoding='utf-8')
                total=re.search(r'Ran (\d+) tests?',logs)
                skipped=re.search(r'skipped=(\d+)',logs)
                record=dict(file=str(relative),status='PASS' if process.returncode==0 else 'FAIL',
                    tests=int(total[1]) if total else 0,skipped=int(skipped[1]) if skipped else 0,
                    elapsed_seconds=round(time.monotonic()-start,2))
            except subprocess.TimeoutExpired:
                record=dict(file=str(relative),status='TIMEOUT',tests=0,elapsed_seconds=180)
        results.append(record)
        print(json.dumps(record),flush=True)
        report=dict(python_files_checked=len(tracked),syntax_errors=syntax_errors,results=results)
        (output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    failed=[r for r in results if r['status'] in ('FAIL','TIMEOUT')]
    summary=dict(tests=sum(r.get('tests',0) for r in results),failed_modules=len(failed),
        not_ported_modules=sum(r['status']=='NOT_PORTED' for r in results),syntax_errors=len(syntax_errors))
    print(json.dumps(summary),flush=True)
    return int(bool(failed or syntax_errors))


if __name__=='__main__':raise SystemExit(main())
