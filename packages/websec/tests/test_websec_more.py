"""packages/websec on its own, continued: the cases wealth-tracker's copy was tested with."""

import io
import logging
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trackerai_websec import client_ip as cip
from trackerai_websec import csrf, headers, log_redact, uploads
from trackerai_websec.throttle import Limiter


# --- client_ip ---------------------------------------------------------------


def _req(peer, **hdrs):
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers={k.replace("_", "-"): v for k, v in hdrs.items()})


def test_trusted_networks_parses_ips_and_cidrs():
    nets = cip.trusted_networks(" 10.0.0.0/8, 172.18.0.5 ,::1")
    assert len(nets) == 3
    assert cip.trusted_networks("") == [] and cip.trusted_networks(None) == []
    with pytest.raises(ValueError):
        cip.trusted_networks("not-an-ip")


def test_headers_are_ignored_from_an_untrusted_peer():
    trusted = cip.trusted_networks("172.18.0.0/16")
    r = _req("203.0.113.9", cf_connecting_ip="1.2.3.4", x_forwarded_for="5.6.7.8")
    assert cip.client_ip(r, trusted) == "203.0.113.9"
    # No proxies configured: always the socket peer.
    assert cip.client_ip(_req("172.18.0.2", cf_connecting_ip="1.2.3.4"), []) == "172.18.0.2"


def test_cf_connecting_ip_from_a_trusted_peer():
    trusted = cip.trusted_networks("172.18.0.0/16")
    assert cip.client_ip(_req("172.18.0.2", cf_connecting_ip="1.2.3.4"), trusted) == "1.2.3.4"


def test_rightmost_untrusted_forwarded_hop():
    trusted = cip.trusted_networks("172.18.0.0/16,10.0.0.1")
    r = _req("172.18.0.2", x_forwarded_for="6.6.6.6, 9.9.9.9, 10.0.0.1")
    # 6.6.6.6 could be forged by the client; 9.9.9.9 is what our proxy saw.
    assert cip.client_ip(r, trusted) == "9.9.9.9"
    assert cip.client_ip(_req("172.18.0.2", x_forwarded_for="garbage"), trusted) == "172.18.0.2"
    assert cip.client_ip(_req("172.18.0.2"), trusted) == "172.18.0.2"


# --- throttle ----------------------------------------------------------------


def test_limiter_counts_per_key_and_resets():
    lim = Limiter(3, 60)
    assert [lim.hit("a") for _ in range(4)] == [True, True, True, False]
    assert lim.blocked("a") and not lim.blocked("b")
    assert lim.hit("b")
    lim.reset("a")
    assert not lim.blocked("a")


def test_limiter_window_slides():
    now = [1000.0]
    lim = Limiter(2, 10, clock=lambda: now[0])
    assert lim.hit("k") and lim.hit("k") and not lim.hit("k")
    now[0] += 10.5
    assert lim.hit("k")


def test_limiter_memory_is_bounded():
    lim = Limiter(1, 60, max_keys=100)
    for i in range(1000):
        lim.hit(f"k{i}")
    assert len(lim._events) == 100


# --- headers -----------------------------------------------------------------


def _app_with(*middleware):
    app = FastAPI()

    @app.get("/x")
    def x():
        return {"ok": True}

    @app.post("/x")
    def post_x():
        return {"ok": True}

    for cls, kwargs in middleware:
        app.add_middleware(cls, **kwargs)
    return app


def test_security_headers_on_every_response():
    c = TestClient(_app_with((headers.SecurityHeadersMiddleware, {"csp": "default-src 'none'", "hsts": True})))
    for r in (c.get("/x"), c.get("/missing")):
        h = r.headers
        assert h["content-security-policy"] == "default-src 'none'"
        assert h["x-frame-options"] == "DENY"
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "camera=()" in h["permissions-policy"]
        assert h["cross-origin-opener-policy"] == "same-origin"
        assert h["strict-transport-security"].startswith("max-age=")
    c2 = TestClient(_app_with((headers.SecurityHeadersMiddleware, {"csp": "x", "hsts": False})))
    assert "strict-transport-security" not in c2.get("/x").headers


# --- csrf --------------------------------------------------------------------


def _csrf_client(allowed=(), exempt=()):
    return TestClient(_app_with((csrf.OriginCheckMiddleware, {
        "allowed_origins": list(allowed), "cookie_name": "sess", "exempt_paths": exempt,
    })))


def test_csrf_refuses_foreign_origin_with_cookie():
    c = _csrf_client()
    c.cookies.set("sess", "abc")
    r = c.post("/x", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_origin"
    assert c.post("/x", headers={"Origin": "null"}).status_code == 403
    assert c.post("/x").status_code == 403  # neither Origin nor Referer


def test_csrf_allows_same_host_listed_origin_and_referer():
    c = _csrf_client(allowed=["https://stocks.example.org"])
    c.cookies.set("sess", "abc")
    assert c.post("/x", headers={"Origin": "http://testserver"}).status_code == 200
    assert c.post("/x", headers={"Origin": "https://stocks.example.org"}).status_code == 200
    assert c.post("/x", headers={"Origin": "https://STOCKS.example.org:443"}).status_code == 200
    assert c.post("/x", headers={"Referer": "http://testserver/accounts?x=1"}).status_code == 200
    assert c.post("/x", headers={"Origin": "https://health.example.org"}).status_code == 403


def test_csrf_exemptions():
    c = _csrf_client(exempt=["/x"])
    c.cookies.set("sess", "abc")
    assert c.post("/x", headers={"Origin": "https://evil.example"}).status_code == 200
    c = _csrf_client()
    # No session cookie: nothing to forge. Bearer: not a browser-forgeable request.
    assert c.post("/x", headers={"Origin": "https://evil.example"}).status_code == 200
    c.cookies.set("sess", "abc")
    assert c.post("/x", headers={"Origin": "https://evil.example", "Authorization": "Bearer t"}).status_code == 200
    assert c.get("/x", headers={"Origin": "https://evil.example"}).status_code == 200


# --- log redaction -----------------------------------------------------------


def test_log_redaction_masks_tokens():
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/1.1" %d',
                            ("1.2.3.4", "POST", "/api/mcp/st_secret123?x=1", 200), None)
    log_redact.RedactFilter().filter(rec)
    assert "st_secret123" not in rec.getMessage() and "/api/mcp/***" in rec.getMessage()
    assert log_redact.redact("Authorization: Bearer abc.def-ghi") == "Authorization: Bearer ***"
    log_redact.install(("websec-test",))
    log_redact.install(("websec-test",))
    assert sum(isinstance(f, log_redact.RedactFilter) for f in logging.getLogger("websec-test").filters) == 1


# --- uploads -----------------------------------------------------------------


def test_save_upload_stops_at_the_limit(tmp_path):
    dest = tmp_path / "f"
    assert uploads.save_upload(io.BytesIO(b"x" * 100), str(dest), 100) == 100
    with pytest.raises(uploads.UploadTooLarge):
        uploads.save_upload(io.BytesIO(b"x" * 101), str(dest), 100)
    assert not dest.exists()
    upload = SimpleNamespace(file=io.BytesIO(b"abc"))
    assert uploads.save_upload(upload, str(dest), 10) == 3


def _zip(members: dict[str, bytes]) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf


def test_check_zip_accepts_a_normal_archive_and_refuses_non_zips(tmp_path):
    uploads.check_zip(_zip({"xl/workbook.xml": b"<x/>" * 100}))
    p = tmp_path / "a.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(uploads.ZipRejected):  # a caller that also takes CSV checks zipfile.is_zipfile first
        uploads.check_zip(str(p))


def test_check_zip_refuses_bombs_and_traversal():
    # 20 MB of zeros compresses to ~20 KB: ratio ~1000.
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"sheet.xml": b"\0" * (20 * 1024 * 1024)}))
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({f"m{i}": b"" for i in range(30)}), max_members=20)
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"a": b"x" * 2000}), max_total_uncompressed=1000)
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"../evil": b"x"}))


def test_check_zip_does_not_trust_declared_sizes():
    """A central directory that under-reports a member's size is caught by streaming it (verify=True)."""
    buf = _zip({"sheet.xml": b"A" * 50_000})
    raw = bytearray(buf.getvalue())
    # Patch the uncompressed size (offset 24) in the central directory entry to 10 bytes.
    cd = raw.rfind(b"PK\x01\x02")
    raw[cd + 24:cd + 28] = (10).to_bytes(4, "little")
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(io.BytesIO(bytes(raw)), verify=True)
