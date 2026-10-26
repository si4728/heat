"""ML environment checks that do not break the Flask application import."""

from __future__ import annotations

import importlib.util
import platform
import sys
from importlib import metadata
from typing import Iterable


DEFAULT_DEPENDENCIES = ("numpy", "scipy", "scikit-learn")
IMPORT_NAMES = {"scikit-learn": "sklearn"}


class MissingMLDependencies(RuntimeError):
    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(f"Missing ML dependencies: {', '.join(missing)}")

    def as_dict(self) -> dict[str, object]:
        return {
            "code": "ML_DEPENDENCY_MISSING",
            "missing": self.missing,
            "install_file": "requirements-ml-lock.txt",
        }


def inspect_environment(dependencies: Iterable[str] = DEFAULT_DEPENDENCIES) -> dict[str, object]:
    packages: dict[str, dict[str, object]] = {}
    for package in dependencies:
        import_name = IMPORT_NAMES.get(package, package.replace("-", "_"))
        installed = importlib.util.find_spec(import_name) is not None
        version = None
        if installed:
            try:
                version = metadata.version(package)
            except metadata.PackageNotFoundError:
                installed = False
        packages[package] = {"installed": installed, "version": version}
    return {
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "database_backend": "mariadb",
        "packages": packages,
    }


def require_ml_environment(dependencies: Iterable[str] = DEFAULT_DEPENDENCIES) -> dict[str, object]:
    status = inspect_environment(dependencies)
    missing = [name for name, value in status["packages"].items() if not value["installed"]]
    if missing:
        raise MissingMLDependencies(missing)
    return status
