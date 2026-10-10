"""packages/websec on its own: no app, no domain. (Once health-tracker's api/websec tests; test_websec_more.py
were wealth-tracker's.)"""

import asyncio
import io
import logging
import zipfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from trackerai_websec import client_ip, csrf, headers, log_redact, throttle, uploads


# --- client_ip ------------------------------------------------------------------------------------------------------


class FakeRequest:
    def __init__(self, peer, hdrs=None):
        self.client = type("C", (), {"host": peer})() if peer else None
        self.headers = {k.lower(): v for k, v in (hdrs or {}).items()}


def test_untrusted_peer_is_the_client_whatever_the_headers_say():
    trusted = client_ip.trusted_networks("")
    req = FakeRequest("203.0.113.9", {"CF-Connecting-IP": "1.2.3.4", "X-Forwarded-For": "5.6.7.8"})
    assert client_ip.client_ip(req, trusted) == "203.0.113.9"


def test_trusted_proxy_cf_header_then_rightmost_untrusted_hop():
    trusted = client_ip.trusted_networks("172.18.0.0/16, 10.0.0.1")
    assert client_ip.client_ip(FakeRequest("172.18.0.5", {"CF-Connecting-IP": "198.51.100.7"}), trusted) == "198.51.100.7"
    # the client wrote 1.1.1.1 itself; the proxy appended what it saw
    req = FakeRequest("172.18.0.5", {"X-Forwarded-For": "1.1.1.1, 198.51.100.8, 10.0.0.1"})
    assert client_ip.client_ip(req, trusted) == "198.51.100.8"
    assert client_ip.client_ip(FakeRequest("172.18.0.5"), trusted) == "172.18.0.5"
    assert client_ip.client_ip(FakeRequest("172.18.0.5", {"X-Forwarded-For": "garbage"}), trusted) == "172.18.0.5"
    assert client_ip.client_ip(FakeRequest(None), trusted) == "unknown"


def test_trusted_networks_refuses_typos():
    with pytest.raises(ValueError):
        client_ip.trusted_networks("10.0.0.0/8, not-an-ip")
    assert client_ip.is_trusted("::ffff:10.1.2.3", client_ip.trusted_networks("10.0.0.0/8"))


# --- throttle -------------------------------------------------------------------------------------------------------


def test_limiter_sliding_window_and_reset():
    now = [0.0]
    lim = throttle.Limiter(3, 60, clock=lambda: now[0])
    assert [lim.hit("a") for _ in range(3)] == [True, True, True]
    assert lim.blocked("a") and not lim.blocked("b")
    assert lim.hit("a") is False and lim.remaining_s("a") > 0
    now[0] = 61
    assert not lim.blocked("a")
    lim.hit("a")
    lim.reset("a")
    assert not lim.blocked("a")


def test_limiter_memory_is_bounded():
    lim = throttle.Limiter(1, 60, max_keys=100)
    for i in range(1000):
        lim.hit(f"k{i}")
    assert len(lim._events) <= 100


# --- headers and csrf ---------------------------------------------------------------------------------------------


def small_app(**csrf_kw):
    app = FastAPI()

    @app.get("/x")
    def x():
        return {"ok": True}

    @app.post("/api/thing")
    def thing():
        return {"ok": True}

    @app.post("/api/mcp/{token}")
    def mcp(token: str):
        return {"ok": True}

    app.add_middleware(csrf.OriginCheckMiddleware, cookie_name="sess", exempt_paths=("/api/mcp",), **csrf_kw)
    app.add_middleware(headers.SecurityHeadersMiddleware, csp="default-src 'self'", hsts=True)
    return app


def test_security_headers_on_every_response():
    r = TestClient(small_app()).get("/x")
    h = r.headers
    assert h["content-security-policy"] == "default-src 'self'"
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin" and "camera=()" in h["permissions-policy"]
    assert h["cross-origin-opener-policy"] == "same-origin" and "max-age" in h["strict-transport-security"]
    assert TestClient(small_app()).get("/missing").headers["x-frame-options"] == "DENY"


def test_origin_check():
    c = TestClient(small_app(allowed_origins=["https://health.example.org"]), base_url="http://testserver")
    c.cookies.set("sess", "1")
    assert c.post("/api/thing", headers={"Origin": "http://testserver"}).status_code == 200
    assert c.post("/api/thing", headers={"Origin": "https://health.example.org"}).status_code == 200
    r = c.post("/api/thing", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_origin"
    assert c.post("/api/thing", headers={"Referer": "https://evil.example/page"}).status_code == 403
    assert c.post("/api/thing", headers={"Origin": "null"}).status_code == 403
    assert c.post("/api/thing").status_code == 403  # the cookie, but neither Origin nor Referer
    assert c.post("/api/thing", headers={"Origin": "https://evil.example", "Authorization": "Bearer t"}).status_code == 200
    assert c.post("/api/mcp/abc", headers={"Origin": "https://evil.example"}).status_code == 200
    assert c.get("/x", headers={"Origin": "https://evil.example"}).status_code == 200
    without = TestClient(small_app())  # no session cookie: nothing to forge
    assert without.post("/api/thing", headers={"Origin": "https://evil.example"}).status_code == 200


# --- log redaction --------------------------------------------------------------------------------------------------


def test_log_redaction_masks_tokens(caplog):
    log_redact.install(("websec-test",))
    logger = logging.getLogger("websec-test")
    with caplog.at_level(logging.INFO, logger="websec-test"):
        logger.info('%s - "%s %s HTTP/%s" %d', "1.2.3.4", "POST", "/api/mcp/tr_secret123?x=1", "1.1", 200)
        logger.info("Authorization: Bearer abc.def-ghi")
    text = caplog.text
    assert "tr_secret123" not in text and "/api/mcp/***" in text
    assert "abc.def-ghi" not in text and "Bearer ***" in text


# --- uploads --------------------------------------------------------------------------------------------------------


def _zip(members: dict) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    buf.seek(0)
    return buf


def test_check_zip_refuses_bombs_and_traversal():
    assert [i.filename for i in uploads.check_zip(_zip({"a.fit": b"x" * 100}))] == ["a.fit"]
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"bomb.xml": b"\0" * (20 * 1024 * 1024)}), max_ratio=100)
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"../evil.sh": b"x"}))
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({f"f{i}": b"x" for i in range(20)}), max_members=10)
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(_zip({"a": b"x" * 5000, "b": b"y" * 5000}), max_total_uncompressed=8000)
    with pytest.raises(uploads.ZipRejected):
        uploads.check_zip(io.BytesIO(b"PK not a zip"))
    assert not uploads.safe_member_name("/etc/passwd") and not uploads.safe_member_name("C:/x") and uploads.safe_member_name("a/b.gpx")


def test_stream_to_file_limit(tmp_path):
    async def chunks():
        for _ in range(5):
            yield b"x" * 100

    path = tmp_path / "f"
    assert asyncio.run(uploads.stream_to_file(chunks(), path, 1000)) == 500
    with pytest.raises(uploads.UploadTooLarge):
        asyncio.run(uploads.stream_to_file(chunks(), path, 300))
    with pytest.raises(uploads.UploadTooLarge):
        asyncio.run(uploads.read_limited(chunks(), 300))


def test_body_limit_middleware():
    app = FastAPI()

    @app.post("/api/small")
    async def small(request: Request):
        return {"n": len(await request.body())}

    @app.post("/api/big/x")
    async def big(request: Request):
        return {"n": len(await request.body())}

    app.add_middleware(uploads.BodyLimitMiddleware, default=1000, limits={"/api/big": 5000})
    c = TestClient(app)
    assert c.post("/api/small", content=b"x" * 900).json() == {"n": 900}
    r = c.post("/api/small", content=b"x" * 1100)
    assert r.status_code == 413 and r.json()["code"] == "upload_too_large"
    assert c.post("/api/big/x", content=b"x" * 4000).json() == {"n": 4000}

    def gen():
        for _ in range(3):
            yield b"x" * 600

    assert c.post("/api/small", content=gen()).status_code == 413  # chunked: counted while it comes in
