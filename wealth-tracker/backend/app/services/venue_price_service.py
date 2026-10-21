"""The price per position: that of the exchange where the position actually sits.

DeGiro holds a fund on two exchanges as two positions, each with the price of
its own exchange. This app stored one Yahoo price per ISIN, and Yahoo has no
Tradegate feed, so a TDG position stood at the XETRA price. Now:

  * **Per position** (Portfolio tab, detail screen): a position on an exchange
    with a source of its own — only Tradegate — gets that price, the last
    traded price. Every other position, or a TDG position whose Tradegate
    price is missing or missed a close, gets the ISIN's Yahoo price, as
    before.
  * **Per ISIN** (dashboard, day chip, charts, returns, Details): that code
    calculates with one price per ISIN times all units. `effective_prices`
    gives it the unit-weighted price over the positions, so an ISIN amount is
    exactly the sum of its positions — and that code itself needs to know
    nothing about exchanges. For a fund on one exchange that price is simply
    the price of that exchange; only for a fund on two exchanges with
    different prices is it an average, and then `blended` is set on it.

The Yahoo ticker stays on the row: the price history and the minute bars
still come from there. Tradegate provides no history.
"""

from app.core import price_refresh
from app.services import tradegate_service
from domain import database

#: Exchanges with a price source of their own → the name of that source.
PROVIDERS = {tradegate_service.VENUE_CODE: "tradegate"}


def open_shares_by_venue(transactions: list[dict]) -> dict[tuple[str, str | None], float]:
    """{(isin, exchange): units} for every open position.

    The same grouping and the same clamp as holdings_service._walk (a sale never
    takes the quantity below zero), so "a position" here is exactly the row the
    Portfolio tab shows.
    """
    groups: dict[tuple[str, str | None], list[dict]] = {}
    for t in transactions:
        groups.setdefault((t["isin"], t.get("exchange") or None), []).append(t)

    shares_by_venue = {}
    for key, trades in groups.items():
        shares = 0.0
        for t in sorted(trades, key=lambda x: (x["date"], x["time"] or "")):
            if t["transaction_type"] == "BUY":
                shares += t["quantity"]
            elif t["transaction_type"] == "SELL":
                shares = max(shares - t["quantity"], 0.0)
        if shares > 0.0001:
            shares_by_venue[key] = shares
    return shares_by_venue


def usable(quote: dict | None) -> bool:
    """An exchange price that may count: in euros, with a price, and not from
    before a close it should have seen (price_refresh.is_stale). An old
    Tradegate price therefore does not push out the Yahoo price.
    """
    return bool(quote and quote.get("currency") == "EUR" and quote.get("price") and not price_refresh.is_stale(quote.get("fetched_at")))


def position_quote(isin: str, venue: str | None, yahoo_prices: dict[str, dict], venue_prices: dict[tuple[str, str], dict]) -> dict | None:
    """The price of one position, with `provider` added ("tradegate" or "yahoo").

    None when there is no usable euro price — the same rule as
    portfolio.calculate_positions: a price in another currency does not count.
    """
    if venue in PROVIDERS:
        quote = venue_prices.get((isin, venue))
        if usable(quote):
            return {**quote, "provider": PROVIDERS[venue]}
    yahoo = yahoo_prices.get(isin)
    if yahoo and yahoo.get("currency") == "EUR" and yahoo.get("price"):
        return {**yahoo, "provider": "yahoo"}
    return None


def effective_prices(transactions: list[dict], yahoo_prices: dict[str, dict], venue_prices: dict[tuple[str, str], dict]) -> dict[str, dict]:
    """The price per ISIN that gives per-ISIN code exactly the sum of the positions.

    Unchanged for every ISIN without a usable exchange price. Otherwise:
    price = Σ units × position price / Σ units, and the previous close likewise —
    but only if *every* counted position has one, because a half-weighted close
    would make a day move out of nothing.

    If one position of such an ISIN has no price at all (rare: no Yahoo price
    next to a Tradegate price), the positions with a price count for all units;
    the Portfolio tab shows that one row as unpriced.
    """
    if not venue_prices:
        return yahoo_prices

    by_isin: dict[str, list[tuple[str | None, float]]] = {}
    for (isin, venue), shares in open_shares_by_venue(transactions).items():
        by_isin.setdefault(isin, []).append((venue, shares))

    prices = dict(yahoo_prices)
    for isin, venues in by_isin.items():
        if not any(v in PROVIDERS and usable(venue_prices.get((isin, v))) for v, _ in venues):
            continue

        priced = [(shares, quote) for venue, shares in venues if (quote := position_quote(isin, venue, yahoo_prices, venue_prices))]
        total = sum(shares for shares, _ in priced)
        if total <= 0:
            continue

        if len(priced) == 1:
            # One position: its price verbatim, not a weighted mean of one that
            # prints 56,303999… where Tradegate said 56,304.
            price = priced[0][1]["price"]
            previous_close = priced[0][1].get("previous_close") or None
        else:
            price = sum(shares * q["price"] for shares, q in priced) / total
            if all((q.get("previous_close") or 0) > 0 for _, q in priced):
                previous_close = sum(shares * q["previous_close"] for shares, q in priced) / total
            else:
                previous_close = None
        stamps = [q["fetched_at"] for _, q in priced if q.get("fetched_at")]
        base = yahoo_prices.get(isin) or {}

        prices[isin] = {
            **base,
            "isin": isin,
            "ticker": base.get("ticker"),
            "price": price,
            "previous_close": previous_close,
            "currency": "EUR",
            # The oldest quote in the blend: that is how current this figure is.
            "fetched_at": min(stamps) if stamps else None,
            "providers": sorted({q["provider"] for _, q in priced}),
            "blended": len({round(q["price"], 6) for _, q in priced}) > 1,
        }
    return prices


# ---------------------------------------------------------------------------
# Storing and refreshing
# ---------------------------------------------------------------------------


def save_quote(conn, quote: dict | None) -> bool:
    """Stores a Tradegate response as the price of the TDG position.

    Only a current response *with* a last traded price: bid and ask are not the
    price of a position, and an old price served from the cache (`stale`) is
    already stored with its own fetch time.
    """
    if not quote or quote.get("status") != "ok" or quote.get("stale") or quote.get("last") is None:
        return False
    fetched_at = quote.get("fetched_at")
    if not fetched_at:
        return False
    database.save_venue_price(
        conn,
        isin=quote["isin"],
        venue=quote.get("venue") or tradegate_service.VENUE_CODE,
        price=quote["last"],
        previous_close=quote.get("previous_close"),
        currency=quote.get("currency") or "EUR",
        source=PROVIDERS[tradegate_service.VENUE_CODE],
        # The format save_price writes, so the Details tab and "oldest quote"
        # comparisons read one shape.
        fetched_at=fetched_at.replace("T", " "),
    )
    return True


def refresh(conn) -> dict:
    """Tradegate prices for every open TDG position of this user.

    Next to portfolio.refresh_all_prices, not inside it: that is Yahoo, this is
    a second source with its own cache and its own error handling. Never raises —
    a failed Tradegate leaves the previous price in place, and that falls back
    to Yahoo by itself as soon as it misses a close.
    """
    refreshed = failed = 0
    for isin, venue in open_shares_by_venue(database.load_transactions(conn)):
        if venue not in PROVIDERS:
            continue
        try:
            if save_quote(conn, tradegate_service.get_quote(isin)):
                refreshed += 1
            else:
                failed += 1
        except Exception as e:  # a database hiccup must not end the pass
            print(f"[venue-prices] {isin}/{venue}: {e!r}")
            failed += 1
    return {"refreshed": refreshed, "failed": failed}
