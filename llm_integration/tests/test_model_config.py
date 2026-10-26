from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iris2.llm_integration.local_llm import remove_thinking_blocks
from iris2.llm_integration.model_config import load_local_runtime_config


class LocalLlmConfigurationTest(unittest.TestCase):
    def _write_config(self, payload: dict) -> Path:
        directory = Path(self.addCleanupDirectory.name)
        path = directory / "models.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def setUp(self) -> None:
        self.addCleanupDirectory = tempfile.TemporaryDirectory()
        self.addCleanup(self.addCleanupDirectory.cleanup)

    def test_local_llama_cpp_configuration_loads(self):
        path = self._write_config({
            "default_model_key": "report",
            "models": [{
                "key": "report",
                "label": "Report",
                "provider": "llama_cpp",
                "model_name": "approved-model",
                "model_path": "models/report.gguf",
                "llama_n_ctx": 4096,
            }],
            "local_llm_cache": {
                "mode": "keep_loaded",
                "max_loaded_models": 1,
                "serialize_requests": True,
            },
        })
        config = load_local_runtime_config(path)
        self.assertEqual(config.default_model_key, "report")
        self.assertEqual(config.models["report"].llama_n_ctx, 4096)
        self.assertEqual(
            config.models["report"].model_path,
            (path.parent / "models" / "report.gguf").resolve(),
        )
        self.assertTrue(config.serialize_requests)

    def test_external_provider_is_rejected(self):
        path = self._write_config({
            "default_model_key": "cloud",
            "models": [{
                "key": "cloud",
                "provider": "gemini",
                "model_name": "external-model",
                "model_path": "unused",
            }],
        })
        with self.assertRaisesRegex(ValueError, "provider is prohibited"):
            load_local_runtime_config(path)

    def test_thinking_blocks_are_removed(self):
        self.assertEqual(
            remove_thinking_blocks("<think>internal reasoning</think>검사 결과 요약"),
            "검사 결과 요약",
        )


if __name__ == "__main__":
    unittest.main()
