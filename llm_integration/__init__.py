"""Offline-only local LLM integration primitives for the IRIS application.

These modules are staged for later application wiring. Importing this package does
not load a model or change the existing Flask application.
"""

from .local_llm import LocalLlmClient, remove_thinking_blocks
from .model_config import LocalModelSpec, LocalRuntimeConfig, load_local_runtime_config

__all__ = [
    "LocalLlmClient",
    "LocalModelSpec",
    "LocalRuntimeConfig",
    "load_local_runtime_config",
    "remove_thinking_blocks",
]
