"""
net_worth.split: the Python port of frontend/lib/net-worth-bridge.ts.

change = saved + market + bank & cash + debt, always. These cases are the ones
where a naive split goes wrong: a repayment, money to the broker that comes back
under another label, money of friends, and the shared-costs option.
"""

import pytest

from domain.money.net_worth import split, split_per_month


def _p(d, *, investments=0.0, bank=0.0, debt=0.0, held=0.0, portfolio=None, invested=None, dividends=None):
    p = {"d": d, "investments": investments, "bank": bank, "debt": debt, "held": held,
         "net": investments + bank + debt}
    if portfolio is not None:
        p |= {"portfolio": portfolio, "portfolio_invested": invested, "portfolio_dividends": dividends or 0.0}
    return p


def _f(d, saved=0.0, to_investments=0.0, others=0.0, unlabelled=0.0, bank_flow=0.0):
    return {"d": d, "saved": saved, "to_investments": to_investments, "others": others,
            "unlabelled": unlabelled, "bank_flow": bank_flow}


def _adds_up(s):
    assert s["saved"] + s["market"] + s["bank"] + s["debt"] == pytest.approx(s["change"])
    d = s["detail"]
    assert d["friends"] + d["unlabelled"] + d["corrections"] + d["transfers"] == pytest.approx(s["bank"])


def test_repayment_moves_from_bank_to_debt():
    start = _p("2026-01-31", bank=1000, debt=-2000)
    end = _p("2026-02-28", bank=500, debt=-1500)
    s = split(start, end, [_f("2026-01-01"), _f("2026-02-10", bank_flow=-500)])
    assert s["change"] == 0
    assert s["debt"] == pytest.approx(500)
    assert s["bank"] == pytest.approx(-500)
    assert s["saved"] == 0 and s["market"] == 0
    assert s["detail"]["transfers"] == pytest.approx(-500) and s["detail"]["corrections"] == 0
    _adds_up(s)


def test_money_back_from_broker_under_another_label_is_no_market_result():
    # 1000 out labelled as investing, bought and sold again, 1000 back labelled as
    # own account: only the price change of the holdings is market.
    start = _p("2026-01-31", investments=10000, bank=2000, portfolio=10000, invested=8000)
    end = _p("2026-02-28", investments=10300, bank=2000, portfolio=10300, invested=8000)
    flows = [_f("2026-01-01"), _f("2026-02-03", to_investments=1000, bank_flow=-1000),
             _f("2026-02-20", bank_flow=1000)]
    s = split(start, end, flows)
    assert s["market"] == pytest.approx(300)
    assert s["bank"] == pytest.approx(0)
    _adds_up(s)
    # Without the holdings' own figures it falls back to the labels, and gets it wrong
    # in exactly this case: that is why the holdings come first.
    old = split({k: v for k, v in start.items() if not k.startswith("portfolio")},
                {k: v for k, v in end.items() if not k.startswith("portfolio")}, flows)
    assert old["market"] == pytest.approx(-700)
    _adds_up(old)


def test_dividend_counts_as_market():
    start = _p("2026-01-31", investments=5000, portfolio=5000, invested=5000, dividends=10)
    end = _p("2026-02-28", investments=5000, bank=0, portfolio=5000, invested=5000, dividends=40)
    s = split(start, end, [_f("2026-01-01")])
    assert s["market"] == pytest.approx(30)


def test_friends_money_held_is_no_gain():
    # Friends pay 500 in before you pay the holiday: it is on your account but held.
    start = _p("2026-01-31", bank=1000)
    end = _p("2026-02-28", bank=1500, debt=-500, held=-500)
    s = split(start, end, [_f("2026-01-01"), _f("2026-02-05", others=500, bank_flow=500)])
    assert s["change"] == 0
    assert s["debt"] == 0 and s["bank"] == 0 and s["detail"]["friends"] == 0
    _adds_up(s)


def test_shared_costs_option_moves_own_share_to_saved():
    # Paid 300 for a group dinner, 200 came back: 100 is your own share.
    start = _p("2026-01-31", bank=1000)
    end = _p("2026-02-28", bank=900)
    flows = [_f("2026-01-01"), _f("2026-02-05", others=-300, bank_flow=-300), _f("2026-02-09", others=200, bank_flow=200)]
    plain = split(start, end, flows)
    assert plain["saved"] == 0 and plain["bank"] == pytest.approx(-100)
    assert plain["detail"]["friends"] == pytest.approx(-100) and plain["shared"] == 0
    _adds_up(plain)
    shared = split(start, end, flows, shared_as_spending=True)
    assert shared["saved"] == pytest.approx(-100) and shared["shared"] == pytest.approx(-100)
    assert shared["bank"] == pytest.approx(0) and shared["detail"]["friends"] == 0
    _adds_up(shared)


def test_saved_unlabelled_and_corrections():
    start = _p("2026-01-31", bank=1000)
    end = _p("2026-02-28", bank=1650)
    flows = [_f("2026-01-01"), _f("2026-02-21", saved=600, bank_flow=600), _f("2026-02-22", unlabelled=-50, bank_flow=-50)]
    s = split(start, end, flows)
    assert s["saved"] == pytest.approx(600)
    assert s["detail"]["unlabelled"] == pytest.approx(-50)
    assert s["detail"]["corrections"] == pytest.approx(100)   # balance went up more than the transactions say
    _adds_up(s)


def test_flows_only_after_start_and_up_to_end():
    start, end = _p("2026-02-01", bank=0), _p("2026-02-03", bank=0)
    flows = [_f("2026-02-01", saved=1), _f("2026-02-02", saved=10), _f("2026-02-03", saved=100), _f("2026-02-04", saved=1000)]
    assert split(start, end, flows)["saved"] == pytest.approx(110)


def test_before_the_bank_data_there_is_no_split():
    s = split(_p("2025-12-01", bank=5), _p("2026-02-28", bank=10), [_f("2026-01-15")])
    assert s["change"] == 5 and s["saved"] is None and s["detail"] is None
    assert split(_p("2026-01-01"), _p("2026-01-02", bank=1), [])["saved"] is None


def test_per_month_runs_from_month_end_to_month_end():
    points = [_p(d, bank=b) for d, b in [("2026-01-30", 100), ("2026-01-31", 110), ("2026-02-01", 120),
                                           ("2026-02-28", 150), ("2026-03-01", 160), ("2026-03-02", 170)]]
    flows = [_f("2026-01-01")]
    rows = split_per_month(points, flows, lambda d: d[:7])
    assert [r["month"] for r in rows] == ["2026-01", "2026-02", "2026-03"]
    assert rows[0]["split"] is None
    assert (rows[1]["from"], rows[1]["to"]) == ("2026-01-31", "2026-02-28")
    assert rows[1]["split"]["change"] == pytest.approx(40) and not rows[1]["partial"]
    assert rows[2]["split"]["change"] == pytest.approx(20) and rows[2]["partial"]   # still running

    cut = split_per_month(points, flows, lambda d: d[:7], until="2026-02-01")
    assert [r["month"] for r in cut] == ["2026-01", "2026-02"]
    assert cut[1]["to"] == "2026-02-01" and cut[1]["partial"]


def test_bank_reads_as_listed_transactions_corrections_and_the_rest():
    # 40 cash withdrawn (lands in Bank & cash), 400 to a savings account that only
    # has balances: it comes back as a correction, not as a transaction.
    start = _p("2026-01-31", bank=1000)
    end = _p("2026-02-28", bank=960)
    flows = [_f("2026-01-01") | {"bank_tx": 0.0},
             _f("2026-02-05", bank_flow=-440) | {"bank_tx": -40.0}]
    s = split(start, end, flows)
    d = s["detail"]
    assert d["listed"] == pytest.approx(-40)
    assert d["corrections"] == pytest.approx(400)
    assert d["other_half"] == pytest.approx(-400)
    assert d["listed"] + d["corrections"] + d["other_half"] == pytest.approx(s["bank"])
    # An older answer without bank_tx gives no listed sum.
    assert split(start, end, [_f("2026-01-01"), _f("2026-02-05", bank_flow=-440)])["detail"]["listed"] is None
