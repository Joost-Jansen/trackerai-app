"""tabstealth's database: every user's library, tabs, edits and practice, in Postgres (DATABASE_URL).

SQLAlchemy Core, as health-tracker. Every data table carries `user_id` (users.id, the account's local key for
tabstealth), and the functions that touch someone's data take that id, so no query can forget whose data it is.

    engine = connect(os.environ["DATABASE_URL"])
    create_schema(engine)

A song is keyed by its YouTube id (or pdf-… for an uploaded PDF), per user. The tab itself is its .gp5 (a few tens of
kB): the file is the source of truth for the player and the editor, so it is kept as it is, with the converter's own
version next to it (orig_gp5, for "restore" and "edited?") and the earlier versions for undo and redo in `history`.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

meta = MetaData()

users = Table(
    "users",
    meta,
    Column("id", Integer, primary_key=True),
    Column("account_id", Integer, nullable=False, unique=True),  # the shared trackerai account
    Column("created_at", DateTime(timezone=True), nullable=False),
)

songs = Table(
    "songs",
    meta,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("key", String(40), nullable=False),  # YouTube id, or pdf-… for an uploaded PDF
    Column("kind", String(10), nullable=False),  # tab, video (kept without a tab) or pdf
    Column("title", String(200), nullable=False),
    Column("artist", String(200), nullable=False, default=""),
    Column("measures", Integer),
    Column("tempo", Integer),
    Column("time_signature", String(10)),
    Column("capo", Integer),
    Column("swing", String(10)),
    Column("flagged", Integer),
    Column("converted", String(10)),  # the day it was converted or added, YYYY-MM-DD
    Column("gp5", LargeBinary),
    Column("orig_gp5", LargeBinary),  # the converter's version, kept from the first edit on
    Column("timing", JSON),  # when every bar starts in the video (tabreader.cli.video_timing)
    Column("review", JSON),  # the bars the converter was unsure about
    Column("pdf", LargeBinary),
    Column("status", String(10), nullable=False, default="new"),
    Column("tags", JSON, nullable=False, default=list),
    Column("favourite", Boolean, nullable=False, default=False),
    Column("checked", JSON, nullable=False, default=list),  # review bars ticked off
    Column("created_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("user_id", "key"),
)

history = Table(
    "history",
    meta,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, nullable=False),
    Column("key", String(40), nullable=False),
    Column("stack", String(4), nullable=False),  # undo or redo
    Column("gp5", LargeBinary, nullable=False),
)

practice = Table(
    "practice",
    meta,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("video", String(40), nullable=False),
    Column("day", String(10), nullable=False),
    Column("seconds", Integer, nullable=False),
    Column("speed", Float, nullable=False),
    Column("source", String(5), nullable=False),
    Column("bars", JSON),
    Column("whole_song", Boolean, nullable=False, default=False),
)

HISTORY_MAX = 100  # undo steps kept per song

# the song fields the library list shows (the files stay out of it)
LISTED = [c for c in songs.c if c.name not in ("user_id", "gp5", "orig_gp5", "timing", "review", "pdf", "created_at")]


def now() -> datetime:
    return datetime.now(UTC)


def connect(url: str) -> Engine:
    if url.startswith("postgres://"):  # Railway's form
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return create_engine(url, pool_pre_ping=True, future=True)


def create_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        meta.create_all(conn)


# ── users ──────────────────────────────────────────────────────────────────────


def user_for_account(engine: Engine, account_id: int) -> int:
    """The tabstealth user of an account, made on its first visit."""
    with engine.begin() as c:
        uid = c.execute(select(users.c.id).where(users.c.account_id == account_id)).scalar()
        if uid is None:
            uid = c.execute(insert(users).values(account_id=account_id, created_at=now()).returning(users.c.id)).scalar()
        return uid


def delete_user(engine: Engine, user_id: int) -> None:
    """Everything of a user: songs and practice go with the user row (cascade), the history by hand."""
    with engine.begin() as c:
        c.execute(delete(history).where(history.c.user_id == user_id))
        c.execute(delete(users).where(users.c.id == user_id))


# ── songs ──────────────────────────────────────────────────────────────────────


def list_songs(engine: Engine, user_id: int) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(*LISTED, (songs.c.orig_gp5.is_not(None) & (songs.c.orig_gp5 != songs.c.gp5)).label("edited"), songs.c.review)
            .where(songs.c.user_id == user_id)
            .order_by(songs.c.created_at)
        ).mappings()
        return [dict(r) for r in rows]


def get_song(engine: Engine, user_id: int, key: str, *cols: str) -> dict | None:
    picked = [songs.c[n] for n in cols] if cols else list(songs.c)
    with engine.connect() as c:
        row = c.execute(select(*picked).where(songs.c.user_id == user_id, songs.c.key == key)).mappings().first()
        return dict(row) if row else None


def put_song(engine: Engine, user_id: int, key: str, values: dict) -> None:
    """Add a song or replace its fields (a conversion again); what `values` leaves out stays."""
    with engine.begin() as c:
        exists = c.execute(select(songs.c.key).where(songs.c.user_id == user_id, songs.c.key == key)).first()
        if exists:
            c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key).values(**values))
        else:
            c.execute(insert(songs).values(user_id=user_id, key=key, created_at=now(), **values))


def update_song(engine: Engine, user_id: int, key: str, values: dict) -> None:
    with engine.begin() as c:
        c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key).values(**values))


def delete_song(engine: Engine, user_id: int, key: str) -> None:
    with engine.begin() as c:
        c.execute(delete(songs).where(songs.c.user_id == user_id, songs.c.key == key))
        c.execute(delete(history).where(history.c.user_id == user_id, history.c.key == key))


# ── the tab, its edits and undo/redo ───────────────────────────────────────────


def counts(engine: Engine, user_id: int, key: str) -> dict:
    with engine.connect() as c:
        rows = c.execute(
            select(history.c.stack, func.count()).where(history.c.user_id == user_id, history.c.key == key).group_by(history.c.stack)
        ).all()
    n = dict(rows)
    return {"undo": n.get("undo", 0), "redo": n.get("redo", 0)}


def save_edit(engine: Engine, user_id: int, key: str, before: bytes, after: bytes) -> None:
    """A changed tab: the version before goes on the undo stack, the redo stack empties, and the converter's version
    is kept once (orig_gp5) for restore."""
    with engine.begin() as c:
        c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key, songs.c.orig_gp5.is_(None)).values(orig_gp5=before))
        c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key).values(gp5=after))
        c.execute(delete(history).where(history.c.user_id == user_id, history.c.key == key, history.c.stack == "redo"))
        _push(c, user_id, key, "undo", before)


def _push(c, user_id: int, key: str, stack: str, gp5: bytes) -> None:
    c.execute(insert(history).values(user_id=user_id, key=key, stack=stack, gp5=gp5))
    old = (
        select(history.c.id)
        .where(history.c.user_id == user_id, history.c.key == key, history.c.stack == stack)
        .order_by(history.c.id.desc())
        .offset(HISTORY_MAX)
    )
    c.execute(delete(history).where(history.c.id.in_(old)))


def step(engine: Engine, user_id: int, key: str, frm: str, to: str) -> bool:
    """Undo (frm=undo, to=redo) or redo: the newest version on `frm` becomes the tab, the tab goes on `to`.
    False when there is nothing to take."""
    with engine.begin() as c:
        top = c.execute(
            select(history.c.id, history.c.gp5)
            .where(history.c.user_id == user_id, history.c.key == key, history.c.stack == frm)
            .order_by(history.c.id.desc())
            .limit(1)
        ).first()
        if top is None:
            return False
        current = c.execute(select(songs.c.gp5).where(songs.c.user_id == user_id, songs.c.key == key)).scalar()
        _push(c, user_id, key, to, current)
        c.execute(delete(history).where(history.c.id == top.id))
        c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key).values(gp5=top.gp5))
        return True


def clear_history(engine: Engine, user_id: int, key: str) -> None:
    """A fresh conversion is the new original: no older backup or undo history to compare it with."""
    with engine.begin() as c:
        c.execute(delete(history).where(history.c.user_id == user_id, history.c.key == key))
        c.execute(update(songs).where(songs.c.user_id == user_id, songs.c.key == key).values(orig_gp5=None))


# ── practice ───────────────────────────────────────────────────────────────────


def add_practice(engine: Engine, user_id: int, entry: dict) -> None:
    with engine.begin() as c:
        c.execute(insert(practice).values(user_id=user_id, **entry))


def practice_entries(engine: Engine, user_id: int) -> list[dict]:
    cols = [practice.c[n] for n in ("video", "day", "seconds", "speed", "source", "bars", "whole_song")]
    with engine.connect() as c:
        return [dict(r) for r in c.execute(select(*cols).where(practice.c.user_id == user_id).order_by(practice.c.id)).mappings()]


def has_practice(engine: Engine, user_id: int, entry: dict) -> bool:
    """The same session logged already (an import done twice)."""
    cond = [practice.c.user_id == user_id] + [practice.c[k] == v for k, v in entry.items() if k != "bars"]
    with engine.connect() as c:
        return c.execute(select(func.count()).where(*cond)).scalar() > 0
