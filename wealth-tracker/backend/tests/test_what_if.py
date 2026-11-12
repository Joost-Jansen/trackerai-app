"""
What if you had kept an earlier portfolio: the holdings on a date, stored
snapshots, the comparison, and the MCP tools on top of them.

The arithmetic is pinned against plain dicts (holdings_on, compare); the
endpoint tests upload a DeGiro-shaped export and stand in for the two downloads
(the value card's history and the kept holdings' closes), since tests have no
network.
"""

import datetime

import pytest

from domain.portfolio import what_if

D = datetime.date


def _t(day, isin, kind, qty, total, name=None):
    return {"date": day, "isin": isin, "name": name or isin, "transaction_type": kind, "quantity": qty, "total_eur": total}


SWITCH = [
    _t("2026-01-05", "OLD", "BUY", 10, -1000.0, "Old fund"),
    _t("2026-01-05", "KEEP", "BUY", 5, -500.0, "Kept stock"),
    _t("2026-03-02", "OLD", "SELL", 10, 1200.0),
    _t("2026-03-02", "NEW", "BUY", 4, -1201.0, "New stock"),
]


# --- holdings_on ---------------------------------------------------------------


def test_holdings_on_replays_up_to_and_including_the_day():
    before = {h["isin"]: h for h in what_if.holdings_on(SWITCH, D(2026, 3, 1))}
    assert set(before) == {"OLD", "KEEP"}
    assert before["OLD"]["quantity"] == 10 and before["OLD"]["cost_eur"] == 1000.0
    after = {h["isin"] for h in what_if.holdings_on(SWITCH, D(2026, 3, 2))}
    assert after == {"KEEP", "NEW"}


def test_a_partial_sale_takes_its_share_of_the_cost():
    tx = [_t("2026-01-05", "A", "BUY", 10, -1000.0), _t("2026-02-01", "A", "SELL", 4, 500.0)]
    [h] = what_if.holdings_on(tx, D(2026, 2, 1))
    assert h["quantity"] == 6 and h["cost_eur"] == 600.0


def test_nothing_held_before_the_first_trade():
    assert what_if.holdings_on(SWITCH, D(2025, 12, 31)) == []


# --- compare -------------------------------------------------------------------


def _points(rows):
    return [{"d": d, "value": v, "invested": i} for d, v, i in rows]


def test_kept_line_starts_on_the_real_one_and_the_difference_is_the_trading():
    holdings = what_if.holdings_on(SWITCH, D(2026, 3, 1))
    closes = {"OLD": [("2026-03-01", 120.0), ("2026-03-03", 110.0)], "KEEP": [("2026-03-01", 100.0), ("2026-03-03", 104.0)]}
    # Real: 1700 on the 1st; the switch costs 1 euro (invested +1); NEW rises to 1300.
    actual = _points([("2026-02-28", 1690, 1500), ("2026-03-01", 1700, 1500), ("2026-03-02", 1700, 1501), ("2026-03-03", 1820, 1501)])
    r = what_if.compare(actual, holdings, D(2026, 3, 1), closes)
    p = {x["d"]: x for x in r["points"]}
    assert list(p) == ["2026-03-01", "2026-03-02", "2026-03-03"]
    assert p["2026-03-01"]["kept"] == p["2026-03-01"]["actual"] == 1700
    # The euro deposited on the 2nd buys the old mix at that day's prices (1700 worth),
    # so every holding grows by 1/1700: (10 × 110 + 5 × 104) × 1701/1700.
    assert p["2026-03-03"]["kept"] == 1620.95
    s = r["summary"]
    assert s["deposited_since"] == 1
    assert s["actual_gain"] == 119  # 1820 − 1700 − 1
    assert s["kept_gain"] == -80.05  # 1620.95 − 1700 − 1
    assert s["difference"] == 199.05
    by = {h["isin"]: h for h in r["holdings"]}
    assert by["OLD"]["change_eur"] == -100 and by["KEEP"]["change_eur"] == 20


def test_money_put_in_later_buys_the_old_mix_instead_of_sitting_as_cash():
    holdings = [{"isin": "A", "name": "A", "quantity": 10, "cost_eur": 1000}]
    closes = {"A": [("2026-03-01", 100.0), ("2026-03-02", 110.0), ("2026-03-03", 121.0)]}
    actual = _points([("2026-03-01", 1000, 1000), ("2026-03-02", 2100, 2000), ("2026-03-03", 2310, 2000)])
    r = what_if.compare(actual, holdings, D(2026, 3, 1), closes)
    p = {x["d"]: x["kept"] for x in r["points"]}
    # 1000 euros at 110 buys 9.0909 more; 19.0909 × 121 = 2310, not 1210 + 1000 in cash.
    assert p == {"2026-03-01": 1000, "2026-03-02": 2100, "2026-03-03": 2310}
    assert r["summary"]["difference"] == 0


def test_money_taken_out_later_sells_the_old_mix_in_proportion():
    holdings = [{"isin": "A", "name": "A", "quantity": 10, "cost_eur": 1000}, {"isin": "B", "name": "B", "quantity": 10, "cost_eur": 1000}]
    closes = {"A": [("2026-03-01", 100.0), ("2026-03-03", 200.0)], "B": [("2026-03-01", 100.0), ("2026-03-03", 100.0)]}
    actual = _points([("2026-03-01", 2000, 2000), ("2026-03-02", 1000, 1000), ("2026-03-03", 1500, 1000)])
    r = what_if.compare(actual, holdings, D(2026, 3, 1), closes)
    # Half taken out on the 2nd: 5 A and 5 B are left, worth 5 × 200 + 5 × 100 on the 3rd.
    assert [x["kept"] for x in r["points"]] == [2000, 1000, 1500]


def test_growth_is_the_kept_holdings_value_against_the_start_day():
    holdings = [{"isin": "A", "name": "A", "quantity": 2, "cost_eur": 100}, {"isin": "B", "name": "B", "quantity": 1, "cost_eur": 100}]
    closes = {
        "A": [("2026-02-27", 50.0), ("2026-03-02", 60.0), ("2026-03-03", 55.0)],
        "B": [("2026-02-27", 100.0), ("2026-03-03", 130.0)],
    }
    g = what_if.growth(holdings, D(2026, 3, 1), closes)
    # The start is a Sunday: Friday's closes carry (2 × 50 + 100 = 200).
    assert g["points"] == [
        {"d": "2026-03-01", "v": 1.0},
        {"d": "2026-03-02", "v": 1.1},  # 2 × 60 + 100
        {"d": "2026-03-03", "v": 1.2},  # 2 × 55 + 130
    ]
    assert g["estimated"] == []


def test_growth_names_a_holding_without_history_and_keeps_it_flat():
    holdings = [{"isin": "A", "name": "A", "quantity": 1, "cost_eur": 100}, {"isin": "X", "name": "Fund X", "quantity": 1, "cost_eur": 100}]
    closes = {"A": [("2026-03-01", 100.0), ("2026-03-02", 300.0)]}
    g = what_if.growth(holdings, D(2026, 3, 1), closes)
    assert [p["v"] for p in g["points"]] == [1.0, 2.0]  # (300 + 100) / (100 + 100)
    assert g["estimated"] == [{"isin": "X", "name": "Fund X", "base": "purchase_price"}]


def test_growth_without_any_history_is_empty():
    assert what_if.growth([{"isin": "X", "name": "X", "quantity": 1, "cost_eur": 1}], D(2026, 3, 1), {})["points"] == []


def test_today_is_valued_at_the_live_price_like_the_real_line():
    today = datetime.date.today()
    start = today - datetime.timedelta(days=1)
    holdings = [{"isin": "A", "name": "A", "quantity": 2, "cost_eur": 100}]
    actual = _points([(start.isoformat(), 100, 100), (today.isoformat(), 110, 100)])
    closes = {"A": [(start.isoformat(), 50.0), (today.isoformat(), 51.0)]}
    r = what_if.compare(actual, holdings, start, closes, {"A": 60.0})
    assert r["points"][-1]["kept"] == 120


def test_a_holding_without_history_is_named_not_hidden():
    holdings = [{"isin": "A", "name": "Fund A", "quantity": 2, "cost_eur": 100}]
    actual = _points([("2026-03-01", 100, 100), ("2026-03-02", 100, 100)])
    r = what_if.compare(actual, holdings, D(2026, 3, 1), {})
    assert r["points"][0]["kept"] == 100  # cost per share stands in
    assert r["estimated"] == [{"isin": "A", "name": "Fund A", "base": "purchase_price"}]


def test_no_points_after_the_date_is_an_empty_answer():
    r = what_if.compare(_points([("2026-01-01", 1, 1)]), [{"isin": "A", "name": "A", "quantity": 1, "cost_eur": 1}], D(2026, 2, 1), {})
    assert r == {"points": [], "summary": None, "holdings": [], "estimated": []}


# --- endpoints and MCP ---------------------------------------------------------


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload(client):
    from tests.test_holdings_endpoint import _tx, _upload_tx

    _upload_tx(
        client,
        [
            _tx(isin="IE00B4L5Y983", name="World", qty=10, price=100, order="o1", date="05-01-2026", fee=0),
            _tx(isin="US02079K3059", name="Alphabet", qty=2, price=150, order="o2", date="05-03-2026", fee=0),
        ],
    )


@pytest.fixture
def offline(monkeypatch):
    """Both downloads replaced: a flat history, and closes of 100 for every ISIN."""
    from app.services import dashboard_service, what_if_service

    def history(conn, transactions, prices, dividends):
        start = D(2026, 1, 5)
        days = (datetime.date.today() - start).days + 1
        pts = [
            {"d": (start + datetime.timedelta(days=i)).isoformat(), "value": 1000.0, "invested": 1000.0, "value_divs": 1000.0}
            for i in range(days)
        ]
        return {"points": pts, "estimated": []}

    monkeypatch.setattr(dashboard_service, "get_value_history", history)
    monkeypatch.setattr(what_if_service, "_closes", lambda conn, prices, isins, start: {i: [("2026-01-01", 100.0)] for i in isins})


def test_holdings_at_a_date(client, offline):
    _login(client)
    _upload(client)
    r = client.get("/api/what-if/holdings", params={"date": "2026-02-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [h["isin"] for h in body["holdings"]] == ["IE00B4L5Y983"]
    assert body["holdings"][0]["value_then"] == 1000 and body["holdings"][0]["weight_then_pct"] == 100
    assert client.get("/api/what-if/holdings", params={"date": "nope"}).status_code == 400
    assert client.get("/api/what-if/holdings", params={"date": "2999-01-01"}).status_code == 400


def test_snapshot_is_stored_compared_and_private(client, offline):
    _login(client)
    _upload(client)
    r = client.post("/api/what-if/snapshots", json={"date": "2026-02-01", "name": "Before the switch"})
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["name"] == "Before the switch" and snap["date"] == "2026-02-01"
    assert [h["isin"] for h in snap["holdings"]] == ["IE00B4L5Y983"]

    listed = client.get("/api/what-if/snapshots").json()["snapshots"]
    assert [s["id"] for s in listed] == [snap["id"]]

    cmp = client.get("/api/what-if/compare", params={"snapshot": snap["id"]}).json()
    assert cmp["snapshot"]["name"] == "Before the switch"
    assert cmp["points"][0]["d"] == "2026-02-01"
    assert cmp["summary"]["kept_start"] == 1000

    assert client.post("/api/what-if/snapshots", json={"date": "2025-01-01"}).status_code == 400  # nothing held

    _login(client, "bob", "bobpw")
    assert client.get("/api/what-if/snapshots").json()["snapshots"] == []
    assert client.get("/api/what-if/compare", params={"snapshot": snap["id"]}).status_code == 404
    assert client.delete(f"/api/what-if/snapshots/{snap['id']}").status_code == 404

    _login(client)
    assert client.delete(f"/api/what-if/snapshots/{snap['id']}").status_code == 200
    assert client.get("/api/what-if/snapshots").json()["snapshots"] == []


def test_mcp_tools(client, offline):
    import json

    from tests.test_mcp_agents import _agent, _call, _mcp, _token

    _login(client)
    _upload(client)
    reader = _agent(client, _token(client, "read"))
    names = {t["name"] for t in _mcp(reader, "tools/list")["result"]["tools"]}
    assert {"get_holdings_at", "list_snapshots", "compare_portfolio"} <= names
    assert "save_snapshot" not in names

    at = json.loads(_call(reader, "get_holdings_at", {"date": "2026-03-06"})["content"][0]["text"])
    assert {h["isin"] for h in at["holdings"]} == {"IE00B4L5Y983", "US02079K3059"}
    assert _call(reader, "save_snapshot", {"date": "2026-02-01"})["isError"]

    writer = _agent(client, _token(client, "write", name="Writer"))
    saved = json.loads(_call(writer, "save_snapshot", {"date": "2026-02-01", "name": "Old"})["content"][0]["text"])
    cmp = json.loads(_call(reader, "compare_portfolio", {"snapshot": saved["id"]})["content"][0]["text"])
    assert cmp["snapshot"]["name"] == "Old" and cmp["summary"] is not None
    assert len(cmp["points"]) <= len(
        json.loads(_call(reader, "compare_portfolio", {"snapshot": saved["id"], "points": "all"})["content"][0]["text"])["points"]
    )
    assert _call(reader, "compare_portfolio", {})["isError"]
    assert not _call(writer, "delete_snapshot", {"id": saved["id"]}).get("isError")
    assert json.loads(_call(reader, "list_snapshots")["content"][0]["text"])["snapshots"] == []


def test_kept_index_endpoint(client, offline, monkeypatch):
    from domain.portfolio import etf_holdings

    _login(client)
    _upload(client)
    snap = client.post("/api/what-if/snapshots", json={"date": "2026-03-06", "name": "Both"}).json()
    r = client.get("/api/what-if/index", params={"snapshot": snap["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot"]["name"] == "Both"
    assert body["points"][0] == {"d": "2026-03-06", "v": 1.0}
    assert body["excluded"] == []

    # With bonds left out, a bond in the snapshot leaves the kept line too.
    monkeypatch.setattr(etf_holdings, "bond_isins", lambda conn, positions: {"IE00B4L5Y983"})
    body = client.get("/api/what-if/index", params={"snapshot": snap["id"], "exclude_bonds": "true"}).json()
    assert body["excluded"] == ["World"]
    assert body["points"][0]["v"] == 1.0
    assert client.get("/api/what-if/index").status_code == 400
