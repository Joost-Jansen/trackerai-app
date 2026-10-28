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
from pydantic import BaseModel, Field

from tabreader.cli import LIBRARY

HERE = Path(__file__).resolve().parent
YT_URL = re.compile(r"^(https?://(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/\S+|[\w-]{11})$")
NO_STORE = {"Cache-Control": "no-store"}  # an edited tab must reload, not come from cache


class ConvertIn(BaseModel):
    url: str = Field(max_length=500)


class BeatEdit(BaseModel):
    bar: int = Field(ge=0)
    beat: int = Field(ge=0)
    # string number (1 = high e) -> fret, "x" for a dead note, null to remove
    frets: dict[str, int | str | None]


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


def apply_edit(path: Path, edit: BeatEdit, lock: threading.Lock) -> None:
    """Set the notes of one beat in a .gp5; the converter's version is kept once as .orig.gp5."""
    backup = path.with_name(path.stem + ".orig.gp5")
    with lock:
        if not backup.exists():
            shutil.copy2(path, backup)
        song = gp.parse(str(path))
        measures = song.tracks[0].measures
        if edit.bar >= len(measures) or edit.beat >= len(measures[edit.bar].voices[0].beats):
            raise HTTPException(404, "no such beat")
        beat = measures[edit.bar].voices[0].beats[edit.beat]
        existing = {n.string: n for n in beat.notes}
        notes = []
        for s in range(1, 7):
            v = edit.frets.get(str(s))
            if v is None or v == "":
                continue
            n = existing.get(s) or gp.Note(beat, string=s)
            if s not in existing:
                n.effect.letRing = True
            if str(v).lower() == "x":
                n.value, n.type = 0, gp.NoteType.dead
            else:
                fret = int(v)
                if not 0 <= fret <= 24:
                    raise HTTPException(400, "fret must be 0-24")
                n.value, n.type = fret, gp.NoteType.normal
            notes.append(n)
        beat.notes = notes
        beat.status = gp.BeatStatus.normal if notes else gp.BeatStatus.rest
        gp.write(song, str(path), version=(5, 1, 0))


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
        return (library / song(vid)["text"]).read_text()

    @app.post("/api/songs/{vid}/beats")
    def edit_beat(vid: str, edit: BeatEdit):
        apply_edit(library / song(vid)["file"], edit, lock)
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
