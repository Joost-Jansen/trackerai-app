"""Onboarding (T23): where a user stands, for the welcome tour, the checklist on the dashboard, the start banner and Help.

Onboarding state per user:

* **What you use the site for** (`choice`): `site` (the website only) or `claude` (also Claude as coach via MCP or
  tools/tr.py). It only decides which steps the tour shows; Help can change it later.
* **Which watch** (`device`): `garmin` (connect the account, the site syncs) or `apple` (an Apple Watch: import the
  export of the Health app, api/apple.py). It decides how the first step reads; both count for "your data is in".
* **Whether the tour is done** (`done`) and where you were in it (`step`; 0 is the choice, 1 the first tour step).
  Stored with the account (`settings.onboarding`), not in the browser, so the tour does not come back on another device.
* **Banners you hid** (`hidden`) and **pages you have looked at** (`visited`, for the "look around" step).

Plus the status of every step, derived from the user's own data (Garmin session, sync state, activities, zones,
profile facts, agent tokens, goals, plans). A user without stored onboarding state who already has activities is
already on the way: `done` defaults to true for them, so existing users are never shown the tour.
"""

from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Body, Depends

from api.errors import ApiError
from api.settings_api import suggested_max
from tools import db

KEY = "onboarding"
CHOICES = ("site", "claude")
DEVICES = ("garmin", "apple")
BANNERS = ("checklist", "data")  # the "Aan de slag" (getting started) card on the dashboard, the start banner above empty pages
# The "look around" step, stored per user in `visited` (web/lib/onboarding.ts PAGES; tests/test_web_routes.py checks
# both sides match). Up to schema 3 two ids were Dutch; tools/db.py migrated them and a visit still accepts them.
PAGES = ("dashboard", "trends", "routes", "history")
OLD_PAGES = {"rondjes": "routes", "historie": "history"}
FIELDS = {"choice", "device", "done", "step", "hide", "visit"}
REQUIRED = ("garmin", "sync", "zones")


def status(u, running: bool, apple_running: bool = False) -> dict:
    """Per part what is already there, from the user's own data."""
    s = u.scope
    store = u.store
    acts = store.activities
    sync = db.get_setting(s, "sync_state") or {}
    zones = store.zones
    goals = db.get_document(s, "goals")
    plans = db.list_plans(s)
    days = sorted((a.get("start_local") or "")[:10] for a in acts if a.get("start_local"))
    return {
        "garmin": {
            "connected": bool(db.get_setting(s, "garmin_tokens")),
            "connected_at": (db.get_setting(s, "garmin_meta") or {}).get("connected_at"),
        },
        "apple": _apple(s, apple_running),
        "sync": {
            "last_sync": sync.get("last_sync_local"),
            "last_failed": sync.get("last_failed") or [],
            "running": running,
        },
        "activities": {
            "count": len(acts),
            "first": days[0] if days else None,
            "last": days[-1] if days else None,
            "sports": sorted({a["sport"] for a in acts if a.get("sport")}),
        },
        "wellness_days": len(store.wellness),
        "zones": {
            "set": sorted(k for k, z in zones.items() if isinstance(z, dict) and z.get("bounds")),
            "estimated": sorted(k for k, z in zones.items() if isinstance(z, dict) and z.get("estimate")),
            "suggested_max": suggested_max(acts),
        },
        "profile": {"filled": sorted(store.profile_facts)},
        "agents": {"tokens": len(db.list_agent_tokens(s))},
        "goals": bool(goals and (goals.get("body") or "").strip()),
        "plan": {"count": len(plans), "active": any(p.get("status") == "active" for p in plans)},
    }


def _apple(s: db.Scope, running: bool) -> dict:
    last = db.get_setting(s, "apple_import") or {}
    done = bool(last.get("imported_at"))  # a failed later import leaves the earlier one's data (and numbers) in place
    return {
        "imported": done,
        "imported_at": last.get("imported_at") if done else None,
        "workouts": last.get("workouts") if done else None,
        "days": last.get("days") if done else None,
        "failed": last.get("status") == "failed",
        "running": running,
    }


def steps(st: dict, visited: list[str]) -> dict:
    """Which steps are done. Required: garmin (your data source: Garmin connected or an Apple Health import), sync,
    zones; the rest is optional."""
    return {
        "garmin": st["garmin"]["connected"] or st["apple"]["imported"],
        "sync": bool(st["sync"]["last_sync"]) or st["activities"]["count"] > 0 or st["apple"]["imported"],
        "zones": bool(st["zones"]["set"]),
        "profile": bool(st["profile"]["filled"]),
        "explore": all(p in visited for p in PAGES[1:]),  # the dashboard is where you land anyway
        "agent": st["agents"]["tokens"] > 0,
        "goals": st["goals"],
        "plan": st["plan"]["count"] > 0,
    }


def _stored(scope: db.Scope) -> dict | None:
    value = db.get_setting(scope, KEY)
    return value if isinstance(value, dict) else None


def read(u, running: bool = False, apple_running: bool = False) -> dict:
    """{choice, device, done, step, hidden, visited, status, steps, required_done}."""
    st = status(u, running, apple_running)
    stand = _stored(u.scope)
    if stand is None:
        # Never started: whoever already has activities is on the way (existing users are not shown the tour).
        stand = {"done": st["activities"]["count"] > 0}
    choice = stand.get("choice") if stand.get("choice") in CHOICES else None
    # without a stored choice: Apple when an Apple import is all there is, else Garmin
    device = stand.get("device") if stand.get("device") in DEVICES else ("apple" if st["apple"]["imported"] and not st["garmin"]["connected"] else "garmin")
    step = stand.get("step") if isinstance(stand.get("step"), int) and not isinstance(stand.get("step"), bool) and stand["step"] >= 0 else 0
    hidden = [b for b in stand.get("hidden") or [] if b in BANNERS]
    visited = [p for p in dict.fromkeys(OLD_PAGES.get(p, p) for p in stand.get("visited") or []) if p in PAGES]
    done_steps = steps(st, visited)
    return {
        "choice": choice,
        "device": device,
        "done": bool(stand.get("done")),
        "step": step,
        "hidden": hidden,
        "visited": visited,
        "status": st,
        "steps": done_steps,
        "required_done": all(done_steps[k] for k in REQUIRED),
    }


def write(u, **fields) -> None:
    """Updates only the given fields: `choice`, `done`, `step`, `hide` (add a banner id), `visit` (add a page id)."""
    now = read(u)
    new = {k: now[k] for k in ("choice", "device", "done", "step", "hidden", "visited")}
    if "choice" in fields:
        if fields["choice"] not in (*CHOICES, None):
            raise ApiError(400, "invalid_choice", options=list(CHOICES))
        new["choice"] = fields["choice"]
    if "device" in fields:
        if fields["device"] not in DEVICES:
            raise ApiError(400, "invalid_device", options=list(DEVICES))
        new["device"] = fields["device"]
    if "done" in fields:
        if not isinstance(fields["done"], bool):
            raise ApiError(400, "invalid_done")
        new["done"] = fields["done"]
    if "step" in fields:
        v = fields["step"]
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 50:
            raise ApiError(400, "invalid_step")
        new["step"] = v
    if "hide" in fields:
        if fields["hide"] not in BANNERS:
            raise ApiError(400, "unknown_banner", options=list(BANNERS))
        new["hidden"] = sorted({*new["hidden"], fields["hide"]})
    if "visit" in fields:
        fields["visit"] = OLD_PAGES.get(fields["visit"], fields["visit"])
        if fields["visit"] not in PAGES:
            raise ApiError(400, "unknown_page", options=list(PAGES))
        new["visited"] = [*new["visited"], fields["visit"]] if fields["visit"] not in new["visited"] else new["visited"]
    db.set_setting(u.scope, KEY, new)


def make_router(current_user: Callable, runner=None, apple_imports=None) -> APIRouter:
    r = APIRouter(prefix="/api/onboarding")

    def running(u) -> bool:
        return bool(runner and u.id in runner.running)

    def apple_running(u) -> bool:
        return bool(apple_imports and u.id in apple_imports.running)

    @r.get("")
    def get_onboarding(u=Depends(current_user)):
        return read(u, running(u), apple_running(u))

    @r.put("")
    def put_onboarding(fields: dict = Body(..., description="only what changes: choice, done, step, hide, visit"), u=Depends(current_user)):
        unknown = set(fields) - FIELDS
        if unknown:
            raise ApiError(400, "unknown_field", fields=sorted(unknown))
        write(u, **fields)
        return read(u, running(u), apple_running(u))

    return r
