"""Safe and atomic storage for ML artifacts."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


_SECRET_KEY = re.compile(
    r"(?:password|passwd|secret|api[_-]?(?:key|token)|access[_-]?token|password[_-]?hash)",
    re.I,
)
_SECRET_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]{12,})", re.I)


def _assert_secret_free(value: Any, location: str = "root") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SECRET_KEY.search(str(key)):
                raise ValueError(f"Secret-bearing field is not allowed in artifacts: {location}.{key}")
            _assert_secret_free(item, f"{location}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_secret_free(item, f"{location}[{index}]")
    elif isinstance(value, str) and _SECRET_VALUE.search(value):
        raise ValueError(f"Secret-like value is not allowed in artifacts: {location}")


class ArtifactStore:
    def __init__(self, root: str | Path, *, protected_directories: tuple[str | Path, ...] = ()) -> None:
        self.root = Path(root).resolve()
        protected = tuple(Path(item).resolve() for item in protected_directories)
        if any(self.root == item or item in self.root.parents for item in protected):
            raise ValueError("Artifact root cannot be inside an operational data directory")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str | Path) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Artifact path must be relative")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("Artifact path escapes the configured root")
        return resolved

    def write_json(self, relative_path: str | Path, value: Any) -> Path:
        _assert_secret_free(value)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        return self.write_text(relative_path, payload)

    def write_text(self, relative_path: str | Path, value: str) -> Path:
        if _SECRET_VALUE.search(value):
            raise ValueError("Secret-like value is not allowed in artifacts")
        target = self.path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary:
                temporary.write(value)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_name, target)
        except BaseException:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise
        return target
