"""Run the MariaDB integration suite and applicable calculation regressions."""
import json,sys,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
loader=unittest.TestLoader()
suite=unittest.TestSuite([loader.discover(str(ROOT/'tests'))])
for name in ['test_calculation_boundaries','test_import_normalization','test_latest_installation_prediction','test_ml_quality_gates']:
    suite.addTests(loader.loadTestsFromName('iris2.'+name))
started=time.monotonic()
with (ROOT/'reports/mariadb_transition/validation.log').open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'seconds':round(time.monotonic()-started,3),'passed':result.wasSuccessful()}
(ROOT/'reports/mariadb_transition/validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
raise SystemExit(0 if result.wasSuccessful() else 1)
