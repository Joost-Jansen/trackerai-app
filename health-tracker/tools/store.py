"""Normalise Garmin and Strava data and store it as one JSON file per activity / per day.

Layout:
    data/activities/YYYY/YYYY-MM-DD_HHMM_<sport>.json   one activity, merged from all sources
    data/wellness/YYYY/YYYY-MM-DD.json                  sleep, HRV, resting HR, Body Battery, readiness
    data/raw/fit/YYYY/<garmin id>.zip                   original Garmin FIT download
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tools.sports import garmin_sport, strava_sport

MATCH_WINDOW_S = 120
# Which source wins for a scalar field when both have it; default is garmin first.
# `manual`: what the user corrected on the site (tools/distance.py), always first.
FIELD_PRIORITY = {"name": ("strava", "garmin", "wahoo_api", "wahoo", "fit", "apple"), "distance_km": ("manual", "garmin", "strava", "wahoo_api", "wahoo", "fit", "apple")}
# Uploaded FIT files (Wahoo, or any other device) come after the synced sources. A Wahoo cloud connection needs a
# source name of its own, so that remove_source() on disconnect leaves the files someone uploaded themselves.
# apple: an Apple Health import (tools/apple_import.py), last: a Garmin or FIT recording of the same session is the
# device's own file, Apple's is a summary of what the phone stored.
DEFAULT_PRIORITY = ("garmin", "strava", "wahoo_api", "wahoo", "fit", "apple")  # wahoo_api: the Wahoo cloud connection (tools/wahoo.py)
SCALAR_FIELDS = (
    "name",
    "distance_km",
    "moving_time_s",
    "elapsed_time_s",
    "elevation_gain_m",
    "avg_hr",
    "max_hr",
    "avg_cadence_spm",
)

# Which activity this is: kept when one source of a merged activity is removed.
IDENTITY_FIELDS = ("start_utc", "start_local", "sport")

STRAVA_STREAM_KEYS = {
    "time": "time", "latlng": "latlng", "heartrate": "heartrate", "velocity_smooth": "velocity",
    "altitude": "altitude", "cadence": "cadence", "distance": "distance", "watts": "watts",
}


def _round(value, digits=0):
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


def _pace(seconds: float, km: float) -> str | None:
    if not km:
        return None
    total = round(seconds / km)
    return f"{total // 60}:{total % 60:02d}"


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def from_strava(activity: dict, streams: dict | None) -> dict:
    sport = strava_sport(activity.get("sport_type") or activity.get("type"))
    cadence = activity.get("average_cadence")
    if cadence is not None and sport == "run":
        cadence *= 2
    record = {
        "start_utc": activity["start_date"],
        "start_local": activity["start_date_local"].rstrip("Z"),
        "sport": sport,
        "name": activity.get("name"),
        "distance_km": _round(activity.get("distance", 0) / 1000, 2),
        "moving_time_s": activity.get("moving_time"),
        "elapsed_time_s": activity.get("elapsed_time"),
        "elevation_gain_m": activity.get("total_elevation_gain"),
        "avg_hr": _round(activity.get("average_heartrate")),
        "max_hr": _round(activity.get("max_heartrate")),
        "avg_cadence_spm": _round(cadence),
        "sources": {"strava": {"id": activity["id"], "raw": activity}},
    }
    if streams:
        record["streams"] = {
            ours: streams[theirs]["data"] for theirs, ours in STRAVA_STREAM_KEYS.items() if theirs in streams
        }
    return _drop_none(record)


def _elapsed_s(activity: dict) -> float | None:
    """Garmin's activity list has given `elapsedDuration` in milliseconds next to `duration` in seconds."""
    elapsed, duration = activity.get("elapsedDuration"), activity.get("duration")
    if elapsed and duration and elapsed > duration * 10:
        return elapsed / 1000
    return elapsed or duration


def _moving_s(activity: dict) -> float | None:
    """Garmin's moving time, except for an open-water swim: there it is broken (3 minutes for a 45-minute swim), the
    timer time is right."""
    if (activity.get("activityType") or {}).get("typeKey") == "open_water_swimming":
        return activity.get("duration") or activity.get("movingDuration")
    return activity.get("movingDuration") or activity.get("duration")


def garmin_summary(detail: dict) -> dict:
    """An activity from Garmin's detail endpoint (get_activity: summaryDTO, activityTypeDTO), as the activity list
    gives it, so from_garmin reads both. Multisport legs only come this way."""
    s = detail.get("summaryDTO") or {}
    clock = lambda v: v.replace("T", " ").split(".")[0] if v else v  # noqa: E731  "2021-04-11T12:36:16.0"
    return {
        **s,
        "activityId": detail["activityId"],
        "activityName": detail.get("activityName"),
        "activityType": detail.get("activityTypeDTO") or {},
        "parentId": detail.get("parentId"),
        "startTimeLocal": clock(s.get("startTimeLocal")),
        "startTimeGMT": clock(s.get("startTimeGMT")),
        "averageRunningCadenceInStepsPerMinute": s.get("averageRunCadence"),
        "averageBikingCadenceInRevPerMinute": s.get("averageBikeCadence"),
    }


def from_garmin(activity: dict, splits: dict | None, fit_file: str | None = None, streams: dict | None = None) -> dict:
    laps = []
    for lap in (splits or {}).get("lapDTOs", []):
        km = (lap.get("distance") or 0) / 1000
        laps.append(
            _drop_none(
                {
                    "distance_km": _round(km, 2),
                    "time_s": _round(lap.get("duration")),
                    "avg_hr": _round(lap.get("averageHR")),
                    "pace": _pace(lap.get("duration") or 0, km),
                    "elevation_gain_m": lap.get("elevationGain"),
                }
            )
        )
    cadence = activity.get("averageRunningCadenceInStepsPerMinute") or activity.get("averageBikingCadenceInRevPerMinute")
    record = {
        "start_utc": activity["startTimeGMT"].replace(" ", "T") + "Z",
        "start_local": activity["startTimeLocal"].replace(" ", "T"),
        "sport": garmin_sport(activity.get("activityType")),
        "open_water": (activity.get("activityType") or {}).get("typeKey") == "open_water_swimming" or None,
        "name": activity.get("activityName"),
        "distance_km": _round((activity.get("distance") or 0) / 1000, 2),
        "moving_time_s": _round(_moving_s(activity)),
        "elapsed_time_s": _round(_elapsed_s(activity)),
        "elevation_gain_m": activity.get("elevationGain"),
        "avg_hr": _round(activity.get("averageHR")),
        "max_hr": _round(activity.get("maxHR")),
        "avg_cadence_spm": _round(cadence),
        "laps": laps or None,
        "fit_file": fit_file,
        "streams": streams or None,
        "sources": {"garmin": {"id": activity["activityId"], "raw": activity}},
    }
    return _drop_none(record)


def from_fit(activity: dict, fit_file: str | None = None, filename: str | None = None, source: str | None = None,
             name: str | None = None, meta: dict | None = None) -> dict:
    """A record from tools.fit.read_fit_activity. Source `wahoo` for an uploaded Wahoo file, else `fit`; the Wahoo
    connection passes its own (`wahoo_api`), with the workout's name and id."""
    source = source or ("wahoo" if "wahoo" in activity.get("manufacturer", "") else "fit")
    laps = []
    for lap in activity.get("laps") or []:
        km = (lap.get("distance_m") or 0) / 1000
        laps.append(_drop_none({
            "distance_km": _round(km, 2), "time_s": _round(lap.get("time_s")), "avg_hr": _round(lap.get("avg_hr")),
            "pace": _pace(lap.get("time_s") or 0, km), "elevation_gain_m": lap.get("ascent_m"),
        }))
    sport = activity["sport"]
    label = {"ride": "Cycling", "run": "Running", "swim": "Swimming"}.get(sport, sport.capitalize())
    cadence = activity.get("avg_cadence")
    if cadence is not None and sport == "run":
        cadence *= 2  # FIT stores running cadence per leg
    record = {
        "start_utc": activity["start_utc"],
        "start_local": activity["start_local"],
        "sport": sport,
        "name": name or f"{'Wahoo' if source.startswith('wahoo') else 'FIT'} {label}",  # like Garmin's "Amsterdam Cycling"
        "distance_km": _round((activity.get("distance_m") or 0) / 1000, 2),
        "moving_time_s": _round(activity.get("timer_s")),
        "elapsed_time_s": _round(activity.get("elapsed_s") or activity.get("timer_s")),
        "elevation_gain_m": activity.get("ascent_m"),
        "avg_hr": _round(activity.get("avg_hr")),
        "max_hr": _round(activity.get("max_hr")),
        "avg_cadence_spm": _round(cadence),
        "avg_power_w": _round(activity.get("avg_power")),
        "indoor": activity.get("indoor") or None,
        "open_water": activity.get("open_water") or None,
        "laps": laps or None,
        "fit_file": fit_file,
        "streams": activity.get("streams") or None,
        "sources": {source: {"file": filename, "manufacturer": activity.get("manufacturer") or None, **(meta or {})}},
    }
    return _drop_none(record)


def _parse_utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _activities_dir(root: Path) -> Path:
    return Path(root) / "data" / "activities"


def _find_match(root: Path, record: dict) -> Path | None:
    start = _parse_utc(record["start_utc"])
    day = date.fromisoformat(record["start_local"][:10])
    for offset in (0, -1, 1):
        d = day + timedelta(days=offset)
        for path in _activities_dir(root).glob(f"{d.year}/{d.isoformat()}_*.json"):
            existing = json.loads(path.read_text())
            if abs((_parse_utc(existing["start_utc"]) - start).total_seconds()) <= MATCH_WINDOW_S:
                return path
    return None


def delete_activity_by_source(root: Path, source: str, source_id, day: str) -> None:
    """Remove the activity file that `source` sent as `source_id`, started around `day`."""
    d = date.fromisoformat(day)
    for offset in (0, -1, 1):
        x = d + timedelta(days=offset)
        for path in _activities_dir(root).glob(f"{x.year}/{x.isoformat()}_*.json"):
            if str(json.loads(path.read_text()).get("sources", {}).get(source, {}).get("id")) == str(source_id):
                path.unlink()


def _rank(source: str, key: str | None = None) -> int:
    order = FIELD_PRIORITY.get(key, DEFAULT_PRIORITY)
    return order.index(source) if source in order else len(order)


def pick_scalars(record: dict) -> dict:
    """Set each scalar field from the highest-priority source that has it; drop a field no source has (any more)."""
    sources = record.get("sources", {})
    for key in SCALAR_FIELDS:
        record.pop(key, None)
        for src in FIELD_PRIORITY.get(key, DEFAULT_PRIORITY):
            value = sources.get(src, {}).get("fields", {}).get(key)
            if value is not None:
                record[key] = value
                break
    return record


def _merge(existing: dict, incoming: dict) -> dict:
    """Keep non-scalar data (streams, laps, fit_file) from whoever has it; pick scalars by source priority.

    `owners` remembers which source gave each non-scalar field. A lower-priority source never overwrites what a
    higher one gave (an uploaded Wahoo file does not replace Garmin's laps), and remove_source() knows what to take
    out when a connection is ended.
    """
    (src,) = incoming["sources"]
    owners = dict(existing.get("owners") or {})
    merged = {k: v for k, v in existing.items() if k not in SCALAR_FIELDS}
    for key, value in incoming.items():
        if key in SCALAR_FIELDS or key in ("sources", "owners"):
            continue
        owner = owners.get(key)
        if key in merged and owner and owner != src and _rank(owner) < _rank(src):
            continue
        merged[key] = value
        owners[key] = src
    merged["sources"] = {**existing.get("sources", {}), **incoming["sources"]}
    merged["owners"] = owners
    return pick_scalars(merged)


def remove_source(record: dict, source: str) -> dict | None:
    """The record without what `source` gave, or None when nothing else is left. Identity fields stay."""
    sources = {k: v for k, v in record.get("sources", {}).items() if k != source}
    if not set(sources) - {"manual"}:  # a correction alone (tools/distance.py) is no activity
        return None
    owners = dict(record.get("owners") or {})
    out = {k: v for k, v in record.items() if owners.get(k) != source or k in IDENTITY_FIELDS}
    out["sources"] = sources
    out["owners"] = {k: v for k, v in owners.items() if v != source}
    return pick_scalars(out)


def prepare(record: dict) -> dict:
    """Keep each source's own scalar values next to it, so a later merge can pick by source priority."""
    (src,) = record["sources"]
    record = dict(record)
    record["sources"] = {src: dict(record["sources"][src], fields={k: record[k] for k in SCALAR_FIELDS if k in record})}
    return record


def activity_id(record: dict) -> str:
    return record["start_local"][:16].replace("T", "_").replace(":", "") + "_" + record["sport"]


def source_distance(sources: dict) -> float | None:
    """The distance the sources give, in priority order (without a correction: what the device measured)."""
    for src in FIELD_PRIORITY["distance_km"]:
        km = ((sources.get(src) or {}).get("fields") or {}).get("distance_km")
        if km is not None:
            return km
    raw = (sources.get("garmin") or {}).get("raw") or {}
    return round(raw["distance"] / 1000, 2) if raw.get("distance") else None


def same_start(a: dict, b: dict) -> bool:
    return abs((_parse_utc(a["start_utc"]) - _parse_utc(b["start_utc"])).total_seconds()) <= MATCH_WINDOW_S


def merge(existing: dict, incoming: dict) -> dict:
    return _merge(existing, incoming)


def upsert_activity(root: Path, record: dict) -> Path:
    """Write the record, merging with an existing file for the same activity (±2 min)."""
    record = prepare(record)
    path = _find_match(root, record)
    if path is None:
        path = _activities_dir(root) / record["start_local"][:4] / f"{activity_id(record)}.json"
        merged = _merge({}, record)
    else:
        merged = _merge(json.loads(path.read_text()), record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    return path


def load_activities(root: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(_activities_dir(root).glob("*/*.json"))]


def _local_clock(ms) -> str | None:
    """Garmin's "...TimestampLocal" (local wall time as epoch ms) as "2026-10-04T23:10"."""
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M") if ms else None


def wellness_from_garmin(sleep: dict | None, hrv: dict | None, summary: dict | None, readiness: list | None) -> dict:
    """The day's summary values from the responses the sync already fetches (no extra calls): sleep (get_sleep_data:
    dailySleepDTO and the top-level bodyBatteryChange), HRV, the user summary (get_user_summary) and readiness."""
    sleep_dto = (sleep or {}).get("dailySleepDTO") or {}
    hrv_sum = (hrv or {}).get("hrvSummary") or {}
    summary = summary or {}
    ready = (readiness or [{}])[0] if readiness else {}

    def hours(seconds):
        return round(seconds / 3600, 2) if seconds else None

    def minutes(seconds):
        return round(seconds / 60) if isinstance(seconds, (int, float)) and seconds >= 0 else None

    def num(v, digits=0):
        return (round(v, digits) if digits else round(v)) if isinstance(v, (int, float)) and v > 0 else None

    moderate, vigorous = summary.get("moderateIntensityMinutes"), summary.get("vigorousIntensityMinutes")

    has_sleep = bool(sleep_dto.get("sleepTimeSeconds"))
    values = _drop_none(
        {
            "sleep_h": hours(sleep_dto.get("sleepTimeSeconds")),
            "deep_sleep_h": hours(sleep_dto.get("deepSleepSeconds")),
            "rem_sleep_h": hours(sleep_dto.get("remSleepSeconds")),
            "light_sleep_h": hours(sleep_dto.get("lightSleepSeconds")),
            "awake_h": hours(sleep_dto.get("awakeSleepSeconds")) if has_sleep else None,
            "sleep_start": _local_clock(sleep_dto.get("sleepStartTimestampLocal")) if has_sleep else None,
            "sleep_end": _local_clock(sleep_dto.get("sleepEndTimestampLocal")) if has_sleep else None,
            "sleep_stress": num(sleep_dto.get("avgSleepStress"), 1),
            "sleep_resp": num(sleep_dto.get("averageRespirationValue"), 1),
            "sleep_resp_low": num(sleep_dto.get("lowestRespirationValue"), 1),
            # the night's SpO2 from the sleep, else the day's from the summary; only when the watch measured it
            "spo2_avg": num(sleep_dto.get("averageSpO2Value") or summary.get("averageSpo2")),
            "spo2_low": num(sleep_dto.get("lowestSpO2Value") or summary.get("lowestSpo2")),
            "bb_charged_sleep": num((sleep or {}).get("bodyBatteryChange") or sleep_dto.get("bodyBatteryChange")) if has_sleep else None,
            "sleep_score": ((sleep_dto.get("sleepScores") or {}).get("overall") or {}).get("value"),
            "hrv_last_night": hrv_sum.get("lastNightAvg"),
            "hrv_weekly_avg": hrv_sum.get("weeklyAvg"),
            "hrv_status": hrv_sum.get("status"),
            # without an overnight recording Garmin estimates resting HR from daytime data, which is unreliable
            "resting_hr": summary.get("restingHeartRate") if has_sleep else None,
            "body_battery_high": summary.get("bodyBatteryHighestValue"),
            "body_battery_low": summary.get("bodyBatteryLowestValue"),
            "stress_avg": summary.get("averageStressLevel"),
            "steps": summary.get("totalSteps"),
            "bb_charged": summary.get("bodyBatteryChargedValue"),
            "bb_drained": summary.get("bodyBatteryDrainedValue"),
            "stress_rest_min": minutes(summary.get("restStressDuration")),
            "stress_low_min": minutes(summary.get("lowStressDuration")),
            "stress_medium_min": minutes(summary.get("mediumStressDuration")),
            "stress_high_min": minutes(summary.get("highStressDuration")),
            # Garmin counts a vigorous minute double towards the weekly goal; the total follows that convention
            "intensity_min": (moderate or 0) + 2 * (vigorous or 0) if moderate is not None or vigorous is not None else None,
            "intensity_moderate_min": moderate,
            "intensity_vigorous_min": vigorous,
            "floors": num(summary.get("floorsAscended")) if summary.get("floorsAscended") is not None else None,
            "active_kcal": num(summary.get("activeKilocalories")),
            "readiness_score": ready.get("score"),
            "readiness_level": ready.get("level"),
        }
    )
    # Garmin uses negative numbers (e.g. stress -1) for "no data"
    return {k: v for k, v in values.items() if not (isinstance(v, (int, float)) and v < 0)}


def _wellness_dir(root: Path) -> Path:
    return Path(root) / "data" / "wellness"


def write_wellness(root: Path, day: str, values: dict) -> Path:
    """Replace the day: Garmin is the only source, and a refetch must drop values newer cleaning rules reject."""
    path = _wellness_dir(root) / day[:4] / f"{day}.json"
    if not values:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=1))
    return path


def load_wellness(root: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(_wellness_dir(root).glob("*/*.json"))}
