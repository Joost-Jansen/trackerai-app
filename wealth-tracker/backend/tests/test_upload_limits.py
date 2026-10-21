"""S1-S3: upload size limits, the zip-bomb guard and upload retention."""

import io
import os
import zipfile

from app.core import config
from domain import database
from tests.test_bank_upload import PAY


def _login(client):
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"}).status_code == 200


def _uploads():
    return os.listdir(database.user_upload_dir("alice"))


def test_a_file_over_the_limit_is_refused_and_not_kept(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    big = b"x" * (1024 * 1024 + 10)
    r = client.post(
        "/api/uploads/transactions", files=[("files", ("big.xlsx", big, "application/octet-stream"))], headers={"X-Locale": "en"}
    )
    assert r.status_code == 413
    assert r.json()["code"] == "upload_too_large"
    assert "1 MB" in r.json()["detail"]
    assert _uploads() == []
    # Dutch too.
    r = client.post("/api/accounts/import", files={"file": ("big.csv", big, "text/csv")}, headers={"X-Locale": "nl"})
    assert r.status_code == 413 and "groter dan 1 MB" in r.json()["detail"]
    # Several bank files: the large one is reported, the others still import.
    r = client.post("/api/uploads/bank", files=[("files", ("big.csv", big, "text/csv")), ("files", ("pay.csv", PAY, "text/csv"))])
    assert r.status_code == 200
    by_file = {x["file"]: x for x in r.json()["results"]}
    assert by_file["big.csv"]["code"] == "upload_too_large"
    assert by_file["pay.csv"]["saved"] == 3


def test_the_request_body_is_limited_before_parsing(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(config, "MAX_UPLOAD_REQUEST_MB", 1)
    r = client.post("/api/uploads/bank", files=[("files", ("a.csv", b"x" * (3 * 1024 * 1024), "text/csv"))])
    assert r.status_code == 413 and r.json()["code"] == "upload_too_large"
    monkeypatch.setattr(config, "MAX_BODY_MB", 1)
    r = client.post(
        "/api/feedback",
        content=b'{"kind":"bug","message":"' + b"a" * (2 * 1024 * 1024) + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_a_chunked_body_without_length_is_counted(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(config, "MAX_BODY_MB", 1)

    def chunks():
        for _ in range(3):
            yield b"a" * (600 * 1024)

    r = client.post("/api/feedback", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def _bomb() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/worksheets/sheet1.xml", b"<a>" + b" " * (40 * 1024 * 1024) + b"</a>")
    return buf.getvalue()


def test_an_xlsx_zip_bomb_is_refused_before_parsing(client, monkeypatch):
    import pandas as pd

    _login(client)
    called = []
    monkeypatch.setattr(pd, "read_excel", lambda *a, **k: called.append(1))
    data = _bomb()
    assert len(data) < 200_000  # small on the wire
    r = client.post("/api/uploads/transactions", files=[("files", ("Transactions.xlsx", data, "application/octet-stream"))])
    assert r.status_code == 422 and r.json()["code"] == "upload_rejected"
    assert called == [] and _uploads() == []


def test_defused_xml_is_active_for_openpyxl():
    import openpyxl.xml

    assert openpyxl.xml.DEFUSEDXML


def test_an_imported_file_is_not_kept_but_the_moment_is(client):
    _login(client)
    r = client.post("/api/accounts/import", files={"file": ("pay.csv", PAY, "text/csv")})
    assert r.status_code == 200, r.text
    assert _uploads() == []
    assert client.get("/api/prices/status").json()["last_import"]


def test_retention_keeps_files_for_n_days(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(config, "UPLOAD_RETENTION_DAYS", 30)
    old = os.path.join(database.user_upload_dir("alice"), "old.csv")
    with open(old, "wb") as f:
        f.write(b"x")
    os.utime(old, (0, 0))  # 1970
    r = client.post("/api/uploads/bank", files=[("files", ("pay.csv", PAY, "text/csv"))])
    assert r.status_code == 200
    assert _uploads() == ["pay.csv"]
