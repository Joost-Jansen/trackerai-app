"""
The Calendar tab: what is going to happen to these holdings, and when.

Three things land on this calendar, and the whole design turns on the fact that
they are not equally well known:

  * **Publicatiedatums.** When a company reports. Yahoo carries the next one
    per share; `earnings_dates` remembers the ones that have passed. A single
    date is one the company has confirmed; a pair is a window Yahoo is guessing
    at, and a guess does not get a day.
  * **Ex-dividenddatums.** Official ones, again from Yahoo, again only for
    shares — a UCITS tracker has no forward data there at all (verified: every
    fund 404s), which is the whole reason the third kind exists.
  * **Paid dividend.** What actually arrived, from the user's own
    payment history. Past-only and exact, and for a portfolio of eleven
    trackers it is the only thing that fills a past month.

Everything above is a *fact*: a date that happened or a date the source states.
It gets a day cell.

Estimates do not. dashboard_service.forecast_dividends can produce an exact day
for a tracker's next payment — it has to, to count forward — but that day is
arithmetic, not knowledge, and the app has one rule about it: **a estimate is
shown at month precision, never on a day.** So estimates come back on a
separate list, keyed by month with a begin/half/eind, and the tab renders them
in a strip under the grid instead of inside it. The rule is the reason the
strip exists; do not "improve" this by scattering them into the cells.

The whole payload is built from data that is already loaded or already cached:
the Yahoo sweep is shared with the dashboard's ex-dividend card
(dashboard_service.get_calendar_entries), and everything else is arithmetic
over rows. Opening this tab after the dashboard costs no network at all.
"""

import datetime
import sqlite3

from app.services import filings_service, holdings_service
from domain import database

#: How far either side of today the calendar carries events. A year back is
#: four quarters of reports and a full dividend cycle; a year forward is more
#: than any source actually knows, so the future end fills only as far as the
#: data reaches and stops looking empty by itself.
_MONTHS_BACK = 12
_MONTHS_AHEAD = 12


def _month_key(day: datetime.date) -> str:
    return day.isoformat()[:7]


def _shift_months(day: datetime.date, months: int) -> datetime.date:
    total = day.year * 12 + (day.month - 1) + months
    year, month = divmod(total, 12)
    return datetime.date(year, month + 1, 1)


def _window(today: datetime.date) -> tuple[str, str]:
    """The first and last day the calendar will accept an event on."""
    start = _shift_months(today.replace(day=1), -_MONTHS_BACK)
    end = _shift_months(today.replace(day=1), _MONTHS_AHEAD + 1) - datetime.timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _shares(positions: list[dict]) -> dict[str, dict]:
    """{isin: position} for the holdings that can report results.

    A tracker is excluded here rather than filtered out later, because "no
    reporting date for this fund" is not a gap in the data — a fund holds
    shares in companies that report, and publishes none of its own. Showing an
    empty earnings row under IWDA would invent a thing that does not exist.
    """
    return {p["isin"]: p for p in positions if p.get("isin") and holdings_service.asset_type(p.get("name") or "") == "share"}


# ---------------------------------------------------------------------------
# The three kinds of certain event
# ---------------------------------------------------------------------------


def earnings_events(
    stored: list[dict],
    entries: list[dict],
    shares: dict[str, dict],
) -> tuple[list[dict], list[dict]]:
    """(day-cell events, month-strip windows) for reporting dates.

    *stored* is what `earnings_dates` remembers, *entries* the fresh sweep.
    They overlap by design — the sweep is what fills the table — so this
    de-duplicates on (isin, date) and lets the sweep's view of `confirmed` win,
    it being the newer of the two.

    A ticker with *two* dates in the sweep has given a window, not a date. Both
    ends are dropped from the day cells and one entry goes to the strip
    instead, spanning whatever it spans.
    """
    windows: list[dict] = []
    windowed: set[tuple[str, str]] = set()

    for entry in entries:
        isin = entry.get("isin")
        dates = sorted(entry.get("earnings_dates") or [])
        if isin not in shares or len(dates) < 2:
            continue
        for date in dates:
            windowed.add((isin, date))
        windows.append(
            {
                "isin": isin,
                "name": shares[isin].get("name"),
                "type": "earnings",
                "month": dates[0][:7],
                "from": dates[0],
                "to": dates[-1],
                "source": "estimate",
            }
        )

    seen: set[tuple[str, str]] = set()
    events: list[dict] = []
    fresh = {
        (e["isin"], d): len(e.get("earnings_dates") or []) == 1 for e in entries if e.get("isin") for d in (e.get("earnings_dates") or [])
    }
    for row in stored:
        isin, date = row.get("isin"), row.get("date")
        key = (isin, date)
        if isin not in shares or not date or key in seen or key in windowed:
            continue
        if not fresh.get(key, row.get("confirmed")):
            continue  # a window this sweep still calls a window
        seen.add(key)
        events.append(
            {
                "date": date,
                "type": "earnings",
                "isin": isin,
                "name": shares[isin].get("name"),
                "ticker": shares[isin].get("ticker"),
            }
        )
    return events, windows


def ex_dividend_events(entries: list[dict], held: set[str]) -> list[dict]:
    """Official ex-dividend dates from the sweep, past ones included — the
    sweep keeps returning a date for a while after it passes, and a date that
    was true stays true."""
    events = []
    for entry in entries:
        isin, ex_date = entry.get("isin"), entry.get("ex_date")
        if not isin or not ex_date or isin not in held:
            continue
        events.append(
            {
                "date": ex_date[:10],
                "type": "ex_dividend",
                "isin": isin,
                "name": entry.get("name"),
                "ticker": entry.get("ticker"),
                "pay_date": (entry.get("pay_date") or None),
            }
        )
    return events


def dividend_paid_events(dividends: list[dict], names: dict[str, str]) -> list[dict]:
    """Payments that actually arrived, one row per holding per day.

    Same same-day summing as dashboard_service.payment_events, and for the same
    reason: DeGiro splits one payment into a gross line and a tax line, and two
    entries on one day would read as two dividends.
    """
    totals: dict[tuple[str, str], float] = {}
    for d in dividends:
        isin, date = d.get("isin"), d.get("date")
        if not isin or not date or d.get("net_eur") is None:
            continue
        key = (isin, date[:10])
        totals[key] = totals.get(key, 0.0) + d["net_eur"]

    return [
        {
            "date": date,
            "type": "dividend_paid",
            "isin": isin,
            "name": names.get(isin),
            "amount_eur": round(amount, 2),
        }
        for (isin, date), amount in totals.items()
        if round(amount, 2) != 0.0
    ]


# ---------------------------------------------------------------------------
# The strip: everything shown at month precision
# ---------------------------------------------------------------------------


def estimate_rows(outlook: dict, windows: list[dict]) -> list[dict]:
    """The month-precision list under each grid: dividend ramingen plus any
    reporting window.

    Entries the outlook has already resolved to an official date (`source ==
    "official"`) are left out — those are facts and have a day cell of their
    own, from ex_dividend_events; carrying them here too would print the same
    ex-dividend twice on one month.
    """
    rows = [
        {
            "isin": e.get("isin"),
            "name": e.get("name"),
            "type": "ex_dividend",
            "month": e.get("month") or (e.get("date") or "")[:7],
            "part": e.get("part"),
            "expected_eur": e.get("expected_eur"),
            "confidence": e.get("confidence"),
            "cadence": e.get("cadence"),
            "source": "estimate",
        }
        for e in outlook.get("upcoming", [])
        if e.get("source") == "estimate"
    ]
    rows.extend(windows)
    rows.sort(key=lambda r: (r.get("month") or "", r.get("name") or ""))
    return rows


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build(
    conn: sqlite3.Connection,
    positions: list[dict],
    dividends: list[dict],
    outlook: dict,
    entries: list[dict],
    today: datetime.date | None = None,
) -> dict:
    """The whole tab. See the module docstring for what goes where and why."""
    today = today or datetime.date.today()
    start, end = _window(today)

    held = {p["isin"] for p in positions if p.get("isin")}
    names = {p["isin"]: p.get("name") for p in positions if p.get("isin")}
    shares = _shares(positions)

    stored = database.load_earnings_dates(conn, since=start)
    earnings, windows = earnings_events(stored, entries, shares)

    events = [
        *earnings,
        *ex_dividend_events(entries, held),
        *dividend_paid_events(dividends, names),
    ]
    events = [e for e in events if start <= e["date"] <= end]
    events.sort(key=lambda e: (e["date"], e["type"], e.get("name") or ""))

    # Only shares are looked up: reports_for skips trackers anyway, and for a
    # portfolio like this one that turns a dozen lookups into one.
    reports = filings_service.reports_for(conn, list(shares.values())) if shares else {}
    for event in events:
        if event["type"] != "earnings":
            continue
        report = reports.get(event["isin"])
        event["report"] = (
            {
                "kind": report["kind"],
                "url": (filings_service.filing_on_or_after(report, event["date"]) or {}).get("url")
                if report["kind"] == "filing"
                else report.get("url"),
                "label": (filings_service.filing_on_or_after(report, event["date"]) or {}).get("label")
                if report["kind"] == "filing"
                else None,
                "source": report.get("source"),
            }
            if report
            else None
        )

    estimates = [r for r in estimate_rows(outlook, windows) if start[:7] <= (r["month"] or "") <= end[:7]]

    return {
        "today": today.isoformat(),
        "range": {"from": start, "to": end},
        "events": events,
        "estimates": estimates,
        # The tab's own empty state depends on *why* it is empty. No shares at
        # all is not a failure — it is a portfolio of trackers, and the page
        # should say so rather than imply the reporting dates went missing.
        "share_count": len(shares),
        "rest_of_year_eur": outlook.get("rest_of_year_eur"),
    }
