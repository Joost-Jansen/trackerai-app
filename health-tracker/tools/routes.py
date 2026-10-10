"""Recognise recurring routes from GPS tracks, for runs and for rides.

A run or ride is reduced to a shape: start, end, distance and the set of ~100 m
grid cells it passes. Two are the same route when they cover mostly the same
cells and have a similar distance, wherever they start: riders and runners often start the
tracker on the bike only once out of town, at a different spot each time, and
a watch can start late on a run. Rides allow more difference in distance and in
the extra stretch of the longer one. A cluster of at least MIN_COUNT[sport]
activities becomes a route; its medoid (the member most like all others) is the
route's "average" track, the other members are its variations. Route ids carry a prefix per sport
(r1, r2, ... for runs; f1, f2, ... for rides) so both live in one routes table.
"""

from __future__ import annotations

import math
import re
from statistics import median

CELL_M = 100.0
REF_LAT = 52.0  # fixed so cell ids are stable across runs; fine for the Netherlands
M_PER_DEG_LAT = 111_320.0
DLAT = CELL_M / M_PER_DEG_LAT
DLON = CELL_M / (M_PER_DEG_LAT * math.cos(math.radians(REF_LAT)))

START_RADIUS_M = 300.0  # combining loops into one run (tools/recommend.py): same start
LOOP_RADIUS_M = 300.0  # watch is often stopped a few hundred metres before home
MAX_DISTANCE_DIFF = 0.10
MIN_OVERLAP = 0.75  # real data: same loop with a small detour overlaps ~76%
# per sport: max relative distance difference, share of the shorter track on the longer one,
# share of the longer track on the shorter one (the longer may have an extra lead-in)
MATCH = {"run": (MAX_DISTANCE_DIFF, MIN_OVERLAP, MIN_OVERLAP), "ride": (0.30, 0.70, 0.60)}
MIN_RUNS = 3
MIN_COUNT = {"run": MIN_RUNS, "ride": 2}  # few rides with GPS, so two of the same already count
PREFIX = {"run": "r", "ride": "f"}
LABELS = {"run": ("loop", "route"), "ride": ("bike loop", "bike route")}  # (loop, point to point)
# Generated names; the site shows them in the user's language (web/lib/i18n). Up to schema 3 they were Dutch
# ("rondje", "fietsrondje", "fietsroute"), which still counts as generated.
DEFAULT_NAME = re.compile(r"^\d+\.\d km (loop \(r|route \(r|bike loop \(f|bike route \(f|rondje \(r|fietsrondje \(f|fietsroute \(f)\d+\)$")
_DUTCH_LABELS = {"rondje": "loop", "fietsrondje": "bike loop", "fietsroute": "bike route"}


def haversine_m(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def _cell(point) -> tuple[int, int]:
    return (math.floor(point[0] / DLAT), math.floor(point[1] / DLON))


def shape(run: dict) -> dict | None:
    """Comparable shape of a run, or None when it has no GPS track."""
    latlng = run.get("latlng") or []
    if len(latlng) < 2:
        return None
    return {
        "start": list(latlng[0]),
        "end": list(latlng[-1]),
        "distance_km": run["distance_km"],
        "cells": {_cell(p) for p in latlng},
    }


def _covered(cells: set, other: set) -> float:
    """Share of `cells` that lie in or next to a cell of `other` (absorbs GPS noise)."""
    if not cells:
        return 0.0
    hit = sum(
        1 for (i, j) in cells if any((i + di, j + dj) in other for di in (-1, 0, 1) for dj in (-1, 0, 1))
    )
    return hit / len(cells)


def overlap(a: dict, b: dict) -> tuple[float, float]:
    """(share of the shorter track on the longer, share of the longer on the shorter)."""
    short, long_ = (a, b) if a["distance_km"] <= b["distance_km"] else (b, a)
    return _covered(short["cells"], long_["cells"]), _covered(long_["cells"], short["cells"])


def same_shape(a: dict, b: dict, sport: str = "run") -> bool:
    max_diff, min_short, min_long = MATCH.get(sport, MATCH["run"])
    longest = max(a["distance_km"], b["distance_km"])
    if longest <= 0 or abs(a["distance_km"] - b["distance_km"]) / longest > max_diff:
        return False
    s, l = overlap(a, b)
    return s >= min_short and l >= min_long


# Pairs that are not the same route by MATCH but plausibly the same circuit: ask the user.
# short: share of the shorter on the longer (a detour, shortcut or lead-in keeps this high);
# long: share of the longer on the shorter (the extra part is at most ~40% of the longer);
# near / near_diff: both shares at least `near` with a similar distance (partly other streets);
# max_diff: never a candidate beyond this relative distance difference (a loop done twice is not a variant).
CANDIDATE = {
    "run": {"short": 0.80, "long": 0.60, "near": 0.60, "near_diff": 0.25, "max_diff": 0.30},
    "ride": {"short": 0.75, "long": 0.60, "near": 0.50, "near_diff": 0.40, "max_diff": 0.40},
}


# reason codes with a Dutch default text; the site shows its own text per code (web/lib/texts.ts)
REASONS = {
    "same": "lijkt hetzelfde rondje",
    "other_start": "zelfde rondje, ander startpunt",
    "extra_loop": "zelfde rondje met een extra lus of omweg",
    "partly_other_way": "grotendeels hetzelfde rondje, deels een andere weg",
    "different": "ander rondje",
}
CONFIDENCE_BAND = {"same": (0.80, 1.0), "candidate": (0.50, 0.79), "different": (0.0, 0.49)}


def compare(a: dict, b: dict, sport: str = "run") -> dict:
    """How alike two shapes are: outcome `same` (MATCH, merged automatically), `candidate` (plausibly the same
    circuit or a variant of it: ask) or `different`, a confidence in 0..1 and a reason in Dutch.

    Cells are a set, so where a loop starts and which way round it goes do not matter."""
    max_diff = MATCH.get(sport, MATCH["run"])[0]
    cand = CANDIDATE.get(sport, CANDIDATE["run"])
    da, db = a["distance_km"], b["distance_km"]
    longest = max(da, db)
    d = abs(da - db) / longest if longest > 0 else 1.0
    s, l = overlap(a, b)
    raw = (0.6 * s + 0.4 * l) * (1 - 0.5 * min(d, 1.0))
    start_far = haversine_m(a["start"], b["start"]) > START_RADIUS_M
    if same_shape(a, b, sport):
        outcome, code = "same", "same"
    elif d <= cand["max_diff"] and ((s >= cand["short"] and l >= cand["long"]) or (min(s, l) >= cand["near"] and d <= cand["near_diff"])):
        outcome = "candidate"
        if s >= cand["short"] and start_far:
            code = "other_start"
        elif s >= cand["short"] and d > max_diff:
            code = "extra_loop"  # the longer one has it; distances are shown next to it
        else:
            code = "partly_other_way"
    else:
        outcome, code = "different", "different"
    # each outcome has its own band (same >= 0.8, candidate 0.5-0.79, different < 0.5), ordered by raw likeness
    lo, hi = CONFIDENCE_BAND[outcome]
    return {"outcome": outcome, "confidence": round(lo + (hi - lo) * raw, 2), "reason_code": code, "reason": REASONS[code], "overlap": [round(s, 2), round(l, 2)], "distance_diff": round(d, 2)}


VARIANT_GAP = 0.08  # a new length variant starts where sorted distances jump by 8% ...
VARIANT_MIN_KM = {"run": 0.5, "ride": 2.0}  # ... and by at least this much


def distance_variants(members: list[dict], sport: str = "run") -> list[dict]:
    """Length variants within a route: members grouped where their sorted distances jump clearly,
    shortest first, each with its median distance, count, members and last date."""
    ordered = sorted((m for m in members if m.get("distance_km")), key=lambda m: m["distance_km"])
    groups: list[list[dict]] = []
    min_km = VARIANT_MIN_KM.get(sport, VARIANT_MIN_KM["run"])
    for m in ordered:
        prev = groups[-1][-1]["distance_km"] if groups else None
        if prev is None or (m["distance_km"] - prev > min_km and m["distance_km"] > prev * (1 + VARIANT_GAP)):
            groups.append([m])
        else:
            groups[-1].append(m)
    return [
        {
            "distance_km": round(median(m["distance_km"] for m in g), 1),
            "runs": len(g),
            "activity_ids": [m["activity_id"] for m in sorted(g, key=lambda m: m["date"])],
            "last_run": max(m["date"] for m in g),
        }
        for g in groups
    ]


def same_route(a: dict, b: dict, sport: str = "run") -> bool:
    sa, sb = shape(a), shape(b)
    return sa is not None and sb is not None and same_shape(sa, sb, sport)


def _medoid(shapes: list[dict]) -> int:
    """Index of the member most like all others (highest summed overlap): the route's "average" track."""
    if len(shapes) <= 2:
        return len(shapes) - 1  # with two, the latest
    return max(range(len(shapes)), key=lambda i: (sum(min(overlap(shapes[i], o)) for j, o in enumerate(shapes) if j != i), i))


def _pace(seconds_per_km: float) -> str:
    total = round(seconds_per_km)
    return f"{total // 60}:{total % 60:02d}"


def _stored_shape(route: dict) -> dict:
    return {
        "start": route["start"],
        "end": route["end"],
        "distance_km": route["distance_km"],
        "cells": {tuple(c) for c in route["cells"]},
    }


def _next_number(ids, prefix: str) -> int:
    nums = [int(i[len(prefix):]) for i in ids if i.startswith(prefix) and i[len(prefix):].isdigit()]
    return 1 + max(nums, default=0)


def member_from_activity(a: dict) -> dict:
    """The fields a route needs of one activity (no track): for merging routes without loading streams."""
    return {
        "activity_id": a["id"],
        "date": a["start_local"][:10],
        "distance_km": a.get("distance_km"),
        "moving_time_s": a.get("moving_time_s"),
        "avg_hr": a.get("avg_hr"),
        "elevation_gain_m": a.get("elevation_gain_m"),
    }


def _num(route_id: str) -> int:
    return int(route_id[1:]) if route_id[1:].isdigit() else 0


def _custom_name(route: dict | None) -> str | None:
    """The name the user gave, or None for a generated default name."""
    name = (route or {}).get("name")
    return None if not name or DEFAULT_NAME.match(name) else name


def _groups(route: dict) -> list[dict]:
    """Parts of a route: one per original route or activity merged into it (just itself when nothing was merged)."""
    return route.get("groups") or [{"id": route["id"], "kind": "route", "activity_ids": list(route.get("activity_ids") or [])}]


def _sort_groups(groups: list[dict], keep: str) -> list[dict]:
    return sorted(groups, key=lambda g: (g["id"] != keep, g.get("kind", "route") == "activity", _num(g["id"]) if g.get("kind", "route") == "route" else 0, g["id"]))


def _summary(members: list[dict], sport: str) -> dict:
    """Route fields computed from its members (sorted by date)."""
    distance = round(median(m["distance_km"] for m in members), 2)
    hrs = [m["avg_hr"] for m in members if m.get("avg_hr")]
    timed = [m for m in members if m.get("moving_time_s") and m.get("distance_km")]
    paces = [m["moving_time_s"] / m["distance_km"] for m in timed]
    speeds = [m["distance_km"] / m["moving_time_s"] * 3600 for m in timed]
    return {
        "distance_km": distance,
        "elevation_gain_m": round(median(m.get("elevation_gain_m") or 0 for m in members)),
        "runs": len(members),
        "first_run": members[0]["date"],
        "last_run": members[-1]["date"],
        # tempo for runs, speed for rides; the other one is None so every route has the same fields
        "median_pace": _pace(median(paces)) if paces and sport != "ride" else None,
        "median_speed_kmh": round(median(speeds), 1) if speeds and sport == "ride" else None,
        "median_hr": round(median(hrs)) if hrs else None,
        "activity_ids": [m["activity_id"] for m in members],
        "distance_variants": distance_variants(members, sport),
    }


def _default_name(distance: float, is_loop: bool, route_id: str, sport: str) -> str:
    loop_label, line_label = LABELS.get(sport, LABELS["run"])
    return f"{distance:.1f} km {loop_label if is_loop else line_label} ({route_id})"


def english_default_name(name: str | None) -> str | None:
    """A generated Dutch name (schema 2) in English; any other name unchanged."""
    m = re.match(r"^(\d+\.\d km )(rondje|fietsrondje|fietsroute)( \([rf]\d+\))$", name or "")
    return f"{m[1]}{_DUTCH_LABELS[m[2]]}{m[3]}" if m else name


def _pairs(decisions: dict | None, key: str) -> list[tuple[str, str]]:
    return [(p[0], p[1]) for p in (decisions or {}).get(key) or [] if isinstance(p, (list, tuple)) and len(p) == 2]


def detect(
    runs: list[dict], existing: list[dict], sport: str = "run", min_runs: int | None = None, decisions: dict | None = None
) -> tuple[list[dict], list[dict]]:
    """Routes of one sport plus candidate pairs to ask the user about.

    - Members of existing routes stay on them, so ids, names and earlier merges are stable; new tracks join the
      group (original route) whose members they match most, if at least half of them, else form new clusters.
    - `decisions` = {"merge": [[id, id]], "separate": [[id, id]]} with route ids or activity ids: merged groups
      become one route under the older id (lowest number) and keep a name the user gave; an activity merged into a
      route becomes a group of its own, so later tracks like it join the route too. Answered pairs are not asked again.
    - Candidates: pairs of routes, and tracks that are on no route, whose `compare` outcome is not `different`.
    """
    prefix = PREFIX.get(sport, sport[:1])
    min_runs = MIN_COUNT.get(sport, MIN_RUNS) if min_runs is None else min_runs
    merges = _pairs(decisions, "merge")
    answered = {frozenset(p) for p in merges + _pairs(decisions, "separate")}

    tracks: dict[str, tuple[dict, dict]] = {}  # activity id -> (run, shape), oldest first
    for run in sorted(runs, key=lambda r: r["date"]):
        s = shape(run)
        if s is not None:
            tracks[run["activity_id"]] = (run, s)
    mine = sorted((r for r in existing if r.get("sport", "run") == sport), key=lambda r: (_num(r["id"]), r["id"]))
    by_id = {r["id"]: r for r in mine}
    route_ids = {g["id"] for r in mine for g in _groups(r) if g.get("kind", "route") == "route"} | set(by_id)

    # 1. groups of existing routes keep their members
    clusters: list[dict] = []  # {gid, kind, home (existing route id), members: [(run, shape)]}
    taken: set[str] = set()
    for route in mine:
        for g in _groups(route):
            members = [tracks[a] for a in g["activity_ids"] if a in tracks and a not in taken]
            if members:
                taken.update(m[0]["activity_id"] for m in members)
                members.sort(key=lambda m: m[0]["date"])
                clusters.append({"gid": g["id"], "kind": g.get("kind", "route"), "home": route["id"], "members": members})
    for aid in sorted({x for p in merges for x in p if x in tracks and x not in route_ids} - taken):
        taken.add(aid)
        clusters.append({"gid": aid, "kind": "activity", "home": None, "members": [tracks[aid]]})

    # 2. other tracks join the group where they match most members, and at least half of them, so one odd member
    #    cannot chain two different routes together
    for aid, (run, s) in tracks.items():
        if aid in taken:
            continue
        best, best_hits = None, 0
        for c in clusters:
            hits = sum(same_shape(m[1], s, sport) for m in c["members"])
            if hits * 2 >= len(c["members"]) and hits > best_hits:
                best, best_hits = c, hits
        if best:
            best["members"].append((run, s))
        else:
            clusters.append({"gid": None, "kind": "route", "home": None, "members": [(run, s)]})

    # 3. ids for new clusters that are big enough: an existing route of the same shape that lost all its members
    #    (older data without activity ids), else the next free number; absorbed ids are never reused
    homes = {c["home"] for c in clusters if c["home"]}
    unmatched = [r for r in mine if r["id"] not in homes and r.get("cells")]
    next_n = _next_number({r["id"] for r in existing} | route_ids, prefix)
    for c in clusters:
        if c["gid"] is None and len(c["members"]) >= min_runs:
            shapes = [m[1] for m in c["members"]]
            rep = shapes[_medoid(shapes)]
            match = next((r for r in unmatched if same_shape(_stored_shape(r), rep, sport)), None)
            if match:
                unmatched.remove(match)
                c["gid"] = c["home"] = match["id"]
            else:
                c["gid"] = f"{prefix}{next_n}"
                next_n += 1

    # 4. groups of one existing route, and merged pairs, form one route
    named = [c for c in clusters if c["gid"]]
    parent = {c["gid"]: c["gid"] for c in named}

    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        if a in parent and b in parent:
            parent[root(a)] = root(b)

    first_of_home: dict[str, str] = {}
    for c in named:
        if c["home"]:
            union(c["gid"], first_of_home.setdefault(c["home"], c["gid"]))
    for a, b in merges:
        union(a, b)
    components: dict[str, list[dict]] = {}
    for c in named:
        components.setdefault(root(c["gid"]), []).append(c)

    routes, parts = [], {}  # parts: route id -> [(group id, representative shape)]
    for comp in components.values():
        keep_c = min((c for c in comp if c["kind"] == "route"), key=lambda c: (_num(c["gid"]), c["gid"]), default=None)
        members = sorted((m for c in comp for m in c["members"]), key=lambda m: m[0]["date"])
        if keep_c is None or len(members) < min_runs:
            continue
        keep = keep_c["gid"]
        shapes = [m[1] for m in keep_c["members"]]
        m = _medoid(shapes)
        rep, medoid = shapes[m], keep_c["members"][m][0]
        known = by_id.get(keep) or by_id.get(keep_c["home"] or "")
        # an existing route stays a loop or a line (its generated name says which) when its main track changes
        is_loop = known["is_loop"] if known and "is_loop" in known else haversine_m(rep["start"], rep["end"]) <= LOOP_RADIUS_M
        ordered = _sort_groups([{"id": c["gid"], "kind": c["kind"], "activity_ids": [x[0]["activity_id"] for x in c["members"]]} for c in comp], keep)
        name = next((n for g in ordered for n in (_custom_name(by_id.get(g["id"])),) if n), None)
        name = name or next((n for c in comp for n in (_custom_name(by_id.get(c["home"])),) if n), None)
        summary = _summary([x[0] for x in members], sport)
        route = {
            "id": keep,
            "sport": sport,
            "name": name or _default_name(summary["distance_km"], is_loop, keep, sport),
            "distance_km": summary["distance_km"],
            "is_loop": is_loop,
            **{k: v for k, v in summary.items() if k != "distance_km"},
            "start": [round(x, 5) for x in rep["start"]],
            "end": [round(x, 5) for x in rep["end"]],
            "medoid_id": medoid["activity_id"],
            "cells": sorted([list(c) for c in rep["cells"]]),
        }
        if len(ordered) > 1:
            route["groups"] = ordered
        routes.append(route)
        parts[keep] = [(c["gid"], [x[1] for x in c["members"]][_medoid([x[1] for x in c["members"]])]) for c in comp]
    routes.sort(key=lambda r: (-r["runs"], r["id"]))
    return routes, _candidates(routes, parts, tracks, answered, sport)


def _side_route(r: dict) -> dict:
    return {"id": r["id"], "kind": "route", "name": r["name"], "distance_km": r["distance_km"], "runs": r["runs"]}


def _best(shapes_a: list, shapes_b: list, sport: str) -> dict | None:
    best = None
    for _, a in shapes_a:
        for _, b in shapes_b:
            c = compare(a, b, sport)
            if c["outcome"] != "different" and (best is None or c["confidence"] > best["confidence"]):
                best = c
    return best


def _candidates(routes: list[dict], parts: dict, tracks: dict, answered: set, sport: str) -> list[dict]:
    def asked(a: set, b: set) -> bool:
        return any(frozenset((x, y)) in answered for x in a for y in b)

    ids = {r["id"]: {r["id"]} | {g for g, _ in parts[r["id"]]} for r in routes}
    out = []
    by_age = sorted(routes, key=lambda r: (_num(r["id"]), r["id"]))
    for i, ra in enumerate(by_age):
        for rb in by_age[i + 1:]:
            best = None if asked(ids[ra["id"]], ids[rb["id"]]) else _best(parts[ra["id"]], parts[rb["id"]], sport)
            if best:
                out.append({"a": _side_route(ra), "b": _side_route(rb), "sport": sport, "outcome": best["outcome"], "confidence": best["confidence"], "reason_code": best["reason_code"], "reason": best["reason"]})
    on_route = {aid for r in routes for aid in r["activity_ids"]}
    for aid, (run, s) in tracks.items():
        if aid in on_route:
            continue
        options = [(r, _best(parts[r["id"]], [(aid, s)], sport)) for r in by_age if not asked(ids[r["id"]], {aid})]
        options = [(r, c) for r, c in options if c]
        if options:
            r, best = max(options, key=lambda x: x[1]["confidence"])
            side = {"id": aid, "kind": "activity", "name": None, "distance_km": run["distance_km"], "runs": 1, "date": run["date"]}
            out.append({"a": _side_route(r), "b": side, "sport": sport, "outcome": best["outcome"], "confidence": best["confidence"], "reason_code": best["reason_code"], "reason": best["reason"]})
    return sorted(out, key=lambda c: -c["confidence"])


def build_routes(runs: list[dict], existing: list[dict], sport: str = "run", min_runs: int | None = None) -> list[dict]:
    """Cluster runs (or rides) of one sport into routes; keep id and name of existing routes (see `detect`).

    `existing` may hold routes of every sport: only those of `sport` are used, so a ride never takes over a
    run route's id or name. Numbering continues per prefix (r for runs, f for rides).
    """
    return detect(runs, existing, sport=sport, min_runs=min_runs)[0]


def apply_merge(routes: list[dict], a: str, b: str, members: dict[str, dict]) -> list[dict] | None:
    """Merge right away what `detect` would merge on the next run: two routes of one sport (the older id stays), or
    an activity into a route. `members`: activity id -> `member_from_activity`. None when the pair does not apply.
    The kept route keeps its main track; statistics and length variants are recomputed."""
    by_id = {r["id"]: r for r in routes}
    ra, rb = by_id.get(a), by_id.get(b)
    if ra and rb:
        if ra is rb or ra.get("sport", "run") != rb.get("sport", "run"):
            return None
        keep, other = sorted((ra, rb), key=lambda r: (_num(r["id"]), r["id"]))
        extra = _groups(other)
    elif ra or rb:
        keep, other, act = (ra, None, b) if ra else (rb, None, a)
        if act not in members or act in (keep.get("activity_ids") or []):
            return None
        extra = [{"id": act, "kind": "activity", "activity_ids": [act]}]
    else:
        return None
    sport = keep.get("sport", "run")
    groups = _sort_groups(_groups(keep) + extra, keep["id"])
    ids = list(dict.fromkeys(x for g in groups for x in g["activity_ids"]))
    found = sorted((members[x] for x in ids if x in members), key=lambda m: m["date"])
    if not found:
        return None
    summary = _summary(found, sport)
    name = _custom_name(keep) or _custom_name(other) or _default_name(summary["distance_km"], keep.get("is_loop", True), keep["id"], sport)
    merged = {**keep, **summary, "name": name, "groups": groups}
    return [merged if r is keep else r for r in routes if r is not other]
