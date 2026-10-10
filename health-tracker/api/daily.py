"""One day of health data from the watch (GET /api/wellness/day, MCP get_day): the day's summary (sleep, resting HR,
Body Battery, stress, respiration, SpO2, steps and activity) against the user's own normal, Garmin's series through
the evening before and the day (heart rate, stress, Body Battery, respiration, SpO2), the sleep window and stages,
and the night's heart rate in numbers (lowest, average, the last two hours of sleep against the rest), so a rise
before waking shows as numbers and not only as a line.

Times are minutes after local midnight of the day; the evening before is negative (tools/intraday.py).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from fastapi import APIRouter, Depends

from api.errors import ApiError
from api.readiness import baseline, normal_resting_hr as normal_rhr_with_source
from tools import db
from tools.intraday import SERIES, SLEEP_STAGES, night_summary

EVENING_MARGIN_MIN = 60  # the timeline starts this long before falling asleep, on a whole hour
BASELINE_DAYS = 60  # normal: the median of the 60 days before, as on Today (api/readiness.py)
# The values that get a "normal" next to them: the night's, which say most about recovery.
NORMAL_KEYS = ("resting_hr", "sleep_hr", "sleep_h", "sleep_resp", "sleep_stress", "bb_charged_sleep", "spo2_avg", "stress_avg")


def normal_resting_hr(wellness: dict, day: date, fallback: float | None = None) -> float | None:
    """Your normal resting HR before `day` (api/readiness.py normal_resting_hr). None without any: no reference line
    rather than a population guess."""
    base, _ = normal_rhr_with_source(wellness, day, fallback)
    return round(base, 1) if base is not None else None


def normals(wellness: dict, day: date, rhr_fallback: float | None = None) -> dict:
    """{key: 60-day median before `day`} for NORMAL_KEYS; None with fewer than 7 values (resting HR: see above)."""
    out = {k: baseline(wellness, k, day, BASELINE_DAYS) for k in NORMAL_KEYS}
    out["resting_hr"] = normal_resting_hr(wellness, day, rhr_fallback)
    return {k: round(v, 1) if isinstance(v, float) else v for k, v in out.items()}


def day_view(s: db.Scope, wellness: dict, day: date | None, rhr_fallback: float | None = None, today: date | None = None) -> dict:
    """Everything the Health page needs for one day. Without `day`: the latest day with data (else today)."""
    days = sorted(set(db.intraday_days(s)) | set(wellness))
    if day is None:
        day = date.fromisoformat(days[-1]) if days else (today or date.today())
    iso = day.isoformat()
    row = db.get_intraday(s, iso) or {}
    before = db.get_intraday(s, (day - timedelta(days=1)).isoformat()) or {}
    after = db.get_intraday(s, (day + timedelta(days=1)).isoformat()) or {}

    sleep = row.get("sleep")
    start = 0
    if sleep and sleep["start"] < 0:  # fell asleep before midnight: show the evening from an hour before
        start = (sleep["start"] - EVENING_MARGIN_MIN) // 60 * 60
    series = {
        k: [[m - 1440, v] for m, v in before.get(k) or [] if m - 1440 >= start] + [[m, v] for m, v in row.get(k) or [] if m <= 1440]
        for k in SERIES
    }
    series = {k: v for k, v in series.items() if v}
    # the next night, when it began before this day's midnight: shaded at the right edge
    next_sleep = (after.get("sleep") or {}).get("start")
    out_sleep = None
    if sleep:
        stages = [{"start": a, "end": b, "stage": SLEEP_STAGES[lvl]} for a, b, lvl in sleep.get("stages") or [] if lvl in SLEEP_STAGES]
        out_sleep = {"start": sleep["start"], "end": sleep["end"], "stages": stages}

    end = 1440
    last = max((pts[-1][0] for pts in series.values()), default=None)
    if today is not None and day >= today and last is not None:  # today: up to the last reading, not an empty evening
        end = min(1440, max(start + 120, (last // 60 + 1) * 60))
    summary = dict(wellness.get(iso) or {})
    if not summary.get("resting_hr") and row.get("resting"):
        summary["resting_hr"] = row["resting"]
    hr_day = [v for m, v in series.get("hr", []) if m >= 0]  # the day itself, 0:00-24:00
    return {
        "day": iso,
        "prev": next((d for d in reversed(days) if d < iso), None),
        "next": next((d for d in days if d > iso), None),
        "latest": days[-1] if days else None,
        "today": today.isoformat() if today else None,
        "from": start,
        "to": end,
        "series": series,
        "sleep": out_sleep,
        "next_sleep_start": 1440 + next_sleep if next_sleep is not None and next_sleep < 0 else None,
        "summary": summary,
        "normals": normals(wellness, day, rhr_fallback),
        "hr_min": min(hr_day) if hr_day else None,
        "hr_max": max(hr_day) if hr_day else None,
        "night": night_summary(series.get("hr", []), sleep),
    }


def clock(minute: int) -> str:
    """Minute after midnight (negative: the evening before) as 23:40."""
    m = minute % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


STAGE_NL = {"deep": "diep", "light": "licht", "rem": "REM", "awake": "wakker"}


def _vs(value, normal, unit: str = "", digits: int = 0) -> str:
    if value is None:
        return "-"
    text = f"{value:.{digits}f}{unit}"
    return f"{text} (normaal {normal:.{digits}f})" if normal is not None else text


def as_markdown(v: dict, block_min: int = 30) -> str:
    """For AI assistants (MCP get_day), in Dutch: the day and night in numbers and a table per half hour."""
    w, nrm, series = v["summary"], v["normals"], v["series"]
    if not w and not series:
        return f"Geen data van {v['day']} (horloge niet gedragen, nog niet gesynchroniseerd of geen Garmin)." + (
            f" Laatste dag met data: {v['latest']}." if v.get("latest") else ""
        )
    lines = [f"# Dag {v['day']}", "", "Normaal = mediaan van de 60 dagen ervoor.", ""]
    sleep = v["sleep"]
    if w.get("sleep_h") or sleep:
        parts = [f"slaap {_vs(w.get('sleep_h'), nrm.get('sleep_h'), ' u', 1)}"]
        if sleep:
            parts.append(f"{clock(sleep['start'])}-{clock(sleep['end'])}")
        if w.get("sleep_score"):
            parts.append(f"score {w['sleep_score']}")
        stages = [f"{name} {w[k]:.1f} u" for k, name in (("deep_sleep_h", "diep"), ("light_sleep_h", "licht"), ("rem_sleep_h", "REM"), ("awake_h", "wakker")) if w.get(k)]
        if stages:
            parts.append(", ".join(stages))
        lines.append("- " + "; ".join(parts))
    lines.append(f"- rusthartslag {_vs(w.get('resting_hr'), nrm.get('resting_hr'), ' bpm')}; hartslag in de slaap {_vs(w.get('sleep_hr'), nrm.get('sleep_hr'), ' bpm')}")
    n = v["night"]
    if n:
        lines.append(
            f"- nacht: laagste {n['lowest']} bpm om {clock(n['lowest_at'])}, gemiddeld {n['avg']}; "
            f"laatste 2 uur slaap gemiddeld {n['last_avg']} tegen {n['before_avg']} daarvoor ({n['rise']:+d})"
        )
    lines.append(f"- ademhaling in de slaap {_vs(w.get('sleep_resp'), nrm.get('sleep_resp'), '/min', 1)}" + (f", laagste {w['sleep_resp_low']}" if w.get("sleep_resp_low") else ""))
    if w.get("spo2_avg"):
        lines.append(f"- SpO2 {_vs(w.get('spo2_avg'), nrm.get('spo2_avg'), '%')}" + (f", laagste {w['spo2_low']}%" if w.get("spo2_low") else ""))
    lines.append(
        f"- Body Battery hoogste {w.get('body_battery_high', '-')}, laagste {w.get('body_battery_low', '-')}, "
        f"opgeladen in de slaap {_vs(w.get('bb_charged_sleep'), nrm.get('bb_charged_sleep'))}, overdag +{w.get('bb_charged', '-')} / -{w.get('bb_drained', '-')}"
    )
    lines.append(
        f"- stress gemiddeld {_vs(w.get('stress_avg'), nrm.get('stress_avg'))}, in de slaap {_vs(w.get('sleep_stress'), nrm.get('sleep_stress'), '', 1)}; "
        f"minuten rust/laag/gemiddeld/hoog {w.get('stress_rest_min', '-')}/{w.get('stress_low_min', '-')}/{w.get('stress_medium_min', '-')}/{w.get('stress_high_min', '-')}"
    )
    lines.append(f"- stappen {w.get('steps', '-')}, intensiteitsminuten {w.get('intensity_min', '-')}, trappen {w.get('floors', '-')}, actieve kcal {w.get('active_kcal', '-')}")

    if series:
        cols = [k for k in ("stress", "bb", "resp", "spo2") if k in series]
        names = {"stress": "Stress", "bb": "BB", "resp": "Adem", "spo2": "SpO2"}
        lines += ["", "| Tijd | HR gem | HR min-max | " + " | ".join(names[c] for c in cols) + " | Slaapfase |", "|---" * (4 + len(cols)) + "|"]
        stages = (sleep or {}).get("stages") or []
        blocks: dict[int, dict[str, list]] = {}
        for k, pts in series.items():
            for m, val in pts:
                blocks.setdefault(m // block_min * block_min, {}).setdefault(k, []).append(val)
        for b in sorted(blocks):
            cell = blocks[b]
            hr = cell.get("hr") or []

            def avg(k, digits=0):
                vals = cell.get(k)
                return f"{sum(vals) / len(vals):.{digits}f}" if vals else ""

            cover: dict[str, int] = {}  # the stage that covers most of this block
            for st in stages:
                overlap = min(st["end"], b + block_min) - max(st["start"], b)
                if overlap > 0:
                    cover[st["stage"]] = cover.get(st["stage"], 0) + overlap
            stage = STAGE_NL[max(cover, key=cover.get)] if cover else ""
            row = [clock(b), avg("hr"), f"{min(hr)}-{max(hr)}" if hr else ""] + [avg(c, 1 if c == "resp" else 0) for c in cols] + [stage]
            lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def make_router(today: Callable[[], date], current_user: Callable) -> APIRouter:
    r = APIRouter()

    @r.get("/api/wellness/day")
    def wellness_day(day: str | None = None, u=Depends(current_user)):
        try:
            when = date.fromisoformat(day) if day else None
        except ValueError:
            raise ApiError(422, "invalid_date", date=day) from None
        return day_view(u.scope, u.store.wellness, when, u.store.rhr_fallback, today())

    return r
