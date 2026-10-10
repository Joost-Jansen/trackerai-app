"""Recommend one of the regular routes (or a combination of loops) for a target distance, per sport.

    python tools/recommend.py --km 14
    python tools/recommend.py --km 14 --tolerance 0.08 --start r2
    python tools/recommend.py --km 60 --sport ride
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from itertools import combinations, combinations_with_replacement
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.routes import MIN_COUNT, START_RADIUS_M, haversine_m

ROOT = Path(__file__).resolve().parents[1]
FALLBACK_MAX_DEVIATION = 0.5  # when nothing fits, still hide options more than 50% off target


def _days_since(day: str, today: date) -> int:
    return (today - date.fromisoformat(day)).days


def _candidates(routes: list[dict], max_parts: int):
    for r in routes:
        yield [r]
    loops = [r for r in routes if r["is_loop"]]
    for size in range(2, max_parts + 1):
        for combo in combinations_with_replacement(loops, size):
            if all(haversine_m(a["start"], b["start"]) <= START_RADIUS_M for a, b in combinations(combo, 2)):
                yield list(combo)


def recommend(
    routes: list[dict],
    target_km: float,
    today: date,
    tolerance: float = 0.05,
    max_parts: int = 3,
    start: str | None = None,
    limit: int = 3,
    sport: str = "run",
) -> list[dict]:
    """Only routes of `sport` are suggested or combined; routes without a sport are runs."""
    routes = [r for r in routes if r.get("sport", "run") == sport]
    if start:
        anchor = next((r for r in routes if r["id"] == start), None)
        if anchor is None:
            return []
        routes = [r for r in routes if haversine_m(r["start"], anchor["start"]) <= START_RADIUS_M]

    options = []
    for parts in _candidates(routes, max_parts):
        total = round(sum(p["distance_km"] for p in parts), 2)
        deviation = round(total - target_km, 2)
        options.append(
            {
                "parts": [p["id"] for p in parts],
                "total_km": total,
                "deviation_km": deviation,
                "within_tolerance": abs(deviation) <= tolerance * target_km,
                "days_since": min(_days_since(p["last_run"], today) for p in parts),
            }
        )

    fitting = [o for o in options if o["within_tolerance"]]
    if fitting:
        # fewest parts first, then the route(s) not run for the longest, then closest distance
        fitting.sort(key=lambda o: (len(o["parts"]), -o["days_since"], abs(o["deviation_km"])))
        return fitting[:limit]
    options.sort(key=lambda o: (abs(o["deviation_km"]), len(o["parts"])))
    close = [o for o in options if abs(o["deviation_km"]) <= FALLBACK_MAX_DEVIATION * target_km]
    return (close or options[:1])[:limit]


def _describe(parts: list[str], by_id: dict) -> str:
    counts = Counter(parts)
    return " + ".join(
        f"{n}× {by_id[rid]['name']}" if n > 1 else by_id[rid]["name"] for rid, n in counts.items()
    )


def _typical(route: dict, sport: str) -> str:
    if sport == "ride":
        speed = route.get("median_speed_kmh")
        return f"{speed:.1f}".replace(".", ",") + " km/u" if speed else "-"
    return f"{route.get('median_pace')}/km"


def format_recommendations(recs: list[dict], routes: list[dict], target_km: float, sport: str = "run") -> str:
    by_id = {r["id"]: r for r in routes}
    ride = sport == "ride"
    if not recs:
        what = "fietsrondjes" if ride else "rondjes"
        return (
            f"Geen vaste {what} gevonden voor {target_km} km. Er zijn nog geen vaste {what} "
            f"(minstens {MIN_COUNT.get(sport, 3)} keer dezelfde route nodig)."
        )
    lines = [f"Aanbeveling voor {target_km} km:"]
    if not recs[0]["within_tolerance"]:
        lines.append("Geen combinatie binnen de tolerantie; dit zijn de dichtstbijzijnde opties.")
    for i, rec in enumerate(recs, 1):
        first = by_id[rec["parts"][0]]
        lines.append(
            f"{i}. {_describe(rec['parts'], by_id)}: {rec['total_km']:.1f} km "
            f"({rec['deviation_km']:+.1f} km), laatst {'gefietst' if ride else 'gelopen'} {rec['days_since']} dagen geleden, "
            f"typisch {_typical(first, sport)} bij {first['median_hr']} bpm"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--km", type=float, required=True, help="doelafstand in km")
    parser.add_argument("--tolerance", type=float, default=0.05, help="toegestane afwijking als fractie (0.05 = 5%%)")
    parser.add_argument("--max-parts", type=int, default=3, help="maximaal aantal rondjes in een combinatie")
    parser.add_argument("--start", help="alleen rondjes met hetzelfde startpunt als deze route-id")
    parser.add_argument("--sport", choices=["run", "ride"], default="run", help="run (lopen) of ride (fietsen)")
    parser.add_argument("--routes", type=Path, default=ROOT / "routes" / "routes.json")
    args = parser.parse_args(argv)

    routes = json.loads(args.routes.read_text()) if args.routes.exists() else []
    recs = recommend(routes, args.km, date.today(), args.tolerance, args.max_parts, args.start, sport=args.sport)
    print(format_recommendations(recs, routes, args.km, sport=args.sport))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
