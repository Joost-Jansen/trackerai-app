"""
issuer_holdings.py — Complete ETF holdings straight from the fund issuers.

Unlike Yahoo Finance (top-10 holdings only), issuers publish the full
portfolio of every fund daily.  This module downloads and parses those
files, returning holdings in a normalised shape:

    [{"symbol": str, "name": str, "weight": float,        (weight = fraction)
      "sector": str | None, "country": str | None}, ...]

sector/country are the raw labels from the source file; etf_holdings.py
normalises naming variants at aggregation time.

Supported issuers
-----------------
iShares  : every product page on ishares.com hosts a complete holdings CSV
           (no account or API key needed).  Funds are registered in
           ISHARES_PRODUCTS below — add new funds there.
SPDR     : ssga.com publishes a daily holdings XLSX per fund; register the
           file slug in SPDR_PRODUCTS.
Vanguard : the UK investor site exposes a public GraphQL endpoint with the
           full month-end holdings per fund; register the numeric portId
           in VANGUARD_PRODUCTS.

Automatic same-index proxy
--------------------------
Funds that aren't registered above are still covered when their *name*
identifies a major index (S&P 500, MSCI World/USA/Japan/China/India/UK,
EURO STOXX 50, STOXX Europe 600, MSCI Europe, MSCI EM, MSCI EM IMI,
MSCI ACWI, Nasdaq-100, AEX): they borrow the holdings of a full-replication
iShares ETF on the same index, or — for FTSE/S&P indices — the matching
Vanguard ETF resolved automatically from its product catalogue (see
_INDEX_RULES / _INDEX_RULES_SPECIFIC / _INDEX_PROXY_SOURCES / _vanguard_match).
This makes the ETF
analysis work out of the box for any user's funds regardless of issuer — e.g.
a Vanguard or Amundi S&P 500 ETF reuses the iShares S&P 500 basket.  Results
are labelled 'proxy' (near-exact), never 'exact'.  Factor/ESG/ex-/small-cap
variants are deliberately not matched and fall back to the approximate path.

Results are cached in SQLite (etf_api_cache table, 7-day TTL) so the
issuer sites are hit at most once a week per fund.
"""

import csv
import io
import json
import re
import sqlite3
import warnings

import requests

from domain import database

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# iShares
# ---------------------------------------------------------------------------
# ISIN → product page path on the iShares UK retail site.  The holdings CSV
# lives at  <path>/1506575576011.ajax?fileType=csv&...  for every fund.
# To add a fund: find its page on ishares.com and copy the path here.

_ISHARES_BASE = "https://www.ishares.com"
_ISHARES_CSV_SUFFIX = "/1506575576011.ajax?fileType=csv&fileName=holdings&dataType=fund&switchLocale=y&siteEntryPassthrough=true"

# The UK retail site was rebuilt (Astro) in 2026 and the CSV suffix above no
# longer downloads anything there: it answers 200 with the product page HTML,
# which parses to zero holdings.  Its holdings table is now fed by BlackRock's
# public product-data API, keyed on the numeric portfolioId that is already
# part of every product page path (/products/<portfolioId>/<slug>).  Same
# fields as the old CSV, delivered as parallel arrays.  The CSV suffix is kept
# as a fallback — the non-UK sites (e.g. /ch/) still serve files that way.
_ISHARES_API_URL = (
    "https://www.ishares.com/varnish-api/uk-retail01-product-data"
    "/product-data/api/v2/get-product-data"
    "?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=ishares-uk"
    "&locale=en_GB&userType=individual&component=holdings&portfolioId={pid}"
)

_PORTFOLIO_ID_RE = re.compile(r"/products/(\d+)")

# German-domiciled iShares funds (the "(DE)" range) aren't on the UK retail
# site; they're served from the Swiss/German sites and publish holdings as
# SpreadsheetML (Excel-2003 XML) rather than CSV.  The download module id is
# constant across that site, so this suffix works for any registered DE path.
_ISHARES_DE_SUFFIX = "/1535604580403.ajax?fileType=xls&fileName=holdings&dataType=fund&switchLocale=y&siteEntryPassthrough=true"

ISHARES_PRODUCTS: dict[str, str] = {
    # iShares Core MSCI World UCITS ETF USD (Acc) — IWDA
    "IE00B4L5Y983": "/uk/individual/en/products/251882/ishares-msci-world-ucits-etf-acc-fund",
    # iShares Core S&P 500 UCITS ETF USD (Dist) — IUSA
    "IE0031442068": "/uk/individual/en/products/251900/ishares-sp-500-ucits-etf-inc-fund",
    # iShares Core EURO STOXX 50 UCITS ETF EUR (Dist) — EUE/EUEA
    "IE0008471009": "/uk/individual/en/products/251781/ishares-euro-stoxx-50-ucits-etf-inc-fund",
    # iShares Core MSCI Europe UCITS ETF EUR (Acc) — SMEA/EUNK
    "IE00B4K48X80": "/uk/individual/en/products/251861/ishares-msci-europe-ucits-etf-acc-fund",
    # iShares Global Clean Energy Transition UCITS ETF USD (Dist) — INRG/IQQH
    "IE00B1XNHC34": "/uk/individual/en/products/251911/ishares-global-clean-energy-ucits-etf",
    # iShares MSCI EM UCITS ETF USD (Acc) — SEMA/EUNM
    "IE00B4L5YC18": "/uk/individual/en/products/251858/ishares-msci-emerging-markets-ucits-etf-acc-fund",
    # iShares Dow Jones Global Sustainability Screened UCITS ETF USD (Acc) — IGSG
    "IE00B57X3V84": "/uk/individual/en/products/251768/ishares-dow-jones-global-sustainability-screened-ucits-etf",
}


def _parse_number(raw: str) -> float | None:
    """'1,234.56' → 1234.56 — iShares CSVs use thousands separators."""
    try:
        return float(raw.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _parse_ishares_csv(text: str) -> list[dict]:
    """
    Parses an iShares holdings CSV into [{symbol, name, weight}].

    The file starts with a few preamble lines ("Fund Holdings as of", blank),
    then a header row.  Column layout varies per fund (some have an extra
    "Type" column), so columns are located by name.  Cash and derivative
    rows are dropped — only Asset Class "Equity" counts as stock exposure.
    """
    rows = list(csv.reader(io.StringIO(text)))

    header_idx = None
    for i, row in enumerate(rows):
        if "Ticker" in row and any(c.startswith("Weight") for c in row):
            header_idx = i
            break
    if header_idx is None:
        return []

    header = rows[header_idx]
    col = {name: j for j, name in enumerate(header)}
    ticker_i = col.get("Ticker")
    name_i = col.get("Name")
    weight_i = next((j for j, c in enumerate(header) if c.startswith("Weight")), None)
    asset_i = col.get("Asset Class")
    sector_i = col.get("Sector")
    country_i = col.get("Location")
    if ticker_i is None or name_i is None or weight_i is None:
        return []

    def _cell(row, i):
        if i is None or len(row) <= i:
            return None
        v = row[i].strip()
        return v if v and v != "-" else None

    holdings = []
    for row in rows[header_idx + 1 :]:
        if len(row) <= weight_i:
            continue
        if asset_i is not None and len(row) > asset_i:
            if row[asset_i].strip().lower() != "equity":
                continue
        weight = _parse_number(row[weight_i])
        if weight is None or weight <= 0:
            continue
        symbol = row[ticker_i].strip()
        name = row[name_i].strip() or symbol
        if not symbol:
            symbol = name
        if not symbol:
            continue
        holdings.append(
            {
                "symbol": symbol,
                "name": name,
                "weight": weight / 100.0,
                "sector": _cell(row, sector_i),
                "country": _cell(row, country_i),
            }
        )
    return holdings


def _parse_ishares_api(payload: dict) -> list[dict]:
    """
    Parses a get-product-data holdings payload into [{symbol, name, weight}].

    The response holds one array per column under
    componentsByNameMap.holdings.containersByNameMap.all.dataPointsByNameMap,
    all aligned by index.  Column names differ from the CSV's headers
    (issueName / holdingPercent / sectorName / countryOfRisk), the row
    semantics do not: only Asset Class "Equity" counts as stock exposure, cash,
    FX and futures rows are dropped.
    """
    try:
        cols = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"]
    except (KeyError, TypeError):
        return []

    def column(key: str) -> list:
        value = (cols.get(key) or {}).get("value")
        return value if isinstance(value, list) else []

    names = column("issueName")
    weights = column("holdingPercent")
    if not names or not weights:
        return []
    tickers = column("ticker")
    assets = column("assetClass")
    sectors = column("sectorName")
    countries = column("countryOfRisk")

    def _cell(arr, i):
        if i >= len(arr) or arr[i] is None:
            return None
        v = str(arr[i]).strip()
        return v if v and v != "-" else None

    holdings = []
    for i in range(min(len(names), len(weights))):
        if assets and (_cell(assets, i) or "").lower() != "equity":
            continue
        weight = weights[i]
        if isinstance(weight, str):
            weight = _parse_number(weight)
        if not isinstance(weight, (int, float)) or weight <= 0:
            continue
        name = _cell(names, i)
        symbol = _cell(tickers, i) or name
        if not name:
            continue
        holdings.append(
            {
                "symbol": symbol or name,
                "name": name,
                "weight": weight / 100.0,
                "sector": _cell(sectors, i),
                "country": _cell(countries, i),
            }
        )
    return holdings


def _fetch_ishares_api(portfolio_id: str) -> list[dict] | None:
    """Fetch a fund's complete holdings from BlackRock's product-data API."""
    try:
        r = requests.get(_ISHARES_API_URL.format(pid=portfolio_id), headers=_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"iShares API: HTTP {r.status_code} for portfolioId {portfolio_id}")
            return None
        payload = r.json()
    except Exception as e:
        print(f"iShares API: request failed for portfolioId {portfolio_id}: {e}")
        return None
    return _parse_ishares_api(payload) or None


def _fetch_ishares_path(path: str) -> list[dict] | None:
    """
    Complete holdings behind an iShares product page path.

    Preferred route is the product-data API (the rebuilt UK site's own source);
    the legacy CSV download is the fallback for sites still serving it.
    """
    m = _PORTFOLIO_ID_RE.search(path or "")
    if m:
        holdings = _fetch_ishares_api(m.group(1))
        if holdings:
            return holdings
    return _fetch_ishares_csv_path(path)


def _fetch_ishares_csv_path(path: str) -> list[dict] | None:
    """Download and parse the holdings CSV behind an iShares product page path."""
    url = _ISHARES_BASE + path + _ISHARES_CSV_SUFFIX
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"iShares: HTTP {r.status_code} for {path}")
            return None
        text = r.content.decode("utf-8-sig", errors="replace")
    except Exception as e:
        print(f"iShares: request failed for {path}: {e}")
        return None

    holdings = _parse_ishares_csv(text)
    return holdings or None


def _fetch_ishares(isin: str) -> list[dict] | None:
    path = ISHARES_PRODUCTS.get(isin)
    if not path:
        return None
    return _fetch_ishares_path(path)


def _parse_ishares_xml(content: bytes) -> list[dict]:
    """
    Parse an iShares SpreadsheetML (Excel-2003 XML) holdings export — the
    format the German "(DE)" funds use.  The Holdings worksheet has the same
    columns as the CSV (Name, Sector, Asset Class, Weight (%), Location), so
    the per-row handling mirrors _parse_ishares_csv.
    """
    import xml.etree.ElementTree as ET

    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import fromstring

    ns = "{urn:schemas-microsoft-com:office:spreadsheet}"
    text = content.decode("utf-8-sig", errors="replace").lstrip("﻿").lstrip()
    try:
        # defusedxml: a downloaded file must not be able to expand entities
        # (billion laughs) or reach out for external ones.
        root = fromstring(text)
    except (ET.ParseError, DefusedXmlException):
        return []

    def _worksheet_rows(ws):
        table = ws.find(f"{ns}Table")
        if table is None:
            return []
        out = []
        for r in table.findall(f"{ns}Row"):
            cells, col = [], 0
            for cell in r.findall(f"{ns}Cell"):
                idx = cell.get(f"{ns}Index")  # sparse cells jump columns
                if idx:
                    col = int(idx) - 1
                while len(cells) < col:
                    cells.append(None)
                data = cell.find(f"{ns}Data")
                cells.append(data.text if data is not None else None)
                col += 1
            out.append(cells)
        return out

    rows = []
    for ws in root.findall(f"{ns}Worksheet"):
        ws_rows = _worksheet_rows(ws)
        header_idx = next(
            (i for i, row in enumerate(ws_rows[:40]) if any(c == "Name" for c in row) and any((c or "").startswith("Weight") for c in row)),
            None,
        )
        if header_idx is not None:
            rows = ws_rows[header_idx:]
            break
    if not rows:
        return []

    header = [c or "" for c in rows[0]]
    col = {name: j for j, name in enumerate(header)}
    ticker_i = col.get("Ticker", col.get("Issuer Ticker"))
    name_i = col.get("Name")
    weight_i = next((j for j, c in enumerate(header) if c.startswith("Weight")), None)
    asset_i = col.get("Asset Class")
    sector_i = col.get("Sector")
    country_i = col.get("Location")
    if name_i is None or weight_i is None:
        return []

    def _cell(row, i):
        if i is None or i >= len(row):
            return None
        v = (row[i] or "").strip()
        return v if v and v != "-" else None

    holdings = []
    for row in rows[1:]:
        if weight_i >= len(row):
            continue
        if asset_i is not None and asset_i < len(row):
            if (row[asset_i] or "").strip().lower() != "equity":
                continue
        weight = _parse_number(row[weight_i]) if row[weight_i] else None
        if weight is None or weight <= 0:
            continue
        name = _cell(row, name_i)
        symbol = _cell(row, ticker_i) or name
        if not name:
            continue
        holdings.append(
            {
                "symbol": symbol or name,
                "name": name,
                "weight": weight / 100.0,
                "sector": _cell(row, sector_i),
                "country": _cell(row, country_i),
            }
        )
    return holdings


def _fetch_ishares_de_path(path: str) -> list[dict] | None:
    """Download and parse the SpreadsheetML holdings of a German iShares fund."""
    url = _ISHARES_BASE + path + _ISHARES_DE_SUFFIX
    try:
        r = requests.get(url, headers=_HEADERS, timeout=30)
        if r.status_code != 200:
            print(f"iShares DE: HTTP {r.status_code} for {path}")
            return None
    except Exception as e:
        print(f"iShares DE: request failed for {path}: {e}")
        return None
    return _parse_ishares_xml(r.content) or None


# ---------------------------------------------------------------------------
# SPDR (State Street)
# ---------------------------------------------------------------------------
# ISIN → file slug on ssga.com.  The daily holdings file lives at
# https://www.ssga.com/library-content/products/fund-data/etfs/emea/
#     holdings-daily-emea-en-<slug>.xlsx
# The slug is the fund's ticker + listing suffix, lowercase (e.g. wtch-na).

_SPDR_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/emea/holdings-daily-emea-en-{slug}.xlsx"

SPDR_PRODUCTS: dict[str, str] = {
    # SPDR MSCI World Technology UCITS ETF — WTCH (Amsterdam)
    "IE00BYTRRD19": "wtch-na",
}


def _parse_spdr_xlsx(content: bytes) -> list[dict]:
    """
    Parses an SSGA holdings XLSX into [{symbol, name, weight}].

    Layout: a few metadata rows, then a header row with
    'Security Name' and 'Percent of Fund', then one row per holding and a
    legal disclaimer at the bottom.  There is no ticker column — symbol is
    left empty and aggregation falls back to the security name.
    """
    import openpyxl

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # "no default style" noise from ssga files
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    header_idx = None
    for i, row in enumerate(rows):
        cells = [str(c) for c in row if c is not None]
        if "Security Name" in cells and any("Percent of Fund" in c for c in cells):
            header_idx = i
            break
    if header_idx is None:
        return []

    header = [str(c) if c is not None else "" for c in rows[header_idx]]
    name_i = header.index("Security Name")
    weight_i = next(j for j, c in enumerate(header) if "Percent of Fund" in c)
    sector_i = next((j for j, c in enumerate(header) if "Sector Classification" in c), None)
    country_i = next((j for j, c in enumerate(header) if "Trade Country Name" in c), None)

    def _cell(row, i):
        if i is None or len(row) <= i or row[i] is None:
            return None
        v = str(row[i]).strip()
        return v if v and v.lower() not in ("-", "unassigned") else None

    holdings = []
    for row in rows[header_idx + 1 :]:
        if row is None or len(row) <= max(name_i, weight_i):
            continue
        name = row[name_i]
        weight = row[weight_i]
        if name is None or weight is None:
            continue
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        holdings.append(
            {
                "symbol": "",
                "name": str(name).strip(),
                "weight": weight / 100.0,
                "sector": _cell(row, sector_i),
                "country": _cell(row, country_i),
            }
        )
    return holdings


def _fetch_spdr(isin: str) -> list[dict] | None:
    slug = SPDR_PRODUCTS.get(isin)
    if not slug:
        return None
    try:
        r = requests.get(_SPDR_URL.format(slug=slug), headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"SPDR: HTTP {r.status_code} for {isin}")
            return None
    except Exception as e:
        print(f"SPDR: request failed for {isin}: {e}")
        return None

    try:
        return _parse_spdr_xlsx(r.content) or None
    except Exception as e:
        print(f"SPDR: parse failed for {isin}: {e}")
        return None


# ---------------------------------------------------------------------------
# Vanguard
# ---------------------------------------------------------------------------
# The Vanguard UK investor site serves full fund holdings over a public
# GraphQL endpoint (the same one its own product pages use).  Holdings are
# month-end snapshots, paginated at 1500 rows per call.  Funds are keyed by
# Vanguard's numeric portId — find it via
# https://www.vanguardinvestor.co.uk/api/productList .

_VANGUARD_GRAPHQL = "https://www.vanguardinvestor.co.uk/gpx/graphql"

VANGUARD_PRODUCTS: dict[str, str] = {
    # Vanguard S&P 500 UCITS ETF USD (Dist) — VUSA
    "IE00B3XXRP09": "9503",
}

_VANGUARD_QUERY = """query FundsHoldingsQuery($portIds: [String!], $securityTypes: [String!], $lastItemKey: String) {
  borHoldings(portIds: $portIds) {
    holdings(limit: 1500, securityTypes: $securityTypes, lastItemKey: $lastItemKey) {
      items { issuerName securityLongDescription marketValuePercentage ticker securityType gicsSectorDescription bloombergIsoCountry }
      totalHoldings
      lastItemKey
    }
  }
}"""

# Vanguard reports countries as ISO 3166 alpha-2 codes; the other issuers
# use names.  Unknown codes pass through unchanged.
_ISO_COUNTRY = {
    "US": "United States",
    "GB": "United Kingdom",
    "NL": "Netherlands",
    "IE": "Ireland",
    "CH": "Switzerland",
    "DE": "Germany",
    "FR": "France",
    "BE": "Belgium",
    "ES": "Spain",
    "IT": "Italy",
    "PT": "Portugal",
    "AT": "Austria",
    "FI": "Finland",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
    "LU": "Luxembourg",
    "JP": "Japan",
    "CN": "China",
    "HK": "Hong Kong",
    "TW": "Taiwan",
    "KR": "South Korea",
    "IN": "India",
    "SG": "Singapore",
    "AU": "Australia",
    "NZ": "New Zealand",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "ZA": "South Africa",
    "IL": "Israel",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "BM": "Bermuda",
    "KY": "Cayman Islands",
    "JE": "Jersey",
    "GG": "Guernsey",
    "CW": "Curacao",
    "LI": "Liechtenstein",
    "MC": "Monaco",
}


def _fetch_vanguard_portid(port_id: str) -> list[dict] | None:
    """Fetch full holdings for a Vanguard fund by its numeric portId."""
    holdings: list[dict] = []
    last_key = None
    for _ in range(10):  # pagination safety cap (1500 rows per page)
        try:
            r = requests.post(
                _VANGUARD_GRAPHQL,
                json={
                    "operationName": "FundsHoldingsQuery",
                    "variables": {"portIds": [port_id], "lastItemKey": last_key},
                    "query": _VANGUARD_QUERY,
                },
                headers=_HEADERS,
                timeout=20,
            )
            if r.status_code != 200:
                print(f"Vanguard: HTTP {r.status_code} for portId {port_id}")
                return None
            block = r.json()["data"]["borHoldings"][0]["holdings"]
        except Exception as e:
            print(f"Vanguard: request failed for portId {port_id}: {e}")
            return None

        for it in block.get("items") or []:
            # EQ.STOCK / EQ.REIT / EQ.RIGHT are equity exposure; the rest is
            # cash, futures and swaps (CRNY, DE.IND, CT.PORTSWAP).
            if not (it.get("securityType") or "").startswith("EQ."):
                continue
            weight = it.get("marketValuePercentage")
            if weight is None or weight <= 0:
                continue
            name = (it.get("issuerName") or it.get("securityLongDescription") or "").strip()
            symbol = (it.get("ticker") or "").strip()
            if not name and not symbol:
                continue
            iso = (it.get("bloombergIsoCountry") or "").strip().upper()
            holdings.append(
                {
                    "symbol": symbol,
                    "name": name or symbol,
                    "weight": weight / 100.0,
                    "sector": (it.get("gicsSectorDescription") or "").strip() or None,
                    "country": _ISO_COUNTRY.get(iso, iso) if iso else None,
                }
            )

        last_key = block.get("lastItemKey")
        if not last_key:
            break

    return holdings or None


def _fetch_vanguard(isin: str) -> list[dict] | None:
    port_id = VANGUARD_PRODUCTS.get(isin)
    if not port_id:
        return None
    return _fetch_vanguard_portid(port_id)


# --- Vanguard auto-discovery: resolve any Vanguard fund to its portId --------
# The UK investor site publishes a product list (ISIN-agnostic) that maps every
# fund name to its portId.  Holdings are identical across share classes of the
# same fund, so a EU-listed ISIN we've never seen is matched to its UK twin by
# normalised fund name — giving exact issuer holdings for any Vanguard ETF
# without registering it in VANGUARD_PRODUCTS by hand.

_VANGUARD_PRODUCTLIST = "https://www.vanguardinvestor.co.uk/api/productList"

# Words stripped when reducing a fund name to a comparable core, so e.g.
# "VANGUARD FTSE ALL-WORLD UCITS - (USD) ACCUMULATING ETF" and the catalogue's
# "FTSE All-World UCITS ETF" both collapse to "ftse all world".  "ex" is kept
# on purpose — it distinguishes "Developed Europe" from "Developed Europe ex UK".
_FUND_NAME_NOISE = {
    "vanguard",
    "ucits",
    "etf",
    "fund",
    "shares",
    "share",
    "class",
    "plc",
}

# Share-class / currency fragments.  A token made up only of these (e.g. the
# concatenated "usdacc" DeGiro stores) carries no fund identity and is dropped.
# Longest form first: the bits are stripped in order, so "dist" must be tried
# before "dis" or "distributing" would leave a stray "t" behind.
_CLASS_BITS = (
    "accumulating",
    "distributing",
    "income",
    "usd",
    "eur",
    "gbp",
    "chf",
    "acc",
    "dist",
    "dis",
    "inc",
)


def _is_shareclass_token(t: str) -> bool:
    for b in _CLASS_BITS:
        t = t.replace(b, "")
    return t == ""


def _norm_fund_name(name: str) -> str:
    low = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    return " ".join(t for t in low.split() if t not in _FUND_NAME_NOISE and not _is_shareclass_token(t))


def _is_subsequence(q: str, s: str) -> bool:
    """True when every char of q appears in s in order (q ⊆ s as a subsequence)."""
    it = iter(s)
    return all(ch in it for ch in q)


def _vanguard_catalog(conn: sqlite3.Connection) -> list[dict] | None:
    """Vanguard UK product list (cached 7 days in SQLite)."""
    cache_key = "vanguard:productlist:v1"
    cached = database.load_etf_api_cache(conn, cache_key)
    if cached is not None:
        try:
            data = json.loads(cached)
            if data:
                return data
        except json.JSONDecodeError:
            pass
    try:
        r = requests.get(_VANGUARD_PRODUCTLIST, headers=_HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"Vanguard productList: HTTP {r.status_code}")
            return None
        data = r.json()
    except Exception as e:
        print(f"Vanguard productList: request failed: {e}")
        return None
    if isinstance(data, list) and data:
        database.save_etf_api_cache(conn, cache_key, json.dumps(data))
        return data
    return None


# Issuer/brand and product-line words dropped (on top of _norm_fund_name) so
# only the *index identity* remains — this lets a non-Vanguard fund be matched
# to the Vanguard ETF on the same index, e.g. "Invesco FTSE All-World" and the
# catalogue's "FTSE All-World UCITS ETF" both reduce to "ftse all world".
_INDEX_NAME_DROP = {
    "ishares",
    "invesco",
    "amundi",
    "xtrackers",
    "lyxor",
    "hsbc",
    "spdr",
    "ssga",
    "vaneck",
    "wisdomtree",
    "franklin",
    "fidelity",
    "jpmorgan",
    "jpm",
    "ubs",
    "deka",
    "lgim",
    "blackrock",
    "source",
    "core",
    "index",
    # DeGiro's own abbreviations for the same issuers — the names arriving here
    # come out of its export, so these are the spellings half the portfolios
    # actually use. Left out, "VNGU FTSE ALL-WORLD" reduced to "vngu ftse all
    # world", matched nothing in Vanguard's catalogue, and the fund got no
    # holdings at all; spelled out in full the very same fund resolves to exact
    # issuer holdings. Same set as portfolio._NAME_EXPANSIONS, which exists
    # because DeGiro really does write them this way.
    "vngu",
    "vgrd",
    "ishs",
    "ishrs",
    "stst",
}

#: Issuer spellings that mean Vanguard, for the test that decides whether a fund
#: is Vanguard's own (exact holdings) or merely tracks the same index (proxy).
_VANGUARD_SPELLINGS = ("vanguard", "vngu", "vgrd")


def _norm_index_name(name: str) -> str:
    return " ".join(t for t in _norm_fund_name(name).split() if t not in _INDEX_NAME_DROP)


def _vanguard_match(conn: sqlite3.Connection, name: str | None, allow_subseq: bool) -> tuple[str, str] | None:
    """
    Find the Vanguard equity ETF tracking the same index as `name`, via the
    product list.  Returns (portId, vanguard_fund_name) or None.

    Matching is on the index identity (issuer/brand stripped), so it serves
    two roles: resolving Vanguard's own funds (exact issuer holdings) and
    standing in for another issuer's fund on the *same* index (proxy).  Match
    is exact-normalised; `allow_subseq` additionally accepts a unique
    subsequence — used only for Vanguard's own funds, whose names some brokers
    (DeGiro) store run-together, e.g. "FTSEDVLPASIAPACEXJPN".  Share classes of
    one fund collapse to a single entry (identical holdings).
    """
    if not name:
        return None
    catalog = _vanguard_catalog(conn)
    if not catalog:
        return None
    want = _norm_index_name(name)
    if not want:
        return None

    by_name: dict[str, tuple[str, str]] = {}
    for it in catalog:
        if (it.get("productType") or "").lower() != "etf":
            continue
        if (it.get("assetClass") or "").lower() != "equity":
            continue
        pid = it.get("portId")
        if pid:
            by_name.setdefault(_norm_index_name(it.get("name") or ""), (pid, it.get("name") or ""))

    if want in by_name:
        return by_name[want]

    if allow_subseq:
        qs = want.replace(" ", "")
        if len(qs) >= 12:
            hits = [v for nm, v in by_name.items() if _is_subsequence(qs, nm.replace(" ", ""))]
            if len(hits) == 1:
                return hits[0]
    return None


# ---------------------------------------------------------------------------
# Index proxies
# ---------------------------------------------------------------------------
# Funds whose issuer publishes no machine-readable holdings file, stood in
# for by another *full-replication* fund tracking the same index.  Weights
# differ from the real fund only by cash buffer and rebalance timing
# (tenths of a percentage point) — near-exact, but labelled as a proxy in
# the UI, never as issuer data.

PROXY_FUNDS: dict[str, dict] = {
    # VanEck AEX UCITS ETF (TDT): VanEck's holdings are rendered client-side
    # with no discoverable API.  TDT fully replicates the AEX index, as does
    # the iShares AEX UCITS ETF (IAEX) — use IAEX's daily holdings file.
    "NL0009272749": {
        "path": "/uk/individual/en/products/251712/ishares-aex-ucits-etf",
        "label": "Index proxy (iShares AEX file)",
    },
}


def _fetch_proxy(isin: str) -> list[dict] | None:
    cfg = PROXY_FUNDS.get(isin)
    if not cfg:
        return None
    return _fetch_ishares_path(cfg["path"])


# ---------------------------------------------------------------------------
# Automatic same-index proxy (works for any provider)
# ---------------------------------------------------------------------------
# PROXY_FUNDS above is keyed by ISIN — every fund must be registered by hand.
# This layer instead recognises the *index* a fund tracks from its name, so a
# fund we have no issuer file for (e.g. a Vanguard or Amundi S&P 500 ETF)
# automatically borrows the holdings of a full-replication iShares ETF on the
# very same index.  The baskets are identical bar cash buffer and rebalance
# timing, so the result is near-exact — always labelled 'proxy', never 'exact'.
#
# Each index points at a verified iShares product page (the same CSV mechanism
# used everywhere else).  To support another index: add a reference fund here
# and a matching rule in _INDEX_RULES.

_INDEX_PROXY_SOURCES: dict[str, dict] = {
    "msci_world": {
        "path": "/uk/individual/en/products/251882/ishares-msci-world-ucits-etf-acc-fund",
        "label": "Index proxy (iShares MSCI World)",
    },
    "sp500": {"path": "/uk/individual/en/products/251900/ishares-sp-500-ucits-etf-inc-fund", "label": "Index proxy (iShares S&P 500)"},
    "euro_stoxx_50": {
        "path": "/uk/individual/en/products/251781/ishares-euro-stoxx-50-ucits-etf-inc-fund",
        "label": "Index proxy (iShares EURO STOXX 50)",
    },
    "msci_europe": {
        "path": "/uk/individual/en/products/251861/ishares-msci-europe-ucits-etf-acc-fund",
        "label": "Index proxy (iShares MSCI Europe)",
    },
    "msci_em": {
        "path": "/uk/individual/en/products/251858/ishares-msci-emerging-markets-ucits-etf-acc-fund",
        "label": "Index proxy (iShares MSCI EM)",
    },
    "msci_em_imi": {
        "path": "/uk/individual/en/products/264659/ishares-msci-emerging-markets-imi-ucits-etf",
        "label": "Index proxy (iShares MSCI EM IMI)",
    },
    "msci_acwi": {"path": "/uk/individual/en/products/251850/ishares-msci-acwi-ucits-etf", "label": "Index proxy (iShares MSCI ACWI)"},
    "nasdaq_100": {"path": "/uk/individual/en/products/253741/ishares-nasdaq-100-ucits-etf", "label": "Index proxy (iShares Nasdaq 100)"},
    "aex": {"path": "/uk/individual/en/products/251712/ishares-aex-ucits-etf", "label": "Index proxy (iShares AEX)"},
    # Single-country MSCI indices (verified full-replication iShares funds)
    "msci_usa": {"path": "/uk/individual/en/products/253740/ishares-msci-usa-b-ucits-etf", "label": "Index proxy (iShares MSCI USA)"},
    "msci_japan": {
        "path": "/uk/individual/en/products/251866/ishares-msci-japan-ucits-etf-inc-fund",
        "label": "Index proxy (iShares MSCI Japan)",
    },
    "msci_china": {
        "path": "/uk/individual/en/products/308751/ishares-msci-china-ucits-etf-usd-acc-fund",
        "label": "Index proxy (iShares MSCI China)",
    },
    "msci_india": {
        "path": "/uk/individual/en/products/297617/ishares-msci-india-ucits-etf-usd-acc-fund",
        "label": "Index proxy (iShares MSCI India)",
    },
    "msci_uk": {"path": "/uk/individual/en/products/253739/ishares-msci-uk-ucits-etf", "label": "Index proxy (iShares MSCI UK)"},
    # German-domiciled iShares fund → SpreadsheetML holdings ("fmt": "de_xls").
    "stoxx_600": {
        "path": "/ch/individual/en/products/251931/ishares-stoxx-europe-600-ucits-etf-de-fund",
        "label": "Index proxy (iShares STOXX Europe 600)",
        "fmt": "de_xls",
    },
}

# Name phrases → index key.  Only indices that genuinely mean the *same basket*
# across providers are listed: S&P 500 / EURO STOXX 50 / MSCI Europe / MSCI EM
# / AEX are unambiguous, and "MSCI World" is matched only when spelled exactly
# (so FTSE Developed World / FTSE All-World — which have a different basket —
# don't get mismapped).
# "Specific" indices that include a small-cap / IMI universe and have their
# own reference fund.  Checked *before* the generic IMI guard, so e.g. an
# "MSCI EM IMI" fund matches its own IMI reference instead of being rejected.
_INDEX_RULES_SPECIFIC: list[tuple[list[str], str]] = [
    (["msci em imi", "msci emerging markets imi", "emerging markets imi", "em imi"], "msci_em_imi"),
]

# Generic broad indices — matched only when no basket-changing qualifier is
# present.  "MSCI World" is matched exactly so FTSE All-World / FTSE Developed
# World (different baskets) don't get mismapped.
_INDEX_RULES: list[tuple[list[str], str]] = [
    (["euro stoxx 50", "eurostoxx 50", "euro stoxx50", "estoxx 50", "ez50"], "euro_stoxx_50"),
    (["stoxx europe 600", "stoxx 600", "stoxx600"], "stoxx_600"),
    (["s&p 500", "s&p500", "sp 500", "sp500", "s & p 500"], "sp500"),
    (["nasdaq 100", "nasdaq-100", "nasdaq100"], "nasdaq_100"),
    (["msci acwi", "msci all country world", "acwi"], "msci_acwi"),
    (["msci world"], "msci_world"),
    (["msci europe"], "msci_europe"),
    (["msci em", "msci emerging markets"], "msci_em"),
    (["aex"], "aex"),
    # Single-country MSCI indices (matched only when spelled with "MSCI",
    # so a FTSE/CSI/Topix tracker on the same country isn't mismapped).
    (["msci usa"], "msci_usa"),
    (["msci japan"], "msci_japan"),
    (["msci china"], "msci_china"),
    (["msci india"], "msci_india"),
    (["msci united kingdom", "msci uk"], "msci_uk"),
]

# Tokens that signal a *different* basket than the plain index (factor tilts,
# screens, exclusions, leverage, sectors, synthetic swaps…).  When any is
# present we refuse to proxy and let the caller fall back to the approximate
# Yahoo/justetf path, so a tilted fund is never silently shown as if it held
# the full vanilla index.  Currency hedging is deliberately absent — a hedged
# fund holds the identical basket.  "imi" is handled separately (see below):
# it's a valid index for EM but small-cap-inclusive for the broad ones.
_INDEX_VARIANT_GUARDS: list[str] = [
    # Size / coverage variants
    "small cap",
    "smallcap",
    "small-cap",
    "mid cap",
    "mid-cap",
    " ex ",
    " ex-",
    "ex usa",
    "ex uk",
    "ex japan",
    "ex europe",
    "top 30",
    "ex-top",
    "ex top",
    # Factor / strategy tilts
    "value",
    "growth",
    "momentum",
    "quality",
    "minimum volatility",
    "min vol",
    "multifactor",
    "multi-factor",
    "high dividend",
    "dividend",
    "buyback",
    "equal weight",
    "equal-weight",
    "leveraged",
    "2x",
    "3x",
    "short",
    "inverse",
    "covered call",
    "swap",
    # Screens
    "esg",
    "sri",
    "screened",
    "sustainab",
    "paris",
    "climate",
    # Sector / industry sub-indices (a "MSCI World <sector>" fund holds a
    # different basket than the parent index — never proxy these).
    "sector",
    "information technology",
    "technology",
    "tech",
    "health care",
    "healthcare",
    "financials",
    "financial",
    "consumer",
    "communication",
    "industrials",
    "materials",
    "utilities",
    "energy",
    "real estate",
    "banks",
    "insurance",
    "semiconductor",
    "biotech",
    # Single-country lookalikes that are a *different* index than the plain
    # MSCI country index (China A-shares / CSI / Islamic / Leaders, etc.).
    "china a",
    "a shares",
    "a-share",
    "a share",
    "csi",
    "a50",
    "hscei",
    "islamic",
    "leaders",
    "onshore",
]


def _resolve_index_proxy(name: str | None) -> tuple[str, dict] | None:
    """
    Map an ETF *name* to a same-index reference fund (key, source dict), or
    None.  Conservative by design: any factor/screen/sector/exclusion variant
    returns None so we never proxy onto a basket that differs materially.
    """
    if not name:
        return None
    low = " " + name.lower() + " "

    # Basket-changing qualifiers (excluding IMI) disqualify everything.
    if any(g in low for g in _INDEX_VARIANT_GUARDS):
        return None

    # IMI-universe indices with a dedicated reference fund (e.g. MSCI EM IMI).
    for phrases, key in _INDEX_RULES_SPECIFIC:
        if any(p in low for p in phrases):
            return key, _INDEX_PROXY_SOURCES[key]

    # For the broad indices, an IMI universe is a different (small-cap-incl.)
    # basket with no reference fund here — fall back to the estimate path.
    if " imi" in low:
        return None

    for phrases, key in _INDEX_RULES:
        if any(p in low for p in phrases):
            return key, _INDEX_PROXY_SOURCES[key]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_FETCHERS = [
    (ISHARES_PRODUCTS, _fetch_ishares),
    (SPDR_PRODUCTS, _fetch_spdr),
    (VANGUARD_PRODUCTS, _fetch_vanguard),
    (PROXY_FUNDS, _fetch_proxy),
]


def _resolve(conn: sqlite3.Connection, isin: str, name: str | None) -> tuple[str, object, str, str] | None:
    """
    Decide where a fund's complete holdings come from.

    Returns (kind, ref, label, quality) or None:
      kind 'registry'      → ref is the ISIN; fetch via the matching _FETCHERS entry (exact/proxy)
      kind 'vanguard_auto' → ref is a portId; Vanguard fund (exact for Vanguard's own funds, proxy as a same-index stand-in)
      kind 'index_proxy'   → ref is an _INDEX_PROXY_SOURCES key; same-index stand-in (proxy)

    Order: hand-registered ISIN → Vanguard's own fund (exact) → iShares
    same-index proxy → Vanguard same-index proxy.
    """
    if isin in ISHARES_PRODUCTS:
        return ("registry", isin, "iShares (issuer)", "exact")
    if isin in SPDR_PRODUCTS:
        return ("registry", isin, "SPDR (issuer)", "exact")
    if isin in VANGUARD_PRODUCTS:
        return ("registry", isin, "Vanguard (issuer)", "exact")
    if isin in PROXY_FUNDS:
        return ("registry", isin, PROXY_FUNDS[isin]["label"], "proxy")

    low_name = (name or "").lower()
    is_vanguard = any(s in low_name for s in _VANGUARD_SPELLINGS)
    vg = _vanguard_match(conn, name, allow_subseq=is_vanguard)
    if vg and is_vanguard:
        return ("vanguard_auto", vg[0], "Vanguard (issuer)", "exact")

    # iShares same-index proxy (covers the MSCI / S&P / Nasdaq / EURO STOXX
    # families that Vanguard's FTSE-based range doesn't).
    proxy = _resolve_index_proxy(name)
    if proxy:
        return ("index_proxy", proxy[0], proxy[1]["label"], "proxy")

    # Vanguard same-index proxy for another issuer's fund (e.g. an Invesco or
    # HSBC FTSE All-World borrows Vanguard's FTSE All-World basket — same index,
    # near-exact).  Safe because the match is on the exact index name, so an
    # MSCI fund never lands on Vanguard's FTSE range.
    if vg:
        label = re.sub(r"\s+ucits etf.*$", "", vg[1], flags=re.IGNORECASE).strip()
        return ("vanguard_auto", vg[0], f"Index proxy (Vanguard {label})", "proxy")

    return None


def supports(conn: sqlite3.Connection, isin: str, name: str | None = None) -> bool:
    """True when complete holdings can be sourced for this fund."""
    return _resolve(conn, isin, name) is not None


def source_info(conn: sqlite3.Connection, isin: str, name: str | None = None) -> tuple[str, str] | None:
    """
    (label, quality) describing where this fund's holdings come from.
    quality is 'exact' for issuer data, 'proxy' for a same-index stand-in.
    None when nothing matches.
    """
    r = _resolve(conn, isin, name)
    return (r[2], r[3]) if r else None


def fetch_issuer_holdings(conn: sqlite3.Connection, isin: str, name: str | None = None) -> list[dict] | None:
    """
    Returns the complete holdings list for a supported fund, or None.

    Resolution: hand-registered issuer/proxy by ISIN → automatic Vanguard
    discovery by name → automatic same-index proxy.  Successful results are
    cached in SQLite for 7 days keyed on the position's own ISIN; failures are
    not cached, so a temporary site problem heals on the next refresh.
    """
    r = _resolve(conn, isin, name)
    if r is None:
        return None
    kind, ref = r[0], r[1]

    # v2: holdings carry sector/country — older cache entries lack them
    cache_key = f"issuer:v2:{isin}"
    cached = database.load_etf_api_cache(conn, cache_key)
    if cached is not None:
        try:
            holdings = json.loads(cached)
            if holdings:
                return holdings
        except json.JSONDecodeError:
            pass

    if kind == "registry":
        fetcher = next(f for registry, f in _FETCHERS if isin in registry)
        holdings = fetcher(isin)
    elif kind == "vanguard_auto":
        holdings = _fetch_vanguard_portid(ref)
    else:  # index_proxy — ref is an _INDEX_PROXY_SOURCES key
        src = _INDEX_PROXY_SOURCES[ref]
        if src.get("fmt") == "de_xls":
            holdings = _fetch_ishares_de_path(src["path"])
        else:
            holdings = _fetch_ishares_path(src["path"])

    if holdings:
        database.save_etf_api_cache(conn, cache_key, json.dumps(holdings))
    return holdings
