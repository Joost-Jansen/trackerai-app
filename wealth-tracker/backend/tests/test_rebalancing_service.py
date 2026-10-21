"""
The Rebalancing tab's arithmetic.

The plan's bar: "target-setting persists, charts match, and next-investment
split math matches for several test amounts." The split is the part worth
pinning — it decides where real money goes, and its edges (an already-overweight
bucket, a portfolio at target, an empty portfolio) are where a plausible-looking
formula stops matching app.py.
"""

import json

import pytest

from app.services import rebalancing_service as rb

# ---------------------------------------------------------------------------
# Split math (app.py:1292-1323, app.py:1487-1513)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("amount", [100.0, 500.0, 1000.0, 2500.0, 10000.0])
def test_split_always_allocates_the_whole_amount(amount):
    """Whatever the amount, the parts sum back to it — no euro is invented or lost."""
    result = rb.split_investment(
        by_bucket={"Stocks": 8000.0, "Bonds": 2000.0},
        targets={"Stocks": 90, "Bonds": 10},
        total_value=10000.0,
        amount=amount,
        buckets=rb.CATEGORIES,
    )
    assert sum(result["recommendations"].values()) == pytest.approx(amount)
    assert sum(result["after_pcts"].values()) == pytest.approx(100.0)


def test_split_favours_the_underweight_bucket():
    """80/20 against a 90/10 target: stocks are short, bonds are over."""
    result = rb.split_investment(
        by_bucket={"Stocks": 8000.0, "Bonds": 2000.0},
        targets={"Stocks": 90, "Bonds": 10},
        total_value=10000.0,
        amount=1000.0,
        buckets=rb.CATEGORIES,
    )
    # Bonds are already above target, so their gap floors at zero and the whole
    # amount goes to stocks.
    assert result["recommendations"]["Stocks"] == pytest.approx(1000.0)
    assert result["recommendations"]["Bonds"] == pytest.approx(0.0)
    assert result["after_pcts"]["Stocks"] == pytest.approx(81.818, abs=0.01)


def test_split_across_three_markets_is_proportional_to_the_gaps():
    result = rb.split_investment(
        by_bucket={"US": 5000.0, "Europe": 1000.0, "Emerging Markets": 0.0},
        targets={"US": 65, "Europe": 20, "Emerging Markets": 15},
        total_value=6000.0,
        amount=1000.0,
        buckets=rb.MARKET_BUCKETS,
    )
    recs = result["recommendations"]
    assert sum(recs.values()) == pytest.approx(1000.0)
    # new_total 7000: US wants 4550 (has 5000 -> gap 0), Europe wants 1400
    # (gap 400), EM wants 1050 (gap 1050). 400:1050 of 1000.
    assert recs["US"] == pytest.approx(0.0)
    assert recs["Europe"] == pytest.approx(1000.0 * 400 / 1450, abs=0.01)
    assert recs["Emerging Markets"] == pytest.approx(1000.0 * 1050 / 1450, abs=0.01)


def test_split_recommends_nothing_when_every_bucket_is_already_over_target():
    """All gaps zero must not divide by zero — app.py guards this the same way."""
    result = rb.split_investment(
        by_bucket={"Stocks": 10000.0, "Bonds": 0.0},
        targets={"Stocks": 0, "Bonds": 0},
        total_value=10000.0,
        amount=1000.0,
        buckets=rb.CATEGORIES,
    )
    assert result["recommendations"] == {"Stocks": 0.0, "Bonds": 0.0}


def test_split_of_an_empty_portfolio_follows_the_targets_exactly():
    result = rb.split_investment(
        by_bucket={"Stocks": 0.0, "Bonds": 0.0},
        targets={"Stocks": 70, "Bonds": 30},
        total_value=0.0,
        amount=1000.0,
        buckets=rb.CATEGORIES,
    )
    assert result["recommendations"]["Stocks"] == pytest.approx(700.0)
    assert result["recommendations"]["Bonds"] == pytest.approx(300.0)
    assert result["after_pcts"]["Stocks"] == pytest.approx(70.0)


def test_a_big_enough_investment_reaches_the_target_exactly():
    """The formula's own claim: enough money lands you on target."""
    result = rb.split_investment(
        by_bucket={"Stocks": 9000.0, "Bonds": 1000.0},
        targets={"Stocks": 50, "Bonds": 50},
        total_value=10000.0,
        amount=16000.0,
        buckets=rb.CATEGORIES,
    )
    assert result["after_pcts"]["Bonds"] == pytest.approx(50.0, abs=0.01)


# ---------------------------------------------------------------------------
# Targets (app.py:1133-1157)
# ---------------------------------------------------------------------------


def test_targets_default_to_90_10_and_round_trip(tmp_path, monkeypatch):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)

    assert rb.load_targets(conn) == {"Stocks": 90, "Bonds": 10}

    rb.save_targets(conn, 60)
    assert rb.load_targets(conn) == {"Stocks": 60, "Bonds": 40}
    conn.close()


def test_targets_roll_up_the_old_three_bucket_format(tmp_path, monkeypatch):
    """An older version split stocks in two; those users keep their setting."""
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)
    database.save_setting(
        conn,
        "rebalancing_targets",
        json.dumps({"Broad ETF": 70, "Individual / Sector ETF": 15, "Bonds": 15}),
    )

    assert rb.load_targets(conn) == {"Stocks": 85, "Bonds": 15}
    conn.close()


def test_market_targets_accept_the_old_em_key(tmp_path, monkeypatch):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)
    database.save_setting(conn, "broad_region_targets", json.dumps({"US": 50, "Europe": 30, "EM": 20}))

    assert rb.load_market_targets(conn) == {"US": 50, "Europe": 30, "Emerging Markets": 20}
    conn.close()


# ---------------------------------------------------------------------------
# Classification and buckets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("iShares Core Global Aggregate Bond UCITS ETF", "Bonds"),
        ("ISHS V-IBDS DEC 2026 TERM EO CREG.SHS", "Stocks"),  # no keyword — user must correct it
        ("Vanguard S&P 500 UCITS ETF", "Stocks"),
        ("iShares Euro Government Bond 3-5yr", "Bonds"),
        ("Xtrackers II EUR Corporate Bond", "Bonds"),
        ("NN Group NV", "Stocks"),
    ],
)
def test_auto_guess_category(name, expected):
    assert rb.auto_guess_category(name) == expected


@pytest.mark.parametrize(
    "country,bucket",
    [
        ("United States", "US"),
        ("Netherlands", "Europe"),
        ("Germany", "Europe"),
        # Economic, not geographic — the point of a hand-written list.
        ("Poland", "Emerging Markets"),
        ("Turkey", "Emerging Markets"),
        ("Greece", "Emerging Markets"),
        ("Taiwan", "Emerging Markets"),
        ("Japan", "Other developed / unclassified"),
        ("Canada", "Other developed / unclassified"),
        ("", "Other developed / unclassified"),
    ],
)
def test_market_bucket(country, bucket):
    assert rb.market_bucket(country) == bucket


def test_market_allocation_rolls_country_fractions_into_buckets():
    by_market = rb.market_allocation(
        region_totals={"United States": 0.5, "Netherlands": 0.2, "China": 0.2, "Japan": 0.1},
        equity_value=10000.0,
    )
    assert by_market["US"] == pytest.approx(5000.0)
    assert by_market["Europe"] == pytest.approx(2000.0)
    assert by_market["Emerging Markets"] == pytest.approx(2000.0)
    assert by_market[rb.OTHER_MARKET] == pytest.approx(1000.0)


def test_categorise_keeps_a_pre_rebuild_bond_classification(tmp_path, monkeypatch):
    """A row saying "Bond" is still the user's answer, not a missing one.

    "Bond" is not in CATEGORIES, so the plain membership check app.py uses falls
    through to the keyword guess — and this fund's name has no keyword, so an
    explicit classification would come back as Stocks and be overwritten on the
    next save. database.bond_isins already reads both spellings; the tab that
    writes them has to agree.
    """
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)
    database.save_asset_category(conn, "IE000WA6L436", "Bond")  # pre-rebuild spelling

    rows = rb.categorise(
        conn,
        [
            {"isin": "IE000WA6L436", "name": "ISHS V-IBDS DEC 2026 TERM EO CREG.SHS", "current_value": 1000.0},
        ],
    )
    assert rows[0]["category"] == "Bonds"
    conn.close()


def test_categorise_guesses_only_when_there_is_no_classification(tmp_path, monkeypatch):
    from domain import database

    monkeypatch.setattr(database, "_HERE", str(tmp_path))
    conn = database.connect("alice")
    database.init_db(conn)
    database.save_asset_category(conn, "A", "Bonds")

    rows = rb.categorise(
        conn,
        [
            {"isin": "A", "name": "Vanguard S&P 500", "current_value": 100.0},  # saved beats the guess
            {"isin": "B", "name": "iShares Global Bond", "current_value": 100.0},  # guessed
            {"isin": "C", "name": "NN Group NV", "current_value": 100.0},  # guessed
        ],
    )
    assert [r["category"] for r in rows] == ["Bonds", "Bonds", "Stocks"]
    conn.close()


def test_allocation_treats_an_uncategorised_position_as_stocks():
    by_cat, pcts, total = rb.allocation(
        positions=[
            {"isin": "A", "current_value": 700.0},
            {"isin": "B", "current_value": 300.0},
        ],
        categories={"B": "Bonds"},  # A has no category
    )
    assert by_cat == {"Stocks": 700.0, "Bonds": 300.0}
    assert pcts["Stocks"] == pytest.approx(70.0)
    assert total == 1000.0


def test_allocation_of_an_unpriced_portfolio_does_not_divide_by_zero():
    by_cat, pcts, total = rb.allocation([{"isin": "A", "current_value": None}], {})
    assert total == 0.0
    assert pcts == {"Stocks": 0.0, "Bonds": 0.0}


@pytest.mark.parametrize(
    "current,target,status",
    [
        (90.0, 90.0, "green"),
        (95.0, 90.0, "green"),  # exactly 5pp off is still green
        (95.1, 90.0, "amber"),
        (85.0, 90.0, "green"),  # and in the other direction
        (105.0, 90.0, "amber"),  # exactly 15pp off is still amber, either way
        (75.0, 90.0, "amber"),
        (74.9, 90.0, "red"),
        (105.1, 90.0, "red"),
    ],
)
def test_deviation_status_thresholds(current, target, status):
    assert rb.deviation_status(current, target) == status
