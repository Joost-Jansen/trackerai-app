"""Keeps the price cache warm on its own, during market hours.

Every "today" in this app is read off that cache: the hero chip is `price`
against `previous_close`, the intraday line's endpoints are anchored to the same
two numbers, and the visit strip follows the chip. One cache, one answer — which
is the design, and it holds exactly as long as the cache is current.

Nothing kept it current. Prices moved only on an upload, on a ticker-override
delete, and on the Update button, so a tab left open across the day showed a
chip labelled "today" that was measuring yesterday, beside a value card whose
own series *had* refreshed (its cache entry expires hourly and re-downloads).
The gap between those two was as wide as the cache was old: EUR 435 on a
nine-day-old one.

Design notes:

  * **In the API process, not a cron on the host.** A cron would have to
    authenticate to reach /api/prices/refresh — the endpoint is per-user and
    behind a session cookie — so it would need a stored credential for every
    account. In here there is no HTTP and no cookie: it walks the accounts and
    refreshes each user's own database directly, exactly as the endpoint does
    for one of them.
  * **A thread, not an asyncio task.** portfolio.refresh_all_prices blocks on
    yfinance and sleeps between ISINs; on the event loop it would stall every
    request for the length of a refresh.
  * **Market hours only.** Refreshing at 03:00 spends requests to store the
    same close again. The window runs to just past the last European close so
    the final print of the day is what the cache holds overnight — that is the
    number the chip measures the *next* day from.
  * **Never fatal.** Any failure is logged and the loop lives on: a stale price
    is a bad day, a crashed API process is a worse one. yfinance failing leaves
    the previous price in place (see portfolio.refresh_all_prices), so a bad
    fetch degrades to "not refreshed", never to "no price".
"""

import datetime
import os
import threading
import time

from app.core import auth_store   # importing anything under `app` puts the
                                  # repo root on sys.path (see app/__init__.py)
from app.core import notify

from domain import database
from domain.portfolio import positions as portfolio

#: How often to refresh while the market is open. Five minutes matches the
#: intraday bars the 1D chart draws, so the chip and the shape it is anchored
#: to never age differently by more than one bar.
INTERVAL_SECONDS = int(os.environ.get("PRICE_REFRESH_INTERVAL_SECONDS", 300))

#: The window, in the container's own timezone (TZ=Europe/Amsterdam, see the
#: Dockerfile). Amsterdam opens at 09:00 and closes 17:40, Xetra 09:00-17:30,
#: Tradegate runs to 22:00; from five minutes before the first open to twenty
#: past the last close covers every listing this app will price, plus the
#: closing auction's print.
OPEN_HOUR, CLOSE_HOUR = datetime.time(8, 55), datetime.time(22, 20)

#: Saturday and Sunday.
_WEEKEND = (5, 6)

_thread: threading.Thread | None = None
_stop = threading.Event()


def _easter(year: int) -> datetime.date:
    """Easter Sunday, anonymous Gregorian algorithm. Good Friday and Easter
    Monday are the only moving holidays Euronext observes, and both hang off
    this date."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    return datetime.date(year, month, day)


def exchange_holidays(year: int) -> frozenset[datetime.date]:
    """The days Euronext Amsterdam does not trade.

    Six a year, and the list has not changed in two decades: New Year's Day,
    Good Friday, Easter Monday, Labour Day, Christmas and Boxing Day. Amsterdam
    rather than Xetra or Tradegate because that is where DeGiro's Dutch orders
    print, and a day the *reader's* exchange is shut is the one that decides
    whether "today" happened at all.

    A list, where the refresh loop needed none: for spending requests it is
    harmless to ask a shut exchange for the same close again, but for *labelling*
    a number "today" the difference is the whole statement.
    """
    easter = _easter(year)
    return frozenset({
        datetime.date(year, 1, 1),
        easter - datetime.timedelta(days=2),   # Good Friday
        easter + datetime.timedelta(days=1),   # Easter Monday
        datetime.date(year, 5, 1),
        datetime.date(year, 12, 25),
        datetime.date(year, 12, 26),
    })


def is_trading_day(day: datetime.date) -> bool:
    """Whether the exchange opens at all on *day*."""
    return day.weekday() not in _WEEKEND and day not in exchange_holidays(day.year)


def traded_today(now: datetime.datetime | None = None) -> bool:
    """Whether a session has actually begun printing prices today.

    False all weekend, all of a holiday, and on a trading day until the opening
    bell — three states in which the newest quote available is still the
    *previous* session's close, so `price` against `previous_close` measures
    that session and not this date. The hero chip reads this to decide whether
    it may say "today" over a number at all.

    Before the open is deliberately in the same bucket as a holiday: at 08:00 on
    a Monday the cache holds Friday's close against Thursday's, which is exactly
    the Saturday situation with a different name on it.
    """
    now = now or datetime.datetime.now()
    return is_trading_day(now.date()) and now.time() >= OPEN_HOUR


def is_market_window(now: datetime.datetime | None = None) -> bool:
    """Whether a refresh could learn anything right now."""
    now = now or datetime.datetime.now()
    if not is_trading_day(now.date()):
        return False
    return OPEN_HOUR <= now.time() <= CLOSE_HOUR


def last_close_passed(now: datetime.datetime | None = None) -> datetime.datetime:
    """The most recent moment a European session has finished printing.

    "Is this quote stale?" cannot be answered with an age in hours. Friday's
    closing price is the right number to show all weekend — it is what the next
    day is measured from, which is why the refresh window deliberately runs
    past the last close and lets that print stand overnight. But the same quote
    on Tuesday afternoon means two refreshes have silently failed.

    So the question is not "how old" but "has a session closed since?". This
    returns the last CLOSE_HOUR on a weekday that is already behind us;
    anything fetched before it has missed a close it should have seen.
    """
    now = now or datetime.datetime.now()
    day = now.date()
    if not is_trading_day(day) or now.time() < CLOSE_HOUR:
        # Today's close has not happened (or never will), so walk back to the
        # most recent trading day and take its close.
        while True:
            day -= datetime.timedelta(days=1)
            if is_trading_day(day):
                break
    return datetime.datetime.combine(day, CLOSE_HOUR)


def is_stale(fetched_at: str | None, now: datetime.datetime | None = None) -> bool:
    """Whether a stored quote has missed a close it should have been refreshed for.

    Unparseable or absent counts as stale: a timestamp nobody can read is not
    evidence of freshness.
    """
    if not fetched_at:
        return True
    try:
        fetched = datetime.datetime.fromisoformat(fetched_at)
    except ValueError:
        return True
    return fetched < last_close_passed(now)


#: How long a reported position stays quiet afterwards. A position that cannot
#: be priced stays unpriced until someone acts on it, and this loop comes round
#: every five minutes — without a hold-off the same warning would arrive 288
#: times a day. A week later it repeats, because it is still broken.
ALERT_REPEAT_DAYS = 7


def _usernames() -> list[str]:
    cfg = auth_store.load_config()
    return sorted((cfg.get("credentials", {}).get("usernames") or {}).keys())


def unpriced_positions(conn) -> list[dict]:
    """Open positions this app has never managed to price.

    Not "the last fetch failed" — that leaves the previous price in place and
    the position keeps counting (see portfolio.refresh_all_prices). This is the
    case that hides: no usable price stored at all, so the row shows "—", sits
    out every total, and the only sign of it is one line of grey text on the
    owner's own screen. That is how a holding went uncounted for a week before
    its owner mentioned it in a chat message.
    """
    from app.services import venue_price_service   # it imports this module

    transactions = database.load_transactions(conn)
    # A position priced only off Tradegate is priced, not missing.
    prices = venue_price_service.effective_prices(
        transactions, database.load_prices(conn), database.load_venue_prices(conn)
    )
    return [
        position
        for position in portfolio.calculate_positions(transactions, prices)
        if position["current_value"] is None
    ]


def _alert_unpriced(conn, username: str) -> int:
    """Pushes one warning for this account's newly-unpriced positions.

    The hold-off marker rides in the api-cache table, which is already a
    general key/value store with timestamps (portfolio.py keeps its OpenFIGI
    answers there under "figi:"). It is written only after the push actually
    goes out, so an unreachable ntfy postpones the warning instead of
    swallowing it for a week.
    """
    if not notify.topic_url():
        return 0

    pending = [
        position for position in unpriced_positions(conn)
        if database.load_etf_api_cache(
            conn, f"price-alert:{position['isin']}", max_age_days=ALERT_REPEAT_DAYS
        ) is None
    ]
    if not pending:
        return 0

    lines = [f"• {p['name'][:44]} ({p['isin']})" for p in pending]
    sent = notify.push(
        f"Stock-tracker: {len(pending)} position(s) without a price",
        f"Account {username}:\n" + "\n".join(lines)
        + """

These don't count in the portfolio total.""",
    )
    if not sent:
        return 0

    for position in pending:
        database.save_etf_api_cache(conn, f"price-alert:{position['isin']}", "reported")
    return len(pending)


def refresh_every_user() -> dict[str, portfolio.RefreshResult]:
    """One pass: every account's prices, refreshed in its own database.

    Returns {username: RefreshResult}, for the log line. A user without
    transactions has no ISINs and costs one empty SELECT.

    This used to return the *size of each price cache*, which is not a measure
    of anything this function did: with the uplink down, every fetch failing
    still logged "18 prices for 1 account(s)". Nothing distinguished a healthy
    round from a dead one, in the one place an operator would look.
    """
    done: dict[str, portfolio.RefreshResult] = {}
    for username in _usernames():
        conn = None
        try:
            # The default same-thread check stands: this connection is opened,
            # used and closed inside this one loop iteration, on this thread.
            conn = database.connect(username)
            database.init_db(conn)
            done[username] = portfolio.refresh_all_prices(conn)
            # Imported here: venue_price_service reads this module's calendar.
            from app.services import venue_price_service
            venue_price_service.refresh(conn)
            _alert_unpriced(conn, username)
        except Exception as e:   # one broken account must not stop the rest
            print(f"[price-refresh] {username}: {e}")
        finally:
            if conn is not None:
                conn.close()
    return done


def _walk() -> None:
    while not _stop.is_set():
        if is_market_window():
            started = time.monotonic()
            done = refresh_every_user()
            refreshed = sum(r.refreshed for r in done.values())
            failed = sum(len(r.failed) for r in done.values())
            skipped = sum(r.skipped for r in done.values())
            # Printed whenever anything was *attempted*, not only when
            # something succeeded: a round of nothing but failures is the round
            # most worth seeing, and gating on a success count is exactly how
            # it stayed invisible.
            if refreshed or failed or skipped:
                line = (f"[price-refresh] {refreshed} refreshed for "
                        f"{len(done)} account(s) in {time.monotonic() - started:.1f}s")
                if failed:
                    line += f", {failed} failed"
                if skipped:
                    line += f", {skipped} skipped (deadline)"
                print(line)
        # Wait on the event rather than sleeping, so shutdown is immediate
        # instead of up to one interval away.
        _stop.wait(INTERVAL_SECONDS)


def start() -> bool:
    """Starts the loop unless it is switched off or already running.

    Off by default outside a container: `next dev` against a local uvicorn
    would otherwise download prices for every account on the machine every
    five minutes, and the test suite never reaches here (TestClient does not
    run the lifespan unless it is entered as a context manager).
    """
    global _thread
    if os.environ.get("PRICE_REFRESH", "off").strip().lower() not in ("on", "true", "1"):
        return False
    if _thread is not None and _thread.is_alive():
        return False
    _stop.clear()
    _thread = threading.Thread(target=_walk, name="price-refresh", daemon=True)
    _thread.start()
    return True


def stop() -> None:
    _stop.set()
