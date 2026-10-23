"""The skin diary: one entry per day (how the skin was, what touched it, what may have set it off), a week view next to
sleep and training, and a CSV for the dermatologist.

Saving merges: a field left out keeps what the day had, so the form and an assistant (MCP add_skin_entry) can each add
their part. Lists given with `add=True` are added to what the day had instead of replacing it; a note is then appended.

The comparisons are associations over the user's own days, with how many days each side counts; they never say what
causes what.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, insert, select, update

from tools import db
from tools.analytics import trimp

LOCATIONS = ("cheeks", "nose", "chin", "mouth", "hairline")  # mouth: around the mouth
LOCATION_NL = {"cheeks": "wangen", "nose": "neus", "chin": "kin", "mouth": "rond de mond", "hairline": "haarlijn"}
SCALES = ("itch", "redness", "sleep", "stress")  # 0-10
OILINESS = (-5, 5)  # -5 very dry, 0 normal, +5 very oily
FLAGS = ("burning", "flaking", "heating")
LISTS = ("products", "new_products", "food")
FIELDS = (*SCALES, "oiliness", "bumps", *FLAGS, "locations", *LISTS, "sport", "weather", "note", "photo_id")
MAX_BUMPS = 500
MAX_ITEMS = 30
MAX_TEXT = 200
MAX_NOTE = 4000
MAX_RANGE_DAYS = 800
SHORT_SLEEP_H, LONG_SLEEP_H = 6.0, 7.0


class SkinError(ValueError):
    def __init__(self, code: str, **params):
        super().__init__(code)
        self.code, self.params = code, params


def _now() -> datetime:
    return datetime.now(UTC)


def parse_day(value: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        raise SkinError("invalid_day") from None


def _texts(values, field: str) -> list[str]:
    if not isinstance(values, list):
        raise SkinError("invalid_list", field=field)
    out: list[str] = []
    for v in values:
        t = " ".join(str(v).split())[:MAX_TEXT]
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    if len(out) > MAX_ITEMS:
        raise SkinError("too_many", field=field, max=MAX_ITEMS)
    return out


def _sport(values) -> list[dict]:
    if not isinstance(values, list):
        raise SkinError("invalid_list", field="sport")
    out = []
    for v in values[:MAX_ITEMS]:
        if not isinstance(v, dict):
            raise SkinError("invalid_list", field="sport")
        name = " ".join(str(v.get("name") or "").split())[:MAX_TEXT]
        aid = str(v["activity_id"])[:64] if v.get("activity_id") else None
        if not name and not aid:
            continue
        out.append({**({"activity_id": aid} if aid else {}), "name": name, "red": bool(v.get("red"))})
    return out


def clean(fields: dict) -> dict:
    """The given fields, checked and normalised; unknown keys are an error, None clears a field."""
    out: dict = {}
    for k, v in fields.items():
        if k not in FIELDS:
            raise SkinError("unknown_field", fields=k)
        if v is None:
            out[k] = [] if k in (*LISTS, "locations", "sport") else None
        elif k in SCALES:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 10:
                raise SkinError("invalid_scale", field=k)
            out[k] = round(v)
        elif k == "oiliness":
            lo, hi = OILINESS
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise SkinError("invalid_oiliness", field=k, min=lo, max=hi)
            out[k] = round(v)
        elif k == "bumps":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= MAX_BUMPS:
                raise SkinError("invalid_count", field=k, max=MAX_BUMPS)
            out[k] = int(v)
        elif k in FLAGS:
            if not isinstance(v, bool):
                raise SkinError("invalid_flag", field=k)
            out[k] = v
        elif k == "locations":
            if not isinstance(v, list) or any(x not in LOCATIONS for x in v):
                raise SkinError("invalid_choice", field=k, options=", ".join(LOCATIONS))
            out[k] = [x for x in LOCATIONS if x in v]
        elif k in LISTS:
            out[k] = _texts(v, k)
        elif k == "sport":
            out[k] = _sport(v)
        elif k == "weather":
            out[k] = " ".join(str(v).split())[:MAX_TEXT] or None
        elif k == "note":
            out[k] = str(v).strip()[:MAX_NOTE] or None
        elif k == "photo_id":
            out[k] = int(v)
    return out


def _row(r) -> dict:
    d = dict(r)
    for k in ("created_at", "updated_at"):
        d.pop(k, None)
    d.pop("user_id", None)
    for k in (*LISTS, "locations", "sport"):
        d[k] = list(d.get(k) or [])
    return d


def get(s: db.Scope, day: str) -> dict | None:
    with s.engine.connect() as conn:
        r = (
            conn.execute(select(db.skin_entries).where(db.skin_entries.c.user_id == s.user_id, db.skin_entries.c.day == day))
            .mappings()
            .first()
        )
    return _row(r) if r else None


def between(s: db.Scope, start: str, end: str) -> list[dict]:
    t = db.skin_entries
    with s.engine.connect() as conn:
        rows = conn.execute(select(t).where(t.c.user_id == s.user_id, t.c.day >= start, t.c.day <= end).order_by(t.c.day)).mappings()
        return [_row(r) for r in rows]


def save(s: db.Scope, day: date, fields: dict, add: bool = False) -> dict:
    """Create or update the day's entry with `fields` (see clean); returns it. `add`: lists grow and the note is
    appended, as an assistant adds what it was told to a day the form may already have filled."""
    values = clean(fields)
    key = day.isoformat()
    old = get(s, key)
    if old and add:
        for k in (*LISTS, "locations"):
            if k in values:
                values[k] = (
                    clean({k: old[k] + values[k]})[k] if k != "locations" else [x for x in LOCATIONS if x in old[k] or x in values[k]]
                )
        if "sport" in values:
            values["sport"] = _sport(old["sport"] + values["sport"])
        if values.get("note") and old.get("note"):
            values["note"] = (old["note"] + "\n" + values["note"])[:MAX_NOTE]
    t = db.skin_entries
    with s.engine.begin() as conn:
        if old:
            if values:
                conn.execute(update(t).where(t.c.id == old["id"], t.c.user_id == s.user_id).values(**values, updated_at=_now()))
        else:
            defaults = {k: [] for k in (*LISTS, "locations", "sport")}
            conn.execute(insert(t).values(**{**defaults, **values}, user_id=s.user_id, day=key, created_at=_now()))
    return get(s, key)


def remove(s: db.Scope, day: str) -> bool:
    entry = get(s, day)
    if not entry:
        return False
    with s.engine.begin() as conn:
        conn.execute(delete(db.skin_entries).where(db.skin_entries.c.id == entry["id"], db.skin_entries.c.user_id == s.user_id))
        if entry.get("photo_id"):
            conn.execute(delete(db.skin_photos).where(db.skin_photos.c.id == entry["photo_id"], db.skin_photos.c.user_id == s.user_id))
    return True


# --- the photo of a day ------------------------------------------------------------------------------------------


def set_photo(s: db.Scope, day: date, mime: str, data: bytes) -> dict:
    """Store the day's photo (already cleaned of metadata), replacing an earlier one; creates the entry if needed."""
    entry = get(s, day.isoformat()) or save(s, day, {})
    with s.engine.begin() as conn:
        if entry.get("photo_id"):
            conn.execute(delete(db.skin_photos).where(db.skin_photos.c.id == entry["photo_id"], db.skin_photos.c.user_id == s.user_id))
        pid = conn.execute(
            insert(db.skin_photos).values(user_id=s.user_id, mime=mime, data=data, created_at=_now()).returning(db.skin_photos.c.id)
        ).scalar_one()
        conn.execute(update(db.skin_entries).where(db.skin_entries.c.id == entry["id"]).values(photo_id=pid, updated_at=_now()))
    return get(s, day.isoformat())


def drop_photo(s: db.Scope, day: str) -> dict | None:
    entry = get(s, day)
    if not entry or not entry.get("photo_id"):
        return entry
    with s.engine.begin() as conn:
        conn.execute(delete(db.skin_photos).where(db.skin_photos.c.id == entry["photo_id"], db.skin_photos.c.user_id == s.user_id))
        conn.execute(update(db.skin_entries).where(db.skin_entries.c.id == entry["id"]).values(photo_id=None, updated_at=_now()))
    return get(s, day)


def photo(s: db.Scope, photo_id: int) -> tuple[str, bytes] | None:
    with s.engine.connect() as conn:
        r = conn.execute(
            select(db.skin_photos.c.mime, db.skin_photos.c.data).where(
                db.skin_photos.c.id == photo_id, db.skin_photos.c.user_id == s.user_id
            )
        ).first()
    return (r[0], bytes(r[1])) if r else None


# --- context from the existing data: training and sleep ---------------------------------------------------------


def day_context(day: str, activities: list[dict], wellness: dict) -> dict:
    """The day's activities (to tick "red afterwards") and the night before it, as Garmin or Apple Health saw it."""
    acts = [
        {"activity_id": a["id"], "name": a.get("name") or a.get("sport") or "", "sport": a.get("sport"), "start": a["start_local"][11:16]}
        for a in activities
        if a.get("start_local", "")[:10] == day
    ]
    w = wellness.get(day) or {}
    return {"activities": acts, "sleep_h": w.get("sleep_h"), "sleep_score": w.get("sleep_score")}


def _week(d: str) -> str:
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def _avg(values: list) -> float | None:
    v = [x for x in values if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def weeks(entries: list[dict], activities: list[dict], wellness: dict, rhr: float, max_by_sport: dict) -> list[dict]:
    """Per ISO week with diary entries: the averages of the skin scales, how often flaking or a burning feeling came
    up, and next to it the week's sleep (Garmin's hours) and training (sessions, minutes, TRIMP load)."""
    by_week: dict[str, list[dict]] = {}
    for e in entries:
        by_week.setdefault(_week(e["day"]), []).append(e)
    out = []
    for week in sorted(by_week):
        days = by_week[week]
        start = date.fromisoformat(days[0]["day"]) - timedelta(days=date.fromisoformat(days[0]["day"]).weekday())
        span = {(start + timedelta(days=i)).isoformat() for i in range(7)}
        acts = [a for a in activities if a.get("start_local", "")[:10] in span]
        out.append(
            {
                "week": week,
                "start": start.isoformat(),
                "days": len(days),
                "itch": _avg([e["itch"] for e in days]),
                "redness": _avg([e["redness"] for e in days]),
                "oiliness": _avg([e.get("oiliness") for e in days]),
                "bumps": _avg([e["bumps"] for e in days]),
                "flaking_days": sum(1 for e in days if e["flaking"]),
                "burning_days": sum(1 for e in days if e["burning"]),
                "sleep_h": _avg([(wellness.get(d) or {}).get("sleep_h") for d in sorted(span)]),
                "sessions": len(acts),
                "training_min": round(sum((a.get("moving_time_s") or 0) for a in acts) / 60),
                "load": round(sum(trimp(a, rhr, max_by_sport) for a in acts)),
            }
        )
    return out


def _side(values: list) -> dict:
    v = [x for x in values if x is not None]
    return {"days": len(v), "redness": _avg(v)}


def comparisons(entries: list[dict], activities: list[dict], wellness: dict) -> list[dict]:
    """Redness on days with and without something: a short night, training, each food tag that came up at least twice.
    Each side says how many days it counts; with fewer than two days on either side a comparison is left out."""
    trained = {a["start_local"][:10] for a in activities if a.get("start_local")}
    rated = [e for e in entries if e["redness"] is not None]
    out = []

    def add(kind: str, label: str, yes: list[dict], no: list[dict]) -> None:
        a, b = _side([e["redness"] for e in yes]), _side([e["redness"] for e in no])
        if a["days"] >= 2 and b["days"] >= 2:
            out.append({"kind": kind, "label": label, "with": a, "without": b})

    sleep = {e["day"]: (wellness.get(e["day"]) or {}).get("sleep_h") for e in rated}
    short = [e for e in rated if sleep[e["day"]] is not None and sleep[e["day"]] < SHORT_SLEEP_H]
    long = [e for e in rated if sleep[e["day"]] is not None and sleep[e["day"]] >= LONG_SLEEP_H]
    add("short_sleep", f"< {SHORT_SLEEP_H:g} h", short, long)
    add("training", "", [e for e in rated if e["day"] in trained], [e for e in rated if e["day"] not in trained])
    tags: dict[str, str] = {}
    for e in rated:
        for f in e["food"]:
            tags.setdefault(f.lower(), f)
    for low, name in sorted(tags.items()):
        yes = [e for e in rated if low in {f.lower() for f in e["food"]}]
        if len(yes) >= 2:
            add("food", name, yes, [e for e in rated if e not in yes])
    return out


# --- for the dermatologist ---------------------------------------------------------------------------------------

CSV_COLUMNS = (
    ("day", "datum"),
    ("itch", "jeuk (0-10)"),
    ("redness", "roodheid (0-10)"),
    ("oiliness", "droog/vet (-5 droog, 0 normaal, +5 vet)"),
    ("bumps", "bultjes/puistjes"),
    ("burning", "branderig/strak"),
    ("locations", "locatie"),
    ("flaking", "schilfers"),
    ("products", "gebruikte producten"),
    ("new_products", "nieuwe producten"),
    ("food", "eten en drinken"),
    ("sport", "sport (rood daarna)"),
    ("sleep_h", "slaap (uur, gemeten)"),
    ("sleep", "slaap (eigen cijfer)"),
    ("stress", "stress (0-10)"),
    ("weather", "weer"),
    ("heating", "verwarming"),
    ("note", "opmerking"),
    ("photo", "foto"),
)


def _cell(key: str, e: dict, wellness: dict) -> str:
    v = e.get(key)
    if key == "locations":
        return ", ".join(LOCATION_NL[x] for x in v)
    if key in LISTS:
        return ", ".join(v)
    if key == "sport":
        return ", ".join(f"{x['name'] or 'training'}{' (rood)' if x['red'] else ''}" for x in v)
    if key == "sleep_h":
        h = (wellness.get(e["day"]) or {}).get("sleep_h")
        return f"{h:.1f}".replace(".", ",") if h is not None else ""
    if key == "photo":
        return "ja" if e.get("photo_id") else ""
    if key == "oiliness":
        return "" if v is None else f"{v:+d}" if v else "0"
    if isinstance(v, bool):
        return "ja" if v else "nee"
    return "" if v is None else str(v)


def to_csv(entries: list[dict], wellness: dict) -> str:
    """Dutch column names and values, semicolon-separated with a BOM: Excel in Dutch opens it as a table."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow([nl for _, nl in CSV_COLUMNS])
    for e in entries:
        w.writerow([_cell(k, e, wellness) for k, _ in CSV_COLUMNS])
    return "﻿" + buf.getvalue()


def entries_md(entries: list[dict], wellness: dict) -> str:
    """The diary as a Markdown table, for an assistant (MCP get_skin_diary)."""
    if not entries:
        return "Nog geen dagen in het huiddagboek in deze periode."
    lines = ["| " + " | ".join(nl for _, nl in CSV_COLUMNS) + " |", "|" + "---|" * len(CSV_COLUMNS)]
    for e in entries:
        lines.append("| " + " | ".join(_cell(k, e, wellness).replace("|", "/").replace("\n", " ") for k, _ in CSV_COLUMNS) + " |")
    return "\n".join(lines)
