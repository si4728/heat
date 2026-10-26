"""Reproducible fingerprints and run manifests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .environment import inspect_environment
from .readonly_db import database_sha256


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).resolve().open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_fingerprint(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    database_path: str | Path,
    dataset_version: str,
    sql_version: str,
    source_files: Iterable[str | Path],
    seed: int,
    settings: dict[str, Any],
    code_version: str = "workspace-no-vcs",
    started_at: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any]:
    sources = {str(Path(path).resolve()): file_sha256(path) for path in sorted(source_files, key=lambda p: str(p))}
    core = {
        "database_sha256": database_sha256(database_path),
        "dataset_version": dataset_version,
        "sql_version": sql_version,
        "source_sha256": sources,
        "environment": inspect_environment(),
        "seed": seed,
        "settings": settings,
        "code_version": code_version,
    }
    now = datetime.now(timezone.utc).isoformat()
    return {
        **core,
        "reproducibility_fingerprint": stable_fingerprint(core),
        "started_at": started_at or now,
        "finished_at": finished_at or now,
    }
