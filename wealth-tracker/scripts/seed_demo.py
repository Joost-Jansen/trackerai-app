"""
seed_demo.py — a demo account with made-up data, to try the app (or take
screenshots of it) without real figures.

Creates the user `demo` and fills their own database with:

  * a portfolio of broad ETFs and a few well-known shares, bought monthly over
    three years, with one sale, transaction costs and dividends;
  * Money: a current account with a year of bank transactions (salary, rent,
    groceries, subscriptions, …) that the default rules label by themselves, a
    savings account, a student debt and budgets per group.

Nothing in here comes from a real person: the amounts, account numbers
(`NL00DEMO…`, not a valid IBAN) and the employer are made up; the funds and
shares are real, public listings.

Prices: with internet the script fetches the real closes from Yahoo, so
purchases and charts match the market. Without (or with `--offline`) it makes
a fixed, made-up price course per ticker (`price_series`), so the script always
works.

    python scripts/seed_demo.py                      # the password is shown
    DEMO_PASSWORD=... python scripts/seed_demo.py --reset
    DATA_DIR=/data AUTH_CONFIG_PATH=/data/auth_config.yaml python scripts/seed_demo.py

If auth_config.yaml does not exist yet, the script creates it with `demo` as
admin (as the first start with ADMIN_USERNAME does). If it does exist, `demo`
is added as a normal user with the beta flags on.
"""

import argparse
import hashlib
import json
import math
import os
import random
import secrets
import sys
from datetime import UTC, date, datetime, timedelta

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BACKEND = os.path.join(_ROOT, "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import bcrypt  # noqa: E402
import yaml  # noqa: E402

from domain import database, onboarding  # noqa: E402
from domain.money import accounts, bank_transactions, budget, categorization  # noqa: E402
from domain.money.bank_providers.base import dedup_hash  # noqa: E402

USER = "demo"
BETA = ("rebalancing", "returns", "dividends", "calendar", "money")

# ISIN, name, Yahoo ticker, exchange, price today (only for the made-up course),
# yearly trend, volatility, dividend per unit per payout, payouts per year.
FUNDS = [
    ("IE00BK5BQT80", "VANGUARD FTSE ALL-WORLD UCITS ETF USD ACC", "VWCE.DE", "XET", 142.0, 0.09, 0.14, 0.0, 0),
    ("IE00B4L5Y983", "ISHARES CORE MSCI WORLD UCITS ETF USD (ACC)", "IWDA.AS", "EAM", 108.0, 0.10, 0.14, 0.0, 0),
    ("IE00BKM4GZ66", "ISHARES CORE MSCI EM IMI UCITS ETF USD (ACC)", "EMIM.AS", "EAM", 36.0, 0.05, 0.16, 0.0, 0),
    ("IE00B8GKDB10", "VANGUARD FTSE ALL-WORLD HIGH DIVIDEND YIELD UCITS ETF", "VHYL.AS", "EAM", 70.0, 0.07, 0.12, 0.62, 4),
    ("NL0010273215", "ASML HOLDING", "ASML.AS", "EAM", 760.0, 0.14, 0.32, 1.60, 4),
    ("NL0011794037", "KONINKLIJKE AHOLD DELHAIZE NV", "AD.AS", "EAM", 34.0, 0.05, 0.18, 0.55, 2),
    ("GB00B10RZP78", "UNILEVER PLC", "UNA.AS", "EAM", 57.0, 0.04, 0.16, 0.43, 4),
    ("IE00B4WXJJ64", "ISHARES CORE EUR GOVT BOND UCITS ETF", "IEGA.AS", "EAM", 116.0, 0.01, 0.05, 1.20, 2),
]

# What goes from the monthly deposit to which fund (euros).
MONTHLY = {"IE00BK5BQT80": 300, "IE00BKM4GZ66": 60, "IE00B4WXJJ64": 40}
# Single purchases: (months after the start, ISIN, amount in euros).
LOOSE = [
    (2, "NL0010273215", 1400),
    (5, "IE00B8GKDB10", 900),
    (7, "NL0011794037", 600),
    (9, "GB00B10RZP78", 700),
    (14, "IE00B4L5Y983", 1500),
    (20, "NL0010273215", 800),
    (26, "IE00B8GKDB10", 600),
    (30, "IE00B4L5Y983", 1000),
]
SALE = (24, "NL0011794037", 0.5)  # after two years half of Ahold sold

_START = date(2015, 1, 1)  # every made-up price series starts here
IBAN_PAY = "NL00DEMO0000000001"
IBAN_SAVINGS = "NL00DEMO0000000002"


# --- prices ----------------------------------------------------------------------------------------


def _workdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def price_series(ticker: str, start: date, end: date, final: float, trend: float = 0.07, volatile: float = 0.15) -> dict[date, float]:
    """A fixed, made-up price course per working day that ends at `final` on `end`.

    Fixed: the same ticker always gives the same course (the seed is the ticker,
    and the series always starts on the same day), so purchases and charts keep
    fitting together, even when something only asks for a piece. The price
    fluctuates around a straight trend line (a mean-reverting walk), so over the
    years it rises by `trend` on average instead of accidentally halving or
    quadrupling.
    """
    rnd = random.Random(int(hashlib.sha1(ticker.encode()).hexdigest()[:8], 16))
    days = _workdays(_START, end)
    sigma = volatile / math.sqrt(252)
    noise, x = [], 0.0
    for _ in days:
        x = 0.985 * x + rnd.gauss(0, sigma)
        noise.append(x)
    n = len(days) - 1
    series = {}
    for i, d in enumerate(days):
        if d >= start:
            log = math.log(final) - trend * (n - i) / 252 + noise[i] - noise[-1]
            series[d] = round(math.exp(log), 2)
    return series


def _real_prices(tickers: list[str], start: date) -> dict[str, dict[date, float]]:
    """Closes from Yahoo, or {} if that does not work (no internet)."""
    try:
        import yfinance as yf

        raw = yf.download(tickers, start=start.isoformat(), progress=False, auto_adjust=False)
        if raw is None or raw.empty:
            return {}
        slot = raw["Close"]
        off = {}
        for t in tickers:
            if t in slot.columns:
                s = slot[t].dropna()
                if len(s) > 100:
                    off[t] = {i.date(): round(float(v), 2) for i, v in s.items()}
        return off
    except Exception:
        return {}


def _price_on(series: dict[date, float], day: date) -> float:
    for i in range(10):
        d = day - timedelta(days=i)
        if d in series:
            return series[d]
    return series[min(series)]


# --- account ---------------------------------------------------------------------------------------


def _auth_path() -> str:
    return os.environ.get("AUTH_CONFIG_PATH") or os.path.join(_ROOT, "auth_config.yaml")


def make_account(password: str, reset: bool) -> bool:
    """Puts `demo` in auth_config.yaml. Returns True if demo became admin."""
    path = _auth_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {
            "cookie": {"name": "stock_tracker_auth", "key": secrets.token_hex(32), "expiry_days": 14},
            "credentials": {"usernames": {}},
            "admins": [],
            "registration_mode": "closed",
        }
    users = cfg.setdefault("credentials", {}).setdefault("usernames", {})
    if USER in users and not reset:
        raise SystemExit(f"User '{USER}' already exists; use --reset to replace it.")
    first = not users or cfg.get("admins") == [USER]
    users[USER] = {
        "name": "Demo",
        "email": f"{USER}@local",
        "password": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(),
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    if first:
        cfg["admins"] = [USER]
    beta = cfg.setdefault("beta", {})
    for flag in BETA:
        items = beta.setdefault(flag, [])
        if USER not in items:
            items.append(USER)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    os.chmod(path, 0o600)
    return first


# --- portfolio -------------------------------------------------------------------------------------


def _month(start: date, n: int, day: int = 3) -> date:
    j, m = start.year + (start.month - 1 + n) // 12, (start.month - 1 + n) % 12 + 1
    d = date(j, m, day)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def fill_portfolio(conn, start: date, final: date, offline: bool) -> dict:
    tickers = [f[2] for f in FUNDS]
    real = {} if offline else _real_prices(tickers, start - timedelta(days=10))
    series_list = {}
    for isin, _name, ticker, _exchange, price, trend, volatile, *_ in FUNDS:
        series_list[isin] = real.get(ticker) or price_series(ticker, start - timedelta(days=10), final, price, trend, volatile)
    info = {f[0]: f for f in FUNDS}
    rnd = random.Random(7)

    transactions, sequence_number = [], 0

    def trade(day: date, isin: str, euro: float | None = None, units: float | None = None, sale: bool = False):
        nonlocal sequence_number
        _, name, ticker, exchange, *_ = info[isin]
        price = _price_on(series_list[isin], day)
        count = units if units is not None else max(1, math.floor(euro / price))
        value = round(count * price, 2) * (1 if sale else -1)
        costs = -1.0 if isin in MONTHLY and not sale else -3.0  # core selection vs. single order
        sequence_number += 1
        transactions.append(
            {
                "order_ref": f"demo-{sequence_number:05d}",
                "date": day.isoformat(),
                "time": f"{rnd.randint(9, 16):02d}:{rnd.randint(0, 59):02d}",
                "name": name,
                "isin": isin,
                "exchange": exchange,
                "execution_venue": exchange,
                "transaction_type": "SELL" if sale else "BUY",
                "quantity": float(count),
                "price": price,
                "local_value": value,
                "value_eur": value,
                "exchange_rate": None,
                "autofx_cost": None,
                "transaction_fee": costs,
                "total_eur": round(value + costs, 2),
            }
        )
        return count

    months = (final.year - start.year) * 12 + final.month - start.month
    bought: dict[str, float] = {}
    for n in range(months + 1):
        day = _month(start, n)
        if day > final:
            break
        for isin, euro in MONTHLY.items():
            bought[isin] = bought.get(isin, 0) + trade(day, isin, euro=euro * rnd.uniform(0.9, 1.1))
        for m, isin, euro in LOOSE:
            if m == n:
                bought[isin] = bought.get(isin, 0) + trade(day + timedelta(days=7), isin, euro=euro)
        if SALE[0] == n:
            isin = SALE[1]
            trade(day + timedelta(days=10), isin, units=math.floor(bought[isin] * SALE[2]), sale=True)
    database.save_transactions(conn, transactions)

    # Dividends: per payout the number of units you had then, 15% withholding tax.
    dividends = []
    for isin, name, _ticker, _exchange, _price, _trend, _volatile, per_piece, per_year in FUNDS:
        if not per_year:
            continue
        step = 12 // per_year
        for n in range(1, months + 1):
            if n % step:
                continue
            day = _month(start, n, 20)
            if day > final:
                break
            units = sum(
                t["quantity"] * (1 if t["transaction_type"] == "BUY" else -1)
                for t in transactions
                if t["isin"] == isin and t["date"] < day.isoformat()
            )
            if units <= 0:
                continue
            gross = round(units * per_piece, 2)
            tax = round(gross * 0.15, 2)
            dividends.append(
                {
                    "date": day.isoformat(),
                    "isin": isin,
                    "name": name,
                    "currency_original": "EUR",
                    "amount_original": gross,
                    "gross_eur": gross,
                    "tax_eur": tax,
                    "net_eur": round(gross - tax, 2),
                }
            )
    database.save_dividends(conn, dividends)

    for isin, name, ticker, *_ in FUNDS:
        series = series_list[isin]
        days = sorted(series)
        database.save_price(conn, isin, name, ticker, series[days[-1]], "EUR", previous_close=series[days[-2]], quote_currency="EUR")
    for isin, *_ in FUNDS:
        database.save_asset_category(conn, isin, "Bonds" if isin == "IE00B4WXJJ64" else "Stocks")
    return {"transactions": len(transactions), "dividends": len(dividends), "real_prices": bool(real)}


# --- money -----------------------------------------------------------------------------------------

IS_FIXED = [  # (day of the month, name, description, amount; spending positive, income negative)
    (1, "WONINGSTICHTING VOORBEELD", "Huur woning", 1185.00),
    (2, "VATTENFALL KLANTENSERVICE", "Termijnbedrag energie", 118.00),
    (4, "ZIGGO SERVICES BV", "Internet en tv", 54.50),
    (5, "ZILVEREN KRUIS ZORGVERZEKERINGEN", "Premie zorgverzekering", 151.95),
    (6, "BASIC-FIT NEDERLAND", "Lidmaatschap", 29.99),
    (8, "SPOTIFY", "Premium", 11.99),
    (8, "NETFLIX.COM", "Abonnement", 13.99),
    (12, "ODIDO", "Mobiel abonnement", 19.50),
    (24, "VOORBEELD BV", "SALARIS {month}", -3650.00),
    (25, "DEGIRO", "Inleg beleggen", 500.00),
    (26, "ORANJE SPAARREKENING", "Naar spaarrekening", 400.00),
    (27, "DUO HOOFDREKENING", "Aflossing studieschuld", 95.00),
]
VARIABLE = [  # (name, description, min, max, times per month)
    ("ALBERT HEIJN 1427 UTRECHT", "Betaalautomaat", 12, 85, 7),
    ("JUMBO UTRECHT", "Betaalautomaat", 8, 60, 3),
    ("LIDL UTRECHT", "Betaalautomaat", 10, 45, 2),
    ("NS GROEP IZ NS REIZIGERS", "OV-chipkaart", 6, 38, 4),
    ("THUISBEZORGD.NL", "Bestelling", 18, 42, 2),
    ("CAFE DE VOORBEELDHOEK", "Betaalautomaat", 9, 48, 2),
    ("BOL.COM", "Bestelling", 15, 120, 1),
    ("KRUIDVAT 7781", "Betaalautomaat", 5, 30, 1),
    ("ZALANDO SE", "Bestelling", 30, 140, 0.5),
    ("PATHE UTRECHT", "Bioscoop", 12, 30, 0.7),
    ("BOOKING.COM", "Hotel", 180, 420, 0.25),
    ("SWAPFIETS", "Abonnement", 19.9, 19.9, 1),
]


def fill_money(conn, final: date) -> dict:
    categorization.seed(conn)
    rnd = random.Random(11)
    pay = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Betaalrekening", iban=IBAN_PAY)
    savings = accounts.make_bank_account(conn, kind="bank", provider="ing", name="Spaarrekening", iban=IBAN_SAVINGS)
    debt = accounts.make_bank_account(conn, kind="debt", provider="manual", name="Studieschuld")

    start = date(final.year - 1, final.month, 1)
    month_names = [
        "januari",
        "februari",
        "march",
        "april",
        "mei",
        "juni",
        "july",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
    ]
    rules = []
    d = start
    while d <= final:
        for day, name, description, amount in IS_FIXED:
            if d.day == day:
                rules.append((d, name, description.format(month=month_names[d.month - 1]), amount))
        for name, description, low, high, per_month in VARIABLE:
            if rnd.random() < per_month / 30:
                rules.append((d, name, description, round(rnd.uniform(low, high), 2)))
        if d.month == 5 and d.day == 22:
            rules.append((d, "VOORBEELD BV", "VAKANTIEGELD", -2350.00))
        d += timedelta(days=1)

    rows = []
    for i, (day, name, description, amount) in enumerate(rules):
        on_date = day.isoformat()
        rows.append(
            {
                "date": on_date,
                "interest_date": None,
                "amount": amount,
                "currency": "EUR",
                "name": name,
                "counterparty_iban": IBAN_SAVINGS if "SAVINGS" in name else None,
                "description": description,
                "account_iban": IBAN_PAY,
                "code": "BA" if amount > 0 else "GT",
                "kind": None,
                "dedup_hash": dedup_hash(on_date, amount, name, description, i),
                "raw": {},
            }
        )
    bank_transactions.save(conn, pay, rows)

    # Balances that match the transactions exactly: at the end of every month.
    balance, per_day = 2400.0, {}
    for day, _, _, amount in sorted(rules, key=lambda r: r[0]):
        balance -= amount
        per_day[day] = round(balance, 2)
    ends, last = [], None
    for day in sorted(per_day):
        if last and day.month != last.month:
            ends.append((last.isoformat(), per_day[last]))
        last = day
    ends.append((last.isoformat(), per_day[last]))
    accounts.set_balance(conn, pay, (start - timedelta(days=1)).isoformat(), 2400.0)
    accounts.set_balances(conn, pay, ends, source="manual")

    saving, student_debt, balances_savings, balances_debt = 6500.0, 14200.0, [], []
    for n in range(13):
        day = _month(start, n, 27)
        if day > final:
            break
        saving += 400 + saving * 0.0015
        student_debt -= 95 - student_debt * 0.0002
        balances_savings.append((day.isoformat(), round(saving, 2)))
        balances_debt.append((day.isoformat(), round(-student_debt, 2)))
    accounts.set_balances(conn, savings, balances_savings, source="manual")
    accounts.set_balances(conn, debt, balances_debt, source="manual")

    labelled = categorization.relabel(conn, everything=True)
    groups = budget.spending_groups(conn)
    wishes = {
        "Boodschappen": 450,
        "Wonen": 1400,
        "Vervoer": 150,
        "Eten & vrije tijd": 250,
        "Abonnementen": 80,
        "Shoppen": 200,
        "Verzekering & zorg": 170,
        "Vakantie": 150,
    }
    for group_name in groups:
        if group_name in wishes:
            budget.put(conn, group_name, wishes[group_name])
    return {"bank_transactions": len(rows), "labelled": labelled, "budget_groups": [g for g in groups if g in wishes]}


# --- everything ------------------------------------------------------------------------------------


def seed(final: date, password: str, reset: bool = False, offline: bool = False) -> dict:
    first = make_account(password, reset)
    if reset:
        database.delete_user_data(USER)  # the folder, and with WEALTH_DATABASE_URL the schema
    conn = database.connect(USER)
    try:
        database.init_db(conn)
        start = date(final.year - 3, final.month, 1)
        off = {"admin": first, **fill_portfolio(conn, start, final, offline), **fill_money(conn, final)}
        onboarding.put(conn, choice="both", done=True)
    finally:
        conn.close()
    return off


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create the demo account with invented data.")
    p.add_argument("--end", dest="final", type=date.fromisoformat, default=date.today(), help="last day with data (default: today)")
    p.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"), help="default: DEMO_PASSWORD or a new random password")
    p.add_argument("--reset", action="store_true", help="first throw away an existing demo account with all its data")
    p.add_argument("--offline", action="store_true", help="fetch no prices; use an invented price path")
    args = p.parse_args(argv)
    password = args.password or secrets.token_urlsafe(12)
    print(json.dumps(seed(args.final, password, args.reset, args.offline), ensure_ascii=False, default=str))
    if not args.password:
        print(f"Log in as '{USER}' with password: {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
