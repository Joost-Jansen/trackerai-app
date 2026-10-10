"""
portfolio.py — Calculates portfolio returns and fetches live prices
"""

import os
import re
import socket
import sqlite3
import time
from dataclasses import dataclass

import requests
import yfinance as yf

from domain import database

# Kept as a floor for anything that reaches the network through Python's own
# socket module. It is NOT what bounds yfinance: since 1.x yfinance talks
# through curl_cffi, and libcurl creates its sockets in C without consulting
# this default — measured, a call that should have stopped at 10s blocked for
# 30. Nor does an explicit timeout= help, because yfinance's cookie/crumb
# bootstrap is called without one and uses its own 30s inside yours. What
# actually bounds a refresh is REFRESH_DEADLINE_SECONDS below.
socket.setdefaulttimeout(10)

_EU_SUFFIXES = [".AS", ".DE", ".PA", ".MI", ".BR", ".SW"]
_EUR_EXCHANGES = {"AMS", "GER", "PAR", "MIL", "BRU", "EBS", "VIE", "ATH"}

# DeGiro "Beurs" code → the venue it names: the ISO market identifiers (MICs)
# that OpenFIGI answers questions about, the Yahoo ticker suffix for that same
# venue, and whether it quotes in euro.
#
# The MICs are a tuple because OpenFIGI keys on the *segment* MIC, not the
# operating one that names the exchange as a whole. Nasdaq's XNAS and Milan's
# XMIL are operating MICs and match nothing at all: every Nasdaq holding of
# every user resolved to nothing for as long as they were in this table, and
# fell through to the name search below, which either priced the position off a
# thin German cross-listing or lost it entirely. Nasdaq splits into three
# segments (Global Select, Global Market, Capital Market) and a listing sits in
# exactly one, so they are tried in turn.
#
# This table is where a price should come from. ISIN + MIC is an exact question
# with one answer; the name search further down is guesswork, and it fails in a
# way nobody sees — Yahoo indexes no US ISINs at all, and a product name like
# "ADR ON TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED" returns nothing
# while "TAIWAN SEMICONDUCTOR MANUFACTURING" returns TSM. A holding whose venue
# is missing here silently ends up with no price and drops out of the totals,
# so the table covers every venue a DeGiro account can trade on, not only the
# five that appear in today's uploads (EAM, XET, TDG, NSY, NDQ).
#
# Every row here was checked against OpenFIGI with a known ISIN of that venue
# (2026-09-04) — that is how the two wrong MICs above were found. A wrong
# DeGiro *code* costs nothing: it never matches and the search below runs as
# before. A wrong MIC is what hurts, because it fails the same way while
# looking correct. tests/test_price_resolution.py pins the shape.
#
# Not every venue quotes in euro. For those the OpenFIGI ticker is still the
# right listing — the position genuinely trades there — so its quote is
# converted, rather than swapped for a European cross-listing of the same
# security. Those cross-listings are usually thin and stale (TSMC's Vienna line
# repeats yesterday's close), and for an ADR they can be a different number of
# shares altogether.
_DEGIRO_VENUES: dict[str, tuple[tuple[str, ...], str, bool]] = {
    #  code:   (MICs,                        Yahoo suffix, quotes in EUR)
    "EAM":     (("XAMS",),                   ".AS", True),   # Euronext Amsterdam
    "EPA":     (("XPAR",),                   ".PA", True),   # Euronext Paris
    "EBR":     (("XBRU",),                   ".BR", True),   # Euronext Brussels
    "MIL":     (("MTAA",),                   ".MI", True),   # Borsa Italiana — MTAA,
                                                             # not the operating XMIL
    "MAD":     (("XMAD",),                   ".MC", True),   # Bolsa de Madrid
    "LIS":     (("XLIS",),                   ".LS", True),   # Euronext Lisbon
    "HEL":     (("XHEL",),                   ".HE", True),   # Nasdaq Helsinki
    "VIE":     (("XWBO",),                   ".VI", True),   # Wiener Börse
    "XET":     (("XETR",),                   ".DE", True),   # XETRA
    "TDG":     (("XETR",),                   ".DE", True),   # Tradegate — no Yahoo feed,
                                                             # XETRA is the closest German
                                                             # venue and prints the same
    "FRA":     (("XFRA",),                   ".F",  True),   # Börse Frankfurt (floor)
    "NSY":     (("XNYS",),                   "",    False),  # NYSE — USD, Yahoo carries
                                                             # US tickers bare
    "NDQ":     (("XNGS", "XNMS", "XNCM"),    "",    False),  # Nasdaq — USD; Global Select,
                                                             # Global Market, Capital Market
    "LSE":     (("XLON",),                   ".L",  False),  # London — quoted in pence,
                                                             # see _fx_to_eur_rate
    "EBS":     (("XSWX",),                   ".SW", False),  # SIX Swiss — CHF
    "OSL":     (("XOSL",),                   ".OL", False),  # Oslo Børs — NOK
    "STO":     (("XSTO",),                   ".ST", False),  # Nasdaq Stockholm — SEK
    "CPH":     (("XCSE",),                   ".CO", False),  # Nasdaq Copenhagen — DKK
    "TOR":     (("XTSE",),                   ".TO", False),  # Toronto — CAD
    "TSE":     (("XTKS",),                   ".T",  False),  # Tokyo — JPY
    "HKG":     (("XHKG",),                   ".HK", False),  # Hong Kong — HKD
    "ASX":     (("XASX",),                   ".AX", False),  # Sydney — AUD
}

# The euro venues, for the name search below: it hunts for a EUR listing, so
# pinning it to a venue only means anything where that venue quotes in euro.
_DEGIRO_EXCHANGE_SUFFIX = {
    code: suffix for code, (_mics, suffix, eur) in _DEGIRO_VENUES.items() if eur
}

# Yahoo ticker suffix → exchange code used in Yahoo *search* results.
_SUFFIX_SEARCH_EXCHANGE = {
    ".AS": "AMS", ".DE": "GER", ".PA": "PAR",
    ".MI": "MIL", ".BR": "BRU", ".SW": "EBS",
}
_NAME_STOP_WORDS = {
    "ucits", "etf", "usd", "eur", "acc", "dist", "dis", "inc",
    "(acc)", "(dist)", "(inc)", "(dis)", "hedged", "gbp", "jpy", "chf",
    "cad", "on", "reg.", "shs",
}
_NAME_EXPANSIONS = {
    "ISHRS": "iShares",
    "ISHS": "iShares",
    "ISHARES": "iShares",
    "STST": "State Street SPDR",
    "SPDR": "SPDR",
    "VNGU": "Vanguard",
    "VGRD": "Vanguard",
}

# ISINs where Yahoo Finance's automatic search resolves to the wrong ticker.
_ISIN_TICKER_OVERRIDE: dict[str, str] = {
    "IE0031442068": "IUSA.AS",  # iShares Core S&P 500 UCITS ETF (Dist) — auto-search wrongly returns SXR8.DE
    "IE00B4L5YC18": "EUNM.DE",  # iShares MSCI EM UCITS ETF USD (Acc) — auto-search wrongly returns EUNI.DE (Dist)
    "IE000WA6L436": "CEBE.DE",  # iShares iBonds Dec 2026 Term EUR Corp ETF — not found by auto-search
    "IE00BYTRRD19": "WTCH.AS",  # SPDR MSCI World Technology — search only finds the stale Stuttgart
                                # listing; WTCH.AS is the Amsterdam venue the position is traded on
    "IE00B1XNHC34": "IQQH.DE",  # iShares Global Clean Energy — auto-search only finds INRG.L (GBp);
                                # the INRG.AS listing Yahoo returns is stale at ~half price. IQQH.DE
                                # (XETRA) matches the DeGiro quote.
}


def _extract_name_keywords(name: str) -> str:
    words = name.split()
    words = [_NAME_EXPANSIONS.get(w.upper(), w) for w in words]
    name = " ".join(words)

    for marker in [" UCITS ", " ETF USD", " ETF EUR", " UCITS"]:
        idx = name.upper().find(marker.upper())
        if idx > 4:
            name = name[:idx]
            break

    cleaned = [w for w in name.split() if w.lower() not in _NAME_STOP_WORDS]
    return " ".join(cleaned[:5]).strip()


def _search_candidates(query: str, max_results: int = 8) -> list[tuple[str, str]]:
    try:
        results = yf.Search(query, max_results=max_results, timeout=8)
        return [
            (q["symbol"], q.get("exchange", ""))
            for q in results.quotes
            if q.get("symbol")
        ]
    except Exception as e:
        print(f"  Search failed for '{query}': {e}")
        return []


# --- Does a candidate ticker price the instrument the user actually holds? ---
#
# The Yahoo search behind steps 2-6 matches on names, and names lie: one iShares
# Nasdaq-100 ETF and another iShares Nasdaq-100 ETF can be two different funds
# at seven times each other's price. Nothing downstream can tell - a wrong fund
# prices every day and moves every day, exactly like the right one - and the
# cached ticker then keeps it for good. OpenFIGI and the overrides are
# authoritative; the search is a guess, and a guess needs checking.
#
# The one piece of ground truth every user has is what they paid. The close of a
# candidate listing on the day of the user's most recent trade has to sit near
# the price of that trade: a same-day close and an execution price differ by a
# few percent at most, a different fund by a factor. The band is wide on
# purpose - it is here to catch the factor, not to police the percent.
#
# What it cannot catch: two share classes of one fund that happen to trade a few
# percent apart (a Dist and an Acc class). For those, and for anything else the
# search gets wrong, there is the per-user ticker override on the Details page.
_PLAUSIBLE_BAND = (0.75, 1.33)
_CHECK_TTL_SECONDS = 30 * 24 * 3600


def _reference_trade(conn: sqlite3.Connection, isin: str) -> tuple[str, float] | None:
    """(date, price per share in EUR) of the user's most recent trade in *isin*."""
    for t in reversed(database.load_transactions(conn)):
        if t["isin"] != isin or not t.get("quantity"):
            continue
        qty = abs(t["quantity"])
        if t.get("value_eur"):
            return t["date"], abs(t["value_eur"]) / qty
        if t.get("price") and t.get("exchange_rate") in (None, 0, 1):
            return t["date"], abs(t["price"])
    return None


def _close_on(symbol: str, day: str) -> float | None:
    """*symbol*'s close on *day*, or the last one in the week before it.

    Split-adjusted, as Yahoo serves its history; see _split_factor_since.
    """
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(day)
        hist = yf.Ticker(symbol).history(
            start=(d - _dt.timedelta(days=7)).isoformat(),
            end=(d + _dt.timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
        closes = hist["Close"].dropna()
        return float(closes.iloc[-1]) if len(closes) else None
    except Exception:
        return None


def _split_factor_since(symbol: str, day: str) -> float:
    """How many shares one share on *day* has become since then (1.0 if none).

    Yahoo adjusts its history for later splits; a trade price from before a
    split is not adjusted, so it is divided by this before comparing.
    """
    import pandas as _pd
    try:
        splits = yf.Ticker(symbol).splits
        if splits is None or len(splits) == 0:
            return 1.0
        cutoff = _pd.Timestamp(day)
        factor = 1.0
        for ts, ratio in splits.items():
            ts = _pd.Timestamp(ts)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
            if ts > cutoff and ratio:
                factor *= float(ratio)
        return factor
    except Exception:
        return 1.0


def _consistent_with_trades(conn: sqlite3.Connection, isin: str, symbol: str, result: dict) -> bool:
    """False when *symbol* cannot be the instrument the user traded as *isin*.

    True whenever there is nothing to check against - no trade with a price, no
    history for the candidate, no exchange rate - so this can only ever remove a
    guess, never stand between a position and a price it would otherwise get.
    The verdict is cached: the refresh loop asks on every pass.
    """
    ref = _reference_trade(conn, isin)
    if not ref:
        return True
    day, paid = ref

    def check() -> dict:
        close = _close_on(symbol, day)
        if close is None:
            return {"ok": True}
        currency = result.get("currency") or "EUR"
        if currency != "EUR":
            rate = _fx_to_eur_rate(currency)
            if not rate:
                return {"ok": True}
            close *= rate
        paid_adj = paid / _split_factor_since(symbol, day)
        if not paid_adj:
            return {"ok": True}
        ratio = close / paid_adj
        lo, hi = _PLAUSIBLE_BAND
        return {"ok": lo <= ratio <= hi, "close": round(close, 4), "paid": round(paid_adj, 4)}

    key = f"price-check:{isin}:{symbol}:{day}:{paid:.4f}"
    verdict = database.get_or_fetch(conn, key, _CHECK_TTL_SECONDS, check)
    if not verdict.get("ok"):
        print(f"  Rejected '{symbol}' for {isin}: it closed at €{verdict['close']:.2f} on {day}, "
              f"while that trade was at €{verdict['paid']:.2f} — a different instrument")
    return bool(verdict.get("ok"))


# --- Share class: a Dist and an Acc class are different instruments ---
#
# The one thing the trade check above cannot tell apart. Both classes of one
# fund trade a few percent from each other, so a search that lands on the other
# class passes, and the position is then priced as a fund the user does not
# hold: the value drifts by the dividends the other class keeps or pays out.
#
# DeGiro's product name says which class the user holds ("... USD DIS",
# "... (ACC)"). Yahoo's long name says it for the classes it marks — in practice
# "Accumulation" on the Acc listing, nothing on the Dist one. So a candidate is
# only turned away when *both* names state a class and the two differ; a name
# that says nothing is never held against a listing.
_ACC_MARKERS = re.compile(r"\b(ACC|ACCUMULATING|ACCUMULATION|CAPITALISATION)\b", re.IGNORECASE)
_DIST_MARKERS = re.compile(r"\b(DIS|DIST|DISTRIBUTING|DISTRIBUTION)\b", re.IGNORECASE)


def _share_class(name: str | None) -> str | None:
    """'acc', 'dist', or None when the name says neither (or, confusingly, both)."""
    acc = bool(_ACC_MARKERS.search(name or ""))
    dist = bool(_DIST_MARKERS.search(name or ""))
    if acc == dist:
        return None
    return "acc" if acc else "dist"


def _yahoo_long_name(conn: sqlite3.Connection, symbol: str) -> str | None:
    """Yahoo's long name for *symbol*, cached like the trade check."""
    def fetch() -> dict:
        try:
            info = yf.Ticker(symbol).info or {}
            return {"name": info.get("longName") or info.get("shortName") or ""}
        except Exception:
            return {"name": ""}
    return database.get_or_fetch(conn, f"yahoo-name:{symbol}", _CHECK_TTL_SECONDS, fetch).get("name") or None


def _acceptable(conn: sqlite3.Connection, isin: str, name: str, symbol: str, result: dict) -> bool:
    """A guessed listing may price this position: right share class, plausible price."""
    ours = _share_class(name)
    # Only a position whose name states a class costs a lookup; a share or a
    # fund with one class never asks Yahoo for anything extra.
    if ours:
        theirs = _share_class(_yahoo_long_name(conn, symbol))
        if theirs and theirs != ours:
            print(f"  Rejected '{symbol}' for {isin}: that is the {theirs} class, "
                  f"the position is {ours}")
            return False
    return _consistent_with_trades(conn, isin, symbol, result)


def fetch_price_for_isin(
    conn: sqlite3.Connection,
    isin: str,
    name: str,
    preferred_suffix: str | None = None,
    degiro_exchange: str | None = None,
) -> dict | None:
    """
    Finds a EUR price for the ISIN.  `preferred_suffix` (e.g. ".AS") pins the
    listing to the venue the position is actually traded on, so the price
    matches what DeGiro displays; other EUR listings remain a fallback when
    that venue has no Yahoo listing.  `degiro_exchange` (the DeGiro "Beurs"
    code, e.g. "XET") lets OpenFIGI resolve the exact ticker for that venue.

    Resolution order: user override → curated override → cached ticker →
    OpenFIGI (ISIN+venue) → Yahoo search.
    """
    def _matches_pref(symbol: str) -> bool:
        return not preferred_suffix or symbol.endswith(preferred_suffix)

    # --- 0a. User ticker override (manual correction, highest priority) ---
    user_override = database.load_ticker_overrides(conn).get(isin)
    if user_override:
        result = _fetch_by_ticker(user_override)
        if result:
            print(f"  Using user override ticker '{user_override}' for {isin}")
            return {"isin": isin, "name": name, **result}
        print(f"  User override '{user_override}' for {isin} returned no price — falling back")

    # --- 0b. Hardcoded ticker override (Yahoo search returns wrong ticker for these ISINs) ---
    if isin in _ISIN_TICKER_OVERRIDE:
        symbol = _ISIN_TICKER_OVERRIDE[isin]
        result = _fetch_by_ticker(symbol)
        if result:
            print(f"  Using override ticker '{symbol}' for {isin}")
            return {"isin": isin, "name": name, **result}

    venue = _DEGIRO_VENUES.get(degiro_exchange or "")
    # A position on a venue that does not quote in euro has no EUR listing of
    # its own, so a cached EUR ticker is always some *other* listing — and
    # `preferred_suffix` is None for exactly those venues, which left
    # _matches_pref waving through any cross-listing the search had once
    # settled on. Those tickers then re-cached themselves on every refresh and
    # never got revisited. Below, such a cache is demoted to a fallback so the
    # venue's own listing (step 1b) is asked for first.
    venue_quotes_eur = venue[2] if venue else True

    # --- 1. Use cached EUR ticker ---
    stored = database.load_prices(conn).get(isin, {})
    cached_result = None
    if stored.get("ticker") and stored.get("currency") == "EUR":
        result = _fetch_by_ticker(stored["ticker"])
        # A cached ticker came from a search once, and a search can be wrong:
        # without this check a wrong fund stays cached for good.
        if (result and result["currency"] == "EUR"
                and _acceptable(conn, isin, name, stored["ticker"], result)):
            if _matches_pref(stored["ticker"]) and venue_quotes_eur:
                print(f"  Using cached ticker '{stored['ticker']}' for {isin}")
                return {"isin": isin, "name": name, **result}
            # Cached listing is on the wrong venue: search for the preferred
            # one below, keeping this result so pricing is never lost.
            cached_result = {"isin": isin, "name": name, **result}

    # --- 1b. OpenFIGI: authoritative ISIN + venue → ticker ---
    if venue:
        mics, venue_suffix, quotes_eur = venue
        base = _openfigi_ticker(conn, isin, mics)
        if base:
            suffix = preferred_suffix or venue_suffix
            symbol = base + suffix
            result = _fetch_by_ticker(symbol)
            if not result:
                # Nordic share classes: Bloomberg writes NOVOB, Yahoo NOVO-B.
                dashed = _dashed_share_class(base)
                if dashed:
                    symbol = dashed + suffix
                    result = _fetch_by_ticker(symbol)
            if result and result["currency"] == "EUR":
                print(f"  OpenFIGI resolved {isin} → '{symbol}'")
                return {"isin": isin, "name": name, **result}
            # A venue that does not quote in euro has no EUR price to hold out
            # for: this *is* the listing the position trades on, so convert it
            # rather than fall through to a search for a different listing.
            if result and not quotes_eur:
                converted = _to_eur(result)
                if converted:
                    print(f"  OpenFIGI resolved {isin} → '{symbol}': converted "
                          f"{result['price']} {result['currency']} → €{converted['price']}")
                    return {"isin": isin, "name": name, **converted}

    print(f"  Searching '{isin}' ({name[:45]})...")

    # --- 2. Search by ISIN ---
    isin_hits = _search_candidates(isin)

    # --- 3. Search by cleaned product name ---
    keywords = _extract_name_keywords(name)
    name_hits = _search_candidates(keywords) if keywords else []

    preferred_exchange = _SUFFIX_SEARCH_EXCHANGE.get(preferred_suffix) if preferred_suffix else None

    seen_symbols: set[str] = set()
    eu_candidates: list[tuple[str, str]] = []   # (symbol, search-exchange)
    other_symbols: list[str] = []
    for sym, exch in isin_hits + name_hits:
        if sym in seen_symbols:
            continue
        seen_symbols.add(sym)
        if exch in _EUR_EXCHANGES:
            eu_candidates.append((sym, exch))
        else:
            other_symbols.append(sym)

    if isin not in seen_symbols:
        other_symbols.append(isin)

    if preferred_suffix:
        # Stable sort: listings on the trading venue first, rest unchanged.
        eu_candidates.sort(
            key=lambda c: 0 if (c[0].endswith(preferred_suffix) or c[1] == preferred_exchange) else 1
        )

    # --- 4. Try EU-exchange candidates first ---
    non_eur_result = None
    first_eur_result = None
    for symbol, _exch in eu_candidates:
        result = _fetch_by_ticker(symbol)
        if not result:
            continue
        if not _acceptable(conn, isin, name, symbol, result):
            continue
        if result["currency"] == "EUR":
            if _matches_pref(symbol):
                print(f"  Found EUR ticker '{symbol}' (EU exchange) for {isin}")
                return {"isin": isin, "name": name, **result}
            if first_eur_result is None:
                first_eur_result = {"isin": isin, "name": name, **result}
        elif non_eur_result is None:
            non_eur_result = {"isin": isin, "name": name, **result}

    # --- 5. Try other candidates ---
    for symbol in other_symbols:
        result = _fetch_by_ticker(symbol)
        if not result:
            continue
        if not _acceptable(conn, isin, name, symbol, result):
            continue
        if result["currency"] == "EUR":
            if _matches_pref(symbol):
                print(f"  Found EUR ticker '{symbol}' for {isin}")
                return {"isin": isin, "name": name, **result}
            if first_eur_result is None:
                first_eur_result = {"isin": isin, "name": name, **result}
        elif non_eur_result is None:
            non_eur_result = {"isin": isin, "name": name, **result}

    # --- 6. Try EU suffixes on all found ticker bases ---
    suffixes = list(_EU_SUFFIXES)
    if preferred_suffix in suffixes:
        suffixes.remove(preferred_suffix)
        suffixes.insert(0, preferred_suffix)

    all_tried = {s for s, _ in eu_candidates} | set(other_symbols)
    bases_searched: set[str] = set()
    for symbol in list(all_tried):
        base = symbol.split(".")[0]
        for suffix in suffixes:
            candidate = base + suffix
            if candidate in all_tried:
                continue
            all_tried.add(candidate)
            result = _fetch_by_ticker(candidate)
            if (result and result["currency"] == "EUR"
                    and _acceptable(conn, isin, name, candidate, result)):
                if _matches_pref(candidate):
                    print(f"  Found EUR ticker '{candidate}' (suffix search) for {isin}")
                    return {"isin": isin, "name": name, **result}
                if first_eur_result is None:
                    first_eur_result = {"isin": isin, "name": name, **result}
        if len(base) >= 3 and base not in bases_searched and base != isin:
            bases_searched.add(base)
            for alt_sym, alt_exch in _search_candidates(base, max_results=5):
                if alt_sym in all_tried:
                    continue
                all_tried.add(alt_sym)
                if alt_exch in _EUR_EXCHANGES:
                    result = _fetch_by_ticker(alt_sym)
                    if (result and result["currency"] == "EUR"
                            and _acceptable(conn, isin, name, alt_sym, result)):
                        if _matches_pref(alt_sym):
                            print(f"  Found EUR ticker '{alt_sym}' (base search) for {isin}")
                            return {"isin": isin, "name": name, **result}
                        if first_eur_result is None:
                            first_eur_result = {"isin": isin, "name": name, **result}

    # --- 7. Fallbacks: preferred venue not found ---
    if cached_result:
        print(f"  No '{preferred_suffix}' listing found for {isin} — "
              f"keeping cached ticker '{cached_result['ticker']}'")
        return cached_result
    if first_eur_result:
        print(f"  No '{preferred_suffix}' listing found for {isin} — "
              f"using '{first_eur_result['ticker']}'")
        return first_eur_result
    if non_eur_result:
        ccy = non_eur_result["currency"]
        converted = _to_eur(non_eur_result)
        if converted:
            print(f"  No EUR listing for {isin}: converted "
                  f"{non_eur_result['price']} {ccy} → €{converted['price']}")
            return converted
        print(f"  Warning: no EUR listing found for {isin} and no FX rate for {ccy}. "
              f"Using {non_eur_result['ticker']} ({ccy}).")
        return non_eur_result

    print(f"  Could not find any price for {isin}")
    return None


def _dashed_share_class(base: str) -> str | None:
    """NOVOB → NOVO-B: the Nordic share class as Yahoo spells it, or None.

    Bloomberg glues the class letter onto the stem, Yahoo separates it. Only
    tried after the plain ticker returns nothing, so a stem that merely happens
    to end in a letter (NOKIA) costs one failed lookup and nothing else.
    """
    if len(base) >= 4 and base[-1].isalpha() and "-" not in base:
        return f"{base[:-1]}-{base[-1]}"
    return None


def _to_eur(result: dict) -> dict | None:
    """Same quote restated in EUR at the spot rate, or None if no rate exists."""
    rate = _fx_to_eur_rate(result["currency"])
    if not rate:
        return None
    # The same spot rate applies to previous_close: yesterday's FX would be more
    # precise, but the pair must share a rate or a flat price would show a
    # phantom day move made purely of currency.
    prev = result.get("previous_close")
    return {
        **result,
        "price": round(result["price"] * rate, 4),
        "currency": "EUR",
        "previous_close": round(prev * rate, 4) if prev else None,
        # The ticker still quotes in the original currency — its history too,
        # which is what the charts download (see charts.listing_currency).
        "quote_currency": result["currency"],
        "quote_fx_rate": rate,
    }


def _fx_to_eur_rate(currency: str) -> float | None:
    """Spot rate that converts one unit of `currency` into EUR, or None."""
    if currency == "EUR":
        return 1.0
    scale = 1.0
    # Yahoo quotes some LSE listings in pence (GBp/GBX): 100 pence = 1 GBP.
    if currency in ("GBp", "GBX"):
        currency, scale = "GBP", 0.01
    try:
        info = yf.Ticker(f"{currency}EUR=X").fast_info
        rate = getattr(info, "last_price", None)
        if rate and rate > 0:
            return rate * scale
    except Exception:
        pass
    return None


_OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# Without a key OpenFIGI answers 25 mapping requests a minute. A first refresh
# of a portfolio with more ISINs than that ran into a 429 halfway, and every
# ISIN after it fell through to the Yahoo name search — the step that cannot
# tell a Dist class from an Acc one. So one 429 is waited out (as long as the
# server asks, within reason) and retried before giving up. OPENFIGI_API_KEY
# raises the limit tenfold; it is optional and read per call.
_OPENFIGI_MAX_WAIT_SECONDS = 30
_OPENFIGI_DEFAULT_WAIT_SECONDS = 10


def _openfigi_post(jobs: list[dict]) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    key = os.environ.get("OPENFIGI_API_KEY", "").strip()
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    resp = requests.post(_OPENFIGI_URL, json=jobs, headers=headers, timeout=8)
    if resp.status_code != 429:
        return resp
    wait = _OPENFIGI_DEFAULT_WAIT_SECONDS
    headers_in = getattr(resp, "headers", None) or {}
    for header in ("Retry-After", "ratelimit-reset"):
        try:
            wait = float(headers_in[header])
            break
        except (KeyError, TypeError, ValueError):
            continue
    if wait > _OPENFIGI_MAX_WAIT_SECONDS:
        return resp
    print(f"  OpenFIGI rate limit: waiting {wait:.0f}s")
    time.sleep(max(wait, 0))
    return requests.post(_OPENFIGI_URL, json=jobs, headers=headers, timeout=8)


def _openfigi_ticker(
    conn: sqlite3.Connection, isin: str, mics: tuple[str, ...]
) -> str | None:
    """
    Resolve an ISIN + venue to its bare exchange ticker via OpenFIGI
    (Bloomberg's free mapping API) — e.g. (IE00B1XNHC34, XETR) → "IQQH".

    `mics` are the venue's segment MICs, tried in order; a listing sits in one
    segment, so the first hit is the answer. This replaces fragile Yahoo
    name/ISIN search with an authoritative lookup, so it works for any user's
    holdings without hardcoding. Results (including known misses, cached as "")
    are kept 30 days in the etf_api_cache table to avoid repeat calls.

    The cache key holds the MICs it was answered for, so correcting a wrong MIC
    is enough to retire the misses it cached: they are keyed to a venue nothing
    asks about any more and expire on their own.
    """
    cache_key = f"figi:{isin}:{'+'.join(mics)}"
    cached = database.load_etf_api_cache(conn, cache_key, max_age_days=30)
    if cached is not None:
        return cached or None

    ticker = None
    for mic in mics:
        try:
            resp = _openfigi_post([{"idType": "ID_ISIN", "idValue": isin, "micCode": mic}])
        except Exception as e:
            # Transient failure: don't cache, just fall through to Yahoo search.
            print(f"  OpenFIGI lookup failed for {isin}/{mic}: {e}")
            return None

        # Only a 200 carries an answer. Anything else — a 429 from the
        # unauthenticated rate limit above all — says nothing about this ISIN,
        # and storing it as a miss would blind the venue for the full 30 days
        # over one busy minute.
        if resp.status_code != 200:
            print(f"  OpenFIGI returned {resp.status_code} for {isin}/{mic}")
            return None

        try:
            payload = resp.json()
            hits = payload[0].get("data") if payload and isinstance(payload, list) else None
        except Exception:
            return None

        if hits:
            raw = hits[0].get("ticker")
            if raw:
                # Bloomberg tickers carry the venue after a space ("TSM UN");
                # keep the root. Within it, a share class is written "BRK/B"
                # where Yahoo writes "BRK-B", and London tickers end in a bare
                # slash ("BP/" for BP.L) that Yahoo does not use at all.
                ticker = raw.split()[0].strip().upper().rstrip("/").replace("/", "-")
                break

    database.save_etf_api_cache(conn, cache_key, ticker or "")
    return ticker


def _fetch_by_ticker(symbol: str) -> dict | None:
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None)
        currency = getattr(info, "currency", "EUR")
        if price and price > 0:
            # previous_close feeds the dashboard's day change. Optional on
            # purpose: a missing/zero value stays None rather than fabricating
            # a 100% move, and the price fetch itself never fails over it.
            prev = getattr(info, "previous_close", None)
            return {
                "ticker": symbol,
                "price": round(price, 4),
                "currency": currency,
                "previous_close": round(prev, 4) if prev and prev > 0 else None,
            }
    except Exception:
        # Stay quiet: this gets probed with guessed tickers (suffix search)
        # that routinely don't exist; callers report when nothing is found.
        pass
    return None


@dataclass
class RefreshResult:
    """What one refresh pass actually achieved.

    Used to return `database.load_prices(conn)` — the whole cache, which has no
    relation to how the pass went. Both callers only took `len()` of it, so a
    round in which every single fetch failed still reported the full count:
    POST /api/prices/refresh answered `{"updated_count": 18}` and the sheet went
    green, while the price-refresh loop logged "18 prices for 1 account(s)".
    Neither the user nor the log could tell a working refresh from a dead
    uplink. These three numbers can.
    """
    refreshed: int          #: prices actually re-fetched and stored
    failed: list[dict]      #: [{isin, name}] this pass could not price
    skipped: int = 0        #: not attempted, because the deadline ran out

    @property
    def attempted(self) -> int:
        return self.refreshed + len(self.failed)

    @property
    def complete(self) -> bool:
        """Whether every ISIN was fetched. False is what callers report on."""
        return not self.failed and not self.skipped


#: How long one pass may run before it stops starting new ISINs, in seconds.
#: A stalled network does not fail fast: yfinance's cookie/crumb bootstrap
#: ignores the timeout its caller passes and blocks for 30s of its own, twice
#: per quote, and fetch_price_for_isin walks a cascade of candidate tickers —
#: one ISIN measured at 721 seconds. Eighteen of those is three and a half
#: hours in which the request thread, and the browser tab waiting on it, are
#: both simply gone. A normal full pass is well under a minute, so this cuts
#: only the pathological case, and what it cuts is reported as `skipped`
#: rather than quietly dropped.
REFRESH_DEADLINE_SECONDS = float(os.environ.get("PRICE_REFRESH_DEADLINE_SECONDS", 120))


def refresh_all_prices(
    conn: sqlite3.Connection,
    deadline_seconds: float | None = None,
) -> RefreshResult:
    """
    Re-fetches the current price for every ISIN in the portfolio.

    Always fetches a fresh price — a cached EUR ticker only short-circuits the
    ticker *search* (inside fetch_price_for_isin), never the price fetch
    itself.  If a fetch fails, the previously stored price is left untouched.

    Each ISIN is pinned to the Yahoo listing of the exchange it is mostly
    traded on (per the transactions), so prices match what DeGiro displays.

    Returns a RefreshResult saying what happened, not the price cache: see that
    class for why. Stops starting new ISINs after *deadline_seconds*; the ones
    it never got to come back as `skipped`.
    """
    isins = database.get_all_isins(conn)
    if not isins:
        print("No stocks in portfolio yet.")
        return RefreshResult(refreshed=0, failed=[])

    if deadline_seconds is None:
        deadline_seconds = REFRESH_DEADLINE_SECONDS

    print(f"Fetching prices for {len(isins)} stock(s)/ETF(s)...")
    home_exchanges = database.load_home_exchanges(conn)
    # Venue pinning only matters for positions still held; for closed ones any
    # cached EUR listing is fine and skipping the preference avoids needless
    # ticker searches on every refresh.
    open_isins = {p["isin"] for p in calculate_positions(database.load_transactions(conn), {})}

    started = time.monotonic()
    refreshed = 0
    failed: list[dict] = []

    for index, row in enumerate(isins):
        isin = row["isin"]
        name = row["name"]

        # Checked before starting one, never in the middle: a fetch already
        # under way is left to finish, so the deadline bounds when the pass
        # stops taking on work rather than cutting a quote in half.
        if time.monotonic() - started > deadline_seconds:
            skipped = len(isins) - index
            print(f"  Deadline reached after {deadline_seconds:.0f}s — "
                  f"{skipped} ISIN(s) not attempted")
            return RefreshResult(refreshed=refreshed, failed=failed, skipped=skipped)

        home_exchange = home_exchanges.get(isin, "")
        preferred_suffix = (
            _DEGIRO_EXCHANGE_SUFFIX.get(home_exchange)
            if isin in open_isins else None
        )
        result = fetch_price_for_isin(
            conn, isin, name,
            preferred_suffix=preferred_suffix,
            degiro_exchange=home_exchange or None,
        )
        if result:
            database.save_price(
                conn,
                isin=isin,
                name=name,
                ticker=result.get("ticker", ""),
                price=result["price"],
                currency=result.get("currency", "EUR"),
                previous_close=result.get("previous_close"),
                quote_currency=result.get("quote_currency"),
                quote_fx_rate=result.get("quote_fx_rate"),
            )
            refreshed += 1
        else:
            failed.append({"isin": isin, "name": name})
        time.sleep(0.5)

    return RefreshResult(refreshed=refreshed, failed=failed)


def calculate_positions(transactions: list[dict], prices: dict[str, dict]) -> list[dict]:
    by_isin: dict[str, list[dict]] = {}
    for t in transactions:
        isin = t["isin"]
        by_isin.setdefault(isin, []).append(t)

    positions = []

    for isin, trades in by_isin.items():
        shares_held = 0.0
        total_invested = 0.0

        for t in trades:
            qty   = t["quantity"]
            total = t["total_eur"]

            if t["transaction_type"] == "BUY":
                shares_held    += qty
                total_invested += abs(total) if total is not None else 0.0

            elif t["transaction_type"] == "SELL":
                if shares_held > 0:
                    # Clamp: selling more than held (e.g. missing buy data)
                    # must not flip the remaining cost basis negative.
                    fraction_sold   = min(qty / shares_held, 1.0)
                    total_invested -= total_invested * fraction_sold
                shares_held -= qty
                shares_held  = max(shares_held, 0.0)

        if shares_held <= 0.0001:
            continue

        avg_cost = total_invested / shares_held if shares_held > 0 else 0.0

        price_info = prices.get(isin)
        # A non-EUR price cannot be combined with the EUR cost basis — treat it
        # as missing rather than silently mixing currencies in the totals.
        if price_info and price_info.get("currency") != "EUR":
            price_info = None
        current_price = price_info["price"]    if price_info else None
        currency      = price_info["currency"] if price_info else "EUR"
        ticker        = price_info["ticker"]   if price_info else None

        if current_price is not None:
            current_value   = shares_held * current_price
            unrealized_gain = current_value - total_invested
            return_pct      = (unrealized_gain / total_invested * 100) if total_invested > 0 else 0.0
        else:
            current_value   = None
            unrealized_gain = None
            return_pct      = None

        positions.append({
            "isin":             isin,
            "name":             trades[0]["name"],
            "ticker":           ticker,
            "shares_held":      round(shares_held, 6),
            "avg_cost":         round(avg_cost, 4),
            "total_invested":   round(total_invested, 2),
            "current_price":    round(current_price, 4) if current_price else None,
            "currency":         currency,
            "current_value":    round(current_value, 2) if current_value else None,
            "unrealized_gain":  round(unrealized_gain, 2) if unrealized_gain is not None else None,
            "return_pct":       round(return_pct, 2) if return_pct is not None else None,
        })

    positions.sort(key=lambda p: p["current_value"] or 0, reverse=True)
    return positions


def calculate_closed_positions(transactions: list[dict]) -> list[dict]:
    """
    Returns a list of positions that have been fully sold (shares_held ≤ 0).
    For each closed position, calculates the realized P&L using the average
    cost basis method: as shares are sold, the proportion of the remaining
    cost basis is released and compared to the actual sale proceeds.
    """
    by_isin: dict[str, list[dict]] = {}
    for t in transactions:
        by_isin.setdefault(t["isin"], []).append(t)

    closed = []

    for isin, trades in by_isin.items():
        shares_held    = 0.0
        cost_base     = 0.0
        total_proceeds = 0.0
        realized_gain  = 0.0
        first_buy      = None
        last_sell      = None

        for t in sorted(trades, key=lambda x: (x["date"], x["time"] or "")):
            qty   = t["quantity"]
            total = abs(t["total_eur"]) if t.get("total_eur") is not None else 0.0

            if t["transaction_type"] == "BUY":
                shares_held += qty
                cost_base  += total
                if first_buy is None:
                    first_buy = t["date"]

            elif t["transaction_type"] == "SELL" and shares_held > 0:
                fraction        = min(qty / shares_held, 1.0)
                cost_of_sold    = cost_base * fraction
                realized_gain  += total - cost_of_sold
                total_proceeds += total
                cost_base     -= cost_of_sold
                shares_held    -= qty
                shares_held     = max(shares_held, 0.0)
                last_sell       = t["date"]

        if shares_held > 0.0001:
            continue  # still open

        total_invested = total_proceeds - realized_gain  # original cost of sold shares
        return_pct = (realized_gain / total_invested * 100) if total_invested > 0 else 0.0

        closed.append({
            "isin":           isin,
            "name":           trades[0]["name"],
            "first_buy":      first_buy,
            "last_sell":      last_sell,
            "total_invested": round(total_invested, 2),
            "total_proceeds": round(total_proceeds, 2),
            "realized_gain":  round(realized_gain, 2),
            "return_pct":     round(return_pct, 2),
        })

    closed.sort(key=lambda p: p["realized_gain"], reverse=True)
    return closed


def transaction_cost(t: dict) -> float:
    """Every euro DeGiro charged on one transaction, as a positive number.

    Both columns are charges on top of the trade's own value — DeGiro's
    `Totaal = Waarde + AutoFX + Transactiekosten` — and both are stored with
    the sign of the row, hence the abs().

    Shared so the dashboard's cost total and the Portfolio tab's per-position
    one cannot drift apart on what counts as a cost.
    """
    return abs(t.get("transaction_fee") or 0.0) + abs(t.get("autofx_cost") or 0.0)


def total_transaction_costs(transactions: list[dict]) -> float:
    return sum(transaction_cost(t) for t in transactions)


def calculate_portfolio_summary(positions: list[dict], transactions: list[dict] | None = None, dividends: list[dict] | None = None) -> dict:
    # Net investment = total paid for buys minus total received from sells.
    # This can go negative when you've cashed out more than you ever put in.
    if transactions is not None:
        net_investment = sum(
            abs(t["total_eur"]) if t["transaction_type"] == "BUY" else -abs(t["total_eur"])
            for t in transactions
            if t.get("total_eur") is not None
        )
    else:
        # Fallback: sum cost basis per position (cannot go negative but avoids breaking change)
        net_investment = sum(p["total_invested"] for p in positions)

    total_dividends = sum(d["net_eur"] for d in dividends) if dividends else 0.0

    priced         = [p for p in positions if p["current_value"] is not None]
    total_value    = sum(p["current_value"] for p in priced)
    total_gain     = total_value - net_investment

    # Split total_gain: "unrealized" is what the open positions are worth
    # versus their remaining cost basis; the rest is P&L already locked in
    # by sells (realized).  The split is only complete when every position
    # has a price (prices_available).
    unrealized_gain = sum(p["unrealized_gain"] for p in priced)
    invested_open   = sum(p["total_invested"] for p in priced)
    realized_gain   = total_gain - unrealized_gain
    unrealized_return_pct = (
        (unrealized_gain / invested_open * 100) if invested_open > 0 else 0.0
    )

    # None, not a number, once the denominator stops meaning "what you put in".
    # net_investment goes negative when more has been taken out than ever went
    # in, and dividing a gain by it flips the sign: a +EUR 3.500 profit came out
    # as -116,67%. The dashboard computes its own percentage and already skips
    # it in that case; this now says the same thing rather than offering a
    # plausible-looking number for a caller to trust.
    total_return_pct = (
        (total_gain / net_investment * 100) if net_investment > 0 else None
    )

    # Already deducted, never a separate term: buys enter net_investment at
    # total_eur (value + costs) and sells leave it at total_eur (proceeds -
    # costs), so total_gain is net of every fee below. This figure exists to
    # make that visible — subtracting it again would double-count it.
    total_costs = total_transaction_costs(transactions) if transactions else 0.0

    return {
        "net_investment":        round(net_investment, 2),
        "total_dividends":       round(total_dividends, 2),
        "total_costs":           round(total_costs, 2),
        "total_value":           round(total_value, 2),
        "total_gain":            round(total_gain, 2),
        "unrealized_gain":       round(unrealized_gain, 2),
        "unrealized_return_pct": round(unrealized_return_pct, 2),
        "realized_gain":         round(realized_gain, 2),
        "total_return_pct":      None if total_return_pct is None else round(total_return_pct, 2),
        "num_positions":         len(positions),
        "prices_available":      len(priced) == len(positions),
    }
