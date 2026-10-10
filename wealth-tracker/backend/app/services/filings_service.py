"""
Where the actual report lives, once a reporting date has passed.

The Calendar tab shows when a company reports. This module answers the next
question — *and now let me read it* — and it has to give two different answers,
because the world has not finished building the thing that would give one.

  * **United States.** The SEC runs EDGAR: a free, official, key-less API where
    every 10-Q and 10-K appears within minutes of being filed, with a direct
    link to the document. Nothing else in this app gets data this good. A US
    holding therefore gets real filings with real dates and a real download.

  * **Everywhere else.** There is no equivalent today. Europe's is called ESAP;
    it began *collecting* in July 2026 and opens to the public in July 2027.
    Until then the report exists only on the company's own site. So a non-US
    holding gets a link to that site, labelled as what it is — a way in, not a
    document. Yahoo carries the address, so this stays automatic; nothing here
    is a hand-maintained list of URLs that would rot.

The gap between those two is not something to paper over. `kind` is on every
row so the UI can say "10-Q, 31 July" for the one and "NN Group's site" for
the other, instead of dressing both up as a download and disappointing on half
the clicks.
"""

import datetime
import sqlite3
import os
import urllib.parse

from domain import database

#: EDGAR requires a descriptive User-Agent with a contact address and blocks
#: requests without one. This is that declaration, not a disguise. The address
#: is the installation's own (SEC_CONTACT_EMAIL), not one in the code.
_SEC_HEADERS = {
    "User-Agent": f"wealth-tracker (contact: {os.environ.get('SEC_CONTACT_EMAIL', '').strip() or 'not configured'})",
    "Accept-Encoding": "gzip, deflate",
}

_SEC_TIMEOUT = 15

#: ticker -> CIK for every SEC registrant, ~800 kB. It changes when a company
#: lists or renames, which is not a daily event; a week keeps it current
#: without re-downloading it for every calendar view.
_TICKER_MAP_TTL_SECONDS = 7 * 24 * 3600

#: A company's filing index. A day: new filings land on the reporting dates the
#: calendar already knows about, and the tab is not a news feed.
_SUBMISSIONS_TTL_SECONDS = 24 * 3600

#: The company website behind a ticker. Effectively never changes.
_PROFILE_TTL_SECONDS = 30 * 24 * 3600

#: The forms worth surfacing: quarterly, annual, and their foreign-issuer
#: equivalents. Amendments (10-K/A) come along too — a restatement is exactly
#: the version you want to be reading.
_FORMS = {"10-Q", "10-K", "20-F", "40-F", "6-K"}

_FORM_LABELS = {
    "10-Q": "Kwartaalcijfers",
    "10-K": "Jaarcijfers",
    "20-F": "Jaarcijfers",
    "40-F": "Jaarcijfers",
    "6-K": "Tussentijds bericht",
}

#: How far back to list. Four years of quarters is sixteen reports, which is
#: more history than the calendar itself shows.
_MAX_FILINGS = 24


def is_us(isin: str | None) -> bool:
    """An ISIN's first two characters are its country of issue. "US" is the
    only one EDGAR covers — a US-listed foreign company files under its own
    ISIN, and the ticker lookup below is what actually decides whether EDGAR
    has it. This is only the cheap pre-filter that avoids the lookup entirely
    for the eleven Irish-domiciled trackers in a typical portfolio."""
    return bool(isin) and isin[:2].upper() == "US"


# ---------------------------------------------------------------------------
# SEC EDGAR
# ---------------------------------------------------------------------------

def _sec_get(url: str) -> dict:
    import requests

    response = requests.get(url, headers=_SEC_HEADERS, timeout=_SEC_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _fetch_ticker_map() -> dict:
    """{TICKER: cik} for every SEC registrant."""
    raw = _sec_get("https://www.sec.gov/files/company_tickers.json")
    return {
        str(row["ticker"]).upper(): int(row["cik_str"])
        for row in raw.values()
        if row.get("ticker") and row.get("cik_str") is not None
    }


def _fetch_submissions(cik: int) -> list[dict]:
    """[{form, date, url}] — the company's recent filings, newest first.

    Only the `recent` block is read. EDGAR pages older filings into separate
    files; `recent` holds about a thousand of them, which for any company
    reaches back well past the four years this lists.
    """
    raw = _sec_get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    recent = (raw.get("filings") or {}).get("recent") or {}
    forms = recent.get("form") or []
    dates = recent.get("filingDate") or []
    accessions = recent.get("accessionNumber") or []
    documents = recent.get("primaryDocument") or []

    out = []
    for form, date, accession, document in zip(forms, dates, accessions, documents):
        if form not in _FORMS or not date or not accession or not document:
            continue
        folder = accession.replace("-", "")
        out.append({
            "form": form,
            "date": date[:10],
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{folder}/{document}",
        })
        if len(out) >= _MAX_FILINGS:
            break
    return out


def _edgar_filings(conn: sqlite3.Connection, ticker: str) -> list[dict]:
    """Filed reports for *ticker*, or [] when EDGAR does not know it.

    Every failure — no such ticker, SEC down, network gone — is [] rather than
    an exception. A missing download link degrades the row to a date on a
    calendar, which is still the thing the tab is for.
    """
    try:
        ticker_map = database.get_or_fetch(
            conn, "filings:sec:tickers", _TICKER_MAP_TTL_SECONDS, _fetch_ticker_map
        )
    except Exception:
        return []

    # "BRK.B" is "BRK-B" on Yahoo and "BRK-B" at the SEC; the Yahoo suffixes
    # that mark a non-US listing (".AS", ".DE") have no EDGAR entry at all,
    # which the lookup below simply misses — correctly.
    cik = ticker_map.get(ticker.upper().replace(".", "-"))
    if cik is None:
        return []

    try:
        return database.get_or_fetch(
            conn, f"filings:sec:{cik}", _SUBMISSIONS_TTL_SECONDS, lambda: _fetch_submissions(cik)
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Everywhere else: the company's own site
# ---------------------------------------------------------------------------

def _fetch_website(ticker: str) -> str | None:
    import yfinance as yf

    info = yf.Ticker(ticker).info or {}
    site = info.get("irWebsite") or info.get("website")
    if not site or not isinstance(site, str):
        return None
    parsed = urllib.parse.urlparse(site if "//" in site else f"https://{site}")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None   # never hand the browser a link this module cannot vouch for
    return parsed.geturl()


def _company_site(conn: sqlite3.Connection, ticker: str) -> str | None:
    try:
        return database.get_or_fetch(
            conn, f"filings:site:{ticker}", _PROFILE_TTL_SECONDS, lambda: _fetch_website(ticker)
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# What the tab asks for
# ---------------------------------------------------------------------------

def reports_for(conn: sqlite3.Connection, positions: list[dict]) -> dict[str, dict]:
    """{isin: {kind, filings|url, label}} for the shares in *positions*.

    `kind` is "filing" when there are documents to download, "site" when all
    this module can offer is the company's own address, and the ISIN is absent
    entirely when it can offer neither. Trackers are never asked about: a fund
    publishes no results, so a report link under one would be a promise about a
    document that does not exist.
    """
    out: dict[str, dict] = {}
    for position in positions:
        isin, ticker = position.get("isin"), position.get("ticker")
        if not isin or not ticker or isin in out:
            continue

        filings = _edgar_filings(conn, ticker) if is_us(isin) else []
        if filings:
            out[isin] = {
                "kind": "filing",
                "source": "SEC EDGAR",
                "filings": [
                    {**f, "label": _FORM_LABELS.get(f["form"], f["form"])}
                    for f in filings
                ],
            }
            continue

        site = _company_site(conn, ticker)
        if site:
            out[isin] = {"kind": "site", "source": None, "url": site}
    return out


def filing_on_or_after(report: dict | None, date: str) -> dict | None:
    """The filing a reporting *date* produced, if this module has it.

    A company reports on the day the calendar shows and files the same day or
    within a few days of it, so the match is "first filing on or after that
    date, within a fortnight" rather than an exact date equality that would
    miss almost every pairing.
    """
    if not report or report.get("kind") != "filing":
        return None
    try:
        day = datetime.date.fromisoformat(date[:10])
    except (ValueError, TypeError):
        return None
    horizon = (day + datetime.timedelta(days=14)).isoformat()
    candidates = [f for f in report["filings"] if date[:10] <= f["date"] <= horizon]
    return min(candidates, key=lambda f: f["date"]) if candidates else None
