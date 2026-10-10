"""
The Allocation tab's two slow inputs, plus the data-quality arithmetic
app.py does inline.

app.py caches both behind @st.cache_data(ttl=86400) (app.py:78, app.py:85) —
they read every fund's published holdings file, so a cold call is many HTTP
requests. Same TTL here, via database.get_or_fetch.

The provenance buckets live here rather than in the browser for the reason the
plan gives this tab: "coverage %/excluded % match exactly ... numeric parity
(not just 'renders') is the bar". Re-deriving app.py's `worst`-of-two ranking in
TypeScript is how the two tabs would come to disagree about how trustworthy the
same number is.
"""

import sqlite3

from domain import database
from domain.portfolio import etf_holdings
from domain.portfolio import issuer_holdings

# The label normalisers get_portfolio_breakdown runs its own holdings through,
# borrowed rather than re-implemented: fund_breakdown below aggregates the same
# issuer rows one fund at a time, and a second spelling of "Information
# Technology" would put a fund's own page at odds with the Allocation tab.
from domain.portfolio.etf_holdings import _norm_country, _norm_sector, _norm_stock_key

_TTL_SECONDS = 86400  # app.py:78's @st.cache_data(ttl=86400)

# app.py:893. Ranks a fund's two data sources so the *worse* one labels it: a
# fund with exact countries but guessed sectors is not "exact".
#: "stock" belongs here too: an individual holding's own sector and country come
#: straight from its yfinance profile, which is as exact as the issuer files are.
#: Missing, it fell to the .get default of 3 and every directly-held share landed
#: in the "none" bucket — the strip called ASML "only derived from the name"
#: while the coverage table two clicks away called the same position exact.
_DQ_RANK = {"exact": 0, "manual": 0, "stock": 0, "proxy": 1, True: 2}


def _positions_fingerprint(positions: list[dict]) -> str:
    """Keys the cache on what actually changes the answer.

    Holdings are per fund and per weight, so a new price (which moves every
    fund's value) has to invalidate it, but the rest of a position does not.
    st.cache_data hashes the whole positions list; this is the same idea,
    narrowed to the fields these two functions read.
    """
    import hashlib
    import json

    relevant = sorted(
        (p["isin"], p.get("ticker"), p.get("current_value")) for p in positions
    )
    blob = json.dumps(relevant, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def as_slices(totals: dict[str, float], decimals: int = 1) -> list[dict]:
    """A `{name: fraction}` totals dict as a list of slices, biggest first.

    get_portfolio_breakdown returns fractions of portfolio value; every consumer
    wants whole percentages sorted descending. Lived in the dashboard router
    until the ETF tab needed the same three conversions — one definition, so a
    slice cannot be rounded one way on the dashboard and another way here.

    `decimals` stays at 1 everywhere a chart is drawn. The long tail of
    countries is the exception: those are tenths of a percent, and rounded to
    one decimal half that list reads "0,0%".
    """
    return sorted(
        ({"name": name, "pct": round(frac * 100.0, decimals)} for name, frac in totals.items()),
        key=lambda s: s["pct"],
        reverse=True,
    )


def _bond_fingerprint(conn: sqlite3.Connection) -> str:
    """The user's own Stocks/Bonds classifications, as a cache-key component.

    Both answers below hold bond funds out of the percentages, and which
    positions those are is partly the user's own call (etf_holdings.bond_isins).
    Without this, reclassifying a position on the Rebalancing tab would leave
    this tab showing yesterday's split for the rest of the day.
    """
    categories = database.load_asset_categories(conn)
    bonds = sorted(i for i, c in categories.items() if c in database.BOND_CATEGORIES)
    import hashlib
    return hashlib.sha256(",".join(bonds).encode("utf-8")).hexdigest()[:8]


def get_breakdown(conn: sqlite3.Connection, positions: list[dict]) -> dict:
    """Sector/region/continent totals, per-position coverage, and excluded %."""
    # v2: region_all_totals joined the payload. The key carries the version so a
    # cached v1 answer expires instead of serving a page without it for a day.
    key = f"etf:breakdown:v2:{_positions_fingerprint(positions)}:{_bond_fingerprint(conn)}"

    def fetch():
        (
            sector, region, continent, coverage, excluded_pct, region_all,
        ) = etf_holdings.get_portfolio_breakdown(conn, positions)
        return {
            "sector_totals": sector,
            "region_totals": region,
            "region_all_totals": region_all,
            "continent_totals": continent,
            # `region_data`/`sector_data` hold True/False as well as strings, and
            # JSON keeps both — the ranking below and the frontend's labels both
            # depend on telling True from "exact".
            "coverage": coverage,
            "excluded_pct": excluded_pct,
        }

    return database.get_or_fetch(conn, key, _TTL_SECONDS, fetch)


def get_exposure(conn: sqlite3.Connection, positions: list[dict]) -> dict:
    """Effective per-company exposure, its coverage %, and each fund's source."""
    key = f"etf:exposure:{_positions_fingerprint(positions)}:{_bond_fingerprint(conn)}"

    def fetch():
        stock_list, stock_coverage, etf_sources = etf_holdings.get_stock_exposure(
            conn, positions
        )
        return {
            "stock_list": stock_list,
            "stock_coverage": stock_coverage,
            "etf_sources": etf_sources,
        }

    return database.get_or_fetch(conn, key, _TTL_SECONDS, fetch)


def fund_breakdown_unavailable() -> dict:
    """The answer's shape when there is nothing to break down.

    Same keys, empty — a share, or a fund whose issuer publishes no list the app
    can read. The frontend then has one thing to check (`source`) rather than
    having to tell an absent field from an empty one.
    """
    return {"source": None, "quality": None, "num_holdings": 0, "top10_pct": None,
            "holdings": [], "sectors": [], "countries": [], "num_countries": 0}


def fund_breakdown(
    conn: sqlite3.Connection, isin: str, name: str, value: float | None
) -> dict:
    """What one fund holds: its biggest positions, its sectors, its countries.

    The same issuer file get_portfolio_breakdown reads, aggregated over one fund
    instead of over the portfolio — so a fund cannot be 36,6% technology on the
    Allocation tab and something else on its own page.

    Percentages are of *the fund*; the euro amount beside each holding is the
    caller's own money, so it needs the position's current value. A fund with no
    readable issuer file gets `source: None` and empty lists: the page says so in
    a sentence, which is a better answer than an empty card.

    Bond funds are deliberately *not* excluded the way they are on Allocation.
    There they are held out of the percentages because a sector label says
    nothing useful about a bond; here the question is only "what is in this
    thing", and if the issuer publishes a list it is worth showing.
    """
    holdings = issuer_holdings.fetch_issuer_holdings(conn, isin, name)
    if not holdings:
        return fund_breakdown_unavailable()

    source, quality = issuer_holdings.source_info(conn, isin, name)

    # Renormalised, for the same reason get_portfolio_breakdown does it: an
    # issuer file's weights sum to a hair either side of 100% (cash lines,
    # rounding), and a column that adds up to 99,7% invites the question of
    # where the rest went.
    weight_sum = sum(h["weight"] for h in holdings) or 1.0

    rows: dict[tuple[str, str | None], dict] = {}
    sec_by: dict[str, float] = {}
    cty_by: dict[str, float] = {}
    for h in holdings:
        pct = h["weight"] / weight_sum * 100
        sector = _norm_sector(h.get("sector")) or "Other"
        country = _norm_country(h.get("country")) or "Other"
        sec_by[sector] = sec_by.get(sector, 0.0) + pct
        cty_by[country] = cty_by.get(country, 0.0) + pct
        # Merged on name and country, the key get_stock_exposure already merges
        # companies on. Two share classes of one company are two lines in the
        # issuer file under one name: unmerged, Alphabet is both the fifth and
        # the seventh position of the S&P 500 fund instead of the third, and the
        # "top 10" below then describes nine companies.
        key = (_norm_stock_key(h.get("name") or h.get("symbol") or ""), country)
        row = rows.get(key)
        if row is None:
            rows[key] = {"name": h.get("name") or h.get("symbol"),
                         "symbol": h.get("symbol"), "pct": pct,
                         "sector": sector, "country": country}
        else:
            row["pct"] += pct

    ranked = sorted(rows.values(), key=lambda r: -r["pct"])

    return {
        "source": source,
        "quality": quality,
        "num_holdings": len(ranked),
        # Twenty: the page shows ten and keeps ten behind "the next ten". A
        # full list would be 772 rows of JSON for a question nobody asks on a
        # phone, and the tab that *does* answer it (Allocation) already exists.
        "holdings": [
            {
                "name": r["name"],
                "symbol": r["symbol"],
                "pct": round(r["pct"], 2),
                "value": round(r["pct"] / 100 * value, 2) if value else None,
            }
            for r in ranked[:20]
        ],
        "top10_pct": round(sum(r["pct"] for r in ranked[:10]), 1),
        "sectors": _as_pct_list(sec_by),
        "countries": _as_pct_list(cty_by),
        "num_countries": len(cty_by),
    }


def _as_pct_list(totals: dict[str, float]) -> list[dict]:
    """A `{name: percentage}` dict as a sorted list, without the 0,0% tail.

    Below 0.05 a slice prints as "0,0%", which reads as a bug rather than as a
    rounding artefact — the same threshold slices.ts uses for its "Overig".
    """
    return sorted(
        ({"name": n, "pct": round(p, 1)} for n, p in totals.items() if p >= 0.05),
        key=lambda s: -s["pct"],
    )


def diversification_quality(coverage: list[dict]) -> dict:
    """app.py:892-933's strip: funds bucketed by their worse data source.

    Percentages are of analysed value — bond ETFs are already out, since
    sector and country labels say nothing useful about them.
    """
    rows = [c for c in coverage if c["region_data"] != "excluded"]
    total = sum(c["current_value"] for c in rows)
    if total <= 0:
        return {"total": 0, "buckets": []}

    buckets: dict[str, list] = {"exact": [], "proxy": [], "est": [], "none": []}
    for c in rows:
        worst = max(c["region_data"], c["sector_data"], key=lambda v: _DQ_RANK.get(v, 3))
        key = (
            # "stock" belongs with the exact ones on both sides of this: the rank
            # above decides which of a fund's two sources is the worse, this
            # decides which bucket that lands in, and missing from either one put
            # a directly-held share in "none".
            "exact" if worst in ("exact", "manual", "stock")
            else "proxy" if worst == "proxy"
            else "est" if worst is True
            else "none"
        )
        buckets[key].append(c)

    return {
        "total": total,
        "buckets": [
            {
                "kind": kind,
                "pct": sum(c["current_value"] for c in rows_in) / total * 100,
                "tickers": [c["ticker"] for c in rows_in],
            }
            for kind, rows_in in buckets.items()
            if rows_in
        ],
    }


def exposure_quality(etf_sources: list[dict]) -> dict:
    """app.py:992-1031's strip, over the same four quality levels."""
    total = sum(s["value"] for s in etf_sources)
    if total <= 0:
        return {"total": 0, "buckets": []}

    return {
        "total": total,
        "buckets": [
            {
                "kind": kind,
                "pct": sum(s["value"] for s in group) / total * 100,
                "tickers": [s["ticker"] for s in group],
            }
            for kind, group in (
                (k, [s for s in etf_sources if s["quality"] == k])
                for k in ("exact", "proxy", "approx", "none")
            )
            if group
        ],
    }
