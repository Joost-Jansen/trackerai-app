"""Recompute derived data in the database: time per HR zone and per heart rate on each activity, and the regular routes
(runs and outdoor rides; indoor rides have no GPS track and never form a route).

Run after every sync and after a zones change:

    DATABASE_URL=... python tools/derive.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import db
from tools.routes import detect

ROUTE_SPORTS = ("run", "ride")
from tools.zones import hr_histogram, zone_seconds


def _run_for_routes(a: dict, latlng: list) -> dict:
    return {
        "activity_id": a["id"],
        "date": a["start_local"][:10],
        "distance_km": a["distance_km"],
        "latlng": latlng,
        "elevation_gain_m": a.get("elevation_gain_m"),
        "avg_hr": a.get("avg_hr"),
        "moving_time_s": a.get("moving_time_s"),
    }


def derive(scope: db.Scope) -> dict:
    zones = db.get_setting(scope, "zones")
    changed = 0
    tracks: dict[str, list[dict]] = {sport: [] for sport in ROUTE_SPORTS}
    for a in db.load_activities(scope, with_streams=True):
        s = a.get("streams") or {}
        if zones:
            z = zone_seconds(zones, a["sport"], s["heartrate"], s["time"]) if s.get("heartrate") and s.get("time") else None
            if a.get("hr_zones_s") != z:
                db.set_derived(scope, a["id"], hr_zones_s=z)
                changed += 1
        hist = hr_histogram(s["heartrate"], s["time"]) if s.get("heartrate") and s.get("time") else None
        if a.get("hr_hist_s") != hist:
            db.set_derived(scope, a["id"], hr_hist_s=hist)
        if a["sport"] in tracks and s.get("latlng") and a.get("distance_km"):
            tracks[a["sport"]].append(_run_for_routes(a, s["latlng"]))

    # save_routes replaces the whole table, so rebuild every sport and save them together;
    # build_routes only matches existing routes of its own sport (ids r.. for runs, f.. for rides)
    # route_decisions: the user's answers to candidate pairs ({merge, separate}); route_candidates: open questions
    existing = db.load_routes(scope)
    decisions = db.get_setting(scope, "route_decisions") or {}
    routes, counts, candidates = [], {}, []
    for sport in ROUTE_SPORTS:
        built, asks = detect(tracks[sport], existing, sport=sport, decisions=decisions)
        counts[sport] = len(built)
        routes += built
        candidates += asks
    db.save_routes(scope, routes)
    db.set_setting(scope, "route_candidates", {"candidates": candidates})
    return {"zones_updated": changed, "routes": counts, "candidates": len(candidates)}


if __name__ == "__main__":
    engine = db.connect(os.environ["DATABASE_URL"])
    db.create_schema(engine)
    for user in db.list_users(engine):
        print(user["username"], derive(db.Scope(engine, user["id"])))
