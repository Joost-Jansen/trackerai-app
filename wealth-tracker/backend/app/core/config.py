"""Backend configuration — paths shared with the existing Streamlit app."""

import os

from trackerai_accounts.config import front_door_origins

# Repo root — same directory database.py/auth_config.yaml already live in,
# so both the legacy Streamlit app and this backend share one set of data
# and one set of accounts during the migration.
# core/config.py -> core -> app -> backend -> repo root (4 levels up)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# AUTH_CONFIG_PATH moves the file, for instance to a volume on a host where
# nothing can be attached to the container (Railway). Empty or absent: next to
# the code, as on the Pi.
AUTH_CONFIG_PATH = os.environ.get("AUTH_CONFIG_PATH") or os.path.join(REPO_ROOT, "auth_config.yaml")


# S11: a session lasts SESSION_DAYS (default 30) and is renewed while in use
# (sliding): a request with a cookie older than a day gets a fresh one. Never
# beyond SESSION_MAX_DAYS after the password was last typed. The old
# `cookie.expiry_days` in auth_config.yaml is no longer read.
def _session_days() -> int:
    try:
        return max(1, int(os.environ.get("SESSION_DAYS", "") or 30))
    except ValueError:
        return 30


SESSION_DAYS = _session_days()
SESSION_MAX_DAYS = 90
SESSION_RENEW_AFTER_SECONDS = 24 * 3600
DEFAULT_TOKEN_EXPIRY_DAYS = SESSION_DAYS  # written into a new auth_config.yaml, for older tools

ACCESS_COOKIE_NAME = "stocktracker_session"

# Permissive CORS is only needed for local dev when the frontend runs on a
# different port than the backend (e.g. `next dev` on :3000 vs uvicorn on
# :8000). In production both sit behind one reverse-proxy origin (see
# docker-compose.yml) and CORS is not needed at all.
DEV_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# News feeds (see app/services/news_service.py). One shared key per provider,
# supplied as an environment variable on the `api` service (docker-compose) and
# kept in the gitignored .env — not per-user, unlike the API Ninjas key that
# lives in each user's settings table. An empty string means "provider off":
# the feed simply omits that source and degrades to whatever the other returns.
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
ALPHAVANTAGE_API_KEY = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()


# --- Hosting and security (shared variable names with health-tracker) --------


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# Set COOKIE_SECURE=false only for local http:// development. Also decides HSTS.
COOKIE_SECURE = _flag("COOKIE_SECURE", True)

# The single opt-out for development and tests: allows a missing
# APP_ENCRYPTION_KEY (and other production requirements). Never in production.
ALLOW_INSECURE_DEFAULTS = _flag("ALLOW_INSECURE_DEFAULTS", False)

# The site's own public origins, e.g. "https://stocks.example.org" (comma-
# separated, for stock- and wealth-tracker on one API). Used by the CSRF origin
# check and to validate the Enable Banking return address. Empty: same-origin
# by the request's Host header only.
PUBLIC_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("PUBLIC_ORIGINS", "").split(",") if o.strip()]
# The front door (trackerai-web) at the shared session cookie's own domain, bare and www: you log in there with the
# account every tracker shares. That domain can set the cookie anyway, so its posts count as this site's own.
FRONT_DOOR_ORIGINS = front_door_origins(os.environ.get("SESSION_COOKIE_DOMAIN", ""))

# The API answers JSON (and a few downloads), never HTML to render: nothing may
# load, frame or run from its responses.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


# S1: the largest single uploaded file (DeGiro or bank export), in MB.
MAX_UPLOAD_MB = max(1, _int("MAX_UPLOAD_MB", 10))
# Several files may go in one upload request; the request body as a whole.
MAX_UPLOAD_REQUEST_MB = MAX_UPLOAD_MB * 5
# Any other request body (JSON). The feedback screenshot (3 MB, base64) fits.
MAX_BODY_MB = 8
# S3: how long an imported file is kept. 0 (default): deleted once imported;
# nothing in the app reads it again.
UPLOAD_RETENTION_DAYS = max(0, _int("UPLOAD_RETENTION_DAYS", 0))


# S15: who runs this installation, for the privacy statement (the GDPR
# controller of the users' data) and how to reach them. Shown on /privacy.
PRIVACY_CONTROLLER = os.environ.get("PRIVACY_CONTROLLER", "").strip()
PRIVACY_CONTACT = os.environ.get("PRIVACY_CONTACT", "").strip()
