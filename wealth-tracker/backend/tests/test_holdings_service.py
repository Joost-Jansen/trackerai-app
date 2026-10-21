"""
The Portfolio tab's arithmetic: the cost split (GAK excluding transaction
costs vs. every euro paid) and the two results built on it.

The distinction the whole tab rests on: `Ongerealiseerd` measures the current
price against what the shares cost, costs excluded, so it is comparable to
GAK; `Totaal` is what the position has actually delivered — that move plus
realized gains plus dividends minus every cost DeGiro charged.

Pure functions over plain dicts, no network, no database.
"""

from app.services import holdings_service as hs
from app.services.portfolio_service import PortfolioBundle
from domain.portfolio import positions as portfolio


def _tx(
    kind="BUY",
    qty=10.0,
    price=100.0,
    fee=2.0,
    date="2026-01-05",
    time="09:30",
    isin="X1",
    name="Fund X",
    autofx=None,
    value=None,
    total=None,
    exchange=None,
):
    """One DeGiro transaction row, with its sign conventions.

    A buy's value and total are negative (money out), a sell's positive, and
    the fee is always charged: total = value +/- fee in the same direction.
    """
    gross = qty * price
    if value is None:
        value = -gross if kind == "BUY" else gross
    if total is None:
        total = value - fee if kind == "BUY" else value - fee
    return {
        "isin": isin,
        "name": name,
        "date": date,
        "time": time,
        "transaction_type": kind,
        "quantity": qty,
        "price": price,
        "value_eur": value,
        "total_eur": total,
        "transaction_fee": -fee,
        "autofx_cost": autofx,
        "exchange": exchange,
    }


def _bundle(transactions, prices=None, dividends_by_isin=None):
    prices = prices or {}
    positions = portfolio.calculate_positions(transactions, prices)
    return PortfolioBundle(
        prices=prices,
        transactions=transactions,
        dividends=[],
        dividends_by_isin=dividends_by_isin or {},
        positions=positions,
        summary=portfolio.calculate_portfolio_summary(positions, transactions, []),
    )


def _price(price=110.0, prev=None, currency="EUR"):
    return {"price": price, "previous_close": prev, "currency": currency, "ticker": "X1.AS"}


# ---------------------------------------------------------------------------
# The cost split
# ---------------------------------------------------------------------------


def test_avg_cost_excludes_transaction_costs():
    """10 shares at 100 with a 2 euro fee cost 1002, but the average cost is 100.

    The fee is not part of what a share cost; folding it in (as
    calculate_positions' avg_cost does, deliberately) would make the average cost
    column incomparable to the price column next to it.
    """
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price()}))
    assert rows[0]["avg_cost_ex_costs"] == 100.0
    assert rows[0]["invested_ex_costs"] == 1000.0
    assert rows[0]["invested_gross"] == 1002.0
    assert rows[0]["costs_eur"] == 2.0


def test_autofx_counts_as_a_transaction_cost():
    tx = _tx(fee=2.0, autofx=-1.5)
    assert hs.cost_breakdown([tx])["X1"]["costs_total"] == 3.5


def test_value_reconstructed_from_total_when_the_column_is_missing():
    """Rows from an export without a 'Waarde' column must not lose their fee.

    A buy paid value + fee and a sell received value - fee, so the
    reconstruction runs in opposite directions — getting the sign wrong here
    moves the average cost by twice the fee.
    """
    buy = _tx(value=None, total=-1002.0, fee=2.0)
    buy["value_eur"] = None
    sell = _tx(kind="SELL", qty=4.0, price=120.0, fee=2.0, date="2026-02-05")
    sell["value_eur"] = None
    sell["total_eur"] = 478.0  # 480 received, minus a 2 euro fee

    b = hs.cost_breakdown([buy, sell])["X1"]
    assert b["cost_ex"] == 600.0  # 6 shares left at 100
    assert round(b["realized_ex"], 2) == 80.0  # sold 4 at 120, cost 100
    assert b["invested_gross"] == 1002.0


# ---------------------------------------------------------------------------
# Unrealised vs. Total
# ---------------------------------------------------------------------------


def test_unrealized_measures_price_against_avg_cost():
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price(110.0)}))
    assert rows[0]["unrealized_eur"] == 100.0  # 1100 value vs 1000 basis
    assert rows[0]["unrealized_pct"] == 10.0


def test_total_is_unrealized_minus_costs_when_nothing_was_sold():
    """With no sells and no dividends the two columns differ by the costs
    alone, and Totaal % is the classic return on every euro paid."""
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price(110.0)}))
    assert rows[0]["total_eur"] == 98.0  # 100 unrealized - 2 costs
    assert rows[0]["total_pct"] == 9.78  # 98 / 1002


def test_total_includes_realized_gains_and_dividends():
    """Sell 4 of 10 at 120, collect 15 dividend, still hold 6 at 110.

    unrealized 6*110 - 600 = 60; realized 4*(120-100) = 80; dividends 15;
    costs 2 + 2 = 4  ->  151 on 1002 invested.
    """
    txs = [_tx(), _tx(kind="SELL", qty=4.0, price=120.0, date="2026-02-05")]
    rows = hs.holdings_rows(_bundle(txs, {"X1": _price(110.0)}, {"X1": 15.0}))
    r = rows[0]
    assert r["shares_held"] == 6.0
    assert r["unrealized_eur"] == 60.0
    assert r["realized_eur"] == 80.0
    assert r["dividends_eur"] == 15.0
    assert r["costs_eur"] == 4.0
    assert r["total_eur"] == 151.0
    assert r["total_pct"] == 15.07  # 151 / 1002


def test_total_pct_is_measured_against_everything_ever_invested():
    """Selling almost the whole position must not inflate the percentage.

    Sell 9 of 10 at 120: realized 180, one share left worth 110 against a
    remaining basis of 100, costs 4 -> a lifetime result of 186. Divided by
    that 100 of remaining basis it would read as +186%; against the 1002
    actually invested it is the +19% the position really returned.
    """
    txs = [_tx(), _tx(kind="SELL", qty=9.0, price=120.0, date="2026-02-05")]
    rows = hs.holdings_rows(_bundle(txs, {"X1": _price(110.0)}))
    r = rows[0]
    assert r["invested_ex_costs"] == 100.0
    assert r["total_eur"] == 186.0
    assert r["total_pct"] == 18.56  # 186 / 1002, not / 100


def test_the_four_reported_parts_add_up_to_the_reported_total():
    """Totale W/V must equal the column the position page prints above it.

    Prices chosen so every term needs rounding: summing the raw floats and
    rounding once puts the total a cent off its own rows, which is what the
    real portfolio did (814,84 + 117,26 + 45,47 - 11,00 under a total of
    966,58). A cent of rounding lands in the total, not between the reader and
    a subtraction they can check.
    """
    txs = [
        _tx(qty=7.0, price=100.005, fee=1.005),
        _tx(kind="SELL", qty=3.0, price=120.005, fee=1.005, date="2026-02-05"),
    ]
    r = hs.holdings_rows(_bundle(txs, {"X1": _price(110.005)}, {"X1": 15.005}))[0]
    assert r["unrealized_eur"] + r["realized_eur"] + r["dividends_eur"] - r["costs_eur"] == r["total_eur"]


def test_unpriced_position_reports_no_result_at_all():
    """Totaal contains the unrealized leg, so it is unknown too — a position
    that cannot be priced must not report its realized gain as its total."""
    txs = [_tx(), _tx(kind="SELL", qty=4.0, price=120.0, date="2026-02-05")]
    rows = hs.holdings_rows(_bundle(txs, {}, {"X1": 15.0}))
    r = rows[0]
    assert r["current_value"] is None
    assert r["unrealized_eur"] is None and r["unrealized_pct"] is None
    assert r["total_eur"] is None and r["total_pct"] is None
    # The parts that do not depend on a price are still reported.
    assert r["realized_eur"] == 80.0
    assert r["dividends_eur"] == 15.0


def test_a_free_position_has_no_percentage_rather_than_zero():
    """Nothing invested means the return is undefined; 0,00% would be a claim."""
    tx = _tx(qty=1.0, price=0.0, fee=0.0)
    rows = hs.holdings_rows(_bundle([tx], {"X1": _price(5.0)}))
    assert rows[0]["unrealized_pct"] is None
    assert rows[0]["total_pct"] is None


def test_closed_positions_do_not_appear():
    txs = [_tx(), _tx(kind="SELL", qty=10.0, price=120.0, date="2026-02-05")]
    assert hs.holdings_rows(_bundle(txs, {"X1": _price(110.0)})) == []


# ---------------------------------------------------------------------------
# Today
# ---------------------------------------------------------------------------


def test_day_figures_come_from_the_previous_close():
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price(110.0, prev=100.0)}))
    assert rows[0]["day_eur"] == 100.0  # 10 shares, +10 each
    assert rows[0]["day_pct"] == 10.0


def test_day_figures_are_absent_without_a_previous_close():
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price(110.0)}))
    assert rows[0]["day_eur"] is None and rows[0]["day_pct"] is None


# ---------------------------------------------------------------------------
# The header strip
# ---------------------------------------------------------------------------


def test_totals_sum_the_rows_and_flag_completeness():
    txs = [
        _tx(isin="X1", name="Fund X"),
        _tx(isin="X2", name="Fund Y", qty=5.0, price=200.0),
    ]
    prices = {"X1": _price(110.0, prev=100.0), "X2": _price(220.0, prev=200.0, currency="EUR")}
    prices["X2"]["ticker"] = "X2.AS"
    bundle = _bundle(txs, prices)
    totals = hs.holdings_totals(hs.holdings_rows(bundle), bundle)

    assert totals["value"] == 2200.0  # 1100 + 1100
    assert totals["num_positions"] == 2
    assert totals["unrealized"]["eur"] == 200.0
    assert totals["total"]["eur"] == 196.0  # 200 - 4 costs
    assert totals["total"]["complete"] is True
    assert totals["day"]["delta_eur"] == 200.0


def test_totals_stay_visible_but_incomplete_when_a_position_has_no_price():
    txs = [_tx(isin="X1"), _tx(isin="X2", name="Fund Y", qty=5.0, price=200.0)]
    bundle = _bundle(txs, {"X1": _price(110.0)})
    totals = hs.holdings_totals(hs.holdings_rows(bundle), bundle)

    assert totals["prices_available"] is False
    assert totals["total"]["complete"] is False
    assert totals["total"]["eur"] == 98.0  # only the priced position
    # The unpriced one still contributed its costs to the breakdown strip.
    assert totals["costs_eur"] == 4.0


# ---------------------------------------------------------------------------
# The dashboard's cost total
# ---------------------------------------------------------------------------
# The dashboard shows one figure this tab does not: transaction costs over the
# *whole* portfolio, closed positions included. The tests below pin the reason
# it is presented as "of which", never as a fourth term in the breakdown.


def test_total_costs_covers_closed_positions_too():
    """The Portfolio tab counts only open positions; the dashboard's
    total_gain covers everything ever traded, so its cost total must too.
    """
    txs = [
        _tx(isin="OPEN", fee=2.0),
        _tx(isin="GONE", fee=2.0, autofx=-0.5),
        _tx(isin="GONE", kind="SELL", qty=10.0, price=120.0, fee=3.0, date="2026-02-05"),
    ]
    # 2 on the open buy, 2 + 0,50 autofx on the closed buy, 3 on its sell.
    assert portfolio.total_transaction_costs(txs) == 7.5

    summary = _bundle(txs, {"OPEN": _price(110.0)}).summary
    assert summary["total_costs"] == 7.5
    # The tab's own strip sees only the one position still open.
    rows = hs.holdings_rows(_bundle(txs, {"OPEN": _price(110.0)}))
    assert sum(r["costs_eur"] for r in rows) == 2.0


def test_total_gain_already_has_the_costs_deducted():
    """Buy at 100, price still 100: the whole result is the fee, negative.

    This is what makes a "Transactiekosten" chip alongside Ongerealiseerd and
    Gerealiseerd wrong — the costs are not a missing fourth term, they are
    already inside the other two.
    """
    summary = _bundle([_tx(fee=2.0)], {"X1": _price(100.0)}).summary
    assert summary["total_costs"] == 2.0
    assert summary["total_gain"] == -2.0
    assert summary["unrealized_gain"] == -2.0


def test_the_three_chips_still_add_up_to_the_headline():
    """Ongerealiseerd + Gerealiseerd + Dividend = the hero's Totaalrendement.

    The dashboard builds its headline as total_gain + dividends and its chips
    from these three; adding total_costs as a fourth would break the identity
    by exactly the cost amount.
    """
    txs = [_tx(), _tx(kind="SELL", qty=4.0, price=120.0, date="2026-02-05")]
    s = _bundle(txs, {"X1": _price(110.0)}, {"X1": 15.0}).summary
    s = {**s, "total_dividends": 15.0}  # dividends reach the summary via its own arg

    headline = s["total_gain"] + s["total_dividends"]
    chips = s["unrealized_gain"] + s["realized_gain"] + s["total_dividends"]
    assert round(chips, 2) == round(headline, 2)
    assert round(chips + s["total_costs"], 2) != round(headline, 2)


# ---------------------------------------------------------------------------
# The dashboard's breakdown as a sum
# ---------------------------------------------------------------------------


def test_gross_split_makes_the_breakdown_add_up():
    """ongerealiseerd + gerealiseerd + dividend - kosten = totaalrendement.

    The identity the dashboard hero prints. It only holds on the *gross*
    figures: with the net ones the costs are already inside the first two
    terms, and the fourth line would subtract them a second time.
    """
    txs = [
        _tx(isin="X1", fee=2.0),
        _tx(isin="X1", kind="SELL", qty=4.0, price=120.0, fee=2.0, date="2026-02-05"),
        _tx(isin="GONE", fee=1.0),
        _tx(isin="GONE", kind="SELL", qty=10.0, price=130.0, fee=1.0, date="2026-03-05"),
    ]
    bundle = _bundle(txs, {"X1": _price(110.0)})
    s = {**bundle.summary, **hs.gross_result_split(bundle)}
    dividends = 15.0

    headline = s["total_gain"] + dividends
    parts = s["unrealized_gain_ex_costs"] + s["realized_gain_ex_costs"] + dividends - s["total_costs"]
    assert round(parts, 2) == round(headline, 2)


def test_gross_split_differs_from_the_net_one_by_exactly_the_costs():
    """Nothing is created or lost by lifting the costs out — they just move
    from inside the two terms to their own line."""
    txs = [
        _tx(isin="X1", fee=2.0),
        _tx(isin="GONE", fee=1.0),
        _tx(isin="GONE", kind="SELL", qty=10.0, price=130.0, fee=1.0, date="2026-03-05"),
    ]
    bundle = _bundle(txs, {"X1": _price(110.0)})
    g = hs.gross_result_split(bundle)
    s = bundle.summary

    lifted = (g["unrealized_gain_ex_costs"] - s["unrealized_gain"]) + (g["realized_gain_ex_costs"] - s["realized_gain"])
    assert round(lifted, 2) == s["total_costs"] == 4.0
    # And each side gets the costs that belong to it: 2 on the open position,
    # 1 + 1 on the one that was bought and sold.
    assert round(g["unrealized_gain_ex_costs"] - s["unrealized_gain"], 2) == 2.0
    assert round(g["realized_gain_ex_costs"] - s["realized_gain"], 2) == 2.0


def test_gross_split_ignores_unpriced_positions_like_the_summary_does():
    """An unpriced holding must not drag its cost basis into the unrealized
    leg while its value is absent — that would print a phantom loss."""
    txs = [_tx(isin="X1", fee=2.0), _tx(isin="X2", fee=2.0)]
    bundle = _bundle(txs, {"X1": _price(110.0)})
    g = hs.gross_result_split(bundle)
    # Only X1 counts: 1100 value against a 1000 cost basis.
    assert g["unrealized_gain_ex_costs"] == 100.0


# ---------------------------------------------------------------------------
# Aandelen vs. Trackers
# ---------------------------------------------------------------------------
# DeGiro's export carries no product type, so the grouping is read off the
# product name. These are the real names from a live portfolio.


def test_funds_are_recognised_as_trackers():
    for name in [
        "VANGUARD S&P 500 UCITS ETF USD DIS",
        "ISHARES CORE EURO STOXX 50 UCITS ETF EUR DIST",
        "STST SPDR MSCI WORLD TECHNOLOGY UCITS ETF",
        "VANECK AEX UCITS ETF",
    ]:
        assert hs.asset_type(name) == "tracker", name


def test_a_fund_without_etf_or_ucits_in_its_name_is_still_a_tracker():
    """The iBonds row is the one that breaks a naive keyword check: DeGiro
    abbreviates iShares to "ISHS" and the name says neither ETF nor UCITS."""
    assert hs.asset_type("ISHS V-IBDS DEC 2026 TERM EO CREG.SHS () EUR DIS. ON") == "tracker"


def test_shares_are_not_mistaken_for_trackers():
    for name in ["NN GROUP NV", "ASML HOLDING", "KONINKLIJKE PHILIPS", "ADYEN NV"]:
        assert hs.asset_type(name) == "share", name


def test_issuer_names_that_are_also_listed_companies_do_not_misfile_their_shares():
    """Invesco and Amundi are listed companies as well as fund issuers, so
    their names must not be tokens — their funds carry UCITS/ETF anyway."""
    assert hs.asset_type("INVESCO LTD") == "share"
    assert hs.asset_type("AMUNDI SA") == "share"
    assert hs.asset_type("AMUNDI MSCI WORLD UCITS ETF") == "tracker"


def test_rows_carry_their_type_and_venue():
    rows = hs.holdings_rows(_bundle([_tx(isin="X1", name="NN GROUP NV", exchange="EAM")], {"X1": _price(110.0)}))
    assert rows[0]["asset_type"] == "share"
    assert rows[0]["exchange"] == "EAM"


def test_venue_is_absent_rather_than_wrong_when_unknown():
    rows = hs.holdings_rows(_bundle([_tx()], {"X1": _price(110.0)}))
    assert rows[0]["exchange"] is None


# ---------------------------------------------------------------------------
# One position per (ISIN, exchange)
# ---------------------------------------------------------------------------
# DeGiro holds a position per product *and* venue, each with its own average
# price. The same ETF on Amsterdam and on Tradegate is two lines in their app,
# and this tab has to be readable beside it.


def test_the_same_fund_on_two_venues_is_two_positions():
    txs = [
        _tx(isin="X1", qty=10.0, price=100.0, exchange="EAM"),
        _tx(isin="X1", qty=4.0, price=120.0, exchange="TDG", date="2026-02-05"),
    ]
    rows = hs.holdings_rows(_bundle(txs, {"X1": _price(130.0)}))
    assert len(rows) == 2

    by_venue = {r["exchange"]: r for r in rows}
    assert by_venue["EAM"]["shares_held"] == 10.0
    assert by_venue["EAM"]["avg_cost_ex_costs"] == 100.0
    assert by_venue["TDG"]["shares_held"] == 4.0
    assert by_venue["TDG"]["avg_cost_ex_costs"] == 120.0


def test_a_sale_only_releases_the_basis_of_its_own_venue():
    """The reason this is a different sum, not a regrouping.

    Buy 10 at 100 on EAM and 10 at 200 on TDG, then sell all 10 EAM shares.
    Per venue, TDG keeps its own 200 average. Walked together the sale would
    release half of the *combined* basis, leaving the remaining ten shares at
    an average of 150 — a number that appears nowhere in DeGiro.
    """
    txs = [
        _tx(isin="X1", qty=10.0, price=100.0, exchange="EAM"),
        _tx(isin="X1", qty=10.0, price=200.0, exchange="TDG", date="2026-01-06"),
        _tx(isin="X1", kind="SELL", qty=10.0, price=110.0, exchange="EAM", date="2026-02-05"),
    ]
    rows = hs.holdings_rows(_bundle(txs, {"X1": _price(210.0)}))
    assert len(rows) == 1  # EAM is closed
    assert rows[0]["exchange"] == "TDG"
    assert rows[0]["avg_cost_ex_costs"] == 200.0

    merged = hs.cost_breakdown(txs)["X1"]
    assert round(merged["cost_ex"] / merged["shares"], 2) == 150.0


def test_venue_split_leaves_the_portfolio_value_unchanged():
    """Splitting a position must not move the total this tab reports — only
    how it is divided over rows."""
    txs = [
        _tx(isin="X1", qty=10.0, price=100.0, exchange="EAM"),
        _tx(isin="X1", qty=4.0, price=120.0, exchange="TDG", date="2026-02-05"),
        _tx(isin="X2", qty=5.0, price=50.0, exchange="EAM"),
    ]
    bundle = _bundle(txs, {"X1": _price(130.0), "X2": _price(60.0)})
    rows = hs.holdings_rows(bundle)
    assert round(sum(r["current_value"] for r in rows), 2) == bundle.summary["total_value"]
    assert round(sum(r["shares_held"] for r in rows if r["isin"] == "X1"), 6) == 14.0


def test_dividends_are_split_over_the_venues_by_shares():
    """Dividends carry no venue, so they are attributed pro rata — and must
    still add up to what was actually received."""
    txs = [
        _tx(isin="X1", qty=10.0, price=100.0, exchange="EAM"),
        _tx(isin="X1", qty=30.0, price=100.0, exchange="TDG", date="2026-02-05"),
    ]
    rows = hs.holdings_rows(_bundle(txs, {"X1": _price(100.0)}, {"X1": 40.0}))
    by_venue = {r["exchange"]: r for r in rows}
    assert by_venue["EAM"]["dividends_eur"] == 10.0  # 10 of 40 shares
    assert by_venue["TDG"]["dividends_eur"] == 30.0
    assert sum(r["dividends_eur"] for r in rows) == 40.0


def test_day_change_rows_still_sum_to_the_portfolio_chip():
    """The header chip comes from the ISIN-level function; the split rows use
    the same formula, so the two must not drift apart."""
    txs = [
        _tx(isin="X1", qty=10.0, price=100.0, exchange="EAM"),
        _tx(isin="X1", qty=10.0, price=100.0, exchange="TDG", date="2026-02-05"),
    ]
    bundle = _bundle(txs, {"X1": _price(110.0, prev=100.0)})
    rows = hs.holdings_rows(bundle)
    chip = hs.holdings_totals(rows, bundle)["day"]
    assert round(sum(r["day_eur"] for r in rows), 2) == chip["delta_eur"] == 200.0


def test_transactions_without_a_venue_still_form_one_position():
    """Older rows can have no Beurs column; they must not vanish or split."""
    rows = hs.holdings_rows(_bundle([_tx(), _tx(date="2026-02-05")], {"X1": _price(110.0)}))
    assert len(rows) == 1
    assert rows[0]["exchange"] is None
    assert rows[0]["shares_held"] == 20.0
