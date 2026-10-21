"""
The Rebalancing tab's arithmetic (app.py:1118-1525).

All of it lives here rather than in the browser because the plan's bar for this
phase is "target-setting persists, charts match, and next-investment split math
matches for several test amounts" — and a split that disagrees with Streamlit's
by a euro is exactly the kind of quietly-wrong number this rebuild must not
introduce.
"""

import json
import sqlite3

from domain import database

CATEGORIES = ["Stocks", "Bonds"]
MARKET_BUCKETS = ["US", "Europe", "Emerging Markets"]
OTHER_MARKET = "Other developed / unclassified"

_TARGETS_SETTING = "rebalancing_targets"
_MARKET_TARGETS_SETTING = "broad_region_targets"

_DEFAULT_STOCK_TARGET = 90
_DEFAULT_MARKET_TARGETS = {"US": 65, "Europe": 20, "Emerging Markets": 15}

# app.py:1354-1368. Economic, not geographic: Poland and Turkey are emerging
# markets rather than Europe, which is why this is a list and not a continent
# lookup — the ETF tab's continent chart answers a different question.
_EUROPE_MARKET_COUNTRIES = {
    "United Kingdom",
    "Netherlands",
    "France",
    "Germany",
    "Switzerland",
    "Spain",
    "Italy",
    "Sweden",
    "Denmark",
    "Norway",
    "Finland",
    "Belgium",
    "Ireland",
    "Austria",
    "Portugal",
    "Luxembourg",
    "Iceland",
    "Jersey",
    "Guernsey",
    "Liechtenstein",
    "Monaco",
}
_EM_MARKET_COUNTRIES = {
    "China",
    "Taiwan",
    "India",
    "South Korea",
    "Brazil",
    "Mexico",
    "South Africa",
    "Indonesia",
    "Thailand",
    "Malaysia",
    "Philippines",
    "Vietnam",
    "Saudi Arabia",
    "United Arab Emirates",
    "Qatar",
    "Kuwait",
    "Turkey",
    "Poland",
    "Czechia",
    "Hungary",
    "Greece",
    "Russia",
    "Chile",
    "Colombia",
    "Peru",
    "Argentina",
    "Egypt",
    "Nigeria",
    "Morocco",
    "Kenya",
}

_BOND_KEYWORDS = ["bond", "obligat", "government", "treasury", "gilt", "aggregate", "corporate"]


def market_bucket(country: str) -> str:
    if country == "United States":
        return "US"
    if country in _EUROPE_MARKET_COUNTRIES:
        return "Europe"
    if country in _EM_MARKET_COUNTRIES:
        return "Emerging Markets"
    return OTHER_MARKET


def auto_guess_category(name: str) -> str:
    """app.py:1172-1178 — a keyword guess the user is expected to correct."""
    lowered = name.lower()
    return "Bonds" if any(kw in lowered for kw in _BOND_KEYWORDS) else "Stocks"


def load_targets(conn: sqlite3.Connection) -> dict:
    """Stocks/Bonds targets, always summing to 100.

    Only Stocks is stored meaningfully — Bonds is whatever is left, which is why
    app.py's slider has no counterpart for it. The back-compat branch is
    app.py:1135-1139: an earlier version split stocks into "Broad ETF" and
    "Individual / Sector ETF", and those roll up rather than being discarded.
    """
    raw = database.load_setting(conn, _TARGETS_SETTING, None)
    saved = json.loads(raw) if raw else {}

    if "Stocks" in saved:
        stocks = int(saved.get("Stocks", _DEFAULT_STOCK_TARGET))
    elif "Broad ETF" in saved or "Individual / Sector ETF" in saved:
        stocks = int(saved.get("Broad ETF", 0)) + int(saved.get("Individual / Sector ETF", 0))
    else:
        stocks = _DEFAULT_STOCK_TARGET

    stocks = max(0, min(100, stocks))
    return {"Stocks": stocks, "Bonds": 100 - stocks}


def save_targets(conn: sqlite3.Connection, stocks: int) -> dict:
    stocks = max(0, min(100, int(stocks)))
    targets = {"Stocks": stocks, "Bonds": 100 - stocks}
    database.save_setting(conn, _TARGETS_SETTING, json.dumps(targets))
    return targets


def load_market_targets(conn: sqlite3.Connection) -> dict:
    raw = database.load_setting(conn, _MARKET_TARGETS_SETTING, None)
    saved = json.loads(raw) if raw else {}
    if not saved:
        return dict(_DEFAULT_MARKET_TARGETS)
    return {
        "US": int(saved.get("US", _DEFAULT_MARKET_TARGETS["US"])),
        "Europe": int(saved.get("Europe", _DEFAULT_MARKET_TARGETS["Europe"])),
        # "EM" is an older key for the same bucket (app.py:1403).
        "Emerging Markets": int(saved.get("Emerging Markets", saved.get("EM", _DEFAULT_MARKET_TARGETS["Emerging Markets"]))),
    }


def save_market_targets(conn: sqlite3.Connection, targets: dict) -> dict:
    clean = {b: max(0, min(100, int(targets.get(b, 0)))) for b in MARKET_BUCKETS}
    database.save_setting(conn, _MARKET_TARGETS_SETTING, json.dumps(clean))
    return clean


def _normalise_category(saved: str | None) -> str | None:
    """Map a stored category onto the two this tab offers, or None to guess.

    A row saved before 5f136d3 (2026-07-16) says "Bond", which is not in
    CATEGORIES — app.py:1184 therefore falls through to its keyword guess, and a
    fund the user explicitly classified silently reappears as Stocks and gets
    overwritten on the next save. database.bond_isins already treats the two
    spellings as one; this keeps the tab that *writes* them agreeing with it.
    """
    if saved in CATEGORIES:
        return saved
    if saved in database.BOND_CATEGORIES:
        return "Bonds"
    return None


def categorise(conn: sqlite3.Connection, positions: list[dict]) -> list[dict]:
    """Each position with its saved category, or a guess when it has none."""
    saved = database.load_asset_categories(conn)
    rows = []
    for position in positions:
        category = _normalise_category(saved.get(position["isin"]))
        rows.append(
            {
                "isin": position["isin"],
                "name": position["name"],
                "value": position.get("current_value") or 0.0,
                "category": category or auto_guess_category(position["name"]),
            }
        )
    return rows


def allocation(positions: list[dict], categories: dict[str, str]) -> tuple[dict, dict, float]:
    """Value and percentage per category.

    Anything uncategorised counts as Stocks, as app.py:1230 does — a position
    with no category is far more often an equity than a bond.
    """
    by_category = {cat: 0.0 for cat in CATEGORIES}
    for position in positions:
        cat = categories.get(position["isin"], "Stocks")
        by_category[cat] = by_category.get(cat, 0.0) + (position.get("current_value") or 0.0)

    total = sum(position.get("current_value") or 0.0 for position in positions)
    if total == 0:
        return by_category, {cat: 0.0 for cat in CATEGORIES}, 0.0

    pcts = {cat: by_category.get(cat, 0.0) / total * 100 for cat in CATEGORIES}
    return by_category, pcts, total


def split_investment(
    by_bucket: dict[str, float],
    targets: dict[str, float],
    total_value: float,
    amount: float,
    buckets: list[str],
) -> dict:
    """Divide *amount* across *buckets* to land closest to *targets*.

    app.py:1292-1323 and app.py:1487-1513 run this identically for the
    Stocks/Bonds and the market split, so it is one function here.

    Each bucket's gap is what it would still need to hit its target share of the
    *post-investment* total, floored at zero — an overweight bucket asks for
    nothing rather than negative, since you cannot un-invest by depositing. The
    amount is then divided in proportion to those gaps. When every bucket is
    already at or above target the gaps are all zero, and rather than divide by
    zero it recommends nothing.
    """
    new_total = total_value + amount
    gaps = {b: max(0.0, new_total * (targets[b] / 100.0) - by_bucket.get(b, 0.0)) for b in buckets}
    total_gap = sum(gaps.values())

    recommendations = {b: (amount * gaps[b] / total_gap) if total_gap > 0 else 0.0 for b in buckets}
    after_pcts = {b: ((by_bucket.get(b, 0.0) + recommendations[b]) / new_total * 100) if new_total > 0 else 0.0 for b in buckets}
    return {
        "recommendations": recommendations,
        "after_pcts": after_pcts,
        "after_values": {b: by_bucket.get(b, 0.0) + recommendations[b] for b in buckets},
        "new_total": new_total,
        # The traffic light for the post-investment split, so the frontend can
        # colour "after this investment" the same way it colours "now" without
        # re-deriving the ±5/±15pp bands in TypeScript — two copies of a
        # threshold is how the two views come to disagree.
        "after_status": {b: deviation_status(after_pcts[b], targets[b]) for b in buckets},
    }


def market_allocation(region_totals: dict[str, float], equity_value: float) -> dict:
    """Roll each country's share of equity up into US / Europe / EM / other.

    region_totals holds fractions of equity value per country, as the ETF tab's
    breakdown produces them (app.py:1428-1429).
    """
    by_market = {b: 0.0 for b in MARKET_BUCKETS + [OTHER_MARKET]}
    for country, fraction in region_totals.items():
        by_market[market_bucket(country)] += fraction * equity_value
    return by_market


def deviation_status(current_pct: float, target_pct: float) -> str:
    """app.py:1259's traffic light: green within ±5pp, amber within ±15pp."""
    deviation = abs(current_pct - target_pct)
    if deviation <= 5:
        return "green"
    return "amber" if deviation <= 15 else "red"
