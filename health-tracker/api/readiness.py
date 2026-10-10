"""Readiness ("Klaar voor training?"): a plain verdict from last night's recovery against the user's own baseline, plus form.

Signals: resting HR above its 60-day median, breathing faster at night than its 60-day median, short sleep, low
Body Battery, very negative form (TSB). When resting HR, the heart rate while asleep and night respiration are all up
together, `illness_hint` is set: that combination often shows a day or two before a cold.
Not medical advice; the dashboard says so.

Returns codes and numbers only; the site renders them with web/lib/texts.ts (T.readiness), agents get `as_text`.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median

MAX_AGE_DAYS = 1  # older recovery data says little about today
# Night respiration (breaths/min) is very steady from night to night, so a small rise already stands out:
# +1 against the 60-day median is worth attention, +2 a warning.
RESP_ATTENTION, RESP_WARN = 1.0, 2.0
# Possible cold: resting HR and the average heart rate while asleep both at least 3 bpm above their normal and night
# respiration at least RESP_ATTENTION above its normal. Each alone happens after a hard day or a late meal; the three
# together are a more specific sign. Deliberately modest: it is worded as "might", never as a diagnosis.
ILLNESS_HR_DELTA = 3


def baseline(wellness: dict, key: str, today: date, days: int) -> float | None:
    """Median of `key` over the `days` before `today` (not today itself); None with fewer than 7 values."""
    values = [w[key] for d, w in wellness.items() if w.get(key) and today - timedelta(days=days) <= date.fromisoformat(d) < today]
    return median(values) if len(values) >= 7 else None


def _note(code: str, **params) -> dict:
    return {"code": code, "params": {k: v for k, v in params.items() if v is not None}}


NORMAL_DAYS = 60  # the normal is the median of this many days before
RECENT_NIGHTS = 7  # with too few nights in those days: the median of the last this many measured nights, however old


def normal_resting_hr(wellness: dict, day: date, fallback: float | None = None) -> tuple[float | None, str | None]:
    """Your normal resting HR before `day` and where it comes from, in this order:
        "60d"      the median of the last 60 days (at least 7 measured nights);
        "recent"   else the median of the last 7 measured nights, however old (one night is too noisy: a cold or a late
                   meal would become the normal);
        "profile"  else what you entered in Settings (`fallback`), for when the watch never measured a night;
        (None, None) without any of these.
    One definition for readiness, Today, Health, Trends and the training load."""
    base = baseline(wellness, "resting_hr", day, NORMAL_DAYS)
    if base is not None:
        return base, "60d"
    nights = sorted((d for d, w in wellness.items() if w.get("resting_hr") and date.fromisoformat(d) < day), reverse=True)[:RECENT_NIGHTS]
    if nights:
        return median(wellness[d]["resting_hr"] for d in nights), "recent"
    if fallback:
        return float(fallback), "profile"
    return None, None


def readiness(wellness: dict, today: date, tsb: float | None = None, form_pct: float | None = None, rhr_fallback: float | None = None) -> dict | None:
    """{verdict: klaar|rustig aan|herstel|onbekend, date: night used or None, no_night, signals: [{key, value, level, note}]}.
    `note` is {code, params}: vs_baseline {delta, baseline}, sleep {score?, baseline?}, highest {date, days_ago},
    form_yesterday {} (form is yesterday's fitness minus fatigue)."""
    days = sorted((d for d, w in wellness.items() if date.fromisoformat(d) <= today and (w.get("resting_hr") or w.get("sleep_h"))), reverse=True)
    latest = days[0] if days and (today - date.fromisoformat(days[0])).days <= MAX_AGE_DAYS else None
    signals = []
    illness_hint = False
    if latest:
        w = wellness[latest]
        base_rhr, _ = normal_resting_hr(wellness, date.fromisoformat(latest), rhr_fallback)
        if w.get("resting_hr") and base_rhr:
            delta = w["resting_hr"] - base_rhr
            level = "warn" if delta >= 5 else "attention" if delta >= 3 else "ok"
            signals.append({"key": "resting_hr", "value": w["resting_hr"], "note": _note("vs_baseline", delta=round(delta), baseline=round(base_rhr)), "level": level})
        base_resp = baseline(wellness, "sleep_resp", date.fromisoformat(latest), 60)
        if w.get("sleep_resp") and base_resp:
            d_resp = round(w["sleep_resp"] - base_resp, 1)
            level = "warn" if d_resp >= RESP_WARN else "attention" if d_resp >= RESP_ATTENTION else "ok"
            signals.append({"key": "respiration", "value": round(w["sleep_resp"], 1), "note": _note("vs_baseline", delta=d_resp, baseline=round(base_resp, 1)), "level": level})
            base_shr = baseline(wellness, "sleep_hr", date.fromisoformat(latest), 60)
            illness_hint = bool(
                base_rhr and w.get("resting_hr") and w["resting_hr"] - base_rhr >= ILLNESS_HR_DELTA
                and base_shr and w.get("sleep_hr") and w["sleep_hr"] - base_shr >= ILLNESS_HR_DELTA
                and d_resp >= RESP_ATTENTION
            )
        if w.get("sleep_h"):
            base_sleep = baseline(wellness, "sleep_h", date.fromisoformat(latest), 30)
            h = w["sleep_h"]
            level = "warn" if h < 5 else "attention" if h < 6 or (base_sleep and h < base_sleep - 1.25) else "ok"
            note = _note("sleep", score=w.get("sleep_score") or None, baseline=round(base_sleep, 1) if base_sleep else None)
            signals.append({"key": "sleep_h", "value": round(h, 1), "note": note, "level": level})
    bb_day = today.isoformat() if (wellness.get(today.isoformat()) or {}).get("body_battery_high") else latest
    bb = (wellness.get(bb_day) or {}).get("body_battery_high") if bb_day else None
    if bb:
        days_ago = (today - date.fromisoformat(bb_day)).days
        signals.append({"key": "body_battery", "value": bb, "note": _note("highest", date=bb_day, days_ago=days_ago), "level": "attention" if bb < 40 else "ok"})
    if tsb is not None:
        # judged as % of fitness (api/dashboard.py FORM_BANDS: below -30% is high risk); the absolute numbers only
        # when there is no percentage yet
        if form_pct is not None:
            level = "warn" if form_pct < -30 else "ok"
        else:
            level = "warn" if tsb < -30 else "attention" if tsb < -20 else "ok"
        signals.append({"key": "tsb", "value": round(tsb, 1), "pct": form_pct, "note": _note("form_yesterday"), "level": level})
    if not signals:
        return None

    warns = sum(s["level"] == "warn" for s in signals)
    attention = sum(s["level"] == "attention" for s in signals)
    if warns >= 2 or (warns and attention):
        verdict = "recover"
    elif warns or attention:
        verdict = "easy"
    elif latest:
        verdict = "ready"
    else:
        verdict = "unknown"
    return {"verdict": verdict, "date": latest, "no_night": latest is None, "signals": signals, "illness_hint": illness_hint}


def as_text(r: dict) -> str:
    """One line for AI assistants (MCP get_context): the verdict and every signal with its number."""
    names = {"resting_hr": "rusthartslag", "respiration": "ademhaling in de slaap", "sleep_h": "slaap", "body_battery": "body battery", "tsb": "vorm"}
    units = {"resting_hr": " bpm", "respiration": "/min", "sleep_h": " u"}
    parts = []
    for s in r["signals"]:
        p = s["note"]["params"]
        value = f"{s['value']:+.0f}" + (f" ({s['pct']:+.0f}%)" if s.get("pct") is not None else "") if s["key"] == "tsb" else f"{s['value']}{units.get(s['key'], '')}"
        detail = {
            "vs_baseline": f"{p.get('delta', 0):+g} t.o.v. mediaan {p.get('baseline')}",
            "sleep": ", ".join(x for x in (f"score {p['score']}" if p.get("score") else "", f"normaal {p['baseline']} u" if p.get("baseline") else "") if x),
            "highest": f"hoogste op {p.get('date')}",
            "form_yesterday": "fitheid min vermoeidheid van gisteren",
        }.get(s["note"]["code"], "")
        parts.append(f"{names.get(s['key'], s['key'])} {value}" + (f" ({detail})" if detail else "") + f" [{s['level']}]")
    night = f"nacht van {r['date']}" if r["date"] else "geen nachtdata van afgelopen nacht"
    verdict = {"ready": "klaar", "easy": "rustig aan", "recover": "herstel", "unknown": "onbekend"}.get(r["verdict"], r["verdict"])
    hint = "; rusthartslag, hartslag in de slaap en ademhaling samen verhoogd: mogelijk komt er een verkoudheid aan" if r.get("illness_hint") else ""
    return f"{verdict} ({night}); " + "; ".join(parts) + hint
