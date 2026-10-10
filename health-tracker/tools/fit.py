"""Read FIT files: per-second streams from a Garmin download, and whole activities from any device (Wahoo, ...)."""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tools.sports import fit_sport

DEG_PER_SEMICIRCLE = 180 / 2**31
# stream name -> FIT fields, first one present wins
FIELDS = {
    "heartrate": ("heart_rate",),
    "velocity": ("enhanced_speed", "speed"),
    "altitude": ("enhanced_altitude", "altitude"),
    "cadence": ("cadence",),
    "distance": ("distance",),
    "watts": ("power",),
}


def _utc(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def streams_from_records(records, start: datetime | None = None, end: datetime | None = None) -> dict:
    """Streams aligned on `time`; `latlng` only holds the records that have a position. With `start` and `end` (UTC)
    only the records in that window."""
    records = [r for r in records if r.get("timestamp") is not None and (start is None or start <= _utc(r["timestamp"]) <= end)]
    if not records:
        return {}
    t0 = records[0]["timestamp"]
    streams: dict[str, list] = {"time": [round((r["timestamp"] - t0).total_seconds()) for r in records]}
    for name, keys in FIELDS.items():
        values = [next((r[k] for k in keys if r.get(k) is not None), None) for r in records]
        if any(v is not None for v in values):
            streams[name] = values
    track = [
        [round(r["position_lat"] * DEG_PER_SEMICIRCLE, 5), round(r["position_long"] * DEG_PER_SEMICIRCLE, 5)]
        for r in records
        if r.get("position_lat") is not None and r.get("position_long") is not None
    ]
    if track:
        streams["latlng"] = track
    return streams


MAX_FIT_BYTES = 100 * 1024 * 1024  # a FIT file of a 24-hour ride is ~20 MB


def read_fit_streams(data: bytes, start: datetime | None = None, end: datetime | None = None) -> dict:
    """Streams from the zip Garmin returns for an ORIGINAL download (or a bare .fit). With `start` and `end` (UTC) only
    the records in that window: one leg of a multisport activity, whose legs share the parent's file."""
    import fitdecode

    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                infos = [i for i in z.infolist() if i.filename.lower().endswith(".fit")]
                if not infos:
                    raise ValueError("no .fit file in Garmin download")
                if infos[0].file_size > MAX_FIT_BYTES:
                    raise ValueError("the .fit file in the Garmin download is too large")
                data = z.read(infos[0])
        except zipfile.BadZipFile as err:
            raise ValueError(f"unreadable Garmin download: {err}") from err

    records = []
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            for frame in reader:
                if frame.frame_type == fitdecode.FIT_FRAME_DATA and frame.name == "record":
                    records.append({f.name: f.value for f in frame.fields})
    except fitdecode.FitError as err:
        raise ValueError(f"unreadable FIT file: {err}") from err
    return streams_from_records(records, start, end)


FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
LOCAL_TZ = ZoneInfo("Europe/Amsterdam")  # only when the file carries no local time of its own


def _as_utc(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return FIT_EPOCH + timedelta(seconds=value)
    return None


def _unzip(data: bytes) -> bytes:
    if data[:2] != b"PK":
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = [i for i in z.infolist() if i.filename.lower().endswith(".fit")]
            if not infos:
                raise ValueError("no .fit file in the zip")
            if infos[0].file_size > MAX_FIT_BYTES:  # unpacked in memory: a zip bomb must not get that far
                raise ValueError("the .fit file in the zip is too large")
            return z.read(infos[0])
    except zipfile.BadZipFile as err:
        raise ValueError(f"unreadable zip: {err}") from err


def read_fit_activity(data: bytes) -> dict:
    """A whole activity from a FIT file of any device (Wahoo, Garmin, Zwift, ...): what we need for a record.

    Returns {manufacturer, sport, start_utc, start_local, distance_m, timer_s, elapsed_s, ascent_m, avg_hr, max_hr,
    avg_cadence, avg_power, laps: [...], streams: {...}}. Raises ValueError for a file that is not an activity.
    """
    import fitdecode

    data = _unzip(data)
    records, laps, session, file_id, activity = [], [], {}, {}, {}
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            for frame in reader:
                if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                    continue
                values = {f.name: f.value for f in frame.fields}
                if frame.name == "record":
                    records.append(values)
                elif frame.name == "lap":
                    laps.append(values)
                elif frame.name == "session" and not session:
                    session = values
                elif frame.name == "file_id" and not file_id:
                    file_id = values
                elif frame.name == "activity":
                    activity = values
    except fitdecode.FitError as err:
        raise ValueError(f"unreadable FIT file: {err}") from err
    if not session and not records:
        raise ValueError("no activity in this FIT file")

    start = _as_utc(session.get("start_time")) or _as_utc(records[0].get("timestamp") if records else None)
    if start is None:
        raise ValueError("no start time in this FIT file")
    # Local time: the device's own offset when the file has it (activity.local_timestamp), else Amsterdam.
    ts, local_ts = _as_utc(activity.get("timestamp")), activity.get("local_timestamp")
    if ts is not None and local_ts is not None:
        local_naive = local_ts.replace(tzinfo=None) if isinstance(local_ts, datetime) else (FIT_EPOCH + timedelta(seconds=local_ts)).replace(tzinfo=None)
        offset = local_naive - ts.replace(tzinfo=None)
        start_local = (start.replace(tzinfo=None) + offset)
    else:
        start_local = start.astimezone(LOCAL_TZ).replace(tzinfo=None)

    sport_raw = str(session.get("sport") or "").lower()
    sub = str(session.get("sub_sport") or "").lower()
    return {
        "manufacturer": str(file_id.get("manufacturer") or "").lower(),
        "sport": fit_sport(sport_raw, sub),
        "indoor": "indoor" in sub or "virtual" in sub or "treadmill" in sub,
        "open_water": sport_raw == "swimming" and sub == "open_water",
        "start_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_local": start_local.strftime("%Y-%m-%dT%H:%M:%S"),
        "distance_m": session.get("total_distance"),
        "timer_s": session.get("total_timer_time"),
        "elapsed_s": session.get("total_elapsed_time"),
        "ascent_m": session.get("total_ascent"),
        "avg_hr": session.get("avg_heart_rate"),
        "max_hr": session.get("max_heart_rate"),
        "avg_cadence": session.get("avg_cadence"),
        "avg_power": session.get("avg_power"),
        "laps": [
            {"distance_m": lap.get("total_distance"), "time_s": lap.get("total_timer_time"), "avg_hr": lap.get("avg_heart_rate"), "ascent_m": lap.get("total_ascent")}
            for lap in laps
        ],
        "streams": streams_from_records(records),
    }
