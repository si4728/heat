from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iris2.ml.artifacts import ArtifactStore
from iris2.ml.environment import MissingMLDependencies, require_ml_environment
from iris2.ml.governance import build_manifest
from iris2.ml.readonly_db import database_sha256, readonly_connection


class MLReadonlyDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.database = self.data / "test.db"
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO sample(value) VALUES ('original')")
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_connection_is_query_only_and_rejects_all_writes(self) -> None:
        before = database_sha256(self.database)
        with readonly_connection(self.database, data_root=self.data) as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            for statement in (
                "INSERT INTO sample(value) VALUES ('x')",
                "UPDATE sample SET value='x'",
                "DELETE FROM sample",
                "CREATE TABLE forbidden(id INTEGER)",
            ):
                with self.assertRaises(sqlite3.OperationalError):
                    connection.execute(statement)
        self.assertEqual(database_sha256(self.database), before)


class MLArtifactTest(unittest.TestCase):
    def test_artifact_boundary_atomic_write_and_secret_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            data = root / "data"
            data.mkdir()
            store = ArtifactStore(root / "outputs" / "ml_implementation", protected_directories=(data,))
            target = store.write_json("run/stage_1_result.json", {"status": "PASS"})
            self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["status"], "PASS")
            self.assertFalse(list(target.parent.glob("*.tmp")))
            with self.assertRaises(ValueError):
                store.path("../../data/database.db")
            with self.assertRaises(ValueError):
                store.write_json("run/leak.json", {"api_token": "not-exported"})
            with self.assertRaises(ValueError):
                ArtifactStore(data / "ml", protected_directories=(data,))


class MLGovernanceTest(unittest.TestCase):
    def test_manifest_core_is_reproducible_for_same_input_and_seed(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            database = root / "source.db"
            source = root / "model.py"
            source.write_text("MODEL = 1\n", encoding="utf-8")
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE sample(id INTEGER)")
                connection.commit()
            finally:
                connection.close()
            first = build_manifest(database_path=database, dataset_version="v1", sql_version="q1", source_files=(source,), seed=42, settings={"x": 1})
            second = build_manifest(database_path=database, dataset_version="v1", sql_version="q1", source_files=(source,), seed=42, settings={"x": 1})
            self.assertEqual(first["reproducibility_fingerprint"], second["reproducibility_fingerprint"])

    def test_missing_dependency_returns_structured_safe_failure(self) -> None:
        with patch("iris2.ml.environment.importlib.util.find_spec", return_value=None):
            with self.assertRaises(MissingMLDependencies) as caught:
                require_ml_environment(("not-installed",))
        self.assertEqual(caught.exception.as_dict()["code"], "ML_DEPENDENCY_MISSING")


if __name__ == "__main__":
    unittest.main()
