"""Tests for transaction_parser.py against synthetic DeGiro-shaped exports."""

import math

import pandas as pd
import pytest

from domain.imports import degiro_transactions as transaction_parser


def _write_xlsx(tmp_path, rows: list[dict], columns: list[str]):
    path = tmp_path / "Transactions.xlsx"
    df = pd.DataFrame(rows, columns=columns)
    df.to_excel(path, index=False, header=True)
    return str(path)


_DUTCH_COLUMNS = [
    "Datum",
    "Tijd",
    "Product",
    "ISIN",
    "Beurs",
    "Uitvoeringsplaats",
    "Aantal",
    "Koers",
    "Lokale waarde",
    "Waarde",
    "Wisselkoers",
    "Transactiekosten",
    "Totaal",
    "Order Id",
]


def test_parses_buy_and_sell_dutch_headers(tmp_path):
    rows = [
        {
            "Datum": "05-01-2026",
            "Tijd": "09:30",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": 10,
            "Koers": 80.5,
            "Lokale waarde": -805.0,
            "Waarde": -805.0,
            "Wisselkoers": 1.0,
            "Transactiekosten": -1.0,
            "Totaal": -806.0,
            "Order Id": "order-1",
        },
        {
            "Datum": "06-01-2026",
            "Tijd": "10:15",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": -4,
            "Koers": 82.0,
            "Lokale waarde": 328.0,
            "Waarde": 328.0,
            "Wisselkoers": 1.0,
            "Transactiekosten": -1.0,
            "Totaal": 327.0,
            "Order Id": "order-2",
        },
    ]
    path = _write_xlsx(tmp_path, rows, _DUTCH_COLUMNS)
    txs = transaction_parser.parse_transactions(path)

    assert len(txs) == 2
    buy, sell = txs
    assert buy["transaction_type"] == "BUY"
    assert buy["quantity"] == 10.0
    assert buy["date"] == "2026-01-05"
    assert buy["isin"] == "IE00B4L5Y983"
    assert buy["total_eur"] == -806.0

    assert sell["transaction_type"] == "SELL"
    assert sell["quantity"] == 4.0  # sign stripped, direction carried in transaction_type
    assert sell["date"] == "2026-01-06"


def test_parses_english_headers(tmp_path):
    english_columns = [
        "Date",
        "Time",
        "Product",
        "ISIN",
        "Reference Exchange",
        "Execution Venue",
        "Quantity",
        "Price",
        "Local value",
        "Value",
        "Exchange rate",
        "Transaction and/or",
        "Total",
        "Order Id",
    ]
    rows = [
        {
            "Date": "10-03-2026",
            "Time": "14:00",
            "Product": "SPDR S&P 500",
            "ISIN": "IE00B6YX5C33",
            "Reference Exchange": "XET",
            "Execution Venue": "XET",
            "Quantity": 5,
            "Price": 45.0,
            "Local value": -225.0,
            "Value": -225.0,
            "Exchange rate": 1.0,
            "Transaction and/or": -0.5,
            "Total": -225.5,
            "Order Id": "order-3",
        }
    ]
    path = _write_xlsx(tmp_path, rows, english_columns)
    txs = transaction_parser.parse_transactions(path)

    assert len(txs) == 1
    assert txs[0]["isin"] == "IE00B6YX5C33"
    assert txs[0]["transaction_type"] == "BUY"
    assert txs[0]["date"] == "2026-03-10"


def test_skips_rows_without_isin(tmp_path):
    rows = [
        {**{c: None for c in _DUTCH_COLUMNS}, "ISIN": ""},
        {
            "Datum": "05-01-2026",
            "Tijd": "09:30",
            "Product": "Valid fund",
            "ISIN": "IE00B4L5Y983",
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": 1,
            "Koers": 10.0,
            "Lokale waarde": -10.0,
            "Waarde": -10.0,
            "Wisselkoers": 1.0,
            "Transactiekosten": 0.0,
            "Totaal": -10.0,
            "Order Id": "order-4",
        },
    ]
    path = _write_xlsx(tmp_path, rows, _DUTCH_COLUMNS)
    txs = transaction_parser.parse_transactions(path)
    assert len(txs) == 1
    assert txs[0]["isin"] == "IE00B4L5Y983"


def test_missing_file_returns_empty_list(tmp_path):
    assert transaction_parser.parse_transactions(str(tmp_path / "does-not-exist.xlsx")) == []


def test_row_without_quantity_derives_quantity_from_value_and_price(tmp_path):
    """
    DeGiro books an order placed in euros — a money-market fund bought for
    exactly €50.000 — with an empty "Aantal". That empty cell reaches pandas as
    NaN, survived float(), and sqlite stored it as NULL against a NOT NULL
    column: one such row used to fail the whole upload with a 500 and save none
    of the other rows in the file.
    """
    rows = [
        {
            "Datum": "11-08-2026",
            "Tijd": "16:00",
            "Product": "PICTET-SHORT-TERM MONEY MARKET EUR-I",
            "ISIN": "LU0128494944",
            "Beurs": "KFS",
            "Uitvoeringsplaats": None,
            "Aantal": None,
            "Koers": 151.6555,
            "Lokale waarde": -49995.099421,
            "Waarde": -49995.099421,
            "Wisselkoers": None,
            "Transactiekosten": -4.9,
            "Totaal": -49999.999421,
            "Order Id": "order-mm",
        },
        {
            "Datum": "12-08-2026",
            "Tijd": "09:00",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": 3,
            "Koers": 100.0,
            "Lokale waarde": -300.0,
            "Waarde": -300.0,
            "Wisselkoers": 1.0,
            "Transactiekosten": -1.0,
            "Totaal": -301.0,
            "Order Id": "order-3",
        },
    ]
    path = _write_xlsx(tmp_path, rows, _DUTCH_COLUMNS)
    warnings: list[dict] = []
    txs = transaction_parser.parse_transactions(path, warnings=warnings)

    # The rest of the file must survive the odd row.
    assert len(txs) == 2
    assert warnings == []

    fund = txs[0]
    # Money left the account, so it is a purchase, and the units are exactly
    # the division DeGiro itself did.
    assert fund["transaction_type"] == "BUY"
    assert fund["quantity"] == pytest.approx(49995.099421 / 151.6555)
    assert math.isfinite(fund["quantity"])


def test_row_with_no_quantity_and_no_price_is_reported_not_dropped(tmp_path):
    """Nothing to derive from: the row is left out, but never in silence."""
    rows = [
        {
            "Datum": "11-08-2026",
            "Tijd": "16:00",
            "Product": "MYSTERY FUND",
            "ISIN": "LU0000000000",
            "Beurs": "KFS",
            "Uitvoeringsplaats": None,
            "Aantal": None,
            "Koers": None,
            "Lokale waarde": None,
            "Waarde": None,
            "Wisselkoers": None,
            "Transactiekosten": None,
            "Totaal": None,
            "Order Id": "order-x",
        },
        {
            "Datum": "12-08-2026",
            "Tijd": "09:00",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Beurs": "EAM",
            "Uitvoeringsplaats": "EAM",
            "Aantal": 3,
            "Koers": 100.0,
            "Lokale waarde": -300.0,
            "Waarde": -300.0,
            "Wisselkoers": 1.0,
            "Transactiekosten": -1.0,
            "Totaal": -301.0,
            "Order Id": "order-3",
        },
    ]
    path = _write_xlsx(tmp_path, rows, _DUTCH_COLUMNS)
    warnings: list[dict] = []
    txs = transaction_parser.parse_transactions(path, warnings=warnings)

    assert [t["isin"] for t in txs] == ["IE00B4L5Y983"]
    assert len(warnings) == 1
    assert warnings[0]["isin"] == "LU0000000000"
    assert warnings[0]["name"] == "MYSTERY FUND"


def test_sell_without_quantity_keeps_its_direction(tmp_path):
    """Money coming in is a sale, even when the units have to be derived."""
    rows = [
        {
            "Datum": "13-08-2026",
            "Tijd": "16:00",
            "Product": "PICTET MONEY MARKET",
            "ISIN": "LU0128494944",
            "Beurs": "KFS",
            "Uitvoeringsplaats": None,
            "Aantal": None,
            "Koers": 150.0,
            "Lokale waarde": 1500.0,
            "Waarde": 1500.0,
            "Wisselkoers": None,
            "Transactiekosten": None,
            "Totaal": 1500.0,
            "Order Id": "order-s",
        }
    ]
    path = _write_xlsx(tmp_path, rows, _DUTCH_COLUMNS)
    txs = transaction_parser.parse_transactions(path)

    assert len(txs) == 1
    assert txs[0]["transaction_type"] == "SELL"
    assert txs[0]["quantity"] == pytest.approx(10.0)
