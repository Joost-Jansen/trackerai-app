"""Prices from Tradegate, as an extra source next to Yahoo.

Yahoo has no Tradegate feed: a position on exchange TDG gets the XETRA price
there (see portfolio._DEGIRO_VENUES). This fetches Tradegate's own price for
such a position, from the same JSON the order book page of tradegatebsx.com
refreshes every few seconds. It is an *additional* price: the portfolio
valuation stays on the Yahoo price, so the day chip, the intraday line and the
totals keep their single source.

Unofficial. The Nutzungsbedingungen of Tradegate Exchange GmbH do not allow
automated access; the owner of this app weighed that and chose to do it
anyway, for personal use. Therefore:

  * **As few requests as possible.** One cache per process, shared by all
    accounts (a price is not personal), with a TTL of minutes during trading
    and half an hour outside it. Failed attempts are remembered *too*, so an
    outage does not cost a new request on every render.
  * **No circumvention.** An honest user agent, no cookies or referer. A
    redirect, 403 or 429 is read as "not welcome" and gets a long pause
    instead of a second attempt. The trades endpoint (with the times of
    trades) refuses direct calls and is therefore not used.
  * **Can be switched off.** TRADEGATE_QUOTES=off turns the whole request off.

What the source does and does not say:

  * `last`, `bid` and `ask` are three different numbers and stay that way. A
    bid, ask or mid price is never used as the last traded price; if `last`
    is missing, it is None.
  * There is **no time of the quote** in the response. `quote_time` is
    therefore always None, and `fetched_at` is only the moment of fetching.
  * Numbers come in alternately as a JSON number (55.52) and as German text
    ("124,80"); both are read. "0,00" and "./." mean "no price" and become
    None.
  * An invalid or unknown ISIN gives HTTP 200 with an empty body.
"""

import datetime
import math
import os
import re
import threading
import time
from dataclasses import dataclass

import requests

from app.core import price_refresh
from domain.i18n import tr

VENUE_CODE = "TDG"   # DeGiro's exchange code for Tradegate
VENUE_NAME = "Tradegate Exchange"
SOURCE_LABEL = "Tradegate Exchange (website, unofficial)"

REFRESH_URL = "https://www.tradegatebsx.com/refresh.php"
USER_AGENT = "stock-tracker/1.0 (personal, non-commercial use)"

#: (connect, read) in seconds. With two attempts and the pause between them a
#: hanging Tradegate holds up a request for ~15 seconds at most — and it is an
#: endpoint of its own, so the rest of the page does not wait for it.
TIMEOUT = (3.05, 4.0)
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5

#: How long a successful price lasts before it may be asked for again.
TTL_SESSION_SECONDS = 120
TTL_CLOSED_SECONDS = 30 * 60
#: How long after a failure nothing is asked again.
TTL_UNAVAILABLE_SECONDS = 60          # timeout, connection, 5xx
TTL_REFUSED_SECONDS = 15 * 60         # 3xx, 403, 429: Tradegate does not want it
TTL_NO_DATA_SECONDS = 6 * 60 * 60     # empty body: Tradegate does not know this ISIN

#: Tradegate's trading hours, in the container's time zone
#: (Europe/Amsterdam, the same as Berlin).
SESSION_OPEN, SESSION_CLOSE = datetime.time(7, 30), datetime.time(22, 0)


def enabled() -> bool:
    return os.environ.get("TRADEGATE_QUOTES", "on").strip().lower() not in ("off", "false", "0", "no")


# ---------------------------------------------------------------------------
# Input: ISIN and numbers
# ---------------------------------------------------------------------------

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def is_valid_isin(isin: object) -> bool:
    """Form and check digit (ISO 6166, Luhn over the digit string).

    Checked before anything goes over the network: a typo must not cost a
    request to Tradegate.
    """
    if not isinstance(isin, str) or not _ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def parse_number(value: object) -> float | None:
    """A number from Tradegate's JSON, or None.

    Accepts JSON numbers and German notation ("1 234,56", "1.234,56",
    "124,80", "-1,39%"). "./.", empty text and anything unreadable becomes
    None — never 0.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    s = value.strip().replace(" ", "").replace(" ", "").rstrip("%")
    if not s or s in ("./.", "-", "--"):
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        number = float(s)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _price(value: object) -> float | None:
    """A price: positive only. "0,00" is Tradegate's "no price"."""
    number = parse_number(value)
    return number if number is not None and number > 0 else None


def _count(value: object) -> int | None:
    number = parse_number(value)
    return int(number) if number is not None and number >= 0 else None


# ---------------------------------------------------------------------------
# Reading the response
# ---------------------------------------------------------------------------

class TradegateError(Exception):
    status = "unavailable"
    ttl = TTL_UNAVAILABLE_SECONDS


class TradegateUnavailable(TradegateError):
    """Temporary: timeout, no connection, server error."""


class TradegateRefused(TradegateError):
    """Tradegate sends us away (redirect, 403, 429). Do not retry."""
    status = "refused"
    ttl = TTL_REFUSED_SECONDS


class TradegateNoData(TradegateError):
    """A response, but without a usable price for this ISIN."""
    status = "no_data"
    ttl = TTL_NO_DATA_SECONDS


def session_open(now: datetime.datetime) -> bool:
    return price_refresh.is_trading_day(now.date()) and SESSION_OPEN <= now.time() <= SESSION_CLOSE


def parse_quote(isin: str, payload: object, now: datetime.datetime) -> dict:
    """Tradegate's JSON as this app's quote. Raises TradegateNoData."""
    if not isinstance(payload, dict):
        raise TradegateNoData("response is not an object")

    last = _price(payload.get("last"))
    bid = _price(payload.get("bid"))
    ask = _price(payload.get("ask"))
    if last is None and bid is None and ask is None:
        raise TradegateNoData("no last, bid or ask price")

    executions = _count(payload.get("executions"))
    volume = _count(payload.get("stueck"))
    currency = payload.get("waehrung")
    currency = currency.strip().upper() if isinstance(currency, str) and currency.strip() else "EUR"

    return {
        "status": "ok",
        "isin": isin,
        "venue": VENUE_CODE,
        "venue_name": VENUE_NAME,
        "source": SOURCE_LABEL,
        # The site itself: "Kurse in EUR; Fremdwährungsanleihen in der jeweiligen
        # Währung". The field `waehrung` is normally missing; the site's own page
        # falls back to EUR as well.
        "currency": currency,
        "last": last,
        "bid": bid,
        "ask": ask,
        "previous_close": _price(payload.get("close")),
        "high": _price(payload.get("high")),
        "low": _price(payload.get("low")),
        "change_pct": parse_number(payload.get("delta")),
        "volume": volume,
        "turnover": parse_number(payload.get("umsatz")),
        "executions": executions,
        # "A" is active; anything else (or a trading halt, secstate "H") makes bid
        # and ask unreliable — the order book page then shows a warning too.
        "trading_state": str(payload.get("state") or "A"),
        "halted": payload.get("secstate") == "H",
        "quote_time": None,
        "fetched_at": now.isoformat(timespec="seconds"),
        "session_open": session_open(now),
        # None when Tradegate does not give the number: unknown is not "no".
        "traded_today": (executions > 0) if executions is not None else None,
    }


# ---------------------------------------------------------------------------
# The network
# ---------------------------------------------------------------------------

# Indirections, so the tests need no real network connection or clock.
_http_get = requests.get
_sleep = time.sleep
_monotonic = time.monotonic
_now = datetime.datetime.now


def _download(isin: str) -> object:
    """The JSON for one ISIN, with bounded retries. Raises TradegateError."""
    reason = "unknown error"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = _http_get(
                REFRESH_URL,
                params={"isin": isin},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=TIMEOUT,
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            reason = f"no response ({type(e).__name__})"
        except requests.RequestException as e:
            raise TradegateUnavailable(f"request failed ({type(e).__name__})") from e
        else:
            code = response.status_code
            if 300 <= code < 400 or code in (403, 429):
                raise TradegateRefused(f"HTTP {code}")
            if code >= 500:
                reason = f"HTTP {code}"
            elif code >= 400:
                raise TradegateNoData(f"HTTP {code}")
            else:
                if not (response.text or "").strip():
                    raise TradegateNoData("empty response")
                try:
                    return response.json()
                except ValueError as e:
                    raise TradegateNoData("response is not JSON") from e
        if attempt < MAX_ATTEMPTS:
            _sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise TradegateUnavailable(reason)


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------

@dataclass
class _Entry:
    quote: dict | None          # : the last successful price, also after an outage
    quote_at: float | None      # : monotonic moment of that price
    retry_at: float             # : monotonic: no new request before this moment
    error_status: str | None = None
    error: str | None = None


_cache: dict[str, _Entry] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def clear_cache() -> None:
    with _locks_guard:
        _cache.clear()
        _locks.clear()


def _lock_for(isin: str) -> threading.Lock:
    # Per ISIN, so two simultaneous renders of the same page make one request and
    # the second waits for the first one's cache.
    with _locks_guard:
        return _locks.setdefault(isin, threading.Lock())


def _present(isin: str, entry: _Entry) -> dict:
    if entry.quote is None:
        messages = {
            "unavailable": tr("Tradegate can't be reached right now."),
            "refused": tr("Tradegate refuses the request; it won't be asked again for a while."),
            "no_data": tr("Tradegate has no price for this ISIN."),
        }
        return {
            "status": entry.error_status or "unavailable",
            "isin": isin,
            "venue": VENUE_CODE,
            "source": SOURCE_LABEL,
            "message": messages.get(entry.error_status or "", tr("No price available.")),
            "error": entry.error,
        }
    result = dict(entry.quote)
    # Stale: the last attempt failed and this is a price fetched earlier.
    result["stale"] = entry.error_status is not None
    result["error"] = entry.error
    result["age_seconds"] = int(max(0.0, _monotonic() - (entry.quote_at or 0.0)))
    return result


def get_quote(isin: str) -> dict:
    """The Tradegate price of an ISIN, from the cache where allowed.

    Never raises: every outcome is a dict with a `status` —
    "ok" (possibly with stale=True), "unavailable", "refused", "no_data",
    "invalid_isin" or "disabled".
    """
    isin = (isin or "").strip().upper()
    if not enabled():
        return {"status": "disabled", "isin": isin, "venue": VENUE_CODE, "source": SOURCE_LABEL,
                "message": tr("Tradegate prices are off (TRADEGATE_QUOTES=off).")}
    if not is_valid_isin(isin):
        return {"status": "invalid_isin", "isin": isin, "venue": VENUE_CODE, "source": SOURCE_LABEL,
                "message": tr("This is not a valid ISIN.")}

    with _lock_for(isin):
        entry = _cache.get(isin)
        if entry is not None and _monotonic() < entry.retry_at:
            return _present(isin, entry)

        now = _now()
        try:
            quote = parse_quote(isin, _download(isin), now)
        except TradegateError as e:
            previous = entry.quote if entry else None
            # An ISIN that did have a price earlier gets no six-hour pause on an empty
            # body: that is more likely a hiccup than an unknown ISIN.
            ttl = TTL_UNAVAILABLE_SECONDS if previous and isinstance(e, TradegateNoData) else e.ttl
            print(f"[tradegate] {isin}: {e.status} — {e}")
            entry = _Entry(
                quote=previous,
                quote_at=entry.quote_at if entry else None,
                retry_at=_monotonic() + ttl,
                error_status=e.status,
                error=str(e),
            )
        except Exception as e:   # an unexpected shape must not hurt the app
            print(f"[tradegate] {isin}: unexpected error — {repr(e)}")
            entry = _Entry(
                quote=entry.quote if entry else None,
                quote_at=entry.quote_at if entry else None,
                retry_at=_monotonic() + TTL_UNAVAILABLE_SECONDS,
                error_status="unavailable",
                error=type(e).__name__,
            )
        else:
            ttl = TTL_SESSION_SECONDS if quote["session_open"] else TTL_CLOSED_SECONDS
            entry = _Entry(quote=quote, quote_at=_monotonic(), retry_at=_monotonic() + ttl)
        _cache[isin] = entry
        return _present(isin, entry)
