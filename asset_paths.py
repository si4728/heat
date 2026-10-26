"""Resolve preserved evidence paths exclusively to private iris2 copies."""
import json
from pathlib import Path
from .db_config import APP_DIR


def local_asset_path(source):
    path=Path(source).resolve()
    if path.is_relative_to(APP_DIR):return path
    manifest=APP_DIR/'data/asset_path_map.json'
    mapping=json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}
    destination=mapping.get(str(path))
    if not destination:raise ValueError('Evidence must be copied into iris2 before use')
    target=Path(destination).resolve()
    if not target.is_relative_to(APP_DIR):raise ValueError('External evidence mapping rejected')
    return target
