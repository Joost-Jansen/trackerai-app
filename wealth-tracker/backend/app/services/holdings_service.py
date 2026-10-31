"""
Per-position economics for the Portfolio tab.

portfolio.calculate_positions already gives every open position its shares,
price and value, but it knows exactly one cost basis: `total_eur`, which is
DeGiro's *fee-inclusive* total. This tab needs both sides of that split —

  GAK          the average price actually paid per share, transaction costs
               excluded, so it is comparable to the current price;
  Totale W/V   everything the position has delivered: the unrealized move,
               the gain locked in by earlier (partial) sells, dividends
               received, minus every transaction cost it ever incurred.

so the walk below tracks two bases at once. It is the same average-cost walk
portfolio.calculate_positions and calculate_closed_positions perform (a sell
releases its proportional share of the remaining basis); duplicating it rather
than extending those is deliberate — they feed the dashboard totals and the
Details tab, and their `total_invested` must keep meaning "incl. fees" there.

Naming: `_ex` is excluding transaction costs, `_gross` is including them.
"""

from app.core import price_refresh
from app.services import dashboard_service, tradegate_service, venue_price_service
from app.services.portfolio_service import PortfolioBundle
from domain import database
from domain.portfolio import brokers
from domain.portfolio import positions as portfolio
from domain.portfolio import series as charts


def _value_ex_costs(t: dict, costs: float) -> float:
    """The trade's EUR value with no fees in it, as a positive number.

    `value_eur` is exactly that column, so it is used whenever present. The
    fallback reconstructs it from `total_eur` for rows that predate the column
    or came from an export missing it — and the reconstruction differs by
    direction, because the costs are charged in the same direction both times:
    a buy pays value + costs, a sell receives value - costs.
    """
    value = t.get("value_eur")
    if value is not None:
        return abs(value)
    total = t.get("total_eur")
    if total is None:
        return 0.0
    return abs(total) - costs if t.get("transaction_type") == "BUY" else abs(total) + costs


def _walk(trades: list[dict]) -> dict:
    """The average-cost walk over one group of trades, in date order."""
    shares = 0.0
    cost_ex = 0.0  # basis excl. costs of the shares still held
    invested_gross = 0.0  # every euro ever paid on a buy, incl. costs
    realized_ex = 0.0  # price gain locked in by sells, excl. costs
    costs_total = 0.0

    for t in sorted(trades, key=lambda x: (x["date"], x["time"] or "")):
        costs = portfolio.transaction_cost(t)
        costs_total += costs
        value = _value_ex_costs(t, costs)
        qty = t["quantity"]

        if t["transaction_type"] == "BUY":
            shares += qty
            cost_ex += value
            invested_gross += value + costs
        elif t["transaction_type"] == "SELL":
            if shares > 0:
                # Clamp as calculate_positions does: selling more than the
                # data says is held (a missing buy) must not drive the
                # remaining basis negative.
                fraction = min(qty / shares, 1.0)
                released = cost_ex * fraction
                realized_ex += value - released
                cost_ex -= released
            shares = max(shares - qty, 0.0)

    return {
        "name": trades[0]["name"],
        "shares": shares,
        "cost_ex": cost_ex,
        "invested_gross": invested_gross,
        "realized_ex": realized_ex,
        "costs_total": costs_total,
    }


def _grouped(transactions: list[dict], key) -> dict:
    groups: dict = {}
    for t in transactions:
        groups.setdefault(key(t), []).append(t)
    return {k: _walk(trades) for k, trades in groups.items()}


def cost_breakdown(transactions: list[dict]) -> dict[str, dict]:
    """{isin: cost figures} for every ISIN that was ever traded.

    Closed positions are included — the caller filters, and keeping them means
    an ISIN that was sold to zero and bought back still carries its earlier
    realized gain and costs into the new position's Totale W/V.
    """
    return _grouped(transactions, lambda t: t["isin"])


def cost_breakdown_by_venue(transactions: list[dict]) -> dict[tuple[str, str | None], dict]:
    """The same walk, but per {(isin, exchange)} — one entry per *position*.

    DeGiro holds a position per product **and exchange**, each with its own
    average price: the same ETF bought on Amsterdam and on Tradegate is two
    lines in their app, with two different GAKs. Grouping by ISIN alone merges
    them, and once one venue has been sold the merged average is not a number
    that appears anywhere in DeGiro.

    This is not the same arithmetic as cost_breakdown() reduced by venue. A
    sell releases a proportion of the basis it belongs to, so where the venues
    are walked together a sale on Amsterdam also releases Tradegate cost. That
    is precisely the difference this function exists to remove — which is also
    why portfolio.calculate_positions is left alone: the dashboard, benchmarks
    and rebalancing all reason per ISIN, and should keep doing so.
    """
    return _grouped(transactions, lambda t: (t["isin"], t.get("exchange") or None))


def broker_of(t: dict) -> str:
    """The broker of a trade; rows from before brokers were stored are DeGiro's."""
    return t.get("broker") or database.LEGACY_BROKER


def cost_breakdown_by_position(transactions: list[dict]) -> dict[tuple[str, str, str | None], dict]:
    """The walk per {(isin, broker, exchange)}: one entry per line in a broker's app.

    cost_breakdown_by_venue with the broker added to the key. Two brokers each
    keep their own average price for the same fund, exactly as two exchanges at
    one broker do, so the Portfolio tab lists them apart; everything that
    reasons about the fund itself (dashboard, allocation, returns) still adds
    them up per ISIN.
    """
    return _grouped(transactions, lambda t: (t["isin"], broker_of(t), t.get("exchange") or None))


# Product names come from DeGiro's export, which carries no product type — so
# the Shares/Trackers split is read off the name, the way a person does.
#
# Only unambiguous tokens are listed. Issuer names that are *also* listed
# companies are deliberately absent: "Invesco" and "Amundi" would misfile their
# own shares, and their funds always carry "UCITS" or "ETF" anyway. The short
# forms (ISHS, ISHRS, VNGU, STST) are DeGiro's own abbreviations — see the same
# set in portfolio._NAME_EXPANSIONS — and they matter: the iBonds row reads
# "ISHS V-IBDS DEC 2026 TERM EO CREG.SHS () EUR DIS. ON", with neither "ETF"
# nor "UCITS" anywhere in it.
_TRACKER_TOKENS = {
    "ETF",
    "ETC",
    "ETN",
    "UCITS",
    "TRACKER",
    "TRACKERS",
    "ISHARES",
    "ISHS",
    "ISHRS",
    "SPDR",
    "STST",
    "VANECK",
    "VANGUARD",
    "VNGU",
    "VGRD",
    "XTRACKERS",
    "WISDOMTREE",
}


def asset_type(name: str) -> str:
    """ "tracker" or "share" — the grouping the Portfolio tab lists under.

    Punctuation is split on as well as whitespace, so "CREG.SHS" and "ETF," do
    not hide a token. A name that matches nothing is a share: that is the safe
    default, since a misfiled ETF is merely odd while inventing a fund out of a
    share the user actually owns is worse.
    """
    words = {w.strip("().,-") for w in name.upper().replace(".", " ").replace("-", " ").split()}
    return "tracker" if words & _TRACKER_TOKENS else "share"


def _pct(part: float, whole: float) -> float | None:
    """None, not 0.0, when there is no base — an undefined percentage must
    render as an em dash rather than as a flat day."""
    return round(part / whole * 100.0, 2) if whole > 0 else None


def _yahoo(bundle: PortfolioBundle) -> dict:
    """The stored Yahoo quotes per ISIN.

    `bundle.prices` is derived from them and is a blend for an ISIN held on two
    exchanges (venue_price_service.effective_prices), so code that prices one
    *position* reads these, and asks position_quote for the exchange's own.
    """
    return bundle.yahoo_prices if bundle.yahoo_prices is not None else bundle.prices


def listing_quote(info: dict) -> dict:
    """{currency, price, previous_close} of a stored quote in the currency its
    ticker trades in — what a price chart of that ticker is drawn in.

    A EUR listing is the row as stored. A converted one (TSM: stored as EUR,
    trades in dollars) is divided back by the rate it was converted at, so the
    price above a position's chart is the same number as the chart's last point:
    before, a dollar line carried a euro sign and ended 14% above the figure
    beside it. Without a stored rate (a row from before quote_fx_rate, until the
    next refresh) the prices are None rather than a guess.
    """
    currency = charts.listing_currency(info) or "EUR"
    if currency == "EUR":
        return {"currency": "EUR", "price": info.get("price"), "previous_close": info.get("previous_close")}
    rate = info.get("quote_fx_rate")
    if not rate:
        return {"currency": currency, "price": None, "previous_close": None}
    price, prev = info.get("price"), info.get("previous_close")
    return {
        "currency": currency,
        "price": round(price / rate, 4) if price is not None else None,
        "previous_close": round(prev / rate, 4) if prev else None,
    }


def holdings_rows(bundle: PortfolioBundle) -> list[dict]:
    """One row per open *position* — per (isin, exchange) — value descending.

    Not per ISIN: DeGiro splits a product held on two exchanges into two lines
    with two average prices, and this tab is meant to be readable next to their
    app. See cost_breakdown_by_venue for why that is a different sum rather
    than a regrouping.

    Each row is priced at its own exchange's price where the app has one — a
    TDG row at Tradegate's last trade — and at the ISIN's Yahoo quote
    otherwise (venue_price_service.position_quote). So the same fund on EAM and
    TDG shows the two prices DeGiro shows, and `price_provider` says which
    source each row's figures rest on.
    """
    breakdown = cost_breakdown_by_position(bundle.transactions)
    # Read once for the whole table rather than per row: every line has to
    # answer "did the market move today?" the same way, and midnight or an
    # opening bell falling between two rows would split the column in half.
    traded = price_refresh.traded_today()
    yahoo_prices = _yahoo(bundle)

    # Dividends are recorded per ISIN, with no venue on them. Split across an
    # ISIN's open positions in proportion to the shares each holds: any split
    # is an attribution rather than a fact, and this one at least sums back to
    # the amount actually received and puts most of it where most of the
    # shares are.
    shares_by_isin: dict[str, float] = {}
    for (isin, _broker, _venue), b in breakdown.items():
        shares_by_isin[isin] = shares_by_isin.get(isin, 0.0) + b["shares"]

    rows = []
    for (isin, broker, venue), b in breakdown.items():
        shares = b["shares"]
        if shares <= 0.0001:
            continue

        cost_ex = b["cost_ex"]
        isin_shares = shares_by_isin.get(isin, 0.0)
        dividends = bundle.dividends_by_isin.get(isin, 0.0) * (shares / isin_shares if isin_shares > 0 else 0.0)

        info = venue_price_service.position_quote(isin, venue, yahoo_prices, bundle.venue_prices)
        price = info["price"] if info else None
        prev = info.get("previous_close") if info else None
        value = round(shares * price, 2) if price is not None else None

        # The three terms Totale W/V is built from, rounded here rather than on
        # the way out, because the position page prints them as a column that
        # adds up to it. Summing the unrounded values and rounding once put the
        # total a cent above its own four rows on a real position (814,84 +
        # 117,26 + 45,47 - 11,00 = 966,57, printed under a total of 966,58) —
        # every figure defensible on its own, and a subtraction the reader can
        # see is wrong. A cent of rounding has to land *somewhere*; it belongs
        # in the total, which is the number derived from the others.
        realized_eur = round(b["realized_ex"], 2)
        dividends_eur = round(dividends, 2)
        costs_eur = round(b["costs_total"], 2)

        # Everything downstream of the current value is unknown when the price
        # is missing — including Totale W/V, which contains the unrealized leg.
        if value is None:
            unrealized_eur = unrealized_pct = total_eur = total_pct = None
            day_eur = day_pct = None
        else:
            unrealized_eur = round(value - cost_ex, 2)
            unrealized_pct = _pct(value - cost_ex, cost_ex)
            total_eur = round(unrealized_eur + realized_eur + dividends_eur - costs_eur, 2)
            # Against every euro ever put in, not against the basis of what is
            # left: after selling most of a position the remaining basis is a
            # sliver, and dividing a whole position's lifetime result by it
            # would print a return of several hundred percent.
            total_pct = _pct(total_eur, b["invested_gross"])
            # Same formula as dashboard_service.position_day_changes, applied to
            # this position's shares rather than the ISIN's — so the rows still
            # sum to the header chip, which comes from that function. Including
            # the zero it reports on a shut exchange: a column of real moves
            # under a header reading €0,00 would be two answers to one question.
            if not traded:
                day_eur = day_pct = 0.0
            elif prev and prev > 0:
                day_eur = round((price - prev) * shares, 2)
                day_pct = round((price / prev - 1.0) * 100.0, 2)
            else:
                day_eur = day_pct = None

        rows.append(
            {
                "isin": isin,
                "name": b["name"],
                # The Yahoo symbol even for a row priced off Tradegate: it is what
                # the koersgrafiek is drawn from.
                "ticker": (yahoo_prices.get(isin) or {}).get("ticker") if info else None,
                "asset_type": asset_type(b["name"]),
                # DeGiro's own venue code ("EAM", "XET", "TDG"), and now the thing
                # that makes this row a distinct position rather than a detail.
                "exchange": venue,
                # Which broker holds this line ("degiro", "trade_republic"). With
                # the exchange, what tells two rows of one ISIN apart.
                "broker": broker,
                "broker_label": brokers.label(broker),
                "shares_held": round(shares, 6),
                "current_price": price,
                "previous_close": prev,
                "current_value": value,
                "avg_cost_ex_costs": round(cost_ex / shares, 4) if shares > 0 else None,
                "invested_ex_costs": round(cost_ex, 2),
                "invested_gross": round(b["invested_gross"], 2),
                "realized_eur": realized_eur,
                "dividends_eur": dividends_eur,
                "costs_eur": costs_eur,
                "unrealized_eur": unrealized_eur,
                "unrealized_pct": unrealized_pct,
                "total_eur": total_eur,
                "total_pct": total_pct,
                "day_eur": day_eur,
                "day_pct": day_pct,
                "price_provider": info["provider"] if info else None,
                "price_fetched_at": info.get("fetched_at") if info else None,
            }
        )

    rows.sort(key=lambda r: r["current_value"] or 0, reverse=True)
    return rows


#: The Yahoo ticker suffix → the venue that listing trades on, for the source
#: line under a price. Bare tickers are US listings.
_YAHOO_SUFFIX_VENUE = {
    ".AS": "Euronext Amsterdam",
    ".PA": "Euronext Parijs",
    ".BR": "Euronext Brussel",
    ".LS": "Euronext Lissabon",
    ".MI": "Borsa Italiana",
    ".MC": "Bolsa de Madrid",
    ".HE": "Nasdaq Helsinki",
    ".VI": "Wiener Börse",
    ".DE": "XETRA",
    ".F": "Börse Frankfurt",
    ".SG": "Börse Stuttgart",
    ".L": "London Stock Exchange",
    ".SW": "SIX Swiss Exchange",
    ".OL": "Oslo Børs",
    ".ST": "Nasdaq Stockholm",
    ".CO": "Nasdaq Kopenhagen",
    ".TO": "Toronto",
    ".T": "Tokio",
    ".HK": "Hongkong",
    ".AX": "ASX Sydney",
}

#: DeGiro venues Yahoo carries no quote for at all, so any Yahoo price for a
#: position there is by definition another exchange's.
_NO_YAHOO_FEED = {"TDG"}


def price_source(ticker: str | None, exchange: str | None, provider: str | None = "yahoo") -> dict | None:
    """Where the price above a position comes from, and whether that is the
    exchange the position is actually held on.

    `venue_fallback` is True when the listing is some *other* exchange's: a
    Tradegate position priced off XETRA (its Tradegate price missing or
    stale), or a cached ticker on a different venue than the transactions
    name. Unknown venues are not called a fallback — there is nothing to
    compare against.
    """
    if provider == "tradegate":
        return {
            "provider": "Tradegate",
            "ticker": None,
            "listing_venue": tradegate_service.VENUE_NAME,
            "position_venue": exchange,
            "venue_fallback": False,
        }
    if not ticker:
        return None
    suffix = ticker[ticker.rindex(".") :] if "." in ticker else ""
    listing_venue = _YAHOO_SUFFIX_VENUE.get(suffix) or ("VS" if suffix == "" else None)

    venue = portfolio._DEGIRO_VENUES.get(exchange or "")
    if exchange in _NO_YAHOO_FEED:
        fallback = True
    elif venue is not None:
        fallback = suffix != venue[1]
    else:
        fallback = False

    return {
        "provider": "Yahoo Finance",
        "ticker": ticker,
        "listing_venue": listing_venue,
        "position_venue": exchange,
        "venue_fallback": fallback,
    }


def position_detail(bundle: PortfolioBundle, isin: str, venue: str | None = None, broker: str | None = None) -> dict | None:
    """One position, with the identity a page needs above it. None when the
    ISIN (or that venue of it) is not an open position.

    The figures are the very same row the Portfolio tab lists — holdings_rows
    is called again rather than re-derived — so the detail page can never print a
    GAK or a Totale W/V that differs from the table you clicked it from.

    *venue* is DeGiro's beurs code, and it is optional: a link that carries none
    lands on the largest position of that ISIN (the rows are value-descending),
    which is the one the user meant in the overwhelmingly common case of there
    being only one. `other_venues` names the rest, so the page can say so.
    """
    rows = holdings_rows(bundle)
    same_isin = [r for r in rows if r["isin"] == isin]
    if not same_isin:
        return None

    # *broker* narrows it the same way, for a fund held at two brokers.
    candidates = [r for r in same_isin if (not venue or r["exchange"] == venue) and (not broker or r["broker"] == broker)]
    if not candidates:
        return None
    row = candidates[0]

    # The same key cost_breakdown_by_position groups on, so "this position's
    # trades" here means exactly the trades its numbers were walked from.
    trades = [
        t
        for t in bundle.transactions
        if t["isin"] == isin and (t.get("exchange") or None) == row["exchange"] and broker_of(t) == row["broker"]
    ]
    buys = [t for t in trades if t["transaction_type"] == "BUY"]

    info = _yahoo(bundle).get(isin) or {}
    tradegate = row["price_provider"] == "tradegate"
    # The price in the listing's own currency, for the header and the chart;
    # every amount on `row` stays in euros. Tradegate quotes in euros itself.
    quote = {"currency": "EUR", "price": row["current_price"]} if tradegate else listing_quote(info)
    return {
        "position": row,
        # Off the Yahoo row rather than off `row`, which carries a ticker only
        # for a usable EUR quote: a position priced in the wrong currency still
        # has a listing whose chart is worth drawing.
        "ticker": info.get("ticker"),
        "currency": "EUR" if tradegate else info.get("currency"),
        "quote_currency": quote["currency"],
        "quote_price": quote["price"],
        # This position's own quote: Tradegate's fetch moment for a TDG row.
        "price_fetched_at": row["price_fetched_at"] or info.get("fetched_at"),
        "price_source": price_source(info.get("ticker"), row["exchange"], row["price_provider"]),
        # Tradegate is an extra quote for exactly the positions held there —
        # ISIN plus beurs, like every other lookup on this page.
        "tradegate_quote": row["exchange"] == tradegate_service.VENUE_CODE,
        "first_buy": min((t["date"] for t in buys), default=None),
        "last_trade": max((t["date"] for t in trades), default=None),
        "num_transactions": len(trades),
        # Why the dagbeweging above the chart reads 0,00%: the exchange has not
        # traded today. Same flag, same wording as the two hero chips.
        "market_closed": not price_refresh.traded_today(),
        "other_venues": [
            {
                "exchange": r["exchange"],
                "broker": r["broker"],
                "broker_label": r["broker_label"],
                "shares_held": r["shares_held"],
                "current_value": r["current_value"],
            }
            for r in same_isin
            if r is not row
        ],
    }


def gross_result_split(bundle: PortfolioBundle) -> dict:
    """Unrealized and realized with the transaction costs lifted back out.

    calculate_portfolio_summary reports both *net* of costs, because it builds
    them from `total_eur` — the fee-inclusive column. That makes the dashboard's
    costs invisible: they are inside the other two terms, so showing them beside
    those terms would subtract them twice.

    Lifting them out turns the breakdown into an actual sum:

        ongerealiseerd + gerealiseerd + dividend - kosten = totaalrendement

    which is the same shape the Portfolio tab already uses per position.

    Priced positions only, mirroring calculate_portfolio_summary: an unpriced
    holding contributes neither a value nor a cost basis, rather than counting
    its basis against a value of zero.
    """
    breakdown = cost_breakdown(bundle.transactions)
    priced = [p for p in bundle.positions if p["current_value"] is not None]

    value = sum(p["current_value"] for p in priced)
    cost_ex_open = sum(breakdown[p["isin"]]["cost_ex"] for p in priced)
    costs = bundle.summary["total_costs"]

    gross_unrealized = value - cost_ex_open
    # The rest of the gross result is what sells locked in — including on
    # positions closed long ago, which is why this is derived from total_gain
    # rather than summed from the open positions' breakdowns.
    gross_realized = (bundle.summary["total_gain"] + costs) - gross_unrealized

    return {
        "unrealized_gain_ex_costs": round(gross_unrealized, 2),
        "realized_gain_ex_costs": round(gross_realized, 2),
    }


def holdings_totals(rows: list[dict], bundle: PortfolioBundle) -> dict:
    """The header strip: the same two modes the table toggles between.

    `complete` is False when any open position sat out its sum (no price, or
    no previous close) — the number still shows, qualified, rather than
    hiding a portfolio because one line could not be priced.
    """
    priced = [r for r in rows if r["current_value"] is not None]
    with_total = [r for r in rows if r["total_eur"] is not None]
    total_sum = sum(r["total_eur"] for r in with_total)
    total_base = sum(r["invested_gross"] for r in with_total)
    unreal_sum = sum(r["unrealized_eur"] for r in with_total)
    unreal_base = sum(r["invested_ex_costs"] for r in with_total)

    return {
        "value": round(sum(r["current_value"] for r in priced), 2),
        "num_positions": len(rows),
        "prices_available": len(priced) == len(rows),
        "total": {
            "eur": round(total_sum, 2),
            "pct": _pct(total_sum, total_base),
            "complete": len(with_total) == len(rows),
        },
        "unrealized": {
            "eur": round(unreal_sum, 2),
            "pct": _pct(unreal_sum, unreal_base),
        },
        "realized_eur": round(sum(r["realized_eur"] for r in rows), 2),
        "dividends_eur": round(sum(r["dividends_eur"] for r in rows), 2),
        "costs_eur": round(sum(r["costs_eur"] for r in rows), 2),
        "by_broker": by_broker(rows, bundle.transactions),
        # None until a price refresh has stored previous closes, exactly as on
        # the dashboard — and the same function, so the two chips agree.
        "day": dashboard_service.portfolio_day_change(bundle.positions, bundle.prices),
    }


def by_broker(rows: list[dict], transactions: list[dict]) -> list[dict]:
    """Per broker: what its open positions are worth and every cost it ever charged.

    The costs are over all of the broker's trades, closed positions included,
    so this is what each broker has cost you in fees; the Portfolio rows only
    carry the costs of what is still open. Largest value first.
    """
    out: dict[str, dict] = {}

    def entry(code: str) -> dict:
        return out.setdefault(code, {"value": 0.0, "num_positions": 0, "costs_eur": 0.0, "priced": True})

    for t in transactions:
        entry(broker_of(t))["costs_eur"] += portfolio.transaction_cost(t)
    for r in rows:
        b = entry(r["broker"])
        b["num_positions"] += 1
        if r["current_value"] is None:
            b["priced"] = False
        else:
            b["value"] += r["current_value"]
    return sorted(
        (
            {
                "broker": code,
                "label": brokers.label(code),
                "value": round(b["value"], 2),
                "num_positions": b["num_positions"],
                "costs_eur": round(b["costs_eur"], 2),
                "prices_available": b["priced"],
            }
            for code, b in out.items()
        ),
        key=lambda b: -b["value"],
    )


def latest_price_fetch(prices: dict[str, dict]) -> str | None:
    return max((p["fetched_at"] for p in prices.values() if p.get("fetched_at")), default=None)


def oldest_price_fetch(prices: dict[str, dict]) -> str | None:
    """The stalest quote in the set — what these totals are really as current as.

    The header line was built on latest_price_fetch, which is the most
    flattering reading available: one ISIN that refreshed while the others
    failed made it say "updated just now" for a portfolio days behind.
    """
    return min((p["fetched_at"] for p in prices.values() if p.get("fetched_at")), default=None)


def overview(bundle: PortfolioBundle) -> dict:
    rows = holdings_rows(bundle)
    return {
        "positions": rows,
        "totals": holdings_totals(rows, bundle),
        "latest_price_fetch": latest_price_fetch(bundle.prices),
        "oldest_price_fetch": oldest_price_fetch(bundle.prices),
    }
