#!/usr/bin/env python3
"""
check_holdings_sources.py — canary for the ETF holdings sources.

Every "exact"/"proxy" figure in the ETF analysis comes from a file or endpoint
on somebody else's website. When one of those changes shape, nothing raises:
`fetch_issuer_holdings` returns None, the caller quietly falls back to a Yahoo
top-10 estimate, and the app keeps working with worse numbers. That is exactly
how the iShares UK rebuild went unnoticed — the CSV download answered 200 with
the product page's HTML for weeks.

This script exercises every registered source against the live sites and
compares the holdings count to a recorded baseline, so a break is a
notification rather than something you eventually notice in a chart.

    python deploy/check_holdings_sources.py                  # check, exit 1 on failure
    python deploy/check_holdings_sources.py --update-baseline

It deliberately calls the low-level fetchers rather than
`issuer_holdings.fetch_issuer_holdings`: the public entry point answers from a
7-day SQLite cache, which would let the canary pass for a week after the source
had already died.

Run weekly from cron via deploy/holdings-canary.sh.
"""

import argparse
import json
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from domain import database          # noqa: E402
from domain.portfolio import issuer_holdings   # noqa: E402

BASELINE_PATH = pathlib.Path(__file__).parent / "holdings_baseline.json"

# A source that returns *fewer* holdings than this fraction of its baseline is
# treated as broken too. A partial parse is the failure mode that hides best:
# a basket of 40 names where 1279 are expected still renders a plausible chart.
# Real index turnover is a couple of percent per rebalance, nowhere near this.
MIN_FRACTION = 0.6

# A source with no baseline entry (a fund registered after the last refresh)
# can only be checked for "returned anything at all".
UNBASELINED_FLOOR = 1


def _sources() -> list[tuple[str, str, str, callable]]:
    """
    (key, description, remote, fetcher) for every registered holdings source.

    Built from issuer_holdings' own registries, so a fund added there is
    covered here without touching this file.

    `remote` identifies the actual download. Several sources share one: the
    registered iShares funds double as the reference basket for the index
    proxies (a Vanguard S&P 500 borrows the very file IUSA already publishes),
    so six of these point at a URL another one also uses. Fetching each once
    per run keeps the traffic honest -- see _run().
    """
    out: list[tuple[str, str, str, callable]] = []

    for isin, path in issuer_holdings.ISHARES_PRODUCTS.items():
        out.append((f"ishares:{isin}", f"iShares {isin}", f"ishares:{path}",
                    lambda p=path: issuer_holdings._fetch_ishares_path(p)))

    for isin in issuer_holdings.SPDR_PRODUCTS:
        out.append((f"spdr:{isin}", f"SPDR {isin}", f"spdr:{isin}",
                    lambda i=isin: issuer_holdings._fetch_spdr(i)))

    for isin in issuer_holdings.VANGUARD_PRODUCTS:
        out.append((f"vanguard:{isin}", f"Vanguard {isin}",
                    f"vanguard:{issuer_holdings.VANGUARD_PRODUCTS[isin]}",
                    lambda i=isin: issuer_holdings._fetch_vanguard(i)))

    for isin, cfg in issuer_holdings.PROXY_FUNDS.items():
        out.append((f"proxy:{isin}", f"Hand-registered proxy {isin}",
                    f"ishares:{cfg['path']}",
                    lambda i=isin: issuer_holdings._fetch_proxy(i)))

    for key, src in issuer_holdings._INDEX_PROXY_SOURCES.items():
        # The format is part of the identity: the same path fetched as
        # SpreadsheetML is a different download than fetched as JSON.
        if src.get("fmt") == "de_xls":
            remote = f"ishares_de:{src['path']}"
            fetch = lambda p=src["path"]: issuer_holdings._fetch_ishares_de_path(p)
        else:
            remote = f"ishares:{src['path']}"
            fetch = lambda p=src["path"]: issuer_holdings._fetch_ishares_path(p)
        out.append((f"index:{key}", f"Index proxy {key}", remote, fetch))

    out.append(("vanguard:catalog", "Vanguard product catalogue",
                "vanguard:catalog", _check_vanguard_catalog))
    return out


def _memory_conn() -> sqlite3.Connection:
    """A throwaway DB so the catalogue check can't read a cached answer."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    database.init_db(conn)
    return conn


def _check_vanguard_catalog() -> list | None:
    """
    The catalogue behind Vanguard auto-discovery — how any unregistered
    Vanguard fund resolves to exact issuer holdings.

    Checked one level deeper than "the endpoint answers": a known fund name
    must still resolve to a portId, so a renamed field or a changed name
    format shows up as a failure and not as a full-looking catalogue that
    nothing matches against.
    """
    conn = _memory_conn()
    try:
        catalog = issuer_holdings._vanguard_catalog(conn)
        if not catalog:
            return None
        match = issuer_holdings._vanguard_match(
            conn, "VANGUARD FTSE ALL-WORLD UCITS ETF USD DIS", allow_subseq=True)
        if not match:
            print("      (catalogue downloaded but FTSE All-World no longer matches)")
            return None
        return catalog
    finally:
        conn.close()


def _load_baseline() -> dict[str, int]:
    if not BASELINE_PATH.exists():
        return {}
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["counts"]


def _run() -> list[tuple[str, str, int, int]]:
    """
    Fetch every source. Returns (key, description, count, expected).

    Downloads are memoised per `remote`, so a file two sources share is
    fetched once. Nothing is cached beyond this run -- the point of the canary
    is to touch the live sites every time.
    """
    baseline = _load_baseline()
    fetched: dict[str, int] = {}
    results = []
    for key, description, remote, fetch in _sources():
        if remote not in fetched:
            try:
                got = fetch()
            except Exception as e:                  # a canary must never crash
                print(f"  !! {description}: {type(e).__name__}: {e}")
                got = None
            fetched[remote] = len(got or [])
        results.append((key, description, fetched[remote], baseline.get(key, 0)))
    return results


def _failures(results) -> list[str]:
    out = []
    for key, description, count, expected in results:
        floor = round(expected * MIN_FRACTION) if expected else UNBASELINED_FLOOR
        if count < floor:
            out.append(f"{description}: {count} holdings (expected ≥{floor})")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-baseline", action="store_true",
                        help="record the current counts as the new baseline")
    args = parser.parse_args()

    results = _run()

    for key, description, count, expected in sorted(results):
        floor = round(expected * MIN_FRACTION) if expected else UNBASELINED_FLOOR
        mark = "ok " if count >= floor else "BAD"
        print(f"  {mark} {count:>5} (baseline {expected:>5})  {description}")

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps({
            "_comment": "Holdings counts per source, recorded by "
                        "check_holdings_sources.py --update-baseline. Refresh "
                        "after registering a new fund.",
            "counts": {key: count for key, _, count, _ in sorted(results)},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline written to {BASELINE_PATH}")
        return 0

    failures = _failures(results)
    if not failures:
        print(f"\nAll {len(results)} sources deliver complete holdings.")
        return 0

    # Printed on the failure path only — deploy/holdings-canary.sh forwards
    # stdout into the push notification, so keep it short and readable.
    print(f"\n{len(failures)} of {len(results)} holdings sources broken:")
    for line in failures:
        print(f"  - {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
