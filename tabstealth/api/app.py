"""tabstealth-api: the song library, YouTube conversions and tab edits behind tabstealth-web.

  uvicorn app:create_app --factory --port 8770

Local-first: no accounts yet, so it binds to 127.0.0.1 and is not meant to be exposed (see README).
"""
import filecmp
import itertools
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import guitarpro as gp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse
from typing import Literal

from pydantic import BaseModel, Field

from tabreader.ascii import gp5_to_ascii
from tabreader.cli import LIBRARY, split_title

HERE = Path(__file__).resolve().parent
YT_URL = re.compile(r"^(https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+|[\w-]{11})$")
NO_STORE = {"Cache-Control": "no-store"}  # an edited tab must reload, not come from cache


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


class VideoIn(BaseModel):
    url: str = Field(max_length=500)
    title: str | None = Field(default=None, max_length=200)
    artist: str | None = Field(default=None, max_length=200)


PDF_MAX = 40 * 1024 * 1024
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})|^([\w-]{11})$")


def youtube_title(vid: str) -> str | None:
    """The video's title, by yt-dlp (which the converter needs anyway, and which brings its own certificates);
    None when it is not installed or offline."""
    try:
        r = subprocess.run(["yt-dlp", "--skip-download", "--print", "%(title)s", f"https://www.youtube.com/watch?v={vid}"],
                           capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() or None if r.returncode == 0 else None


class ReviewMark(BaseModel):
    bar: int = Field(ge=0)
    checked: bool


class BarEdit(BaseModel):
    bar: int = Field(ge=0)
    section: str | None = Field(default=None, max_length=60)


class Jobs:
    """Conversions run one at a time in a worker thread (each one keeps several cores busy)."""

    def __init__(self, runner=None):
        self.items: dict[int, dict] = {}
        self.queue: "queue.Queue[int]" = queue.Queue()
        self.ids = itertools.count(1)
        self.runner = runner or self._run
        threading.Thread(target=self._work, daemon=True).start()

    def add(self, url: str) -> dict:
        jid = next(self.ids)
        self.items[jid] = {"id": jid, "url": url, "status": "queued", "log": []}
        self.queue.put(jid)
        return self.items[jid]

    def _work(self) -> None:
        while True:
            job = self.items[self.queue.get()]
            job["status"] = "running"
            ok = self.runner(job)
            job["status"] = "done" if ok else "failed"

    @staticmethod
    def _run(job: dict) -> bool:
        url = job["url"]
        args = ["--playlist", url] if "list=" in url and "watch?v=" not in url else [url]
        p = subprocess.Popen([sys.executable, "-m", "tabreader", *args], cwd=HERE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            job["log"] = (job["log"] + [line.rstrip()])[-200:]
        return p.wait() == 0 and not any("FAILED" in line for line in job["log"])


def read_index(library: Path) -> dict:
    p = library / "index.json"
    return json.loads(p.read_text()) if p.exists() else {}


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


class History:
    """Undo and redo for a song's .gp5: two stacks of earlier versions next to the library.

    library/.history/<file stem>/undo/00001.gp5 …; a change pushes the current file on undo and empties redo.
    """

    MAX = 100

    def __init__(self, path: Path):
        self.path = path
        self.base = path.parent / ".history" / path.stem

    def _dir(self, stack: str) -> Path:
        d = self.base / stack
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _files(self, stack: str) -> list[Path]:
        return sorted(self._dir(stack).glob("*.gp5"))

    def count(self, stack: str) -> int:
        return len(self._files(stack))

    def _push(self, stack: str) -> None:
        files = self._files(stack)
        n = int(files[-1].stem) + 1 if files else 1
        shutil.copy2(self.path, self._dir(stack) / f"{n:05d}.gp5")
        for old in files[: max(0, len(files) + 1 - self.MAX)]:
            old.unlink()

    def before_change(self) -> None:
        self._push("undo")
        for f in self._files("redo"):
            f.unlink()

    def step(self, frm: str, to: str) -> None:
        """Undo (frm=undo, to=redo) or redo (frm=redo, to=undo)."""
        files = self._files(frm)
        if not files:
            raise HTTPException(409, f"nothing to {frm}")
        self._push(to)
        shutil.move(files[-1], self.path)


def _edit_gp5(path: Path, lock: threading.Lock, change) -> None:
    """Change a .gp5 in place: the version before goes on the undo stack, and the converter's version is kept once
    as .orig.gp5 (restore)."""
    backup = path.with_name(path.stem + ".orig.gp5")
    with lock:
        song = gp.parse(str(path))
        change(song)  # raises on a bad edit, before anything is written
        if not backup.exists():
            shutil.copy2(path, backup)
        History(path).before_change()
        gp.write(song, str(path), version=(5, 1, 0))


def is_edited(path: Path) -> bool:
    backup = path.with_name(path.stem + ".orig.gp5")
    return backup.exists() and not filecmp.cmp(backup, path, shallow=False)


def apply_edit(path: Path, edit: BeatEdit, lock: threading.Lock) -> None:
    """Set one beat: its notes with their techniques, the strum and the chord name.

    Built on the existing notes, so what this form does not show (staccato, a trill) stays as it was.
    """
    def change(song):
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
                e.bend = gp.BendEffect(type=gp.BendType.bend, value=spec.bend,
                                       points=[gp.BendPoint(0, 0), gp.BendPoint(6, st), gp.BendPoint(12, st)])
            if spec.grace is None:
                e.grace = None
            else:
                fret, gdead = _fret(spec.grace.fret)
                e.grace = gp.GraceEffect(
                    fret=fret, duration=32, isDead=gdead,
                    transition=gp.GraceEffectTransition.slide if spec.grace.slide
                    else gp.GraceEffectTransition.hammer if spec.grace.hammer else gp.GraceEffectTransition.none)
            notes.append(n)
        beat.notes = notes
        beat.status = gp.BeatStatus.normal if notes else gp.BeatStatus.rest
        if edit.stroke is None or not notes:
            beat.effect.stroke = gp.BeatStroke()
        else:
            beat.effect.stroke = gp.BeatStroke(
                direction=gp.BeatStrokeDirection.up if edit.stroke == "up" else gp.BeatStrokeDirection.down,
                value=16 if edit.stroke == "arpeggio" else 64)
        beat.text = (edit.chord or "").strip() or None

    _edit_gp5(path, lock, change)


def read_beat(path: Path, bar: int, beat_idx: int) -> dict:
    """One beat as the editor's form (BeatEdit plus the bar's section), straight from the .gp5: the file is the
    source of truth, and the renderer can drop details (a slide whose target is bars away)."""
    song = gp.parse(str(path))
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
            tie=n.type == gp.NoteType.tie, hammer=e.hammer, slide=bool(e.slides), let_ring=e.letRing,
            palm_mute=e.palmMute, ghost=e.ghostNote, harmonic=e.harmonic is not None, vibrato=e.vibrato,
            bend=_bend_of(e.bend),
            grace=None if g is None else GraceIn(
                fret="x" if g.isDead else g.fret, slide=g.transition == gp.GraceEffectTransition.slide,
                hammer=g.transition == gp.GraceEffectTransition.hammer),
        ).model_dump()
    st = beat.effect.stroke
    stroke = (None if st is None or st.direction == gp.BeatStrokeDirection.none
              else "arpeggio" if st.value and st.value <= 16
              else "up" if st.direction == gp.BeatStrokeDirection.up else "down")
    marker = measures[bar].header.marker
    return {"bar": bar, "beat": beat_idx, "notes": notes, "stroke": stroke, "chord": beat.text or None,
            "section": marker.title if marker else None}


def apply_bar(path: Path, edit: BarEdit, lock: threading.Lock) -> None:
    """Set or clear the section name (a Guitar Pro marker) that starts at a bar."""
    def change(song):
        if edit.bar >= len(song.measureHeaders):
            raise HTTPException(404, "no such bar")
        name = (edit.section or "").strip()
        song.measureHeaders[edit.bar].marker = gp.Marker(title=name) if name else None

    _edit_gp5(path, lock, change)


def read_meta(library: Path) -> dict:
    p = library / "meta.json"
    return json.loads(p.read_text()) if p.exists() else {}


def read_review(library: Path, entry: dict) -> list[dict]:
    """The converter's review list for a song (older conversions have none)."""
    p = library / entry.get("review", "")
    return json.loads(p.read_text()) if entry.get("review") and p.exists() else []


def read_practice(library: Path) -> list[dict]:
    p = library / "practice.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def practice_summary(entries: list[dict], today: str | None = None) -> dict:
    """Minutes per day, per song, the streak and the speed reached per song per day."""
    from datetime import date, timedelta

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


def create_app(library: Path = LIBRARY, jobs: Jobs | None = None) -> FastAPI:
    app = FastAPI(title="tabstealth-api", docs_url=None, redoc_url=None)
    jobs = jobs or Jobs()
    lock = threading.Lock()

    def song(vid: str) -> dict:
        entry = read_index(library).get(vid)
        if not entry:
            raise HTTPException(404, "unknown song")
        return entry

    @app.get("/api/songs")
    def songs():
        idx = read_index(library)
        meta = read_meta(library)
        played = {x["video"]: x for x in practice_summary(read_practice(library))["songs"]}

        def to_review(vid: str, e: dict) -> int:
            checked = set(meta.get(vid, {}).get("checked", []))
            return sum(1 for r in read_review(library, e) if r["bar"] not in checked)

        out = []
        for vid, e in idx.items():
            m = meta.get(vid, {})
            p = played.get(vid, {})
            tab = e.get("kind", "tab") == "tab"
            out.append({"video": vid, "kind": "tab", **e, "edited": tab and is_edited(library / e["file"]),
                        "status": m.get("status", "new"), "tags": m.get("tags", []), "favourite": m.get("favourite", False),
                        "practised_seconds": p.get("seconds", 0), "last_practised": p.get("last"),
                        "to_review": to_review(vid, e)})
        return out

    # ── the collection: videos to keep (no tab to read) and PDFs ────────────────────

    def add_entry(key: str, entry: dict) -> dict:
        with lock:
            idx = read_index(library)
            if key in idx:
                raise HTTPException(409, "already in the library")
            idx[key] = {**entry, "converted": time.strftime("%Y-%m-%d")}
            library.mkdir(parents=True, exist_ok=True)
            (library / "index.json").write_text(json.dumps(idx, indent=2))
        return {"video": key, **idx[key]}

    @app.post("/api/library/video")
    def save_video(body: VideoIn):
        m = VIDEO_ID.search(body.url.strip())
        if not m:
            raise HTTPException(400, "not a YouTube link")
        vid = m.group(1) or m.group(2)
        title, artist = body.title, body.artist
        if not title:
            title, artist2 = split_title(youtube_title(vid) or vid)
            artist = artist or artist2
        return add_entry(vid, {"kind": "video", "title": title, "artist": artist or ""})

    @app.post("/api/library/pdf")
    async def upload_pdf(request: Request, title: str = "", artist: str = ""):
        data = await request.body()
        if len(data) > PDF_MAX:
            raise HTTPException(413, "PDF larger than 40 MB")
        if not data.startswith(b"%PDF"):
            raise HTTPException(400, "not a PDF")
        key = f"pdf-{uuid.uuid4().hex[:10]}"
        files = library / "files"
        files.mkdir(parents=True, exist_ok=True)
        (files / f"{key}.pdf").write_bytes(data)
        return add_entry(key, {"kind": "pdf", "file": f"files/{key}.pdf", "title": title.strip()[:200] or "PDF",
                               "artist": artist.strip()[:200]})

    @app.get("/api/songs/{vid}/pdf")
    def pdf(vid: str):
        e = song(vid)
        if e.get("kind") != "pdf":
            raise HTTPException(404, "not a PDF")
        return FileResponse(library / e["file"], media_type="application/pdf",
                            headers={"Content-Disposition": "inline"})

    @app.post("/api/songs/{vid}/convert")
    def convert_saved(vid: str):
        """A saved video turns out to have a tab after all: convert it (the tab replaces the saved video)."""
        if song(vid).get("kind") != "video":
            raise HTTPException(400, "only a saved video can be converted")
        return jobs.add(f"https://www.youtube.com/watch?v={vid}")

    @app.delete("/api/songs/{vid}")
    def remove(vid: str):
        """Take an item out of the library. Its files go to library/.trash, not away: a mistake can be undone."""
        e = song(vid)
        with lock:
            trash = library / ".trash" / f"{vid}-{time.strftime('%Y%m%d-%H%M%S')}"
            trash.mkdir(parents=True, exist_ok=True)
            names = [e.get(k) for k in ("file", "timing", "text", "review") if e.get(k)]
            if e.get("file", "").endswith(".gp5"):
                names.append(Path(e["file"]).stem + ".orig.gp5")
            for n in names:
                if (library / n).exists():
                    shutil.move(library / n, trash / Path(n).name)
            (trash / "entry.json").write_text(json.dumps({vid: e}, indent=2))
            idx = read_index(library)
            idx.pop(vid, None)
            (library / "index.json").write_text(json.dumps(idx, indent=2))
        return {"ok": True}

    @app.patch("/api/songs/{vid}")
    def patch_song(vid: str, body: SongPatch):
        song(vid)
        with lock:
            meta = read_meta(library)
            m = meta.setdefault(vid, {})
            if body.status is not None:
                m["status"] = body.status
            if body.tags is not None:
                m["tags"] = sorted({t.strip().lower()[:30] for t in body.tags if t.strip()})
            if body.favourite is not None:
                m["favourite"] = body.favourite
            (library / "meta.json").write_text(json.dumps(meta, indent=2))
        return m

    @app.get("/api/songs/{vid}/review")
    def review(vid: str):
        """The bars the converter was unsure about, with why, and whether you checked them."""
        checked = set(read_meta(library).get(vid, {}).get("checked", []))
        return [{**r, "checked": r["bar"] in checked} for r in read_review(library, song(vid))]

    @app.post("/api/songs/{vid}/review")
    def mark_review(vid: str, body: ReviewMark):
        song(vid)
        with lock:
            meta = read_meta(library)
            m = meta.setdefault(vid, {})
            checked = set(m.get("checked", []))
            (checked.add if body.checked else checked.discard)(body.bar)
            m["checked"] = sorted(checked)
            (library / "meta.json").write_text(json.dumps(meta, indent=2))
        return review(vid)

    @app.post("/api/practice")
    def log_practice(body: PracticeIn):
        song(body.video)
        with lock, open(library / "practice.jsonl", "a") as f:
            f.write(json.dumps(body.model_dump(mode="json")) + "\n")
        return {"ok": True}

    @app.get("/api/practice")
    def practice(today: str | None = None):
        return practice_summary(read_practice(library), today)

    @app.get("/api/songs/{vid}/tab")
    def tab(vid: str):
        return FileResponse(library / song(vid)["file"], media_type="application/octet-stream",
                            headers=NO_STORE)

    @app.get("/api/songs/{vid}/timing")
    def timing(vid: str):
        return json.loads((library / song(vid)["timing"]).read_text())

    @app.get("/api/songs/{vid}/text", response_class=PlainTextResponse)
    def text(vid: str):
        # from the .gp5 as it is now, so the text tab always has your edits
        return PlainTextResponse(gp5_to_ascii(str(library / song(vid)["file"])), headers=NO_STORE)

    @app.get("/api/songs/{vid}/beats/{bar}/{beat}")
    def get_beat(vid: str, bar: int, beat: int):
        return read_beat(library / song(vid)["file"], bar, beat)

    @app.post("/api/songs/{vid}/beats")
    def edit_beat(vid: str, edit: BeatEdit):
        apply_edit(library / song(vid)["file"], edit, lock)
        return {"ok": True}

    @app.post("/api/songs/{vid}/bars")
    def edit_bar(vid: str, edit: BarEdit):
        apply_bar(library / song(vid)["file"], edit, lock)
        return {"ok": True}

    @app.post("/api/songs/{vid}/restore")
    def restore(vid: str):
        """Back to the converter's version; undoable like any other change."""
        path = library / song(vid)["file"]
        backup = path.with_name(path.stem + ".orig.gp5")
        with lock:
            if is_edited(path):
                History(path).before_change()
                shutil.copy2(backup, path)
        return {"ok": True}

    @app.get("/api/songs/{vid}/history")
    def history(vid: str):
        h = History(library / song(vid)["file"])
        return {"undo": h.count("undo"), "redo": h.count("redo")}

    @app.post("/api/songs/{vid}/undo")
    def undo(vid: str):
        with lock:
            History(library / song(vid)["file"]).step("undo", "redo")
        return history(vid)

    @app.post("/api/songs/{vid}/redo")
    def redo(vid: str):
        with lock:
            History(library / song(vid)["file"]).step("redo", "undo")
        return history(vid)

    @app.post("/api/convert")
    def convert(body: ConvertIn):
        url = body.url.strip()
        if not YT_URL.match(url):
            raise HTTPException(400, "not a YouTube link")
        return jobs.add(url)

    @app.get("/api/jobs")
    def list_jobs():
        return [{**j, "log": j["log"][-8:]} for j in sorted(jobs.items.values(), key=lambda j: -j["id"])]

    return app
