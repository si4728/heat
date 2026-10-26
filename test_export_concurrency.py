from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from iris2 import excel_export
from iris2.iris_v2_database import _shared_session_factory, session_scope


class ExportCacheTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / 'export.db'
        with closing(sqlite3.connect(self.db)) as connection:
            connection.execute('pragma journal_mode=WAL')
            connection.execute('create table source(value text)')
            connection.execute("insert into source values ('before')")
            connection.commit()
        self.calls = 0

    def tearDown(self):
        excel_export.clear_heat_exchanger_export_cache()
        self.temp.cleanup()

    def build(self, path):
        self.calls += 1
        time.sleep(.05)
        with closing(sqlite3.connect(path)) as connection:
            return BytesIO(connection.execute('select value from source').fetchone()[0].encode())

    def test_three_requests_generate_once_with_independent_streams(self):
        with patch.object(excel_export, '_generate_export_workbook', self.build):
            with ThreadPoolExecutor(max_workers=3) as pool:
                results = list(pool.map(excel_export.get_heat_exchanger_export, [self.db]*3))
        self.assertEqual(self.calls, 1)
        self.assertEqual([r.read() for r in results], [b'before']*3)
        self.assertEqual(len({id(r) for r in results}), 3)

    def test_external_commits_invalidate_cache_and_failure_does_not_serve_stale_data(self):
        with patch.object(excel_export, '_generate_export_workbook', self.build):
            self.assertEqual(excel_export.get_heat_exchanger_export(self.db).read(), b'before')
            with closing(sqlite3.connect(self.db)) as connection:
                connection.execute("update source set value='after'")
                connection.commit()
            with patch.object(excel_export, '_generate_export_workbook', side_effect=RuntimeError('generation failed')):
                with self.assertRaises(RuntimeError):
                    excel_export.get_heat_exchanger_export(self.db)
            self.assertEqual(excel_export.get_heat_exchanger_export(self.db).read(), b'after')
        self.assertEqual(self.calls, 2)

    def test_session_engine_reused_and_sqlite_settings_retained(self):
        from sqlalchemy import text
        with session_scope(self.db) as session:
            first = session.get_bind()
            self.assertEqual(session.execute(text('pragma foreign_keys')).scalar(), 1)
            self.assertEqual(session.execute(text('pragma busy_timeout')).scalar(), 30000)
        with session_scope(self.db) as session:
            self.assertIs(session.get_bind(), first)

    def test_commit_during_generation_prevents_caching_old_snapshot(self):
        def changing_build(path):
            result = self.build(path)
            if self.calls == 1:
                with closing(sqlite3.connect(path)) as connection:
                    connection.execute("update source set value='after'")
                    connection.commit()
            return result
        with patch.object(excel_export, '_generate_export_workbook', changing_build):
            self.assertEqual(excel_export.get_heat_exchanger_export(self.db).read(), b'before')
            self.assertEqual(excel_export.get_heat_exchanger_export(self.db).read(), b'after')
            self.assertEqual(excel_export.get_heat_exchanger_export(self.db).read(), b'after')
        self.assertEqual(self.calls, 2)

    def test_export_queries_remain_on_one_snapshot_during_external_commit(self):
        from iris2 import test_app as fixtures
        clone = Path(self.temp.name) / 'snapshot.db'
        with closing(sqlite3.connect(fixtures.TEST_DB)) as source:
            with closing(sqlite3.connect(clone)) as target:
                source.backup(target)
        from iris2.iris_v2_database import init_v2_db
        init_v2_db(clone)
        with closing(sqlite3.connect(clone)) as connection:
            equipment_id, old_name = connection.execute('select equipment_id,equipment_name from equipment limit 1').fetchone()
        original = excel_export._rows
        observations = []
        def checked_rows(connection, sql):
            result = original(connection, sql)
            if not observations:
                with closing(sqlite3.connect(clone)) as writer:
                    writer.execute('update equipment set equipment_name=? where equipment_id=?', ('changed during export',equipment_id))
                    writer.commit()
            observations.append((connection.connection.driver_connection.in_transaction,
                                 connection.exec_driver_sql('select equipment_name from equipment where equipment_id=?', (equipment_id,)).scalar()))
            return result
        with patch.object(excel_export, '_rows', checked_rows):
            excel_export.build_heat_exchanger_export(clone)
        self.assertEqual(observations, [(True, old_name)] * 5)
        with closing(sqlite3.connect(clone)) as connection:
            self.assertEqual(connection.execute('select equipment_name from equipment where equipment_id=?', (equipment_id,)).fetchone()[0], 'changed during export')


if __name__ == '__main__':
    unittest.main()
