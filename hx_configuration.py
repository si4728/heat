from __future__ import annotations

import configparser
import os
import secrets
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(
    os.environ.get("IRIS2_CONFIG_PATH", APP_DIR / "hx_configuration.conf")
).resolve()


def _load_config(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None)
    if not path.is_file():
        raise RuntimeError(f"IRIS configuration file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as config_file:
            config.read_file(config_file)
    except (OSError, configparser.Error) as exc:
        raise RuntimeError(f"Failed to read IRIS configuration file: {path}") from exc
    return config


if not CONFIG_PATH.is_relative_to(APP_DIR):
    raise RuntimeError("IRIS2 configuration must stay within the independent application directory")

CONFIG = _load_config(CONFIG_PATH)


def _required(section: str, option: str) -> str:
    if not CONFIG.has_option(section, option):
        raise RuntimeError(f"[{section}] {option} is required in {CONFIG_PATH}")
    value = CONFIG.get(section, option).strip()
    if not value:
        raise RuntimeError(f"[{section}] {option} must not be empty in {CONFIG_PATH}")
    return value


def _required_int(section: str, option: str) -> int:
    _required(section, option)
    try:
        return CONFIG.getint(section, option)
    except ValueError as exc:
        raise RuntimeError(
            f"[{section}] {option} must be an integer in {CONFIG_PATH}"
        ) from exc


def _required_float(section: str, option: str) -> float:
    _required(section, option)
    try:
        return CONFIG.getfloat(section, option)
    except ValueError as exc:
        raise RuntimeError(
            f"[{section}] {option} must be a number in {CONFIG_PATH}"
        ) from exc


def _required_bool(section: str, option: str) -> bool:
    _required(section, option)
    try:
        return CONFIG.getboolean(section, option)
    except ValueError as exc:
        raise RuntimeError(
            f"[{section}] {option} must be true or false in {CONFIG_PATH}"
        ) from exc


def _configured_path(section: str, option: str) -> Path:
    path = Path(_required(section, option))
    if not path.is_absolute():
        path = CONFIG_PATH.parent / path
    resolved = path.resolve()
    if not resolved.is_relative_to(APP_DIR):
        raise RuntimeError("IRIS2 file paths must remain inside the independent application directory")
    return resolved


def _application_secret_key() -> str:
    """Return a strong session key without keeping it in distributable config."""
    environment_value = os.environ.get("IRIS2_SECRET_KEY", "").strip()
    configured_value = CONFIG.get("application", "secret_key", fallback="").strip()
    known_placeholders = {"iris-v3-local-system", "change-me", "changeme"}
    for candidate in (environment_value, configured_value):
        if candidate and candidate.lower() not in known_placeholders:
            if len(candidate) < 32:
                raise RuntimeError("IRIS session secret must be at least 32 characters")
            return candidate

    secret_path = CONFIG_PATH.parent / "data" / ".session_secret"
    try:
        if secret_path.is_file():
            value = secret_path.read_text(encoding="utf-8").strip()
            if len(value) >= 32:
                return value
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        secret_path.write_text(value + "\n", encoding="utf-8")
        return value
    except OSError as exc:
        raise RuntimeError(
            "Set IRIS2_SECRET_KEY to a random value of at least 32 characters; "
            f"could not use local secret file {secret_path}"
        ) from exc


DB_PATH = _configured_path("database", "name")

SERVER_HOST = _required("server", "host")
SERVER_PORT = _required_int("server", "port")
SERVER_HEALTH_CHECK = _required_bool("server", "health_check")
if not 1 <= SERVER_PORT <= 65535:
    raise RuntimeError(f"[server] port must be between 1 and 65535 in {CONFIG_PATH}")

AUTHENTICATION_REQUIRED = _required_bool("access", "authentication_required")
if not CONFIG.has_option("access", "api_write_token"):
    raise RuntimeError(f"[access] api_write_token is required in {CONFIG_PATH}")
API_WRITE_TOKEN = CONFIG.get("access", "api_write_token").strip()

APP_SECRET_KEY = _application_secret_key()
MAX_CONTENT_LENGTH = _required_int("application", "max_content_length")
JSON_AS_ASCII = _required_bool("application", "json_as_ascii")
SESSION_IDLE_TIMEOUT_SECONDS = _required_int(
    "application", "session_idle_timeout_seconds"
)
PERMANENT_SESSION_LIFETIME_MINUTES = _required_int(
    "application", "permanent_session_lifetime_minutes"
)
SESSION_REFRESH_EACH_REQUEST = _required_bool(
    "application", "session_refresh_each_request"
)
SESSION_COOKIE_HTTPONLY = _required_bool("application", "session_cookie_httponly")
SESSION_COOKIE_SAMESITE = _required("application", "session_cookie_samesite")
SESSION_COOKIE_SECURE = CONFIG.getboolean(
    "application", "session_cookie_secure", fallback=False
)

if MAX_CONTENT_LENGTH <= 0:
    raise RuntimeError(f"[application] max_content_length must be positive in {CONFIG_PATH}")
if SESSION_IDLE_TIMEOUT_SECONDS <= 0:
    raise RuntimeError(
        f"[application] session_idle_timeout_seconds must be positive in {CONFIG_PATH}"
    )
if PERMANENT_SESSION_LIFETIME_MINUTES <= 0:
    raise RuntimeError(
        f"[application] permanent_session_lifetime_minutes must be positive in {CONFIG_PATH}"
    )

ENDPOINT_PERMISSIONS = {
    endpoint.strip(): screen_key.strip().upper()
    for endpoint, screen_key in CONFIG.items("permissions")
    if endpoint.strip() and screen_key.strip()
}
if not ENDPOINT_PERMISSIONS:
    raise RuntimeError(f"[permissions] must define at least one endpoint in {CONFIG_PATH}")

UPLOAD_DIR = _configured_path("paths", "uploads")
REPORT_DIR = _configured_path("paths", "reports")
PDF_REPORT_DIR = _configured_path("paths", "pdf_reports")
CUMULATIVE_REPORT = _configured_path("paths", "cumulative_report")

ML_UNITS = tuple(
    unit.strip().upper() for unit in _required("ml", "units").split(",") if unit.strip()
)
ML_CONTAMINATION = _required_float("ml", "contamination")
ML_RANDOM_STATE = _required_int("ml", "random_state")
ML_ESTIMATORS = _required_int("ml", "estimators")
ML_TOP_RESULTS = _required_int("ml", "top_results")
ML_REVIEW_DB_PATH = _configured_path("ml", "review_database")
ML_ARTIFACT_ROOT = _configured_path("ml", "artifact_root")
if not ML_UNITS:
    raise RuntimeError(f"[ml] units must define at least one unit in {CONFIG_PATH}")
if not 0 < ML_CONTAMINATION <= 0.5:
    raise RuntimeError(
        f"[ml] contamination must be greater than 0 and no more than 0.5 in {CONFIG_PATH}"
    )
if ML_ESTIMATORS < 50:
    raise RuntimeError(f"[ml] estimators must be at least 50 in {CONFIG_PATH}")
if ML_TOP_RESULTS <= 0:
    raise RuntimeError(f"[ml] top_results must be positive in {CONFIG_PATH}")

REMAINING_LIFE_AS_OF_DATE_MODE = _required(
    "remaining_life", "as_of_date_mode"
).lower()
if REMAINING_LIFE_AS_OF_DATE_MODE not in {"system", "fixed"}:
    raise RuntimeError(
        f"[remaining_life] as_of_date_mode must be system or fixed in {CONFIG_PATH}"
    )
if not CONFIG.has_option("remaining_life", "fixed_as_of_date"):
    raise RuntimeError(
        f"[remaining_life] fixed_as_of_date is required in {CONFIG_PATH}"
    )
REMAINING_LIFE_FIXED_AS_OF_DATE = CONFIG.get(
    "remaining_life", "fixed_as_of_date"
).strip()
if REMAINING_LIFE_AS_OF_DATE_MODE == "fixed" and not REMAINING_LIFE_FIXED_AS_OF_DATE:
    raise RuntimeError(
        f"[remaining_life] fixed_as_of_date must be set in fixed mode in {CONFIG_PATH}"
    )
REMAINING_LIFE_FORECAST_END_YEAR = _required_int(
    "remaining_life", "forecast_end_year"
)
REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT = _required_float(
    "remaining_life", "plugging_wall_loss_percent"
)
try:
    REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS = tuple(
        float(value.strip())
        for value in _required("remaining_life", "allowable_plugging_options").split(",")
        if value.strip()
    )
except ValueError as exc:
    raise RuntimeError(
        f"[remaining_life] allowable_plugging_options must contain numbers in {CONFIG_PATH}"
    ) from exc
REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT = _required_float(
    "remaining_life", "default_allowable_plugging_percent"
)
API510_INTERVAL_FRACTION = _required_float(
    "remaining_life", "api510_interval_fraction"
)
API510_INTERNAL_MAX_INTERVAL_YEARS = _required_float(
    "remaining_life", "api510_internal_max_interval_years"
)
API510_EXTERNAL_MAX_INTERVAL_YEARS = _required_float(
    "remaining_life", "api510_external_max_interval_years"
)
API510_CODE_EDITION = _required("remaining_life", "api510_code_edition")
for option, value in (
    ("plugging_wall_loss_percent", REMAINING_LIFE_PLUGGING_WALL_LOSS_PERCENT),
    ("default_allowable_plugging_percent", REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT),
):
    if not 0 < value <= 100:
        raise RuntimeError(
            f"[remaining_life] {option} must be greater than 0 and no more than 100 in {CONFIG_PATH}"
        )
if set(REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS) != {
        float(value) for value in range(1, 21)
}:
    raise RuntimeError(
        f"[remaining_life] allowable_plugging_options must contain every integer "
        f"from 1 through 20 in {CONFIG_PATH}"
    )
if REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT not in REMAINING_LIFE_ALLOWABLE_PLUGGING_OPTIONS:
    raise RuntimeError(
        f"[remaining_life] default_allowable_plugging_percent must be one of "
        f"allowable_plugging_options in {CONFIG_PATH}"
    )
if REMAINING_LIFE_DEFAULT_ALLOWABLE_PLUGGING_PERCENT != 20.0:
    raise RuntimeError(
        f"[remaining_life] default_allowable_plugging_percent must be 20 in {CONFIG_PATH}"
    )
if not 0 < API510_INTERVAL_FRACTION <= 1:
    raise RuntimeError(
        f"[remaining_life] api510_interval_fraction must be greater than 0 and no more than 1 in {CONFIG_PATH}"
    )
if API510_INTERNAL_MAX_INTERVAL_YEARS <= 0 or API510_EXTERNAL_MAX_INTERVAL_YEARS <= 0:
    raise RuntimeError(
        f"[remaining_life] API 510 maximum inspection intervals must be positive in {CONFIG_PATH}"
    )

DEGRADATION_POSITION_TOLERANCE_MM = _required_float(
    "degradation", "position_tolerance_mm"
)
if DEGRADATION_POSITION_TOLERANCE_MM <= 0:
    raise RuntimeError(
        f"[degradation] position_tolerance_mm must be positive in {CONFIG_PATH}"
    )

# v3 is primary. Respect an explicitly supplied test/tool database path.
# The v2 alias remains only for legacy module compatibility.
os.environ.setdefault("IRIS2_LEGACY_DB_PATH", str(DB_PATH))
os.environ.setdefault("IRIS2_LEGACY_V2_DB_PATH", os.environ["IRIS2_LEGACY_DB_PATH"])


def ensure_directories() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
