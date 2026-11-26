"""Return local redirect paths without trusting arbitrary URLs or browser slashes."""
from urllib.parse import unquote, urlsplit, urlunsplit


def local_redirect_path(value, fallback, *, origin=None):
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        return fallback
    try:
        target = urlsplit(value)
        if target.scheme or target.netloc:
            if not origin:
                return fallback
            expected = urlsplit(origin)
            if (target.scheme, target.netloc) != (expected.scheme, expected.netloc) or target.username or target.password:
                return fallback
        path = target.path
        for _ in range(4):
            if not path.startswith('/') or path.startswith('//') or '\\' in path or any(ord(c) < 32 or ord(c) == 127 for c in path):
                return fallback
            path = unquote(path)
        return urlunsplit(('', '', target.path, target.query, target.fragment))
    except (ValueError, UnicodeError):
        return fallback
