"""Every test client acts like a browser on this site: it names the page's origin on every write, as the CSRF check
(packages/websec) requires for a cookie-authenticated POST/PUT/PATCH/DELETE. A test that wants another Origin, or
none, passes its own headers."""

import pytest
from fastapi.testclient import TestClient

_init = TestClient.__init__


def _with_origin(self, *args, headers=None, **kwargs):
    _init(self, *args, headers={"Origin": "http://testserver", **(headers or {})}, **kwargs)


@pytest.fixture(autouse=True)
def browser_origin(monkeypatch):
    monkeypatch.setattr(TestClient, "__init__", _with_origin)
