"""tabstealth-api: the song library, YouTube conversions and tab edits behind tabstealth-web.

  uvicorn app:create_app --factory --port 8770

Local-first: no accounts yet, so it binds to 127.0.0.1 and is not meant to be exposed (see README).
"""
import itertools
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import guitarpro as gp
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from typing import Literal

from pydantic import BaseModel, Field

from tabreader.ascii import gp5_to_ascii
from tabreader.cli import LIBRARY

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
    grace: GraceIn | None = None  # a grace note just before the beat


class BeatEdit(BaseModel):
    bar: int = Field(ge=0)
    beat: int = Field(ge=0)  # index among the bar's beats, grace notes not counted
    # string number (1 = high e) -> the note on it; a string that is not listed has no note
    notes: dict[Literal["1", "2", "3", "4", "5", "6"], NoteIn] = {}
    stroke: Literal["down", "up", "arpeggio"] | None = None
    chord: str | None = Field(default=None, max_length=40)


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


def _edit_gp5(path: Path, lock: threading.Lock, change) -> None:
    """Change a .gp5 in place; the converter's version is kept once as .orig.gp5."""
    backup = path.with_name(path.stem + ".orig.gp5")
    with lock:
        song = gp.parse(str(path))
        change(song)  # raises on a bad edit, before anything is written
        if not backup.exists():
            shutil.copy2(path, backup)
        gp.write(song, str(path), version=(5, 1, 0))


def apply_edit(path: Path, edit: BeatEdit, lock: threading.Lock) -> None:
    """Set one beat: its notes with their techniques, the strum and the chord name.

    Built on the existing notes, so what this form does not show (a bend, a trill) stays as it was.
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
        return [{"video": vid, **e, "edited": (library / e["file"]).with_name(
            Path(e["file"]).stem + ".orig.gp5").exists()} for vid, e in idx.items()]

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
        path = library / song(vid)["file"]
        backup = path.with_name(path.stem + ".orig.gp5")
        if backup.exists():
            shutil.move(backup, path)
        return {"ok": True}

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
