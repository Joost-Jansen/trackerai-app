"""Markdown summaries the AI reads at the start of every session."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median

from tools.zones import NAMES, load_zones

SESSION_GAP = timedelta(minutes=30)  # runs saved in pieces with short stops count as one session


def _sum_zones(activities: list[dict]) -> dict[str, int] | None:
    with_zones = [a["hr_zones_s"] for a in activities if a.get("hr_zones_s")]
    if not with_zones:
        return None
    return {z: sum(x.get(z, 0) for x in with_zones) for z in NAMES}


def run_sessions(activities: list[dict]) -> list[dict]:
    """Merge consecutive runs with at most SESSION_GAP between end and next start into one session."""
    runs = sorted((a for a in activities if a["sport"] == "run"), key=lambda a: a["start_local"])
    groups: list[list[dict]] = []
    for a in runs:
        if groups:
            prev = groups[-1][-1]
            prev_end = datetime.fromisoformat(prev["start_local"]) + timedelta(
                seconds=prev.get("elapsed_time_s") or prev.get("moving_time_s") or 0
            )
            if datetime.fromisoformat(a["start_local"]) - prev_end <= SESSION_GAP:
                groups[-1].append(a)
                continue
        groups.append([a])

    sessions = []
    for g in groups:
        secs = sum(a.get("moving_time_s") or 0 for a in g)
        timed_hr = [(a["avg_hr"], a.get("moving_time_s") or 0) for a in g if a.get("avg_hr")]
        hr_time = sum(t for _, t in timed_hr)
        sessions.append(
            {
                "start_local": g[0]["start_local"],
                "sport": "run",
                "name": g[0].get("name"),
                "distance_km": round(sum(a.get("distance_km") or 0 for a in g), 2),
                "moving_time_s": secs,
                "avg_hr": round(sum(h * t for h, t in timed_hr) / hr_time) if hr_time else None,
                "hr_zones_s": _sum_zones(g),
                "parts": len(g),
            }
        )
    return sessions


def _day(activity: dict) -> date:
    return date.fromisoformat(activity["start_local"][:10])


def _hm(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def _pace(seconds: float, km: float) -> str:
    if not km:
        return "-"
    total = round(seconds / km)
    return f"{total // 60}:{total % 60:02d}"


def _fmt(value, digits=1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if isinstance(value, float) else str(value)


def this_week_md(activities: list[dict], wellness: dict, today: date, last_sync: str, zones: dict | None = None) -> str:
    zones = zones if zones is not None else load_zones()
    monday = today - timedelta(days=today.weekday())
    week = sorted((a for a in activities if monday <= _day(a) <= today), key=lambda a: a["start_local"])

    lines = [
        f"# Deze week ({monday.isoformat()} t/m {(monday + timedelta(days=6)).isoformat()})",
        "",
        f"Laatste sync: {last_sync} (Europe/Amsterdam)",
        "",
        "## Totalen",
        "",
        "| Sport | Aantal | km | Tijd |",
        "|---|---|---|---|",
    ]
    by_sport = defaultdict(list)
    for a in week:
        by_sport[a["sport"]].append(a)
    for sport, acts in sorted(by_sport.items()):
        km = sum(a.get("distance_km") or 0 for a in acts)
        secs = sum(a.get("moving_time_s") or 0 for a in acts)
        lines.append(f"| {sport} | {len(acts)} | {km:.1f} | {_hm(secs)} |")

    lines += ["", "## Activiteiten", "", "| Datum | Sport | Naam | km | Tempo/km | Gem. HR |", "|---|---|---|---|---|---|"]
    for a in week:
        lines.append(
            f"| {_day(a).isoformat()} | {a['sport']} | {a.get('name', '')} | {a.get('distance_km', 0):.1f} | "
            f"{_pace(a.get('moving_time_s') or 0, a.get('distance_km'))} | {_fmt(a.get('avg_hr'))} |"
        )

    order = ["run", "ride", "swim"]
    sports = [sp for sp in sorted(by_sport, key=lambda x: (order.index(x) if x in order else 99, x)) if sp in zones and _sum_zones(by_sport[sp])]
    if sports:
        per_sport = {sp: _sum_zones(by_sport[sp]) for sp in sports}
        lines += ["", "## Hartslagzones (eigen zones, zie zones.json)", "", "| Zone | " + " | ".join(sports) + " |"]
        lines += ["|---|" + "---|" * len(sports)]
        lines += [f"| {z} | " + " | ".join(_hm(per_sport[sp][z]) for sp in sports) + " |" for z in NAMES]

    lines += [
        "",
        "## Herstel, laatste 7 dagen",
        "",
        "| Datum | Slaap (u) | Slaapscore | HRV | Rust-HR | HR slaap | Adem slaap (/min) | Slaapstress | Body Battery max | Readiness |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for offset in range(6, -1, -1):
        d = (today - timedelta(days=offset)).isoformat()
        w = wellness.get(d)
        if w:
            lines.append(
                f"| {d} | {_fmt(w.get('sleep_h'))} | {_fmt(w.get('sleep_score'))} | {_fmt(w.get('hrv_last_night'))} | "
                f"{_fmt(w.get('resting_hr'))} | {_fmt(w.get('sleep_hr'))} | {_fmt(w.get('sleep_resp'))} | {_fmt(w.get('sleep_stress'))} | "
                f"{_fmt(w.get('body_battery_high'))} | {_fmt(w.get('readiness_score'))} |"
            )
    return "\n".join(lines) + "\n"


def last_90_days_md(activities: list[dict], wellness: dict, today: date, zones: dict | None = None) -> str:
    zones = zones if zones is not None else load_zones()
    this_monday = today - timedelta(days=today.weekday())
    weeks = [this_monday - timedelta(weeks=i) for i in range(12, -1, -1)]
    first = weeks[0]
    runs = [a for a in run_sessions(activities) if first <= _day(a) <= today]

    lines = [f"# Laatste 13 weken ({first.isoformat()} t/m {today.isoformat()})", "", "## Hardlopen per week", ""]
    lines += ["| Week vanaf | km | Runs | Langste (km) | Gem. HR | Gem. slaap (u) | Gem. HRV | Gem. rust-HR |", "|---|---|---|---|---|---|---|---|"]
    for monday in weeks:
        in_week = [a for a in runs if monday <= _day(a) < monday + timedelta(days=7)]
        days = [(monday + timedelta(days=i)).isoformat() for i in range(7)]
        ws = [wellness[d] for d in days if d in wellness]

        def avg(key, source):
            values = [x[key] for x in source if x.get(key) is not None]
            return round(mean(values), 1) if values else None

        km = sum(a.get("distance_km") or 0 for a in in_week)
        longest = max((a.get("distance_km") or 0 for a in in_week), default=0)
        lines.append(
            f"| {monday.isoformat()} | {km:.1f} | {len(in_week)} | {longest:.1f} | {_fmt(avg('avg_hr', in_week))} | "
            f"{_fmt(avg('sleep_h', ws))} | {_fmt(avg('hrv_last_night', ws))} | {_fmt(avg('resting_hr', ws))} |"
        )

    if runs:
        long_run = max(runs, key=lambda a: a.get("distance_km") or 0)
        lines += ["", f"Langste run: {long_run['distance_km']:.1f} km op {_day(long_run).isoformat()}"]

    lines += ["", "## Hardlopen per week in eigen zones (% van de tijd)", "", "| Week vanaf | Z1 | Z2 | Z3 | Z4-5 |", "|---|---|---|---|---|"]
    for monday in weeks:
        z = _sum_zones([a for a in runs if monday <= _day(a) < monday + timedelta(days=7)])
        total = sum(z.values()) if z else 0
        if total:
            share = [z["Z1"], z["Z2"], z["Z3"], z["Z4"] + z["Z5"]]
            lines.append(f"| {monday.isoformat()} | " + " | ".join(f"{round(x / total * 100)}%" for x in share) + " |")

    low, high = zones["run"]["bounds"][0], zones["run"]["bounds"][1] - 1
    lines += ["", f"## Tempo in Z2 hardlopen ({low}-{high} bpm), aerobe efficiëntie per 4 weken", "", "| Periode | Mediaan tempo/km | Runs |", "|---|---|---|"]
    for start in range(len(weeks) % 4, len(weeks), 4):  # anchored at the end: latest block is 4 full weeks
        block = weeks[start : start + 4]
        begin, end = block[0], block[-1] + timedelta(days=6)
        paces = [
            a["moving_time_s"] / a["distance_km"]
            for a in runs
            if begin <= _day(a) <= end and a.get("avg_hr") and low <= a["avg_hr"] <= high and a.get("distance_km")
        ]
        if paces:
            lines.append(f"| {begin.isoformat()} t/m {min(end, today).isoformat()} | {_pace(median(paces), 1)} | {len(paces)} |")
    return "\n".join(lines) + "\n"
