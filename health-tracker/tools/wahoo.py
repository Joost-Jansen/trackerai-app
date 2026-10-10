"""The Wahoo connection: a user's workouts from the Wahoo cloud API (https://cloud-api.wahooligan.com).

The user connects on the site (OAuth, api/connections.py); the tokens are stored encrypted (`settings.wahoo_tokens`,
tools/secretbox.py). Access tokens live 2 hours and are refreshed with the refresh token; once a refreshed token is
used, Wahoo revokes the old pair, so the newest tokens are saved after every sync. Each workout comes in as its FIT
file, as source `wahoo_api` (a Wahoo file the user uploads is `wahoo`): disconnecting, or revoking access at Wahoo,
removes exactly what came in this way (db.remove_source). A ride that is on Garmin too is merged, with Garmin's values
and streams leading (tools/store.py priorities).

Client id and secret: WAHOO_CLIENT_ID and WAHOO_CLIENT_SECRET in the environment of `web` and `sync`.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from urllib.parse import quote, urlencode

import requests

from tools import db
from tools.fit import read_fit_activity
from tools.store import from_fit

API = "https://api.wahooligan.com"
SCOPES = "workouts_read offline_data user_read"
SOURCE = "wahoo_api"
TOKENS_KEY = "wahoo_tokens"
FIRST_SYNC_DAYS = 365
OVERLAP_DAYS = 2  # look back a little: a workout uploaded late from the device still comes in
PER_PAGE = 30
TIMEOUT_S = 30


class WahooError(Exception):
    pass


class WahooRevoked(WahooError):
    """The user revoked access at Wahoo (or the refresh token is gone): the connection has ended."""


def credentials() -> tuple[str, str] | None:
    cid, secret = os.environ.get("WAHOO_CLIENT_ID", ""), os.environ.get("WAHOO_CLIENT_SECRET", "")
    return (cid, secret) if cid and secret else None


def authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    q = {"client_id": client_id, "redirect_uri": redirect_uri, "scope": SCOPES, "response_type": "code", "state": state}
    return f"{API}/oauth/authorize?{urlencode(q, quote_via=quote)}"  # scopes space-separated as %20, as Wahoo documents


def _detail(r) -> str:
    """Status and the start of the body, for the log (Wahoo's error bodies hold no tokens)."""
    body = (r.content or b"")[:200].decode("utf-8", "replace").strip()
    return f"HTTP {r.status_code}" + (f" {body}" if body else "")


def _tokens(body: dict, now: float) -> dict:
    return {"access_token": body["access_token"], "refresh_token": body["refresh_token"], "expires_at": int(now + int(body.get("expires_in") or 7200))}


def exchange_code(code: str, redirect_uri: str, creds: tuple[str, str], http=requests, now=time.time) -> dict:
    """The tokens for the code Wahoo sent to the callback."""
    r = http.post(f"{API}/oauth/token", data={"client_id": creds[0], "client_secret": creds[1], "code": code,
                                              "redirect_uri": redirect_uri, "grant_type": "authorization_code"}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise WahooError(f"token exchange: {_detail(r)}")
    return _tokens(r.json(), now())


class WahooClient:
    def __init__(self, tokens: dict, creds: tuple[str, str], http=requests, now=time.time, sleep=time.sleep):
        self._t = dict(tokens)
        self.creds = creds
        self.http = http
        self.now = now
        self.sleep = sleep

    def tokens(self) -> dict:
        return dict(self._t)

    def refresh(self) -> None:
        r = self.http.post(f"{API}/oauth/token", data={"client_id": self.creds[0], "client_secret": self.creds[1],
                                                       "grant_type": "refresh_token", "refresh_token": self._t["refresh_token"]}, timeout=TIMEOUT_S)
        if r.status_code in (400, 401) and b"invalid_grant" in (r.content or b""):
            raise WahooRevoked(f"refresh token refused: {_detail(r)}")
        if r.status_code != 200:
            raise WahooError(f"token refresh: {_detail(r)}")
        self._t = _tokens(r.json(), self.now())

    def _request(self, method: str, path: str, refresh_on_401: bool = True, **params):
        if self._t.get("expires_at", 0) - 120 < self.now():
            self.refresh()
        for attempt in (1, 2) if refresh_on_401 else (2,):
            r = self.http.request(method, f"{API}{path}", params=params or None,
                                  headers={"Authorization": f"Bearer {self._t['access_token']}"}, timeout=TIMEOUT_S)
            if r.status_code == 401 and attempt == 1:
                self.refresh()
                continue
            if r.status_code >= 400:  # a 401 with a fresh token is not a revoke: that shows in the refresh (invalid_grant)
                raise WahooError(f"{method} {path}: {_detail(r)}")
            return r.json() if r.content else {}

    def workouts(self, page: int = 1, per_page: int = PER_PAGE) -> dict:
        """Newest first: {workouts: [...], total, page, per_page}."""
        return self._request("GET", "/v1/workouts", page=page, per_page=per_page)

    def summary(self, workout_id) -> dict:
        """A 401 here is about this one workout ("not authorized to view this workout summary"), not the token: the
        list call before it already worked with this token, so no refresh."""
        return self._request("GET", f"/v1/workouts/{workout_id}/workout_summary", refresh_on_401=False)

    def download(self, url: str) -> bytes:
        """The FIT file; Wahoo's file server answers a 5xx now and then, so up to three tries."""
        for attempt in range(3):
            if attempt:
                self.sleep(2 * attempt)
            try:
                r = self.http.get(url, timeout=TIMEOUT_S * 2)
            except requests.RequestException as err:
                status = type(err).__name__
                continue
            if r.status_code == 200:
                return r.content
            status = f"HTTP {r.status_code}"
            if r.status_code < 500:
                break
        raise WahooError(f"FIT download: {status}")

    def deauthorize(self) -> None:
        """Revoke this app's access at Wahoo (DELETE /v1/permissions)."""
        self._request("DELETE", "/v1/permissions")


def load_tokens(stored: str, key: str) -> dict:
    from tools.secretbox import decrypt

    return json.loads(decrypt(stored, key))


def save_tokens(s: db.Scope, tokens: dict, key: str) -> None:
    from tools.secretbox import encrypt

    db.set_setting(s, TOKENS_KEY, encrypt(json.dumps(tokens), key))


def sync_wahoo(s: db.Scope, client: WahooClient, state: dict, today: date, since: date | None = None, read_activity=None,
               progress=None) -> int:
    """New workouts since the last one seen (the past year the first time) -> activities. Returns how many.
    `progress("wahoo", days, total_days)`: how far back from today it is, newest first."""
    read_activity = read_activity or read_fit_activity
    w = state.setdefault("wahoo", {})
    if since:
        cutoff = since
    elif w.get("last_workout_day"):
        cutoff = date.fromisoformat(w["last_workout_day"]) - timedelta(days=OVERLAP_DAYS)
    else:
        cutoff = today - timedelta(days=FIRST_SYNC_DAYS)
    count, newest, page = 0, w.get("last_workout_day"), 1
    span = max((today - cutoff).days, 1)
    if progress:
        progress("wahoo", 0, span)
    tries = w.setdefault("failed", {})  # workout id -> failed downloads; retried by the next syncs, three times at most
    retry_from = None
    while True:
        data = client.workouts(page)
        items = data.get("workouts") or []
        done = not items
        for wo in items:
            day = (wo.get("starts") or "")[:10]
            if not day or day < cutoff.isoformat():
                done = True  # newest first: everything after this is older
                break
            if progress:
                progress("wahoo", min(max((today - date.fromisoformat(day)).days, 0), span), span)
            summary = wo.get("workout_summary")
            if not summary:
                try:
                    summary = client.summary(wo["id"])
                except WahooError as err:  # Wahoo refuses some workouts' summaries: skip that one, not the rest
                    print(f"wahoo: workout {wo['id']} van {wo.get('starts')} ({wo.get('name')!r}, type {wo.get('workout_type_id')}, "
                          f"bron {wo.get('workout_token') or '-'}) overgeslagen ({err})")
                    continue
            url = ((summary or {}).get("file") or {}).get("url")
            if not url:
                continue  # a manual entry without a file: nothing to measure
            key = f"{SOURCE}/{wo['id']}"
            fit = db.get_fit(s, key)
            if fit is None:
                try:
                    fit = client.download(url)
                except WahooError as err:  # one file not coming in does not stop the rest
                    n = tries[str(wo["id"])] = tries.get(str(wo["id"]), 0) + 1
                    print(f"wahoo: workout {wo['id']} niet gedownload, poging {n} ({err})")
                    if n < 3:
                        retry_from = min(retry_from or day, day)
                    continue
                db.put_fit(s, key, fit)
                tries.pop(str(wo["id"]), None)
            try:
                activity = read_activity(fit)
            except ValueError as err:
                print(f"wahoo: workout {wo['id']} niet leesbaar ({err})")
                continue
            record = from_fit(activity, source=SOURCE, name=wo.get("name") or None, meta={"id": wo["id"]})
            aid = db.upsert_activity(s, record)
            if not (db.get_activity(s, aid) or {}).get("fit_file"):  # a Garmin original stays the file of record
                db.set_derived(s, aid, fit_file=key)
            count += 1
            newest = max(newest or day, day)
        total = data.get("total") or 0
        if done or page * (data.get("per_page") or PER_PAGE) >= total:
            break
        page += 1
    if newest:
        w["last_workout_day"] = newest
    if retry_from:  # the next sync looks back to the oldest workout whose file did not come in
        w["last_workout_day"] = min(w.get("last_workout_day") or retry_from, retry_from)
    return count
