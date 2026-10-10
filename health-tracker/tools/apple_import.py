"""Put an Apple Health export into a user's data (the parsing is tools/apple_health.py).

* Workouts become activities with source `apple`. One that starts within two minutes of an activity we already have
  (the same run from Garmin, Strava or a FIT upload) merges into it; Garmin's values stay leading (tools/store.py).
  Importing the same export again changes nothing: each workout merges into itself.
* A day's wellness from Apple is stored with `source: "apple"`. A day that already has wellness from Garmin keeps
  Garmin's values; Apple only fills what Garmin did not give (HRV as SDNN, say). The next Garmin sync of that day
  replaces it, as Garmin is the synced source.
* Intraday rows the same way: a day that has Garmin's series keeps them.
* `remove` takes out everything the import gave, for "remove my Apple data" (privacy statement: removable).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from tools import db
from tools.apple_health import Export, intraday_days, read_export, wellness_days, workout_record
from tools.derive import derive

SOURCE = "apple"


def apply(s: db.Scope, x: Export, filename: str | None = None, progress: Callable[[str, int | None, int | None], None] | None = None) -> dict:
    """Store what `x` holds for this user. Returns counts for the import summary."""
    report = progress or (lambda *_: None)
    # one workout at a time, its route read from the zip only then: years of per-second streams do not fit in memory
    added = merged = 0
    workouts, workout_days, sports = 0, [], set()
    existing_ids = {a["id"] for a in db.load_activities(s)}
    total = len(x.workouts)
    for n in range(total):
        record = workout_record(x.workouts[n], x, filename)
        if record is None:
            continue
        workouts += 1
        workout_days.append(record["start_local"][:10])
        sports.add(record["sport"])
        aid = db.upsert_activity(s, record)
        if aid in existing_ids:
            merged += 1
        else:
            added += 1
            existing_ids.add(aid)
        if n % 25 == 0:
            report("workouts", n + 1, total)

    stored = db.load_wellness(s)
    wellness = wellness_days(x)
    kept = 0
    for n, (day, values) in enumerate(sorted(wellness.items())):
        old = stored.get(day)
        if old and old.get("source") != SOURCE:
            filled = {**values, **old}  # Garmin's day: Apple only fills the gaps
            if filled != old:
                db.write_wellness(s, day, filled)
            kept += 1
        else:
            db.write_wellness(s, day, {**values, "source": SOURCE})
        if n % 100 == 0:
            report("days", n + 1, len(wellness))

    series = intraday_days(x, wellness)
    intraday = 0
    for day, row in series.items():
        old = db.get_intraday(s, day)
        if old and old.get("source") != SOURCE:
            continue
        db.write_intraday(s, day, row)
        intraday += 1

    report("derive", None, None)
    derive(s)
    span = sorted([*wellness, *workout_days])
    nights = sum(1 for v in wellness.values() if v.get("sleep_h"))
    return {
        "workouts": workouts,
        "added": added,
        "merged": merged,
        "days": len(wellness),
        "nights": nights,
        "staged_nights": sum(1 for v in wellness.values() if v.get("deep_sleep_h") is not None),
        "kept_garmin_days": kept,
        "intraday_days": intraday,
        "first": span[0] if span else None,
        "last": span[-1] if span else None,
        "sports": sorted(sports),
    }


def import_file(s: db.Scope, path, filename: str | None = None, progress=None) -> dict:
    """Read the export at `path` and store it. Raises tools.apple_health.NotAnExport for a wrong file."""
    x = read_export(path, progress)
    if not x.workouts and not len(x.hr.t) and not x.sleep and not x.daily and not x.counters:
        from tools.apple_health import NotAnExport

        raise NotAnExport("the export holds no workouts or health data")
    summary = apply(s, x, filename, progress)
    summary["exported"] = x.export_date
    summary["imported_at"] = datetime.now().isoformat(timespec="seconds")
    return summary


def remove(s: db.Scope) -> dict:
    """Everything the Apple import gave: its workouts (and its part of merged ones), its wellness days and its
    intraday rows. Wellness days that were Garmin's stay (with the gaps Apple filled; those are Garmin's day now)."""
    out = db.remove_source(s, SOURCE)
    days = 0
    for day, values in db.load_wellness(s).items():
        if values.get("source") == SOURCE:
            db.write_wellness(s, day, {})
            days += 1
    rows = 0
    for day in db.intraday_days(s):
        row = db.get_intraday(s, day) or {}
        if row.get("source") == SOURCE:
            db.write_intraday(s, day, {})
            rows += 1
    derive(s)
    return {**out, "days": days, "intraday_days": rows}
