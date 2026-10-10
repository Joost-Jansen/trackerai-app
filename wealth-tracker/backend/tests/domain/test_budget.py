"""
Tests for budget.py — the month overview of the old spreadsheet: per group
actual next to budget.

The group names come from the taxonomy itself and are not fixed here: that way
this tests the behaviour and not the current layout of the default categories.
"""

import pytest

from domain.money import bank_transactions
from domain.money import budget
from domain.money import categorization
from domain import database
from domain.money import accounts


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("DATA_DIR", raising=False)
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


@pytest.fixture()
def conn():
    conn = database.connect("alice")
    database.init_db(conn)
    categorization.seed(conn)
    yield conn
    conn.close()


def _spending_categories(conn) -> dict[str, list[str]]:
    """{group: [category, ...]} for the spending categories."""
    per: dict[str, list[str]] = {}
    for c in categorization.load_categories(conn):
        if c["type"] == "EXPENSE":
            per.setdefault(c["group_name"], []).append(c["name"])
    return per


@pytest.fixture()
def groups(conn):
    per = _spending_categories(conn)
    assert len(per) >= 2, "de standaardtaxonomie heeft minstens twee uitgavengroepen"
    return per


@pytest.fixture()
def account(conn):
    return accounts.make_bank_account(conn, kind="bank", provider="manual", name="Test")


def _expense(conn, account, date, amount, category):
    tid = bank_transactions.add_manually(conn, account_id=account, date=date,
                                             amount=amount, name="Winkel 1 BV", description="")
    bank_transactions.set_category_manual(conn, tid, category)


def _month_full(conn, account, month, per_category: dict[str, float]):
    """A month with a transaction on the first and the last day, so it counts as
    complete (coverage runs from the first to the last transaction).
    """
    import calendar
    year, m = (int(x) for x in month.split("-"))
    last = calendar.monthrange(year, m)[1]
    items = list(per_category.items())
    for i, (category, amount) in enumerate(items):
        day = 1 if i == 0 else last
        _expense(conn, account, f"{month}-{day:02d}", amount, category)
    if len(items) == 1:
        # A zero expense on the last day is not possible (amount > 0 required): a
        # second transaction of one cent in the same category.
        _expense(conn, account, f"{month}-{last:02d}", 0.01, items[0][0])


# ---------------------------------------------------------------------------
# Setting
# ---------------------------------------------------------------------------

def test_set_a_budget_and_remove_it_again(conn, groups):
    group_name = next(iter(groups))
    budget.put(conn, group_name, 400)
    assert budget.load(conn) == {group_name: 400.0}
    budget.put(conn, group_name, 450)
    assert budget.load(conn) == {group_name: 450.0}
    budget.put(conn, group_name, None)
    assert budget.load(conn) == {}


def test_zero_is_not_a_budget(conn, groups):
    group_name = next(iter(groups))
    budget.put(conn, group_name, 400)
    budget.put(conn, group_name, 0)
    assert budget.load(conn) == {}


def test_an_unknown_group_is_refused(conn):
    with pytest.raises(budget.UnknownGroup):
        budget.put(conn, "Bestaat niet", 100)


def test_a_negative_budget_is_refused(conn, groups):
    with pytest.raises(ValueError):
        budget.put(conn, next(iter(groups)), -5)


def test_only_spending_groups(conn):
    """A group with only income or internal categories gets no budget."""
    spending = set(_spending_categories(conn))
    other = {c["group_name"] for c in categorization.load_categories(conn)} - spending
    assert other, "de taxonomie heeft ook groepen zonder uitgaven"
    assert not other & set(budget.spending_groups(conn))


# ---------------------------------------------------------------------------
# The overview
# ---------------------------------------------------------------------------

def test_actual_per_group_per_month(conn, groups, account):
    (g1, cats1), (g2, cats2) = list(groups.items())[:2]
    _month_full(conn, account, "2026-01", {cats1[0]: 100.0, cats2[0]: 40.0})
    budget.put(conn, g1, 120)

    o = budget.overview(conn)
    assert o["months"] == ["2026-01"]
    row = {r["group_name"]: r for r in o["groups"]}
    assert row[g1]["actual"]["2026-01"] == pytest.approx(100.0)
    assert row[g1]["budget"] == 120.0
    assert row[g2]["budget"] is None
    assert o["total"]["budget"] == 120.0
    assert o["total"]["actual"]["2026-01"] == pytest.approx(140.0)


def test_two_categories_in_one_group_add_up(conn, groups, account):
    group_name, cats = next((g, c) for g, c in groups.items() if len(c) >= 2)
    _month_full(conn, account, "2026-01", {cats[0]: 30.0, cats[1]: 20.0})
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == group_name)
    assert row["actual"]["2026-01"] == pytest.approx(50.0)


def test_the_median_ignores_an_outlier(conn, groups, account):
    group_name, cats = next(iter(groups.items()))
    for month, amount in [("2025-10", 300.0), ("2025-11", 320.0), ("2025-12", 2500.0)]:
        _month_full(conn, account, month, {cats[0]: amount})
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == group_name)
    # Every month has a cent added (see _month_full).
    assert row["median"] == pytest.approx(320.01)


def test_a_half_month_does_not_count_in_the_median(conn, groups, account):
    group_name, cats = next(iter(groups.items()))
    _month_full(conn, account, "2025-11", {cats[0]: 300.0})
    _month_full(conn, account, "2025-12", {cats[0]: 320.0})
    # January only runs until the fifth: the export stops there.
    _expense(conn, account, "2026-01-01", 10.0, cats[0])
    _expense(conn, account, "2026-01-05", 10.0, cats[0])

    o = budget.overview(conn)
    assert o["complete"]["2026-01"] is False
    row = next(r for r in o["groups"] if r["group_name"] == group_name)
    assert row["median"] == pytest.approx(310.01)


def test_a_month_without_spending_in_a_group_counts_as_zero(conn, groups, account):
    (g1, cats1), (g2, cats2) = list(groups.items())[:2]
    _month_full(conn, account, "2025-11", {cats1[0]: 100.0, cats2[0]: 60.0})
    _month_full(conn, account, "2025-12", {cats1[0]: 100.0})
    _month_full(conn, account, "2026-01", {cats1[0]: 100.0})
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == g2)
    assert row["median"] == 0.0


def test_internal_and_income_do_not_count(conn, account):
    internal = next(c["name"] for c in categorization.load_categories(conn) if c["type"] == "INTERNAL")
    _expense(conn, account, "2026-01-10", 500.0, internal)
    assert budget.overview(conn)["total"]["actual"].get("2026-01", 0.0) == 0.0


def test_the_number_of_months_can_be_chosen(conn, groups, account):
    cats = next(iter(groups.values()))
    for month in ("2025-10", "2025-11", "2025-12", "2026-01"):
        _month_full(conn, account, month, {cats[0]: 50.0})
    assert budget.overview(conn, months=2)["months"] == ["2025-12", "2026-01"]


def test_a_group_with_a_budget_but_no_spending_is_included(conn, groups):
    group_name = next(iter(groups))
    budget.put(conn, group_name, 200)
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == group_name)
    assert row["budget"] == 200.0
    assert row["median"] is None


def test_without_data_an_empty_overview(conn):
    o = budget.overview(conn)
    assert o["months"] == [] and o["groups"] == [] and o["total"]["budget"] is None


def test_the_current_month_is_included_even_without_spending(conn, groups, account):
    from datetime import date
    cats = next(iter(groups.values()))
    _month_full(conn, account, "2026-01", {cats[0]: 50.0})
    o = budget.overview(conn, present_day=date(2026, 2, 1))
    assert o["months"] == ["2026-01", "2026-02"]
    assert o["complete"]["2026-02"] is False
    assert o["total"]["actual"]["2026-02"] == 0.0


def test_an_old_export_gets_no_empty_current_month(conn, groups, account):
    from datetime import date
    cats = next(iter(groups.values()))
    _month_full(conn, account, "2026-01", {cats[0]: 50.0})
    assert budget.overview(conn, present_day=date(2026, 5, 10))["months"] == ["2026-01"]


def test_a_refund_counts_net_and_is_shown_apart(conn, groups, account):
    group_name, cats = next(iter(groups.items()))
    _month_full(conn, account, "2026-01", {cats[0]: 30.0})
    # A Tikkie from a friend on the same category: money coming in.
    _expense(conn, account, "2026-01-15", -26.0, cats[0])
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == group_name)
    assert row["actual"]["2026-01"] == pytest.approx(4.01)
    assert row["back"]["2026-01"] == pytest.approx(26.0)


def test_without_a_refund_no_refunded(conn, groups, account):
    group_name, cats = next(iter(groups.items()))
    _month_full(conn, account, "2026-01", {cats[0]: 30.0})
    row = next(r for r in budget.overview(conn)["groups"] if r["group_name"] == group_name)
    assert row["back"] == {}


def _is_fixed(conn, account, date, amount, category, name):
    tid = bank_transactions.add_manually(conn, account_id=account, date=date,
                                             amount=amount, name=name, description="")
    bank_transactions.set_category_manual(conn, tid, category)


def test_expected_counts_a_fixed_cost_on_its_own_day(conn, groups, account):
    from datetime import date
    (g1, cats1), (g2, _) = list(groups.items())[:2]
    # Rent on the first of every month: a fixed cost in g1.
    for month in ("05", "06", "07", "08"):
        _is_fixed(conn, account, f"2026-{month}-01", 1000.0, cats1[0], "Verhuurder")
    budget.put(conn, g1, 1200)
    budget.put(conn, g2, 300)

    o = budget.overview(conn, present_day=date(2026, 9, 3))
    row = {r["group_name"]: r for r in o["groups"]}
    # Day 3 of 30: the rent is already expected, the other 200 for a tenth.
    assert row[g1]["expected"] == pytest.approx(1020.0)
    # Without fixed costs simply the pace of the month.
    assert row[g2]["expected"] == pytest.approx(30.0)
    assert o["current"] == "2026-09"


def test_a_fixed_cost_later_in_the_month_is_not_expected_yet(conn, groups, account):
    from datetime import date
    group_name, cats = next(iter(groups.items()))
    for month in ("05", "06", "07", "08"):
        _is_fixed(conn, account, f"2026-{month}-20", 50.0, cats[0], "Sportschool")
    budget.put(conn, group_name, 350)
    row = next(r for r in budget.overview(conn, present_day=date(2026, 9, 3))["groups"] if r["group_name"] == group_name)
    assert row["expected"] == pytest.approx(30.0)
