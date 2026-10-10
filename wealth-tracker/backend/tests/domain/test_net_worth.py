"""
Tests for net_worth.py — investments, bank and debt together.

The portfolio knows what your holdings are worth and moves every day. Your bank
balance you only know on the days you looked. Net worth is the sum of the two,
and the whole difficulty lies in that difference in pace.

The rules for the days without a measurement are in accounts.value_on: zero
before the first data, a straight line between manual measurements.

Debt counts as a negative amount, as in the old bookkeeping: net is the sum of
all three.
"""

import sqlite3

import pytest

from domain import database
from domain.money import accounts
from domain.money import net_worth


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _conn() -> sqlite3.Connection:
    conn = database.connect("alice")
    database.init_db(conn)
    return conn


def _account(conn, name, kind="bank", iban=None) -> int:
    return accounts.make_bank_account(
        conn, kind=kind, provider="manual", name=name, iban=iban
    )


def _investments(*pairs) -> list[dict]:
    """The shape dashboard_service.get_value_history returns."""
    return [{"d": d, "invested": 0.0, "value": v, "value_divs": v} for d, v in pairs]


def _point(series, date):
    return next(p for p in series["points"] if p["d"] == date)


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------

def test_without_anything_there_is_no_series():
    conn = _conn()
    series = net_worth.series(conn, [])
    assert series["points"] == []
    assert series["measurements"] == 0
    conn.close()


def test_investments_only_starts_at_the_first_price():
    """Without accounts your net worth *is* your portfolio — nothing can be missing."""
    conn = _conn()
    series = net_worth.series(conn, _investments(("2026-01-01", 1000.0), ("2026-01-02", 1100.0)))

    assert [p["d"] for p in series["points"]] == ["2026-01-01", "2026-01-02"]
    assert _point(series, "2026-01-02")["net"] == pytest.approx(1100.0)
    assert _point(series, "2026-01-02")["bank"] == pytest.approx(0.0)
    conn.close()


def test_bank_and_investments_are_added():
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-01", 2500.0)

    series = net_worth.series(conn, _investments(("2026-01-01", 1000.0)))
    p = _point(series, "2026-01-01")
    assert p["investments"] == pytest.approx(1000.0)
    assert p["bank"] == pytest.approx(2500.0)
    assert p["net"] == pytest.approx(3500.0)
    conn.close()


def test_debt_counts_negative():
    """As in the old bookkeeping: net is the sum of all three."""
    conn = _conn()
    debt = _account(conn, "Studieschuld", kind="debt")
    accounts.set_balance(conn, debt, "2026-01-01", -39000.0)

    series = net_worth.series(conn, _investments(("2026-01-01", 50000.0)))
    p = _point(series, "2026-01-01")
    assert p["debt"] == pytest.approx(-39000.0)
    assert p["net"] == pytest.approx(11000.0)
    conn.close()


def test_cash_and_manual_count_as_bank():
    """Money in a drawer is no investment and no debt; it simply sits on the bank stack."""
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "Portemonnee", kind="cash"), "2026-01-01", 50.0)
    accounts.set_balance(conn, _account(conn, "Tikkies open", kind="manual"), "2026-01-01", 120.0)

    assert _point(net_worth.series(conn, _investments(("2026-01-01", 0.0))), "2026-01-01")["bank"] == pytest.approx(170.0)
    conn.close()


def test_a_broker_account_counts_as_investment():
    """A broker that is not in this app — Coinbase, a second account — belongs with
    your investments and not with your bank.
    """
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "Coinbase", kind="broker"), "2026-01-01", 800.0)

    p = _point(net_worth.series(conn, _investments(("2026-01-01", 1000.0))), "2026-01-01")
    assert p["investments"] == pytest.approx(1800.0)
    assert p["bank"] == pytest.approx(0.0)
    conn.close()


# ---------------------------------------------------------------------------
# The two paces
# ---------------------------------------------------------------------------

def test_between_two_measurements_runs_a_straight_line():
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-01", 1000.0)
    accounts.set_balance(conn, bank, "2026-01-04", 1300.0)

    series = net_worth.series(conn, _investments(("2026-01-01", 0.0), ("2026-01-04", 0.0)))
    assert [_point(series, d)["bank"] for d in
            ("2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04")] == [1000.0, 1100.0, 1200.0, 1300.0]
    conn.close()


def test_investments_do_move_every_day():
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-01", 1000.0)

    series = net_worth.series(conn, _investments(("2026-01-01", 500.0), ("2026-01-02", 600.0)))
    assert _point(series, "2026-01-01")["net"] == pytest.approx(1500.0)
    assert _point(series, "2026-01-02")["net"] == pytest.approx(1600.0)
    conn.close()


def test_before_the_first_measurement_an_account_counts_as_zero():
    """The line starts at the earliest data of any source; a source that starts later
    counts as zero until then.
    """
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-03", 1000.0)

    series = net_worth.series(conn, _investments(
        ("2026-01-01", 500.0), ("2026-01-02", 500.0), ("2026-01-03", 500.0)))

    assert series["from_date"] == "2026-01-01"
    assert _point(series, "2026-01-02")["bank"] == 0.0
    assert _point(series, "2026-01-02")["net"] == pytest.approx(500.0)
    assert _point(series, "2026-01-03")["net"] == pytest.approx(1500.0)
    conn.close()


def test_the_series_continues_after_the_last_measurement():
    """You last looked in January; your investments keep moving."""
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-01", 1000.0)

    series = net_worth.series(conn, _investments(
        ("2026-01-01", 500.0), ("2026-02-01", 700.0), ("2026-03-01", 900.0)))

    assert series["points"][-1]["d"] == "2026-03-01"
    assert _point(series, "2026-03-01")["net"] == pytest.approx(1900.0)
    assert _point(series, "2026-02-15")["portfolio"] == pytest.approx(700.0), \
        "een dag zonder slotkoers staat op de vorige"
    conn.close()


def test_measurements_are_marked():
    """A point that was measured is something different from a point that was carried
    forward.

    The chart must be able to show that; otherwise every point seems equally hard.
    """
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-01", 1000.0)
    accounts.set_balance(conn, bank, "2026-01-03", 1100.0)

    series = net_worth.series(conn, _investments(
        ("2026-01-01", 0.0), ("2026-01-02", 0.0), ("2026-01-03", 0.0)))

    assert [p["measured"] for p in series["points"]] == [True, False, True]
    assert series["measurements"] == 2
    conn.close()


def test_a_closed_account_does_not_count():
    conn = _conn()
    shut = _account(conn, "Oude rekening")
    accounts.set_balance(conn, shut, "2026-01-01", 5000.0)
    accounts.update_account(conn, shut, active=0)

    series = net_worth.series(conn, _investments(("2026-01-01", 100.0)))
    assert series["points"] == [] or _point(series, "2026-01-01")["bank"] == pytest.approx(0.0)
    conn.close()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_summary_gives_the_last_point_and_the_change():
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-01", 1000.0)
    accounts.set_balance(conn, bank, "2026-02-01", 1200.0)

    series = net_worth.series(conn, _investments(("2026-01-01", 500.0), ("2026-02-01", 800.0)))
    now = series["now"]

    assert now["net"] == pytest.approx(2000.0)
    assert now["investments"] == pytest.approx(800.0)
    assert now["bank"] == pytest.approx(1200.0)
    assert now["debt"] == pytest.approx(0.0)
    # Since the first point: 1500 -> 2000
    assert series["change"]["absolute"] == pytest.approx(500.0)
    conn.close()


def test_no_change_for_a_one_point_series():
    """One measurement is not a course; a growth percentage would be made up here."""
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-01", 1000.0)
    series = net_worth.series(conn, _investments(("2026-01-01", 0.0)))
    assert series["change"] is None
    conn.close()


# ---------------------------------------------------------------------------
# Months: income, spending, what is left
# ---------------------------------------------------------------------------

def _tx(conn, account_id, date, amount, type_, hash_):
    from domain.money import bank_transactions
    bank_transactions.save(conn, account_id, [{
        "date": date, "interest_date": None, "amount": amount, "currency": "EUR",
        "name": "X", "counterparty_iban": None, "description": "",
        "code": None, "kind": None, "dedup_hash": hash_, "raw": {},
    }])
    # The type is not a column you set but follows from the category, so here a
    # category of the requested type.
    from domain.money import categorization
    categorization.seed(conn)
    category = {"EXPENSE": "Supermarkt", "INCOME": "Salaris",
                 "INTERNAL": "Naar spaarrekening",
                 "INVEST": categorization.INVESTMENT_CATEGORY,
                 "FRIENDS": categorization.EXCLUDE}.get(type_)
    conn.cursor().execute("UPDATE bank_transactions SET category_auto = ? WHERE dedup_hash = ?",
                          (category, hash_))
    conn.commit()


def test_months_separate_spending_income_and_internal():
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-05", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-25", -2000.0, "INCOME", "b" * 16)
    _tx(conn, r, "2026-01-15", 500.0, "INTERNAL", "c" * 16)

    month = net_worth.per_month(conn)[0]
    assert month["month"] == "2026-01"
    assert month["spending"] == pytest.approx(100.0)
    assert month["income"] == pytest.approx(2000.0)
    assert month["remaining"] == pytest.approx(1900.0)
    conn.close()


def test_savings_rate_is_not_calculated_with_hardly_any_income():
    """Divide by a few tenners and out comes a percentage that means nothing.
    Leaving it out is then more honest than a number.
    """
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-05", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-25", -20.0, "INCOME", "b" * 16)

    assert net_worth.per_month(conn)[0]["spaarquote"] is None
    conn.close()


def test_savings_rate_in_a_normal_month():
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-05", 750.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-25", -3000.0, "INCOME", "b" * 16)

    assert net_worth.per_month(conn)[0]["spaarquote"] == pytest.approx(75.0)
    conn.close()


def test_edge_months_are_marked_incomplete():
    """The first and last month of an export rarely run from the 1st to the 31st.

    A half month next to whole months in the same chart reads as a month in which
    you suddenly spent much less.
    """
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-20", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-02-10", 200.0, "EXPENSE", "b" * 16)
    _tx(conn, r, "2026-02-20", 200.0, "EXPENSE", "c" * 16)
    _tx(conn, r, "2026-03-05", 100.0, "EXPENSE", "d" * 16)

    months = {m["month"]: m for m in net_worth.per_month(conn)}
    assert months["2026-01"]["complete"] is False, "begint pas op de 20e"
    assert months["2026-02"]["complete"] is True
    assert months["2026-03"]["complete"] is False, "eindigt op de 5e"
    conn.close()


def test_months_without_transactions_are_not_included():
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-20", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-03-05", 100.0, "EXPENSE", "b" * 16)
    assert [m["month"] for m in net_worth.per_month(conn)] == ["2026-01", "2026-03"]
    conn.close()


def test_spending_is_split_per_group():
    conn = _conn()
    r = _account(conn, "ING")
    from domain.money import categorization
    categorization.seed(conn)
    for i, (name, amount, cat) in enumerate([
        ("AH", 100.0, "Supermarkt"),
        ("JUMBO", 50.0, "Supermarkt"),
        ("NS", 30.0, "Openbaar vervoer"),
    ]):
        _tx(conn, r, "2026-01-05", amount, "EXPENSE", f"{i}" * 16)
        conn.cursor().execute("UPDATE bank_transactions SET category_auto = ? WHERE dedup_hash = ?",
                              (cat, f"{i}" * 16))
    conn.commit()

    groups = net_worth.per_month(conn)[0]["groups"]
    assert groups["Boodschappen"] == pytest.approx(150.0)
    assert groups["Vervoer"] == pytest.approx(30.0)
    conn.close()


def test_small_groups_merge_under_other():
    """Beyond eight or so colours a person can no longer tell them apart, certainly
    not in a stacked bar.
    """
    conn = _conn()
    r = _account(conn, "ING")
    from domain.money import categorization
    categorization.seed(conn)
    # Nine groups: eight large and one small.
    pairs = [("Supermarkt", 900.0), ("Huur", 800.0), ("Verzekeringen", 700.0),
             ("Openbaar vervoer", 600.0), ("Uitjes & evenementen", 500.0),
             ("Kleding & schoenen", 400.0), ("Media & software", 300.0),
             ("Betaald aan vrienden", 5.0)]
    for i, (cat, amount) in enumerate(pairs):
        _tx(conn, r, "2026-01-05", amount, "EXPENSE", f"{i:x}" * 16)
        conn.cursor().execute("UPDATE bank_transactions SET category_auto = ? WHERE dedup_hash = ?",
                              (cat, f"{i:x}" * 16))
    conn.commit()

    groups = net_worth.per_month(conn)[0]["groups"]
    assert len(groups) <= net_worth.MAX_GROUPS + 1
    assert net_worth.MISC in groups
    assert groups[net_worth.MISC] == pytest.approx(5.0), "de kleinste valt samen"


def test_a_group_keeps_the_same_name_in_every_month():
    """Which groups get their own colour is decided over the whole period.

    Deciding per month would let a group change colour as soon as it is a month
    larger or smaller than its neighbour, and then a colour means nothing.
    """
    conn = _conn()
    r = _account(conn, "ING")
    from domain.money import categorization
    categorization.seed(conn)
    for i, (month, cat, amount) in enumerate([
        ("2026-01-05", "Supermarkt", 500.0),
        ("2026-02-05", "Supermarkt", 10.0),
        ("2026-02-05", "Huur", 900.0),
    ]):
        _tx(conn, r, month, amount, "EXPENSE", f"{i}" * 16)
        conn.cursor().execute("UPDATE bank_transactions SET category_auto = ? WHERE dedup_hash = ?",
                              (cat, f"{i}" * 16))
    conn.commit()

    months = {m["month"]: m["groups"] for m in net_worth.per_month(conn)}
    assert "Boodschappen" in months["2026-01"]
    assert "Boodschappen" in months["2026-02"], "ook als hij die maand klein is"
    conn.close()


# ---------------------------------------------------------------------------
# A month is only complete when *every* account covers it
# ---------------------------------------------------------------------------

def test_a_month_is_complete_only_when_every_account_covers_it():
    """Coverage was decided over all accounts together, and that made a half month
    look like a whole one — just one level higher.

    With an ING export until 20 February and a bunq export until the end of April,
    March and April counted as complete. But your salary account was not in those
    months at all, so March's savings rate was that of bunq alone.
    """
    conn = _conn()
    ing = _account(conn, "ING", iban="NL00INGB0000000001")
    bunq = _account(conn, "bunq", iban="NL00BUNQ0000000002")
    for i, (r, d) in enumerate([
        (ing, "2026-01-21"), (ing, "2026-02-20"),
        (bunq, "2026-01-03"), (bunq, "2026-03-15"), (bunq, "2026-04-30"),
    ]):
        _tx(conn, r, d, 10.0, "EXPENSE", f"{i}" * 16)

    months = {m["month"]: m for m in net_worth.per_month(conn)}
    assert not any(m["complete"] for m in months.values())
    assert set(months["2026-01"]["missing"]) == {"ING", "bunq"}, "beide beginnen na de 1e"
    assert months["2026-02"]["missing"] == ["ING"], "ING stopt op de 20e"
    assert months["2026-03"]["missing"] == ["ING"], "ING zit er helemaal niet in"
    assert months["2026-04"]["missing"] == ["ING"]
    conn.close()


def test_a_month_every_account_covers_is_complete():
    conn = _conn()
    ing = _account(conn, "ING", iban="NL00INGB0000000001")
    bunq = _account(conn, "bunq", iban="NL00BUNQ0000000002")
    for i, (r, d) in enumerate([
        (ing, "2026-01-01"), (ing, "2026-03-31"),
        (bunq, "2026-01-01"), (bunq, "2026-03-31"),
    ]):
        _tx(conn, r, d, 10.0, "EXPENSE", f"{i}" * 16)

    months = {m["month"]: m for m in net_worth.per_month(conn)}
    assert months["2026-01"]["complete"] is True
    assert months["2026-01"]["missing"] == []
    assert months["2026-03"]["complete"] is True
    conn.close()


def test_a_closed_account_does_not_hold_back_a_month():
    """An account you closed does not have to cover the months after it; otherwise
    nothing is complete after every closure.
    """
    conn = _conn()
    ing = _account(conn, "ING", iban="NL00INGB0000000001")
    old = _account(conn, "Oude rekening", iban="NL91ABNA0417164300")
    for i, (r, d) in enumerate([
        (ing, "2026-01-01"), (ing, "2026-03-31"),
        (old, "2026-01-05"), (old, "2026-01-10"),
    ]):
        _tx(conn, r, d, 10.0, "EXPENSE", f"{i}" * 16)
    accounts.update_account(conn, old, active=0)

    months = {m["month"]: m for m in net_worth.per_month(conn)}
    assert months["2026-03"]["complete"] is True
    conn.close()


# ---------------------------------------------------------------------------
# The portfolio is included, and you can see how much
# ---------------------------------------------------------------------------

def test_investments_split_into_portfolio_and_the_rest():
    """The portfolio is *in* your net worth, not next to it — and that must be
    visible, otherwise "Investments" is a number of which you do not know what is
    in it.
    """
    conn = _conn()
    cash = _account(conn, "DeGiro cash", kind="broker")
    accounts.set_balance(conn, cash, "2026-01-01", 1500.0)

    p = _point(net_worth.series(conn, _investments(("2026-01-01", 80000.0))), "2026-01-01")
    assert p["portfolio"] == pytest.approx(80000.0)
    assert p["investments_external"] == pytest.approx(1500.0)
    assert p["investments"] == pytest.approx(p["portfolio"] + p["investments_external"])
    assert p["net"] == pytest.approx(81500.0)
    conn.close()


def test_a_measurement_after_the_last_price_day_is_not_lost():
    """A balance from today while the prices are yesterday's used to drop out of the
    series silently. Now the portfolio stands at its last close that day.
    """
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-05", 1000.0)

    series = net_worth.series(conn, _investments(
        ("2026-01-01", 100.0), ("2026-01-02", 110.0), ("2026-01-03", 120.0)))

    p = _point(series, "2026-01-05")
    assert p["portfolio"] == pytest.approx(120.0)
    assert p["bank"] == pytest.approx(1000.0)
    assert p["net"] == pytest.approx(1120.0)
    conn.close()


def test_net_is_always_the_sum_of_the_stacks():
    """The arithmetic rule the whole page rests on, over a whole series."""
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-01", 2000.0)
    accounts.set_balance(conn, _account(conn, "Coinbase", kind="broker"), "2026-01-02", 300.0)
    accounts.set_balance(conn, _account(conn, "Studieschuld", kind="debt"), "2026-01-01", 5000.0)

    series = net_worth.series(conn, _investments(
        ("2026-01-01", 100.0), ("2026-01-02", 150.0), ("2026-01-03", 125.0)))
    for p in series["points"]:
        assert p["net"] == pytest.approx(p["investments"] + p["bank"] + p["debt"]), p["d"]
        assert p["debt"] == pytest.approx(-5000.0), "positief ingevuld, negatief geteld"
    conn.close()


# ---------------------------------------------------------------------------
# When net worth starts, and when a percentage says something
# ---------------------------------------------------------------------------

def test_the_line_runs_per_calendar_day():
    """Also when the sources only say something now and then: otherwise the time axis
    is not a time axis, and a year of monthly measurements is squeezed next to
    daily prices.
    """
    conn = _conn()
    bank = _account(conn, "ING")
    accounts.set_balance(conn, bank, "2026-01-01", 100.0)
    accounts.set_balance(conn, bank, "2026-03-01", 300.0)

    series = net_worth.series(conn, [])
    assert len(series["points"]) == 60   # 1 January up to and including 1 March
    assert series["measurements"] == 2
    conn.close()


def test_no_percentage_on_an_almost_empty_base():
    """From a few cents to a few thousand euros is millions of percent: true, and useless."""
    conn = _conn()
    accounts.set_balance(conn, _account(conn, "ING"), "2026-01-01", 0.01)

    series = net_worth.series(conn, _investments(("2026-01-01", 0.0), ("2026-01-02", 5000.0)))
    assert series["change"]["absolute"] == pytest.approx(5000.0)
    assert series["change"]["percent"] is None
    conn.close()


# ---------------------------------------------------------------------------
# Money of others: "Niet meetellen"
# ---------------------------------------------------------------------------

def _from_others(conn, account_id, date, amount, hash_):
    from domain.money import bank_transactions
    bank_transactions.save(conn, account_id, [{
        "date": date, "interest_date": None, "amount": amount, "currency": "EUR",
        "name": "FRIENDS", "counterparty_iban": None, "description": "",
        "code": None, "kind": None, "dedup_hash": hash_, "raw": {},
    }])
    conn.execute("UPDATE bank_transactions SET category_manual = 'Niet meetellen' WHERE dedup_hash = ?", (hash_,))
    conn.commit()


def test_money_you_hold_for_others_is_a_debt():
    """2,000 euros from friends in January, the sailing holiday paid in June. It
    really was on your account, but it was not yours: net worth stays flat.
    """
    conn = _conn()
    r = _account(conn, "bunq")
    _from_others(conn, r, "2026-01-10", -2000.0, "a" * 16)
    _from_others(conn, r, "2026-06-10", 2000.0, "b" * 16)
    accounts.set_balance(conn, r, "2026-07-01", 1000.0)

    series = net_worth.series(conn, [])
    feb = _point(series, "2026-02-01")
    assert feb["bank"] == pytest.approx(3000.0), "het saldo zelf blijft echt"
    assert feb["debt"] == pytest.approx(-2000.0)
    assert feb["held"] == pytest.approx(-2000.0)
    assert {_point(series, d)["net"] for d in ("2026-01-09", "2026-02-01", "2026-06-10", "2026-07-01")} == {1000.0}
    assert _point(series, "2026-06-10")["held"] == 0
    conn.close()


def test_paying_more_than_you_received_is_not_a_credit():
    """2,000 received, 2,300 paid: that 300 is your own share of the holiday. Your net
    worth drops by it, and no credit with others takes its place.
    """
    conn = _conn()
    r = _account(conn, "bunq")
    _from_others(conn, r, "2026-01-10", -2000.0, "a" * 16)
    _from_others(conn, r, "2026-06-10", 2300.0, "b" * 16)
    accounts.set_balance(conn, r, "2026-07-01", 700.0)

    series = net_worth.series(conn, [])
    assert _point(series, "2026-02-01")["net"] == pytest.approx(1000.0)
    july = _point(series, "2026-07-01")
    assert july["held"] == 0 and july["debt"] == 0
    assert july["net"] == pytest.approx(700.0)
    conn.close()


def test_a_rule_on_your_own_transfers_does_not_inflate_net_worth():
    """A rule that puts your own transfers to an account outside the app on Niet
    meetellen: debits without a receipt against them. That is not 40,000 euros of
    credit with others.
    """
    conn = _conn()
    r = _account(conn, "bunq")
    _from_others(conn, r, "2026-01-10", 40000.0, "a" * 16)
    accounts.set_balance(conn, r, "2026-02-01", 1000.0)

    now = net_worth.series(conn, [])["now"]
    assert now["held"] == 0
    assert now["net"] == pytest.approx(1000.0) and now["bank"] == pytest.approx(1000.0)
    conn.close()


def test_money_of_others_on_an_account_without_balance_does_not_count():
    """Without a balance the account does not take part in net worth, so neither does its money of others."""
    conn = _conn()
    along = _account(conn, "ING")
    accounts.set_balance(conn, along, "2026-01-01", 500.0)
    loose = _account(conn, "bunq")
    _from_others(conn, loose, "2026-01-10", -2000.0, "a" * 16)

    assert net_worth.series(conn, [])["now"]["net"] == pytest.approx(500.0)
    conn.close()


def test_daily_flows_give_saved_and_what_went_to_investments():
    """Saved is income minus spending; a transfer to the broker is not spending
    but is reported apart, so the page can take it out of the market result.
    Money for friends and unlabelled transactions are reported apart too."""
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-05", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-05", -2000.0, "INCOME", "b" * 16)
    _tx(conn, r, "2026-01-06", 500.0, "INVEST", "c" * 16)
    _tx(conn, r, "2026-01-07", -50.0, "INVEST", "d" * 16)
    _tx(conn, r, "2026-01-07", 300.0, "INTERNAL", "e" * 16)
    _tx(conn, r, "2026-01-08", -80.0, "FRIENDS", "f" * 16)
    _tx(conn, r, "2026-01-09", 25.0, "NONE", "g" * 16)

    flows = {f["d"]: f for f in net_worth.daily_flows(conn)}
    assert flows["2026-01-05"]["saved"] == 1900.0
    assert flows["2026-01-05"]["to_investments"] == 0.0
    assert flows["2026-01-06"]["saved"] == 0.0
    assert flows["2026-01-06"]["to_investments"] == 500.0
    # Money back from the broker counts against what went in; an internal
    # transfer counts nowhere.
    assert flows["2026-01-07"]["saved"] == 0.0
    assert flows["2026-01-07"]["to_investments"] == -50.0
    # Received for friends: money in, but not saved.
    assert flows["2026-01-08"]["others"] == 80.0
    assert flows["2026-01-08"]["saved"] == 0.0
    assert flows["2026-01-09"]["unlabelled"] == -25.0
    # No balance on the account, so it is not in net worth and has no bank flow.
    assert all(f["bank_flow"] == 0.0 for f in flows.values())
    conn.close()


def test_bank_flow_counts_every_transaction_on_an_account_in_net_worth():
    conn = _conn()
    r = _account(conn, "ING")
    accounts.set_balance(conn, r, "2026-01-01", 1000.0)
    _tx(conn, r, "2026-01-05", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-06", 500.0, "INVEST", "c" * 16)
    flows = {f["d"]: f for f in net_worth.daily_flows(conn)}
    assert flows["2026-01-05"]["bank_flow"] == -100.0
    assert flows["2026-01-06"]["bank_flow"] == -500.0
    conn.close()


def test_bank_tx_counts_only_categories_that_land_in_bank_and_cash():
    """Cash withdrawn lands in Bank & cash; a savings transfer (own accounts),
    the broker and friends' money have their other side elsewhere."""
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-05", 40.0, "INTERNAL", "a" * 16)
    _tx(conn, r, "2026-01-05", 500.0, "INVEST", "b" * 16)
    _tx(conn, r, "2026-01-05", -80.0, "FRIENDS", "c" * 16)
    _tx(conn, r, "2026-01-06", 60.0, "EXPENSE", "d" * 16)
    conn.cursor().execute("UPDATE bank_transactions SET category_auto = 'Contant opnemen' WHERE dedup_hash = ?",
                          ("d" * 16,))
    conn.commit()
    flows = {f["d"]: f for f in net_worth.daily_flows(conn)}
    assert flows["2026-01-05"]["bank_tx"] == 0.0
    assert flows["2026-01-06"]["bank_tx"] == -60.0
    conn.close()


def test_points_carry_what_went_into_the_holdings_and_dividend():
    """The page measures the market on the holdings: change in value minus what
    went in (buys minus sells) plus dividend. Selling everything and buying back
    is then no gain or loss, however the money moved via the bank was labelled."""
    conn = _conn()
    points = [
        {"d": "2026-01-01", "invested": 10000.0, "value": 10000.0, "value_divs": 10000.0},
        # Sold everything: value and invested both drop.
        {"d": "2026-01-02", "invested": 0.0, "value": 0.0, "value_divs": 50.0},
        # Bought back, and the price rose 100.
        {"d": "2026-01-03", "invested": 10000.0, "value": 10100.0, "value_divs": 10150.0},
    ]
    series = net_worth.series(conn, points)
    first, last = _point(series, "2026-01-01"), _point(series, "2026-01-03")
    market = ((last["portfolio"] - first["portfolio"])
              - (last["portfolio_invested"] - first["portfolio_invested"])
              + (last["portfolio_dividends"] - first["portfolio_dividends"]))
    assert market == pytest.approx(150.0)   # 100 price + 50 dividend
    conn.close()


# ---------------------------------------------------------------------------
# Balance corrections per account: where the corrections in Bank & cash come from
# ---------------------------------------------------------------------------

def _bridge_corrections(conn, start, end):
    """What split() calls corrections, for the same period."""
    series = net_worth.series(conn, [])
    flows = net_worth.daily_flows(conn)
    # Before the series starts nothing counts yet: zero.
    a = next((p for p in series["points"] if p["d"] == start), {"bank": 0.0})
    b = _point(series, end)
    return b["bank"] - a["bank"] - sum(f["bank_flow"] for f in flows if start < f["d"] <= end)


def test_corrections_of_an_account_with_only_balances_are_its_measurements():
    conn = _conn()
    r = _account(conn, "Spaar")
    accounts.set_balance(conn, r, "2026-01-01", 1000.0, source="sync")
    accounts.set_balance(conn, r, "2026-01-15", 1500.0, source="sync")
    accounts.set_balance(conn, r, "2026-02-15", 1200.0, source="sync")
    out = net_worth.bank_corrections(conn, "2026-01-10", "2026-01-31")
    assert out["total"] == pytest.approx(500.0)
    [acc] = out["accounts"]
    assert acc["account_id"] == r and acc["start_balance"] == 1000.0 and acc["end_balance"] == 1500.0
    assert acc["transactions"] == 0.0 and acc["correction"] == pytest.approx(500.0)
    assert acc["events"] == [{"date": "2026-01-15", "kind": "measurement", "source": "sync",
                              "balance": 1500.0, "amount": 500.0}]
    conn.close()


def test_an_account_whose_transactions_explain_the_balance_has_no_correction():
    conn = _conn()
    r = _account(conn, "ING")
    _tx(conn, r, "2026-01-02", 100.0, "EXPENSE", "a" * 16)
    _tx(conn, r, "2026-01-20", 50.0, "EXPENSE", "b" * 16)
    accounts.set_balance(conn, r, "2026-01-31", 850.0, source="manual")
    out = net_worth.bank_corrections(conn, "2026-01-10", "2026-01-31")
    assert out == {"start": "2026-01-10", "end": "2026-01-31", "total": 0.0, "accounts": []}
    conn.close()


def test_the_first_data_of_an_account_is_a_start_not_a_mistake():
    """Before its first transaction an account counts as zero; the balance it
    starts with is no transaction, so it is a correction, of kind start."""
    conn = _conn()
    r = _account(conn, "Bunq")
    _tx(conn, r, "2026-01-20", 50.0, "EXPENSE", "a" * 16)
    accounts.set_balance(conn, r, "2026-01-31", 950.0, source="sync")
    out = net_worth.bank_corrections(conn, "2026-01-10", "2026-01-31")
    [acc] = out["accounts"]
    assert acc["correction"] == pytest.approx(1000.0)
    assert acc["events"] == [{"date": "2026-01-19", "kind": "start", "source": "derived",
                              "balance": 1000.0, "amount": 1000.0}]
    assert out["total"] == pytest.approx(_bridge_corrections(conn, "2026-01-10", "2026-01-31"))
    conn.close()


def test_a_savings_account_moves_with_transfers_from_your_current_account():
    conn = _conn()
    ing = _account(conn, "ING")
    spaar = accounts.make_bank_account(conn, kind="bank", provider="manual", name="Spaar",
                                       iban="NL11INGB0001234567")
    _tx(conn, ing, "2026-01-02", 10.0, "EXPENSE", "a" * 16)
    accounts.set_balance(conn, ing, "2026-01-02", 2000.0, source="manual")
    accounts.set_balance(conn, spaar, "2026-01-01", 500.0, source="manual")
    from domain.money import bank_transactions
    bank_transactions.save(conn, ing, [{
        "date": "2026-01-15", "interest_date": None, "amount": 300.0, "currency": "EUR",
        "name": "Spaar", "counterparty_iban": "NL11INGB0001234567", "description": "",
        "code": None, "kind": None, "dedup_hash": "c" * 16, "raw": {},
    }])
    out = net_worth.bank_corrections(conn, "2026-01-10", "2026-01-15")
    [acc] = out["accounts"]
    assert acc["account_id"] == spaar and acc["correction"] == pytest.approx(300.0)
    assert acc["events"][0]["kind"] == "transfer" and acc["events"][0]["amount"] == pytest.approx(300.0)
    assert out["total"] == pytest.approx(_bridge_corrections(conn, "2026-01-10", "2026-01-15"))
    conn.close()


def test_corrections_per_account_add_up_to_the_split():
    conn = _conn()
    a = _account(conn, "Spaar")
    b = _account(conn, "Kas", kind="cash")
    accounts.set_balance(conn, a, "2026-01-01", 1000.0, source="sync")
    accounts.set_balance(conn, a, "2026-01-20", 400.0, source="sync")
    accounts.set_balance(conn, b, "2026-01-05", 100.0, source="manual")
    accounts.set_balance(conn, b, "2026-02-04", 400.0, source="manual")
    out = net_worth.bank_corrections(conn, "2026-01-10", "2026-01-31")
    assert out["total"] == pytest.approx(_bridge_corrections(conn, "2026-01-10", "2026-01-31"), abs=0.02)
    kas = next(x for x in out["accounts"] if x["account_id"] == b)
    # A straight line between two manual balances: part of the step falls in the period.
    assert kas["correction"] == pytest.approx(210.0)
    conn.close()
