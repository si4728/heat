"""Governed, read-only machine-learning support for IRIS.

Modules in this package must not mutate operational measurements, maintenance
state, or API 510 approval data. Optional ML dependencies are imported only by
the command or model that needs them.
"""

from .readonly_db import database_sha256, readonly_connection

__all__ = ["database_sha256", "readonly_connection"]
