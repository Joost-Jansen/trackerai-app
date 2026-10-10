"""Routes: recurring routes (runs and rides) with a map, the history of every run or ride on them, and "a route for X km".

The pure functions take plain data; the router reads the caller's routes and activities from their DataStore:

    app.include_router(routes_api.make_router(today_fn, current_user))
"""

from __future__ import annotations

from datetime import date
from statistics import median
from typing import Callable

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.errors import ApiError
from api.history import _pick
from tools import db
from tools.recommend import recommend
from tools.routes import apply_merge, distance_variants, member_from_activity

PREVIEW_POINTS = 150
TRACK_POINTS = 800
VARIANT_POINTS = {"preview": 80, "detail": 300}
# (user id, activity id, points) -> downsampled track; a stored track never changes. Keyed by user because activity
# ids repeat across users; streams_fn is the user's DataStore.streams (plain functions in tests key on themselves).
_TRACK_CACHE: dict[tuple, list] = {}
_CACHE_MAX = 4000


def _runs(route: dict, activities: list[dict]) -> list[dict]:
    refs = set(route.get("activity_ids") or [])
    return sorted((a for a in activities if a["id"] in refs or a["start_local"] in refs), key=lambda a: a["start_local"])


def _pace(a: dict) -> int | None:
    if a.get("moving_time_s") and a.get("distance_km"):
        return round(a["moving_time_s"] / a["distance_km"])
    return None


def _efficiency(a: dict) -> float | None:
    """Metres per heartbeat: speed divided by heart rate. Higher at the same route = fitter, whatever the effort."""
    if a.get("moving_time_s") and a.get("distance_km") and a.get("avg_hr"):
        return round(a["distance_km"] * 1000 / (a["moving_time_s"] / 60 * a["avg_hr"]), 3)
    return None


def _activity_track(aid: str, streams_fn: Callable, limit: int) -> list[list[float]]:
    owner = getattr(streams_fn, "__self__", None)
    scope = getattr(owner, "scope", None)
    key = (scope.user_id if scope is not None else streams_fn, aid, limit)
    if key not in _TRACK_CACHE:
        latlng = [p for p in ((streams_fn(aid) or {}).get("latlng") or []) if p and p[0] is not None]
        if len(_TRACK_CACHE) >= _CACHE_MAX:
            _TRACK_CACHE.clear()
        _TRACK_CACHE[key] = [[round(latlng[i][0], 5), round(latlng[i][1], 5)] for i in _pick(len(latlng), limit)] if len(latlng) >= 2 else []
    return _TRACK_CACHE[key]


def _track(route: dict, runs: list[dict], streams_fn: Callable, limit: int) -> list[list[float]]:
    """The route's "average" track: its medoid (the run most like all others, from tools/routes.py), else the
    most recent run with GPS."""
    medoid = route.get("medoid_id")
    ordered = ([a for a in runs if a["id"] == medoid] if medoid else []) + list(reversed(runs))
    for a in ordered:
        track = _activity_track(a["id"], streams_fn, limit)
        if track:
            return track
    return []


def _variants(route: dict, runs: list[dict], streams_fn: Callable, limit: int) -> list[dict]:
    """Every other run on the route, to draw lightly under the average track."""
    medoid = route.get("medoid_id")
    out = []
    for a in runs:
        if a["id"] == medoid:
            continue
        track = _activity_track(a["id"], streams_fn, limit)
        if track:
            out.append({"id": a["id"], "date": a["start_local"][:10], "track": track})
    return out


def route_summary(route: dict, activities: list[dict], streams_fn: Callable, points: int = PREVIEW_POINTS, variant_points: int = VARIANT_POINTS["preview"]) -> dict:
    runs = _runs(route, activities)
    paces = [(a, _pace(a)) for a in runs if _pace(a)]
    best = min(paces, key=lambda x: x[1]) if paces else None
    recent = [p for _, p in paces[-5:]]
    earlier = [p for _, p in paces[:-5]]
    eff = [e for e in (_efficiency(a) for a in runs) if e]
    return {
        **{k: route.get(k) for k in ("id", "name", "distance_km", "is_loop", "elevation_gain_m", "runs", "first_run", "last_run", "median_pace", "median_speed_kmh", "median_hr", "start")},
        "sport": route.get("sport", "run"),
        "best": {"activity_id": best[0]["id"], "date": best[0]["start_local"][:10], "pace_s_per_km": best[1], "moving_time_s": best[0].get("moving_time_s")} if best else None,
        "recent_pace_s_per_km": round(median(recent)) if recent else None,
        "earlier_pace_s_per_km": round(median(earlier)) if earlier else None,
        "recent_efficiency": round(median(eff[-5:]), 3) if eff[:-5] else None,
        "earlier_efficiency": round(median(eff[:-5]), 3) if eff[:-5] else None,
        "medoid_id": route.get("medoid_id"),
        # length variants (one circuit ridden with a detour, shortcut or lead-in); computed for routes stored before
        "distance_variants": route.get("distance_variants") or distance_variants([member_from_activity(a) for a in runs if a.get("distance_km")], route.get("sport", "run")),
        "track": _track(route, runs, streams_fn, points),
        "variants": _variants(route, runs, streams_fn, variant_points),
    }


def route_detail(route: dict, activities: list[dict], streams_fn: Callable) -> dict:
    runs = _runs(route, activities)
    out = route_summary(route, activities, streams_fn, TRACK_POINTS, VARIANT_POINTS["detail"])
    out["history"] = [
        {"id": a["id"], "date": a["start_local"][:10], "distance_km": a.get("distance_km"), "moving_time_s": a.get("moving_time_s"), "avg_hr": a.get("avg_hr"), "pace_s_per_km": _pace(a), "m_per_beat": _efficiency(a), "hr_zones_s": a.get("hr_zones_s")}
        for a in runs
    ]
    return out


def suggest(routes: list[dict], activities: list[dict], streams_fn: Callable, km: float, today: date, tolerance: float = 0.05, start: str | None = None, limit: int = 3, sport: str = "run") -> list[dict]:
    """Routes of one sport only (routes stored without a sport are runs); `start` must be a route of that sport."""
    usable = [r for r in routes if r.get("start") and r.get("last_run") and r.get("sport", "run") == sport]
    if not usable:
        return []
    by_id = {r["id"]: r for r in usable}
    if start and start not in by_id:
        raise ApiError(404, "unknown_route")
    out = []
    for rec in recommend(usable, km, today, tolerance, start=start, limit=limit, sport=sport):
        parts = [by_id[p] for p in rec["parts"]]
        out.append({**rec, "names": [p.get("name") or p["id"] for p in parts], "tracks": {p["id"]: _track(p, _runs(p, activities), streams_fn, 300) for p in parts}})
    return out


# --- candidate pairs: tools/derive.py stores them in setting route_candidates, answers go to route_decisions ---


def _pending(scope) -> list[dict]:
    return list((db.get_setting(scope, "route_candidates") or {}).get("candidates") or [])


def _answered(scope) -> set:
    d = db.get_setting(scope, "route_decisions") or {}
    return {frozenset(p) for key in ("merge", "separate") for p in d.get(key) or [] if len(p) == 2}


def candidates_view(pending: list[dict], answered: set, routes: list[dict], activities: list[dict], streams_fn: Callable, sport: str | None = None) -> list[dict]:
    """Open pairs with current names and a preview track per side; pairs whose route or activity is gone, that
    were answered, or whose activity is on a route by now are left out."""
    by_route = {r["id"]: r for r in routes}
    by_act = {a["id"]: a for a in activities}
    on_route = {x for r in routes for x in r.get("activity_ids") or []}
    out = []
    for c in pending:
        if (sport and c.get("sport") != sport) or frozenset((c["a"]["id"], c["b"]["id"])) in answered:
            continue
        sides = []
        for side in (c["a"], c["b"]):
            if side.get("kind") == "activity":
                a = by_act.get(side["id"])
                if a is None or side["id"] in on_route:
                    break
                sides.append({"id": a["id"], "kind": "activity", "name": a.get("name"), "distance_km": a.get("distance_km"), "runs": 1, "date": a["start_local"][:10], "track": _activity_track(a["id"], streams_fn, PREVIEW_POINTS)})
            else:
                r = by_route.get(side["id"])
                if r is None:
                    break
                sides.append({**{k: r.get(k) for k in ("id", "name", "distance_km", "runs", "last_run")}, "kind": "route", "track": _track(r, _runs(r, activities), streams_fn, PREVIEW_POINTS)})
        else:
            out.append({**{k: c.get(k) for k in ("sport", "outcome", "confidence", "reason_code", "reason")}, "a": sides[0], "b": sides[1]})
    return out


class CandidateAnswer(BaseModel):
    a: str
    b: str
    same: bool


class RouteRename(BaseModel):
    name: str


def make_router(today: Callable[[], date], current_user: Callable) -> APIRouter:
    """Routes of the caller (`current_user` returns an api.users.User); a rename is saved in their routes."""
    r = APIRouter()

    def find(u, route_id: str) -> dict:
        for route in u.store.routes:
            if route["id"] == route_id:
                return route
        raise ApiError(404, "route_not_found")

    @r.get("/api/routes")
    def list_routes(sport: str | None = None, u=Depends(current_user)):
        items = [x for x in u.store.routes if not sport or x.get("sport", "run") == sport]
        acts = u.store.activities
        return sorted((route_summary(x, acts, u.store.streams) for x in items), key=lambda x: -(x.get("runs") or 0))

    # before /{route_id} so "suggest" is not taken for an id
    @r.get("/api/routes/suggest")
    def suggest_route(
        km: float = Query(..., gt=0, le=300),
        tolerance: float = Query(0.05, ge=0, le=0.5),
        start: str | None = None,
        sport: str = "run",
        u=Depends(current_user),
    ):
        return {"km": km, "options": suggest(u.store.routes, u.store.activities, u.store.streams, km, today(), tolerance, start, sport=sport)}

    @r.get("/api/routes/candidates")
    def list_candidates(sport: str | None = None, u=Depends(current_user)):
        """Open "same loop?" questions, plus the last sync (routes are recognised after every sync)."""
        pending = candidates_view(_pending(u.scope), _answered(u.scope), u.store.routes, u.store.activities, u.store.streams, sport)
        return {"candidates": pending, "last_sync": u.store.last_sync}

    @r.post("/api/routes/candidates")
    def answer_candidate(body: CandidateAnswer, u=Depends(current_user)):
        """Record the answer (derive applies it on every run) and apply a merge right away when the data allows."""
        pair = frozenset((body.a, body.b))
        pending = _pending(u.scope)
        if len(pair) != 2 or not any(frozenset((c["a"]["id"], c["b"]["id"])) == pair for c in pending):
            raise ApiError(404, "no_open_question")
        decisions = db.get_setting(u.scope, "route_decisions") or {}
        key, other = ("merge", "separate") if body.same else ("separate", "merge")
        decisions = {
            key: [p for p in decisions.get(key) or [] if frozenset(p) != pair] + [[body.a, body.b]],
            other: [p for p in decisions.get(other) or [] if frozenset(p) != pair],
        }
        db.set_setting(u.scope, "route_decisions", {"merge": decisions["merge"], "separate": decisions["separate"]})

        route, applied, gone = None, True, set()
        if body.same:
            items = u.store.routes
            members = {}
            for a in u.store.activities:
                members[a["id"]] = members[a["start_local"]] = member_from_activity(a)
            merged = apply_merge(items, body.a, body.b, members)
            if merged is None:
                applied = False
            else:
                db.save_routes(u.scope, merged)
                kept = next(x for x in merged if x["id"] in pair)
                gone = pair - {kept["id"]}
                route = route_summary(kept, u.store.activities, u.store.streams)
        # questions about the answered pair, or about what was merged away, are dropped; the next sync asks anew
        left = [c for c in pending if frozenset((c["a"]["id"], c["b"]["id"])) != pair and not ({c["a"]["id"], c["b"]["id"]} & gone)]
        db.set_setting(u.scope, "route_candidates", {"candidates": left})
        return {"applied": applied, "applied_on_next_sync": not applied, "route": route, "remaining": len(left)}

    @r.get("/api/routes/{route_id}")
    def get_route(route_id: str, u=Depends(current_user)):
        return route_detail(find(u, route_id), u.store.activities, u.store.streams)

    @r.patch("/api/routes/{route_id}")
    def rename(route_id: str, body: RouteRename, u=Depends(current_user)):
        name = body.name.strip()
        if not name or len(name) > 80:
            raise ApiError(422, "route_name_length", min=1, max=80)
        items = u.store.routes
        for x in items:
            if x["id"] == route_id:
                x["name"] = name
                db.save_routes(u.scope, items)
                return route_detail(x, u.store.activities, u.store.streams)
        raise ApiError(404, "route_not_found")

    return r
