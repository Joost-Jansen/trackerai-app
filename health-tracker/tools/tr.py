"""`tr`: command line access to the health-tracker API for scripts and AI assistants.

Needs two environment variables:
    TRAINING_API_URL    e.g. https://your-domain.example
    TRAINING_API_TOKEN  an agent token from Settings, Agents (never write it into a file in this repo)

    python tools/tr.py context                      # everything to read at the start of a session (markdown)
    python tools/tr.py doc get profile|goals
    python tools/tr.py doc put profile|goals < file.md
    python tools/tr.py log "Titel" < body.md        # add a log entry (today, Europe/Amsterdam)
    python tools/tr.py analysis "Titel" < body.md   # add an analysis
    python tools/tr.py entries [log|analysis]
    python tools/tr.py plan show                    # active plan with sessions
    python tools/tr.py plan create < plan.json      # {"title","goal","race","notes","sessions":[{date,sport,kind,distance_km,duration_min,target_zone,description}]}
    python tools/tr.py plan sessions <id> < sessions.json
    python tools/tr.py get /api/<path>              # raw JSON from any GET endpoint
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

ZONES = ("Z1", "Z2", "Z3", "Z4", "Z5")


class ApiError(Exception):
    pass


def call(method: str, path: str, body=None):
    base = os.environ.get("TRAINING_API_URL", "").rstrip("/")
    token = os.environ.get("TRAINING_API_TOKEN", "")
    if not base or not token:
        raise ApiError("zet TRAINING_API_URL en TRAINING_API_TOKEN")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise ApiError(f"{e.code}: {e.read().decode(errors='replace')[:300]}") from e


def _hm(seconds) -> str:
    m = round((seconds or 0) / 60)
    return f"{m // 60}:{m % 60:02d}"


def context_markdown(ctx: dict) -> str:
    d = ctx["dashboard"]
    out = [f"# Trainingscontext (laatste sync: {ctx['last_sync']})", ""]
    out += ["## Profiel", "", ctx.get("profile") or "_leeg_", "", "## Doelen", "", ctx.get("goals") or "_leeg_", ""]
    for period, label in (("week", "deze week"), ("month", "deze maand")):
        out.append(f"## Zones {label} (eigen zones per sport)")
        z = d["zones"][period]
        if not z:
            out.append("_geen training met hartslag_")
        for sport, share in sorted(z.items(), key=lambda kv: kv[0] != "all"):
            pct = " ".join(f"{k} {round(share['pct'][k])}%" for k in ZONES)
            out.append(f"- {sport}: {_hm(share['total_s'])} u; {pct}")
        out.append("")
    f = d.get("form")
    if f:
        status = {"transition": "overgang (fitheid zakt weg)", "fresh": "fris", "neutral": "neutraal", "optimal": "optimaal trainen", "high_risk": "hoog risico"}.get(f["status"], f["status"])
        if f.get("pct") is not None:
            status += f" ({f['pct']}% van fitheid)"
        out += [f"## Vorm: {status}", f"Fitheid {f['ctl']:.0f}, vermoeidheid {f['atl']:.0f}, vorm {f['tsb']:+.0f}; piek fitheid {f['ctl_peak']:.0f} op {f['ctl_peak_date']}.", ""]
    out.append("## Volume deze week (gemiddelde 4 weken)")
    for sport, v in d["volume"]["week"].items():
        avg = d["volume"]["avg4w"].get(sport, {})
        out.append(f"- {sport}: {v['km']:.1f} km, {_hm(v['seconds'])} ({avg.get('km', 0):.1f} km, {_hm(avg.get('seconds'))})")
    out.append("")
    plan = ctx.get("active_plan")
    out.append("## Actief schema")
    if plan:
        out.append(f"**{plan['title']}** (id {plan['id']}); doel: {plan.get('goal') or '-'}; race: {plan.get('race') or '-'}")
        for s in plan["sessions"]:
            size = f"{s['distance_km']} km" if s.get("distance_km") else f"{s.get('duration_min') or '?'} min"
            out.append(f"- {s['date']} {s['sport']} {s.get('kind') or ''} {size} {s.get('target_zone') or ''} {s.get('description') or ''}".rstrip())
    else:
        out.append("_geen_")
    out += ["", "## Vaste rondjes"]
    for r in ctx.get("routes", []):
        typical = f"{r['median_speed_kmh']} km/u" if r.get("sport") == "ride" and r.get("median_speed_kmh") else f"{r.get('median_pace')}/km"
        out.append(f"- {r['id']} {r['name']}: {r['distance_km']} km, {r['runs']}x, laatst {r['last_run']}, {typical} bij {r.get('median_hr')} bpm")
    out += ["", "## Recente log"]
    for e in ctx.get("recent_log", []):
        out += [f"### {e['day']}: {e['title']} ({e['author']})", e["body"].strip(), ""]
    if ctx.get("recent_analyses"):
        out.append("## Recente analyses")
        out += [f"- {e['day']}: {e['title']} ({e['author']})" for e in ctx["recent_analyses"]]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "context":
        print(context_markdown(call("GET", "/api/context")))
    elif cmd == "doc" and len(rest) == 2 and rest[0] == "get":
        print(call("GET", f"/api/docs/{rest[1]}")["body"])
    elif cmd == "doc" and len(rest) == 2 and rest[0] == "put":
        call("PUT", f"/api/docs/{rest[1]}", {"body": sys.stdin.read()})
        print(f"{rest[1]} bijgewerkt")
    elif cmd in ("log", "analysis") and rest:
        r = call("POST", "/api/entries", {"kind": cmd, "title": rest[0], "body": sys.stdin.read()})
        print(f"{cmd} {r['id']} opgeslagen")
    elif cmd == "entries":
        kind = f"?kind={rest[0]}" if rest else ""
        for e in call("GET", f"/api/entries{kind}"):
            print(f"{e['day']} [{e['kind']}] {e['title']} ({e['author']})")
    elif cmd == "plan" and rest == ["show"]:
        print(json.dumps(call("GET", "/api/plans/active")["plan"], indent=1, ensure_ascii=False))
    elif cmd == "plan" and rest == ["create"]:
        p = call("POST", "/api/plans", json.load(sys.stdin))
        print(f"schema {p['id']} aangemaakt en actief, {len(p['sessions'])} sessies")
    elif cmd == "plan" and len(rest) == 2 and rest[0] == "sessions":
        p = call("PUT", f"/api/plans/{rest[1]}/sessions", json.load(sys.stdin))
        print(f"schema {p['id']}: {len(p['sessions'])} sessies")
    elif cmd == "get" and rest:
        print(json.dumps(call("GET", rest[0]), indent=1, ensure_ascii=False))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ApiError as err:
        print(f"fout: {err}", file=sys.stderr)
        raise SystemExit(1)
