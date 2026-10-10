"""
News feeds for the News tab (and the dashboard's teaser card).

Three feeds, all built from the same two providers and the same normalised item
shape:

  * market   — general world/market news that moves the exchange (tariffs, a
               ceasefire, a central-bank decision).
  * holdings — news about the single stocks the user directly owns.
  * etf-top  — news about the five largest look-through holdings inside the
               user's ETFs (the ranking the Allocation tab already computes).

Both Finnhub and Alpha Vantage feed every list, and without a Finnhub key Yahoo
Finance (keyless, like the prices) fills in; their items are merged and
deduplicated so one provider covers what the other misses ("beide overal, met
fallback"). Everything remote goes through database.get_or_fetch, so a page load
never blocks on the network twice, and any provider failure degrades to an empty
contribution rather than an error — a feed with nothing to say just shows less.

Rate limits shape the caching, not the feature set:

  * Finnhub free tier is generous (60 calls/min), so it is the primary source
    and is refetched on the feed's own TTL (1 h).
  * Alpha Vantage free tier is only 25 calls/day. Its results are cached on a
    separate, longer TTL (see _AV_TTL_SECONDS) and gated by a per-day budget
    counter, and the client also recognises Alpha Vantage's own rate-limit
    response and falls back to Finnhub-only. So the AV enrichment can never
    break the daily cap; at worst it goes quiet until the next day.
"""

import datetime
import hashlib
import json

import requests

from domain import database
from app.core import config

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------

_FEED_TTL_SECONDS = 3600            # how long a merged feed is served from cache
_AV_TTL_SECONDS = 4 * 3600         # Alpha Vantage is fetched at most this often
_AV_DAILY_BUDGET = 20              # backstop under the 25/day free-tier cap
_HTTP_TIMEOUT = 8                  # seconds; a slow provider must not hang a load

_MARKET_CAP = 14
_LIST_CAP = 10
_HOLDINGS_TICKER_CAP = 12         # do not fan out to a huge portfolio at once
_COMPANY_NEWS_DAYS = 7            # company-news lookback window

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_AV_BASE = "https://www.alphavantage.co/query"

# Alpha Vantage topic filters for the macro/world feed. These are the buckets
# that actually move an index; company earnings topics are left out because the
# holdings/etf-top feeds cover those per ticker.
_AV_MARKET_TOPICS = "financial_markets,economy_macro,economy_fiscal,economy_monetary"


# ---------------------------------------------------------------------------
# Classification (pure — unit-testable without a network)
# ---------------------------------------------------------------------------

# Checked in this order; first hit wins. Dividend before earnings: a headline
# like "raises dividend after strong results" is dividend news to its reader.
# World (geopolitics) sits above Macro so "ceasefire" lands there rather than
# in the generic economics bucket.
_NEWS_LABELS: list[tuple[str, tuple[str, ...]]] = [
    ("Dividend", ("dividend", "payout", "payout", "buyback", "share repurchase", "inkoop")),
    ("Earnings", ("earnings", "kwartaalcijfers", "quarterly", "results", "results",
                  "revenue", "omzet", "guidance", "outlook", "profit", "winst", "beats",
                  "misses", "q1", "q2", "q3", "q4", "full-year", "halfjaar")),
    ("Analyst", ("analyst", "upgrade", "downgrade", "price target", "price_target", "rating",
                 "overweight", "underweight", "initiates", "reiterates", "buy rating",
                 "sell rating", "outperform")),
    ("M&A", ("acquisition", "acquires", "merger", "takeover", "overname", "buyout",
             "neemt over", "stake in", "to buy", "deal to", "fusie")),
    ("World", ("war", "oorlog", "ceasefire", "wapenstilstand", "sanction", "sanctie",
                "geopolit", "conflict", "military", "invasion", "invasie", "election",
                "verkiezing", "opec", "oil price", "olieprijs", "strait", "missile",
                "airstrike", "troops", "coup", "border")),
    ("Macro", ("ecb", "fed", "inflation", "inflatie", "interest rate", "interest",
               "central bank", "centrale bank", "recession", "recessie", "tariff",
               "heffing", "invoerheffing", "gdp", "bbp", "jobs report", "unemployment",
               "trade war", "handelsoorlog", "stimulus", "yield")),
]

_DEFAULT_NEWS_LABEL = "Macro"


def classify_news(title: str, summary: str = "") -> str:
    """Bucket a headline into the chip taxonomy the frontend colours.

    The summary is scanned too — provider headlines are often terse ("ASML Q2")
    while the body carries the signal ("raises full-year guidance")."""
    text = f"{title or ''} {summary or ''}".lower()
    for label, keywords in _NEWS_LABELS:
        if any(k in text for k in keywords):
            return label
    return _DEFAULT_NEWS_LABEL


# ---------------------------------------------------------------------------
# Normalised item + dedup
# ---------------------------------------------------------------------------

def _safe_link(link: str | None) -> str | None:
    """Only http(s) links go to the browser: a feed is outside data, and a
    javascript: or data: link in an <a href> would run in the app's origin."""
    if not isinstance(link, str):
        return None
    link = link.strip()
    return link if link.lower().startswith(("https://", "http://")) else None


def _item(
    *, ident: str, title: str, summary: str | None, publisher: str | None,
    link: str | None, published: str | None, ticker: str | None,
    holding: str | None, sentiment: float | None, source_api: str,
) -> dict:
    return {
        "id": ident,
        "title": title,
        "summary": summary or None,
        "publisher": publisher or None,
        "link": _safe_link(link),
        "published": published,
        "ticker": ticker,
        "holding": holding,
        "label": classify_news(title, summary or ""),
        "sentiment": sentiment,
        "source_api": source_api,
    }


def _merge(*sources: list[dict], cap: int) -> list[dict]:
    """Flatten provider lists into one feed, newest first, without duplicates.

    A story often reaches both providers under slightly different headlines, so
    dedup keys on the canonical URL first and falls back to a normalised title.
    Items with a real timestamp sort above undated ones."""
    seen_left: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []
    for source in sources:
        for it in source:
            title_key = (it.get("title") or "").strip().lower()
            if not title_key:
                continue
            link_key = (it.get("link") or "").strip().lower()
            if (link_key and link_key in seen_left) or title_key in seen_titles:
                continue
            if link_key:
                seen_left.add(link_key)
            seen_titles.add(title_key)
            out.append(it)
    out.sort(key=lambda i: i["published"] or "", reverse=True)
    return out[:cap]


def _fingerprint(*objs) -> str:
    return hashlib.sha1(json.dumps(objs, sort_keys=True, default=str).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Finnhub (primary source)
# ---------------------------------------------------------------------------

def _finnhub_get(path: str, params: dict) -> list:
    if not config.FINNHUB_API_KEY:
        return []
    try:
        resp = requests.get(
            f"{_FINNHUB_BASE}/{path}",
            params={**params, "token": config.FINNHUB_API_KEY},
            timeout=_HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else []
    except (requests.RequestException, ValueError):
        return []


def _finnhub_normalise(raw: dict, ticker: str | None, holding: str | None) -> dict | None:
    headline = raw.get("headline")
    if not headline:
        return None
    published = None
    ts = raw.get("datetime")
    if ts:
        try:
            published = datetime.datetime.fromtimestamp(
                int(ts), tz=datetime.timezone.utc
            ).isoformat()
        except (ValueError, OSError, OverflowError):
            pass
    ident = str(raw.get("id") or raw.get("url") or f"{ticker or 'gen'}:{headline[:60]}")
    return _item(
        ident=f"fh:{ident}",
        title=headline,
        summary=raw.get("summary"),
        publisher=raw.get("source"),
        link=raw.get("url"),
        published=published,
        ticker=ticker or (raw.get("related") or None),
        holding=holding,
        sentiment=None,
        source_api="finnhub",
    )


def _finnhub_general() -> list[dict]:
    raw = _finnhub_get("news", {"category": "general"})
    items = [_finnhub_normalise(r, None, None) for r in raw]
    return [i for i in items if i]


def _finnhub_company(symbol: str, holding: str | None) -> list[dict]:
    today = datetime.date.today()
    frm = today - datetime.timedelta(days=_COMPANY_NEWS_DAYS)
    # Finnhub keys company news on the bare symbol, not the Yahoo venue suffix
    # the portfolio stores — "ASML.AS" returns nothing, "ASML" resolves. Strip
    # it, and tag the items with the bare symbol so they read the same as AV's.
    api_symbol = _bare_symbol(symbol)
    raw = _finnhub_get(
        "company-news",
        {"symbol": api_symbol, "from": frm.isoformat(), "to": today.isoformat()},
    )
    items = [_finnhub_normalise(r, api_symbol, holding) for r in raw]
    return [i for i in items if i]


# ---------------------------------------------------------------------------
# Alpha Vantage (secondary source — rate-limit budgeted)
# ---------------------------------------------------------------------------

def _av_budget_remaining(conn) -> bool:
    """True while today's Alpha Vantage call count is under the daily budget.

    The counter lives in the per-user settings table keyed by date, so it resets
    naturally at midnight without any cleanup job. It is a backstop, not the main
    defence — the long _AV_TTL_SECONDS cache is what keeps calls rare — but it
    stops a cache-miss storm (many refreshes in one day) from burning the cap."""
    key = f"av_news_calls:{datetime.date.today().isoformat()}"
    try:
        used = int(database.load_setting(conn, key, "0") or "0")
    except (TypeError, ValueError):
        used = 0
    return used < _AV_DAILY_BUDGET


def _av_record_call(conn) -> None:
    key = f"av_news_calls:{datetime.date.today().isoformat()}"
    try:
        used = int(database.load_setting(conn, key, "0") or "0")
    except (TypeError, ValueError):
        used = 0
    database.save_setting(conn, key, str(used + 1))


def _bare_symbol(ticker: str) -> str:
    """Strip a Yahoo-style exchange suffix to the bare symbol (ASML.AS -> ASML).

    Both news providers key company news on the bare symbol, not the venue-
    suffixed Yahoo ticker the portfolio stores: Alpha Vantage requires it, and
    Finnhub returns nothing for "ASML.AS" while "ASML" (the same company's
    primary/US listing) resolves. Best effort — an unknown symbol simply
    returns no feed."""
    return ticker.split(".")[0].upper() if ticker else ticker


def _av_fetch(conn, *, tickers: str | None, topics: str | None) -> list[dict]:
    """One NEWS_SENTIMENT call, or [] if the key is missing, the budget is spent,
    or Alpha Vantage answers with a rate-limit/error note instead of a feed."""
    if not config.ALPHAVANTAGE_API_KEY or not _av_budget_remaining(conn):
        return []
    params = {
        "function": "NEWS_SENTIMENT",
        "apikey": config.ALPHAVANTAGE_API_KEY,
        "sort": "LATEST",
        "limit": "50",
    }
    if tickers:
        params["tickers"] = tickers
    if topics:
        params["topics"] = topics
    try:
        resp = requests.get(_AV_BASE, params=params, timeout=_HTTP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []
    # A successful HTTP 200 that carries "Note"/"Information" but no "feed" is
    # Alpha Vantage's way of saying "rate limited" or "bad request" — count it
    # as a spent call (it was one) and contribute nothing.
    _av_record_call(conn)
    feed = data.get("feed")
    if not isinstance(feed, list):
        return []
    items = [_av_normalise(r) for r in feed]
    return [i for i in items if i]


def _av_normalise(raw: dict) -> dict | None:
    title = raw.get("title")
    if not title:
        return None
    published = None
    tp = raw.get("time_published")  # "YYYYMMDDTHHMMSS"
    if isinstance(tp, str) and len(tp) >= 15:
        try:
            published = datetime.datetime.strptime(tp[:15], "%Y%m%dT%H%M%S").replace(
                tzinfo=datetime.timezone.utc
            ).isoformat()
        except ValueError:
            pass
    sentiment = raw.get("overall_sentiment_score")
    try:
        sentiment = float(sentiment) if sentiment is not None else None
    except (TypeError, ValueError):
        sentiment = None
    # The most-relevant tagged ticker, if any, becomes the item's ticker.
    ticker = None
    ts = raw.get("ticker_sentiment")
    if isinstance(ts, list) and ts:
        try:
            best = max(ts, key=lambda t: float(t.get("relevance_score", 0) or 0))
            ticker = best.get("ticker")
        except (TypeError, ValueError):
            ticker = ts[0].get("ticker")
    return _item(
        ident=f"av:{raw.get('url') or title[:60]}",
        title=title,
        summary=raw.get("summary"),
        publisher=raw.get("source"),
        link=raw.get("url"),
        published=published,
        ticker=ticker,
        holding=None,
        sentiment=sentiment,
        source_api="alphavantage",
    )


def _av_cached(conn, scope: str, *, tickers: str | None, topics: str | None) -> list[dict]:
    """Serve Alpha Vantage results for a scope from a longer-lived cache than the
    feed itself, so hourly feed refreshes do not each cost an AV call."""
    key = f"news:av:{scope}:{_fingerprint(tickers, topics)}"
    try:
        return database.get_or_fetch(
            conn, key, _AV_TTL_SECONDS,
            lambda: _av_fetch(conn, tickers=tickers, topics=topics),
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Yahoo Finance (keyless fallback)
# ---------------------------------------------------------------------------

# Index symbols whose Yahoo news page carries general market headlines.
_YAHOO_MARKET_SYMBOLS = ("^GSPC", "^STOXX50E")
_YAHOO_NEWS_COUNT = 10


def _yahoo_enabled() -> bool:
    """Yahoo fills in when no Finnhub key is set, so the News tab is never empty
    just because nobody signed up for an API key. Prices already come from
    Yahoo, so it needs nothing new."""
    return not config.FINNHUB_API_KEY


def _yahoo_normalise(raw: dict, ticker: str | None, holding: str | None) -> dict | None:
    """yfinance has returned two shapes over the years: the current one nests
    everything under "content", the old one is flat. Both are read."""
    c = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    title = c.get("title")
    if not title:
        return None
    url = ((c.get("canonicalUrl") or {}).get("url")
           or (c.get("clickThroughUrl") or {}).get("url")
           or c.get("link"))
    publisher = (c.get("provider") or {}).get("displayName") or c.get("publisher")
    published = c.get("pubDate") or c.get("displayTime")
    if not published and c.get("providerPublishTime"):
        try:
            published = datetime.datetime.fromtimestamp(
                int(c["providerPublishTime"]), tz=datetime.timezone.utc
            ).isoformat()
        except (ValueError, OSError, OverflowError):
            published = None
    if published:
        try:
            published = datetime.datetime.fromisoformat(
                str(published).replace("Z", "+00:00")
            ).isoformat()
        except ValueError:
            published = None
    ident = str(raw.get("id") or raw.get("uuid") or url or title[:60])
    return _item(
        ident=f"yh:{ident}",
        title=title,
        summary=c.get("summary") or c.get("description"),
        publisher=publisher,
        link=url,
        published=published,
        ticker=ticker,
        holding=holding,
        sentiment=None,
        source_api="yahoo",
    )


def _yahoo_news(symbol: str, holding: str | None = None, *, tag: str | None = None) -> list[dict]:
    if not _yahoo_enabled():
        return []
    try:
        import yfinance as yf
        raw = yf.Ticker(symbol).get_news(count=_YAHOO_NEWS_COUNT)
    except Exception:   # a Yahoo hiccup must not hurt the page
        return []
    items = [_yahoo_normalise(r, tag, holding) for r in raw or [] if isinstance(r, dict)]
    return [i for i in items if i]


# ---------------------------------------------------------------------------
# Public feeds
# ---------------------------------------------------------------------------

def get_market_news(conn) -> list[dict]:
    """General world/market headlines that move the exchange."""
    def fetch():
        return _merge(
            _finnhub_general(),
            _av_cached(conn, "market", tickers=None, topics=_AV_MARKET_TOPICS),
            *(_yahoo_news(s) for s in _YAHOO_MARKET_SYMBOLS),
            cap=_MARKET_CAP,
        )
    try:
        return database.get_or_fetch(conn, "news:market", _FEED_TTL_SECONDS, fetch)
    except Exception:
        return []


def _company_feed(conn, scope: str, holdings: list[dict]) -> list[dict]:
    """Shared body of the holdings and etf-top feeds: per-ticker Finnhub company
    news plus one batched Alpha Vantage call across all the tickers.

    *holdings* is a list of {"symbol"/"ticker": str, "name"/"holding": str|None}.
    """
    pairs: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for h in holdings:
        sym = (h.get("symbol") or h.get("ticker") or "").strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        pairs.append((sym, h.get("name") or h.get("holding")))
        if len(pairs) >= _HOLDINGS_TICKER_CAP:
            break
    if not pairs:
        return []

    key = f"news:{scope}:{_fingerprint(sorted(s for s, _ in pairs))}"

    def fetch():
        finnhub_items: list[dict] = []
        for symbol, name in pairs:
            finnhub_items.extend(_finnhub_company(symbol, name))
        av_tickers = ",".join(dict.fromkeys(_bare_symbol(s) for s, _ in pairs))
        av_items = _av_cached(conn, scope, tickers=av_tickers, topics=None)
        yahoo_items: list[dict] = []
        for symbol, name in pairs:
            yahoo_items.extend(_yahoo_news(symbol, name, tag=_bare_symbol(symbol)))
        return _merge(finnhub_items, av_items, yahoo_items, cap=_LIST_CAP)

    try:
        return database.get_or_fetch(conn, key, _FEED_TTL_SECONDS, fetch)
    except Exception:
        return []


def get_holdings_news(conn, positions: list[dict]) -> list[dict]:
    """News about the single stocks the user directly owns."""
    holdings = [
        {"symbol": p["ticker"], "name": p.get("name")}
        for p in positions
        if p.get("ticker")
    ]
    return _company_feed(conn, "holdings", holdings)


def get_etf_top_news(conn, top_stocks: list[dict]) -> list[dict]:
    """News about the top look-through holdings inside the user's ETFs.

    *top_stocks* is the Allocation tab's stock_list slice: dicts with a "symbol" and
    "name". Entries whose symbol is a fallback display string (no real ticker)
    are skipped — company-news needs an actual symbol.
    """
    holdings = [
        {"symbol": s["symbol"], "name": s.get("name")}
        for s in top_stocks
        if s.get("symbol") and s["symbol"].isascii() and " " not in s["symbol"]
        and "…" not in s["symbol"]
    ]
    return _company_feed(conn, "etf-top", holdings)


def get_combined_news(conn, positions: list[dict], top_stocks: list[dict]) -> list[dict]:
    """The dashboard teaser card's feed: holdings + ETF look-through + market
    news, merged newest-first and deduplicated across all three.

    The News tab keeps the three feeds separate, but the dashboard has room for
    one card. Folding all three in means the card stays populated for an
    ETF-only portfolio — which owns no single stocks directly, so its holdings
    feed is empty and, on its own, the card would hide itself. Holdings go first
    so a story that also surfaces via ETF-top/market keeps its holdings framing.
    """
    return _merge(
        get_holdings_news(conn, positions),
        get_etf_top_news(conn, top_stocks),
        get_market_news(conn),
        cap=_LIST_CAP,
    )


def clear_cache(conn) -> None:
    """Drop every news feed and the Alpha Vantage sub-caches (not the daily
    budget counter — that must survive a manual refresh)."""
    database.clear_api_cache(conn, "news:")
