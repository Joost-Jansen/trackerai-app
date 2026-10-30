"""
etf_holdings.py — Fetch ETF holdings, sector weights and country breakdown.

Holdings     : the issuers' own published files (issuer_holdings.py), or an
               index proxy — another fully-replicating fund on the same index —
               when the issuer publishes nothing machine-readable; falls back to
               yfinance's top-10 when neither is available
Sector data  : yfinance funds_data.sector_weightings
Country data : justetf.com ETF profile page (static HTML, no JS needed)

Public API
----------
get_portfolio_breakdown(conn, positions)
    →  (sector_totals, region_totals, continent_totals, coverage, excluded_pct,
        region_all_totals)

    sector_totals     : dict[str, float]  sector → weighted fraction of portfolio
    region_totals     : dict[str, float]  country → fraction, <0.5% folded into "Other"
    continent_totals  : dict[str, float]  continent → weighted fraction of portfolio
    coverage          : list[dict]        per-position data/status summary
    excluded_pct      : float             % of portfolio value excluded (bond ETFs)
    region_all_totals : dict[str, float]  country → fraction, nothing folded

get_stock_exposure(conn, positions)
    →  (stocks, coverage_pct, etf_sources)

Every function that reads/writes the ETF holdings cache takes the caller's
already-open `conn: sqlite3.Connection` explicitly — see database.py's module
docstring for why (no ambient "current user" state).
"""

import json
import re
import sqlite3

import requests
import yfinance as yf

from domain import database
from domain.portfolio import issuer_holdings

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_JUSTETF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Some stored tickers (e.g. .SG) are not recognised by yfinance.
# Map ISIN → an alternative ticker that yfinance does resolve.
_ISIN_TICKER_OVERRIDE: dict[str, str] = {
    "IE00BYTRRD19": "WTCH.AS",  # SPDR MSCI World Technology
}

# Hard-coded overrides for positions where automatic data fails.
# Format: isin → {"country": ..., "sector": ...}
_ISIN_MANUAL: dict[str, dict] = {
    "NL0010773842": {"country": "Netherlands", "sector": "Financials"},  # NN Group NV
}

# Last-resort list of ISINs that are not equity, for the case where neither the
# user's own classification nor the fund data settles it. It used to be the
# *only* test, which meant one hand-added ISIN decided the answer for everybody:
# a second user's bond ETF was quietly run through the sector and country
# machinery, and the "bond ETFs are not included below" note stayed hidden
# because the excluded percentage was zero. Wrong numbers with nothing to say so.
# See bond_isins() for what decides it now.
_ISIN_EXCLUDE: set[str] = {
    "IE000WA6L436",  # iShares iBonds Dec 2026 Term EUR Corp — bond ETF
}

# Above this share of a fund's assets in bonds, it is a bond fund. Held well
# clear of the edge on purpose: a term bond ETF near maturity can be a third
# cash (CEBE.DE reads 69% bonds / 31% cash) and is still not an equity fund,
# while a mixed fund that happens to be exactly half bonds is a judgement call
# nobody should make silently.
_BOND_THRESHOLD = 0.5

# A fund's asset mix moves on the scale of years, and this is one HTTP request
# per ticker — a month is short next to how often it changes and long next to
# how often this page is opened.
_ASSET_CLASS_TTL_SECONDS = 30 * 86400


def _bond_fraction(conn: sqlite3.Connection, ticker: str) -> float | None:
    """How much of *ticker* is held in bonds, per yfinance. None when unknown.

    "Unknown" is cached like any other answer: an individual stock has no fund
    profile at all, and letting that raise on every page load would cost a
    failed request per position per visit.
    """

    def fetch():
        try:
            classes = yf.Ticker(ticker).funds_data.asset_classes or {}
            value = classes.get("bondPosition")
            return {"bond": float(value) if value is not None else None}
        except Exception:
            return {"bond": None}

    cached = database.get_or_fetch(conn, f"assetclass:{ticker}", _ASSET_CLASS_TTL_SECONDS, fetch)
    return cached.get("bond")


def bond_isins(conn: sqlite3.Connection, positions: list[dict]) -> set[str]:
    """Which of *positions* are bonds, and so have no place in an equity breakdown.

    Sector and country labels describe companies; a bond fund put through them
    produces either nothing or nonsense, so those positions are held out of the
    percentages and reported separately as "excluded".

    Three tests, in order of who has the best claim to know:

      1. What the user classified the position as on the Rebalancing tab. That
         is an explicit statement about their own portfolio and it wins outright
         — including when it says a position is *not* a bond.
      2. The fund's own asset mix, from yfinance. This is what makes the feature
         work for someone who never opened that tab.
      3. The hand-maintained list above, for a fund yfinance has no profile for.
    """
    categories = database.load_asset_categories(conn)
    bonds: set[str] = set()

    for p in positions:
        isin = p["isin"]
        category = categories.get(isin)
        if category is not None:
            if category in database.BOND_CATEGORIES:
                bonds.add(isin)
            continue
        ticker = p.get("ticker")
        if ticker:
            fraction = _bond_fraction(conn, ticker)
            if fraction is not None and fraction > _BOND_THRESHOLD:
                bonds.add(isin)
                continue
        if isin in _ISIN_EXCLUDE:
            bonds.add(isin)

    return bonds


# yfinance sector keys → official GICS names, so the fallback path lands in
# the same buckets as the issuer holdings files.
_SECTOR_LABELS: dict[str, str] = {
    "technology": "Information Technology",
    "financial_services": "Financials",
    "consumer_cyclical": "Consumer Discretionary",
    "consumer_defensive": "Consumer Staples",
    "healthcare": "Health Care",
    "industrials": "Industrials",
    "communication_services": "Communication Services",
    "energy": "Energy",
    "basic_materials": "Materials",
    "utilities": "Utilities",
    "realestate": "Real Estate",
}

# Issuers spell sectors/countries slightly differently ("Communication" on
# iShares vs GICS "Communication Services"); normalise onto one taxonomy.
_SECTOR_ALIASES: dict[str, str] = {
    "communication": "Communication Services",
    "telecommunications": "Communication Services",
    "telecommunication services": "Communication Services",
    "healthcare": "Health Care",
    "technology": "Information Technology",
    "basic materials": "Materials",
    "consumer cyclical": "Consumer Discretionary",
    "consumer defensive": "Consumer Staples",
    "financial services": "Financials",
    "financial": "Financials",
}

_COUNTRY_ALIASES: dict[str, str] = {
    "korea (south)": "South Korea",
    "republic of korea": "South Korea",
    "korea": "South Korea",
    "taiwan, province of china": "Taiwan",
    "russian federation": "Russia",
    "united states of america": "United States",
    "viet nam": "Vietnam",
    "hong kong sar": "Hong Kong",
    "czech republic": "Czechia",
}


def _norm_sector(raw: str | None) -> str | None:
    if not raw:
        return None
    return _SECTOR_ALIASES.get(raw.strip().lower(), raw.strip())


def _norm_country(raw: str | None) -> str | None:
    if not raw:
        return None
    return _COUNTRY_ALIASES.get(raw.strip().lower(), raw.strip())


# Country (normalised name) → continent, for the higher-level regional rollup.
# Middle-Eastern countries are folded into Asia (geographic continents only).
_CONTINENT: dict[str, str] = {
    # North America
    "United States": "North America",
    "Canada": "North America",
    "Mexico": "North America",
    "Bermuda": "North America",
    "Cayman Islands": "North America",
    # South America
    "Brazil": "South America",
    "Argentina": "South America",
    "Chile": "South America",
    "Colombia": "South America",
    "Peru": "South America",
    "Uruguay": "South America",
    # Europe
    "United Kingdom": "Europe",
    "Netherlands": "Europe",
    "France": "Europe",
    "Germany": "Europe",
    "Switzerland": "Europe",
    "Spain": "Europe",
    "Italy": "Europe",
    "Sweden": "Europe",
    "Denmark": "Europe",
    "Norway": "Europe",
    "Finland": "Europe",
    "Belgium": "Europe",
    "Ireland": "Europe",
    "Austria": "Europe",
    "Portugal": "Europe",
    "Luxembourg": "Europe",
    "Poland": "Europe",
    "Czechia": "Europe",
    "Greece": "Europe",
    "Hungary": "Europe",
    "Russia": "Europe",
    "Jersey": "Europe",
    "Guernsey": "Europe",
    "Liechtenstein": "Europe",
    "Monaco": "Europe",
    "Iceland": "Europe",
    # Asia (incl. Middle East)
    "China": "Asia",
    "Taiwan": "Asia",
    "Japan": "Asia",
    "South Korea": "Asia",
    "India": "Asia",
    "Hong Kong": "Asia",
    "Singapore": "Asia",
    "Indonesia": "Asia",
    "Thailand": "Asia",
    "Malaysia": "Asia",
    "Philippines": "Asia",
    "Vietnam": "Asia",
    "Israel": "Asia",
    "Saudi Arabia": "Asia",
    "United Arab Emirates": "Asia",
    "Qatar": "Asia",
    "Kuwait": "Asia",
    "Turkey": "Asia",
    # Oceania
    "Australia": "Oceania",
    "New Zealand": "Oceania",
    # Africa
    "South Africa": "Africa",
    "Egypt": "Africa",
    "Nigeria": "Africa",
    "Morocco": "Africa",
    "Kenya": "Africa",
}


def _continent_of(country: str) -> str:
    """Map a normalised country name to its continent ('Other' if unknown)."""
    return _CONTINENT.get(country, "Other")


# Fallback: infer region from ETF name when justetf scrape fails
_REGION_RULES: list[tuple[list[str], str]] = [
    (["s&p 500", "sp500", "sp 500"], "United States"),
    (["stoxx 50", "stoxx50", "euro stoxx"], "Europe"),
    (["stoxx 600", "stoxx600"], "Europe"),
    (["msci europe"], "Europe"),
    (["aex"], "Netherlands"),
    (["emerging market", "msci em", " em "], "Emerging Markets"),
    (["world technology", "msci world tech"], "Global (Tech)"),
    (["msci world"], "Global"),
    (["clean energy", "renewable"], "Global (Clean Energy)"),
    (["ftse all", "ftse world"], "Global"),
    (["nasdaq"], "United States"),
    (["ibonds", "term ", "creg", "bond", "treasury", "govt"], "Bonds"),
]


# ---------------------------------------------------------------------------
# Data fetching helpers
# ---------------------------------------------------------------------------


def _fetch_countries_justetf(isin: str) -> dict[str, float] | None:
    """
    Scrape the country breakdown table from the justetf ETF profile page.
    Returns a dict of {country_name: fraction} (values sum to ~1.0),
    or None if the page cannot be fetched / parsed.
    """
    url = "https://www.justetf.com/en/etf-profile.html"
    try:
        # params=: the ISIN comes from an upload and is encoded, never spliced in.
        r = requests.get(url, params={"isin": isin, "tab": "holdings"}, headers=_JUSTETF_HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        countries = re.findall(
            r'tl_etf-holdings_countries_value_name">([^<]+)</td>.*?'
            r'tl_etf-holdings_countries_value_percentage">([0-9.]+)%',
            r.text,
            re.DOTALL,
        )
        if not countries:
            return None
        result = {}
        for name, pct in countries:
            result[name.strip()] = round(float(pct) / 100, 6)
        return result
    except Exception:
        return None


def _infer_region_fallback(name: str) -> str:
    """Return a broad region label inferred from the ETF name."""
    lower = name.lower()
    for patterns, label in _REGION_RULES:
        if any(p in lower for p in patterns):
            return label
    return "Other"


def _fetch_sector_weights(ticker: str) -> dict[str, float] | None:
    """Fetch sector weightings from yfinance. Returns None on failure."""
    try:
        sw = yf.Ticker(ticker).funds_data.sector_weightings
        if sw:
            return {_SECTOR_LABELS.get(k, k.title()): round(v, 6) for k, v in sw.items()}
        return None
    except Exception:
        return None


def _fetch_top_holdings(ticker: str):
    """Fetch top holdings DataFrame from yfinance. Returns None on failure."""
    try:
        df = yf.Ticker(ticker).funds_data.top_holdings
        if df is not None and not df.empty:
            return df
        return None
    except Exception:
        return None


def _fetch_stock_info(conn: sqlite3.Connection, ticker: str) -> dict | None:
    """
    yfinance profile for an individual position: {quote_type, sector, country}.
    Cached in SQLite for 7 days (same store as ETF holdings).  Lets an
    individual stock be placed in its own sector/country exactly, instead of
    falling back to the inaccurate ETF estimate path.  Returns None on failure.
    """
    if not ticker:
        return None
    cache_key = f"stockinfo:v1:{ticker}"
    cached = database.load_etf_api_cache(conn, cache_key)
    if cached is not None:
        try:
            data = json.loads(cached)
            return data or None
        except json.JSONDecodeError:
            pass
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return None
    data = {
        "quote_type": (info.get("quoteType") or "").upper(),
        "sector": info.get("sector"),
        "country": info.get("country"),
    }
    database.save_etf_api_cache(conn, cache_key, json.dumps(data))
    return data


# Tokens dropped when normalising company names for cross-source matching.
# Different sources spell the same company differently ("NVIDIA CORP" on
# iShares, "NVIDIA Corporation" on SPDR) — without this the same stock
# would appear as two separate bars.
_NAME_STOP_TOKENS = {
    "CORP",
    "CORPORATION",
    "INC",
    "INCORPORATED",
    "PLC",
    "NV",
    "SA",
    "SE",
    "AG",
    "SPA",
    "LTD",
    "LIMITED",
    "CO",
    "COMPANY",
    "HOLDING",
    "HOLDINGS",
    "GROUP",
    "CLASS",
    "ADR",
    "A",
    "B",
    "C",
    "REIT",
    "OYJ",
    "ASA",
    "AB",
    "KGAA",
    "THE",
    "REGISTERED",
    "SHS",
    "ORD",
    "NEW",
}


def _norm_stock_key(name: str) -> str:
    """'NVIDIA Corporation' / 'NVIDIA CORP' → 'NVIDIA' — aggregation key."""
    tokens = re.sub(r"[^A-Z0-9 ]", " ", name.upper()).split()
    core = [t for t in tokens if t not in _NAME_STOP_TOKENS]
    return " ".join(core) if core else name.upper().strip()


def get_stock_exposure(
    conn: sqlite3.Connection,
    positions: list[dict],
) -> tuple[list[dict], float, list[dict]]:
    """
    Calculate effective EUR exposure to individual stocks across all ETF positions.
    Multiplies each ETF's current portfolio value by the weight of each holding,
    then aggregates per company (name-normalised across data sources).

    Holdings source priority per ETF:
      1. Issuer files (iShares CSV / SPDR XLSX / Vanguard GraphQL) or a
         registered full-replication index proxy — complete holdings
      2. yfinance top-10 — approximate fallback

    Returns
    -------
    stocks : list[dict]
        Sorted by effective value (EUR) descending. Each dict:
        symbol, name, value (EUR), sources (list of ETF names contributing).
    coverage_pct : float
        Percentage of total included portfolio value captured by the holdings data.
    etf_sources : list[dict]
        Per ETF: name, ticker, source label, quality ('exact' | 'proxy' |
        'approx' | 'none'), num_holdings, weight_pct (fund coverage),
        value (position EUR value).
    """
    priced = [p for p in positions if p.get("current_value") and p["current_value"] > 0]
    excluded_isins = bond_isins(conn, priced)
    included = [p for p in priced if p["isin"] not in excluded_isins]

    total_value = sum(p["current_value"] for p in included)
    covered_value = 0.0

    stock_exposure: dict[str, dict] = {}  # norm key → {symbol, name, value, sources}
    etf_sources: list[dict] = []

    def _add(symbol: str, holding_name: str, stock_value: float, etf_name: str, country: str | None = None):
        # Keyed on name *and* country. The name alone merged companies that only
        # share a word once the legal-form tokens are stripped: 'MERCK & CO INC'
        # (United States) and 'MERCK' (Germany) have been separate companies
        # since 1917, and their euro amounts were summed into one bar labelled
        # with whichever name the holdings file happened to list first. Same for
        # 'EQT CORP' (US natural gas) and 'EQT' (Swedish private equity).
        #
        # Safe to split on, measured against 2.579 real holdings from four funds
        # and two issuers: every one carries a country, and only three name keys
        # ever span more than one — Merck, EQT and Rio Tinto, all of which are
        # genuinely separate listings. Loosening the stop-token list instead was
        # tried and rejected: keeping GROUP/HOLDINGS would break 67 of the 500
        # merges that are correct.
        key = (_norm_stock_key(holding_name or symbol), _norm_country(country))
        entry = stock_exposure.setdefault(key, {"symbol": "", "name": holding_name or symbol, "value": 0.0, "sources": []})
        # Prefer a real (short) ticker symbol for display when any source has one
        if symbol and (not entry["symbol"] or len(symbol) < len(entry["symbol"])):
            entry["symbol"] = symbol
        entry["value"] += stock_value
        if etf_name not in entry["sources"]:
            entry["sources"].append(etf_name)

    def _record_source(source: str, quality: str, num: int, w_pct: float, pos: dict, ticker_label: str):
        etf_sources.append(
            {
                "name": pos["name"],
                "ticker": ticker_label,
                "source": source,
                "quality": quality,
                "num_holdings": num,
                "weight_pct": w_pct,
                "value": pos["current_value"],
            }
        )

    for p in included:
        isin = p["isin"]
        name = p["name"]
        value = p["current_value"]
        ticker = p.get("ticker")

        # Individual stock (manual override) — 100% itself
        if isin in _ISIN_MANUAL:
            _add(ticker or isin, name, value, name, _ISIN_MANUAL[isin].get("country"))
            covered_value += value
            _record_source("position itself", "exact", 1, 100.0, p, ticker or "–")
            continue

        # --- 1. Issuer files / index proxies: complete holdings ---
        holdings = issuer_holdings.fetch_issuer_holdings(conn, isin, name)
        if holdings:
            src_label, src_quality = issuer_holdings.source_info(conn, isin, name)
            weight_sum = sum(h["weight"] for h in holdings)
            covered_value += value * min(weight_sum, 1.0)
            for h in holdings:
                _add(h["symbol"], h["name"], value * h["weight"], name, h.get("country"))
            _record_source(
                src_label,
                src_quality,
                len(holdings),
                round(min(weight_sum, 1.0) * 100, 1),
                p,
                ticker or "–",
            )
            continue

        effective_ticker = _ISIN_TICKER_OVERRIDE.get(isin, ticker)
        if not effective_ticker:
            _record_source("no data", "none", 0, 0.0, p, "–")
            continue

        # --- Individual stock: it's 100% exposure to itself ---
        info = _fetch_stock_info(conn, effective_ticker)
        if info and info["quote_type"] == "EQUITY":
            _add(ticker or effective_ticker, name, value, name, info.get("country"))
            covered_value += value
            _record_source("Individual stock", "exact", 1, 100.0, p, effective_ticker)
            continue

        # --- 2. Fallback: yfinance top-10 (approximate) ---
        df = _fetch_top_holdings(effective_ticker)
        if df is None:
            _record_source("no data", "none", 0, 0.0, p, effective_ticker)
            continue

        holdings_sum = df["Holding Percent"].sum()
        covered_value += value * holdings_sum
        for symbol, row in df.iterrows():
            _add(symbol, row["Name"], value * row["Holding Percent"], name)
        _record_source(
            "Yahoo top 10",
            "approx",
            len(df),
            round(holdings_sum * 100, 1),
            p,
            effective_ticker,
        )

    # Fold the per-country buckets back together. A name only stays split when
    # two *known* countries disagree — the yfinance top-10 fallback carries no
    # country at all, and letting that count as "a different country" would show
    # one company as two bars whenever a covered and an uncovered fund both hold
    # it. So an unknown-country bucket joins the single known one where there is
    # exactly one, and only keeps to itself when there is genuinely more than one
    # company under the name and no way to tell which it belongs to.
    by_name: dict[str, list[tuple[str | None, dict]]] = {}
    for (name_key, country), data in stock_exposure.items():
        by_name.setdefault(name_key, []).append((country, data))

    def _merge(entries: list[dict]) -> dict:
        first = entries[0]
        symbol, sources = first["symbol"], list(first["sources"])
        value = 0.0
        for e in entries:
            value += e["value"]
            if e["symbol"] and (not symbol or len(e["symbol"]) < len(symbol)):
                symbol = e["symbol"]
            for s in e["sources"]:
                if s not in sources:
                    sources.append(s)
        return {"symbol": symbol, "name": first["name"], "value": value, "sources": sources}

    combined: list[dict] = []
    for buckets in by_name.values():
        known = {c for c, _ in buckets if c}
        if len(known) <= 1:
            combined.append(_merge([d for _, d in buckets]))
        else:
            for _country, data in buckets:
                combined.append(_merge([data]))

    result = [
        {
            "symbol": data["symbol"] or (data["name"][:24] + "…" if len(data["name"]) > 24 else data["name"]),
            "name": data["name"],
            "value": round(data["value"], 2),
            "sources": data["sources"],
        }
        for data in combined
    ]
    result.sort(key=lambda x: -x["value"])

    coverage_pct = round(covered_value / total_value * 100, 1) if total_value > 0 else 0.0
    return result, coverage_pct, etf_sources


def position_mix(conn: sqlite3.Connection, isin: str, name: str, ticker: str | None) -> dict:
    """One position's own look-through: where a euro in it ends up.

        {"sector": {name: fraction}, "country": {name: fraction},
         "dominant_region": str, "region_data": ..., "sector_data": ...}

    Each of the two dicts sums to 1 — the position's whole value — so a caller
    multiplies by whatever weight that position has *on its date*. Lived inline
    in get_portfolio_breakdown, which could only weigh it by today's value; the
    allocation-over-time series needs the same mix weighed by a value on any
    past month-end, and one copy keeps the two from labelling a fund
    differently.

    The order of sources is unchanged: a hand-made override, the issuer's own
    holdings file, the share's own yfinance profile, and for the rest justetf's
    countries and yfinance's sector weights (or "Unknown" when there are none,
    so a fund without sector data does not silently inflate the others).
    """
    # --- Manual override (e.g. individual stocks we know) ---
    if isin in _ISIN_MANUAL:
        manual = _ISIN_MANUAL[isin]
        return {
            "sector": {manual["sector"]: 1.0},
            "country": {manual["country"]: 1.0},
            "dominant_region": manual["country"],
            "region_data": "manual",
            "sector_data": "manual",
        }

    # --- Exact: aggregate per-holding sector/country from issuer data ---
    holdings = issuer_holdings.fetch_issuer_holdings(conn, isin, name)
    if holdings:
        _, src_quality = issuer_holdings.source_info(conn, isin, name)  # 'exact' | 'proxy'
        weight_sum = sum(h["weight"] for h in holdings) or 1.0
        sec_by: dict[str, float] = {}
        cty_by: dict[str, float] = {}
        for h in holdings:
            frac = h["weight"] / weight_sum  # renormalise: fund contributes exactly its position weight
            sec = _norm_sector(h.get("sector")) or "Other"
            cty = _norm_country(h.get("country")) or "Other"
            sec_by[sec] = sec_by.get(sec, 0.0) + frac
            cty_by[cty] = cty_by.get(cty, 0.0) + frac
        return {
            "sector": sec_by,
            "country": cty_by,
            "dominant_region": max(cty_by, key=lambda k: cty_by[k]),
            "region_data": src_quality,
            "sector_data": src_quality,
        }

    # --- Individual stock: its own sector + country (yfinance) ---
    effective_ticker = _ISIN_TICKER_OVERRIDE.get(isin, ticker)
    info = _fetch_stock_info(conn, effective_ticker) if effective_ticker else None
    if info and info["quote_type"] == "EQUITY":
        country = _norm_country(info["country"]) or "Other"
        sector = _norm_sector(info["sector"]) or "Other"
        return {
            "sector": {sector: 1.0},
            "country": {country: 1.0},
            "dominant_region": country,
            "region_data": "stock",
            "sector_data": "stock",
        }

    # --- Fallback: country/region breakdown (justetf scrape) ---
    country_weights = _fetch_countries_justetf(isin)
    if country_weights:
        countries = dict(country_weights)
        region_data_available = True
        # Use the dominant country as the summary region label for the coverage table
        dominant = max(country_weights, key=lambda k: country_weights[k])
    else:
        # Fallback: infer from name
        dominant = _infer_region_fallback(name)
        countries = {dominant: 1.0}
        region_data_available = False

    # --- Sector breakdown (yfinance) ---
    sector_weights = _fetch_sector_weights(effective_ticker) if effective_ticker else None
    if sector_weights:
        sectors = dict(sector_weights)
        sector_available = True
    else:
        # The country side always lands this fund's weight somewhere (justetf,
        # else a guess from the name), so nothing goes missing there. Sectors
        # had no such floor: the fund contributed nothing and the renormalise
        # in get_portfolio_breakdown then scaled every other fund up to close
        # the gap, so a portfolio half of which had no sector data showed the
        # other half's sectors at double their real share. Naming the gap keeps
        # the pie honest — "Unknown" renders as "Onbekend".
        sectors = {"Unknown": 1.0}
        sector_available = False

    return {
        "sector": sectors,
        "country": countries,
        "dominant_region": dominant,
        "region_data": region_data_available,
        "sector_data": sector_available,
    }


def get_portfolio_breakdown(
    conn: sqlite3.Connection,
    positions: list[dict],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], list[dict], float]:
    """
    Aggregate sector and country exposure across all positions, weighted by
    each position's current portfolio value.

    Primary source: the per-holding sector and country labels in the issuer
    holdings files (iShares/SPDR/Vanguard, or a registered index proxy) —
    the same exact data behind get_stock_exposure.  Funds without issuer
    data fall back to justetf.com country tables and yfinance fund-level
    sector weightings, as before.

    Parameters
    ----------
    positions : list of position dicts from portfolio.calculate_positions()

    Returns
    -------
    sector_totals : dict[str, float]
        Sector name → fraction of total valued portfolio (0–1).
    region_totals : dict[str, float]
        Country name → fraction of total valued portfolio (0–1), with everything
        below 0.5% folded into "Other" — the chartable list.
    continent_totals : dict[str, float]
        Continent name → fraction of total valued portfolio (0–1).
    coverage : list[dict]
        Per-position breakdown: name, value, region, sector_data_available.
    excluded_pct : float
        Percentage of total portfolio value excluded from the charts
        (bond funds — see bond_isins()).
    region_all_totals : dict[str, float]
        The same country fractions *before* that fold — every country the
        holdings mention, however small. Returned alongside rather than
        instead: the balk wants the short list (a dozen slivers of 0,1% is
        noise), but "where else am I invested" is a real question and the answer
        was thrown away here.
    """
    priced = [p for p in positions if p.get("current_value") is not None and p["current_value"] > 0]

    # Split into included and excluded positions upfront — off the *same* set
    # both times. These used to disagree: what counted was bond_isins() (the
    # user's own classification, then yfinance, then the hand-maintained list),
    # while what was *reported* as excluded was the hand-maintained list alone,
    # which holds exactly one ISIN. A bond the user classified themselves was
    # therefore left out of every percentage and mentioned nowhere: excluded_pct
    # came back 0, and the sentence saying bond funds are left out is only shown
    # when that is above zero, so the page said nothing at all. The reverse case
    # was just as wrong — classifying that one hardcoded ISIN as "Stocks" put it
    # in the percentages *and* in the excluded list, giving it two rows in the
    # coverage table and an excluded_pct that described nothing.
    excluded_isins = bond_isins(conn, priced)
    excluded = [p for p in priced if p["isin"] in excluded_isins]
    included = [p for p in priced if p["isin"] not in excluded_isins]

    total_value = sum(p["current_value"] for p in included)
    excluded_value = sum(p["current_value"] for p in excluded)
    excluded_pct = round(excluded_value / (total_value + excluded_value) * 100, 1) if (total_value + excluded_value) > 0 else 0

    sector_totals: dict[str, float] = {}
    region_totals: dict[str, float] = {}
    coverage: list[dict] = []

    # The coverage table lists every position, bonds included, so its "Gewicht"
    # column has to be one fraction of one whole — share of the portfolio. The
    # included rows used to be divided by the equity part and the excluded rows
    # by everything, so the column added up to more than 100%.
    grand_total = total_value + excluded_value

    for p in included:
        # Share of the *equity* part: this is what the sector and country
        # percentages are built from, so it must stay on that base.
        weight = p["current_value"] / total_value if total_value > 0 else 0
        portfolio_weight = p["current_value"] / grand_total if grand_total > 0 else 0
        mix = position_mix(conn, p["isin"], p["name"], p.get("ticker"))
        for sec, frac in mix["sector"].items():
            sector_totals[sec] = sector_totals.get(sec, 0.0) + frac * weight
        for cty, frac in mix["country"].items():
            region_totals[cty] = region_totals.get(cty, 0.0) + frac * weight
        coverage.append(
            {
                "name": p["name"],
                "isin": p["isin"],
                "ticker": p.get("ticker") or "–",
                "current_value": p["current_value"],
                "weight_pct": round(portfolio_weight * 100, 2),
                "dominant_region": mix["dominant_region"],
                "region_data": mix["region_data"],
                "sector_data": mix["sector_data"],
            }
        )

    # Add excluded positions to coverage (marked as excluded)
    for p in excluded:
        coverage.append(
            {
                "name": p["name"],
                "isin": p["isin"],
                "ticker": p.get("ticker") or "–",
                "current_value": p["current_value"],
                "weight_pct": round(p["current_value"] / grand_total * 100, 2) if grand_total > 0 else 0,
                "dominant_region": "Excluded (bond)",
                "region_data": "excluded",
                "sector_data": "excluded",
            }
        )

    # Renormalise sector totals to 1 (positions with no data are excluded)
    sector_sum = sum(sector_totals.values())
    if sector_sum > 0:
        sector_totals = {k: v / sector_sum for k, v in sector_totals.items()}

    # Renormalise region totals to 1 ("Other" from individual positions absorbs the gap)
    region_sum = sum(region_totals.values())
    if region_sum > 0:
        region_totals = {k: v / region_sum for k, v in region_totals.items()}

    # Roll countries up to continents from the full (un-bucketed) data, so even
    # tiny countries still count towards their continent.
    continent_totals: dict[str, float] = {}
    for country, frac in region_totals.items():
        cont = _continent_of(country)
        continent_totals[cont] = continent_totals.get(cont, 0.0) + frac

    # Keep the full list before the fold below throws it away: the tab shows the
    # chartable dozen, and offers this behind "Overig" for the rest.
    region_all_totals = dict(region_totals)

    # Drop tiny slices (< 0.5%) and bucket them into "Other"
    threshold = 0.005
    big = {k: v for k, v in region_totals.items() if v >= threshold or k == "Other"}
    small_sum = sum(v for k, v in region_totals.items() if v < threshold and k != "Other")
    if small_sum > 0:
        big["Other"] = big.get("Other", 0.0) + small_sum
    region_totals = big

    # Sort dicts largest-first
    sector_totals = dict(sorted(sector_totals.items(), key=lambda x: -x[1]))
    region_totals = dict(sorted(region_totals.items(), key=lambda x: -x[1]))
    region_all_totals = dict(sorted(region_all_totals.items(), key=lambda x: -x[1]))
    continent_totals = dict(sorted(continent_totals.items(), key=lambda x: -x[1]))

    return sector_totals, region_totals, continent_totals, coverage, excluded_pct, region_all_totals
