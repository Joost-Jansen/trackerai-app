"""Fill a database with a synthetic demo account, to try the app (or take screenshots) without real data.

Creates the user `demo` (display name "Demo") with about six months of made-up training: runs, rides and pool swims
with per-second-ish streams (GPS around a few invented loops east of Utrecht, heart rate, pace, altitude), daily sleep
and recovery values, four weeks of heart rate, stress, Body Battery, respiration and SpO2 through the day and night with sleep stages, heart-rate zones, a profile and goals, a marathon plan, a few log entries and an analysis, and gear (two pairs of running shoes, one retired, and a bike).
Afterwards it runs `tools/derive.py` so zone times and routes exist, just like after a real sync.
Nothing here comes from a real person: every number is generated from a fixed random seed.

    DATABASE_URL=postgresql://postgres:dev@127.0.0.1:55432/health python scripts/seed_demo.py           # prints a generated password
    DATABASE_URL=postgresql://postgres:dev@127.0.0.1:55432/health python scripts/seed_demo.py --reset   # delete the demo user first
    DEMO_PASSWORD=... python scripts/seed_demo.py --days 90 --end 2026-10-03

On an empty database the demo user becomes the admin (like the first registration). The login lives in the shared
accounts (packages/accounts): with ACCOUNTS_DATABASE_URL set, the demo user gets its account there. Log in on the site
with username `demo` and the password that was printed (or the one in DEMO_PASSWORD / --password).
"""

from __future__ import annotations

import argparse
import math
import os
import random
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bcrypt

from tools import db
from tools.derive import derive

TZ = ZoneInfo("Europe/Amsterdam")
USERNAME = "demo"
M_PER_DEG_LAT = 111_320.0
HOME = (52.0835, 5.1490)  # a made-up start point east of Utrecht; the loops are invented, not real routes
PERCENT = [70.0, 77.0, 85.0, 92.5]
MAX_HR = {"run": 190, "ride": 183, "swim": 178}


def bounds_for(max_hr: int) -> list[int]:
    """Same rule as api/settings_api.py: Z2 = round(max x P1), Z3..Z5 = round(max x P) + 1."""
    return [round(max_hr * PERCENT[0] / 100)] + [round(max_hr * p / 100) + 1 for p in PERCENT[1:]]


# --- geometry ------------------------------------------------------------------------------------------------------


def _offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    return lat + north_m / M_PER_DEG_LAT, lon + east_m / (M_PER_DEG_LAT * math.cos(math.radians(lat)))


@dataclass
class Loop:
    """A closed, organic-looking loop through HOME (a circle with a few harmonics), scaled to `km`."""

    km: float
    seed: int
    bearing: float = 0.0  # direction from HOME to the loop's centre, degrees

    def __post_init__(self):
        rnd = random.Random(self.seed)
        harmonics = [(k, rnd.uniform(0.04, 0.16) / k**0.6, rnd.uniform(0, 2 * math.pi)) for k in (2, 3, 5, 7)]
        pts = []
        n = 720
        for i in range(n + 1):
            t = 2 * math.pi * i / n
            r = 1 + sum(a * math.sin(k * t + ph) for k, a, ph in harmonics)
            pts.append((r * math.cos(t), r * math.sin(t)))
        # start the loop at the point nearest to the bearing's opposite side, so HOME lies on the loop
        b = math.radians(self.bearing)
        start = min(range(n), key=lambda i: (pts[i][0] + math.sin(b)) ** 2 + (pts[i][1] + math.cos(b)) ** 2)
        pts = pts[start:-1] + pts[:start] + [pts[start]]
        length = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
        scale = self.km * 1000 / length
        x0, y0 = pts[0]
        self.xy = [((x - x0) * scale, (y - y0) * scale) for x, y in pts]  # metres east, north of HOME
        self.cum = [0.0]
        for p, q in zip(self.xy, self.xy[1:]):
            self.cum.append(self.cum[-1] + math.dist(p, q))

    def at(self, dist_m: float, jitter: tuple[float, float] = (0.0, 0.0), origin: tuple[float, float] = HOME) -> list[float]:
        d = dist_m % self.cum[-1]
        lo, hi = 0, len(self.cum) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cum[mid] <= d:
                lo = mid
            else:
                hi = mid
        seg = self.cum[hi] - self.cum[lo] or 1
        f = (d - self.cum[lo]) / seg
        x = self.xy[lo][0] + f * (self.xy[hi][0] - self.xy[lo][0]) + jitter[0]
        y = self.xy[lo][1] + f * (self.xy[hi][1] - self.xy[lo][1]) + jitter[1]
        lat, lon = _offset(*origin, y, x)
        return [round(lat, 6), round(lon, 6)]


RUN_LOOPS = [
    Loop(6.0, seed=37, bearing=260),
    Loop(8.1, seed=11, bearing=40),
    Loop(10.2, seed=23, bearing=150),
    Loop(16.0, seed=41, bearing=100),
    Loop(21.1, seed=43, bearing=70),
    Loop(25.0, seed=47, bearing=330),
    Loop(30.0, seed=59, bearing=120),
]
RIDE_LOOPS = [Loop(52.0, seed=53, bearing=20), Loop(71.0, seed=67, bearing=200), Loop(88.0, seed=71, bearing=300)]


def nearest(loops: list[Loop], km: float) -> Loop:
    """Runs and rides follow a few fixed loops, so the route detection finds regular routes like in real life."""
    return min(loops, key=lambda lp: abs(lp.km - km))


# --- one workout ---------------------------------------------------------------------------------------------------


@dataclass
class Segment:
    metres: float
    speed: float  # m/s
    hr: float  # target heart rate


def simulate(
    sport: str, segments: list[Segment], loop: Loop | None, rnd: random.Random, step: int, origin: tuple[float, float] = HOME
) -> dict:
    """Streams sampled every `step` seconds: heart rate follows its target with a lag and drifts up slowly."""
    t, dist, hr = 0, 0.0, segments[0].hr - 35
    out = {k: [] for k in ("time", "heartrate", "velocity", "distance", "altitude", "cadence")}
    if loop:
        out["latlng"] = []
    total = sum(s.metres for s in segments)
    seg_i, seg_end = 0, segments[0].metres
    wobble = rnd.uniform(0, 2 * math.pi)
    noise = vnoise = 0.0
    jitter = (rnd.uniform(-4, 4), rnd.uniform(-4, 4))
    while dist < total:
        while dist >= seg_end and seg_i < len(segments) - 1:
            seg_i += 1
            seg_end += segments[seg_i].metres
        seg = segments[seg_i]
        vnoise = max(-0.08, min(0.08, 0.985 * vnoise + rnd.gauss(0, 0.006)))  # pace wanders a little, like on the road
        v = max(0.6, seg.speed * (1 + vnoise + 0.01 * math.sin(t / 400 + wobble) + rnd.gauss(0, 0.012)))
        drift = 4.0 * t / 3600
        noise = 0.9 * noise + rnd.gauss(0, 0.5)  # slow wander instead of jitter, like a smoothed wrist sensor
        hr += (seg.hr + drift - hr) * (1 - math.exp(-step / 35))
        out["time"].append(t)
        out["heartrate"].append(round(hr + noise))
        out["velocity"].append(round(v, 2))
        out["distance"].append(round(dist, 1))
        out["altitude"].append(round(2.5 + 2.2 * math.sin(dist / 1700) + 1.1 * math.sin(dist / 430 + 1) + rnd.gauss(0, 0.15), 1))
        out["cadence"].append(round((88 if sport == "ride" else 26 if sport == "swim" else 172 + 10 * (v - 2.9)) + rnd.gauss(0, 1.5)))
        if loop:
            out["latlng"].append(loop.at(dist, (jitter[0] + rnd.gauss(0, 1.2), jitter[1] + rnd.gauss(0, 1.2)), origin))
        t += step
        dist += v * step
    return out


def fastest(streams: dict, metres: float) -> int | None:
    """Fastest time over `metres` anywhere in the workout (Garmin's fastestSplit_*), two pointers over distance."""
    d, tm = streams["distance"], streams["time"]
    if not d or d[-1] < metres:
        return None
    best, j = None, 0
    for i in range(len(d)):
        while j < len(d) and d[j] - d[i] < metres:
            j += 1
        if j == len(d):
            break
        span = tm[j] - tm[i]
        best = span if best is None or span < best else best
    return best


def laps(streams: dict, every_m: float) -> list[dict]:
    d, tm, h, alt = streams["distance"], streams["time"], streams["heartrate"], streams["altitude"]
    out, start, nxt = [], 0, every_m
    for i in range(len(d)):
        if d[i] >= nxt or i == len(d) - 1:
            km = (d[i] - d[start]) / 1000
            if km < 0.05:
                break
            secs = tm[i] - tm[start]
            gain = sum(max(0.0, alt[k + 1] - alt[k]) for k in range(start, i))
            per_km = round(secs / km) if km else 0
            out.append(
                {
                    "distance_km": round(km, 2),
                    "time_s": secs,
                    "avg_hr": round(sum(h[start : i + 1]) / (i + 1 - start)),
                    "pace": f"{per_km // 60}:{per_km % 60:02d}",
                    "elevation_gain_m": round(gain, 1),
                }
            )
            start, nxt = i, nxt + every_m
    return out


def record(sport: str, start: datetime, name: str, streams: dict, garmin_id: int, vo2max: float | None, lap_m: float) -> dict:
    tm, h = streams["time"], streams["heartrate"]
    moving = tm[-1]
    km = streams["distance"][-1] / 1000
    alt = streams["altitude"]
    smooth = [sum(alt[max(0, i - 5) : i + 5]) / len(alt[max(0, i - 5) : i + 5]) for i in range(len(alt))]
    gain = round(sum(max(0.0, b - a) for a, b in zip(smooth, smooth[1:])), 1)
    utc = start.astimezone(UTC)
    raw = {
        "activityId": garmin_id,
        "hasPolyline": "latlng" in streams,
        "calories": round(km * (68 if sport == "run" else 24 if sport == "ride" else 260)),
    }
    if sport == "run":
        if vo2max:
            raw["vO2MaxValue"] = round(vo2max)
        for key, metres in (
            ("fastestSplit_1000", 1000),
            ("fastestSplit_5000", 5000),
            ("fastestSplit_10000", 10000),
            ("fastestSplit_21098", 21097.5),
        ):
            secs = fastest(streams, metres)
            if secs:
                raw[key] = float(secs)
    rec = {
        "start_utc": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_local": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "sport": sport,
        "name": name,
        "distance_km": round(km, 2),
        "moving_time_s": moving,
        "elapsed_time_s": moving + random.Random(garmin_id).randint(10, 90),
        "elevation_gain_m": gain,
        "avg_hr": round(sum(h) / len(h)),
        "max_hr": max(h),
        "avg_cadence_spm": round(sum(streams["cadence"]) / len(streams["cadence"])),
        "laps": laps(streams, lap_m),
        "streams": streams,
        "sources": {"garmin": {"id": garmin_id, "raw": raw}},
    }
    return rec


# --- the training --------------------------------------------------------------------------------------------------


def pace(min_per_km: float) -> float:
    return 1000 / (min_per_km * 60)


def zone_hr(sport: str, zone: int) -> float:
    """A heart rate in the middle of a zone (1..5) for that sport."""
    b = [round(MAX_HR[sport] * 0.6)] + bounds_for(MAX_HR[sport]) + [MAX_HR[sport]]
    return (b[zone - 1] + b[zone]) / 2


def run_workout(kind: str, km: float, fitness: float, rnd: random.Random) -> list[Segment]:
    """`fitness` 0..1 over the six months: easy pace goes from about 5:55 to 5:25 per km."""
    easy = pace(5.92 - 0.5 * fitness + rnd.uniform(-0.06, 0.06))
    if kind == "interval":
        segs = [Segment(2000, easy, zone_hr("run", 2))]
        for _ in range(max(3, min(6, int((km * 1000 - 3000) / 1400)))):
            segs += [Segment(1000, pace(4.35 - 0.25 * fitness), zone_hr("run", 4) + 3), Segment(400, pace(6.6), zone_hr("run", 2) - 4)]
        rest = max(800, km * 1000 - sum(s.metres for s in segs))
        return segs + [Segment(rest, easy * 0.97, zone_hr("run", 2) - 2)]
    if kind == "tempo":
        return [
            Segment(2000, easy, zone_hr("run", 2)),
            Segment(km * 1000 - 4000, pace(4.75 - 0.25 * fitness), zone_hr("run", 3) + 4),
            Segment(2000, easy, zone_hr("run", 2)),
        ]
    if kind == "race":
        return [Segment(km * 1000, pace(4.62 - 0.2 * fitness if km > 15 else 4.3 - 0.2 * fitness), zone_hr("run", 4) + 2)]
    if kind == "recovery":
        return [Segment(km * 1000, easy * 0.93, zone_hr("run", 1) + 4)]
    return [Segment(km * 1000, easy, zone_hr("run", 2) - 1)]


# Weekly pattern: (weekday, sport, kind, distance km in the base phase, in the build phase, zone, description)
WEEK = [
    (1, "run", "interval", 9, 11, "Z4", "5 x 1 km at 10K pace, 400 m jog"),
    (2, "run", "easy run", 7, 9, "Z2", "Easy run"),
    (3, "swim", "technique", 1.8, 2.2, "Z2", "Swim: technique and 4 x 200 m"),
    (4, "run", "recovery", 5, 6, "Z1", "Recovery run, very easy"),
    (5, "ride", "endurance ride", 45, 55, "Z2", "Endurance ride"),
    (6, "run", "long run", 13, 16, "Z2", "Long run"),
]


def plan_sessions(plan_start: date, race: date) -> list[dict]:
    """A 16-week marathon build: long run grows, every fourth week is lighter, two weeks of taper."""
    out = []
    weeks = (race - plan_start).days // 7
    for w in range(weeks + 1):
        monday = plan_start + timedelta(weeks=w)
        light = w % 4 == 3
        taper = weeks - w
        for wd, sport, kind, _base, build, zone, desc in WEEK:
            day = monday + timedelta(days=wd)
            if day > race:
                continue
            km = build * (1 + 0.04 * w)
            if kind == "long run":
                km = min(32, 16 + 1.5 * w)
            elif sport == "run":
                km = min(km, 12)  # the quality sessions and easy runs stay short; the long run carries the build
            if light:
                km *= 0.75
            if taper == 1:
                km *= 0.6
            if taper == 0:
                km *= 0.4
            if day == race:
                continue
            if sport == "run":
                km = nearest(RUN_LOOPS, km).km  # the plan picks one of the regular loops
                if kind == "long run" and km >= 25:
                    desc = f"Long run {km:g} km, last 3 km at marathon pace"
            elif sport == "ride":
                km = nearest(RIDE_LOOPS, km).km
            if sport == "swim":
                out.append(
                    {
                        "date": day.isoformat(),
                        "sport": sport,
                        "kind": kind,
                        "distance_km": 2.0,
                        "duration_min": 45,
                        "target_zone": zone,
                        "description": desc,
                    }
                )
            else:
                km = round(km if sport == "ride" else min(km, 32), 0 if sport == "ride" else 1)
                out.append(
                    {"date": day.isoformat(), "sport": sport, "kind": kind, "distance_km": km, "target_zone": zone, "description": desc}
                )
        if w % 3 == 2 and taper > 2:  # every third week the Wednesday easy run becomes a tempo run
            for s in out:
                if s["date"] == (monday + timedelta(days=2)).isoformat():
                    s.update(
                        kind="tempo", target_zone="Z3", description="Tempo run: 2 km warm-up, the rest at threshold pace, 2 km cool-down"
                    )
    out.append(
        {
            "date": race.isoformat(),
            "sport": "run",
            "kind": "race",
            "distance_km": 42.2,
            "target_zone": "Z3",
            "description": "Marathon: first half at 5:00/km, then by feel",
        }
    )
    return out


# --- seeding -------------------------------------------------------------------------------------------------------


def _local(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), tzinfo=TZ)


PROFILE = """# Profile

Demo athlete (synthetic data, not a real person).

- Has been running for a few years; rides and swims on the side for variety.
- Trains 5 to 6 times a week: 4 runs, 1 ride, 1 swim.
- Weekday evenings, weekend mornings.
- No injuries at the moment.
"""

GOALS = """# Goals

1. **Marathon under 3:30** ({race}).
2. Half marathon under 1:40 (done: {half}).
3. At least 80% of the time in Z1-Z2 every week.
"""

ANALYSIS = """| | Value |
|---|---|
| Time | {time} |
| Average pace | {pace}/km |
| Average heart rate | {hr} bpm |

**Observation.** Evenly paced; in the second half the heart rate rose 5 to 6 beats at the same pace.

**Interpretation.** The aerobic base is good, but the drift shows that runs over 25 km are still missing.

**Advice.** Make the long run 1.5 km longer every week, up to 32 km three weeks before the marathon. Pace stays Z2.
"""


def daily_extras(sleep: float, after_hard: bool, rnd: random.Random) -> dict:
    """The day's other summary values (tools/store.py wellness_from_garmin): sleep detail, respiration, SpO2, sleep
    stress, Body Battery and stress per level, activity. A hard day before shows as a slightly faster breath at night."""
    light = sleep * rnd.uniform(0.5, 0.58)
    moderate, vigorous = rnd.randint(5, 45), rnd.randint(0, 30)
    rest, low, medium = rnd.randint(500, 700), rnd.randint(250, 400), rnd.randint(60, 150)
    return {
        "light_sleep_h": round(light, 2),
        "awake_h": round(rnd.uniform(0.1, 0.5), 2),
        "sleep_resp": round(rnd.gauss(14.2 + (0.5 if after_hard else 0), 0.35), 1),
        "sleep_resp_low": round(rnd.gauss(11.5, 0.4), 1),
        "sleep_stress": round(max(5, rnd.gauss(15 + (4 if after_hard else 0), 3)), 1),
        "spo2_avg": round(rnd.gauss(95.5, 0.6)),
        "spo2_low": round(rnd.gauss(89, 1.5)),
        "bb_charged_sleep": round(max(15, rnd.gauss(58 - (8 if after_hard else 0), 8))),
        "bb_charged": round(max(15, rnd.gauss(62, 9))),
        "bb_drained": round(max(20, rnd.gauss(64, 10))),
        "stress_rest_min": rest,
        "stress_low_min": low,
        "stress_medium_min": medium,
        "stress_high_min": rnd.randint(10, 60),
        "intensity_moderate_min": moderate,
        "intensity_vigorous_min": vigorous,
        "intensity_min": moderate + 2 * vigorous,
        "floors": rnd.randint(2, 18),
        "active_kcal": round(rnd.gauss(650, 180)),
    }


INTRADAY_DAYS = 28  # series through the day for the last four weeks, like a recent sync gives
STEP_MIN = 2  # Garmin gives heart rate and respiration about every 2 minutes, stress and Body Battery every 3


@dataclass
class Night:
    """One synthetic night, in minutes after midnight of the morning it ends (the evening before is negative)."""

    start: int
    end: int
    rhr: float
    resp: float  # breaths/min while asleep
    bb_from: int  # Body Battery when falling asleep and when waking up
    bb_to: int
    stages: list[list[int]]  # [start, end, level] as tools/intraday.py stores them: 0 deep, 1 light, 2 rem, 3 awake
    rise: bool  # heart rate climbs in the last 1.5 hours before waking

    def stage(self, t: int) -> int:
        return next((lvl for a, b, lvl in self.stages if a <= t < b), 1)

    def hr(self, t: int) -> float:
        settle = 9 * math.exp(-(t - self.start) / 70)  # it takes an hour or two to come down after falling asleep
        level = {0: -1.5, 1: 0.5, 2: 3.5, 3: 9.0}[self.stage(t)]
        climb = 28 * max(0.0, (t - (self.end - 95)) / 95) if self.rise else 0.0
        return self.rhr - 1.5 + settle + level + climb

    def stress(self, t: int) -> float:
        return {0: 6, 1: 11, 2: 19, 3: 30}[self.stage(t)] + (12 * max(0.0, (t - (self.end - 95)) / 95) if self.rise else 0)

    def respiration(self, t: int) -> float:
        return self.resp + {0: -0.6, 1: 0.0, 2: 1.0, 3: 1.8}[self.stage(t)]

    def body_battery(self, t: int) -> float:
        return self.bb_from + (self.bb_to - self.bb_from) * min(1.0, max(0.0, (t - self.start) / max(1, self.end - self.start)))


def make_night(day: date, w: dict, rnd: random.Random, rise: bool, bb_from: int) -> Night:
    wake = (7 * 60 + 45 if day.weekday() >= 5 else 6 * 60 + 50) + round(rnd.gauss(0, 18))
    start = wake - round(w.get("sleep_h", 7.2) * 60) - rnd.randint(8, 25)  # time in bed is a bit more than sleep
    stages, t = [], start
    while t < wake:
        frac = (t - start) / max(1, wake - start)
        # 90-minute cycles: deep sleep early in the night, REM growing towards the morning, now and then awake
        parts = [
            (1, rnd.randint(12, 22)),
            (0, max(0, round(rnd.gauss(30 * (1 - frac), 6)))),
            (1, rnd.randint(10, 20)),
            (2, round(8 + 30 * frac)),
        ]
        if rnd.random() < 0.3:
            parts.append((3, rnd.randint(2, 6)))
        for level, minutes in parts:
            if minutes <= 0 or t >= wake:
                continue
            b = min(wake, t + minutes)
            if stages and stages[-1][2] == level:
                stages[-1][1] = b
            else:
                stages.append([t, b, level])
            t = b
    return Night(
        start,
        wake,
        w.get("resting_hr", 50),
        w.get("sleep_resp", 14.2),
        bb_from,
        max(bb_from + 5, w.get("body_battery_high", 85)),
        stages,
        rise,
    )


def seed_intraday(s: db.Scope, end: date, days: int = INTRADAY_DAYS) -> int:
    """Synthetic series through the day (tools/intraday.py's format: heart rate, stress, Body Battery, respiration,
    SpO2 while asleep) and sleep stages for the last `days` days, from the stored sleep, resting HR and Body Battery
    and the activities of each day; the day's sleep window and heart rate while asleep go back into wellness, as the
    sync does. A random seed of its own, so the rest of the demo stays the same."""
    rnd = random.Random(2027)
    wellness = db.load_wellness(s)
    workouts: dict[str, list[tuple[int, int, int]]] = {}
    for a in db.load_activities(s):
        t = datetime.fromisoformat(a["start_local"])
        workouts.setdefault(a["start_local"][:10], []).append(
            (t.hour * 60 + t.minute, round((a.get("moving_time_s") or 0) / 60), a.get("avg_hr") or 140)
        )
    first = end - timedelta(days=days - 1)
    nights: dict[date, Night] = {}
    bb = 30
    for i in range(days + 1):
        d = first + timedelta(days=i)
        w = wellness.get(d.isoformat()) or wellness.get((d - timedelta(days=1)).isoformat()) or {}
        # the last night shows the pre-wake rise the page explains; now and then another night too
        nights[d] = make_night(d, w, rnd, d == end or rnd.random() < 0.12, bb)
        bb = max(8, min(45, round(rnd.gauss(26, 6))))  # where the next evening ends
    wobble = 0.0
    for i in range(days):
        d = first + timedelta(days=i)
        night, tonight = nights[d], nights[d + timedelta(days=1)]
        bed = 1440 + tonight.start
        walks = [rnd.randint(night.end + 30, 1200) for _ in range(rnd.randint(2, 4))]
        todays = workouts.get(d.isoformat(), [])
        stop = night.end + 100 if d == end else 1440  # today: up to shortly after getting up
        row: dict[str, list] = {"hr": [], "stress": [], "bb": [], "resp": [], "spo2": []}
        for m in range(0, stop):
            in_workout = next((avg for start, minutes, avg in todays if start <= m < start + minutes), None)
            asleep = m < night.end or m >= bed
            sleeper = night if m < night.end else tonight
            t = m if m < night.end else m - 1440
            if m % STEP_MIN == 0 and rnd.random() > 0.01:  # a missed reading now and then
                wobble = 0.75 * wobble + rnd.gauss(0, 0.9)
                if asleep:
                    v = sleeper.hr(t)
                else:
                    # awake: higher after getting up, slowly lower towards the evening, bumps for walking and workouts
                    frac = (m - night.end) / max(1, bed - night.end)
                    v = night.rhr + 21 - 11 * frac + 4 * rnd.random() + (22 if any(w <= m < w + 15 for w in walks) else 0)
                    if in_workout:
                        v = in_workout + rnd.gauss(0, 5)
                row["hr"].append([m, max(38, round(v + wobble))])
                if in_workout is None:  # Garmin has no respiration during an activity
                    r = sleeper.respiration(t) if asleep else 15.5 + 2 * rnd.random()
                    row["resp"].append([m, round(r + rnd.gauss(0, 0.3), 1)])
                if asleep:
                    row["spo2"].append([m, max(88, min(100, round(rnd.gauss(95.5, 1.1))))])
            if m % 3 == 0:
                if in_workout is None:  # -2 during an activity: left out, as the sync does
                    st = sleeper.stress(t) if asleep else 24 + 22 * rnd.random() + (25 if rnd.random() < 0.08 else 0)
                    row["stress"].append([m, max(0, min(99, round(st + rnd.gauss(0, 3))))])
                if asleep:
                    level = sleeper.body_battery(t)
                else:
                    frac = (m - night.end) / max(1, bed - night.end)
                    level = night.bb_to - (night.bb_to - tonight.bb_from) * frac
                row["bb"].append([m, max(5, min(100, round(level)))])
        hr = row["hr"]
        db.write_intraday(
            s,
            d.isoformat(),
            {
                **row,
                "resting": round(night.rhr),
                "min": min(v for _, v in hr),
                "max": max(v for _, v in hr),
                "sleep": {"start": night.start, "end": night.end, "stages": night.stages},
            },
        )
        asleep_hr = [v for m, v in hr if night.start <= m <= night.end]
        w = dict(wellness.get(d.isoformat()) or {})
        if w:
            local = lambda minute: (datetime.combine(d, time()) + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M")  # noqa: E731, B023  # used within this iteration only
            w.update(
                {
                    "sleep_start": local(night.start),
                    "sleep_end": local(night.end),
                    "sleep_hr": round(sum(asleep_hr) / len(asleep_hr)) if asleep_hr else None,
                    "bb_charged_sleep": night.bb_to - night.bb_from,
                    "body_battery_high": night.bb_to,
                    "body_battery_low": tonight.bb_from,
                }
            )
            db.write_wellness(s, d.isoformat(), {k: v for k, v in w.items() if v is not None})
    return days


def seed(
    engine,
    end: date,
    days: int = 182,
    password: str | None = None,
    reset: bool = False,
    *,
    username: str = USERNAME,
    display_name: str = "Demo",
    home: tuple[float, float] = HOME,
    login: bool = True,
) -> dict:
    """`username`, `display_name` and `home` (the made-up start point of every loop) let api/example.py reuse this for its
    read-only example account; `login=False` gives that account no usable password and no admin rights."""
    db.create_schema(engine)
    existing = db.get_user_by_name(engine, username)
    if existing:
        if not reset:
            raise SystemExit(f"user '{username}' exists already; use --reset to replace it")
        db.delete_user(engine, existing["id"])
    first = login and db.count_users(engine) == 0
    password = (password or secrets.token_urlsafe(12)) if login else None
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode() if login else "!"  # "!" never matches
    uid = db.create_user(engine, username, password_hash, is_admin=first, display_name=display_name)
    s = db.Scope(engine, uid)
    rnd = random.Random(2026)

    zones = {sport: {"max_hr": mx, "bounds": bounds_for(mx), "estimate": sport != "run"} for sport, mx in MAX_HR.items()}
    db.set_setting(s, "zones", zones)
    db.set_setting(s, "zones_model", {"percent": PERCENT})
    db.set_setting(s, "profile_facts", {"birth_year": 1991, "weight_kg": 72.0, "height_cm": 181.0, "resting_hr": 49})

    start = end - timedelta(days=days)
    race = end + timedelta(days=(6 - end.weekday()) % 7 + 35)  # a Sunday five to six weeks ahead
    plan_start = race - timedelta(weeks=16) - timedelta(days=race.weekday())
    half = plan_start + timedelta(weeks=4, days=6)  # a half marathon as a test, in week 5 of the plan
    ten_k = start + timedelta(days=(6 - start.weekday()) % 7 + 35)
    sessions = plan_sessions(plan_start, race)
    planned = {(x["date"], x["sport"]): x for x in sessions}

    gid, count = 9_000_000_000, 0
    hard_days: set[date] = set()
    half_result = None
    day = start
    while day <= end:
        fitness = (day - start).days / max(1, days)
        wd = day.weekday()
        todo: list[tuple[str, str, float, str]] = []  # sport, kind, km, name
        if day == half:
            todo = [("run", "race", 21.1, "Half marathon")]
        elif day == ten_k:
            todo = [("run", "race", 10.0, "10 km race")]
        elif day >= plan_start:
            for (d, sport), x in planned.items():
                if d == day.isoformat() and day < end + timedelta(days=1):
                    km = x.get("distance_km") or 2.0
                    label = {
                        "interval": "Interval training",
                        "tempo": "Tempo run",
                        "recovery": "Recovery run",
                        "long run": "Long run",
                        "easy run": "Easy run",
                        "endurance ride": "Endurance ride",
                        "technique": "Swim",
                    }.get(x["kind"], x["kind"].capitalize())
                    todo.append((sport, x["kind"], km, label))
        else:
            for w, sport, kind, base, _build, _zone, _desc in WEEK:
                if w == wd:
                    km = base * (0.9 + 0.2 * fitness)
                    label = {
                        "interval": "Interval training",
                        "recovery": "Recovery run",
                        "long run": "Long run",
                        "easy run": "Easy run",
                        "endurance ride": "Endurance ride",
                        "technique": "Swim",
                    }[kind]
                    todo.append((sport, kind, km, label))
        if day == end:
            todo = []  # today: nothing done yet, so the dashboard shows today's session as planned
        for sport, kind, km, name in todo:
            if rnd.random() < 0.07 and kind != "race":
                continue  # a missed session now and then
            gid += rnd.randint(50, 400)
            evening = wd < 5
            when = _local(day, 18 if evening else 9, rnd.choice((0, 5, 10, 20, 30, 40)))
            if sport == "run":
                lap = 1000
                kind_for_sim = "race" if kind == "race" else "long" if kind == "long run" else kind
                loop = nearest(RUN_LOOPS, km)
                if kind == "race":
                    when = _local(day, 10 if km > 15 else 11, 0)
                else:
                    km = loop.km
                segs = run_workout("easy run" if kind_for_sim == "long" else kind_for_sim, km, fitness, rnd)
                step = 2
            elif sport == "ride":
                lap, step = 5000, 3
                loop = nearest(RIDE_LOOPS, km)
                km = loop.km
                v = (26.5 + 2.5 * fitness + rnd.uniform(-1, 1)) / 3.6
                segs = [Segment(km * 1000, v, zone_hr("ride", 2))]
                name = "Endurance ride"
            else:
                lap, step, loop = 100, 5, None
                metres = 1800 + 400 * fitness + rnd.choice((0, 100, 200))
                v = 100 / (118 - 10 * fitness)
                segs = [
                    Segment(400, v * 0.92, zone_hr("swim", 1) + 4),
                    Segment(metres - 600, v, zone_hr("swim", 2)),
                    Segment(200, v * 0.9, zone_hr("swim", 1) + 6),
                ]
                name = "Pool swim"
            streams = simulate(sport, segs, loop, rnd, step, home)
            vo2 = 49 + 4 * fitness + rnd.uniform(-0.6, 0.6) if sport == "run" and kind != "recovery" else None
            rec = record(sport, when, name, streams, gid, vo2, lap)
            db.upsert_activity(s, rec)
            count += 1
            if kind in ("interval", "race", "tempo") or km >= 20:
                hard_days.add(day)
            if day == half:
                half_result = rec
        day += timedelta(days=1)

    # sleep and recovery: resting HR slowly drops with fitness and is a bit higher after hard days.
    # `more` draws the values added later (respiration, sleep stress, ...), so the older ones stay as they were.
    more = random.Random(2028)
    for i in range(days + 1):
        d = start + timedelta(days=i)
        fitness = i / max(1, days)
        after_hard = (d - timedelta(days=1)) in hard_days
        rhr = round(52 - 4 * fitness + (2.5 if after_hard else 0) + rnd.gauss(0, 1.1))
        sleep = max(5.4, min(9.0, rnd.gauss(7.4 if d.weekday() >= 4 else 7.1, 0.55)))
        db.write_wellness(
            s,
            d.isoformat(),
            {
                "sleep_h": round(sleep, 2),
                "deep_sleep_h": round(sleep * rnd.uniform(0.17, 0.23), 2),
                "rem_sleep_h": round(sleep * rnd.uniform(0.2, 0.26), 2),
                "sleep_score": max(45, min(97, round(60 + (sleep - 6) * 11 + rnd.gauss(0, 5) - (6 if after_hard else 0)))),
                "resting_hr": rhr,
                "hrv_last_night": round(rnd.gauss(58 + 8 * fitness - (6 if after_hard else 0), 5)),
                "hrv_status": "BALANCED",
                "body_battery_high": max(40, min(100, round(rnd.gauss(84 - (8 if after_hard else 0), 6)))),
                "body_battery_low": max(5, min(45, round(rnd.gauss(24, 6)))),
                "stress_avg": max(12, min(55, round(rnd.gauss(29, 5)))),
                "steps": max(3000, round(rnd.gauss(10500, 2500))),
                **daily_extras(sleep, after_hard, more),
            },
        )

    intraday_days = seed_intraday(s, end, min(INTRADAY_DAYS, days + 1))
    db.set_setting(s, "sync_state", {"last_sync_local": f"{end.isoformat()} 06:02"})
    db.set_setting(
        s,
        "onboarding",
        {
            "choice": "claude",
            "done": True,
            "step": 0,
            "hidden": ["checklist", "data"],
            "visited": ["dashboard", "trends", "routes", "history"],
        },
    )

    half_time = half_result["moving_time_s"] if half_result else 0
    half_pace = round(half_time / 21.1) if half_result else 0
    db.put_document(s, "profile", PROFILE, username)
    db.put_document(s, "goals", GOALS.format(race=race.isoformat(), half=half.isoformat()), username)
    pid = db.create_plan(
        s,
        "Marathon in 16 weeks",
        username,
        goal="Marathon under 3:30",
        race=f"Marathon, {race.isoformat()}",
        notes="Built in four-week blocks: three weeks up, one week down. The long run grows to 32 km; "
        "the last two weeks are the taper. Intervals on Tuesday, a tempo run every third Wednesday.",
    )
    db.add_sessions(s, pid, sessions)
    if half_result:
        db.add_entry(
            s,
            "analysis",
            "Half marathon: review",
            ANALYSIS.format(
                time=f"{half_time // 3600}:{half_time % 3600 // 60:02d}:{half_time % 60:02d}",
                pace=f"{half_pace // 60}:{half_pace % 60:02d}",
                hr=half_result["avg_hr"],
            ),
            "agent",
            day=(half + timedelta(days=1)).isoformat(),
        )
    db.add_entry(
        s,
        "log",
        "Marathon plan started",
        "- Question: a plan for a marathon under 3:30\n- Data: running 4 times a week, long run 14 km\n"
        "- Decision: 16 weeks, built in blocks of 4, see Plan",
        "agent",
        day=plan_start.isoformat(),
    )
    db.add_entry(
        s,
        "log",
        "Weekly review",
        "- Question: how did this week go?\n- Data: 82% in Z1-Z2, resting heart rate stable\n"
        "- Advice: keep going; make Saturday's ride a bit shorter before the long run",
        "agent",
        day=(end - timedelta(days=2)).isoformat(),
    )
    db.add_entry(
        s,
        "log",
        "Heavy legs after intervals",
        "Calves stiff after the 1000s. Recovery run tomorrow instead of the easy run.",
        username,
        day=(end - timedelta(days=9)).isoformat(),
    )

    # Gear: the old shoes ran until the plan started and then retired, the new pair is the default for runs since then,
    # and a bike for rides. derive() below links the activities to the defaults (db.apply_gear_defaults).
    old = db.create_gear(
        s,
        kind="shoes",
        name="Ghost 15",
        brand="Brooks",
        model="Ghost 15",
        start_km=520.0,
        retired_on=(plan_start - timedelta(days=1)).isoformat(),
    )
    new = db.create_gear(s, kind="shoes", name="Pegasus 41", brand="Nike", model="Pegasus 41", start_km=60.0, since=plan_start.isoformat())
    bike = db.create_gear(s, kind="bike", name="Endurace", brand="Canyon", model="Endurace CF 7", start_km=3200.0)
    db.set_setting(s, db.GEAR_DEFAULTS_KEY, {"run": new["id"], "ride": bike["id"]})
    for a in db.load_activities(s):
        if a["sport"] == "run" and a["start_local"][:10] < plan_start.isoformat():
            db.set_activity_gear(s, a["id"], [old["id"]])  # the runs before the plan: chosen on the activity
    derived = derive(s)
    run_names = ("Short loop", "Park loop", "Along the river", "Big loop", "Half marathon loop", "Long loop", "Thirty")
    ride_names = ("Polder loop", "Lakes loop", "Dike loop")
    names = {"run": {lp.km: n for lp, n in zip(RUN_LOOPS, run_names)}, "ride": {lp.km: n for lp, n in zip(RIDE_LOOPS, ride_names)}}
    routes = db.load_routes(s)
    for r in routes:
        by_km = names.get(r.get("sport", "run"), {})
        km = min(by_km, key=lambda k: abs(k - r["distance_km"]), default=None)
        if km is not None and abs(km - r["distance_km"]) < 1.5:
            r["name"] = by_km[km]
    db.save_routes(s, routes)
    return {
        "user_id": uid,
        "admin": first,
        "password": password,
        "activities": count,
        "plan_id": pid,
        "intraday_days": intraday_days,
        **derived,
    }


def link_account(accounts, engine, username: str = USERNAME) -> None:
    """Give the seeded user its trackerai account, with the password `seed` set. After a --reset the existing account
    is linked to the new user and keeps its password."""
    row = db.get_user_by_name(engine, username, with_hash=True)
    account = accounts.by_username(username)
    if account:
        accounts.set_local_key(account["id"], "health", str(row["id"]))
    else:
        accounts.create_linked(username, row["password_hash"], "health", str(row["id"]), is_admin=bool(row["is_admin"]))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--end", type=date.fromisoformat, default=datetime.now(TZ).date(), help="last day with data (default today)")
    p.add_argument("--days", type=int, default=182, help="how many days of history (default 182)")
    p.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"), help="password for the demo user (default: generated)")
    p.add_argument("--reset", action="store_true", help="delete an existing demo user with all its data first")
    args = p.parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        p.error("set DATABASE_URL, e.g. postgresql://postgres:dev@127.0.0.1:55432/health (compose.dev.yml)")
    engine = db.connect(url)
    out = seed(engine, args.end, args.days, args.password, args.reset)
    shown = out.pop("password")
    print(out)
    if os.environ.get("ACCOUNTS_DATABASE_URL"):
        from trackerai_accounts import open_accounts

        link_account(open_accounts(), engine)
    else:
        print("ACCOUNTS_DATABASE_URL is not set: the demo user has no account to log in with yet")
    if not args.password:
        print(f"log in as '{USERNAME}' with password: {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
