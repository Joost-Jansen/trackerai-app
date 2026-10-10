"""Read an Apple Health export (the export.zip from the Health app on an iPhone) into the site's own shapes: workouts
as activity records (tools/store.py), and per day the wellness summary and the intraday series (tools/intraday.py).

Apple has no server API: the data lives on the phone, and Health › profile › "Export All Health Data" writes a zip:

    apple_health_export/export.xml        every sample: <Record>, <Workout>, <ActivitySummary>, ... (the name is
                                          localised on some phones, e.g. exportar.xml; the largest .xml is the one)
    apple_health_export/export_cda.xml    the same as a clinical document: not used
    apple_health_export/workout-routes/route_*.gpx   GPS of workouts (iOS 12+; older exports have <Location> inline)

The file can be gigabytes, so it is read as a stream (expat, never the whole tree) and DTD entity declarations are
refused (an upload is untrusted: no entity expansion). Samples keep the clock of the phone ("2026-10-05 07:12:03
+0200"): the local day and minute come from that wall time, the moment in UTC from the offset.

What becomes what:

* Workouts (HKWorkoutActivityType*) -> activities, source `apple`: distance, duration, heart rate (from the workout's
  statistics, else the heart-rate samples in its window), elevation, indoor/open water, and streams (heart rate,
  GPS from the route). A workout that starts within two minutes of one we already have merges into it.
* Sleep (HKCategoryTypeIdentifierSleepAnalysis) -> per night, on the day you woke up: total, deep, core (= light),
  REM and awake, the window and the stages. One source per night (the one with stages, else the longest): an
  iPhone and a Watch both writing the same night would otherwise count twice.
* Resting heart rate, HRV (SDNN, Apple's measure: not Garmin's RMSSD, so stored as hrv_sdnn), breathing rate and
  SpO2 in the night, VO2max, steps, active energy, flights climbed and exercise minutes -> wellness. Counters
  (steps, energy, flights, exercise) take the source with the most that day, as Health itself avoids double counts.
* Heart rate, breathing rate and SpO2 through the day -> intraday rows, for the last INTRADAY_DAYS days.

Apple has no Body Battery and no stress score: those stay empty.
"""

from __future__ import annotations

import bisect
import io
import math
import re
import zipfile
from array import array
from calendar import timegm
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import IO, Callable
from xml.parsers import expat

from tools.sports import apple_sport

INTRADAY_DAYS = 90  # intraday rows for the last 90 days with data, as the Garmin backfill (tools/sync.py)
NIGHT_GAP_S = 3 * 3600  # sleep samples further apart than this are separate sleeps
MIN_NIGHT_S = 3 * 3600  # shorter (asleep) is a nap: not the night of that day
WORKOUT_HR_MARGIN_S = 15  # a heart-rate sample this close to a route point belongs to it

SLEEP_VALUES = {
    "HKCategoryValueSleepAnalysisAsleepDeep": "deep",
    "HKCategoryValueSleepAnalysisAsleepCore": "light",
    "HKCategoryValueSleepAnalysisAsleepREM": "rem",
    "HKCategoryValueSleepAnalysisAwake": "awake",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "asleep",
    "HKCategoryValueSleepAnalysisAsleep": "asleep",  # before iOS 16: asleep without stages
    "HKCategoryValueSleepAnalysisInBed": "in_bed",
}
STAGE_LEVEL = {"deep": 0, "light": 1, "rem": 2, "awake": 3}  # tools/intraday.py SLEEP_STAGES

HR = "HKQuantityTypeIdentifierHeartRate"
COUNTERS = {
    "HKQuantityTypeIdentifierStepCount": "steps",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "active_kcal",
    "HKQuantityTypeIdentifierFlightsClimbed": "floors",
    "HKQuantityTypeIdentifierAppleExerciseTime": "intensity_min",
}
SERIES_TYPES = {  # samples kept with their time: for the night's values and the intraday series
    "HKQuantityTypeIdentifierRespiratoryRate": "resp",
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "hrv",
}
DAILY_TYPES = {  # one value per day: the last of the day
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierVO2Max": "vo2max",
}
DISTANCE_TYPES = (
    "HKQuantityTypeIdentifierDistanceWalkingRunning",
    "HKQuantityTypeIdentifierDistanceCycling",
    "HKQuantityTypeIdentifierDistanceSwimming",
    "HKQuantityTypeIdentifierDistanceWheelchair",
    "HKQuantityTypeIdentifierDistanceDownhillSnowSports",
    "HKQuantityTypeIdentifierDistanceRowing",
    "HKQuantityTypeIdentifierDistancePaddleSports",
    "HKQuantityTypeIdentifierDistanceCrossCountrySkiing",
)
TO_KM = {"km": 1.0, "m": 0.001, "mi": 1.609344, "yd": 0.0009144, "ft": 0.0003048, "cm": 0.00001}


class NotAnExport(ValueError):
    """The file is no Apple Health export (no export.xml, or not XML)."""


# --- time --------------------------------------------------------------------------------------------------------

_DATE = re.compile(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.\d+)?\s*(?:([+-])(\d\d):?(\d\d)|Z)?")


def parse_time(text: str) -> tuple[int, int]:
    """Apple's "2026-10-05 07:12:03 +0200" -> (UTC epoch seconds, offset seconds). Without an offset: UTC."""
    m = _DATE.match(text or "")
    if not m:
        raise ValueError(f"no date: {text!r}")
    y, mo, d, h, mi, s = (int(x) for x in m.groups()[:6])
    offset = 0
    if m.group(7):
        offset = (int(m.group(8)) * 3600 + int(m.group(9)) * 60) * (1 if m.group(7) == "+" else -1)
    wall = timegm((y, mo, d, h, mi, s, 0, 0, 0))
    return wall - offset, offset


def local_day(utc: int, offset: int) -> str:
    return datetime.fromtimestamp(utc + offset, timezone.utc).strftime("%Y-%m-%d")


def local_minute(utc: int, offset: int, day: str) -> int:
    """Minutes after local midnight of `day` (negative: the evening before), as tools/intraday.py."""
    midnight = timegm(date.fromisoformat(day).timetuple())
    return round((utc + offset - midnight) / 60)


def _local_clock(utc: int, offset: int) -> str:
    return datetime.fromtimestamp(utc + offset, timezone.utc).strftime("%Y-%m-%dT%H:%M")


def _num(text) -> float | None:
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


# --- the parsed export -------------------------------------------------------------------------------------------


MAX_GPX_BYTES = 64 * 1024 * 1024  # a route of a day-long hike is a few MB


@dataclass
class Series:
    """Samples of one kind, compact: UTC seconds, offset in minutes, value."""

    t: array = field(default_factory=lambda: array("q"))
    off: array = field(default_factory=lambda: array("h"))
    v: array = field(default_factory=lambda: array("f"))
    src: list = field(default_factory=list)  # index into Export.sources, per sample (only kept where it matters)

    def add(self, utc: int, offset: int, value: float, source: int | None = None) -> None:
        self.t.append(utc)
        self.off.append(offset // 60)
        self.v.append(value)
        if source is not None:
            self.src.append(source)

    def sort(self) -> None:
        order = sorted(range(len(self.t)), key=self.t.__getitem__)
        if all(order[i] < order[i + 1] for i in range(len(order) - 1)):
            return
        self.t = array("q", (self.t[i] for i in order))
        self.off = array("h", (self.off[i] for i in order))
        self.v = array("f", (self.v[i] for i in order))
        if self.src:
            self.src = [self.src[i] for i in order]

    def window(self, start: int, end: int) -> range:
        """Indexes of the samples with start <= t <= end (sorted first)."""
        return range(bisect.bisect_left(self.t, start), bisect.bisect_right(self.t, end))


@dataclass
class Export:
    hr: Series = field(default_factory=Series)
    series: dict = field(default_factory=lambda: defaultdict(Series))  # resp, spo2, hrv
    daily: dict = field(default_factory=lambda: defaultdict(dict))  # day -> {resting_hr, vo2max}
    counters: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(float)))  # (day, key) -> {source: sum}
    sleep: list = field(default_factory=list)  # (start_utc, end_utc, offset, stage, source)
    workouts: list = field(default_factory=list)
    routes: dict = field(default_factory=dict)  # gpx path in the zip -> [(utc, lat, lon, ele, speed)], read when needed
    route_files: dict = field(default_factory=dict)  # gpx path in the zip -> member name, for route()
    zip_source: object = None
    sources: list = field(default_factory=list)
    _source_ids: dict = field(default_factory=dict)
    export_date: str | None = None

    def route(self, path: str) -> list:
        """The points of a workout's route file ("/workout-routes/route_....gpx"), read from the zip on first use."""
        key = path.lstrip("/")
        if key in self.routes:
            return self.routes[key]
        member = self.route_files.get(key) or next((m for k, m in self.route_files.items() if k.endswith(key)), None)
        if member is None or self.zip_source is None:
            return []
        if hasattr(self.zip_source, "seek"):
            self.zip_source.seek(0)
        with zipfile.ZipFile(self.zip_source) as z:
            if z.getinfo(member).file_size > MAX_GPX_BYTES:  # read into memory whole: an oversized member is skipped
                return []
            return read_gpx(z.read(member))

    def source(self, name: str) -> int:
        if name not in self._source_ids:
            self._source_ids[name] = len(self.sources)
            self.sources.append(name)
        return self._source_ids[name]


# --- reading -----------------------------------------------------------------------------------------------------


def _export_member(z: zipfile.ZipFile) -> zipfile.ZipInfo:
    xmls = [i for i in z.infolist() if i.filename.lower().endswith(".xml") and "cda" not in i.filename.lower().rsplit("/", 1)[-1]
            and "/workout-routes/" not in i.filename and "/electrocardiograms/" not in i.filename]
    if not xmls:
        raise NotAnExport("no export.xml in the zip")
    return max(xmls, key=lambda i: i.file_size)


class _Reader:
    """expat handlers: top-level <Record>s are handled at once, a <Workout> once it is closed."""

    def __init__(self, out: Export):
        self.out = out
        self.workout: dict | None = None
        self.route: list | None = None
        self.depth = 0
        self.seen_root = False

    def start(self, name: str, a: dict) -> None:
        self.depth += 1
        if self.depth == 1:
            if name != "HealthData":
                raise NotAnExport(f"root element is <{name}>, not <HealthData>")
            self.seen_root = True
            return
        if name == "ExportDate":
            self.out.export_date = a.get("value")
        elif name == "Record" and self.depth == 2:
            self.record(a)
        elif name == "Workout":
            self.workout = {"attrs": a, "meta": {}, "stats": {}, "route_files": [], "locations": []}
        elif self.workout is not None:
            if name == "MetadataEntry" and self.route is None:
                self.workout["meta"][a.get("key")] = a.get("value")
            elif name == "WorkoutStatistics":
                self.workout["stats"][a.get("type")] = a
            elif name == "FileReference":
                self.workout["route_files"].append(a.get("path") or "")
            elif name == "WorkoutRoute":
                self.route = self.workout["locations"]
            elif name == "Location" and self.route is not None:
                try:
                    utc, _ = parse_time(a.get("date", ""))
                except ValueError:
                    return
                lat, lon = _num(a.get("latitude")), _num(a.get("longitude"))
                if lat is not None and lon is not None:
                    self.route.append((utc, lat, lon, _num(a.get("altitude")), _num(a.get("speed"))))

    def end(self, name: str) -> None:
        self.depth -= 1
        if name == "WorkoutRoute":
            self.route = None
        elif name == "Workout" and self.workout is not None:
            self.out.workouts.append(self.workout)
            self.workout = None

    def record(self, a: dict) -> None:
        kind = a.get("type") or ""
        try:
            utc, offset = parse_time(a.get("startDate", ""))
        except ValueError:
            return
        out = self.out
        if kind == HR:
            v = _num(a.get("value"))
            if v and 20 <= v <= 250:
                out.hr.add(utc, offset, v)
        elif kind == "HKCategoryTypeIdentifierSleepAnalysis":
            stage = SLEEP_VALUES.get(a.get("value") or "")
            try:
                end, _ = parse_time(a.get("endDate", ""))
            except ValueError:
                return
            if stage and end > utc:
                out.sleep.append((utc, end, offset, stage, out.source(a.get("sourceName") or "")))
        elif kind in SERIES_TYPES:
            v = _num(a.get("value"))
            if v is None:
                return
            key = SERIES_TYPES[kind]
            if key == "spo2" and v <= 1.0:
                v *= 100  # a fraction ("0.97", unit "%")
            out.series[key].add(utc, offset, v)
        elif kind in DAILY_TYPES:
            v = _num(a.get("value"))
            if v:
                out.daily[local_day(utc, offset)][DAILY_TYPES[kind]] = v
        elif kind in COUNTERS:
            v = _num(a.get("value"))
            if not v or v < 0:
                return
            key = COUNTERS[kind]
            if key == "active_kcal" and (a.get("unit") or "").lower() == "kj":
                v /= 4.184
            out.counters[(local_day(utc, offset), key)][a.get("sourceName") or ""] += v


def _refuse_entities(*_args) -> None:
    raise NotAnExport("the file declares XML entities: refused")


def read_xml(stream: IO[bytes], out: Export, size: int | None = None, progress: Callable[[int, int | None], None] | None = None) -> None:
    """Feed export.xml from a binary stream into `out`."""
    reader = _Reader(out)
    parser = expat.ParserCreate()
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.EntityDeclHandler = _refuse_entities
    parser.buffer_text = False
    done = 0
    try:
        while True:
            chunk = stream.read(1 << 20)
            if not chunk:
                break
            parser.Parse(chunk, False)
            done += len(chunk)
            if progress:
                progress(done, size)
        parser.Parse(b"", True)
    except expat.ExpatError as err:
        if not reader.seen_root:
            raise NotAnExport(f"not XML: {err}") from err
        raise NotAnExport(f"the export is damaged: {err}") from err
    if not reader.seen_root:
        raise NotAnExport("empty file")


_GPX_TIME = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?")


def read_gpx(data: bytes) -> list[tuple]:
    """Apple's route_*.gpx -> [(utc, lat, lon, ele, speed)]. Same refusal of entities as the export."""
    points: list[tuple] = []
    cur: dict = {}
    text: list[str] = []

    def start(name, a):
        text.clear()
        if name == "trkpt":
            cur.clear()
            cur["lat"], cur["lon"] = _num(a.get("lat")), _num(a.get("lon"))

    def chars(s):
        text.append(s)

    def end(name):
        value = "".join(text).strip()
        text.clear()
        if name in ("ele", "speed") and cur:
            cur[name] = _num(value)
        elif name == "time" and cur:
            m = _GPX_TIME.match(value)
            if m:
                zone = m.group(2) or "Z"
                stamp = datetime.fromisoformat(m.group(1) + ("+00:00" if zone == "Z" else zone))
                cur["t"] = int(stamp.timestamp())
        elif name == "trkpt" and cur:
            if cur.get("lat") is not None and cur.get("lon") is not None and cur.get("t") is not None:
                points.append((cur["t"], cur["lat"], cur["lon"], cur.get("ele"), cur.get("speed")))
            cur.clear()

    parser = expat.ParserCreate()
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.EntityDeclHandler = _refuse_entities
    try:
        parser.Parse(data, True)
    except expat.ExpatError:
        return points
    return points


def read_export(source, progress: Callable[[str, int | None, int | None], None] | None = None) -> Export:
    """A path or binary file of export.zip (or export.xml alone) -> Export. Raises NotAnExport."""
    out = Export()
    report = progress or (lambda *_: None)
    head = _peek(source)
    if head.startswith(b"PK"):
        try:
            z = zipfile.ZipFile(source)
        except zipfile.BadZipFile as err:
            raise NotAnExport("not a readable zip") from err
        with z:
            member = _export_member(z)
            with z.open(member) as f:
                read_xml(f, out, member.file_size, lambda d, t: report("read", d, t))
            # routes are read per workout when it is stored (Export.route): years of GPS do not fit in memory at once
            for info in z.infolist():
                if info.filename.lower().endswith(".gpx"):
                    out.route_files[info.filename.split("apple_health_export/", 1)[-1]] = info.filename
            out.zip_source = source
    else:
        f = open(source, "rb") if isinstance(source, (str, bytes)) or hasattr(source, "__fspath__") else source
        try:
            size = _size(f)
            read_xml(f, out, size, lambda d, t: report("read", d, t))
        finally:
            if f is not source:
                f.close()
    out.hr.sort()
    for s in out.series.values():
        s.sort()
    return out


def _peek(source) -> bytes:
    if isinstance(source, (str, bytes)) or hasattr(source, "__fspath__"):
        with open(source, "rb") as f:
            return f.read(4)
    pos = source.tell()
    head = source.read(4)
    source.seek(pos)
    return head


def _size(f) -> int | None:
    try:
        pos = f.tell()
        f.seek(0, io.SEEK_END)
        size = f.tell()
        f.seek(pos)
        return size
    except (OSError, AttributeError):
        return None


# --- sleep -------------------------------------------------------------------------------------------------------


@dataclass
class Night:
    day: str  # the day you woke up
    start: int
    end: int
    offset: int
    segments: list  # (start, end, stage)

    def seconds(self, *stages: str) -> int:
        return sum(b - a for a, b, s in self.segments if s in stages)


def nights(segments: list) -> dict[str, Night]:
    """The main sleep per day (woke up that day): per source the samples are joined into sleeps, then per day the
    sleep with stages wins, else the one asleep longest. Naps (under MIN_NIGHT_S asleep) do not count."""
    by_source: dict[int, list] = defaultdict(list)
    for seg in segments:
        by_source[seg[4]].append(seg)
    candidates: dict[str, list[Night]] = defaultdict(list)
    for segs in by_source.values():
        segs.sort()
        groups: list[list] = []
        for seg in segs:
            if groups and seg[0] - max(s[1] for s in groups[-1]) <= NIGHT_GAP_S:
                groups[-1].append(seg)
            else:
                groups.append([seg])
        for g in groups:
            asleep = [s for s in g if s[3] not in ("in_bed",)]
            core = asleep or g  # only "in bed" samples: that is all there is
            start, end = min(s[0] for s in core), max(s[1] for s in core)
            offset = max(core, key=lambda s: s[1])[2]
            night = Night(local_day(end, offset), start, end, offset, [(s[0], s[1], s[3]) for s in core])
            if night.seconds("deep", "light", "rem", "asleep") >= MIN_NIGHT_S:
                candidates[night.day].append(night)
    out = {}
    for day, options in candidates.items():
        out[day] = max(options, key=lambda n: (n.seconds("deep", "light", "rem") > 0, n.seconds("deep", "light", "rem", "asleep")))
    return out


def _union_seconds(segments: list, stages: tuple) -> int:
    """Seconds covered by these stages, overlaps counted once."""
    spans = sorted((a, b) for a, b, s in segments if s in stages)
    total, cur_a, cur_b = 0, None, None
    for a, b in spans:
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        else:
            cur_b = max(cur_b, b)
    if cur_b is not None:
        total += cur_b - cur_a
    return total


# --- per day -----------------------------------------------------------------------------------------------------


def _avg(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def wellness_days(x: Export) -> dict[str, dict]:
    """{day: wellness values} in the keys of tools/store.py wellness_from_garmin (plus hrv_sdnn and vo2max)."""
    out: dict[str, dict] = defaultdict(dict)
    for day, night in nights(x.sleep).items():
        h = lambda *s: round(_union_seconds(night.segments, s) / 3600, 2)  # noqa: E731
        staged = night.seconds("deep", "light", "rem") > 0
        w = out[day]
        w["sleep_h"] = h("deep", "light", "rem", "asleep")
        if staged:
            w.update(deep_sleep_h=h("deep"), light_sleep_h=h("light"), rem_sleep_h=h("rem"), awake_h=h("awake"))
        w["sleep_start"] = _local_clock(night.start, night.offset)
        w["sleep_end"] = _local_clock(night.end, night.offset)
        hr = [x.hr.v[i] for i in x.hr.window(night.start, night.end)]
        if len(hr) >= 6:
            w["sleep_hr"] = round(_avg(hr))
        for key, out_key, low_key, digits in (("resp", "sleep_resp", "sleep_resp_low", 1), ("spo2", "spo2_avg", "spo2_low", 0)):
            s = x.series.get(key)
            vals = [s.v[i] for i in s.window(night.start, night.end)] if s else []
            if vals:
                w[out_key] = round(_avg(vals), digits) if digits else round(_avg(vals))
                w[low_key] = round(min(vals), digits) if digits else round(min(vals))
        s = x.series.get("hrv")
        vals = [s.v[i] for i in s.window(night.start, night.end)] if s else []
        if vals:
            w["hrv_sdnn"] = round(_avg(vals))
    # HRV outside a night (Apple also measures during the day): the day's average where the night had none
    s = x.series.get("hrv")
    if s:
        per_day: dict[str, list] = defaultdict(list)
        for i in range(len(s.t)):
            per_day[local_day(s.t[i], s.off[i] * 60)].append(s.v[i])
        for day, vals in per_day.items():
            out[day].setdefault("hrv_sdnn", round(_avg(vals)))
    for day, values in x.daily.items():
        for key, v in values.items():
            out[day][key] = round(v, 1) if key == "vo2max" else round(v)
    for (day, key), per_source in x.counters.items():
        out[day][key] = round(max(per_source.values()))  # the source with the most: no double counts
    return {d: {k: v for k, v in w.items() if v is not None} for d, w in out.items() if w}


def intraday_days(x: Export, wellness: dict[str, dict] | None = None, days: int = INTRADAY_DAYS) -> dict[str, dict]:
    """{day: intraday row} (tools/intraday.py shape) for the last `days` days with heart-rate data."""
    per_day: dict[str, dict[str, dict[int, list]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    sources = [("hr", x.hr), *((k, x.series[k]) for k in ("resp", "spo2") if k in x.series)]
    if not len(x.hr.t):
        return {}
    last = local_day(x.hr.t[-1], x.hr.off[-1] * 60)
    first = (date.fromisoformat(last) - timedelta(days=days - 1)).isoformat()
    first_n = (date.fromisoformat(first) - date(1970, 1, 1)).days
    names: dict[int, str] = {}
    for key, s in sources:
        for t, off, v in zip(s.t, s.off, s.v):
            local = t + off * 60  # integer math: an export has millions of samples
            n = local // 86400
            if n < first_n:
                continue
            day = names.get(n) or names.setdefault(n, (date(1970, 1, 1) + timedelta(days=n)).isoformat())
            per_day[day][key][(local % 86400) // 60].append(v)
    night_by_day = nights(x.sleep)
    out = {}
    for day, series in per_day.items():
        row: dict = {}
        for key, minutes in series.items():
            digits = 1 if key == "resp" else 0
            pts = [[m, round(_avg(v), digits) if digits else round(_avg(v))] for m, v in sorted(minutes.items()) if 0 <= m < 1440]
            if pts:
                row[key] = pts
        if "hr" in row:
            values = [v for _, v in row["hr"]]
            row["min"], row["max"] = min(values), max(values)
            resting = (wellness or {}).get(day, {}).get("resting_hr") or x.daily.get(day, {}).get("resting_hr")
            if resting:
                row["resting"] = round(resting)
        night = night_by_day.get(day)
        if night:
            stages = []
            for a, b, s in sorted(night.segments):
                if s not in STAGE_LEVEL:
                    continue
                ma, mb = local_minute(a, night.offset, day), local_minute(b, night.offset, day)
                if stages and stages[-1][2] == STAGE_LEVEL[s] and stages[-1][1] >= ma:
                    stages[-1][1] = max(stages[-1][1], mb)
                elif mb > ma:
                    stages.append([ma, mb, STAGE_LEVEL[s]])
            row["sleep"] = {"start": local_minute(night.start, night.offset, day), "end": local_minute(night.end, night.offset, day), "stages": stages}
        if row:
            row["source"] = "apple"
            out[day] = row
    return out


# --- workouts ----------------------------------------------------------------------------------------------------


def _km(value, unit) -> float | None:
    v = _num(value)
    if v is None:
        return None
    return v * TO_KM.get((unit or "km").lower(), 1.0)


def _haversine_m(a: tuple, b: tuple) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _ascent(points: list) -> float | None:
    eles = [p[3] for p in points if p[3] is not None]
    if len(eles) < 2:
        return None
    up, base = 0.0, eles[0]
    for e in eles[1:]:  # 2 m hysteresis against GPS noise
        if e - base >= 2:
            up += e - base
            base = e
        elif e < base:
            base = e
    return round(up)


def workout_record(w: dict, x: Export, filename: str | None = None) -> dict | None:
    """One <Workout> -> an activity record (tools/store.py), or None when it has no usable time."""
    a, meta, stats = w["attrs"], w["meta"], w["stats"]
    try:
        start, offset = parse_time(a.get("startDate", ""))
        end, _ = parse_time(a.get("endDate", ""))
    except ValueError:
        return None
    sport = apple_sport(a.get("workoutActivityType"))
    duration = _num(a.get("duration"))
    unit = (a.get("durationUnit") or "min").lower()
    moving = duration * {"min": 60, "s": 1, "sec": 1, "hr": 3600, "h": 3600}.get(unit, 60) if duration else end - start
    km = _km(a.get("totalDistance"), a.get("totalDistanceUnit"))
    if km is None:
        for t in DISTANCE_TYPES:
            if t in stats:
                km = _km(stats[t].get("sum"), stats[t].get("unit"))
                break

    points: list = []
    for path in w["route_files"]:
        points = x.route(path)
        if points:
            break
    if not points and w["locations"]:
        points = sorted(w["locations"])
    if km is None and len(points) > 1:
        km = sum(_haversine_m(p, q) for p, q in zip(points, points[1:])) / 1000

    hr_idx = x.hr.window(start, end)
    hr_t = [x.hr.t[i] for i in hr_idx]
    hr_v = [x.hr.v[i] for i in hr_idx]
    hr_stat = stats.get(HR) or {}
    avg_hr = _num(hr_stat.get("average")) or (_avg(hr_v) if hr_v else None)
    max_hr = _num(hr_stat.get("maximum")) or (max(hr_v) if hr_v else None)

    ascent = meta.get("HKElevationAscended")
    elevation = None
    if ascent:
        m = re.match(r"([\d.]+)\s*(\w+)?", ascent)
        if m:
            elevation = round(float(m.group(1)) * {"cm": 0.01, "m": 1, "ft": 0.3048}.get((m.group(2) or "m").lower(), 1))
    if elevation is None and points:
        elevation = _ascent(points)

    label = {"run": "Running", "ride": "Cycling", "swim": "Swimming"}.get(sport, sport.replace("_", " ").capitalize())
    device = a.get("sourceName") or "Apple Health"
    record = {
        "start_utc": datetime.fromtimestamp(start, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_local": datetime.fromtimestamp(start + offset, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        "sport": sport,
        "name": f"Apple Watch {label}" if "watch" in device.lower() else f"Apple Health {label}",
        "distance_km": round(km, 2) if km else None,
        "moving_time_s": round(moving) if moving else None,
        "elapsed_time_s": end - start,
        "elevation_gain_m": elevation,
        "avg_hr": round(avg_hr) if avg_hr else None,
        "max_hr": round(max_hr) if max_hr else None,
        "indoor": meta.get("HKIndoorWorkout") == "1" or None,
        "open_water": (sport == "swim" and meta.get("HKSwimmingLocationType") == "2") or None,
        "has_gps": len(points) > 1 or None,  # the history list shows a map only for these (api/history.py)
        "streams": _streams(start, points, hr_t, hr_v) or None,
        "sources": {"apple": {"file": filename, "device": device, "type": a.get("workoutActivityType")}},
    }
    return {k: v for k, v in record.items() if v is not None}


def _streams(start: int, points: list, hr_t: list, hr_v: list) -> dict:
    """Streams as tools/fit.py: on the route's points when there is a route (heart rate from the nearest sample),
    else on the heart-rate samples."""
    if points:
        pts = [p for p in points if p[0] >= start - 60]
        if not pts:
            return {}
        out: dict = {"time": [p[0] - start for p in pts]}
        dist, total = [0.0], 0.0
        for p, q in zip(pts, pts[1:]):
            total += _haversine_m(p, q)
            dist.append(round(total, 1))
        out["distance"] = dist
        out["latlng"] = [[round(p[1], 5), round(p[2], 5)] for p in pts]
        if any(p[3] is not None for p in pts):
            out["altitude"] = [round(p[3], 1) if p[3] is not None else None for p in pts]
        if any(p[4] is not None and p[4] >= 0 for p in pts):
            out["velocity"] = [round(p[4], 2) if p[4] is not None and p[4] >= 0 else None for p in pts]
        if hr_t:
            hr = []
            for p in pts:
                j = bisect.bisect_left(hr_t, p[0])
                near = [k for k in (j - 1, j) if 0 <= k < len(hr_t) and abs(hr_t[k] - p[0]) <= WORKOUT_HR_MARGIN_S]
                hr.append(round(hr_v[min(near, key=lambda k: abs(hr_t[k] - p[0]))]) if near else None)
            if any(v is not None for v in hr):
                out["heartrate"] = hr
        return out
    if hr_t:
        return {"time": [t - start for t in hr_t], "heartrate": [round(v) for v in hr_v]}
    return {}


def activities(x: Export, filename: str | None = None) -> list[dict]:
    out = [workout_record(w, x, filename) for w in x.workouts]
    return [r for r in out if r]
