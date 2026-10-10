"""Read access for the API, for one user (a `db.Scope`).

Activities and wellness (large, change only on a sync) are cached for TTL seconds; everything else is read live,
so an agent write shows up immediately. One DataStore per user (api/users.py `Stores`)."""

from __future__ import annotations

import time

from tools import db
from tools.distance import counted


TTL = 60


class DataStore:
    def __init__(self, scope: db.Scope, ttl: float = TTL):
        self.scope = scope
        self.engine = scope  # every db call takes the scope; the name stays for older callers
        self.ttl = ttl
        self._cache: dict = {}

    def invalidate(self) -> None:
        """After a sync: read activities and wellness fresh."""
        self._cache.clear()

    def _cached(self, key: str, load):
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        value = load()
        self._cache[key] = (time.monotonic(), value)
        return value

    @property
    def activities(self) -> list[dict]:
        # a doubtful GPS distance (open water) counts as none: totals, paces and plans leave it out (tools/distance.py)
        return self._cached("activities", lambda: [counted(a) for a in db.load_activities(self.engine)])

    @property
    def wellness(self) -> dict:
        return self._cached("wellness", lambda: db.load_wellness(self.engine))

    @property
    def routes(self) -> list[dict]:
        return db.load_routes(self.engine)

    @property
    def profile_facts(self) -> dict:
        return db.get_setting(self.scope, "profile_facts") or {}

    @property
    def rhr_fallback(self) -> float | None:
        """Resting HR the user entered, for when there is no sleep data."""
        return self.profile_facts.get("resting_hr")

    @property
    def zones(self) -> dict:
        return db.get_setting(self.engine, "zones") or {}

    @property
    def last_sync(self) -> str:
        state = db.get_setting(self.engine, "sync_state") or {}
        text = state.get("last_sync_local", "nog nooit")
        if state.get("last_failed"):
            text += f"; mislukt: {', '.join(state['last_failed'])}"
        return text

    def streams(self, activity_id: str) -> dict | None:
        return db.load_streams(self.engine, activity_id)
