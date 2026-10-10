"""Garmin's intraday data of one calendar day, compact: heart rate, stress, Body Battery, respiration and SpO2 through
the day, plus the sleep that ended that morning (window and stages). One row per day in the `intraday` table
(tools/db.py); the daily summaries stay in `wellness`.

Times are minutes after local midnight of the day, so the night before starts at a negative minute:

    {"hr": [[minute, bpm], ...], "stress": [...], "bb": [...], "resp": [[minute, breaths/min], ...], "spo2": [...],
     "resting", "min", "max", "sleep": {"start", "end", "stages": [[start, end, level]]}}

A series Garmin has nothing for is left out; a day without anything is {}.
"""

from __future__ import annotations

from calendar import timegm
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

# Garmin's sleepLevels.activityLevel; stored as the number, named in the API (api/daily.py)
SLEEP_STAGES = {0: "deep", 1: "light", 2: "rem", 3: "awake"}
SERIES = ("hr", "stress", "bb", "resp", "spo2")

LAST_HOURS_MIN = 120  # "the last two hours of sleep"
MIN_NIGHT_MIN = 180  # a night summary only for a sleep of 3 h or more
# ... with heart rate through the whole night: readings in at least 80% of its half hours, and 12 or more. Spread, not
# a rate: Garmin gives one about every 2 minutes, an Apple Watch every 5 to 10 while asleep.
MIN_COVERAGE = 0.8
COVERAGE_BLOCK_MIN = 30
MIN_READINGS = 12


def _gmt_seconds(text) -> float | None:
    """Garmin's "2026-10-05T22:00:00.0" (GMT, no zone) or epoch milliseconds, as epoch seconds."""
    if text is None or text == "":
        return None
    if isinstance(text, (int, float)):
        return text / 1000
    return datetime.fromisoformat(str(text).replace(" ", "T")).replace(tzinfo=timezone.utc).timestamp()


def _offset(responses: list[dict], sleep_dto: dict, day: str) -> float:
    """Local minus GMT in seconds for this day: from a response's own start timestamps, else the sleep's, else the
    site's zone."""
    for r in responses:
        local, gmt = _gmt_seconds(r.get("startTimestampLocal")), _gmt_seconds(r.get("startTimestampGMT"))
        if local is not None and gmt is not None:
            return local - gmt
    if sleep_dto.get("sleepStartTimestampLocal") and sleep_dto.get("sleepStartTimestampGMT"):
        return (sleep_dto["sleepStartTimestampLocal"] - sleep_dto["sleepStartTimestampGMT"]) / 1000
    return datetime.fromisoformat(f"{day}T12:00").replace(tzinfo=ZoneInfo("Europe/Amsterdam")).utcoffset().total_seconds()


def _series(rows, minute, index: int = 1, digits: int = 0, zero_ok: bool = False) -> list[list]:
    """[[ts, value, ...], ...] -> [[minute, value], ...]. Garmin marks "no data" with None or a negative number
    (stress -1 off the wrist, -2 during an activity): dropped. 0 is a reading only where `zero_ok` (stress, Body Battery)."""
    out: dict[int, float] = {}
    for item in rows or []:
        if not isinstance(item, (list, tuple)) or len(item) <= index or item[0] is None:
            continue
        v = item[index]
        if not isinstance(v, (int, float)) or v < 0 or (v == 0 and not zero_ok):
            continue
        out[minute(_gmt_seconds(item[0]))] = round(v, digits) if digits else int(round(v))
    return [[m, out[m]] for m in sorted(out)]


def _index(descriptors, key: str, default: int) -> int:
    """Where `key` sits in each value array, from Garmin's descriptor list (names differ per endpoint)."""
    for d in descriptors or []:
        name = d.get("key") or d.get("bodyBatteryValueDescriptorKey")
        idx = d.get("index", d.get("bodyBatteryValueDescriptorIndex"))
        if name == key and isinstance(idx, int):
            return idx
    return default


def intraday_from_garmin(day: str, hr: dict | None = None, sleep: dict | None = None, stress: dict | None = None,
                         respiration: dict | None = None, spo2: dict | None = None) -> dict:
    """Garmin's answers for one day -> the compact row (module docstring).
        hr           get_heart_rates       heartRateValues [[ms, bpm | None]], about every 2 min
        sleep        get_sleep_data        dailySleepDTO.sleepStart/EndTimestampLocal|GMT (ms), sleepLevels
        stress       get_stress_data       stressValuesArray [[ms, level]] (every 3 min) and
                                           bodyBatteryValuesArray [[ms, status, level, version]]
        respiration  get_respiration_data  respirationValuesArray [[ms, breaths/min]]
        spo2         get_spo2_data         continuousReadingDTOList [{epochTimestamp, spo2Reading}] or
                                           spO2HourlyAverages [[ms, %]]; only when the watch measured it"""
    midnight = timegm(date.fromisoformat(day).timetuple())  # local midnight as if it were UTC
    hr, stress, respiration, spo2 = hr or {}, stress or {}, respiration or {}, spo2 or {}
    dto = (sleep or {}).get("dailySleepDTO") or {}
    offset = _offset([hr, stress, respiration, spo2], dto, day)

    def minute(epoch_s: float) -> int:
        return round((epoch_s + offset - midnight) / 60)

    out: dict = {}
    series = {
        "hr": _series(hr.get("heartRateValues"), minute),
        "stress": _series(stress.get("stressValuesArray"), minute, _index(stress.get("stressValueDescriptorsDTOList"), "stressLevel", 1), zero_ok=True),
        "bb": _series(stress.get("bodyBatteryValuesArray"), minute, _index(stress.get("bodyBatteryValueDescriptorsDTOList"), "bodyBatteryLevel", 2), zero_ok=True),
        "resp": _series(respiration.get("respirationValuesArray"), minute, 1, digits=1),
    }
    readings = [[r.get("epochTimestamp"), r.get("spo2Reading")] for r in spo2.get("continuousReadingDTOList") or [] if isinstance(r, dict)]
    series["spo2"] = _series(readings or spo2.get("spO2HourlyAverages"), minute)
    out.update({k: v for k, v in series.items() if v})
    if series["hr"]:
        out.update({k: hr[f"{k}HeartRate"] for k in ("resting", "min", "max") if hr.get(f"{k}HeartRate")})

    if dto.get("sleepStartTimestampLocal") and dto.get("sleepEndTimestampLocal"):
        sleep_offset = (dto["sleepStartTimestampLocal"] - dto["sleepStartTimestampGMT"]) / 1000 if dto.get("sleepStartTimestampGMT") else offset
        stages = []
        for lvl in (sleep or {}).get("sleepLevels") or []:
            start, end = _gmt_seconds(lvl.get("startGMT")), _gmt_seconds(lvl.get("endGMT"))
            level = lvl.get("activityLevel")
            if start is None or end is None or level is None or round(level) not in SLEEP_STAGES:
                continue
            a, b = (round((t + sleep_offset - midnight) / 60) for t in (start, end))
            if stages and stages[-1][2] == round(level) and stages[-1][1] == a:
                stages[-1][1] = b  # one segment per stretch
            elif b > a:
                stages.append([a, b, round(level)])
        out["sleep"] = {
            "start": round((dto["sleepStartTimestampLocal"] / 1000 - midnight) / 60),
            "end": round((dto["sleepEndTimestampLocal"] / 1000 - midnight) / 60),
            "stages": stages,
        }
    return out


def _avg(values: list[float]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def night_summary(points: list[list[int]], sleep: dict | None) -> dict | None:
    """Heart rate over the sleep window: {lowest, lowest_at, avg, last_avg, before_avg, rise, minutes}, or None when
    the night is too short or has too few readings. `last_avg` is the last two hours of sleep, `before_avg` the rest,
    `rise` the difference: a few beats is usual towards waking up, a clear rise is what this is meant to show."""
    if not sleep:
        return None
    start, end = sleep["start"], sleep["end"]
    if end - start < MIN_NIGHT_MIN:
        return None
    inside = [(m, v) for m, v in points if start <= m <= end]
    blocks = range(start, end, COVERAGE_BLOCK_MIN)
    covered = {(m - start) // COVERAGE_BLOCK_MIN for m, _ in inside}
    if len(inside) < MIN_READINGS or len(covered) < MIN_COVERAGE * len(blocks):
        return None
    split = end - LAST_HOURS_MIN
    last = [v for m, v in inside if m >= split]
    before = [v for m, v in inside if m < split]
    low_at, low = min(inside, key=lambda p: (p[1], p[0]))
    last_avg, before_avg = _avg(last), _avg(before)
    return {
        "lowest": low,
        "lowest_at": low_at,
        "avg": _avg([v for _, v in inside]),
        "last_avg": last_avg,
        "before_avg": before_avg,
        "rise": last_avg - before_avg if last_avg is not None and before_avg is not None else None,
        "minutes": end - start,
    }
