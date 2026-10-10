"""Wrist heart rate quality: flag runs whose heart rate stream is implausible, so HR-based trends can leave them out.

A wrist sensor often reads far too low in the first minutes (poor contact, cold skin), locks onto one value, or drops
out. Three checks, each a reason code:

- ``low_start``: in the first km (after a two-minute lag) the heart rate is far below what this user's own pace-HR
  relation expects at that speed, and (when the rest of the run went at a similar speed) also far below the run's own
  steady part, so an easy day is not mistaken for a sensor problem. Without enough runs for a relation, the run's own
  steady part is the only reference.
- ``flat``: the heart rate stays at exactly one value for minutes while moving.
- ``dropout``: no heart rate for a minute or more while moving.

Pure functions over a streams dict (``time``, ``heartrate``, ``velocity``, optional ``distance``): ``run_stats``
reduces a run to a few numbers, ``fit_relation`` fits HR = intercept + slope x speed over many runs, ``assess``
returns the reason codes for one run.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, pstdev

MIN_SPEED = 1.5  # m/s; slower is walking or standing
LAG_S = 120  # the heart rate needs about two minutes to follow the effort
START_M = 1000  # the first km
MIN_START_S = 60  # moving seconds with HR in the first km before it can be judged
STEADY_AFTER_S = 600  # steady state: after ten minutes and after the first km
MIN_STEADY_S = 300
LOW_START_BPM = 25  # at least this far below the expected heart rate
SIMILAR_SPEED = 0.85  # without a relation: only compare a first km at >= 85% of the steady speed
FLAT_S = 240  # exactly the same value for four minutes while moving
DROPOUT_S = 60  # a minute without heart rate while moving
MAX_DT = 30  # a pause in recording counts at most this long
MIN_RUNS = 5  # runs needed to fit a relation
MIN_SPEED_SPREAD = 0.05  # m/s; without spread in speed the slope means nothing


@dataclass(frozen=True)
class Relation:
    """The user's own steady-state heart rate per speed: intercept + slope x speed (m/s), and the spread around it."""

    intercept: float
    slope: float
    sd: float

    def at(self, speed: float) -> float:
        return self.intercept + self.slope * speed


def _distances(streams: dict) -> list[float]:
    time, v = streams["time"], streams["velocity"]
    dist = streams.get("distance") or []
    if len(dist) == len(time) and all(d is not None for d in dist):
        return dist
    out, total = [0.0], 0.0
    for i in range(1, len(time)):
        total += (v[i - 1] or 0) * min(time[i] - time[i - 1], MAX_DT)
        out.append(total)
    return out


def run_stats(streams: dict) -> dict | None:
    """The numbers the checks need, or None without usable heart rate and speed."""
    time, hr, v = streams.get("time") or [], streams.get("heartrate") or [], streams.get("velocity") or []
    if not (len(time) == len(hr) == len(v)) or len(time) < 10 or not any(hr):
        return None
    dist = _distances(streams)
    t0 = time[0]
    start_hr, start_v, steady = [], [], []
    start_s = steady_s = 0.0
    run_dropout = run_flat = dropout = flat = 0.0
    for i in range(len(time) - 1):
        dt = min(time[i + 1] - time[i], MAX_DT)
        moving = bool(v[i]) and v[i] >= MIN_SPEED
        h = hr[i] or None
        # longest stretch without heart rate, and with exactly the same heart rate, while moving
        run_dropout = run_dropout + dt if moving and h is None else 0.0
        run_flat = run_flat + dt if moving and h is not None and i > 0 and hr[i - 1] == h else 0.0
        dropout, flat = max(dropout, run_dropout), max(flat, run_flat)
        if not moving or h is None:
            continue
        since = time[i] - t0
        if since >= LAG_S and dist[i] <= START_M:
            start_hr.append(h)
            start_v.append(v[i])
            start_s += dt
        elif since >= STEADY_AFTER_S and dist[i] > START_M:
            steady.append((v[i], h))
            steady_s += dt
    out = {"dropout_s": round(dropout), "flat_s": round(flat), "start_hr": None, "start_v": None, "steady_hr": None, "steady_v": None}
    if start_s >= MIN_START_S:
        out["start_hr"], out["start_v"] = round(mean(start_hr), 1), round(mean(start_v), 3)
    if steady_s >= MIN_STEADY_S:
        out["steady_v"] = round(median(s for s, _ in steady), 3)
        out["steady_hr"] = round(median(h for _, h in steady), 1)
    return out


def fit_relation(stats: list[dict | None]) -> Relation | None:
    """Least squares HR = intercept + slope x speed over the steady parts of many runs (one point per run)."""
    pts = [(s["steady_v"], s["steady_hr"]) for s in stats if s and s.get("steady_v") and s.get("steady_hr")]
    if len(pts) < MIN_RUNS or pstdev(v for v, _ in pts) < MIN_SPEED_SPREAD:
        return None
    mv, mh = mean(v for v, _ in pts), mean(h for _, h in pts)
    den = sum((v - mv) ** 2 for v, _ in pts)
    slope = sum((v - mv) * (h - mh) for v, h in pts) / den
    if slope <= 0:  # faster at a lower heart rate across runs says more about fitness over time than about speed
        slope = 0.0
    intercept = mh - slope * mv
    sd = pstdev(h - (intercept + slope * v) for v, h in pts)
    return Relation(round(intercept, 2), round(slope, 2), round(sd, 2))


def assess(stats: dict | None, relation: Relation | None) -> list[str]:
    """Reason codes for one run (empty when the heart rate looks plausible)."""
    if not stats:
        return []
    out = []
    start = stats["start_hr"]
    if start is not None:
        similar = stats["steady_hr"] is not None and stats["start_v"] >= SIMILAR_SPEED * stats["steady_v"]
        below_self = start < stats["steady_hr"] - LOW_START_BPM if similar else None
        if relation is not None:
            below_relation = start < relation.at(stats["start_v"]) - max(LOW_START_BPM, 3 * relation.sd)
            low = below_relation and below_self is not False
        else:
            low = bool(below_self)
        if low:
            out.append("low_start")
    if stats["flat_s"] >= FLAT_S:
        out.append("flat")
    if stats["dropout_s"] >= DROPOUT_S:
        out.append("dropout")
    return out
