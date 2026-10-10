"""Training load: Banister TRIMP per activity, and fitness (CTL), fatigue (ATL) and form (TSB) per day."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

CTL_DAYS = 42
ATL_DAYS = 7
MIN_CTL_FOR_PCT = 5  # below this a percentage of fitness is noise (the first weeks of data)


def _weight(hr: float, rhr: float, hr_max: float) -> float:
    """Banister's load per minute at a heart rate: heart-rate reserve weighted exponentially (men's coefficients)."""
    ratio = max(0.0, min(1.0, (hr - rhr) / (hr_max - rhr)))
    return ratio * 0.64 * math.exp(1.92 * ratio)


def trimp(activity: dict, rhr: float, max_by_sport: dict) -> float:
    """Banister TRIMP with the max HR of the activity's sport (run max as fallback). From the time per heart rate
    (`hr_hist_s`, tools/derive.py) when the activity has heart-rate streams: the weight grows exponentially, so an
    interval or a race weighs more than its average heart rate says. Without streams: from the average HR."""
    hr_max = max_by_sport.get(activity["sport"]) or max_by_sport.get("run") or max(max_by_sport.values(), default=None)
    if not hr_max or hr_max <= rhr:
        return 0.0  # no max heart rate known yet (no zones set and no data): no load
    hist = activity.get("hr_hist_s")
    if hist:
        return sum(secs / 60 * _weight(float(bpm), rhr, hr_max) for bpm, secs in hist.items())
    hr, secs = activity.get("avg_hr"), activity.get("moving_time_s")
    if not hr or not secs:
        return 0.0
    return secs / 60 * _weight(hr, rhr, hr_max)


def fitness_series(activities: list[dict], rhr: float, max_by_sport: dict, end: date) -> list[dict]:
    """One row per day from the first activity to `end`: load, ctl, atl, tsb (form = yesterday's ctl - atl) and
    form_pct, form as a share of yesterday's fitness. The percentage does not depend on how big the load numbers are
    (TRIMP here, TSS elsewhere) and grows along with fitness; None while fitness is still under MIN_CTL_FOR_PCT."""
    load: dict[date, float] = defaultdict(float)
    for a in activities:
        load[date.fromisoformat(a["start_local"][:10])] += trimp(a, rhr, max_by_sport)
    if not load:
        return []

    rows, ctl, atl = [], 0.0, 0.0
    day = min(load)
    while day <= end:
        tsb = ctl - atl
        pct = round(tsb / ctl * 100) if ctl >= MIN_CTL_FOR_PCT else None
        x = load.get(day, 0.0)
        ctl += (x - ctl) / CTL_DAYS
        atl += (x - atl) / ATL_DAYS
        rows.append({"date": day.isoformat(), "load": round(x, 1), "ctl": round(ctl, 1), "atl": round(atl, 1), "tsb": round(tsb, 1), "form_pct": pct})
        day += timedelta(days=1)
    return rows
