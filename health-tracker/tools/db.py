"""The training database: the single source of truth for the website, the sync and the agents.

SQLAlchemy Core on Postgres: on Railway, on a laptop (compose.dev.yml at the repository root) and in the tests (packages/testing).

Multi-user: every data table carries `user_id`, and every function that
touches a user's data takes a `Scope(engine, user_id)` instead of an engine, so no query can forget the user.
Global tables: `users`, `invites`, `app_settings`, `agent_tokens` (a token points at its user).

    engine = connect(os.environ["DATABASE_URL"])
    create_schema(engine)          # creates or migrates (v1 single-user -> v2 multi-user)
    s = Scope(engine, user_id)
    load_activities(s)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    Text,
    create_engine,
    delete,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine

from tools.routes import english_default_name
from tools.sports import sport_of
from tools.store import _rank, activity_id, merge, prepare, same_start, source_distance
from tools.store import remove_source as _strip_source

SCHEMA_VERSION = 9  # v9: achievements (a new table only: create_all makes it)
meta = MetaData()

# --- global tables -------------------------------------------------------------------------------------------

users = Table(
    "users",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("username", String(40), nullable=False, unique=True),
    Column("display_name", String(80)),
    Column("password_hash", String(100), nullable=False),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("suspended", Boolean, nullable=False, default=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_login_at", DateTime(timezone=True)),
    # schema 6 (added to existing databases by _migrate_v6):
    Column("session_version", Integer, nullable=False, default=0, server_default="0"),  # +1 ends every other session
    Column("consent_at", DateTime(timezone=True)),  # consent to processing health data (GDPR art. 9), at registration
    Column("privacy_version", String(20)),  # the privacy statement consented to
    Column("totp_secret", Text),  # encrypted (tools/secretbox.py); set by setup, in use once totp_enabled_at is set
    Column("totp_enabled_at", DateTime(timezone=True)),
    Column("totp_last_step", Integer),  # the last code's time step: a code is only good once
    Column("totp_backup", JSON),  # hashes of the unused backup codes
    Column("betas", JSON),  # beta features an admin switched on for this user (api/betas.py), a list of ids
)
SECRET_USER_FIELDS = ("password_hash", "totp_secret", "totp_last_step", "totp_backup")  # never leave tools/db.py by default
V6_USER_COLUMNS = ("session_version", "consent_at", "privacy_version", "totp_secret", "totp_enabled_at", "totp_last_step", "totp_backup")
V7_USER_COLUMNS = ("betas",)
invites = Table(
    "invites",
    meta,
    Column("code", String(40), primary_key=True),
    Column("created_by", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
    Column("used_by", Integer),
    Column("used_at", DateTime(timezone=True)),
)
app_settings = Table("app_settings", meta, Column("key", String(64), primary_key=True), Column("value", JSON, nullable=False))
agent_tokens = Table(
    "agent_tokens",
    meta,
    Column("id", String(16), primary_key=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("name", String(60), nullable=False),
    Column("hash", String(64), nullable=False, unique=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# --- per-user tables -------------------------------------------------------------------------------------------

activities = Table(
    "activities",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("id", String(64), nullable=False),
    Column("start_local", String(19), nullable=False, index=True),
    Column("start_utc", String(20), nullable=False),
    Column("sport", String(40), nullable=False, index=True),
    Column("data", JSON, nullable=False),  # the merged record without streams
    PrimaryKeyConstraint("user_id", "id"),
)
streams = Table(
    "activity_streams",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("activity_id", String(64), nullable=False),
    Column("data", JSON, nullable=False),
    PrimaryKeyConstraint("user_id", "activity_id"),
)
fit_files = Table(
    "fit_files",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("activity_id", String(64), nullable=False),
    Column("data", LargeBinary, nullable=False),
    PrimaryKeyConstraint("user_id", "activity_id"),
)
wellness = Table(
    "wellness",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("day", String(10), nullable=False),
    Column("data", JSON, nullable=False),
    PrimaryKeyConstraint("user_id", "day"),
)
intraday = Table(
    # Garmin's series through one calendar day (heart rate, stress, Body Battery, respiration, SpO2) plus the sleep
    # that ended that morning, compact (tools/intraday.py): about 25-30 kB a day. Wellness keeps the daily summary.
    "intraday",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("day", String(10), nullable=False),
    Column("data", JSON, nullable=False),
    PrimaryKeyConstraint("user_id", "day"),
)
settings = Table(
    "settings",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("key", String(64), nullable=False),
    Column("value", JSON, nullable=False),
    PrimaryKeyConstraint("user_id", "key"),
)
documents = Table(
    "documents",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("key", String(64), nullable=False),
    Column("body", Text, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("updated_by", String(40), nullable=False),
    PrimaryKeyConstraint("user_id", "key"),
)
entries = Table(
    "entries",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("kind", String(20), nullable=False, index=True),  # log | analysis
    Column("day", String(10), nullable=False, index=True),
    Column("title", String(200), nullable=False),
    Column("body", Text, nullable=False),
    Column("author", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
plans = Table(
    "plans",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("title", String(200), nullable=False),
    Column("goal", Text),
    Column("race", String(200)),
    Column("notes", Text),
    Column("status", String(20), nullable=False),  # draft | active | finished | stopped
    Column("author", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
sessions = Table(
    "plan_sessions",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("plan_id", Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("date", String(10), nullable=False),
    Column("sport", String(40), nullable=False),
    Column("kind", String(60)),
    Column("distance_km", Float),
    Column("duration_min", Integer),
    Column("target_zone", String(20)),
    Column("description", Text),
    Column("route_id", String(20)),
)
plan_links = Table(
    # What the user decided about an activity in a plan: linked to the session of its sport on `session_date`, or
    # (session_date NULL) not part of the plan. Keyed by date, not session id: editing a plan replaces its sessions.
    "plan_links",
    meta,
    Column("user_id", Integer, nullable=False, index=True),
    Column("plan_id", Integer, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
    Column("activity_id", String(80), nullable=False),
    Column("session_date", String(10)),
    PrimaryKeyConstraint("plan_id", "activity_id"),
)
achievements = Table(
    # What the user achieved and wants to keep: a challenge finished, a race, a record. Finished plans are achievements
    # too; those are derived from the plans (api/plans.py), not stored here.
    "achievements",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("day", String(10), nullable=False),
    Column("title", String(200), nullable=False),
    Column("body", Text),
    Column("kind", String(20), nullable=False),  # challenge | race | record | milestone
    Column("sport", String(40)),
    Column("plan_id", Integer),
    Column("author", String(40), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
routes = Table(
    "routes",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("id", String(20), nullable=False),
    Column("sport", String(40), nullable=False),
    Column("data", JSON, nullable=False),
    PrimaryKeyConstraint("user_id", "id"),
)

gear = Table(
    # Shoes, a bike, anything an activity wears out. From Garmin (garmin_uuid, garmin: what Garmin says about it) or
    # added on the site. Distance is computed (api/gear.py): start_km + what Garmin counted before the activities here +
    # the activities linked in activity_gear.
    "gear",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("kind", String(20), nullable=False),  # shoes | bike | other
    Column("name", String(100), nullable=False),
    Column("brand", String(60)),
    Column("model", String(80)),
    Column("start_km", Float, nullable=False, default=0),  # used before it was tracked here (and not in Garmin)
    Column("max_km", Float),  # replace at; None: Garmin's limit, else the kind's default (api/gear.py)
    Column("since", String(10)),  # in use from: default gear only fills in activities from this day
    Column("retired_on", String(10)),
    Column("notes", Text),
    Column("garmin_uuid", String(64)),
    Column("garmin", JSON),  # {name, kind, total_km, activities, max_km, status, date_begin, date_end} as Garmin last said
    Column("created_at", DateTime(timezone=True), nullable=False),
)
activity_gear = Table(
    # Which gear an activity used. source: garmin (as set in Garmin Connect), manual (chosen on the site; wins over
    # the rest) or default (the sport's default gear, for an activity no other source gave gear).
    "activity_gear",
    meta,
    Column("user_id", Integer, nullable=False, index=True),
    Column("activity_id", String(80), nullable=False),
    Column("gear_id", Integer, nullable=False),
    Column("source", String(10), nullable=False),
    PrimaryKeyConstraint("user_id", "activity_id", "gear_id", "source"),
)

# --- nutrition (tools/nutrition/, api/nutrition.py) -----------------------------------------------------------
# Foods are global (a food table such as NEVO, imported by an admin, and Open Food Facts products cached on first use);
# the rest is per user. Nutrient dicts use the keys of tools/nutrition/nutrients.py, per 100 g or 100 ml (`unit`).

foods = Table(
    "foods",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(10), nullable=False),  # nevo | off | usda
    Column("source_code", String(40), nullable=False),  # the source's own id: NEVO-code, EAN, FDC id
    Column("name_nl", String(200), nullable=False),
    Column("name_en", String(200)),
    Column("synonyms", Text),
    Column("food_group", String(80)),
    Column("unit", String(2), nullable=False, default="g"),  # g | ml: what the per_100 values are per 100 of
    Column("per_100", JSON, nullable=False),
    Column("default_portion_g", Float),
    Column("source_version", String(40)),  # "NEVO-online 2025/9.0": a new release replaces, past meals keep their snapshot
    Column("brand", String(100)),
)
user_foods = Table(
    # Foods a user added from a label, or a recipe: theirs only, never mixed into the global table.
    "user_foods",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("name_nl", String(200), nullable=False),
    Column("name_en", String(200)),
    Column("brand", String(100)),
    Column("unit", String(2), nullable=False, default="g"),
    Column("per_100", JSON, nullable=False),
    Column("default_portion_g", Float),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
meals = Table(
    "meals",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("day", String(10), nullable=False, index=True),
    Column("eaten_at", String(5), nullable=False),  # HH:MM, local time
    Column("moment", String(12), nullable=False),  # breakfast | lunch | dinner | snack | training | drinks
    Column("input", String(10), nullable=False),  # photo | search | barcode | repeat | agent
    Column("photo_id", Integer),
    Column("note", Text),
    Column("ai_run_id", Integer),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)
meal_items = Table(
    # One food in a meal with its amount and a snapshot of what it held: a new food table release never changes a day
    # already logged. grams_source: ai (estimated from a photo), user (typed or confirmed), memory (the usual portion).
    "meal_items",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("meal_id", Integer, ForeignKey("meals.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("position", Integer, nullable=False, default=0),
    Column("food_ref", String(60), nullable=False),  # nevo:1234 | off:8710000000000 | user:12
    Column("name", String(200), nullable=False),
    Column("unit", String(2), nullable=False, default="g"),
    Column("grams", Float, nullable=False),
    Column("grams_ai", Float),
    Column("grams_low", Float),
    Column("grams_high", Float),
    Column("grams_source", String(10), nullable=False, default="user"),
    Column("confidence", Float),
    Column("nutrients", JSON, nullable=False),  # scaled to `grams`
)
meal_photos = Table(
    "meal_photos",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("mime", String(20), nullable=False),
    Column("data", LargeBinary, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),  # None: kept
)
portion_memory = Table(
    # Your usual amount of a food, learnt from what you confirmed: the default next time.
    "portion_memory",
    meta,
    Column("user_id", Integer, nullable=False),
    Column("food_ref", String(60), nullable=False),
    Column("grams_typical", Float, nullable=False),
    Column("uses", Integer, nullable=False, default=0),
    Column("last_used", String(10)),
    PrimaryKeyConstraint("user_id", "food_ref"),
)
meal_templates = Table(
    # Favourites: a meal to log again in one tap. items: [{food_ref, name, unit, grams}].
    "meal_templates",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("name", String(100), nullable=False),
    Column("moment", String(12)),
    Column("items", JSON, nullable=False),
    Column("position", Integer, nullable=False, default=0),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
nutrition_ai_runs = Table(
    # Every photo analysis: model, prompt version, time and tokens (cost) and the raw answer, to measure accuracy.
    "nutrition_ai_runs",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("model", String(60), nullable=False),
    Column("prompt_version", String(20), nullable=False),
    Column("request_ms", Integer),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("response", JSON),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

admin_audit = Table(
    # What admins did: who, what, to whom, when. Shown at the bottom of the admin page.
    "admin_audit",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("actor", String(40), nullable=False),
    Column("action", String(40), nullable=False),
    Column("target", String(80)),
    Column("detail", String(200)),
    Column("at", DateTime(timezone=True), nullable=False),
)
feedback = Table(
    # What users report from the site: something broken or an idea. Read by the admins (settings, MCP).
    "feedback",
    meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, nullable=False, index=True),
    Column("kind", String(10), nullable=False),  # bug | idea
    Column("message", Text, nullable=False),
    Column("page", String(300)),
    Column("context", JSON),  # browser, screen, version, recent errors: what makes a report fixable
    Column("screenshot", LargeBinary),
    Column("screenshot_type", String(20)),
    Column("status", String(10), nullable=False, default="new"),  # new | planned | fixed | wontfix
    Column("reply", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True)),
)

USER_TABLES = (
    activities,
    streams,
    fit_files,
    wellness,
    intraday,
    settings,
    documents,
    entries,
    plan_links,
    plans,
    achievements,
    routes,
    feedback,
    gear,
    activity_gear,
    meal_items,
    meals,
    meal_photos,
    user_foods,
    portion_memory,
    meal_templates,
    nutrition_ai_runs,
)
SESSION_FIELDS = ("date", "sport", "kind", "distance_km", "duration_min", "target_zone", "description", "route_id")


@dataclass(frozen=True)
class Scope:
    """One user's view of the database."""

    engine: Engine
    user_id: int


def connect(url: str, **kwargs) -> Engine:
    """An engine for DATABASE_URL (postgres:// or postgresql://, as Railway gives it), on psycopg 3. The same rules as
    trackerai_accounts.store.sqlalchemy_url, written out here: the sync image (Dockerfile.sync) has tools/ only."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            url = "postgresql+psycopg://" + url[len(scheme) :]
    if not url.startswith("postgresql+psycopg://"):
        raise ValueError("DATABASE_URL must be a postgresql:// URL; SQLite is not supported any more")
    return create_engine(url, pool_pre_ping=True, future=True, **kwargs)


def _now() -> datetime:
    return datetime.now(UTC)


# --- schema and migration ----------------------------------------------------------------------------------------


def _v1_meta() -> tuple[MetaData, dict[str, Table]]:
    """The single-user schema (before T19), only to read old data during the migration."""
    m = MetaData()
    t = {
        "activities": Table(
            "activities",
            m,
            Column("id", String(64), primary_key=True),
            Column("start_local", String(19)),
            Column("start_utc", String(20)),
            Column("sport", String(40)),
            Column("data", JSON),
        ),
        "activity_streams": Table("activity_streams", m, Column("activity_id", String(64), primary_key=True), Column("data", JSON)),
        "fit_files": Table("fit_files", m, Column("activity_id", String(64), primary_key=True), Column("data", LargeBinary)),
        "wellness": Table("wellness", m, Column("day", String(10), primary_key=True), Column("data", JSON)),
        "settings": Table("settings", m, Column("key", String(64), primary_key=True), Column("value", JSON)),
        "documents": Table(
            "documents",
            m,
            Column("key", String(64), primary_key=True),
            Column("body", Text),
            Column("updated_at", DateTime(timezone=True)),
            Column("updated_by", String(40)),
        ),
        "entries": Table(
            "entries",
            m,
            Column("id", Integer, primary_key=True),
            Column("kind", String(20)),
            Column("day", String(10)),
            Column("title", String(200)),
            Column("body", Text),
            Column("author", String(40)),
            Column("created_at", DateTime(timezone=True)),
        ),
        "plans": Table(
            "plans",
            m,
            Column("id", Integer, primary_key=True),
            Column("title", String(200)),
            Column("goal", Text),
            Column("race", String(200)),
            Column("notes", Text),
            Column("status", String(20)),
            Column("author", String(40)),
            Column("created_at", DateTime(timezone=True)),
        ),
        "plan_sessions": Table(
            "plan_sessions",
            m,
            Column("id", Integer, primary_key=True),
            Column("plan_id", Integer),
            *[Column(c, String) for c in ("date", "sport", "kind", "target_zone", "description", "route_id")],
            Column("distance_km", Float),
            Column("duration_min", Integer),
        ),
        "routes": Table("routes", m, Column("id", String(20), primary_key=True), Column("sport", String(40)), Column("data", JSON)),
    }
    return m, t


def _fix_sequences(conn, tables) -> None:
    """After inserting explicit ids into Postgres serial columns, move the sequences past the highest id."""
    for t in tables:
        conn.execute(
            text(f"SELECT setval(pg_get_serial_sequence('{t.name}', 'id'), COALESCE((SELECT MAX(id) FROM {t.name}), 0) + 1, false)")
        )


def _migrate_v1(conn, owner_id: int = 1) -> dict:
    """Single-user tables -> multi-user tables, all data to `owner_id`. Runs inside the caller's transaction: on any
    error nothing changes (Postgres has transactional DDL)."""
    v1_meta, v1 = _v1_meta()
    present = set(inspect(conn).get_table_names())
    rows = {name: [dict(r) for r in conn.execute(select(t)).mappings()] for name, t in v1.items() if name in present}
    v1_meta.drop_all(conn, tables=[t for n, t in v1.items() if n in present], checkfirst=True)
    meta.create_all(conn)
    counts = {}
    for name, items in rows.items():
        if name == "settings":
            tokens = next((r["value"] for r in items if r["key"] == "agent_tokens"), None) or []
            for tok in tokens:
                conn.execute(
                    insert(agent_tokens).values(
                        id=tok["id"],
                        user_id=owner_id,
                        name=tok["name"],
                        hash=tok["hash"],
                        created_at=datetime.fromisoformat(tok["created_at"]),
                    )
                )
            items = [r for r in items if r["key"] != "agent_tokens"]
        table = meta.tables[name]
        for r in items:
            values = dict(r) if name == "plan_sessions" else {**r, "user_id": owner_id}
            conn.execute(insert(table).values(**values))
        counts[name] = len(items)
    _fix_sequences(conn, [entries, plans, sessions])
    return counts


PLAN_STATUS_V2 = {"actief": "active", "afgerond": "finished", "gestopt": "stopped"}
ONBOARDING_PAGE_V2 = {"rondjes": "routes", "historie": "history"}


def _migrate_v3(conn) -> None:
    """Dutch values stored up to schema 2 -> English: plan statuses, the onboarding pages you visited and generated
    route names ("6.0 km rondje (r1)" -> "6.0 km loop (r1)"; tools/routes.py makes them in English now)."""
    for old, new in PLAN_STATUS_V2.items():
        conn.execute(update(plans).where(plans.c.status == old).values(status=new))
    for row in conn.execute(select(settings).where(settings.c.key == "onboarding")).mappings().all():
        value = dict(row["value"] or {})
        visited = value.get("visited") or []
        if any(p in ONBOARDING_PAGE_V2 for p in visited):
            value["visited"] = list(dict.fromkeys(ONBOARDING_PAGE_V2.get(p, p) for p in visited))
            conn.execute(update(settings).where(settings.c.user_id == row["user_id"], settings.c.key == "onboarding").values(value=value))
    for row in conn.execute(select(routes)).mappings().all():
        data = dict(row["data"] or {})
        name = english_default_name(data.get("name"))
        if name != data.get("name"):
            data["name"] = name
            conn.execute(update(routes).where(routes.c.user_id == row["user_id"], routes.c.id == row["id"]).values(data=data))


def _migrate_v4(conn) -> None:
    """The sport of every stored activity again from its raw Garmin or Strava type (tools/sports.py): running,
    cycling and swimming variants that had their own code before, and Garmin's `_v2`/`_ws` suffixes."""
    for row in conn.execute(select(activities.c.user_id, activities.c.id, activities.c.sport, activities.c.data)).mappings().all():
        sport = sport_of(row["data"] or {}) or {"walk": "walking", "hike": "hiking"}.get(row["sport"])  # FIT uploads before v4
        if sport and sport != row["sport"]:
            data = {**row["data"], "sport": sport}
            conn.execute(
                update(activities)
                .where(activities.c.user_id == row["user_id"], activities.c.id == row["id"])
                .values(sport=sport, data=data)
            )


def _migrate_v5(conn) -> None:
    """Open-water swims: the timer time instead of Garmin's moving time, which is broken there (tools/store.py)."""
    for row in (
        conn.execute(select(activities.c.user_id, activities.c.id, activities.c.data).where(activities.c.sport == "swim")).mappings().all()
    ):
        data = row["data"] or {}
        garmin = (data.get("sources") or {}).get("garmin") or {}
        raw = garmin.get("raw") or {}
        if (raw.get("activityType") or {}).get("typeKey") != "open_water_swimming" or not raw.get("duration"):
            continue
        fields = {**(garmin.get("fields") or {}), "moving_time_s": round(raw["duration"])}
        sources = {**data["sources"], "garmin": {**garmin, "fields": fields}}
        data = {**data, "sources": sources, "open_water": True, "moving_time_s": round(raw["duration"])}  # garmin leads for time
        conn.execute(update(activities).where(activities.c.user_id == row["user_id"], activities.c.id == row["id"]).values(data=data))


def _migrate_v6(conn) -> None:
    """Columns on `users` for sessions that end on a password change, consent and two-step login (v6) and beta
    features (v7)."""
    have = {c["name"] for c in inspect(conn).get_columns("users")}
    for name in (*V6_USER_COLUMNS, *V7_USER_COLUMNS):
        if name in have:
            continue
        col = users.c[name]
        kind = col.type.compile(dialect=conn.dialect)
        default = " NOT NULL DEFAULT 0" if name == "session_version" else ""
        conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {kind}{default}"))


def create_schema(engine: Engine) -> dict | None:
    """Create missing tables; migrate a single-user (v1) database to multi-user, Dutch stored values to English (v3)
    and stored sports to the codes of tools/sports.py (v4).
    Returns the v1 migration counts or None."""
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        migrated = None
        if "activities" in tables and "user_id" not in {c["name"] for c in inspect(conn).get_columns("activities")}:
            migrated = _migrate_v1(conn)
        meta.create_all(conn)
        version = conn.execute(select(app_settings.c.value).where(app_settings.c.key == "schema_version")).scalar_one_or_none()
        if version is None or int(version) < 3:
            _migrate_v3(conn)
        if version is None or int(version) < 4:
            _migrate_v4(conn)
        if version is None or int(version) < 5:
            _migrate_v5(conn)
        _migrate_v6(conn)  # checks the columns itself: cheap, and safe on a database another branch already moved on
        if version != SCHEMA_VERSION:
            conn.execute(delete(app_settings).where(app_settings.c.key == "schema_version"))
            conn.execute(insert(app_settings).values(key="schema_version", value=SCHEMA_VERSION))
    return migrated


# --- users ------------------------------------------------------------------------------------------------------


def _user_row(row) -> dict:
    out = dict(row)
    for k in SECRET_USER_FIELDS:
        out.pop(k, None)
    out["totp_enabled"] = bool(out.pop("totp_enabled_at", None))
    for k in ("created_at", "last_login_at", "consent_at"):
        if out.get(k):
            out[k] = out[k].isoformat()
    out["session_version"] = out.get("session_version") or 0
    out["betas"] = list(out.get("betas") or [])
    return out


def create_user(
    engine: Engine,
    username: str,
    password_hash: str,
    is_admin: bool = False,
    display_name: str | None = None,
    user_id: int | None = None,
    consent_at: datetime | None = None,
    privacy_version: str | None = None,
) -> int:
    values = dict(
        username=username.lower(),
        password_hash=password_hash,
        is_admin=is_admin,
        suspended=False,
        display_name=display_name,
        created_at=_now(),
        session_version=0,
        consent_at=consent_at,
        privacy_version=privacy_version,
    )
    if user_id is not None:
        values["id"] = user_id
    with engine.begin() as conn:
        uid = conn.execute(insert(users).values(**values)).inserted_primary_key[0]
        if user_id is not None:
            _fix_sequences(conn, [users])
    return uid


def get_user(engine: Engine, user_id: int, with_hash: bool = False) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return (dict(row) if with_hash else _user_row(row)) if row else None


def get_user_by_name(engine: Engine, username: str, with_hash: bool = False) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(select(users).where(users.c.username == username.strip().lower())).mappings().first()
    return (dict(row) if with_hash else _user_row(row)) if row else None


def files_bytes(engine: Engine) -> dict[int, int]:
    """{user id: bytes of the activity files (FIT) stored for them}, the bulk of what a user takes up; users without
    files are left out."""
    with engine.connect() as conn:
        rows = conn.execute(select(fit_files.c.user_id, func.sum(func.length(fit_files.c.data))).group_by(fit_files.c.user_id)).all()
    return {uid: int(n or 0) for uid, n in rows}


def list_users(engine: Engine) -> list[dict]:
    files = files_bytes(engine)
    with engine.connect() as conn:
        rows = conn.execute(select(users).order_by(users.c.id)).mappings().all()
        counts = dict(conn.execute(select(activities.c.user_id, func.count()).group_by(activities.c.user_id)).all())
        syncs = {
            uid: v for uid, v in conn.execute(select(settings.c.user_id, settings.c.value).where(settings.c.key == "sync_state")).all()
        }
    return [
        {
            **_user_row(r),
            "activities": counts.get(r["id"], 0),
            "files_bytes": files.get(r["id"], 0),
            "last_sync": (syncs.get(r["id"]) or {}).get("last_sync_local"),
        }
        for r in rows
    ]


def user_betas(engine: Engine, user_id: int) -> list[str]:
    """The beta features switched on for a user, as stored (api/betas.py keeps only the ones that still exist)."""
    with engine.connect() as conn:
        value = conn.execute(select(users.c.betas).where(users.c.id == user_id)).scalar_one_or_none()
    return list(value or [])


def all_user_betas(engine: Engine) -> dict[int, list[str]]:
    """{user id: betas as stored} for every user."""
    with engine.connect() as conn:
        return {uid: list(value or []) for uid, value in conn.execute(select(users.c.id, users.c.betas))}


def set_user_beta(engine: Engine, user_id: int, feature: str, enabled: bool) -> list[str]:
    """Switch one beta feature on or off for a user; returns the user's betas after it."""
    with engine.begin() as conn:
        value = conn.execute(select(users.c.betas).where(users.c.id == user_id)).scalar_one_or_none()
        betas = [b for b in (value or []) if b != feature] + ([feature] if enabled else [])
        conn.execute(update(users).where(users.c.id == user_id).values(betas=sorted(betas)))
    return sorted(betas)


def activity_totals(engine: Engine) -> dict[int, tuple[int, str | None]]:
    """{user id: (number of activities, start_utc of the newest)}, over every user (the admin hub)."""
    with engine.connect() as conn:
        rows = conn.execute(
            select(activities.c.user_id, func.count(), func.max(activities.c.start_utc)).group_by(activities.c.user_id)
        ).all()
    return {uid: (n, last) for uid, n, last in rows}


def activities_per_day(engine: Engine, since: date) -> dict[str, int]:
    """{YYYY-MM-DD: activities that started that local day} from `since` on, over every user (the admin hub)."""
    day = func.substr(activities.c.start_local, 1, 10)
    with engine.connect() as conn:
        rows = conn.execute(select(day, func.count()).where(activities.c.start_local >= since.isoformat()).group_by(day)).all()
    return {d: n for d, n in rows}


def add_audit(engine: Engine, actor: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(admin_audit).values(actor=actor, action=action, target=target, detail=(detail or None) and detail[:200], at=_now())
        )


def list_audit(engine: Engine, limit: int = 30) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(admin_audit).order_by(admin_audit.c.id.desc()).limit(limit)).mappings().all()
    return [{**dict(r), "at": r["at"].isoformat()} for r in rows]


def count_users(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(users)).scalar_one()


def update_user(engine: Engine, user_id: int, **fields) -> None:
    allowed = {"username", "display_name", "password_hash", "is_admin", "suspended", "last_login_at", *V6_USER_COLUMNS}
    values = {k: v for k, v in fields.items() if k in allowed}
    if "username" in values:
        values["username"] = values["username"].lower()
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(**values))


def delete_user(engine: Engine, user_id: int) -> None:
    """The user and all their data."""
    with engine.begin() as conn:
        plan_ids = [p for (p,) in conn.execute(select(plans.c.id).where(plans.c.user_id == user_id))]
        if plan_ids:
            conn.execute(delete(sessions).where(sessions.c.plan_id.in_(plan_ids)))
        for t in USER_TABLES:
            conn.execute(delete(t).where(t.c.user_id == user_id))
        conn.execute(delete(agent_tokens).where(agent_tokens.c.user_id == user_id))
        conn.execute(delete(users).where(users.c.id == user_id))


def bump_session_version(engine: Engine, user_id: int) -> int:
    """Every session of the user ends (a password change, two-step login switched on or off); returns the new version."""
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(session_version=func.coalesce(users.c.session_version, 0) + 1))
        return conn.execute(select(users.c.session_version).where(users.c.id == user_id)).scalar_one()


def session_version(engine: Engine, user_id: int) -> int | None:
    """None when the user does not exist."""
    with engine.connect() as conn:
        row = conn.execute(select(users.c.session_version).where(users.c.id == user_id)).first()
    return None if row is None else (row[0] or 0)


# Settings that hold credentials (encrypted sessions at Garmin and Wahoo): never part of an export.
SECRET_SETTINGS = ("garmin_tokens", "wahoo_tokens")


def _jsonable(value):
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None  # binary columns (FIT files, screenshots) are exported as files of their own
    return value


def export_tables(s: Scope):
    """(name, rows) per table of the user's data, rows as JSON-ready dicts, read one table at a time (GDPR art. 20).
    Without credentials and hashes: the encrypted Garmin/Wahoo sessions, token hashes, FIT and screenshot bytes."""
    uid = s.user_id
    with s.engine.connect() as conn:
        user = conn.execute(select(users).where(users.c.id == uid)).mappings().first()
        yield "account", [{k: _jsonable(v) for k, v in _user_row(user).items()}] if user else []
        for t in (
            activities,
            streams,
            wellness,
            intraday,
            documents,
            entries,
            plans,
            plan_links,
            achievements,
            routes,
            gear,
            activity_gear,
            meals,
            meal_items,
            user_foods,
            portion_memory,
            meal_templates,
            nutrition_ai_runs,
        ):
            yield (
                t.name,
                (
                    {k: _jsonable(v) for k, v in r.items() if k != "user_id"}
                    for r in conn.execute(select(t).where(t.c.user_id == uid)).mappings()
                ),
            )
        yield (
            "settings",
            (
                {"key": r["key"], "value": r["value"]}
                for r in conn.execute(select(settings).where(settings.c.user_id == uid)).mappings()
                if r["key"] not in SECRET_SETTINGS
            ),
        )
        plan_ids = select(plans.c.id).where(plans.c.user_id == uid).scalar_subquery()
        yield (
            "plan_sessions",
            (
                {k: _jsonable(v) for k, v in r.items()}
                for r in conn.execute(select(sessions).where(sessions.c.plan_id.in_(plan_ids))).mappings()
            ),
        )
        cols = [c for c in feedback.c if c.name not in ("screenshot", "user_id")]
        yield (
            "feedback",
            ({k: _jsonable(v) for k, v in r.items()} for r in conn.execute(select(*cols).where(feedback.c.user_id == uid)).mappings()),
        )
        yield (
            "agent_tokens",
            (
                {k: _jsonable(v) for k, v in r.items()}
                for r in conn.execute(
                    select(agent_tokens.c.id, agent_tokens.c.name, agent_tokens.c.created_at).where(agent_tokens.c.user_id == uid)
                ).mappings()
            ),
        )


def export_files(s: Scope):
    """(path in the export, bytes): the stored FIT files and feedback screenshots, one at a time."""
    with s.engine.connect() as conn:
        keys = [
            k
            for (k,) in conn.execute(
                select(fit_files.c.activity_id).where(fit_files.c.user_id == s.user_id).order_by(fit_files.c.activity_id)
            )
        ]
        shots = conn.execute(
            select(feedback.c.id, feedback.c.screenshot_type).where(feedback.c.user_id == s.user_id, feedback.c.screenshot.isnot(None))
        ).all()
    for key in keys:
        data = get_fit(s, key)
        if data is not None:
            yield f"fit/{key.replace('/', '__')}.fit", data
    for fid, media in shots:
        with s.engine.connect() as conn:
            data = conn.execute(
                select(feedback.c.screenshot).where(feedback.c.id == fid, feedback.c.user_id == s.user_id)
            ).scalar_one_or_none()
        if data:
            yield f"feedback/{fid}.{(media or 'image/png').split('/')[-1]}", data
    with s.engine.connect() as conn:
        photos = conn.execute(
            select(meal_photos.c.id, meal_photos.c.mime).where(meal_photos.c.user_id == s.user_id).order_by(meal_photos.c.id)
        ).all()
    for pid, media in photos:
        with s.engine.connect() as conn:
            data = conn.execute(
                select(meal_photos.c.data).where(meal_photos.c.id == pid, meal_photos.c.user_id == s.user_id)
            ).scalar_one_or_none()
        if data:
            yield f"meals/{pid}.{(media or 'image/jpeg').split('/')[-1]}", data


def count_admins(engine: Engine, except_user: int | None = None) -> int:
    """Admins who can still log in (not suspended), optionally leaving one user out."""
    q = select(func.count()).select_from(users).where(users.c.is_admin.is_(True), users.c.suspended.is_(False))
    if except_user is not None:
        q = q.where(users.c.id != except_user)
    with engine.connect() as conn:
        return conn.execute(q).scalar_one()


def user_ids_with_setting(engine: Engine, key: str) -> list[int]:
    with engine.connect() as conn:
        return [uid for (uid,) in conn.execute(select(settings.c.user_id).where(settings.c.key == key).order_by(settings.c.user_id))]


# --- app settings and invites ---------------------------------------------------------------------------------------


def get_app_setting(engine: Engine, key: str, default=None):
    with engine.connect() as conn:
        value = conn.execute(select(app_settings.c.value).where(app_settings.c.key == key)).scalar_one_or_none()
    return default if value is None else value


def set_app_setting(engine: Engine, key: str, value) -> None:
    with engine.begin() as conn:
        conn.execute(delete(app_settings).where(app_settings.c.key == key))
        conn.execute(insert(app_settings).values(key=key, value=value))


def create_invite(engine: Engine, code: str, created_by: int, expires_at: datetime | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(insert(invites).values(code=code, created_by=created_by, created_at=_now(), expires_at=expires_at))


def list_invites(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(select(invites).order_by(invites.c.created_at.desc())).mappings().all()
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()} for r in rows]


def use_invite(engine: Engine, code: str, user_id: int) -> bool:
    """Marks a valid, unused, unexpired invite as used by `user_id`. False when it cannot be used."""
    with engine.begin() as conn:
        row = conn.execute(select(invites).where(invites.c.code == code)).mappings().first()
        if not row or row["used_by"] is not None:
            return False
        if row["expires_at"] is not None and row["expires_at"] < _now():
            return False
        conn.execute(update(invites).where(invites.c.code == code).values(used_by=user_id, used_at=_now()))
    return True


def invite_usable(engine: Engine, code: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(select(invites).where(invites.c.code == code)).mappings().first()
    if not row or row["used_by"] is not None:
        return False
    return row["expires_at"] is None or row["expires_at"] >= _now()


def delete_invite(engine: Engine, code: str) -> None:
    with engine.begin() as conn:
        conn.execute(delete(invites).where(invites.c.code == code))


# --- feedback ----------------------------------------------------------------------------------------------------

FEEDBACK_KINDS = ("bug", "idea")
FEEDBACK_STATUSES = ("new", "planned", "fixed", "wontfix")


def add_feedback(
    engine: Engine,
    user_id: int,
    kind: str,
    message: str,
    page: str | None,
    context: dict | None,
    screenshot: bytes | None = None,
    screenshot_type: str | None = None,
) -> int:
    with engine.begin() as conn:
        return conn.execute(
            insert(feedback).values(
                user_id=user_id,
                kind=kind,
                message=message,
                page=page,
                context=context,
                screenshot=screenshot,
                screenshot_type=screenshot_type,
                status="new",
                created_at=_now(),
            )
        ).inserted_primary_key[0]


def _feedback_out(row) -> dict:
    out = {k: row[k] for k in ("id", "user_id", "kind", "message", "page", "context", "status", "reply")}
    out["has_screenshot"] = bool(row["has_screenshot"])
    out["created_at"] = row["created_at"].isoformat() if row["created_at"] else None
    out["updated_at"] = row["updated_at"].isoformat() if row["updated_at"] else None
    if "username" in row:
        out["username"] = row["username"]
    return out


def list_feedback(engine: Engine, user_id: int | None = None, status: str | None = None, limit: int = 200) -> list[dict]:
    """Newest first, without the screenshot bytes. `user_id` None: everyone's, with the username (admins)."""
    cols = [c for c in feedback.c if c.name != "screenshot"] + [feedback.c.screenshot.isnot(None).label("has_screenshot"), users.c.username]
    q = select(*cols).join(users, users.c.id == feedback.c.user_id, isouter=True)
    if user_id is not None:
        q = q.where(feedback.c.user_id == user_id)
    if status:
        q = q.where(feedback.c.status == status)
    with engine.connect() as conn:
        return [_feedback_out(r) for r in conn.execute(q.order_by(feedback.c.id.desc()).limit(limit)).mappings()]


def get_feedback(engine: Engine, feedback_id: int) -> dict | None:
    cols = [c for c in feedback.c if c.name != "screenshot"] + [feedback.c.screenshot.isnot(None).label("has_screenshot"), users.c.username]
    with engine.connect() as conn:
        row = (
            conn.execute(select(*cols).join(users, users.c.id == feedback.c.user_id, isouter=True).where(feedback.c.id == feedback_id))
            .mappings()
            .first()
        )
    return _feedback_out(row) if row else None


def feedback_screenshot(engine: Engine, feedback_id: int) -> tuple[int, bytes, str] | None:
    """(owner user id, bytes, media type), or None."""
    with engine.connect() as conn:
        row = conn.execute(
            select(feedback.c.user_id, feedback.c.screenshot, feedback.c.screenshot_type).where(feedback.c.id == feedback_id)
        ).first()
    return (row[0], row[1], row[2] or "image/png") if row and row[1] else None


def update_feedback(engine: Engine, feedback_id: int, **fields) -> bool:
    """Set status and/or reply (None leaves a field as it is, "" clears the reply)."""
    values = {k: v for k, v in fields.items() if k in ("status", "reply") and v is not None}
    if "reply" in values:
        values["reply"] = values["reply"].strip() or None
    with engine.begin() as conn:
        return conn.execute(update(feedback).where(feedback.c.id == feedback_id).values(**values, updated_at=_now())).rowcount > 0


# --- agent tokens ------------------------------------------------------------------------------------------------


def add_agent_token(s: Scope, token_id: str, name: str, token_hash: str) -> None:
    with s.engine.begin() as conn:
        conn.execute(insert(agent_tokens).values(id=token_id, user_id=s.user_id, name=name, hash=token_hash, created_at=_now()))


def list_agent_tokens(s: Scope) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(
            select(agent_tokens.c.id, agent_tokens.c.name, agent_tokens.c.created_at)
            .where(agent_tokens.c.user_id == s.user_id)
            .order_by(agent_tokens.c.created_at)
        ).mappings()
        return [{**r, "created_at": r["created_at"].isoformat()} for r in rows]


def delete_agent_token(s: Scope, token_id: str) -> bool:
    with s.engine.begin() as conn:
        return conn.execute(delete(agent_tokens).where(agent_tokens.c.id == token_id, agent_tokens.c.user_id == s.user_id)).rowcount > 0


def user_for_token_hash(engine: Engine, token_hash: str) -> int | None:
    with engine.connect() as conn:
        return conn.execute(select(agent_tokens.c.user_id).where(agent_tokens.c.hash == token_hash)).scalar_one_or_none()


# --- activities ----------------------------------------------------------------------------------------------------


def _find_match(conn, s: Scope, record: dict) -> dict | None:
    day = date.fromisoformat(record["start_local"][:10])
    lo, hi = (day - timedelta(days=1)).isoformat(), (day + timedelta(days=2)).isoformat()
    rows = conn.execute(
        select(activities).where(activities.c.user_id == s.user_id, activities.c.start_local >= lo, activities.c.start_local < hi)
    ).mappings()
    for row in rows:
        if same_start(row, record):
            return dict(row)
    return None


def upsert_activity(s: Scope, record: dict) -> str:
    """Insert or merge an activity from one source; streams go to their own table. Returns the activity id."""
    record = prepare(record)
    new_streams = record.pop("streams", None)
    uid = s.user_id
    with s.engine.begin() as conn:
        (src,) = record["sources"]
        match = _find_match(conn, s, record)
        if new_streams:
            owner = ((match or {}).get("data") or {}).get("owners", {}).get("streams")
            if match and not owner:
                # stored before owners were kept: streams already there came from the best of its other sources
                has = conn.execute(
                    select(streams.c.activity_id).where(streams.c.user_id == uid, streams.c.activity_id == match["id"])
                ).first()
                others = [k for k in (match["data"] or {}).get("sources", {}) if k != src]
                owner = min(others, key=_rank) if has and others else None
            if match and owner and owner != src and _rank(owner) < _rank(src):
                new_streams = None  # a higher-priority source already gave the streams
        if match is None:
            aid = activity_id(record)
            merged = merge({}, record)
            if new_streams:
                merged["owners"]["streams"] = src
            conn.execute(
                insert(activities).values(
                    user_id=uid,
                    id=aid,
                    start_local=merged["start_local"],
                    start_utc=merged["start_utc"],
                    sport=merged["sport"],
                    data=merged,
                )
            )
        else:
            aid = match["id"]
            merged = merge(match["data"], record)
            if new_streams:
                merged["owners"]["streams"] = src
            conn.execute(
                update(activities).where(activities.c.user_id == uid, activities.c.id == aid).values(data=merged, sport=merged["sport"])
            )
        if new_streams:
            conn.execute(delete(streams).where(streams.c.user_id == uid, streams.c.activity_id == aid))
            conn.execute(insert(streams).values(user_id=uid, activity_id=aid, data=new_streams))
    return aid


def delete_activity_by_source(s: Scope, source: str, source_id, day: str) -> None:
    """Remove the activity (with its streams) that `source` sent as `source_id`, started around `day`."""
    d = date.fromisoformat(day)
    lo, hi = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=2)).isoformat()
    with s.engine.begin() as conn:
        rows = conn.execute(
            select(activities.c.id, activities.c.data).where(
                activities.c.user_id == s.user_id, activities.c.start_local >= lo, activities.c.start_local < hi
            )
        ).all()
        for aid, data in rows:
            if str(((data or {}).get("sources") or {}).get(source, {}).get("id")) == str(source_id):
                conn.execute(delete(streams).where(streams.c.user_id == s.user_id, streams.c.activity_id == aid))
                conn.execute(delete(activities).where(activities.c.user_id == s.user_id, activities.c.id == aid))


def set_manual_distance(s: Scope, aid: str, km: float | None) -> dict | None:
    """The distance the user entered (source `manual`, first for distance_km); None removes the correction.
    Returns the activity, or None when it is not this user's."""
    where = (activities.c.user_id == s.user_id, activities.c.id == aid)
    with s.engine.begin() as conn:
        data = conn.execute(select(activities.c.data).where(*where)).scalar_one_or_none()
        if data is None:
            return None
        sources = dict(data.get("sources") or {})
        if km is None:
            sources.pop("manual", None)
            km = source_distance(sources)
        else:
            sources["manual"] = {"fields": {"distance_km": round(km, 2)}}
        data = {**data, "sources": sources, "distance_km": round(km, 2) if km is not None else None}
        conn.execute(update(activities).where(*where).values(data=data))
    return dict(data, id=aid)


def remove_source(s: Scope, source: str) -> dict:
    """Everything `source` gave, gone: activities only it had, and its part of merged ones.

    For ending a connection (a user who revokes Wahoo access, say). Fields, laps and streams another source gave
    stay; FIT files stored under `<source>/` go. Zones and routes are the caller's to recompute (tools.derive).
    """
    uid = s.user_id
    removed = changed = 0
    with s.engine.begin() as conn:
        rows = conn.execute(select(activities.c.id, activities.c.data).where(activities.c.user_id == uid)).all()
        for aid, data in rows:
            if source not in (data or {}).get("sources", {}):
                continue
            where_streams = (streams.c.user_id == uid, streams.c.activity_id == aid)
            kept = _strip_source(data, source)
            if kept is None:
                conn.execute(delete(streams).where(*where_streams))
                conn.execute(delete(fit_files).where(fit_files.c.user_id == uid, fit_files.c.activity_id.in_([aid, f"upload/{aid}"])))
                conn.execute(delete(activities).where(activities.c.user_id == uid, activities.c.id == aid))
                removed += 1
                continue
            if (data.get("owners") or {}).get("streams") == source:
                conn.execute(delete(streams).where(*where_streams))
            if kept.get("fit_file", "").startswith(f"{source}/"):
                kept.pop("fit_file")
            conn.execute(update(activities).where(activities.c.user_id == uid, activities.c.id == aid).values(data=kept))
            changed += 1
        conn.execute(delete(fit_files).where(fit_files.c.user_id == uid, fit_files.c.activity_id.like(f"{source}/%")))
    return {"removed": removed, "changed": changed}


def get_activity(s: Scope, aid: str) -> dict | None:
    with s.engine.connect() as conn:
        data = conn.execute(select(activities.c.data).where(activities.c.user_id == s.user_id, activities.c.id == aid)).scalar_one_or_none()
    return dict(data, id=aid) if data is not None else None


def set_derived(s: Scope, aid: str, **fields) -> None:
    """Update derived fields (e.g. hr_zones_s) on an activity; None removes the field."""
    where = (activities.c.user_id == s.user_id, activities.c.id == aid)
    with s.engine.begin() as conn:
        data = dict(conn.execute(select(activities.c.data).where(*where)).scalar_one())
        for k, v in fields.items():
            if v is None:
                data.pop(k, None)
            else:
                data[k] = v
        conn.execute(update(activities).where(*where).values(data=data))


def load_activities(s: Scope, with_streams: bool = False) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(
            select(activities.c.id, activities.c.data).where(activities.c.user_id == s.user_id).order_by(activities.c.start_local)
        ).all()
        out = [dict(data, id=aid) for aid, data in rows]
        if with_streams:
            by_id = dict(conn.execute(select(streams.c.activity_id, streams.c.data).where(streams.c.user_id == s.user_id)).all())
            for a in out:
                if a["id"] in by_id:
                    a["streams"] = by_id[a["id"]]
    return out


def load_streams(s: Scope, aid: str) -> dict | None:
    with s.engine.connect() as conn:
        return conn.execute(select(streams.c.data).where(streams.c.user_id == s.user_id, streams.c.activity_id == aid)).scalar_one_or_none()


def put_fit(s: Scope, aid: str, data: bytes) -> None:
    with s.engine.begin() as conn:
        conn.execute(delete(fit_files).where(fit_files.c.user_id == s.user_id, fit_files.c.activity_id == aid))
        conn.execute(insert(fit_files).values(user_id=s.user_id, activity_id=aid, data=data))


def get_fit(s: Scope, key: str) -> bytes | None:
    with s.engine.connect() as conn:
        return conn.execute(
            select(fit_files.c.data).where(fit_files.c.user_id == s.user_id, fit_files.c.activity_id == key)
        ).scalar_one_or_none()


def has_fit(s: Scope, aid: str) -> bool:
    with s.engine.connect() as conn:
        return (
            conn.execute(select(fit_files.c.activity_id).where(fit_files.c.user_id == s.user_id, fit_files.c.activity_id == aid)).first()
            is not None
        )


# --- wellness, settings, documents ---------------------------------------------------------------------------------


def write_wellness(s: Scope, day: str, values: dict) -> None:
    """Replace the day; an empty result removes it (Garmin is the only source)."""
    with s.engine.begin() as conn:
        conn.execute(delete(wellness).where(wellness.c.user_id == s.user_id, wellness.c.day == day))
        if values:
            conn.execute(insert(wellness).values(user_id=s.user_id, day=day, data=values))


def load_wellness(s: Scope) -> dict[str, dict]:
    with s.engine.connect() as conn:
        return {
            d: data
            for d, data in conn.execute(
                select(wellness.c.day, wellness.c.data).where(wellness.c.user_id == s.user_id).order_by(wellness.c.day)
            )
        }


def write_intraday(s: Scope, day: str, values: dict) -> None:
    """Replace the day; an empty result removes it (Garmin is the only source)."""
    with s.engine.begin() as conn:
        conn.execute(delete(intraday).where(intraday.c.user_id == s.user_id, intraday.c.day == day))
        if values:
            conn.execute(insert(intraday).values(user_id=s.user_id, day=day, data=values))


def get_intraday(s: Scope, day: str) -> dict | None:
    with s.engine.connect() as conn:
        return conn.execute(select(intraday.c.data).where(intraday.c.user_id == s.user_id, intraday.c.day == day)).scalar_one_or_none()


def intraday_days(s: Scope) -> list[str]:
    """The days with intraday data, oldest first."""
    with s.engine.connect() as conn:
        return [d for (d,) in conn.execute(select(intraday.c.day).where(intraday.c.user_id == s.user_id).order_by(intraday.c.day))]


# --- gear -------------------------------------------------------------------------------------------------------

GEAR_KINDS = ("shoes", "bike", "other")
GEAR_FIELDS = ("kind", "name", "brand", "model", "start_km", "max_km", "since", "retired_on", "notes")
GEAR_DEFAULTS_KEY = "gear_defaults"  # setting: {sport: gear id}, the gear a new activity of that sport gets
GEAR_NONE_KEY = "gear_none"  # setting: activity ids the user cleared by hand (no gear, not even a default)


def list_gear(s: Scope) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(select(gear).where(gear.c.user_id == s.user_id).order_by(gear.c.id)).mappings().all()
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items() if k != "user_id"} for r in rows]


def get_gear(s: Scope, gid: int) -> dict | None:
    return next((g for g in list_gear(s) if g["id"] == gid), None)


def create_gear(s: Scope, **fields) -> dict:
    values = {k: fields[k] for k in (*GEAR_FIELDS, "garmin_uuid", "garmin") if k in fields}
    values.setdefault("start_km", 0)
    with s.engine.begin() as conn:
        gid = conn.execute(insert(gear).values(user_id=s.user_id, created_at=_now(), **values)).inserted_primary_key[0]
    return get_gear(s, gid)


def update_gear(s: Scope, gid: int, **fields) -> dict | None:
    values = {k: v for k, v in fields.items() if k in (*GEAR_FIELDS, "garmin")}
    with s.engine.begin() as conn:
        n = conn.execute(update(gear).where(gear.c.user_id == s.user_id, gear.c.id == gid).values(**values)).rowcount if values else 1
    return get_gear(s, gid) if n else None


def delete_gear(s: Scope, gid: int) -> bool:
    with s.engine.begin() as conn:
        conn.execute(delete(activity_gear).where(activity_gear.c.user_id == s.user_id, activity_gear.c.gear_id == gid))
        n = conn.execute(delete(gear).where(gear.c.user_id == s.user_id, gear.c.id == gid)).rowcount
    defaults = {k: v for k, v in (get_setting(s, GEAR_DEFAULTS_KEY) or {}).items() if v != gid}
    set_setting(s, GEAR_DEFAULTS_KEY, defaults)
    return bool(n)


def gear_links(s: Scope) -> list[dict]:
    """Which gear each activity used, as it counts: the user's choice (manual, also "none") wins over Garmin's, and
    Garmin's over the sport's default. Every source keeps its rows, so going back to automatic needs no new sync."""
    with s.engine.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                select(activity_gear.c.activity_id, activity_gear.c.gear_id, activity_gear.c.source).where(
                    activity_gear.c.user_id == s.user_id
                )
            ).mappings()
        ]
    cleared = set(get_setting(s, GEAR_NONE_KEY) or [])
    rank = {"manual": 0, "garmin": 1, "default": 2}
    best: dict[str, int] = {}
    for r in rows:
        best[r["activity_id"]] = min(best.get(r["activity_id"], 9), rank.get(r["source"], 9))
    return [r for r in rows if r["activity_id"] not in cleared and rank.get(r["source"], 9) == best[r["activity_id"]]]


def set_activity_gear(s: Scope, aid: str, gear_ids: list[int] | None) -> None:
    """The gear the user chose for an activity: a list replaces what Garmin or the default gave, [] means none, None
    hands the activity back to them."""
    uid = s.user_id
    with s.engine.begin() as conn:
        mine = {g for (g,) in conn.execute(select(gear.c.id).where(gear.c.user_id == uid))}
        conn.execute(
            delete(activity_gear).where(
                activity_gear.c.user_id == uid, activity_gear.c.activity_id == aid, activity_gear.c.source == "manual"
            )
        )
        for gid in dict.fromkeys(gear_ids or []):
            if gid in mine:
                conn.execute(insert(activity_gear).values(user_id=uid, activity_id=aid, gear_id=gid, source="manual"))
    cleared = [a for a in (get_setting(s, GEAR_NONE_KEY) or []) if a != aid]
    if gear_ids == []:
        cleared.append(aid)
    set_setting(s, GEAR_NONE_KEY, cleared)


def _garmin_ids(conn, uid: int) -> dict[str, str]:
    """Garmin's activity id -> the id here, for the activities Garmin gave."""
    out = {}
    for aid, data in conn.execute(select(activities.c.id, activities.c.data).where(activities.c.user_id == uid)).all():
        gid = (((data or {}).get("sources") or {}).get("garmin") or {}).get("id")
        if gid is not None:
            out[str(gid)] = aid
    return out


def save_garmin_gear(s: Scope, items: list[dict]) -> dict:
    """Garmin's gear (tools/sync.py GarminClient.gear) into the user's gear: new items added, Garmin's facts refreshed
    (name, retired, distance, limit) without overwriting what the user changed here, and the activities Garmin links to
    each item linked here too (source garmin; the user's own choice on an activity still wins, see gear_links)."""
    uid = s.user_id
    added = linked = 0
    with s.engine.begin() as conn:
        mine = {
            r["garmin_uuid"]: dict(r)
            for r in conn.execute(select(gear).where(gear.c.user_id == uid, gear.c.garmin_uuid.isnot(None))).mappings()
        }
        by_garmin = _garmin_ids(conn, uid)
        for item in items:
            facts = {k: item.get(k) for k in ("name", "kind", "total_km", "activities", "max_km", "status", "date_begin", "date_end")}
            row = mine.get(item["uuid"])
            if row is None:
                gid = conn.execute(
                    insert(gear).values(
                        user_id=uid,
                        kind=item.get("kind") or "other",
                        name=(item.get("name") or "Garmin")[:100],
                        brand=item.get("brand"),
                        model=item.get("model"),
                        start_km=0,
                        since=item.get("date_begin"),
                        garmin_uuid=item["uuid"],
                        garmin=facts,
                        retired_on=(item.get("date_end") or date.today().isoformat()) if item.get("status") == "retired" else None,
                        created_at=_now(),
                    )
                ).inserted_primary_key[0]
                added += 1
            else:
                gid = row["id"]
                values = {"garmin": facts}
                old = row.get("garmin") or {}
                if item.get("status") == "retired" and not row.get("retired_on"):
                    values["retired_on"] = item.get("date_end") or date.today().isoformat()
                elif item.get("status") != "retired" and old.get("status") == "retired" and row.get("retired_on"):
                    values["retired_on"] = None  # brought back into use in Garmin
                if row["name"] == (old.get("name") or row["name"]) and item.get("name"):
                    values["name"] = item["name"][:100]  # not renamed here: follow Garmin's name
                conn.execute(update(gear).where(gear.c.id == gid).values(**values))
            if item.get("activity_ids") is None:
                continue  # Garmin did not say this time: keep the links as they are
            conn.execute(
                delete(activity_gear).where(
                    activity_gear.c.user_id == uid, activity_gear.c.gear_id == gid, activity_gear.c.source == "garmin"
                )
            )
            for gaid in dict.fromkeys(str(x) for x in item["activity_ids"]):
                aid = by_garmin.get(gaid)
                if aid:
                    conn.execute(insert(activity_gear).values(user_id=uid, activity_id=aid, gear_id=gid, source="garmin"))
                    linked += 1
    return {"added": added, "linked": linked}


def apply_gear_defaults(s: Scope) -> int:
    """Default gear per sport for every activity that got gear from nowhere else: from the gear's `since` day, and
    not after it was retired. Recomputed in full, so changing a default or a date reaches earlier activities too."""
    uid = s.user_id
    defaults = {sport: gid for sport, gid in (get_setting(s, GEAR_DEFAULTS_KEY) or {}).items() if gid}
    cleared = set(get_setting(s, GEAR_NONE_KEY) or [])
    with s.engine.begin() as conn:
        conn.execute(delete(activity_gear).where(activity_gear.c.user_id == uid, activity_gear.c.source == "default"))
        if not defaults:
            return 0
        items = {
            r["id"]: r for r in conn.execute(select(gear.c.id, gear.c.since, gear.c.retired_on).where(gear.c.user_id == uid)).mappings()
        }
        has = {
            a
            for (a,) in conn.execute(
                select(activity_gear.c.activity_id).where(activity_gear.c.user_id == uid, activity_gear.c.source != "default")
            )
        }
        n = 0
        for aid, sport, start in conn.execute(
            select(activities.c.id, activities.c.sport, activities.c.start_local).where(activities.c.user_id == uid)
        ).all():
            g = items.get(defaults.get(sport))
            if not g or aid in has or aid in cleared:
                continue
            day = start[:10]
            if (g["since"] and day < g["since"]) or (g["retired_on"] and day > g["retired_on"]):
                continue
            conn.execute(insert(activity_gear).values(user_id=uid, activity_id=aid, gear_id=g["id"], source="default"))
            n += 1
    return n


def get_setting(s: Scope, key: str):
    with s.engine.connect() as conn:
        return conn.execute(select(settings.c.value).where(settings.c.user_id == s.user_id, settings.c.key == key)).scalar_one_or_none()


def set_setting(s: Scope, key: str, value) -> None:
    with s.engine.begin() as conn:
        conn.execute(delete(settings).where(settings.c.user_id == s.user_id, settings.c.key == key))
        conn.execute(insert(settings).values(user_id=s.user_id, key=key, value=value))


def delete_setting(s: Scope, key: str) -> None:
    with s.engine.begin() as conn:
        conn.execute(delete(settings).where(settings.c.user_id == s.user_id, settings.c.key == key))


def put_document(s: Scope, key: str, body: str, author: str) -> None:
    with s.engine.begin() as conn:
        conn.execute(delete(documents).where(documents.c.user_id == s.user_id, documents.c.key == key))
        conn.execute(insert(documents).values(user_id=s.user_id, key=key, body=body, updated_at=_now(), updated_by=author))


def get_document(s: Scope, key: str) -> dict | None:
    with s.engine.connect() as conn:
        row = conn.execute(select(documents).where(documents.c.user_id == s.user_id, documents.c.key == key)).mappings().first()
    if not row:
        return None
    out = {k: v for k, v in row.items() if k != "user_id"}
    return {**out, "updated_at": row["updated_at"].isoformat()}


# --- log and analyses ------------------------------------------------------------------------------------------------


def add_entry(s: Scope, kind: str, title: str, body: str, author: str, day: str | None = None) -> int:
    with s.engine.begin() as conn:
        res = conn.execute(
            insert(entries).values(
                user_id=s.user_id, kind=kind, day=day or date.today().isoformat(), title=title, body=body, author=author, created_at=_now()
            )
        )
        return res.inserted_primary_key[0]


def list_entries(s: Scope, kind: str | None = None, limit: int = 100) -> list[dict]:
    q = select(entries).where(entries.c.user_id == s.user_id).order_by(entries.c.day.desc(), entries.c.id.desc()).limit(limit)
    if kind:
        q = q.where(entries.c.kind == kind)
    with s.engine.connect() as conn:
        return [
            {**{k: v for k, v in r.items() if k != "user_id"}, "created_at": r["created_at"].isoformat()}
            for r in conn.execute(q).mappings()
        ]


# --- plans -----------------------------------------------------------------------------------------------------------


def create_plan(
    s: Scope,
    title: str,
    author: str,
    goal: str | None = None,
    race: str | None = None,
    notes: str | None = None,
    status: str = "active",
) -> int:
    """A new plan. An active one replaces the user's previous active plan (marked finished); a draft leaves it alone."""
    if status not in ("active", "draft"):
        raise ValueError(f"status {status}")
    with s.engine.begin() as conn:
        if status == "active":
            conn.execute(update(plans).where(plans.c.user_id == s.user_id, plans.c.status == "active").values(status="finished"))
        res = conn.execute(
            insert(plans).values(
                user_id=s.user_id, title=title, goal=goal, race=race, notes=notes, status=status, author=author, created_at=_now()
            )
        )
        return res.inserted_primary_key[0]


def _owns_plan(conn, s: Scope, plan_id: int) -> bool:
    return conn.execute(select(plans.c.id).where(plans.c.id == plan_id, plans.c.user_id == s.user_id)).first() is not None


def add_sessions(s: Scope, plan_id: int, items: list[dict]) -> None:
    with s.engine.begin() as conn:
        if not _owns_plan(conn, s, plan_id):
            raise KeyError(f"plan {plan_id}")
        for item in items:
            conn.execute(insert(sessions).values(plan_id=plan_id, **{k: item.get(k) for k in SESSION_FIELDS}))


def replace_sessions(s: Scope, plan_id: int, items: list[dict]) -> None:
    with s.engine.begin() as conn:
        if not _owns_plan(conn, s, plan_id):
            raise KeyError(f"plan {plan_id}")
        conn.execute(delete(sessions).where(sessions.c.plan_id == plan_id))
    add_sessions(s, plan_id, items)


def get_plan(s: Scope, plan_id: int) -> dict | None:
    with s.engine.connect() as conn:
        row = conn.execute(select(plans).where(plans.c.id == plan_id, plans.c.user_id == s.user_id)).mappings().first()
        if not row:
            return None
        items = conn.execute(select(sessions).where(sessions.c.plan_id == plan_id).order_by(sessions.c.date, sessions.c.id)).mappings()
        out = {k: v for k, v in row.items() if k != "user_id"}
        links = {r.activity_id: r.session_date for r in conn.execute(select(plan_links).where(plan_links.c.plan_id == plan_id))}
        return {**out, "created_at": row["created_at"].isoformat(), "sessions": [dict(x) for x in items], "links": links}


def set_plan_link(s: Scope, plan_id: int, activity_id: str, session_date: str | None) -> None:
    """Link an activity to the plan's session of its sport on `session_date`, or with None keep it out of the plan."""
    with s.engine.begin() as conn:
        if not _owns_plan(conn, s, plan_id):
            raise KeyError(f"plan {plan_id}")
        conn.execute(delete(plan_links).where(plan_links.c.plan_id == plan_id, plan_links.c.activity_id == activity_id))
        conn.execute(insert(plan_links).values(user_id=s.user_id, plan_id=plan_id, activity_id=activity_id, session_date=session_date))


def clear_plan_link(s: Scope, plan_id: int, activity_id: str) -> None:
    """Back to automatic matching for this activity."""
    with s.engine.begin() as conn:
        conn.execute(
            delete(plan_links).where(
                plan_links.c.user_id == s.user_id, plan_links.c.plan_id == plan_id, plan_links.c.activity_id == activity_id
            )
        )


def active_plan(s: Scope) -> dict | None:
    with s.engine.connect() as conn:
        pid = conn.execute(
            select(plans.c.id).where(plans.c.user_id == s.user_id, plans.c.status == "active").order_by(plans.c.id.desc())
        ).scalar()
    return get_plan(s, pid) if pid else None


def list_plans(s: Scope) -> list[dict]:
    with s.engine.connect() as conn:
        rows = conn.execute(select(plans).where(plans.c.user_id == s.user_id).order_by(plans.c.id.desc())).mappings()
        return [{**{k: v for k, v in r.items() if k != "user_id"}, "created_at": r["created_at"].isoformat()} for r in rows]


def set_plan_status(s: Scope, plan_id: int, status: str) -> None:
    with s.engine.begin() as conn:
        conn.execute(update(plans).where(plans.c.id == plan_id, plans.c.user_id == s.user_id).values(status=status))


def update_plan(s: Scope, plan_id: int, **fields) -> None:
    allowed = {"title", "goal", "race", "notes", "status"}
    values = {k: v for k, v in fields.items() if k in allowed}
    with s.engine.begin() as conn:
        if values.get("status") == "active":
            conn.execute(update(plans).where(plans.c.user_id == s.user_id, plans.c.status == "active").values(status="finished"))
        if values:
            conn.execute(update(plans).where(plans.c.id == plan_id, plans.c.user_id == s.user_id).values(**values))


# --- achievements ------------------------------------------------------------------------------------------------------

ACHIEVEMENT_KINDS = ("challenge", "race", "record", "milestone")


def add_achievement(
    s: Scope,
    day: str,
    title: str,
    author: str,
    kind: str = "milestone",
    body: str | None = None,
    sport: str | None = None,
    plan_id: int | None = None,
) -> int:
    if kind not in ACHIEVEMENT_KINDS:
        raise ValueError(f"kind {kind}")
    with s.engine.begin() as conn:
        if plan_id is not None and not _owns_plan(conn, s, plan_id):
            raise KeyError(f"plan {plan_id}")
        res = conn.execute(
            insert(achievements).values(
                user_id=s.user_id,
                day=day,
                title=title,
                body=body,
                kind=kind,
                sport=sport,
                plan_id=plan_id,
                author=author,
                created_at=_now(),
            )
        )
        return res.inserted_primary_key[0]


def list_achievements(s: Scope) -> list[dict]:
    q = select(achievements).where(achievements.c.user_id == s.user_id).order_by(achievements.c.day.desc(), achievements.c.id.desc())
    with s.engine.connect() as conn:
        return [
            {**{k: v for k, v in r.items() if k != "user_id"}, "created_at": r["created_at"].isoformat()}
            for r in conn.execute(q).mappings()
        ]


def delete_achievement(s: Scope, achievement_id: int) -> bool:
    with s.engine.begin() as conn:
        res = conn.execute(delete(achievements).where(achievements.c.id == achievement_id, achievements.c.user_id == s.user_id))
        return res.rowcount > 0


# --- routes ------------------------------------------------------------------------------------------------------------


def save_routes(s: Scope, items: list[dict]) -> None:
    with s.engine.begin() as conn:
        conn.execute(delete(routes).where(routes.c.user_id == s.user_id))
        for r in items:
            conn.execute(insert(routes).values(user_id=s.user_id, id=r["id"], sport=r.get("sport", "run"), data=r))


def load_routes(s: Scope) -> list[dict]:
    with s.engine.connect() as conn:
        return [data for (data,) in conn.execute(select(routes.c.data).where(routes.c.user_id == s.user_id))]
