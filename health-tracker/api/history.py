"""History: activity list, activity detail (map track coloured by HR zone, laps, HR/pace series) and a route heatmap.

Pure functions over plain data so they work on the file store and on tools/db.py alike:
`activities` are records without streams, `streams(id)` returns an activity's streams dict (or None).
"""

from __future__ import annotations

from statistics import mean
from typing import Callable

from api.dashboard import summary
from tools.zones import zone_for

StreamsFn = Callable[[str], "dict | None"]

TRACK_POINTS = 1500
SERIES_POINTS = 1500
HEATMAP_POINTS = 300
DETAIL_FIELDS = ("elapsed_time_s", "avg_cadence_spm", "calories")


def _pick(n: int, limit: int) -> list[int]:
    """Evenly spaced indices into a list of length n, at most `limit`, always including the last one."""
    if n <= limit:
        return list(range(n))
    step = (n - 1) / (limit - 1)
    return [round(i * step) for i in range(limit)]


def _raw(a: dict) -> dict:
    return ((a.get("sources") or {}).get("garmin") or {}).get("raw") or {}


def list_activities(activities: list[dict], sport: str | None = None, start: str | None = None, end: str | None = None, hr_flags: dict[str, list[str]] | None = None) -> list[dict]:
    """Summaries, newest first. `hr_flags` (api/trends.py hr_flags): runs with an implausible wrist heart rate get
    their reason codes as `hr_flags`."""
    out = []
    for a in activities:
        day = a["start_local"][:10]
        if sport and a["sport"] != sport:
            continue
        if (start and day < start) or (end and day > end):
            continue
        s = summary(a)
        s["has_gps"] = bool(a.get("has_gps", _raw(a).get("hasPolyline")))
        if hr_flags and a["id"] in hr_flags:
            s["hr_flags"] = hr_flags[a["id"]]
        out.append(s)
    out.sort(key=lambda s: s["start_local"], reverse=True)
    return out


def _zone_at(zones: dict, sport: str, hr) -> str | None:
    return zone_for(zones, sport, hr) if hr else None


def track(streams: dict, zones: dict, sport: str, limit: int = TRACK_POINTS) -> dict | None:
    """Downsampled GPS track with the HR zone of every point. GPS and HR streams can differ a few samples
    in length (GPS fix starts later), so each GPS point takes the HR sample at the same relative position."""
    latlng = [p for p in (streams.get("latlng") or []) if p and p[0] is not None]
    if len(latlng) < 2:
        return None
    hr = streams.get("heartrate") or []
    idx = _pick(len(latlng), limit)
    points = [[round(latlng[i][0], 6), round(latlng[i][1], 6)] for i in idx]
    zone = []
    for i in idx:
        j = round(i * (len(hr) - 1) / (len(latlng) - 1)) if len(hr) > 1 else None
        zone.append(_zone_at(zones, sport, hr[j]) if j is not None else None)
    return {"latlng": points, "zone": zone}


def series(streams: dict, limit: int = SERIES_POINTS) -> dict | None:
    time = streams.get("time") or []
    if len(time) < 2:
        return None
    idx = _pick(len(time), limit)
    out: dict[str, list] = {"time": [time[i] for i in idx]}
    for key in ("heartrate", "velocity", "altitude", "cadence", "distance"):
        values = streams.get(key) or []
        if len(values) == len(time):
            out[key] = [None if values[i] is None else round(values[i], 2) for i in idx]
    return out


def km_splits(streams: dict) -> list[dict]:
    """Per whole kilometre: time, average HR and elevation change, from the distance stream (metres)."""
    time, dist = streams.get("time") or [], streams.get("distance") or []
    hr, alt = streams.get("heartrate") or [], streams.get("altitude") or []
    if len(dist) != len(time) or len(time) < 2:
        return []
    out, start_i, next_km = [], 0, 1000.0
    for i, d in enumerate(dist):
        if d is None or d < next_km:
            continue
        seg_hr = [h for h in hr[start_i : i + 1] if h] if len(hr) == len(time) else []
        split = {"km": int(next_km // 1000), "seconds": time[i] - time[start_i], "avg_hr": round(mean(seg_hr)) if seg_hr else None}
        if len(alt) == len(time) and alt[i] is not None and alt[start_i] is not None:
            split["elevation_m"] = round(alt[i] - alt[start_i], 1)
        out.append(split)
        start_i, next_km = i, next_km + 1000
    return out


def decoupling(streams: dict, min_seconds: int = 1200) -> float | None:
    """Aerobic decoupling (Pa:HR drift) in %: how much the speed-per-heartbeat of the second half drops
    against the first half. Below 5% means the aerobic base holds at this effort. Moving samples only."""
    time, hr, v = streams.get("time") or [], streams.get("heartrate") or [], streams.get("velocity") or []
    if not (len(time) == len(hr) == len(v)) or len(time) < 10 or time[-1] - time[0] < min_seconds:
        return None
    moving = [(t, h, s) for t, h, s in zip(time, hr, v) if h and s and s > 1.0]
    if len(moving) < 10:
        return None
    half = len(moving) // 2

    def ratio(part):
        return mean(s for _, _, s in part) / mean(h for _, h, _ in part)

    first, second = ratio(moving[:half]), ratio(moving[half:])
    return round((first - second) / first * 100, 1)


def _route_refs(route: dict) -> set[str]:
    # routes.json refers to runs by start_local (file store) or by id (database)
    return set(route.get("activity_ids") or [])


def route_of(activity: dict, routes: list[dict]) -> dict | None:
    for r in routes:
        refs = _route_refs(r)
        if activity["id"] in refs or activity["start_local"] in refs:
            return r
    return None


def route_history(route: dict, activities: list[dict]) -> list[dict]:
    """Every run on the same route, oldest first, for a pace/HR comparison."""
    refs = _route_refs(route)
    runs = sorted((a for a in activities if a["id"] in refs or a["start_local"] in refs), key=lambda a: a["start_local"])
    return [
        {
            "id": a["id"],
            "date": a["start_local"][:10],
            "moving_time_s": a.get("moving_time_s"),
            "distance_km": a.get("distance_km"),
            "avg_hr": a.get("avg_hr"),
            "pace_s_per_km": round(a["moving_time_s"] / a["distance_km"]) if a.get("moving_time_s") and a.get("distance_km") else None,
        }
        for a in runs
    ]


def same_day(activity: dict, activities: list[dict]) -> list[dict]:
    """Other activities on the same day (triathlon, brick, split run): a run after swim/bike is not a standalone run."""
    day = activity["start_local"][:10]
    return [
        {k: a.get(k) for k in ("id", "start_local", "sport", "name", "distance_km", "moving_time_s")}
        for a in sorted(activities, key=lambda a: a["start_local"])
        if a["start_local"][:10] == day and a["id"] != activity["id"]
    ]


def activity_detail(activity_id: str, activities: list[dict], streams_fn: StreamsFn, zones: dict, routes: list[dict] | None = None) -> dict | None:
    by_id = {a["id"]: a for a in activities}
    a = by_id.get(activity_id)
    if a is None:
        return None
    raw = _raw(a)
    out = summary(a)
    for k in DETAIL_FIELDS:
        if a.get(k) is not None:
            out[k] = a[k]
    if raw.get("calories") and "calories" not in out:
        out["calories"] = round(raw["calories"])
    if raw.get("vO2MaxValue"):
        out["vo2max"] = raw["vO2MaxValue"]
    out["laps"] = a.get("laps") or []
    out["zone_bounds"] = (zones.get(a["sport"]) or {}).get("bounds")
    out["zone_estimate"] = bool((zones.get(a["sport"]) or {}).get("estimate"))

    streams = streams_fn(activity_id) or {}
    out["track"] = track(streams, zones, a["sport"])
    out["series"] = series(streams)
    out["splits"] = km_splits(streams) if a["sport"] in ("run", "walking") else []
    out["decoupling_pct"] = decoupling(streams) if a["sport"] in ("run", "ride") else None
    out["same_day"] = same_day(a, activities)

    route = route_of(a, routes or [])
    out["route"] = None
    if route:
        out["route"] = {"id": route["id"], "name": route.get("name"), "distance_km": route.get("distance_km"), "history": route_history(route, activities)}

    ordered = sorted(activities, key=lambda x: x["start_local"])
    i = ordered.index(a)
    out["prev_id"] = ordered[i - 1]["id"] if i > 0 else None
    out["next_id"] = ordered[i + 1]["id"] if i + 1 < len(ordered) else None
    return out


def heatmap(activities: list[dict], streams_fn: StreamsFn, sport: str | None = "run", limit: int = HEATMAP_POINTS) -> dict:
    tracks = []
    for a in sorted(activities, key=lambda a: a["start_local"]):
        if sport and a["sport"] != sport:
            continue
        latlng = [p for p in ((streams_fn(a["id"]) or {}).get("latlng") or []) if p and p[0] is not None]
        if len(latlng) < 2:
            continue
        tracks.append([[round(latlng[i][0], 5), round(latlng[i][1], 5)] for i in _pick(len(latlng), limit)])
    return {"tracks": tracks}

