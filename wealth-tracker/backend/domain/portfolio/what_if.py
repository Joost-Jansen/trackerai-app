"""
what_if.py — the portfolio you had on a date, and what it would be worth had you kept it.

Two questions with one ingredient, the holdings on a day:

  - holdings_on(transactions, day)
        What you held at the end of *day*, replayed from the stored transactions:
        quantity and cost basis per ISIN. Nothing new is stored for it; the
        transactions are the record.
  - compare(actual_points, holdings, start, closes, live_prices)
        From *start* to today, your real portfolio next to the one you would have
        had if you had stopped trading at the end of *start*.

A snapshot (database.portfolio_snapshots) stores the outcome of holdings_on with a
name, so a comparison keeps working after the transactions behind it are
uploaded again, and an assistant can find "the portfolio before the switch" by
name.

How the two lines stay comparable. The real line keeps moving with money you put
in or take out after *start*; the kept portfolio did not trade. So the kept line
gets the same net money as cash, without return:

    kept(t) = Σ quantity × close(t)  +  (deposited(t) − deposited(start))

where deposited is the value card's "Deposited" line (buys minus sells, costs
included). On the day of *start* both lines are the same number. After it, the
gap between them is exactly what the trading since then earned or cost —
transaction costs included, since a buy's cost raises deposited but not the
value. Dividends are left out of both, as on the value card.
"""

from __future__ import annotations

import datetime
from bisect import bisect_right

#: A share count this small is a rounding remainder of a sale, not a holding.
_EPSILON = 1e-9


def holdings_on(transactions: list[dict], day: datetime.date) -> list[dict]:
    """[{isin, name, quantity, cost_eur}] held at the end of *day*, largest cost first.

    cost_eur is the weighted-average cost of what is left (a sale takes its share
    of the cost with it), the same arithmetic as the value card's fallback price.
    """
    held: dict[str, float] = {}
    cost: dict[str, float] = {}
    names: dict[str, str] = {}
    cutoff = day.isoformat()
    for t in sorted(transactions, key=lambda t: (t["date"], t.get("id") or 0)):
        if t["date"] > cutoff:
            break
        isin = t["isin"]
        names[isin] = t.get("name") or names.get(isin) or isin
        qty = float(t["quantity"] or 0)
        if t["transaction_type"] == "BUY":
            held[isin] = held.get(isin, 0.0) + qty
            cost[isin] = cost.get(isin, 0.0) + abs(t["total_eur"] or 0.0)
        elif t["transaction_type"] == "SELL":
            before = held.get(isin, 0.0)
            after = max(before - qty, 0.0)
            cost[isin] = cost.get(isin, 0.0) * (after / before) if before > 0 else 0.0
            held[isin] = after
    out = [
        {"isin": isin, "name": names[isin], "quantity": round(q, 6), "cost_eur": round(cost.get(isin, 0.0), 2)}
        for isin, q in held.items()
        if q > _EPSILON
    ]
    return sorted(out, key=lambda h: -h["cost_eur"])


def _price_on(closes: list[tuple[str, float]], day: str) -> float | None:
    """The last close on or before *day* (carry-forward over weekends and holidays)."""
    i = bisect_right(closes, (day, float("inf")))
    return closes[i - 1][1] if i else None


def compare(
    actual_points: list[dict],
    holdings: list[dict],
    start: datetime.date,
    closes: dict[str, list[tuple[str, float]]],
    live_prices: dict[str, float] | None = None,
) -> dict:
    """The real portfolio and the kept one, per day from *start* to the last point.

    *actual_points* are the value card's points ({d, value, invested}, today's
    pinned to the live total). *closes* is {isin: [(iso date, EUR close), …]}
    sorted by date. *live_prices* ({isin: EUR price}) values the kept holdings on
    today's point, the same way the real line's last point is valued; without one
    the last close stands.

    A holding with no price on a day falls back to its live price, then to its
    cost per share; it is then listed in `estimated`, because a line that rests on
    a stand-in looks exactly like one that did not move.
    """
    live_prices = live_prices or {}
    today = datetime.date.today().isoformat()
    first = start.isoformat()
    # The day itself may have no point (before the first trade nothing is drawn):
    # the kept portfolio then starts at the first point after it.
    points = [p for p in actual_points if p["d"] >= first]
    if not points or not holdings:
        return {"points": [], "summary": None, "holdings": [], "estimated": []}
    base_invested = points[0]["invested"]

    estimated: dict[str, str] = {}

    def price(h: dict, day: str) -> float:
        isin = h["isin"]
        if day == today and isin in live_prices:
            return live_prices[isin]
        p = _price_on(closes.get(isin, []), day)
        if p is not None:
            return p
        if isin in live_prices:
            estimated[isin] = "current_price"
            return live_prices[isin]
        estimated[isin] = "purchase_price"
        return h["cost_eur"] / h["quantity"] if h["quantity"] else 0.0

    out = []
    for p in points:
        kept = sum(h["quantity"] * price(h, p["d"]) for h in holdings)
        out.append(
            {
                "d": p["d"],
                "actual": round(p["value"], 2),
                "kept": round(kept + p["invested"] - base_invested, 2),
            }
        )
    a, b = out[0], out[-1]
    # On the start day the kept line is the real value, by construction; the
    # holdings' own value is what the start is measured from.
    start_value = round(sum(h["quantity"] * price(h, a["d"]) for h in holdings), 2)
    deposited = round(points[-1]["invested"] - points[0]["invested"], 2)
    actual_gain = round(b["actual"] - a["actual"] - deposited, 2)
    kept_gain = round(b["kept"] - a["kept"] - deposited, 2)
    per_holding = []
    for h in holdings:
        v0 = h["quantity"] * price(h, a["d"])
        v1 = h["quantity"] * price(h, b["d"])
        per_holding.append(
            {
                "isin": h["isin"],
                "name": h["name"],
                "quantity": h["quantity"],
                "value_start": round(v0, 2),
                "value_end": round(v1, 2),
                "change_eur": round(v1 - v0, 2),
                "change_pct": round(100 * (v1 / v0 - 1), 2) if v0 else None,
            }
        )
    per_holding.sort(key=lambda r: -r["value_start"])

    def pct(gain: float, over: float) -> float | None:
        return round(100 * gain / over, 2) if over else None

    names = {h["isin"]: h["name"] for h in holdings}
    return {
        "points": out,
        "summary": {
            "start": a["d"],
            "end": b["d"],
            "actual_start": a["actual"],
            "actual_end": b["actual"],
            "kept_start": start_value,
            "kept_end": b["kept"],
            "deposited_since": deposited,
            "actual_gain": actual_gain,
            "kept_gain": kept_gain,
            "difference": round(actual_gain - kept_gain, 2),
            # The real portfolio over what was there at the start plus half of what was
            # deposited since (simple Dietz: money that came in halfway was invested for
            # about half the time). The kept one over its start value: it got no new money
            # into its holdings, only beside them as cash.
            "actual_pct": pct(actual_gain, a["actual"] + max(deposited, 0) / 2),
            "kept_pct": pct(kept_gain, start_value),
        },
        "holdings": per_holding,
        "estimated": [{"isin": i, "name": names.get(i, i), "base": base} for i, base in sorted(estimated.items())],
    }
