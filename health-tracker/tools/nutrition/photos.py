"""Meal photos: checked, stripped of metadata, stored per user and deleted when their time is up.

The phone already sends a re-encoded JPEG without EXIF (web: components/nutrition/photo.ts); the server strips it again
so a location never reaches the database whatever sent the file: JPEG APP1 (EXIF, XMP), APP13 (IPTC) and comments,
PNG text, time and eXIf chunks. Pixels are not touched, so no image library is needed.

Keeping (the user's setting `photos`): "30d" (default) deletes a photo 30 days after it was taken, "keep" never, and
"never" stores none at all (the analysis still sees it, the meal has no photo). A photo is pending until a saved meal
claims it (`attach`): one whose review was cancelled is deleted after PENDING_HOURS. Deleting a meal deletes its photo.
"""

from __future__ import annotations

import struct
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select

from tools import db

MAX_BYTES = 8 * 1024 * 1024
KEEP_DAYS = {"30d": 30, "keep": None}
PENDING_HOURS = 24
JPEG, PNG = b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n"
JPEG_DROP = {0xE1, 0xED, 0xFE}  # APP1 (EXIF, XMP), APP13 (IPTC), COM
PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs", b"bKGD"}


class PhotoError(ValueError):
    pass


def kind(data: bytes) -> str | None:
    if data.startswith(JPEG):
        return "image/jpeg"
    if data.startswith(PNG):
        return "image/png"
    return None


def _strip_jpeg(data: bytes) -> bytes:
    out, i = bytearray(data[:2]), 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise PhotoError("not a valid JPEG")
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker == 0xDA:  # start of scan: the image data and everything after it stay as they are
            out += data[i:]
            return bytes(out)
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        (length,) = struct.unpack(">H", data[i + 2:i + 4])
        if length < 2 or i + 2 + length > len(data):
            raise PhotoError("not a valid JPEG")
        if marker not in JPEG_DROP:
            out += data[i:i + 2 + length]
        i += 2 + length
    raise PhotoError("not a valid JPEG")


def _strip_png(data: bytes) -> bytes:
    out, i = bytearray(PNG), len(PNG)
    while i + 12 <= len(data):
        (length,) = struct.unpack(">I", data[i:i + 4])
        name = data[i + 4:i + 8]
        end = i + 12 + length
        if end > len(data):
            raise PhotoError("not a valid PNG")
        if name in PNG_KEEP:
            out += data[i:end]
        i = end
        if name == b"IEND":
            return bytes(out)
    raise PhotoError("not a valid PNG")


def clean(data: bytes) -> tuple[str, bytes]:
    """(mime, the image without metadata); PhotoError for anything that is not a JPEG or PNG."""
    if not data:
        raise PhotoError("empty file")
    if len(data) > MAX_BYTES:
        raise PhotoError("too large")
    mime = kind(data)
    if mime is None:
        raise PhotoError("not a JPEG or PNG")
    return mime, (_strip_jpeg(data) if mime == "image/jpeg" else _strip_png(data))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry(created: datetime, keep: str) -> datetime | None:
    days = KEEP_DAYS.get(keep, 30)
    return created + timedelta(days=days) if days else None


def save(s: db.Scope, mime: str, data: bytes, keep: str = "30d") -> int | None:
    """Store a cleaned photo, pending until a meal claims it; None when the user keeps no photos."""
    if keep == "never":
        return None
    now = _now()
    with s.engine.begin() as conn:
        return conn.execute(insert(db.meal_photos).values(user_id=s.user_id, mime=mime, data=data, created_at=now,
                                                          expires_at=now + timedelta(hours=PENDING_HOURS))).inserted_primary_key[0]


def attach(s: db.Scope, photo_id: int, keep: str) -> None:
    """A saved meal claims the photo: from now on it is kept by the user's setting."""
    with s.engine.begin() as conn:
        created = conn.execute(select(db.meal_photos.c.created_at).where(db.meal_photos.c.user_id == s.user_id, db.meal_photos.c.id == photo_id)).scalar_one_or_none()
        if created is not None:
            conn.execute(db.meal_photos.update().where(db.meal_photos.c.id == photo_id).values(expires_at=_expiry(created, keep)))


def load(s: db.Scope, photo_id: int) -> tuple[str, bytes] | None:
    with s.engine.connect() as conn:
        row = conn.execute(select(db.meal_photos.c.mime, db.meal_photos.c.data, db.meal_photos.c.expires_at)
                           .where(db.meal_photos.c.user_id == s.user_id, db.meal_photos.c.id == photo_id)).first()
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at < _now():
        return None
    return row.mime, bytes(row.data)


def owns(s: db.Scope, photo_id: int) -> bool:
    with s.engine.connect() as conn:
        return conn.execute(select(db.meal_photos.c.id).where(db.meal_photos.c.user_id == s.user_id, db.meal_photos.c.id == photo_id)).first() is not None


def purge_expired(engine, now: datetime | None = None) -> int:
    """Delete every photo past its time (all users); the meals keep everything else."""
    now = now or _now()
    with engine.begin() as conn:
        ids = [i for (i,) in conn.execute(select(db.meal_photos.c.id).where(db.meal_photos.c.expires_at.isnot(None),
                                                                              db.meal_photos.c.expires_at < now))]
        if not ids:
            return 0
        conn.execute(delete(db.meal_photos).where(db.meal_photos.c.id.in_(ids)))
        conn.execute(db.meals.update().where(db.meals.c.photo_id.in_(ids)).values(photo_id=None))
    return len(ids)


def retention_changed(s: db.Scope, keep: str) -> None:
    """The user changed how long photos are kept: "never" deletes theirs now, the others re-date the stored ones."""
    with s.engine.begin() as conn:
        if keep == "never":
            ids = [i for (i,) in conn.execute(select(db.meal_photos.c.id).where(db.meal_photos.c.user_id == s.user_id))]
            if ids:
                conn.execute(delete(db.meal_photos).where(db.meal_photos.c.user_id == s.user_id))
                conn.execute(db.meals.update().where(db.meals.c.user_id == s.user_id, db.meals.c.photo_id.in_(ids)).values(photo_id=None))
            return
        claimed = select(db.meals.c.photo_id).where(db.meals.c.user_id == s.user_id, db.meals.c.photo_id.isnot(None))
        for pid, created in conn.execute(select(db.meal_photos.c.id, db.meal_photos.c.created_at)
                                         .where(db.meal_photos.c.user_id == s.user_id, db.meal_photos.c.id.in_(claimed))).all():
            conn.execute(db.meal_photos.update().where(db.meal_photos.c.id == pid).values(expires_at=_expiry(created, keep)))
