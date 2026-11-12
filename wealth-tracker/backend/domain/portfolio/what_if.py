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
in or take out after *start*. The kept portfolio gets the same money, invested
the way it was: on a day the value card's "Deposited" line (buys minus sells,
costs included) goes up by D, the kept portfolio buys its own mix for D at that
day's prices, so every holding grows by the same factor; when it goes down it
sells in the same proportion.

    kept(t) = s(t) × Σ quantity × close(t),   s(t) = s(t−1) × (V + D) / V

with V the kept value that day before the money. Money parked as cash at the
broker is in neither line, because neither line counts cash. On the day of
*start* both lines are the same number; after it the gap is what the switch did,
not what new money earned in only one of them (as cash without return, it would
make every later deposit count for the new portfolio).

  - growth(holdings, start, closes)
        The kept holdings' value relative to the start day, without any money in
        or out: the line the Returns tab sets next to its time-weighted return and
        the indices, which have no deposits in them either.
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
    scale = 1.0
    previous = base_invested
    for p in points:
        value = scale * sum(h["quantity"] * price(h, p["d"]) for h in holdings)
        money = p["invested"] - previous
        previous = p["invested"]
        if money and value > 0:
            # Buy (or sell) the kept mix in proportion, at this day's prices.
            scale *= max(value + money, 0.0) / value
            value = max(value + money, 0.0)
        out.append({"d": p["d"], "actual": round(p["value"], 2), "kept": round(value, 2)})
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
            # Both over what was there at the start plus half of what was deposited
            # since (simple Dietz: money that came in halfway was invested for about
            # half the time). Both got the same money, so the same yardstick.
            "actual_pct": pct(actual_gain, a["actual"] + max(deposited, 0) / 2),
            "kept_pct": pct(kept_gain, start_value + max(deposited, 0) / 2),
        },
        "holdings": per_holding,
        "estimated": [{"isin": i, "name": names.get(i, i), "base": base} for i, base in sorted(estimated.items())],
    }


def growth(holdings: list[dict], start: datetime.date, closes: dict[str, list[tuple[str, float]]]) -> dict:
    """{points: [{d, v}], estimated}: the kept holdings' value over the start day's.

    v is 1.0 on *start* and follows every day any holding has a close, up to the
    last one. No money goes in or out, so this is the kept portfolio's return
    as such. With adjusted closes (dividends reinvested) it is on the same basis
    as a time-weighted return and a total-return index.

    A holding without any close stays at its cost per share and is named in
    `estimated`; without a single close there is no line at all.
    """
    first = start.isoformat()
    if not any(closes.get(h["isin"]) for h in holdings):
        return {"points": [], "estimated": []}
    estimated = {}

    def price(h: dict, day: str) -> float:
        p = _price_on(closes.get(h["isin"], []), day)
        if p is not None:
            return p
        if not closes.get(h["isin"]):
            estimated[h["isin"]] = "purchase_price"
        else:
            # Listed only after the start: its first close stands in before that.
            p = closes[h["isin"]][0][1]
            estimated[h["isin"]] = "first_close"
            return p
        return h["cost_eur"] / h["quantity"] if h["quantity"] else 0.0

    def value(day: str) -> float:
        return sum(h["quantity"] * price(h, day) for h in holdings)

    base = value(first)
    if base <= 0:
        return {"points": [], "estimated": []}
    days = sorted({d for h in holdings for d, _ in closes.get(h["isin"], []) if d > first})
    points = [{"d": first, "v": 1.0}] + [{"d": d, "v": round(value(d) / base, 6)} for d in days]
    names = {h["isin"]: h["name"] for h in holdings}
    return {
        "points": points,
        "estimated": [{"isin": i, "name": names.get(i, i), "base": b} for i, b in sorted(estimated.items())],
    }
