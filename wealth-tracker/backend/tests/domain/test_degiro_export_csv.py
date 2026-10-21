"""CSV and Excel exports must produce the same financial values."""

import csv

import pandas as pd
import pytest

from domain.imports import degiro_cash
from domain.imports import degiro_dividends as dividend_parser
from domain.imports import degiro_transactions as transaction_parser
from domain.imports.degiro_export import number


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1.234,56", 1234.56),
        ("-1.234,56", -1234.56),
        ("1,234.56", 1234.56),
        ("62,02", 62.02),
        ("62.02", 62.02),
        ("NaN", None),
        ("inf", None),
        ("", None),
    ],
)
def test_numbers(text, expected):
    assert number(text) == expected


def write_csv(path, headers, rows, delimiter):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_transaction_csv_matches_excel(tmp_path, delimiter):
    headers = ["Datum", "Tijd", "Product", "ISIN", "Aantal", "Koers", "Lokale waarde", "Waarde EUR", "Totaal EUR", "Order ID"]
    row = ["11-06-2026", "10:31", "Example Fund", "IE0000000001", 9, 62.02, -558.18, -558.18, -561.18, "example-order"]
    excel = tmp_path / "export.xlsx"
    pd.DataFrame([row], columns=headers).to_excel(excel, index=False)
    csv_path = tmp_path / "export.csv 2"
    write_csv(csv_path, headers, [[str(v).replace(".", ",") if isinstance(v, float) else v for v in row]], delimiter)
    parsed = transaction_parser.parse_transactions(csv_path)
    assert len(parsed) == 1
    assert parsed == transaction_parser.parse_transactions(excel)
    assert parsed[0]["total_eur"] == -561.18


def test_account_csv_dividend_and_cash_match_excel(tmp_path):
    headers = ["Datum", "Tijd", "Valutadatum", "Product", "ISIN", "Omschrijving", "FX", "Mutatie", "", "Saldo", "", "Order ID"]
    row = ["11-06-2026", "10:31", "11-06-2026", "Example Fund", "IE0000000001", "Dividend", None, "EUR", 12.34, "EUR", 1234.56, ""]
    excel = tmp_path / "account.xlsx"
    pd.DataFrame([row], columns=headers).to_excel(excel, index=False)
    csv_path = tmp_path / "account.csv"
    write_csv(csv_path, headers, [[str(v).replace(".", ",") if isinstance(v, float) else v for v in row]], ",")
    assert dividend_parser.parse_dividends(csv_path) == dividend_parser.parse_dividends(excel)
    assert dividend_parser.parse_dividends(csv_path)[0]["net_eur"] == 12.34
    assert degiro_cash.read(csv_path) == degiro_cash.read(excel) == [{"date": "2026-06-11", "balance": 1234.56}]
