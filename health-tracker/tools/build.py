"""Regenerate routes/ and summary/ from data/.

    python tools/build.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.routes import build_routes
from tools.store import load_activities, load_wellness
from tools.summarize import last_90_days_md, this_week_md
from tools.zones import load_zones, zone_seconds

ROOT = Path(__file__).resolve().parents[1]


def _runs_with_gps(activities: list[dict]) -> list[dict]:
    runs = []
    for a in activities:
        latlng = (a.get("streams") or {}).get("latlng")
        if a["sport"] == "run" and latlng and a.get("distance_km"):
            runs.append(
                {
                    "activity_id": a["start_local"],
                    "date": a["start_local"][:10],
                    "distance_km": a["distance_km"],
                    "latlng": latlng,
                    "elevation_gain_m": a.get("elevation_gain_m"),
                    "avg_hr": a.get("avg_hr"),
                    "moving_time_s": a.get("moving_time_s"),
                }
            )
    return runs


def routes_md(routes: list[dict]) -> str:
    lines = [
        "# Vaste rondjes",
        "",
        "Gegenereerd door `tools/build.py`. Hernoemen: pas `name` aan in `routes.json`.",
        "Aanbeveling voor een afstand: `python tools/recommend.py --km <afstand>`.",
        "",
    ]
    if not routes:
        return "\n".join(lines + ["Nog geen vaste rondjes (minimaal 3 keer dezelfde route met GPS nodig).", ""])
    lines += [
        "| Id | Naam | km | Rondje | Hoogtemeters | Keer | Laatst | Tempo/km | HR |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in routes:
        lines.append(
            f"| {r['id']} | {r['name']} | {r['distance_km']:.1f} | {'ja' if r['is_loop'] else 'nee'} | "
            f"{r['elevation_gain_m']} | {r['runs']} | {r['last_run']} | {r['median_pace'] or '-'} | {r['median_hr'] or '-'} |"
        )
    return "\n".join(lines) + "\n"


def store_zone_seconds(root: Path, zones: dict) -> None:
    """Write hr_zones_s (own zones) into each activity file; only rewrites files whose value changed."""
    for path in sorted((root / "data" / "activities").glob("*/*.json")):
        a = json.loads(path.read_text())
        s = a.get("streams") or {}
        z = zone_seconds(zones, a["sport"], s["heartrate"], s["time"]) if s.get("heartrate") and s.get("time") else None
        if a.get("hr_zones_s") != z:
            if z is None:
                a.pop("hr_zones_s", None)
            else:
                a["hr_zones_s"] = z
            path.write_text(json.dumps(a, ensure_ascii=False, indent=1))


def build(root: Path = ROOT, today: date | None = None) -> None:
    root = Path(root)
    today = today or date.today()
    zones = load_zones(root if (root / "zones.json").exists() else ROOT)
    store_zone_seconds(root, zones)
    activities = load_activities(root)
    wellness = load_wellness(root)

    state_path = root / "data" / "sync_state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last_sync = state.get("last_sync_local", "nog nooit")
    if state.get("last_failed"):
        last_sync += f"; MISLUKT: {', '.join(state['last_failed'])} (data van die bron kan verouderd zijn)"

    routes_path = root / "routes" / "routes.json"
    existing = json.loads(routes_path.read_text()) if routes_path.exists() else []
    routes = build_routes(_runs_with_gps(activities), existing)

    routes_path.parent.mkdir(parents=True, exist_ok=True)
    routes_path.write_text(json.dumps(routes, ensure_ascii=False, indent=1))
    (root / "routes" / "routes.md").write_text(routes_md(routes))

    summary = root / "summary"
    summary.mkdir(parents=True, exist_ok=True)
    (summary / "this-week.md").write_text(this_week_md(activities, wellness, today, last_sync, zones))
    (summary / "last-90-days.md").write_text(last_90_days_md(activities, wellness, today, zones))


if __name__ == "__main__":
    build()
