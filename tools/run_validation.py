"""Run integration and calculation tests after checking the local MariaDB."""
import contextlib
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
REPORT_DIR = ROOT / 'reports/mariadb_transition'


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with (REPORT_DIR / 'validation.log').open('w', encoding='utf-8') as stream:
        try:
            # Reuse the guarded iris2-only startup; Flask tests need no web server.
            startup = subprocess.run(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', str(ROOT / 'start_mariadb.ps1')],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                timeout=45,
            )
            stream.write(startup.stdout.decode('utf-8', errors='replace'))
            if startup.returncode:
                raise RuntimeError('Local MariaDB startup failed')
            from iris2.database import database_status
            if not database_status()['schema_ready']:
                raise RuntimeError('MariaDB schema is not ready')
        except Exception:
            # Connection exceptions may contain credentials; keep diagnostics safe.
            stream.write('\nMariaDB preflight failed; tests were not run.\n')
            report = dict(tests=0, failures=0, errors=0, skipped=0, passed=False,
                          phase='preflight',
                          reason='MariaDB unavailable or schema not ready; check local configuration and logs/mariadb-error.log')
        else:
            loader = unittest.TestLoader()
            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                suite = unittest.TestSuite([loader.discover(str(ROOT / 'tests'))])
                for name in ['test_calculation_boundaries', 'test_import_normalization',
                             'test_latest_installation_prediction', 'test_ml_quality_gates']:
                    suite.addTests(loader.loadTestsFromName('iris2.' + name))
                result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
            report = dict(tests=result.testsRun, failures=len(result.failures),
                          errors=len(result.errors), skipped=len(result.skipped),
                          passed=result.wasSuccessful())
    report['seconds'] = round(time.monotonic() - started, 3)
    (REPORT_DIR / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
