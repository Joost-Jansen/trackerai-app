"""Distances that cannot be trusted, and the distance you corrected yourself.

An open-water swim measures its distance with GPS, which barely works with the watch under water: 2 km can come back
as 200 m. A pace outside OPEN_WATER_PACE (per 100 m) is not a swim but a GPS error. Such an activity keeps its time
and heart rate, but no distance: totals in km, paces and plan matching leave it out. The GPS value stays visible
(`gps_distance_km`) and the user can enter the real distance (source `manual`, tools/store.py), which always wins.
"""

from __future__ import annotations

from tools.store import source_distance

OPEN_WATER_PACE = (60, 240)  # seconds per 100 m: faster than 1:00 or slower than 4:00 is a GPS error


def is_open_water(a: dict) -> bool:
    if a.get("open_water"):
        return True
    raw = ((a.get("sources") or {}).get("garmin") or {}).get("raw") or {}
    return (raw.get("activityType") or raw.get("activityTypeDTO") or {}).get("typeKey") == "open_water_swimming"


def manual_distance(a: dict) -> float | None:
    return (((a.get("sources") or {}).get("manual") or {}).get("fields") or {}).get("distance_km")


def doubtful(a: dict) -> bool:
    """An open-water swim whose GPS distance gives an impossible pace (and that you did not correct)."""
    if a.get("sport") != "swim" or not is_open_water(a) or manual_distance(a) is not None:
        return False
    km, secs = a.get("distance_km"), a.get("moving_time_s")
    if not km or not secs:
        return bool(secs)  # time but no distance at all: nothing to count either
    pace = secs / (km * 10)
    return not OPEN_WATER_PACE[0] <= pace <= OPEN_WATER_PACE[1]


def counted(a: dict) -> dict:
    """The activity as the rest of the app should count it: a doubtful distance becomes None (kept as
    `gps_distance_km`); a corrected one is marked `distance_manual`."""
    if manual_distance(a) is not None:
        measured = source_distance({k: v for k, v in (a.get("sources") or {}).items() if k != "manual"})
        return {**a, "distance_manual": True, "gps_distance_km": measured, "open_water": is_open_water(a) or None}
    if doubtful(a):
        return {**a, "distance_km": None, "gps_distance_km": a.get("distance_km"), "distance_doubtful": True, "open_water": True}
    if is_open_water(a):
        return {**a, "open_water": True}
    return a
