"""Run the regression suites used by the complete customer request audit."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))


def main():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pattern in ('test_text_to_sql*.py', 'test_customer*.py', 'test_plugging_web.py',
                    'test_sample_wall_loss.py', 'test_life_dashboard.py', 'test_short_term_corrosion.py',
                    'test_model_queue.py', 'test_access_audit.py', 'test_inspection_lifecycle.py',
                    'test_current_measurements.py', 'test_review_followups_mariadb.py'):
        suite.addTests(loader.discover(str(ROOT / 'tests'), pattern=pattern))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
