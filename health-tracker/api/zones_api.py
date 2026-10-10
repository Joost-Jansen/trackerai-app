"""Time per heart-rate zone over time: one week or month (browse back with offset) and a history of periods.

Weeks are ISO weeks (Monday-Sunday), months calendar months. Every activity's `hr_zones_s` was computed with its
own sport's zones, so "all" is a plain sum (same rule as the dashboard)."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Literal

from fastapi import APIRouter, Depends, Query

from api.dashboard import _day, _share, _zone_share
from api.errors import ApiError
from tools.zones import NAMES

Period = Literal["week", "month"]
MAX_COUNT = {"week": 104, "month": 36}
MAX_OFFSET = 1000
SPORT_ORDER = ("run", "ride", "swim")
MONTHS = ("januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december")
MONTHS_SHORT = ("jan", "feb", "mrt", "apr", "mei", "jun", "jul", "aug", "sep", "okt", "nov", "dec")


def _month_start(d: date, back: int = 0) -> date:
    index = d.year * 12 + d.month - 1 - back
    return date(index // 12, index % 12 + 1, 1)


def period_bounds(period: str, today: date, offset: int = 0) -> tuple[date, date]:
    """First and last day of the week/month `offset` periods before the one containing `today`."""
    if period == "week":
        start = today - timedelta(days=today.weekday(), weeks=offset)
        return start, start + timedelta(days=6)
    start = _month_start(today, offset)
    return start, _month_start(start, -1) - timedelta(days=1)


def period_label(period: str, start: date, end: date) -> str:
    if period == "month":
        return f"{MONTHS[start.month - 1]} {start.year}"
    if start.year != end.year:
        span = f"{start.day} {MONTHS_SHORT[start.month - 1]} {start.year} – {end.day} {MONTHS_SHORT[end.month - 1]} {end.year}"
    elif start.month != end.month:
        span = f"{start.day} {MONTHS_SHORT[start.month - 1]} – {end.day} {MONTHS_SHORT[end.month - 1]} {end.year}"
    else:
        span = f"{start.day} – {end.day} {MONTHS_SHORT[end.month - 1]} {end.year}"
    return f"week {start.isocalendar().week} · {span}"


def _bounds(zones: dict) -> dict:
    return {sport: z["bounds"] for sport, z in zones.items() if isinstance(z, dict) and "bounds" in z}


def _sport_key(sport: str) -> tuple:
    return (SPORT_ORDER.index(sport) if sport in SPORT_ORDER else len(SPORT_ORDER), sport)


def zones_for_period(activities: list[dict], zones: dict, period: str, offset: int, today: date) -> dict:
    start, end = period_bounds(period, today, offset)
    inside = [a for a in activities if start <= _day(a) <= end]
    return {
        "period": period,
        "offset": offset,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "label": period_label(period, start, end),
        "is_current": offset == 0,
        "zones": _zone_share(inside),
        "bounds": _bounds(zones),
    }


def _empty() -> dict:
    return {"seconds": {z: 0 for z in NAMES}, "total_s": 0, "pct": {z: 0 for z in NAMES}}


def zone_history(activities: list[dict], period: str, count: int, sport: str, today: date) -> dict:
    """`count` periods oldest -> newest, the last one the current (running) period; empty periods are zeros."""
    periods = [period_bounds(period, today, back) for back in range(count - 1, -1, -1)]
    first, last = periods[0][0], periods[-1][1]
    key = (lambda d: d - timedelta(days=d.weekday())) if period == "week" else (lambda d: d.replace(day=1))

    secs: dict[date, dict[str, int]] = defaultdict(lambda: {z: 0 for z in NAMES})
    sports: set[str] = set()
    for a in activities:
        hr = a.get("hr_zones_s")
        if not hr or not any(hr.values()):
            continue
        day = _day(a)
        if not first <= day <= last:
            continue
        sports.add(a["sport"])
        if sport != "all" and a["sport"] != sport:
            continue
        bucket = secs[key(day)]
        for z, s in hr.items():
            bucket[z] += s

    items = []
    for start, end in periods:
        share = _share(secs[start]) if start in secs and sum(secs[start].values()) else _empty()
        items.append({"start": start.isoformat(), "end": end.isoformat(), "label": period_label(period, start, end), **share})
    return {"period": period, "sport": sport, "sports": sorted(sports, key=_sport_key), "items": items}


def make_router(today: Callable[[], date], current_user: Callable) -> APIRouter:
    r = APIRouter()

    @r.get("/api/zones")
    def zones_period(period: Period = "week", offset: int = Query(0, ge=0, le=MAX_OFFSET), u=Depends(current_user)):
        return zones_for_period(u.store.activities, u.store.zones, period, offset, today())

    @r.get("/api/zones/history")
    def zones_history(period: Period = "week", count: int = Query(12, ge=1), sport: str = "all", u=Depends(current_user)):
        if count > MAX_COUNT[period]:
            raise ApiError(422, "max_periods", max=MAX_COUNT[period])
        return zone_history(u.store.activities, period, count, sport, today())

    return r
