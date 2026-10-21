"""
Where an uploaded file waits while it is imported (S1, S2, S3).

  * **Size**: copied to the user's upload folder in chunks, at most
    MAX_UPLOAD_MB; a larger file is refused (413, code "upload_too_large")
    and nothing of it is kept.
  * **Zip bombs**: an .xlsx is a zip of XML. Before pandas/openpyxl opens one,
    `check_spreadsheet` counts its members and what they really unpack to;
    openpyxl parses the XML with defusedxml (in the requirements), so entity
    tricks are refused too.
  * **Retention**: nothing in the app reads an imported file again; only the
    moment of the last import is shown. So once a file is imported it is
    deleted (UPLOAD_RETENTION_DAYS=0, the default) or kept that many days, and
    the moment is stored in the settings (`last_import`).
"""

import os
import sqlite3
import time
import zipfile
from datetime import datetime

from fastapi import UploadFile, status

from app.core import config
from app.core.errors import CodedError
from domain import database
from domain.i18n import tr
from trackerai_websec import uploads as guard

LAST_IMPORT_KEY = "last_import"
# An .xlsx export of a few thousand rows has a few dozen parts and unpacks to a
# few MB; these leave a wide margin and stop a bomb long before memory does.
XLSX_MAX_MEMBERS = 1000
XLSX_MAX_UNPACKED = 200 * 1024 * 1024
XLSX_MAX_RATIO = 100


def safe_name(raw: str | None, default: str) -> str:
    # The browser picks this string and it is joined onto the user's upload
    # dir, so "../../foo" must not escape it. Keep the last path segment only,
    # normalising Windows separators first since basename() ignores those on
    # POSIX. Names iOS hands over can also be odd ("Transactions.xlsx 2").
    name = os.path.basename((raw or "").replace("\\", "/")).strip().replace("\x00", "")
    return name if name not in ("", ".", "..") else default


def receive(username: str, upload: UploadFile, default_name: str) -> str:
    """Store the upload in the user's folder; returns the path."""
    name = safe_name(upload.filename, default_name)
    dest = os.path.join(database.user_upload_dir(username), name)
    limit = config.MAX_UPLOAD_MB * 1024 * 1024
    try:
        guard.save_upload(upload, dest, limit)
    except guard.UploadTooLarge as e:
        raise CodedError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "upload_too_large",
            tr("'{0}' is larger than {1} MB.", name, config.MAX_UPLOAD_MB),
            {"max_mb": config.MAX_UPLOAD_MB},
        ) from e
    return dest


def check_spreadsheet(path: str) -> None:
    """Refuse a zip (xlsx) that would unpack to far more than any export does."""
    try:
        if zipfile.is_zipfile(path):  # a CSV is not a zip: nothing to check
            guard.check_zip(path, XLSX_MAX_MEMBERS, XLSX_MAX_UNPACKED, XLSX_MAX_RATIO, verify=True)
    except guard.ZipRejected as e:
        raise CodedError(
            422,
            "upload_rejected",
            tr("'{0}' can't be opened safely: it doesn't look like a normal export.", os.path.basename(path)),
        ) from e


def done(conn: sqlite3.Connection, username: str, path: str | None) -> None:
    """The file was imported: remember when, and let it go per the retention."""
    database.save_setting(conn, LAST_IMPORT_KEY, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if path and config.UPLOAD_RETENTION_DAYS == 0:
        discard(path)
    purge(username)


def discard(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def purge(username: str, keep_days: int | None = None) -> int:
    """Delete stored uploads older than the retention. Returns how many."""
    keep_days = config.UPLOAD_RETENTION_DAYS if keep_days is None else keep_days
    folder = database.user_upload_dir(username)
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and (keep_days == 0 or os.path.getmtime(path) < cutoff):
            discard(path)
            removed += 1
    return removed


def last_import(conn: sqlite3.Connection, username: str) -> str | None:
    """When something was last imported. Falls back to the newest stored file,
    for imports from before the moment was recorded."""
    stored = database.load_setting(conn, LAST_IMPORT_KEY)
    folder = database.user_upload_dir(username)
    mtimes = [os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))]
    from_files = datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M:%S") if mtimes else None
    candidates = [v for v in (stored, from_files) if v]
    return max(candidates) if candidates else None
