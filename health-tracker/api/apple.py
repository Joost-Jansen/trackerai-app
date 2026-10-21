"""Apple Health import: the export.zip from the Health app on an iPhone (tools/apple_health.py, tools/apple_import.py).

The site uploads in parts, because Cloudflare (free plan) refuses a request body over 100 MB and real exports are
often bigger:

    POST   /api/apple/upload                    {name, size} -> 201 {upload_id, chunk_size, max_bytes}
    PUT    /api/apple/upload/{id}/{index}       part `index` (0-based) as the raw body, exactly chunk_size bytes
                                                (the last one the rest) -> {received, size}; parts go in order, the
                                                last part again is fine (a retry after a lost answer)
    POST   /api/apple/upload/{id}/finish        all parts in: checked, then read in the background -> 202 (as below)
    DELETE /api/apple/upload/{id}               give up: the parts are removed

    POST   /api/apple/import?name=export.zip    the whole file as the raw body in one request (scripts, small files)
    GET    /api/apple/import                    {running, progress: {step, done, total} | null, last: summary | null}
    DELETE /api/apple/import                    remove everything the import gave

An upload belongs to the user who started it (its id is random and checked against the caller); one upload and one
import per user at a time; an upload left alone for APPLE_UPLOAD_TTL_MIN (60) minutes is removed. An export is often
hundreds of megabytes and takes a minute or more to read, longer than a request should wait, so the page polls GET
for the progress. The temporary file is removed when the import is done.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.errors import ApiError
from tools import db
from tools.apple_health import NotAnExport
from tools.apple_import import import_file, remove
from trackerai_websec.uploads import UploadTooLarge, ZipRejected, check_zip, stream_to_file

KEY = "apple_import"  # settings: the last import's summary, or its error
# Years of Watch data zip to a few hundred MB, rarely more than 1-2 GB; one user must not be able to fill the disk.
MAX_BYTES = int(os.environ.get("APPLE_IMPORT_MAX_MB") or 2048) * 1024 * 1024
# Parts of the chunked upload: Cloudflare's free plan refuses request bodies over 100 MB.
CHUNK_BYTES = int(float(os.environ.get("APPLE_CHUNK_MB") or 32) * 1024 * 1024)
UPLOAD_TTL_S = int(os.environ.get("APPLE_UPLOAD_TTL_MIN") or 60) * 60
# A zip is checked before it is read (api/websec/uploads.py): export.xml compresses 10-30 times, a zip bomb thousands.
MAX_UNZIPPED = 40 * MAX_BYTES
MAX_MEMBERS = 200_000  # one GPX per workout with a route, ECGs, ...
MAX_RATIO = 300


@dataclass
class Upload:
    """A chunked upload under way: the parts so far in one temporary file, in order."""

    id: str
    user_id: int
    name: str
    size: int
    path: str
    chunk_size: int
    received: int = 0
    touched: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class UploadStart(BaseModel):
    name: str = Field("export.zip", max_length=200)
    size: int


def check_export(path: str) -> None:
    """Refused before the background work: neither a zip nor XML, or a zip that would unpack to too much."""
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"PK"):
        try:
            check_zip(path, max_members=MAX_MEMBERS, max_total_uncompressed=MAX_UNZIPPED, max_ratio=MAX_RATIO)
        except ZipRejected as err:
            raise ApiError(422, "not_an_export") from err
        return
    if not (head.lstrip().startswith(b"<?xml") or head.lstrip().startswith(b"<HealthData")):
        raise ApiError(422, "not_an_export")


class AppleImports:
    """The running imports, per user: progress in memory, the result in the user's settings."""

    def __init__(
        self,
        stores=None,
        on_done: Callable[[], None] | None = None,
        upload_dir: str | os.PathLike | None = None,
        chunk_size: int = CHUNK_BYTES,
        max_bytes: int = MAX_BYTES,
        ttl_s: float = UPLOAD_TTL_S,
    ):
        self.stores = stores
        self.on_done = on_done  # e.g. clear the trends cache: its key does not see an import
        self.running: dict[int, dict | None] = {}
        self._guard = threading.Lock()
        self.uploads: dict[str, Upload] = {}
        self.dir = Path(upload_dir or os.environ.get("APPLE_UPLOAD_DIR") or Path(tempfile.gettempdir()) / "health-tracker-uploads")
        self.chunk_size, self.max_bytes, self.ttl_s = chunk_size, max_bytes, ttl_s
        self._sweep_files()

    # --- chunked uploads --------------------------------------------------------------------------------------

    def _sweep_files(self) -> None:
        """Parts left behind by a restart (the uploads in memory are gone with it)."""
        try:
            for f in self.dir.glob("apple-*.part"):
                if time.time() - f.stat().st_mtime > self.ttl_s:
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def sweep(self) -> None:
        """Remove uploads nobody touched for `ttl_s`."""
        now = time.monotonic()
        with self._guard:
            stale = [u for u in self.uploads.values() if now - u.touched > self.ttl_s]
            for u in stale:
                self.uploads.pop(u.id, None)
        for u in stale:
            Path(u.path).unlink(missing_ok=True)

    def new_upload(self, user_id: int, name: str, size: int) -> Upload:
        """A new upload for the user; an earlier unfinished one of theirs is dropped (one at a time)."""
        self.sweep()
        self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        upload_id = secrets.token_urlsafe(18)
        fd, path = tempfile.mkstemp(prefix="apple-", suffix=".part", dir=self.dir)
        os.close(fd)
        upload = Upload(upload_id, user_id, name, size, path, self.chunk_size)
        with self._guard:
            old = [u for u in self.uploads.values() if u.user_id == user_id]
            for u in old:
                self.uploads.pop(u.id, None)
            self.uploads[upload_id] = upload
        for u in old:
            Path(u.path).unlink(missing_ok=True)
        return upload

    def get_upload(self, upload_id: str, user_id: int) -> Upload:
        """The caller's own upload, or 404 (also for someone else's id: no telling which ids exist)."""
        self.sweep()
        upload = self.uploads.get(upload_id)
        if upload is None or upload.user_id != user_id:
            raise ApiError(404, "upload_not_found")
        upload.touched = time.monotonic()
        return upload

    def drop_upload(self, upload: Upload, keep_file: bool = False) -> None:
        with self._guard:
            self.uploads.pop(upload.id, None)
        if not keep_file:
            Path(upload.path).unlink(missing_ok=True)

    def start(self, user_id: int, scope: db.Scope, path: str, name: str) -> bool:
        with self._guard:
            if user_id in self.running:
                return False
            self.running[user_id] = None
        threading.Thread(target=self._run, args=(user_id, scope, path, name), name=f"apple-{user_id}", daemon=True).start()
        return True

    @staticmethod
    def _failed(scope: db.Scope, error: str, detail: str | None = None) -> None:
        """Record the failure for the page; the previous import's numbers stay (that data is still there)."""
        try:
            last = db.get_setting(scope, KEY) or {}
            db.set_setting(
                scope,
                KEY,
                {
                    **last,
                    "status": "failed",
                    "error": error,
                    "detail": (detail or "")[:200],
                    "failed_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
        except Exception as err:  # noqa: BLE001  the database itself is the problem: the log is all there is
            print(f"apple import: could not record the failure ({type(err).__name__}: {err})", flush=True)

    def _run(self, user_id: int, scope: db.Scope, path: str, name: str) -> None:
        def progress(step: str, done: int | None = None, total: int | None = None) -> None:
            self.running[user_id] = {"step": step, "done": done, "total": total}

        try:
            summary = import_file(scope, path, name, progress)
            db.set_setting(scope, KEY, {"status": "done", "file": name, **summary})
        except NotAnExport as err:
            self._failed(scope, "not_an_export", str(err))
        except Exception as err:  # noqa: BLE001  the thread must not die silently: the page shows the failure
            print(f"apple import {user_id}: MISLUKT ({type(err).__name__}: {err})", flush=True)
            self._failed(scope, "import_failed")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
            if self.stores is not None:
                self.stores.get(user_id).invalidate()
            if self.on_done:
                self.on_done()
            with self._guard:
                self.running.pop(user_id, None)


def make_router(current_user: Callable, imports: AppleImports) -> APIRouter:
    r = APIRouter(prefix="/api/apple")

    def state(u) -> dict:
        last = db.get_setting(u.scope, KEY)
        return {"running": u.id in imports.running, "progress": imports.running.get(u.id), "last": last if isinstance(last, dict) else None}

    @r.get("/import")
    def get_import(u=Depends(current_user)):
        return state(u)

    def too_large() -> ApiError:
        return ApiError(413, "upload_too_large", max_mb=imports.max_bytes // (1024 * 1024))

    def begin(u, path: str, name: str) -> JSONResponse:
        """The file is complete: check it, then read it in the background (the import owns the file from here)."""
        if not imports.start(u.id, u.scope, path, name):
            os.unlink(path)
            raise ApiError(409, "apple_import_running")
        return JSONResponse(state(u), status_code=202)

    @r.post("/import")
    async def post_import(request: Request, name: str = Query("export.zip", max_length=200), u=Depends(current_user)):
        if u.id in imports.running:
            raise ApiError(409, "apple_import_running")
        imports.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, path = tempfile.mkstemp(prefix="apple-", suffix=".upload", dir=imports.dir)
        os.close(fd)
        try:
            try:
                size = await stream_to_file(request.stream(), path, imports.max_bytes)
            except UploadTooLarge:
                raise too_large()
            if not size:
                raise ApiError(400, "upload_empty")
            await run_in_threadpool(check_export, path)
        except BaseException:
            os.unlink(path)
            raise
        return begin(u, path, name)

    @r.post("/upload", status_code=201)
    def start_upload(body: UploadStart, u=Depends(current_user)):
        if u.id in imports.running:
            raise ApiError(409, "apple_import_running")
        if body.size <= 0:
            raise ApiError(400, "upload_empty")
        if body.size > imports.max_bytes:
            raise too_large()
        up = imports.new_upload(u.id, body.name.strip() or "export.zip", body.size)
        return {"upload_id": up.id, "chunk_size": up.chunk_size, "max_bytes": imports.max_bytes, "size": up.size}

    @r.put("/upload/{upload_id}/{index}")
    async def put_chunk(upload_id: str, index: int, request: Request, u=Depends(current_user)):
        up = imports.get_upload(upload_id, u.id)
        async with up.lock:  # one part at a time per upload, in order
            offset = index * up.chunk_size
            next_index = up.received // up.chunk_size if up.received < up.size else -(-up.size // up.chunk_size)
            # the next part, or the last one again (its answer may have been lost on the way back)
            if index < 0 or offset >= up.size or index not in (next_index, next_index - 1):
                raise ApiError(409, "upload_out_of_order", expected=next_index)
            expected = min(up.chunk_size, up.size - offset)
            with open(up.path, "r+b") as f:
                f.truncate(offset)
            try:
                got = await stream_to_file(request.stream(), up.path, expected, mode="ab")
            except UploadTooLarge:
                got = -1
            if got != expected:
                with open(up.path, "r+b") as f:
                    f.truncate(offset)
                up.received = offset
                raise ApiError(422, "upload_size_mismatch", expected=expected)
            up.received = offset + got
            up.touched = time.monotonic()
            return {"received": up.received, "size": up.size}

    @r.post("/upload/{upload_id}/finish")
    async def finish_upload(upload_id: str, u=Depends(current_user)):
        up = imports.get_upload(upload_id, u.id)
        async with up.lock:
            if up.received != up.size:
                raise ApiError(409, "upload_incomplete", received=up.received, size=up.size)
            if u.id in imports.running:
                raise ApiError(409, "apple_import_running")
            try:
                await run_in_threadpool(check_export, up.path)
            except ApiError:
                imports.drop_upload(up)
                raise
            imports.drop_upload(up, keep_file=True)
            return begin(u, up.path, up.name)

    @r.delete("/upload/{upload_id}")
    def cancel_upload(upload_id: str, u=Depends(current_user)):
        imports.drop_upload(imports.get_upload(upload_id, u.id))
        return {"ok": True}

    @r.delete("/import")
    def delete_import(u=Depends(current_user)):
        if u.id in imports.running:
            raise ApiError(409, "apple_import_running")
        out = remove(u.scope)
        db.delete_setting(u.scope, KEY)
        u.store.invalidate()
        if imports.on_done:
            imports.on_done()
        return out

    return r
