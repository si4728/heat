"""IRIS v3 heat exchanger management application."""


def create_app(*args, **kwargs):
    """Load the Flask factory lazily so direct script execution also works."""
    from .app import create_app as factory
    return factory(*args, **kwargs)


__all__ = ["create_app"]
