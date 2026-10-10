"""
End-to-end integration test through FastAPI's TestClient: login sets the
session cookie, /api/auth/me resolves it, and every DB-touching endpoint is
correctly scoped to that user — the same guarantee tests/test_database.py
proves at the database.py layer, now proven through the actual HTTP surface.

The `client` fixture lives in conftest.py, shared with test_details_endpoints.py.
"""


def test_login_requires_correct_password(client):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
    assert resp.status_code == 401


def test_login_sets_cookie_and_me_resolves_it(client):
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    assert resp.status_code == 200
    assert "trackerai_session" in resp.cookies  # the shared trackerai session

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_dashboard_requires_auth(client):
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 401


def test_dashboard_summary_empty_portfolio(client):
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    resp = client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["num_positions"] == 0


def test_intraday_requires_auth(client):
    resp = client.get("/api/dashboard/intraday")
    assert resp.status_code == 401


def test_intraday_empty_portfolio_is_an_empty_answer_not_an_error(client):
    """A brand-new account must not 500 the card that fetches this on 1D."""
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    resp = client.get("/api/dashboard/intraday")
    assert resp.status_code == 200
    # anchored: nothing to pin, so the card falls back to the daily series
    # rather than drawing a day the chip did not measure.
    assert resp.json() == {"points": [], "prev_close": None, "anchored": False}


def test_two_users_never_see_each_others_dashboard_data(client):
    # Alice uploads a transaction.
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    xlsx_bytes = _build_transactions_xlsx()
    resp = client.post(
        "/api/uploads/transactions",
        files={"files": ("Transactions.xlsx", xlsx_bytes,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["saved"] == 1

    alice_summary = client.get("/api/dashboard/summary").json()
    assert alice_summary["summary"]["num_positions"] == 1

    # Bob logs in on the same client (cookie gets overwritten) and must see nothing.
    client.post("/api/auth/login", json={"username": "bob", "password": "bobpw"})
    bob_summary = client.get("/api/dashboard/summary").json()
    assert bob_summary["summary"]["num_positions"] == 0


def test_the_summary_names_a_position_without_a_price(client):
    """The hero shows "—" for such a portfolio; the warning above it has to be
    able to say which holding is the reason."""
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})
    client.post(
        "/api/uploads/transactions",
        files={"files": ("Transactions.xlsx", _build_transactions_xlsx(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    body = client.get("/api/dashboard/summary").json()

    assert body["summary"]["prices_available"] is False
    # The one ISIN in _build_transactions_xlsx; tests never fetch prices.
    assert [p["isin"] for p in body["unpriced"]] == ["IE00B4L5Y983"]


def test_an_empty_portfolio_has_nothing_unpriced(client):
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})

    assert client.get("/api/dashboard/summary").json()["unpriced"] == []


def test_get_db_connection_survives_teardown_on_another_thread(client):
    """A get_db connection must tolerate setup and teardown on different threads.

    FastAPI runs a sync dependency's setup and its post-yield teardown as
    separate threadpool tasks with no guarantee they land on the same thread.
    Under sqlite3's default check_same_thread that made get_db's conn.close()
    raise ProgrammingError once requests overlapped — the dashboard fires its
    four chart endpoints at once — failing them 500 at random while sequential
    requests stayed green.

    Two single-worker pools rather than one two-worker pool: this must fail on
    a regression every run, not whenever the scheduler happens to switch.
    """
    import concurrent.futures

    from app.deps import CurrentUser, get_db

    user = CurrentUser(username="alice", name="Alice", is_admin=False, beta_features=[])
    from starlette.requests import Request
    gen = get_db(Request({"type": "http", "method": "GET", "path": "/api/dashboard", "headers": []}), user)

    def teardown():
        next(gen, None)  # runs the finally: conn.close()

    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as setup_thread,
        concurrent.futures.ThreadPoolExecutor(max_workers=1) as teardown_thread,
    ):
        conn = setup_thread.submit(next, gen).result()
        assert setup_thread.submit(lambda: conn.execute("SELECT 1").fetchone()[0]).result() == 1
        teardown_thread.submit(teardown).result()  # raised ProgrammingError before the fix


def _build_transactions_xlsx() -> bytes:
    import io
    import pandas as pd

    df = pd.DataFrame([{
        "Datum": "05-01-2026", "Tijd": "09:30", "Product": "iShares Core MSCI World",
        "ISIN": "IE00B4L5Y983", "Beurs": "EAM", "Uitvoeringsplaats": "EAM",
        "Aantal": 10, "Koers": 80.5, "Lokale waarde": -805.0, "Waarde": -805.0,
        "Wisselkoers": 1.0, "Transactiekosten": -1.0, "Totaal": -806.0,
        "Order Id": "order-1",
    }])
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()
