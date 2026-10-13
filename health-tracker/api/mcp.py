"""MCP server (Model Context Protocol, streamable HTTP, JSON responses) so an AI assistant can use the training data
as tools. Any MCP client works: Claude, ChatGPT, Codex, Copilot, Cursor, Gemini, ...

    POST /api/mcp            Authorization: Bearer <agent token>     (Claude Code: claude mcp add --transport http ...)
    POST /api/mcp/<token>    token in the path, for clients that only take a URL (a connector in claude.ai or ChatGPT)

Stateless: every request is one JSON-RPC message (or a batch). No server-sent events, no sessions.
Tools read and write the same data as the website: what an agent changes, the user sees on the site.
"""

from __future__ import annotations

import json
import threading
from datetime import date
from typing import Callable

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from api.errors import ApiError
from trackerai_accounts.oauth import OAuth, PREFIX
from api.dashboard import build_dashboard, today_form_pct, today_tsb
from api.daily import as_markdown as day_md, day_view
from api.history import activity_detail, list_activities
from api.plans import enrich, parse_table
from api.readiness import as_text as readiness_text, readiness
from api.routes_api import suggest
from api.trends import build_trends
from trackerai_websec import log_redact
from tools import db, wahoo
from tools.sports import effort_kind
from tools.summarize import last_90_days_md, this_week_md

PROTOCOLS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
INSTRUCTIONS = (
    "Trainingsdata van {name} (Garmin: lopen, fietsen, zwemmen; slaap en herstel), de doelen, het trainingsschema en het logboek. "
    "Begin een coachingsessie met get_context. Antwoord in het Nederlands, scheid observatie, interpretatie en advies, "
    "reken met de data in plaats van te schatten. Hartslagzones komen uit de eigen zones per sport, nooit uit Garmins hrTimeInZone. "
    "Een run na zwemmen of fietsen op dezelfde dag (triathlon, brick) is niet vergelijkbaar met een losse run. "
    "Schrijf aan het eind van een sessie een logentry (add_log). Geen medisch advies."
)


def instructions(user) -> str:
    text = INSTRUCTIONS.format(name=user.display_name or user.username)
    if getattr(user, "agent_scope", "write") == "read":
        text = text.replace("Schrijf aan het eind van een sessie een logentry (add_log).", "Alleen lezen: verander geen gegevens.")
    return text

SESSION_TABLE_HELP = (
    "Markdown- of CSV-tabel met kopregel. Kolommen: Datum (verplicht, 2026-10-06 of 6-10), Sport (lopen/fietsen/zwemmen/kracht/rust), "
    "Type, Km, Duur (min of 1:10), Zone (Z2 of Z3-Z4), Omschrijving."
)


# Codes in the data are English; the text for the agent is Dutch (see INSTRUCTIONS).
PLAN_STATUS_NL = {"active": "actief", "finished": "afgerond", "stopped": "gestopt"}
SESSION_STATUS_NL = {"done": "gedaan", "missed": "gemist", "today": "vandaag", "planned": "gepland", "rest": "rust"}
FORM_STATUS_NL = {"transition": "overgang (fitheid zakt weg)", "fresh": "fris", "neutral": "neutraal", "optimal": "optimaal trainen", "high_risk": "hoog risico"}


def _str(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


TOOLS = [
    {"name": "get_context", "description": "Alles voor de start van een coachingsessie, als markdown: profiel, doelen, actief schema met gedaan/gemist per sessie, vorm, deze week, laatste 90 dagen, rondjes en de laatste logentries.", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "list_activities",
        "description": "Activiteiten, nieuwste eerst, als tabel met id, datum, sport, afstand, tijd, tempo, gemiddelde hartslag en tijd per zone.",
        "inputSchema": {"type": "object", "properties": {"sport": _str("run, ride, swim, strength_training, ..."), "from": _str("vanaf datum YYYY-MM-DD"), "to": _str("tot en met datum YYYY-MM-DD"), "limit": {"type": "integer", "default": 30}}},
    },
    {
        "name": "get_activity",
        "description": "Eén activiteit met details: kilometersplits, ronden, zones, decoupling (hartslagdrift), rondje en eerdere keren daarop, andere activiteiten die dag.",
        "inputSchema": {"type": "object", "properties": {"id": _str("activity id, bv. 2026-09-27_1130_run")}, "required": ["id"]},
    },
    {
        "name": "get_day",
        "description": "Eén dag en de nacht ervoor van het horloge (Garmin): slaap (duur, score, fases, van-tot), rusthartslag, hartslag, ademhaling en stress in de slaap, "
        "SpO2, Body Battery, stress, stappen en intensiteitsminuten, elk tegen de eigen normaal (mediaan 60 dagen); de nacht in getallen (laagste hartslag, "
        "gemiddeld, laatste 2 uur slaap tegen de rest) en een tabel per half uur met hartslag, stress, Body Battery, ademhaling, SpO2 en slaapfase.",
        "inputSchema": {"type": "object", "properties": {"day": _str("YYYY-MM-DD, de dag waarop je wakker werd; standaard de laatste dag met data")}},
    },
    {"name": "get_trends", "description": "Vorm (CTL/ATL/TSB, laatste 60 dagen), volume per week, tempo in Z2, VO2max, herstel per week, records, wedstrijden, voorspelde wedstrijdtijden en inzichten.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_plan", "description": "Het actieve trainingsschema als tabel, per sessie met status (gedaan, gemist, vandaag, gepland, rust), wat er gedaan is en een voorgesteld rondje. Een activiteit tot 2 dagen voor of na een open sessie van dezelfde sport telt voor die sessie; Gedaan km per week telt alle activiteiten van de sporten in het schema.", "inputSchema": {"type": "object", "properties": {}}},
    {
        "name": "create_plan",
        "description": "Nieuw trainingsschema uit een tabel. Wordt het actieve schema; het vorige gaat naar afgerond. Gebruik preview=true om eerst te zien hoe de tabel gelezen wordt.",
        "inputSchema": {"type": "object", "properties": {"title": _str("titel"), "table": _str(SESSION_TABLE_HELP), "goal": _str("doel, bv. 10 km onder 50 minuten"), "race": _str("wedstrijd en datum"), "notes": _str("toelichting bij het schema"), "preview": {"type": "boolean", "default": False}}, "required": ["title", "table"]},
    },
    {
        "name": "replace_plan_sessions",
        "description": "Vervang alle sessies van het actieve schema (of plan_id) door een tabel. Haal eerst get_plan op, pas de tabel aan en stuur hem volledig terug.",
        "inputSchema": {"type": "object", "properties": {"table": _str(SESSION_TABLE_HELP), "plan_id": {"type": "integer"}, "preview": {"type": "boolean", "default": False}}, "required": ["table"]},
    },
    {
        "name": "set_plan_status",
        "description": "Zet het actieve schema (of plan_id) op afgerond, gestopt of weer actief.",
        "inputSchema": {"type": "object", "properties": {"status": {"type": "string", "enum": ["active", "finished", "stopped"], "description": "active (actief), finished (afgerond) of stopped (gestopt)"}, "plan_id": {"type": "integer"}}, "required": ["status"]},
    },
    {
        "name": "sync_now",
        "description": "Haal nu nieuwe data op uit Garmin (en Wahoo), zoals de knop op de site: activiteiten, slaap en herstel. Wacht tot ongeveer een minuut; loopt de sync langer, dan meldt het waar hij is en kun je sync_now later opnieuw aanroepen (dat start geen tweede). Gebruik het als de laatste sync (get_context) niet van vandaag is.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_log",
        "description": "Schrijf een logentry (kind=log: vraag, belangrijkste data, besluit/advies van deze sessie) of een analyse (kind=analysis). Markdown.",
        "inputSchema": {"type": "object", "properties": {"title": _str("onderwerp"), "body": _str("markdown"), "kind": {"type": "string", "enum": ["log", "analysis"], "default": "log"}, "day": _str("YYYY-MM-DD, standaard vandaag")}, "required": ["title", "body"]},
    },
    {"name": "list_log", "description": "Laatste logentries of analyses.", "inputSchema": {"type": "object", "properties": {"kind": {"type": "string", "enum": ["log", "analysis"], "default": "log"}, "limit": {"type": "integer", "default": 10}}}},
    {"name": "get_doc", "description": "Profiel (zones, max HR, PR's) of doelen, als markdown.", "inputSchema": {"type": "object", "properties": {"key": {"type": "string", "enum": ["profile", "goals"]}}, "required": ["key"]}},
    {
        "name": "update_doc",
        "description": "Vervang profiel of doelen door nieuwe markdown. Haal eerst get_doc op en stuur het volledige document terug.",
        "inputSchema": {"type": "object", "properties": {"key": {"type": "string", "enum": ["profile", "goals"]}, "body": _str("volledige markdown")}, "required": ["key", "body"]},
    },
    {
        "name": "suggest_route",
        "description": "Vaste rondjes (of combinaties vanaf dezelfde start) voor een afstand, het langst niet gelopen eerst.",
        "inputSchema": {"type": "object", "properties": {"km": {"type": "number"}, "tolerance": {"type": "number", "default": 0.05}, "sport": {"type": "string", "enum": ["run", "ride"], "default": "run"}}, "required": ["km"]},
    },
]


WRITE_NAMES = {"create_plan", "replace_plan_sessions", "set_plan_status", "add_log", "update_doc", "update_feedback", "sync_now"}
SYNC_WAIT_S = 55  # what an MCP call waits for a sync; a longer one keeps running in the background


class ToolError(Exception):
    pass


# --- formatting -----------------------------------------------------------------------------------------

# Only for an admin's token: feedback from all users of the site (api/feedback.py).
FEEDBACK_TOOLS = [
    {
        "name": "list_feedback",
        "description": "Feedback van gebruikers van de site: kapot (bug) of een idee, met pagina, browser, versie en recente fouten. Nieuwste eerst. Standaard alleen open meldingen (new en planned).",
        "inputSchema": {"type": "object", "properties": {"status": _str("new, planned, fixed, wontfix of all", enum=["new", "planned", "fixed", "wontfix", "all", "open"], default="open"), "limit": {"type": "integer", "default": 30}}},
    },
    {
        "name": "update_feedback",
        "description": "Status en/of antwoord bij een melding. De gebruiker ziet beide op de site. Status: new, planned, fixed, wontfix.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}, "status": _str("Nieuwe status", enum=list(db.FEEDBACK_STATUSES)), "reply": _str("Antwoord voor de gebruiker, kort en in hun taal")}, "required": ["id"]},
    },
]


def feedback_md(items: list[dict]) -> str:
    out = []
    for f in items:
        ctx = f.get("context") or {}
        head = f"## #{f['id']} {f['kind']} · {f['status']} · {f['created_at'][:16].replace('T', ' ')} · {f.get('username') or f['user_id']}"
        lines = [head, f["message"].strip()]
        meta = [f"pagina {f['page']}" if f.get("page") else None, f"versie {ctx['version']}" if ctx.get("version") else None, ctx.get("browser"), ctx.get("screen"), ctx.get("language")]
        lines.append("_" + " · ".join(m for m in meta if m) + "_")
        for e in ctx.get("errors") or []:
            lines.append(f"- fout: {e.get('message')} {('(' + str(e.get('where')) + ')') if e.get('where') else ''}".rstrip())
        if f.get("has_screenshot"):
            lines.append(f"- screenshot: /api/feedback/{f['id']}/screenshot (alleen in de browser)")
        if f.get("reply"):
            lines.append(f"Antwoord: {f['reply']}")
        out.append("\n".join(lines))
    return "\n\n".join(out) or "Geen feedback."


def _clock(seconds) -> str:
    if not seconds:
        return "-"
    s = round(seconds)
    h, m = divmod(s // 60, 60)
    return f"{h}:{m:02d}:{s % 60:02d}" if h else f"{m}:{s % 60:02d}"


def _pace(a: dict) -> str:
    if not a.get("distance_km") or not a.get("moving_time_s"):
        return "-"
    kind = effort_kind(a["sport"])
    if kind == "speed":
        return f"{a['distance_km'] / a['moving_time_s'] * 3600:.1f} km/u"
    if kind == "swim":
        return f"{_clock(a['moving_time_s'] / a['distance_km'] / 10)}/100m"
    if kind == "row":
        return f"{_clock(a['moving_time_s'] / a['distance_km'] / 2)}/500m"
    return f"{_clock(a['moving_time_s'] / a['distance_km'])}/km"


def _distance_note(a: dict) -> str:
    if a.get("distance_doubtful"):
        return f" (GPS gaf {a.get('gps_distance_km') or 0} km: onbetrouwbaar in open water, telt niet mee)"
    if a.get("distance_manual"):
        return " (afstand door gebruiker gecorrigeerd)"
    return ""


def _zones(z: dict | None) -> str:
    total = sum((z or {}).values())
    return " ".join(f"{k} {round(v / total * 100)}%" for k, v in z.items() if v) if total else "-"


def activities_md(items: list[dict]) -> str:
    lines = ["| Id | Datum | Sport | Naam | km | Tijd | Tempo | HR | Zones |", "|---|---|---|---|---|---|---|---|---|"]
    for a in items:
        lines.append(
            f"| {a['id']} | {a['start_local'][:16].replace('T', ' ')} | {a['sport']} | {a.get('name') or ''} | {a.get('distance_km') or ('GPS?' if a.get('distance_doubtful') else '-')} | "
            f"{_clock(a.get('moving_time_s'))} | {_pace(a)} | {a.get('avg_hr') or '-'} | {_zones(a.get('hr_zones_s'))} |"
        )
    return "\n".join(lines)


def activity_md(a: dict) -> str:
    out = [
        f"# {a.get('name') or a['sport']} ({a['id']})",
        f"{a['start_local']} · {a['sport']} · {a.get('distance_km') or '-'} km{_distance_note(a)} · {_clock(a.get('moving_time_s'))} bewegend"
        + (f" ({_clock(a['elapsed_time_s'])} totaal)" if a.get("elapsed_time_s") else "")
        + f" · {_pace(a)} · HR {a.get('avg_hr') or '-'} (max {a.get('max_hr') or '-'})",
        f"Zones: {_zones(a.get('hr_zones_s'))}" + (" (zones voor deze sport zijn geschat)" if a.get("zone_estimate") else "") + (f", grenzen {a['zone_bounds']}" if a.get("zone_bounds") else ""),
    ]
    if a.get("decoupling_pct") is not None:
        out.append(f"Decoupling (Pa:HR, tweede helft t.o.v. eerste): {a['decoupling_pct']}%")
    if a.get("same_day"):
        out.append("Zelfde dag: " + ", ".join(f"{x['sport']} {x['start_local'][11:16]} ({x.get('distance_km') or '-'} km)" for x in a["same_day"]))
    if a.get("route"):
        r = a["route"]
        hist = ", ".join(f"{h['date']} {_clock(h['pace_s_per_km'])}/km HR {h.get('avg_hr') or '-'}" for h in r["history"][-8:])
        out.append(f"Rondje {r.get('name')} ({r['id']}), laatste keren: {hist}")
    if a.get("splits"):
        out += ["", "| Km | Tijd | HR | Hoogte m |", "|---|---|---|---|"]
        out += [f"| {s['km']} | {_clock(s['seconds'])} | {s.get('avg_hr') or '-'} | {s.get('elevation_m', '-')} |" for s in a["splits"]]
    if a.get("laps") and len(a["laps"]) > 1:
        out += ["", "| Ronde | km | Tijd | HR |", "|---|---|---|---|"]
        out += [f"| {i} | {lap.get('distance_km')} | {_clock(lap.get('time_s'))} | {lap.get('avg_hr') or '-'} |" for i, lap in enumerate(a["laps"], 1)]
    return "\n".join(out)


def plan_md(plan: dict | None) -> str:
    if not plan:
        return "Geen actief schema."
    out = [f"# {plan['title']} (id {plan['id']}, {PLAN_STATUS_NL.get(plan['status'], plan['status'])}, door {plan['author']})"]
    if plan.get("goal") or plan.get("race"):
        out.append(f"Doel: {plan.get('goal') or '-'} · wedstrijd: {plan.get('race') or '-'}")
    if plan.get("notes"):
        out.append(plan["notes"])
    out += ["", "| Datum | Sport | Type | Km | Duur | Zone | Omschrijving | Status | Gedaan | Rondje |", "|---|---|---|---|---|---|---|---|---|---|"]
    for s in plan["sessions"]:
        d = s.get("done")
        done = (f"{d['distance_km']} km {_clock(d['moving_time_s'])} HR {d.get('avg_hr') or '-'}" + (f", {d['zone_pct']}% volgens zone" if d.get("zone_pct") is not None else "")) if d else ""
        if d and d.get("date") != s["date"]:
            done += f", gedaan op {d['date']}"
        rs = s.get("route_suggestion")
        out.append(
            f"| {s['date']} | {s['sport']} | {s.get('kind') or ''} | {s.get('distance_km') or ''} | {s.get('duration_min') or ''} | {s.get('target_zone') or ''} | "
            f"{s.get('description') or ''} | {SESSION_STATUS_NL.get(s.get('status'), s.get('status') or '')} | {done} | {' + '.join(rs['names']) if rs else ''} |"
        )
    out += ["", "| Week | Gepland km | Gedaan km | Sessies gedaan | Gemist |", "|---|---|---|---|---|"]
    out += [f"| {w['week']} | {w['planned_km']} | {w['done_km']} | {w['done']}/{w['planned']} | {w['missed']} |" for w in plan["weeks"]]
    return "\n".join(out)


# --- the server -------------------------------------------------------------------------------------------


class Server:
    """Answers MCP messages for one user (an api.users.User): their data, written as `agent`."""

    def __init__(self, user, today: Callable[[], date], runner=None):
        self.user = user
        self.runner = runner  # api.sync_runner.SyncRunner: sync_now
        self.store = user.store
        self.engine = user.scope  # every db call takes the user's scope
        self.today = today

    def _plan(self, plan_id: int | None) -> dict:
        plan = db.get_plan(self.engine, plan_id) if plan_id else db.active_plan(self.engine)
        if not plan:
            raise ToolError("Geen actief schema" if not plan_id else f"Schema {plan_id} bestaat niet")
        return plan

    def _full(self, plan: dict | None) -> dict | None:
        return enrich(plan, self.store.activities, self.store.routes, self.today()) if plan else None

    def _sync(self) -> str:
        """The site's sync (api/connections.py), from here: start it, wait a while, say what came in."""
        if self.runner is None:
            raise ToolError("Synchroniseren kan hier niet.")
        if not db.get_setting(self.engine, "garmin_tokens") and not db.get_setting(self.engine, wahoo.TOKENS_KEY):
            raise ToolError("Geen Garmin of Wahoo gekoppeld: koppel op de site onder Instellingen, Koppelingen.")
        uid = self.user.id
        if uid in self.runner.running:
            step = (self.runner.progress.get(uid) or {}).get("step") or "bezig"
            return f"Er loopt al een sync (sinds {self.runner.running[uid]}, stap: {step}). Roep sync_now over een minuut opnieuw aan."
        before = len(self.store.activities)
        worker = threading.Thread(target=self.runner.sync_user, args=(uid,), name=f"sync-{uid}", daemon=True)
        worker.start()
        worker.join(SYNC_WAIT_S)
        if worker.is_alive():
            step = (self.runner.progress.get(uid) or {}).get("step") or "bezig"
            return f"De sync loopt nog (stap: {step}) en gaat op de achtergrond door. Roep sync_now over een minuut opnieuw aan voor de uitkomst."
        self.store.invalidate()
        state = db.get_setting(self.engine, "sync_state") or {}
        failed = state.get("last_failed") or []
        new = len(self.store.activities) - before
        return (f"Sync klaar: laatste sync {state.get('last_sync_local') or '-'}, {new} nieuwe activiteit{'en' if new != 1 else ''}."
                + (f" Mislukt: {', '.join(failed)}." if failed else ""))

    def call(self, name: str, args: dict, who: str) -> str:
        if name in WRITE_NAMES and getattr(self.user, "agent_scope", "write") == "read":
            raise ToolError("This connection only has read access.")
        s, today = self.store, self.today()
        for field, most in (("title", 200), ("race", 200), ("goal", 5000)):  # as the columns in tools/db.py
            if isinstance(args.get(field), str) and len(args[field]) > most:
                raise ToolError(f"{field} is langer dan {most} tekens")
        if name == "sync_now":
            return self._sync()
        if name == "get_context":
            profile, goals = db.get_document(self.engine, "profile"), db.get_document(self.engine, "goals")
            dash = build_dashboard(s.activities, s.wellness, s.zones, today, s.last_sync, s.rhr_fallback)
            f = dash["form"]
            parts = [f"# Trainingscontext {today.isoformat()}", f"Laatste sync: {s.last_sync}.", "", "## Profiel", profile["body"] if profile else "(leeg)", "", "## Doelen", goals["body"] if goals else "(leeg)", "", "## Actief schema", plan_md(self._full(db.active_plan(self.engine)))]
            rd = readiness(s.wellness, today, today_tsb(f), today_form_pct(f), s.rhr_fallback)
            if rd:
                parts.append(f"\n## Klaar voor vandaag\n{readiness_text(rd)}")
            if f:
                parts.append(f"\n## Vorm\nFitheid (CTL) {f['ctl']}, vermoeidheid (ATL) {f['atl']}, vorm (TSB) {f['tsb']} ({f.get('pct') if f.get('pct') is not None else '-'}% van fitheid): {FORM_STATUS_NL.get(f['status'], f['status'])}. Piek CTL {f['ctl_peak']} op {f['ctl_peak_date']}.")
            parts += [this_week_md(s.activities, s.wellness, today, s.last_sync, s.zones), last_90_days_md(s.activities, s.wellness, today, s.zones)]
            parts += ["## Vaste rondjes", "", "| Id | Naam | km | Keer | Laatst | Tempo/km | HR |", "|---|---|---|---|---|---|---|"]
            parts += [f"| {r['id']} | {r.get('name')} | {r.get('distance_km')} | {r.get('runs')} | {r.get('last_run')} | {r.get('median_pace') or (str(r['median_speed_kmh']) + ' km/u' if r.get('median_speed_kmh') else '-')} | {r.get('median_hr')} |" for r in s.routes]
            parts += ["", "## Laatste logentries"]
            parts += [f"### {e['day']}: {e['title']} ({e['author']})\n{e['body'].strip()}" for e in db.list_entries(self.engine, kind="log", limit=5)]
            return "\n".join(parts)
        if name == "list_activities":
            items = list_activities(s.activities, args.get("sport"), args.get("from"), args.get("to"))[: int(args.get("limit") or 30)]
            return activities_md(items) if items else "Geen activiteiten gevonden."
        if name == "get_activity":
            a = activity_detail(str(args.get("id", "")), s.activities, s.streams, s.zones, s.routes)
            if a is None:
                raise ToolError(f"Activiteit {args.get('id')} niet gevonden; gebruik list_activities voor de ids.")
            return activity_md(a)
        if name == "get_day":
            try:
                day = date.fromisoformat(args["day"]) if args.get("day") else None
            except ValueError:
                raise ToolError("day als YYYY-MM-DD")
            return day_md(day_view(self.engine, s.wellness, day, s.rhr_fallback, today))
        if name == "get_trends":
            t = build_trends(s.activities, s.wellness, s.zones, s.streams, today, s.rhr_fallback, plan=db.active_plan(self.engine), last_sync=s.last_sync)
            t["form"] = t["form"][-60:]
            t["recovery_daily"] = t.get("recovery_daily", [])[-60:]  # keeps the agent response small
            t["weekly"] = t["weekly"][-26:]
            return json.dumps(t, ensure_ascii=False)
        if name == "get_plan":
            return plan_md(self._full(db.active_plan(self.engine)))
        if name in ("create_plan", "replace_plan_sessions"):
            items, warnings = parse_table(args.get("table", ""), today.year)
            note = "".join(f"\nLet op: {w}" for w in warnings)
            if not items:
                raise ToolError("Geen sessies in de tabel." + note)
            if args.get("preview"):
                return plan_md({"id": "-", "title": args.get("title", "voorbeeld"), "status": "voorbeeld", "author": who, "sessions": items, "weeks": []}) + note
            if name == "create_plan":
                pid = db.create_plan(self.engine, args["title"], who, args.get("goal"), args.get("race"), args.get("notes"))
                db.add_sessions(self.engine, pid, items)
            else:
                pid = self._plan(args.get("plan_id"))["id"]
                db.replace_sessions(self.engine, pid, items)
            return plan_md(self._full(db.get_plan(self.engine, pid))) + note
        if name == "set_plan_status":
            status = args.get("status")
            status = {nl: code for code, nl in PLAN_STATUS_NL.items()}.get(status, status)  # the Dutch words still work
            if status not in PLAN_STATUS_NL:
                raise ToolError("status is active, finished of stopped")
            plan = self._plan(args.get("plan_id"))
            if status == "active":
                for p in db.list_plans(self.engine):
                    if p["status"] == "active" and p["id"] != plan["id"]:
                        db.set_plan_status(self.engine, p["id"], "finished")
            db.set_plan_status(self.engine, plan["id"], status)
            return f"Schema {plan['id']} ({plan['title']}) staat op {PLAN_STATUS_NL[status]}."
        if name == "add_log":
            kind = args.get("kind") or "log"
            if kind not in ("log", "analysis"):
                raise ToolError("kind is log of analysis")
            day = args.get("day") or today.isoformat()
            try:
                date.fromisoformat(day)
            except ValueError:
                raise ToolError("day als YYYY-MM-DD")
            eid = db.add_entry(self.engine, kind, args["title"], args["body"], author=who, day=day)
            return f"{'Logentry' if kind == 'log' else 'Analyse'} {eid} opgeslagen voor {day}."
        if name == "list_log":
            rows = db.list_entries(self.engine, kind=args.get("kind") or "log", limit=min(int(args.get("limit") or 10), 100))
            return "\n\n".join(f"## {e['day']}: {e['title']} ({e['author']})\n{e['body'].strip()}" for e in rows) or "Nog niets."
        if name in ("get_doc", "update_doc"):
            key = args.get("key")
            if key not in ("profile", "goals"):
                raise ToolError("key is profile of goals")
            if name == "update_doc":
                db.put_document(self.engine, key, args["body"], author=who)
                return f"{key} bijgewerkt."
            doc = db.get_document(self.engine, key)
            return doc["body"] if doc else "(leeg)"
        if name == "suggest_route":
            sport = args.get("sport") or "run"
            opts = suggest(s.routes, s.activities, lambda _: None, float(args["km"]), today, float(args.get("tolerance") or 0.05), sport=sport)
            if not opts:
                return "Geen vaste rondjes gevonden."
            verb = "gefietst" if sport == "ride" else "gelopen"
            return "\n".join(
                f"{i}. {' + '.join(o['names'])}: {o['total_km']} km ({o['deviation_km']:+.1f} km), {o['days_since']} dagen niet {verb}" for i, o in enumerate(opts, 1)
            )
        if name in ("list_feedback", "update_feedback"):
            if not self.user.is_admin:
                raise ToolError("Alleen voor beheerders")
            engine = self.engine.engine
            if name == "list_feedback":
                status = args.get("status") or "open"
                items = db.list_feedback(engine, status=None if status in ("all", "open") else status, limit=min(int(args.get("limit") or 30), 200))
                if status == "open":
                    items = [f for f in items if f["status"] in ("new", "planned")]
                return feedback_md(items)
            status = args.get("status")
            if status is not None and status not in db.FEEDBACK_STATUSES:
                raise ToolError(f"status is een van {', '.join(db.FEEDBACK_STATUSES)}")
            if not db.update_feedback(engine, int(args["id"]), status=status, reply=args.get("reply")):
                raise ToolError(f"Feedback {args['id']} bestaat niet")
            return feedback_md([db.get_feedback(engine, int(args["id"]))])
        raise ToolError(f"Onbekende tool {name}")

    def handle(self, msg: dict, who: str) -> dict | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # notification (initialized, cancelled): nothing to answer
            return None

        def ok(result):
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        if method == "initialize":
            asked = params.get("protocolVersion")
            return ok(
                {
                    "protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "health-tracker", "title": "health-tracker", "version": "1.0"},
                    "instructions": instructions(self.user),
                }
            )
        if method == "ping":
            return ok({})
        if method == "tools/list":
            tools = TOOLS + (FEEDBACK_TOOLS if self.user.is_admin else [])
            if getattr(self.user, "agent_scope", "write") == "read":
                tools = [t for t in tools if t["name"] not in WRITE_NAMES]
            if getattr(self.user, "agent_oauth", False):
                tools = [{**t, "securitySchemes": [{"type": "oauth2", "scopes": ["health:write" if t["name"] in WRITE_NAMES else "health:read"]}]} for t in tools]
            return ok({"tools": tools})
        if method == "tools/call":
            try:
                text = self.call(params.get("name", ""), params.get("arguments") or {}, who)
                return ok({"content": [{"type": "text", "text": text}], "isError": False})
            except (ToolError, KeyError, ValueError, TypeError) as e:
                return ok({"content": [{"type": "text", "text": f"Fout: {e}"}], "isError": True})
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def make_router(today: Callable[[], date], bearer_user: Callable[[Request], object], token_user: Callable[[str], object | None], guards=None, accounts=None,
                runner=None) -> APIRouter:
    """`bearer_user(request)` authenticates the header (raises 401) and returns the User; `token_user(token)` checks a
    token from the path. Each request is answered for that user only. Only tokens: a browser session cookie is no way
    in (the CSRF origin check leaves /api/mcp out, because MCP clients are not browsers). Failed tokens count against
    the caller's IP (`guards.token_ip`)."""
    r = APIRouter()
    log_redact.install()  # access logs print the path: keep the token of /api/mcp/<token> out of them

    async def serve(request: Request, user) -> Response:
        server, who = Server(user, today, runner), user.author
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
        if isinstance(body, list):
            # In a thread: the tools read the database, and sync_now waits for Garmin.
            out = [x for x in [await run_in_threadpool(server.handle, m, who) for m in body if isinstance(m, dict)] if x]
            return JSONResponse(out) if out else Response(status_code=202)
        if not isinstance(body, dict):
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}, status_code=400)
        res = await run_in_threadpool(server.handle, body, who)
        return JSONResponse(res) if res else Response(status_code=202)

    @r.post("/api/mcp")
    async def mcp(request: Request):
        if not request.headers.get("authorization", "").lower().startswith("bearer "):
            raise ApiError(401, "invalid_agent_token", headers=OAuth(accounts).challenge("health") if accounts else None)
        return await serve(request, bearer_user(request, Response()))

    @r.post("/api/mcp/{token}")
    async def mcp_path(token: str, request: Request):
        if token.startswith(PREFIX):
            raise ApiError(401, "invalid_agent_token")
        ip = guards.ip(request) if guards else None
        if guards and guards.token_ip.blocked(ip):
            raise guards.too_many(guards.token_ip, ip)
        who = token_user(token)
        if not who:
            if guards:
                guards.token_ip.hit(ip)
            raise ApiError(401, "invalid_agent_token")
        return await serve(request, who)

    @r.get("/api/mcp")
    @r.get("/api/mcp/{token}")
    def no_stream():
        return Response(status_code=405, headers={"Allow": "POST"})

    return r
