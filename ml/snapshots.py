"""Reproducible dataset snapshot metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from .artifacts import ArtifactStore


def canonical_rows_sha256(rows: Iterable[dict[str, Any]]) -> str:
    materialized = sorted(rows, key=lambda row: int(row["iris_tube_result_id"]))
    payload = json.dumps(materialized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_snapshot_manifest(store: ArtifactStore, relative_path: str, rows: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    result = {**metadata, "row_count": len(rows), "rows_sha256": canonical_rows_sha256(rows)}
    return str(store.write_json(relative_path, result))
