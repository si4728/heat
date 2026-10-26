from __future__ import annotations

import os
import re
from collections import OrderedDict
from contextlib import nullcontext
from threading import RLock
from typing import Any

from .model_config import LocalModelSpec, LocalRuntimeConfig


def remove_thinking_blocks(text: str) -> str:
    return re.sub(
        r"<think>.*?</think>\s*", "", str(text or ""), flags=re.IGNORECASE | re.DOTALL
    ).strip()


class LocalLlmClient:
    """Lazy, process-local llama.cpp client with a bounded model cache.

    The class contains no HTTP client and accepts only model specs that already
    passed the ``llama_cpp`` provider allowlist in ``model_config``.
    """

    def __init__(self, config: LocalRuntimeConfig) -> None:
        self.config = config
        self._models: OrderedDict[str, Any] = OrderedDict()
        self._lock = RLock()

    def generate(
        self,
        prompt: str,
        *,
        model_key: str | None = None,
        system_prompt: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        prompt = str(prompt or "").strip()
        if not prompt:
            raise ValueError("Prompt is required")
        if not 0 <= float(temperature) <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if int(max_tokens) <= 0:
            raise ValueError("max_tokens must be positive")
        key = str(model_key or self.config.default_model_key).strip()
        try:
            spec = self.config.models[key]
        except KeyError as exc:
            raise ValueError(f"Unknown local model key: {key}") from exc

        lock_context = self._lock if self.config.serialize_requests else nullcontext()
        with lock_context:
            llm, cache_key = self._load_model(spec)
            try:
                response = llm.create_chat_completion(
                    messages=[
                        {
                            "role": "system",
                            "content": system_prompt
                            or "검증된 입력 데이터만 사용해 한국어로 정확하게 답변한다.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=float(temperature),
                    max_tokens=int(max_tokens),
                )
                content = response["choices"][0]["message"]["content"]
                return remove_thinking_blocks(content)
            finally:
                if not self.config.keep_loaded:
                    self._unload(cache_key)

    def close(self) -> None:
        with self._lock:
            for key in list(self._models):
                self._unload(key)

    def _load_model(self, spec: LocalModelSpec) -> tuple[Any, str]:
        if not spec.model_path.is_file():
            raise FileNotFoundError(f"Local model file not found: {spec.model_path}")
        cache_key = f"{spec.model_path}::n_ctx={spec.llama_n_ctx}"
        if self.config.keep_loaded and cache_key in self._models:
            llm = self._models.pop(cache_key)
            self._models[cache_key] = llm
            return llm, cache_key
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise RuntimeError(
                "llama-cpp-python is required; install llm_integration/requirements.txt"
            ) from exc
        llm = Llama(
            model_path=str(spec.model_path),
            n_ctx=spec.llama_n_ctx,
            n_threads=int(os.getenv("LLAMA_N_THREADS", "8")),
            n_batch=int(os.getenv("LLAMA_N_BATCH", "512")),
            n_gpu_layers=int(os.getenv("LLAMA_N_GPU_LAYERS", "0")),
            verbose=False,
        )
        if self.config.keep_loaded:
            self._models[cache_key] = llm
            self._enforce_cache_limit()
        return llm, cache_key

    def _enforce_cache_limit(self) -> None:
        while len(self._models) > self.config.max_loaded_models:
            oldest_key = next(iter(self._models))
            self._unload(oldest_key)

    def _unload(self, cache_key: str) -> None:
        llm = self._models.pop(cache_key, None)
        if llm is None:
            return
        close = getattr(llm, "close", None)
        if callable(close):
            close()
