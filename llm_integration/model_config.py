from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ALLOWED_PROVIDER = "llama_cpp"


@dataclass(frozen=True)
class LocalModelSpec:
    key: str
    label: str
    provider: str
    model_name: str
    model_path: Path
    llama_n_ctx: int = 8192


@dataclass(frozen=True)
class LocalRuntimeConfig:
    default_model_key: str
    models: dict[str, LocalModelSpec]
    keep_loaded: bool = True
    max_loaded_models: int = 1
    serialize_requests: bool = True


def _positive_int(value: Any, *, field: str, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _model_path(value: Any, config_dir: Path) -> Path:
    text = os.path.expandvars(str(value or "").strip())
    if not text:
        raise ValueError("Local model_path is required")
    path = Path(text)
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()


def load_local_runtime_config(path: str | Path) -> LocalRuntimeConfig:
    """Load an offline-only model configuration.

    Any provider other than ``llama_cpp`` is rejected instead of silently ignored.
    This is the primary boundary preventing cloud providers from entering the IRIS
    deployment configuration.
    """
    config_path = Path(path).resolve()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"LLM configuration not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid LLM configuration JSON: {config_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("LLM configuration root must be an object")

    rows = payload.get("models")
    if not isinstance(rows, list) or not rows:
        raise ValueError("At least one local model must be configured")
    models: dict[str, LocalModelSpec] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"models[{index}] must be an object")
        provider = str(row.get("provider") or "").strip()
        if provider != ALLOWED_PROVIDER:
            raise ValueError(
                f"External or unsupported provider is prohibited: {provider or '(empty)'}"
            )
        key = str(row.get("key") or "").strip()
        model_name = str(row.get("model_name") or "").strip()
        if not key or not model_name:
            raise ValueError(f"models[{index}] requires key and model_name")
        if key in models:
            raise ValueError(f"Duplicate model key: {key}")
        models[key] = LocalModelSpec(
            key=key,
            label=str(row.get("label") or model_name).strip(),
            provider=provider,
            model_name=model_name,
            model_path=_model_path(row.get("model_path"), config_path.parent),
            llama_n_ctx=_positive_int(
                row.get("llama_n_ctx"), field=f"models[{index}].llama_n_ctx", default=8192
            ),
        )

    default_key = str(payload.get("default_model_key") or "").strip()
    if default_key not in models:
        raise ValueError("default_model_key must reference a configured local model")
    cache = payload.get("local_llm_cache") or {}
    if not isinstance(cache, dict):
        raise ValueError("local_llm_cache must be an object")
    return LocalRuntimeConfig(
        default_model_key=default_key,
        models=models,
        keep_loaded=str(cache.get("mode") or "keep_loaded").strip() == "keep_loaded",
        max_loaded_models=_positive_int(
            cache.get("max_loaded_models"), field="max_loaded_models", default=1
        ),
        serialize_requests=bool(cache.get("serialize_requests", True)),
    )
