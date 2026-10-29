"""tabstealth-api: the song library, YouTube conversions and tab edits behind tabstealth-web.

  uvicorn app:create_app --factory --port 8770

Behind the shared trackerai login (packages/accounts): every route sees only the caller's own library, in Postgres
(DATABASE_URL, db.py). Only accounts the admin gave tabstealth may use it (an admin gets it on the first visit).
Conversions run here, one at a time (tabreader); a song converted elsewhere, or a whole library, comes in as an
export (python -m tabreader export) through /api/library/import.
"""

import io
import itertools
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Literal

import db
import guitarpro as gp
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from tabreader.ascii import gp5_to_ascii
from tabreader.cli import split_title

from trackerai_accounts import AccountError, Accounts, Config, crypto, open_accounts
from trackerai_accounts import connect as connect_accounts
from trackerai_accounts import install as install_accounts
from trackerai_accounts import make_router as accounts_router
from trackerai_accounts import session as account_session
from trackerai_accounts.config import front_door_origins
from trackerai_websec.csrf import OriginCheckMiddleware
from trackerai_websec.headers import SecurityHeadersMiddleware
from trackerai_websec.uploads import BodyLimitMiddleware

APP = "tabstealth"
HERE = Path(__file__).resolve().parent
YT_URL = re.compile(r"^(https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+|[\w-]{11})$")
NO_STORE = {"Cache-Control": "no-store"}  # an edited tab must reload, not come from cache
PDF_MAX = 40 * 1024 * 1024
IMPORT_MAX = 200 * 1024 * 1024  # a whole library with its PDFs, as one export
JSON_BODY_MAX = 256 * 1024
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})|^([\w-]{11})$")
KEY = re.compile(r"^([\w-]{11}|pdf-[0-9a-f]{10})$")
API_CSP = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# a PDF is shown in a frame of tabstealth's own page (the site passes /api/* on under its own origin)
PDF_HEADERS = {
    "Content-Disposition": "inline",
    "X-Frame-Options": "SAMEORIGIN",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'",
}


class ConvertIn(BaseModel):
    url: str = Field(max_length=500)


Fret = int | Literal["x"]  # 0-24, or "x" for a dead note


class GraceIn(BaseModel):
    fret: Fret
    slide: bool = False
    hammer: bool = False


class NoteIn(BaseModel):
    fret: Fret
    tie: bool = False  # continues the previous note on this string
    hammer: bool = False  # hammer-on / pull-off to the next note on this string
    slide: bool = False  # slide to the next note on this string
    let_ring: bool = False
    palm_mute: bool = False
    ghost: bool = False
    harmonic: bool = False  # natural harmonic
    vibrato: bool = False
    bend: Literal[0, 50, 100] = 0  # none, half (1 semitone), full (2 semitones)
    grace: GraceIn | None = None  # a grace note just before the beat


class BeatEdit(BaseModel):
    bar: int = Field(ge=0)
    beat: int = Field(ge=0)  # index among the bar's beats, grace notes not counted
    # string number (1 = high e) -> the note on it; a string that is not listed has no note
    notes: dict[Literal["1", "2", "3", "4", "5", "6"], NoteIn] = {}
    stroke: Literal["down", "up", "arpeggio"] | None = None
    chord: str | None = Field(default=None, max_length=40)


Status = Literal["new", "checking", "learning", "mastered"]


class SongPatch(BaseModel):
    status: Status | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    favourite: bool | None = None


class PracticeIn(BaseModel):
    video: str = Field(max_length=20)
    day: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")  # the player's own date: practice counts on your calendar
    seconds: int = Field(ge=1, le=600)
    speed: float = Field(ge=0.1, le=2)
    source: Literal["video", "tab"]
    bars: tuple[int, int] | None = None  # the looped range, if any (1-based, inclusive)
    whole_song: bool = False  # played from the start to the end at this speed


class ReanalyseIn(BaseModel):
    overwrite_edits: bool = False


class VideoIn(BaseModel):
    url: str = Field(max_length=500)
    title: str | None = Field(default=None, max_length=200)
    artist: str | None = Field(default=None, max_length=200)


class ReviewMark(BaseModel):
    bar: int = Field(ge=0)
    checked: bool


class BarEdit(BaseModel):
    bar: int = Field(ge=0)
    section: str | None = Field(default=None, max_length=60)


def youtube_title(vid: str) -> str | None:
    """The video's title, by yt-dlp (which the converter needs anyway, and which brings its own certificates);
    None when it is not installed or offline."""
    try:
        r = subprocess.run(
            ["yt-dlp", "--skip-download", "--print", "%(title)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True,
            text=True,
            timeout=40,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


# ── importing converter output: a conversion here, an export from a Mac, a whole library ─────────────────────


class Export:
    """The converter's output, as a folder (a conversion here) or a zip (python -m tabreader export): index.json with
    an entry per song and the files it names, and for a whole library meta.json (status, tags, checked review bars)
    and practice.jsonl. Only the files the index names are read, so a zip cannot place anything anywhere."""

    def __init__(self, read: Callable[[str], bytes | None]):
        self.read = read

    @classmethod
    def folder(cls, path: Path) -> "Export":
        def read(name: str) -> bytes | None:
            p = (path / name).resolve()
            return p.read_bytes() if p.is_relative_to(path.resolve()) and p.is_file() else None

        return cls(read)

    @classmethod
    def zip(cls, data: bytes) -> "Export":
        try:
            z = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile:
            raise HTTPException(400, "not a tabstealth export") from None
        if sum(i.file_size for i in z.infolist()) > IMPORT_MAX * 3:
            raise HTTPException(413, "export too large")
        names = set(z.namelist())
        return cls(lambda name: z.read(name) if name in names else None)

    def json(self, name: str, default):
        raw = self.read(name)
        return json.loads(raw) if raw else default


def import_export(engine, uid: int, ex: Export, overwrite_edits: bool = False) -> dict:
    """Songs, their state and practice into a user's library. A song with edits is only replaced with
    overwrite_edits; the same practice session imported twice counts once."""
    index = ex.json("index.json", {})
    if not isinstance(index, dict):
        raise HTTPException(400, "not a tabstealth export")
    meta = ex.json("meta.json", {})
    added, kept = [], []
    for key, e in index.items():
        if not KEY.match(key) or not isinstance(e, dict):
            continue
        kind = e.get("kind", "tab")
        values = {
            "kind": kind,
            "title": str(e.get("title") or key)[:200],
            "artist": str(e.get("artist") or "")[:200],
            "converted": str(e.get("converted") or date.today().isoformat())[:10],
        }
        if kind == "tab":
            gp5 = ex.read(e.get("file", ""))
            if not gp5:
                continue
            current = db.get_song(engine, uid, key, "gp5", "orig_gp5")
            if current and current["orig_gp5"] is not None and current["orig_gp5"] != current["gp5"] and not overwrite_edits:
                kept.append(key)  # your edits stay
                continue
            stem = Path(e["file"]).stem
            orig = ex.read(f"{stem}.orig.gp5")  # an edited song from a library export: its edits come along
            values |= {
                "gp5": gp5,
                "orig_gp5": orig,
                "timing": json.loads(ex.read(e.get("timing", "")) or "null"),
                "review": json.loads(ex.read(e.get("review", "")) or "[]"),
                **{k: e.get(k) for k in ("measures", "tempo", "time_signature", "capo", "swing", "flagged")},
            }
            db.put_song(engine, uid, key, values)
            if not orig:
                db.clear_history(engine, uid, key)
        elif kind == "pdf":
            pdf = ex.read(e.get("file", ""))
            if not pdf or not pdf.startswith(b"%PDF"):
                continue
            db.put_song(engine, uid, key, values | {"pdf": pdf})
        else:
            db.put_song(engine, uid, key, values)
        m = meta.get(key) or {}
        state = {
            "status": m.get("status") if m.get("status") in ("new", "checking", "learning", "mastered") else None,
            "tags": [str(t)[:30] for t in m.get("tags", [])][:20] if isinstance(m.get("tags"), list) else None,
            "favourite": bool(m["favourite"]) if "favourite" in m else None,
            "checked": [int(b) for b in m.get("checked", [])] if isinstance(m.get("checked"), list) else None,
        }
        state = {k: v for k, v in state.items() if v is not None}
        if state:
            db.update_song(engine, uid, key, state)
        added.append(key)
    practised = 0
    for line in (ex.read("practice.jsonl") or b"").decode().splitlines():
        try:
            p = PracticeIn.model_validate_json(line).model_dump(mode="json")
        except ValueError:
            continue
        p["bars"] = list(p["bars"]) if p["bars"] else None
        if not db.has_practice(engine, uid, p):
            db.add_practice(engine, uid, p)
            practised += 1
    return {"songs": added, "kept_edits": kept, "practice": practised}


class Jobs:
    """Conversions run one at a time in a worker thread (each one keeps several cores busy). Each job belongs to the
    user who asked for it; its result goes into that user's library."""

    def __init__(self, runner=None):
        self.items: dict[int, dict] = {}
        self.queue: queue.Queue[int] = queue.Queue()
        self.ids = itertools.count(1)
        self.runner = runner or self._run
        self.store: Callable[[dict, Path], None] = lambda job, out: None
        threading.Thread(target=self._work, daemon=True).start()

    def add(self, uid: int, url: str, args: list[str] | None = None, overwrite_edits: bool = False) -> dict:
        jid = next(self.ids)
        self.items[jid] = {
            "id": jid,
            "user": uid,
            "url": url,
            "args": args or [],
            "overwrite_edits": overwrite_edits,
            "status": "queued",
            "log": [],
        }
        self.queue.put(jid)
        return self.view(self.items[jid])

    @staticmethod
    def view(job: dict) -> dict:
        return {k: job[k] for k in ("id", "url", "args", "status")} | {"log": job["log"][-8:]}

    def of(self, uid: int) -> list[dict]:
        return [self.view(j) for j in sorted(self.items.values(), key=lambda j: -j["id"]) if j["user"] == uid]

    def _work(self) -> None:
        while True:
            job = self.items[self.queue.get()]
            job["status"] = "running"
            with tempfile.TemporaryDirectory(prefix="tabstealth-") as out:
                try:
                    ok = self.runner(job, Path(out))
                    if ok:
                        self.store(job, Path(out))
                except Exception as e:  # noqa: BLE001 - one bad video must not stop the worker
                    job["log"].append(f"FAILED {e!r}")
                    ok = False
            job["status"] = "done" if ok else "failed"

    @staticmethod
    def _run(job: dict, out: Path) -> bool:
        url = job["url"]
        args = ["--playlist", url] if "list=" in url and "watch?v=" not in url else [url]
        args += [*job.get("args", []), "--out", str(out)]
        p = subprocess.Popen(
            [sys.executable, "-m", "tabreader", *args], cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        for line in p.stdout:
            job["log"] = (job["log"] + [line.rstrip()])[-200:]
        return p.wait() == 0 and not any("FAILED" in line for line in job["log"])


# ── reading and editing a .gp5 ─────────────────────────────────────────────────


def _fret(v: int | str) -> tuple[int, bool]:
    """(fret, dead) from a fret field."""
    if v == "x":
        return 0, True
    if not 0 <= int(v) <= 24:
        raise HTTPException(400, "fret must be 0-24")
    return int(v), False


def _bend_of(bend) -> int:
    """0, 50 or 100: the height of a bend (half or full) from its highest point, in semitones."""
    if bend is None or not bend.points:
        return 0
    top = max(p.value for p in bend.points)
    return 100 if top >= 2 else 50 if top >= 1 else 0


def parse(gp5: bytes):
    return gp.parse(io.BytesIO(gp5))


def written(song) -> bytes:
    out = io.BytesIO()
    gp.write(song, out, version=(5, 1, 0))
    return out.getvalue()


def change_beat(song, edit: BeatEdit) -> None:
    """Set one beat: its notes with their techniques, the strum and the chord name.

    Built on the existing notes, so what this form does not show (staccato, a trill) stays as it was.
    """
    measures = song.tracks[0].measures
    if edit.bar >= len(measures) or edit.beat >= len(measures[edit.bar].voices[0].beats):
        raise HTTPException(404, "no such beat")
    beat = measures[edit.bar].voices[0].beats[edit.beat]
    existing = {n.string: n for n in beat.notes}
    notes = []
    for s in range(1, 7):
        spec = edit.notes.get(str(s))
        if spec is None:
            continue
        n = existing.get(s) or gp.Note(beat, string=s)
        n.value, dead = _fret(spec.fret)
        n.type = gp.NoteType.dead if dead else gp.NoteType.tie if spec.tie else gp.NoteType.normal
        e = n.effect
        e.hammer = spec.hammer
        if not spec.slide:
            e.slides = []
        elif not e.slides:
            e.slides = [gp.SlideType.legatoSlideTo]
        e.letRing, e.palmMute, e.ghostNote, e.vibrato = spec.let_ring, spec.palm_mute, spec.ghost, spec.vibrato
        if not spec.harmonic:
            e.harmonic = None
        elif e.harmonic is None:
            e.harmonic = gp.NaturalHarmonic()
        have = _bend_of(e.bend)
        if spec.bend == 0:
            e.bend = None
        elif have != spec.bend:  # an unchanged bend keeps its own shape
            st = spec.bend // 50
            e.bend = gp.BendEffect(
                type=gp.BendType.bend, value=spec.bend, points=[gp.BendPoint(0, 0), gp.BendPoint(6, st), gp.BendPoint(12, st)]
            )
        if spec.grace is None:
            e.grace = None
        else:
            fret, gdead = _fret(spec.grace.fret)
            e.grace = gp.GraceEffect(
                fret=fret,
                duration=32,
                isDead=gdead,
                transition=gp.GraceEffectTransition.slide
                if spec.grace.slide
                else gp.GraceEffectTransition.hammer
                if spec.grace.hammer
                else gp.GraceEffectTransition.none,
            )
        notes.append(n)
    beat.notes = notes
    beat.status = gp.BeatStatus.normal if notes else gp.BeatStatus.rest
    if edit.stroke is None or not notes:
        beat.effect.stroke = gp.BeatStroke()
    else:
        beat.effect.stroke = gp.BeatStroke(
            direction=gp.BeatStrokeDirection.up if edit.stroke == "up" else gp.BeatStrokeDirection.down,
            value=16 if edit.stroke == "arpeggio" else 64,
        )
    beat.text = (edit.chord or "").strip() or None


def change_bar(song, edit: BarEdit) -> None:
    """Set or clear the section name (a Guitar Pro marker) that starts at a bar."""
    if edit.bar >= len(song.measureHeaders):
        raise HTTPException(404, "no such bar")
    name = (edit.section or "").strip()
    song.measureHeaders[edit.bar].marker = gp.Marker(title=name) if name else None


def read_beat(song, bar: int, beat_idx: int) -> dict:
    """One beat as the editor's form (BeatEdit plus the bar's section), straight from the .gp5: the file is the
    source of truth, and the renderer can drop details (a slide whose target is bars away)."""
    measures = song.tracks[0].measures
    if bar >= len(measures) or beat_idx >= len(measures[bar].voices[0].beats):
        raise HTTPException(404, "no such beat")
    beat = measures[bar].voices[0].beats[beat_idx]
    notes = {}
    for n in beat.notes:
        e = n.effect
        g = e.grace
        notes[str(n.string)] = NoteIn(
            fret="x" if n.type == gp.NoteType.dead else n.value,
            tie=n.type == gp.NoteType.tie,
            hammer=e.hammer,
            slide=bool(e.slides),
            let_ring=e.letRing,
            palm_mute=e.palmMute,
            ghost=e.ghostNote,
            harmonic=e.harmonic is not None,
            vibrato=e.vibrato,
            bend=_bend_of(e.bend),
            grace=None
            if g is None
            else GraceIn(
                fret="x" if g.isDead else g.fret,
                slide=g.transition == gp.GraceEffectTransition.slide,
                hammer=g.transition == gp.GraceEffectTransition.hammer,
            ),
        ).model_dump()
    st = beat.effect.stroke
    stroke = (
        None
        if st is None or st.direction == gp.BeatStrokeDirection.none
        else "arpeggio"
        if st.value and st.value <= 16
        else "up"
        if st.direction == gp.BeatStrokeDirection.up
        else "down"
    )
    marker = measures[bar].header.marker
    return {
        "bar": bar,
        "beat": beat_idx,
        "notes": notes,
        "stroke": stroke,
        "chord": beat.text or None,
        "section": marker.title if marker else None,
    }


def practice_summary(entries: list[dict], today: str | None = None) -> dict:
    """Minutes per day, per song, the streak and the speed reached per song per day."""
    from datetime import timedelta

    per_day: dict[str, int] = {}
    per_song: dict[str, dict] = {}
    speed: dict[str, dict[str, float]] = {}
    for e in entries:
        per_day[e["day"]] = per_day.get(e["day"], 0) + e["seconds"]
        s = per_song.setdefault(e["video"], {"video": e["video"], "seconds": 0, "last": e["day"], "best_speed": 0.0})
        s["seconds"] += e["seconds"]
        s["last"] = max(s["last"], e["day"])
        if e.get("whole_song"):
            s["best_speed"] = max(s["best_speed"], e["speed"])
        sp = speed.setdefault(e["video"], {})
        sp[e["day"]] = max(sp.get(e["day"], 0.0), e["speed"])
    streak = 0
    d = date.fromisoformat(today) if today else max((date.fromisoformat(k) for k in per_day), default=None)
    if d is not None and d.isoformat() not in per_day:
        d -= timedelta(days=1)  # today not practised yet: the streak still counts up to yesterday
    while d is not None and d.isoformat() in per_day:
        streak += 1
        d -= timedelta(days=1)
    return {
        "days": [{"day": k, "seconds": v} for k, v in sorted(per_day.items())],
        "songs": sorted(per_song.values(), key=lambda x: -x["seconds"]),
        "speed": {v: [{"day": k, "speed": sp} for k, sp in sorted(days.items())] for v, days in speed.items()},
        "streak": streak,
        "total_seconds": sum(per_day.values()),
    }


# ── the app ────────────────────────────────────────────────────────────────────


def test_accounts(engine) -> Accounts:
    """Accounts of their own for a test app: an `accounts` schema in the test's database, two-step login off."""
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS accounts"))
    url = engine.url.update_query_dict({"options": "-csearch_path=accounts"}).render_as_string(hide_password=False)
    cfg = Config(database_url=url, session_secret="t" * 40, encryption_key=crypto.new_key(), cookie_secure=False, require_totp="off")
    return Accounts(connect_accounts(cfg.database_url), cfg)


def purge(engine, accounts: Accounts) -> int:
    """Delete the libraries of accounts that left tabstealth or were deleted (also from another tracker)."""
    n = 0
    for p in accounts.pending_purges(APP):
        key = p.get("local_key")
        if key and str(key).isdigit():
            db.delete_user(engine, int(key))
        accounts.purged(p["account_id"], APP)
        n += 1
    return n


def create_app(engine=None, accounts: Accounts | None = None, jobs: Jobs | None = None) -> FastAPI:
    """`engine`: the database (default DATABASE_URL); `accounts`: the shared accounts (default ACCOUNTS_*)."""
    production = engine is None
    engine = engine or db.connect(os.environ["DATABASE_URL"])
    db.create_schema(engine)
    accounts = accounts or (open_accounts() if production else test_accounts(engine))
    jobs = jobs or Jobs()
    app = FastAPI(title="tabstealth-api", docs_url=None, redoc_url=None)
    edit_lock = threading.Lock()

    account_routes, sessions = accounts_router(accounts, APP)
    install_accounts(app)
    app.include_router(account_routes)
    public = [o.strip() for o in os.environ.get("PUBLIC_ORIGINS", "").split(",") if o.strip()]
    origins = (*public, *front_door_origins(accounts.config.cookie_domain))
    app.add_middleware(OriginCheckMiddleware, allowed_origins=origins, cookie_name=account_session.COOKIE)
    app.add_middleware(
        BodyLimitMiddleware,
        default=JSON_BODY_MAX,
        limits={"/api/library/pdf": PDF_MAX + 1024, "/api/library/import": IMPORT_MAX + 1024},
    )
    app.add_middleware(SecurityHeadersMiddleware, csp=API_CSP, hsts=accounts.config.cookie_secure)
    app.state.engine, app.state.accounts, app.state.jobs = engine, accounts, jobs

    def user(s=Depends(sessions.ready)) -> int:
        """The caller's tabstealth user. Only accounts with the app; an admin gets it on the first visit."""
        if APP not in s.apps:
            if not s.account["is_admin"]:
                raise AccountError(403, "app_not_available")
            accounts.join_app(s.id, APP)
        key = accounts.local_key(s.id, APP)
        if key is None:
            key = str(db.user_for_account(engine, s.id))
            accounts.set_local_key(s.id, APP, key)
        return int(key)

    def song(uid: int, vid: str, *cols: str) -> dict:
        row = db.get_song(engine, uid, vid, *cols, "kind") if cols else db.get_song(engine, uid, vid)
        if row is None:
            raise HTTPException(404, "unknown song")
        return row

    def tab_of(uid: int, vid: str) -> bytes:
        row = song(uid, vid, "gp5")
        if not row["gp5"]:
            raise HTTPException(404, "no tab")
        return row["gp5"]

    def store(job: dict, out: Path) -> None:
        r = import_export(engine, job["user"], Export.folder(out), job.get("overwrite_edits", False))
        if r["kept_edits"]:
            job["log"].append(f"kept your edits: {', '.join(r['kept_edits'])} (reanalyse again to replace them)")

    jobs.store = store

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/me")
    def me(s=Depends(sessions.ready), uid: int = Depends(user)):
        """Who is logged in; the site's gate (401: log in, 403 app_not_available: not given tabstealth)."""
        return {"username": s.username, "is_admin": bool(s.account["is_admin"]), "front_door_url": accounts.config.front_door_url}

    @app.get("/api/songs")
    def songs(uid: int = Depends(user)):
        played = {x["video"]: x for x in practice_summary(db.practice_entries(engine, uid))["songs"]}
        out = []
        for r in db.list_songs(engine, uid):
            checked = set(r.pop("checked") or [])
            review = r.pop("review") or []
            p = played.get(r["key"], {})
            out.append(
                {
                    "video": r.pop("key"),
                    **r,
                    "edited": bool(r["edited"]),
                    "practised_seconds": p.get("seconds", 0),
                    "last_practised": p.get("last"),
                    "to_review": sum(1 for x in review if x["bar"] not in checked),
                }
            )
        return out

    # ── the collection: videos to keep (no tab to read) and PDFs ────────────────────

    def add_entry(uid: int, key: str, values: dict) -> dict:
        if db.get_song(engine, uid, key, "key"):
            raise HTTPException(409, "already in the library")
        db.put_song(engine, uid, key, values | {"converted": date.today().isoformat()})
        return {"video": key, **values}

    @app.post("/api/library/video")
    def save_video(body: VideoIn, uid: int = Depends(user)):
        m = VIDEO_ID.search(body.url.strip())
        if not m:
            raise HTTPException(400, "not a YouTube link")
        vid = m.group(1) or m.group(2)
        title, artist = body.title, body.artist
        if not title:
            title, artist2 = split_title(youtube_title(vid) or vid)
            artist = artist or artist2
        return add_entry(uid, vid, {"kind": "video", "title": title, "artist": artist or ""})

    @app.post("/api/library/pdf")
    async def upload_pdf(request: Request, title: str = "", artist: str = "", uid: int = Depends(user)):
        data = await request.body()
        if len(data) > PDF_MAX:
            raise HTTPException(413, "PDF larger than 40 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "not a PDF")
        key = f"pdf-{uuid.uuid4().hex[:10]}"
        add_entry(uid, key, {"kind": "pdf", "title": title.strip()[:200] or "PDF", "artist": artist.strip()[:200]})
        db.update_song(engine, uid, key, {"pdf": data})
        return {"video": key, "kind": "pdf", "title": title.strip()[:200] or "PDF", "artist": artist.strip()[:200]}

    @app.post("/api/library/import")
    async def import_library(request: Request, overwrite_edits: bool = False, uid: int = Depends(user)):
        """A converter export (python -m tabreader export): one song converted elsewhere, or a whole library."""
        data = await request.body()
        if len(data) > IMPORT_MAX:
            raise HTTPException(413, "export larger than 200 MB")
        return import_export(engine, uid, Export.zip(data), overwrite_edits)

    @app.get("/api/songs/{vid}/pdf")
    def pdf(vid: str, uid: int = Depends(user)):
        row = song(uid, vid, "pdf")
        if row["kind"] != "pdf" or not row["pdf"]:
            raise HTTPException(404, "not a PDF")
        return Response(row["pdf"], media_type="application/pdf", headers=PDF_HEADERS)

    @app.post("/api/songs/{vid}/convert")
    def convert_saved(vid: str, body: ReanalyseIn | None = None, uid: int = Depends(user)):
        """Convert a saved video that turns out to have a tab after all (the tab replaces the saved video), or read a
        converted tab again with the current converter. That replaces edits, so an edited tab needs overwrite_edits."""
        row, url = song(uid, vid, "gp5", "orig_gp5"), f"https://www.youtube.com/watch?v={vid}"
        if row["kind"] == "pdf":
            raise HTTPException(400, "a PDF cannot be converted")
        if row["kind"] == "video":
            return jobs.add(uid, url)
        overwrite = bool(body and body.overwrite_edits)
        if row["orig_gp5"] is not None and row["orig_gp5"] != row["gp5"] and not overwrite:
            raise HTTPException(409, "the tab has edits; reanalysing replaces them")
        # --force is not needed: the frame scan is cached, only the reading runs again
        return jobs.add(uid, url, ["--overwrite-edits"] if overwrite else [], overwrite_edits=overwrite)

    @app.delete("/api/songs/{vid}")
    def remove(vid: str, uid: int = Depends(user)):
        song(uid, vid, "key")
        db.delete_song(engine, uid, vid)
        return {"ok": True}

    @app.patch("/api/songs/{vid}")
    def patch_song(vid: str, body: SongPatch, uid: int = Depends(user)):
        song(uid, vid, "key")
        values = {}
        if body.status is not None:
            values["status"] = body.status
        if body.tags is not None:
            values["tags"] = sorted({t.strip().lower()[:30] for t in body.tags if t.strip()})
        if body.favourite is not None:
            values["favourite"] = body.favourite
        if values:
            db.update_song(engine, uid, vid, values)
        r = song(uid, vid, "status", "tags", "favourite")
        return {k: r[k] for k in ("status", "tags", "favourite")}

    @app.get("/api/songs/{vid}/review")
    def review(vid: str, uid: int = Depends(user)):
        """The bars the converter was unsure about, with why, and whether you checked them."""
        r = song(uid, vid, "review", "checked")
        checked = set(r["checked"] or [])
        return [{**x, "checked": x["bar"] in checked} for x in r["review"] or []]

    @app.post("/api/songs/{vid}/review")
    def mark_review(vid: str, body: ReviewMark, uid: int = Depends(user)):
        checked = set(song(uid, vid, "checked")["checked"] or [])
        (checked.add if body.checked else checked.discard)(body.bar)
        db.update_song(engine, uid, vid, {"checked": sorted(checked)})
        return review(vid, uid)

    @app.post("/api/practice")
    def log_practice(body: PracticeIn, uid: int = Depends(user)):
        song(uid, body.video, "key")
        entry = body.model_dump(mode="json")
        entry["bars"] = list(entry["bars"]) if entry["bars"] else None
        db.add_practice(engine, uid, entry)
        return {"ok": True}

    @app.get("/api/practice")
    def practice(today: str | None = None, uid: int = Depends(user)):
        return practice_summary(db.practice_entries(engine, uid), today)

    @app.get("/api/songs/{vid}/tab")
    def tab(vid: str, uid: int = Depends(user)):
        return Response(tab_of(uid, vid), media_type="application/octet-stream", headers=NO_STORE)

    @app.get("/api/songs/{vid}/timing")
    def timing(vid: str, uid: int = Depends(user)):
        t = song(uid, vid, "timing")["timing"]
        if t is None:
            raise HTTPException(404, "no timing")
        return t

    @app.get("/api/songs/{vid}/text", response_class=PlainTextResponse)
    def text_tab(vid: str, uid: int = Depends(user)):
        # from the .gp5 as it is now, so the text tab always has your edits
        return PlainTextResponse(gp5_to_ascii(io.BytesIO(tab_of(uid, vid))), headers=NO_STORE)

    @app.get("/api/songs/{vid}/beats/{bar}/{beat}")
    def get_beat(vid: str, bar: int, beat: int, uid: int = Depends(user)):
        return read_beat(parse(tab_of(uid, vid)), bar, beat)

    def edit(uid: int, vid: str, change) -> None:
        """Change the tab: the version before goes on the undo stack (db.save_edit)."""
        with edit_lock:
            before = tab_of(uid, vid)
            s = parse(before)
            change(s)  # raises on a bad edit, before anything is written
            db.save_edit(engine, uid, vid, before, written(s))

    @app.post("/api/songs/{vid}/beats")
    def edit_beat(vid: str, body: BeatEdit, uid: int = Depends(user)):
        edit(uid, vid, lambda s: change_beat(s, body))
        return {"ok": True}

    @app.post("/api/songs/{vid}/bars")
    def edit_bar(vid: str, body: BarEdit, uid: int = Depends(user)):
        edit(uid, vid, lambda s: change_bar(s, body))
        return {"ok": True}

    @app.post("/api/songs/{vid}/restore")
    def restore(vid: str, uid: int = Depends(user)):
        """Back to the converter's version; undoable like any other change."""
        with edit_lock:
            r = song(uid, vid, "gp5", "orig_gp5")
            if r["orig_gp5"] is not None and r["orig_gp5"] != r["gp5"]:
                db.save_edit(engine, uid, vid, r["gp5"], r["orig_gp5"])
        return {"ok": True}

    @app.get("/api/songs/{vid}/history")
    def history(vid: str, uid: int = Depends(user)):
        song(uid, vid, "key")
        return db.counts(engine, uid, vid)

    @app.post("/api/songs/{vid}/undo")
    def undo(vid: str, uid: int = Depends(user)):
        with edit_lock:
            if not db.step(engine, uid, vid, "undo", "redo"):
                raise HTTPException(409, "nothing to undo")
        return db.counts(engine, uid, vid)

    @app.post("/api/songs/{vid}/redo")
    def redo(vid: str, uid: int = Depends(user)):
        with edit_lock:
            if not db.step(engine, uid, vid, "redo", "undo"):
                raise HTTPException(409, "nothing to redo")
        return db.counts(engine, uid, vid)

    @app.post("/api/convert")
    def convert(body: ConvertIn, uid: int = Depends(user)):
        url = body.url.strip()
        if not YT_URL.match(url):
            raise HTTPException(400, "not a YouTube link")
        return jobs.add(uid, url)

    @app.get("/api/jobs")
    def list_jobs(uid: int = Depends(user)):
        return jobs.of(uid)

    if production:

        def sweep():  # a deletion in another tracker reaches tabstealth's data within a minute
            stop = threading.Event()
            while not stop.wait(60):
                try:
                    purge(engine, accounts)
                except Exception as e:  # noqa: BLE001 - the next sweep tries again
                    print(f"purge: {e!r}", flush=True)

        purge(engine, accounts)
        threading.Thread(target=sweep, name="purge", daemon=True).start()

    return app
