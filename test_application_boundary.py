"""IRIS2 boundary checks independent of obsolete parent packaging tools."""
from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import unittest

from iris2 import hx_configuration as config

APP_DIR=Path(__file__).resolve().parent


class ApplicationBoundaryTest(unittest.TestCase):
    def test_configured_application_paths_stay_under_iris2(self):
        for path in (config.DB_PATH,config.UPLOAD_DIR,config.REPORT_DIR,
                     config.PDF_REPORT_DIR,config.CUMULATIVE_REPORT):
            self.assertTrue(Path(path).resolve().is_relative_to(APP_DIR))

    def test_runtime_assets_stay_under_iris2(self):
        for path in ('server.py','app.py','static/vendor/three/three.min.js'):
            self.assertTrue((APP_DIR/path).is_file(),path)

    def test_active_python_does_not_import_iris(self):
        paths=[APP_DIR/'app.py',APP_DIR/'server.py',*APP_DIR.joinpath('web').rglob('*.py'),
               *APP_DIR.joinpath('application').rglob('*.py'),*APP_DIR.joinpath('domain').rglob('*.py')]
        forbidden=[]
        for path in paths:
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                modules=([a.name for a in node.names] if isinstance(node,ast.Import) else
                         [node.module or ''] if isinstance(node,ast.ImportFrom) and node.level==0 else [])
                if any(name=='iris' or name.startswith('iris.') for name in modules):
                    forbidden.append(str(path.relative_to(APP_DIR)))
        self.assertEqual(forbidden,[])

    def test_private_config_and_runtime_data_are_not_tracked(self):
        tracked=subprocess.run(['git','ls-files','config/database.conf','config/database-admin.conf',
            'config/database-readonly.conf','config/database-text-to-sql.conf',
            'data/*.db','logs/*','backups/*'],cwd=APP_DIR,capture_output=True,text=True,check=True)
        self.assertEqual(tracked.stdout.strip(),'')


if __name__=='__main__':unittest.main()
