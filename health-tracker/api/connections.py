"""Connections (T19, "Koppelingen" in the Dutch UI): each user connects their own Garmin and Wahoo accounts on the site.

Wahoo uses its official OAuth: /wahoo/start gives the Wahoo login URL with a one-time state, Wahoo sends the browser
back to /wahoo/callback, the tokens are stored encrypted and the first sync fetches the past year (tools/wahoo.py).
Disconnecting revokes the access at Wahoo and removes what came in through it.


The user types Garmin e-mail and password (and the MFA code when Garmin asks for one). The server logs in once and keeps
only the encrypted session (`settings.garmin_tokens`, tools/secretbox.py); the password is never stored. Garmin has no
public API for individuals, so this uses the same unofficial login as tools/setup_garmin.py.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Callable
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from api.errors import MESSAGES, ApiError
from tools import db, wahoo
from tools.derive import derive
from tools.secretbox import WrongKey, decrypt, encrypt
from tools.sync import end_wahoo
from trackerai_websec.throttle import Limiter

MFA_TTL_S = 10 * 60
WAHOO_STATE_TTL_S = 15 * 60
WAHOO_DONE = "/settings/connections/"
FIRST_SYNC_DAYS = 365


class GarminLoginError(Exception):
    """`code` is one of garmin_rejected, garmin_rate_limited, garmin_failed (api/errors.py); any other text is shown as is."""

    def __init__(self, code: str):
        super().__init__(MESSAGES.get(code, code))
        self.code = code if code in MESSAGES else "garmin_failed"


class GarminAuth:
    """Real Garmin login. `start` returns ("ok", tokens) or ("mfa", handle); `finish(handle, code)` returns tokens."""

    def start(self, email: str, password: str):
        from garminconnect import Garmin

        api = Garmin(email, password, return_on_mfa=True)
        try:
            status, state = api.login()
        except Exception as err:
            raise GarminLoginError(_explain(err)) from err
        if status == "needs_mfa":
            return "mfa", (api, state)
        return "ok", api.client.dumps()

    def finish(self, handle, code: str) -> str:
        api, state = handle
        try:
            api.resume_login(state, code)
        except Exception as err:
            raise GarminLoginError(_explain(err)) from err
        return api.client.dumps()


def _explain(err: Exception) -> str:
    """The error code for a failed Garmin login."""
    text = f"{type(err).__name__}: {err}".lower()
    if "401" in text or "authentication" in text or "credentials" in text or "password" in text:
        return "garmin_rejected"
    if "429" in text or "too many" in text:
        return "garmin_rate_limited"
    return "garmin_failed"


class GarminCredentials(BaseModel):
    email: str
    password: str


class MfaCode(BaseModel):
    code: str


def _readable(stored: str | None, key: str) -> bool | None:
    if not (stored and key):
        return None
    try:
        decrypt(stored, key)
        return True
    except WrongKey:
        return False


def status(scope: db.Scope, key: str, running: bool, progress: dict | None = None) -> dict:
    stored = db.get_setting(scope, "garmin_tokens")
    stored_wahoo = db.get_setting(scope, wahoo.TOKENS_KEY)
    wahoo_state = (db.get_setting(scope, "sync_state") or {}).get("wahoo") or {}
    key_ok = None
    if stored and key:
        try:
            decrypt(stored, key)
            key_ok = True
        except WrongKey:
            key_ok = False
    state = db.get_setting(scope, "sync_state") or {}
    return {
        "garmin": {
            "connected": bool(stored),
            "readable": key_ok,  # False: saved by a service with another key; reconnect
            "connected_at": (db.get_setting(scope, "garmin_meta") or {}).get("connected_at"),
            "last_sync": state.get("last_sync_local"),
            "last_failed": state.get("last_failed") or [],
            "syncing": running,
            "progress": progress if running else None,  # {step, done, total}: which part of the sync runs and how far
        },
        "wahoo": {
            "available": wahoo.credentials() is not None,  # the server has a Wahoo app (WAHOO_CLIENT_ID/SECRET)
            "connected": bool(stored_wahoo),
            "readable": _readable(stored_wahoo, key),
            "connected_at": (db.get_setting(scope, "wahoo_meta") or {}).get("connected_at"),
            "last_workout_day": wahoo_state.get("last_workout_day"),
            "failed": "wahoo" in (state.get("last_failed") or []),
        },
    }


def revoke_wahoo(scope: db.Scope, key: str) -> None:
    """Revoke the user's access at Wahoo (best effort: it may already be gone, or Wahoo be unreachable)."""
    stored, creds = db.get_setting(scope, wahoo.TOKENS_KEY), wahoo.credentials()
    if stored and creds and key:
        try:
            wahoo.WahooClient(wahoo.load_tokens(stored, key), creds).deauthorize()
        except Exception as err:  # noqa: BLE001  revoked already, or Wahoo unreachable: the data still goes
            print(f"wahoo: intrekken bij Wahoo mislukt ({type(err).__name__})", flush=True)


def make_router(
    current_user: Callable, runner, key: str, auth: GarminAuth | None = None, today: Callable[[], date] = date.today
) -> APIRouter:
    r = APIRouter(prefix="/api/connections")
    auth = auth or GarminAuth()
    pending: dict[int, tuple[float, object]] = {}  # user id -> (time, MFA handle)
    # The server logs in at Garmin for the user: without a limit it would be a free proxy for guessing Garmin passwords.
    garmin_logins = Limiter(10, 60 * 60)
    guard = threading.Lock()

    def person(u=Depends(current_user)):
        if u.via != "cookie":
            raise ApiError(403, "connections_site_only")
        return u

    def save(u, tokens: str) -> None:
        if not key:
            raise ApiError(500, "no_encryption_key")
        db.set_setting(u.scope, "garmin_tokens", encrypt(tokens, key))
        db.set_setting(u.scope, "garmin_meta", {"connected_at": time.strftime("%Y-%m-%d %H:%M")})
        first = not (db.get_setting(u.scope, "sync_state") or {}).get("garmin")
        runner.start_user(u.id, since=date.fromordinal(today().toordinal() - FIRST_SYNC_DAYS) if first else None)

    @r.get("")
    def get_status(u=Depends(current_user)):
        return status(u.scope, key, u.id in runner.running, runner.progress.get(u.id))

    @r.post("/garmin")
    def connect(body: GarminCredentials, u=Depends(person)):
        if not body.email.strip() or not body.password:
            raise ApiError(422, "missing_garmin_credentials")
        if not garmin_logins.hit(str(u.id)):
            raise ApiError(429, "too_many_attempts")
        try:
            kind, value = auth.start(body.email.strip(), body.password)
        except GarminLoginError as err:
            raise ApiError(400, err.code, detail=str(err))
        if kind == "mfa":
            with guard:
                pending[u.id] = (time.monotonic(), value)
            return {"status": "mfa"}
        save(u, value)
        return {"status": "connected"}

    @r.post("/garmin/mfa")
    def mfa(body: MfaCode, u=Depends(person)):
        with guard:
            item = pending.pop(u.id, None)
        if not item or time.monotonic() - item[0] > MFA_TTL_S:
            raise ApiError(410, "mfa_expired")
        try:
            tokens = auth.finish(item[1], body.code.strip())
        except GarminLoginError as err:
            raise ApiError(400, err.code, detail=str(err))
        save(u, tokens)
        return {"status": "connected"}

    @r.delete("/garmin")
    def disconnect(u=Depends(person)):
        db.delete_setting(u.scope, "garmin_tokens")
        db.delete_setting(u.scope, "garmin_meta")
        return {"ok": True}

    wahoo_states: dict[int, tuple[float, str]] = {}  # user id -> (time, state) of a Wahoo login under way

    def wahoo_redirect_uri(request: Request) -> str:
        return os.environ.get("WAHOO_REDIRECT_URI") or str(request.url_for("wahoo_callback"))

    @r.get("/wahoo/start")
    def wahoo_start(request: Request, u=Depends(person)):
        creds = wahoo.credentials()
        if not creds:
            raise ApiError(503, "wahoo_not_configured")
        if not key:
            raise ApiError(500, "no_encryption_key")
        state = secrets.token_urlsafe(24)
        with guard:
            wahoo_states[u.id] = (time.monotonic(), state)
        return {"url": wahoo.authorize_url(creds[0], wahoo_redirect_uri(request), state)}

    @r.get("/wahoo/callback", name="wahoo_callback")
    def wahoo_callback(request: Request, code: str = "", state: str = "", error: str = "", u=Depends(person)):
        """Wahoo sends the browser here after the login; back to the Connections page with ?wahoo=connected|<error>."""
        with guard:
            item = wahoo_states.pop(u.id, None)
        if error:
            return RedirectResponse(f"{WAHOO_DONE}?wahoo=denied", status_code=303)
        if not item or time.monotonic() - item[0] > WAHOO_STATE_TTL_S or not secrets.compare_digest(item[1], state) or not code:
            return RedirectResponse(f"{WAHOO_DONE}?wahoo=expired", status_code=303)
        creds = wahoo.credentials()
        if not creds or not key:
            return RedirectResponse(f"{WAHOO_DONE}?wahoo=failed", status_code=303)
        try:
            tokens = wahoo.exchange_code(code, wahoo_redirect_uri(request), creds)
        except Exception:
            return RedirectResponse(f"{WAHOO_DONE}?wahoo=failed", status_code=303)
        wahoo.save_tokens(u.scope, tokens, key)
        db.set_setting(u.scope, "wahoo_meta", {"connected_at": time.strftime("%Y-%m-%d %H:%M")})
        runner.start_user(u.id)  # the first Wahoo sync fetches the past year by itself
        return RedirectResponse(f"{WAHOO_DONE}?wahoo=connected", status_code=303)

    @r.delete("/wahoo")
    def wahoo_disconnect(u=Depends(person)):
        """Revoke the access at Wahoo (best effort: it may already be gone) and remove what came in through Wahoo."""
        revoke_wahoo(u.scope, key)
        removed = end_wahoo(u.scope)
        state = db.get_setting(u.scope, "sync_state") or {}
        if state.pop("wahoo", None) is not None:
            db.set_setting(u.scope, "sync_state", state)
        if removed["removed"] or removed["changed"]:
            derive(u.scope)
        u.store.invalidate()
        return {"ok": True, **removed}

    @r.post("/sync")
    def sync_now(u=Depends(current_user)):
        if not db.get_setting(u.scope, "garmin_tokens") and not db.get_setting(u.scope, wahoo.TOKENS_KEY):
            raise ApiError(409, "garmin_not_connected")
        started = runner.start_user(u.id)
        return {"started": started, **status(u.scope, key, True)}

    return r
