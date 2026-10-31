"""
brokers.py — the brokers a portfolio can be spread over.

Every trade and dividend carries the code of the broker it belongs to
(`transactions.broker`, `dividends.broker`), and every broker can have one cash
account (an `accounts` row of kind `broker` whose `provider` is that code).

Positions aggregate *per ISIN* across brokers everywhere a number is about the
fund (dashboard totals, allocation, returns, net worth): two lots of the same
ETF at two brokers are one exposure. Only the Portfolio tab lists them apart,
per broker and exchange, because each broker reports its own average cost.

A code is data, not behaviour: nothing in the app branches on which broker a
row came from, except the importer that read it. Adding a broker is adding a
code here (and to accounts.PROVIDERS) plus, optionally, an importer.
"""

#: code -> display name. The name is a proper noun and is not translated.
BROKERS: dict[str, str] = {
    "degiro": "DeGiro",
    "trade_republic": "Trade Republic",
}

#: What a broker cash account is called when the app creates it by itself.
CASH_ACCOUNT_NAMES: dict[str, str] = {code: f"{name} cash" for code, name in BROKERS.items()}


def label(code: str | None) -> str:
    """The display name of a broker code; an unknown code is shown as it is."""
    if not code:
        return ""
    return BROKERS.get(code, code)


def verify(code: str) -> str:
    """The code itself, or ValueError for a broker the app does not know."""
    from domain.i18n import tr

    if code not in BROKERS:
        raise ValueError(tr("Unknown broker: {0}. Choose from: {1}", repr(code), ", ".join(BROKERS)))
    return code
