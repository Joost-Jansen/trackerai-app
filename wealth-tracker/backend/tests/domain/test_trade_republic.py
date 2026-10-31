"""
Trade Republic: its transaction export, entering movements by hand, and how its
positions add up with DeGiro's.

The fixture backend/tests/data/trade_republic_export.csv has the header of
Trade Republic's "Transaktionsexport" as published by users of independent
importers (pytr issue #408, Export-To-Ghostfolio issue #329,
GhostfolioSidekick issue #1411), and rows in the shapes shown there: a
deposit, savings-plan buys with fractional shares and no fee, a sell with a
€1 fee, a distribution with withholding tax and an original USD amount, an
interest payment, a tax-only row (Vorabpauschale), a withdrawal and a USD card
payment. Names, ids and IBANs are made up.
"""

import pathlib

import pytest

from domain import database
from domain.imports import trade_republic
from domain.money import accounts
from domain.portfolio import broker_ledger
from domain.portfolio import positions as portfolio

FIXTURE = pathlib.Path(__file__).resolve().parents[1] / "data" / "trade_republic_export.csv"
VWCE, EMIM, AVWS = "IE00BK5BQT80", "IE00BKM4GZ66", "IE0003R87OG3"


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn():
    conn = database.connect("alice")
    database.init_db(conn)
    return conn


def _european(tmp_path) -> pathlib.Path:
    """The same file as a spreadsheet in a Dutch or German locale writes it: semicolons, decimal commas."""
    out = []
    for line in FIXTURE.read_text().splitlines():
        cells = [c.strip('"') for c in line.split('","')]
        cells = [c.replace(".", ",") if c.replace(".", "").replace("-", "").isdigit() else c for c in cells]
        out.append(";".join(cells))
    path = tmp_path / "tr-european.csv"
    path.write_text("\n".join(out), encoding="utf-8-sig")
    return path


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------


def test_the_header_is_recognised_and_other_files_are_not():
    assert trade_republic.looks_like(FIXTURE.read_text().splitlines()[0].replace('"', "").split(","))
    assert not trade_republic.looks_like(["Datum", "Tijd", "Product", "ISIN", "Aantal", "Koers"])


def test_trades_have_the_signs_and_fractions_of_the_file():
    parsed = trade_republic.parse(str(FIXTURE))
    by_isin = {(t["isin"], t["transaction_type"]): t for t in parsed["trades"]}
    assert len(parsed["trades"]) == 4

    plan = by_isin[(VWCE, "BUY")]
    assert plan["quantity"] == pytest.approx(2.8901)
    assert plan["value_eur"] == pytest.approx(-400.0)
    assert plan["transaction_fee"] is None, "a savings-plan execution has no fee"
    assert plan["total_eur"] == pytest.approx(-400.0)
    assert plan["order_ref"] == "0b6f2c9e-0000-4000-8000-000000000002"
    assert plan["time"] == "06:30"
    assert plan["broker"] == "trade_republic"

    sell = by_isin[(VWCE, "SELL")]
    assert sell["quantity"] == pytest.approx(0.5), "the file signs a sale on the shares; the app on the type"
    assert sell["value_eur"] == pytest.approx(70.0)
    assert sell["transaction_fee"] == pytest.approx(-1.0)
    assert sell["total_eur"] == pytest.approx(69.0)


def test_a_distribution_is_a_dividend_net_of_tax():
    (d,) = trade_republic.parse(str(FIXTURE))["dividends"]
    assert d["isin"] == "IE00B1XNHC34"
    assert d["gross_eur"] == pytest.approx(0.30)
    assert d["tax_eur"] == pytest.approx(-0.06)
    assert d["net_eur"] == pytest.approx(0.24)
    assert (d["amount_original"], d["currency_original"]) == (pytest.approx(0.27), "USD")


def test_every_eur_row_moves_the_cash_and_says_what_it_was():
    parsed = trade_republic.parse(str(FIXTURE))
    kinds = [e["kind"] for e in parsed["entries"]]
    assert kinds == ["deposit", "buy", "buy", "buy", "sell", "dividend", "interest", "tax", "withdrawal"]
    assert sum(e["amount"] for e in parsed["entries"]) == pytest.approx(47.51)
    assert len({e["key"] for e in parsed["entries"]}) == len(parsed["entries"])


def test_another_currency_is_reported_not_counted():
    parsed = trade_republic.parse(str(FIXTURE))
    assert parsed["skipped"] == [{"line": 11, "type": "CARD_TRANSACTION", "reason": "currency USD"}]


def test_semicolons_and_decimal_commas_read_the_same(tmp_path):
    plain = trade_republic.parse(str(FIXTURE))
    european = trade_republic.parse(str(_european(tmp_path)))
    assert european["trades"] == plain["trades"]
    assert european["dividends"] == plain["dividends"]
    assert [e["amount"] for e in european["entries"]] == [e["amount"] for e in plain["entries"]]


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------


def test_import_creates_the_account_with_its_cash_and_is_idempotent():
    conn = _conn()
    first = trade_republic.import_file(conn, str(FIXTURE))
    assert (first["saved"], first["dividends"], first["cash_entries"]) == (4, 1, 9)

    account = broker_ledger.cash_account(conn, "trade_republic")
    assert account["kind"] == "broker" and account["provider"] == "trade_republic"
    assert accounts.balance_on(conn, account["id"], "2026-09-03") == pytest.approx(0.0)
    assert accounts.balance_on(conn, account["id"], "2026-10-31") == pytest.approx(47.51)

    again = trade_republic.import_file(conn, str(FIXTURE))
    assert (again["saved"], again["skipped"], again["dividends"], again["cash_entries"]) == (0, 4, 0, 0)
    assert accounts.balance_on(conn, account["id"], "2026-10-31") == pytest.approx(47.51)
    assert all(t["account_id"] == account["id"] for t in database.load_transactions(conn))
    conn.close()


def test_positions_at_two_brokers_add_up_per_isin():
    conn = _conn()
    database.save_transactions(
        conn,
        [
            {
                "order_ref": "dg-1",
                "date": "2026-10-01",
                "time": "09:00",
                "name": "VANGUARD FTSE AW",
                "isin": VWCE,
                "exchange": "XET",
                "transaction_type": "BUY",
                "quantity": 100,
                "price": 130.0,
                "value_eur": -13000.0,
                "transaction_fee": -3.0,
                "total_eur": -13003.0,
            }
        ],
    )
    trade_republic.import_file(conn, str(FIXTURE))
    txs = database.load_transactions(conn)
    assert {t["broker"] for t in txs} == {"degiro", "trade_republic"}, "a row without a broker is DeGiro's"

    prices = {i: {"price": 140.0, "currency": "EUR", "ticker": "T"} for i in (VWCE, EMIM, AVWS)}
    held = {p["isin"]: p for p in portfolio.calculate_positions(txs, prices)}
    assert held[VWCE]["shares_held"] == pytest.approx(100 + 2.8901 - 0.5)
    assert held[EMIM]["shares_held"] == pytest.approx(1.4205)
    assert held[AVWS]["shares_held"] == pytest.approx(1.0526)
    summary = portfolio.calculate_portfolio_summary(list(held.values()), txs)
    assert summary["total_costs"] == pytest.approx(4.0), "DeGiro's €3 and Trade Republic's €1"
    conn.close()


# ---------------------------------------------------------------------------
# Entering by hand
# ---------------------------------------------------------------------------


def test_a_savings_plan_by_hand_moves_holdings_and_cash_together():
    conn = _conn()
    account = broker_ledger.cash_account(conn, "trade_republic", create=True)
    aid = account["id"]
    broker_ledger.add_manual(conn, aid, kind="deposit", date="2026-09-01", amount=500)
    broker_ledger.add_manual(conn, aid, kind="buy", date="2026-09-03", isin=VWCE, quantity=2.8901, amount=400, name="VWCE")
    broker_ledger.add_manual(conn, aid, kind="buy", date="2026-09-03", isin=EMIM, quantity=1.4205, price=35.2)
    out = broker_ledger.add_manual(conn, aid, kind="buy", date="2026-09-03", isin=AVWS, quantity=1.0526, amount=50, fee=1)

    assert out["cash"] == pytest.approx(-51.0)
    txs = database.load_transactions(conn)
    assert len(txs) == 3 and {t["source"] for t in txs} == {"manual"} and {t["broker"] for t in txs} == {"trade_republic"}
    vwce = next(t for t in txs if t["isin"] == VWCE)
    assert vwce["price"] == pytest.approx(400 / 2.8901, rel=1e-6)
    assert vwce["total_eur"] == pytest.approx(-400.0)
    assert next(t for t in txs if t["isin"] == EMIM)["name"] == EMIM, "an unknown ISIN without a name is named by its ISIN"
    # 500 − 400 − 35,2 × 1,4205 − 51
    assert accounts.balance_on(conn, aid, "2026-09-30") == pytest.approx(500 - 400 - 50.0016 - 51, abs=0.01)
    conn.close()


def test_dividend_interest_fee_and_tax_by_hand():
    conn = _conn()
    aid = broker_ledger.cash_account(conn, "trade_republic", create=True)["id"]
    broker_ledger.add_manual(conn, aid, kind="dividend", date="2026-09-05", isin=VWCE, amount=10, tax=1.5)
    broker_ledger.add_manual(conn, aid, kind="interest", date="2026-09-30", amount=2)
    broker_ledger.add_manual(conn, aid, kind="fee", date="2026-09-30", amount=1)
    broker_ledger.add_manual(conn, aid, kind="tax", date="2026-10-01", amount=0.5)
    broker_ledger.add_manual(conn, aid, kind="withdrawal", date="2026-10-02", amount=5)

    (d,) = database.load_dividends(conn)
    assert (d["gross_eur"], d["tax_eur"], d["net_eur"], d["broker"]) == (10, -1.5, 8.5, "trade_republic")
    assert accounts.balance_on(conn, aid, "2026-10-31") == pytest.approx(8.5 + 2 - 1 - 0.5 - 5)
    conn.close()


def test_wrong_input_is_refused_with_a_reason():
    conn = _conn()
    aid = broker_ledger.cash_account(conn, "trade_republic", create=True)["id"]
    with pytest.raises(ValueError):
        broker_ledger.add_manual(conn, aid, kind="buy", date="2026-09-03", isin="NOT-AN-ISIN", quantity=1, price=1)
    with pytest.raises(ValueError):
        broker_ledger.add_manual(conn, aid, kind="buy", date="2026-09-03", isin=VWCE, quantity=0, price=1)
    with pytest.raises(ValueError):
        broker_ledger.add_manual(conn, aid, kind="gift", date="2026-09-03", amount=1)
    with pytest.raises(ValueError):
        broker_ledger.add_manual(conn, aid, kind="deposit", date="03-11-2026", amount=1)
    bank = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Betaal")
    with pytest.raises(ValueError):
        broker_ledger.add_manual(conn, bank, kind="deposit", date="2026-09-03", amount=1)
    conn.close()


def test_deleting_a_manual_entry_takes_its_cash_along_and_imports_stay():
    conn = _conn()
    trade_republic.import_file(conn, str(FIXTURE))
    aid = broker_ledger.cash_account(conn, "trade_republic")["id"]
    stored = broker_ledger.add_manual(conn, aid, kind="buy", date="2026-10-10", isin=VWCE, quantity=0.1, price=140)
    assert accounts.balance_on(conn, aid, "2026-10-31") == pytest.approx(47.51 - 14.0)

    assert broker_ledger.delete_manual(conn, stored["table"], stored["id"])
    assert accounts.balance_on(conn, aid, "2026-10-31") == pytest.approx(47.51)
    assert len(database.load_transactions(conn)) == 4

    imported = database.load_transactions(conn)[0]
    assert not broker_ledger.delete_manual(conn, "transactions", imported["id"])
    entries = broker_ledger.ledger(conn, aid)
    assert all(e["ref"] is None and e["source"] == "import" for e in entries)
    conn.close()


def test_a_balance_entered_by_hand_wins_on_its_day():
    conn = _conn()
    aid = broker_ledger.cash_account(conn, "trade_republic", create=True)["id"]
    broker_ledger.add_manual(conn, aid, kind="deposit", date="2026-09-01", amount=100)
    accounts.set_balance(conn, aid, "2026-09-01", 90.0)
    broker_ledger.add_manual(conn, aid, kind="interest", date="2026-09-30", amount=1)
    assert accounts.balance_on(conn, aid, "2026-09-01") == pytest.approx(90.0)
    assert accounts.balance_on(conn, aid, "2026-09-30") == pytest.approx(101.0)
    conn.close()


def test_deleting_the_account_takes_its_trades_but_not_degiros():
    conn = _conn()
    database.save_transactions(
        conn,
        [
            {
                "order_ref": "dg",
                "date": "2026-10-01",
                "name": "X",
                "isin": VWCE,
                "transaction_type": "BUY",
                "quantity": 1,
                "price": 1,
                "total_eur": -1,
            }
        ],
    )
    trade_republic.import_file(conn, str(FIXTURE))
    accounts.delete_account(conn, broker_ledger.cash_account(conn, "trade_republic")["id"])
    assert [t["broker"] for t in database.load_transactions(conn)] == ["degiro"]
    assert database.load_dividends(conn) == []
    conn.close()


# ---------------------------------------------------------------------------
# An existing database
# ---------------------------------------------------------------------------


def test_rows_from_before_brokers_become_degiros(tmp_path):
    """A database from before this change has no broker columns; opening it adds them and marks every row DeGiro's."""
    import sqlite3

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, order_ref TEXT, date TEXT NOT NULL, time TEXT,"
        " name TEXT NOT NULL, isin TEXT NOT NULL, exchange TEXT, execution_venue TEXT, transaction_type TEXT NOT NULL,"
        " quantity REAL NOT NULL, price REAL, local_value REAL, value_eur REAL, exchange_rate REAL, autofx_cost REAL,"
        " transaction_fee REAL, total_eur REAL)"
    )
    old.execute("INSERT INTO transactions (date, name, isin, transaction_type, quantity) VALUES ('2025-01-02', 'X', ?, 'BUY', 3)", (VWCE,))
    old.execute(
        "CREATE TABLE dividends (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, isin TEXT NOT NULL, name TEXT,"
        " currency_original TEXT, amount_original REAL, gross_eur REAL, tax_eur REAL, net_eur REAL NOT NULL)"
    )
    old.execute("INSERT INTO dividends (date, isin, net_eur) VALUES ('2025-02-03', ?, 1.5)", (VWCE,))
    old.commit()
    old.row_factory = sqlite3.Row
    database.init_db(old)
    (t,) = database.load_transactions(old)
    (d,) = database.load_dividends(old)
    assert (t["broker"], t["source"], t["account_id"]) == ("degiro", "import", None)
    assert (d["broker"], d["source"]) == ("degiro", "import")
    database.init_db(old)  # a second time changes nothing
    assert database.load_transactions(old)[0]["broker"] == "degiro"
    old.close()
