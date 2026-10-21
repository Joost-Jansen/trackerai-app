"""Uploads without surprises: a byte limit while the body streams in (never read whole, then measured), a body limit
for every request, and a check of a zip before anything is unpacked (zip bombs, path traversal).

    size = await stream_to_file(request.stream(), path, max_bytes)      # raises UploadTooLarge
    size = save_upload(upload_file, path, max_bytes)                     # the same for a (sync) UploadFile
    check_zip(path, max_members=10_000, max_total_uncompressed=2 * 1024**3, max_ratio=200)   # raises ZipRejected

`BodyLimitMiddleware` refuses a request whose body is larger than its path allows (413), by Content-Length before
anything is read and by counting for a chunked body.
"""

from __future__ import annotations

import json
import os
import posixpath
import zipfile
from collections.abc import AsyncIterator, Iterable
from typing import BinaryIO

CHUNK = 1024 * 1024


class UploadTooLarge(Exception):
    """The upload is larger than allowed; `max_bytes` (also `limit`) is the limit in bytes."""

    code = "upload_too_large"

    def __init__(self, max_bytes: int):
        super().__init__(f"upload larger than {max_bytes} bytes")
        self.max_bytes = self.limit = max_bytes


class ZipRejected(ValueError):
    """A zip that is not unpacked: unreadable, too many members, too large unpacked, a suspicious ratio or an unsafe
    name."""

    code = "upload_rejected"


async def stream_to_file(chunks: AsyncIterator[bytes], path: str | os.PathLike, max_bytes: int, mode: str = "wb") -> int:
    """Write the chunks to `path` (mode "ab" appends); stop with UploadTooLarge once more than `max_bytes` came in.
    Returns the number of bytes written. The caller removes the file on an error."""
    size = 0
    with open(path, mode) as f:
        async for chunk in chunks:
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise UploadTooLarge(max_bytes)
            f.write(chunk)
    return size


async def read_limited(chunks: AsyncIterator[bytes], max_bytes: int) -> bytes:
    """The whole body in memory, for small uploads only, with the same limit while reading."""
    parts, size = [], 0
    async for chunk in chunks:
        size += len(chunk)
        if size > max_bytes:
            raise UploadTooLarge(max_bytes)
        parts.append(chunk)
    return b"".join(parts)


def save_upload(upload, dest: str | os.PathLike, max_bytes: int) -> int:
    """Copy `upload` (a Starlette UploadFile, or any object with `.file` or `.read`) to `dest`, at most `max_bytes`.
    Returns the number of bytes. On any error the partial file is removed."""
    src = getattr(upload, "file", upload)
    written = 0
    try:
        with open(dest, "wb") as out:
            while chunk := src.read(CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLarge(max_bytes)
                out.write(chunk)
    except BaseException:
        try:
            os.remove(dest)
        except OSError:
            pass
        raise
    return written


def safe_member_name(name: str) -> bool:
    """No absolute paths, no drive letters, no `..`: a name that stays inside the folder it would be unpacked to."""
    if not name or "\x00" in name:
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/") or (len(norm) > 1 and norm[1] == ":"):
        return False
    return ".." not in posixpath.normpath(norm).split("/")


def check_zip(
    source: str | os.PathLike | BinaryIO,
    max_members: int = 10_000,
    max_total_uncompressed: int = 1024**3,
    max_ratio: float = 200,
    max_member: int | None = None,
    verify: bool = False,
) -> list[zipfile.ZipInfo]:
    """Refuse (ZipRejected) a zip that would unpack to too much, before unpacking it. Returns the members.

    The ratio is checked per member that unpacks to more than 1 MB (small files compress wildly without being
    dangerous) and for the whole archive. Python's zipfile never writes more than a member's declared size, so the
    declared sizes bound the real work; `verify=True` also streams every member once and counts what really comes
    out (for small archives such as .xlsx files)."""
    try:
        with zipfile.ZipFile(source) as z:
            infos = z.infolist()
            _check_infos(infos, max_members, max_total_uncompressed, max_ratio, max_member)
            if verify:
                _verify(z, infos, max_total_uncompressed)
    except ZipRejected:
        raise
    except Exception as err:  # noqa: BLE001 - BadZipFile, zlib.error, EOFError, OSError, encrypted members, ...
        raise ZipRejected(f"not a readable zip: {err}") from err
    finally:
        if hasattr(source, "seek"):
            source.seek(0)
    return infos


def _check_infos(infos, max_members: int, max_total_uncompressed: int, max_ratio: float, max_member: int | None) -> None:
    if len(infos) > max_members:
        raise ZipRejected(f"more than {max_members} files in the zip")
    total = compressed = 0
    for info in infos:
        if not safe_member_name(info.filename):
            raise ZipRejected(f"unsafe name in the zip: {info.filename!r}")
        if info.flag_bits & 0x1:
            raise ZipRejected("encrypted zip")
        if max_member is not None and info.file_size > max_member:
            raise ZipRejected(f"{info.filename} unpacks to more than {max_member} bytes")
        if info.file_size > 1024 * 1024 and info.file_size > max_ratio * max(info.compress_size, 1):
            raise ZipRejected(f"{info.filename} is compressed suspiciously well")
        total += info.file_size
        compressed += info.compress_size
        if total > max_total_uncompressed:
            raise ZipRejected(f"the zip unpacks to more than {max_total_uncompressed} bytes")
    if total > 1024 * 1024 and total > max_ratio * max(compressed, 1):
        raise ZipRejected("the zip is compressed suspiciously well")


def _verify(z: zipfile.ZipFile, infos, max_total_uncompressed: int) -> None:
    """The sizes in the archive can lie: stream every member and stop as soon as it gives more than it declared."""
    produced = 0
    for info in infos:
        seen = 0
        with z.open(info) as member:
            while chunk := member.read(CHUNK):
                seen += len(chunk)
                produced += len(chunk)
                if seen > info.file_size or produced > max_total_uncompressed:
                    raise ZipRejected(f"{info.filename!r} unpacks beyond its declared size")


class BodyLimitMiddleware:
    """413 for a request body over the limit of its path: `limits` maps path prefixes to bytes (longest prefix wins),
    `default` covers the rest (None: no limit)."""

    def __init__(self, app, default: int | None, limits: dict[str, int] | Iterable[tuple[str, int]] = ()):
        self.app = app
        self.default = default
        items = limits.items() if isinstance(limits, dict) else limits
        self.limits = sorted(items, key=lambda kv: -len(kv[0]))

    def limit_for(self, path: str) -> int | None:
        for prefix, limit in self.limits:
            if path.startswith(prefix):
                return limit
        return self.default

    @staticmethod
    async def _refuse(send, limit: int) -> None:
        body = json.dumps(
            {
                "detail": f"request body larger than {limit // (1024 * 1024)} MB",
                "code": "upload_too_large",
                "params": {"max_mb": limit // (1024 * 1024)},
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit_for(scope.get("path", ""))
        if limit is None:
            return await self.app(scope, receive, send)
        for k, v in scope.get("headers") or []:
            if k.lower() == b"content-length":
                try:
                    if int(v) > limit:
                        return await self._refuse(send, limit)
                except ValueError:
                    return await self._refuse(send, limit)
        seen = 0
        started = False

        async def counted():
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise UploadTooLarge(limit)
            return message

        async def tracking_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, tracking_send)
        except UploadTooLarge:
            if not started:
                await self._refuse(send, limit)
