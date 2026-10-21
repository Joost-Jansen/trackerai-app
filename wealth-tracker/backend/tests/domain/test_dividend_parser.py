"""Tests for dividend_parser.py against synthetic DeGiro mutations exports."""

import pandas as pd

from domain.imports import degiro_dividends as dividend_parser

_COLUMNS = ["Datum", "Tijd", "Valutadatum", "Product", "ISIN", "Omschrijving", "FX", "Mutatie", "Bedrag", "Saldo"]


def _write_xlsx(tmp_path, rows: list[dict]):
    path = tmp_path / "Account.xlsx"
    df = pd.DataFrame(rows, columns=_COLUMNS)
    df.to_excel(path, index=False, header=True)
    return str(path)


def test_eur_dividend_with_withholding_tax(tmp_path):
    rows = [
        {
            "Datum": "01-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "01-02-2026",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Omschrijving": "Dividend",
            "FX": None,
            "Mutatie": "EUR",
            "Bedrag": 12.50,
            "Saldo": 100.0,
        },
        {
            "Datum": "01-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "01-02-2026",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Omschrijving": "Dividendbelasting",
            "FX": None,
            "Mutatie": "EUR",
            "Bedrag": -1.50,
            "Saldo": 98.5,
        },
    ]
    path = _write_xlsx(tmp_path, rows)
    divs = dividend_parser.parse_dividends(path)

    assert len(divs) == 1
    d = divs[0]
    assert d["isin"] == "IE00B4L5Y983"
    assert d["currency_original"] == "EUR"
    assert d["gross_eur"] == 12.50
    assert d["tax_eur"] == -1.50
    assert d["net_eur"] == 11.00


def test_usd_dividend_converted_via_fx_debit(tmp_path):
    rows = [
        {
            "Datum": "01-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "01-02-2026",
            "Product": "SPDR S&P 500",
            "ISIN": "IE00B6YX5C33",
            "Omschrijving": "Dividend",
            "FX": None,
            "Mutatie": "USD",
            "Bedrag": 10.17,
            "Saldo": None,
        },
        {
            "Datum": "02-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "02-02-2026",
            "Product": "SPDR S&P 500",
            "ISIN": "IE00B6YX5C33",
            "Omschrijving": "Valuta Debitering",
            "FX": 1.1749,
            "Mutatie": "USD",
            "Bedrag": -10.17,
            "Saldo": None,
        },
        {
            "Datum": "02-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "02-02-2026",
            "Product": "SPDR S&P 500",
            "ISIN": "IE00B6YX5C33",
            "Omschrijving": "Valuta Creditering",
            "FX": None,
            "Mutatie": "EUR",
            "Bedrag": 8.66,
            "Saldo": None,
        },
    ]
    path = _write_xlsx(tmp_path, rows)
    divs = dividend_parser.parse_dividends(path)

    assert len(divs) == 1
    d = divs[0]
    assert d["currency_original"] == "USD"
    assert d["amount_original"] == 10.17
    assert abs(d["gross_eur"] - 8.6561) < 0.001  # 10.17 / 1.1749
    assert d["tax_eur"] == 0.0


def test_missing_description_column_returns_empty(tmp_path):
    path = tmp_path / "bad.xlsx"
    pd.DataFrame({"Foo": [1], "Bar": [2]}).to_excel(path, index=False)
    assert dividend_parser.parse_dividends(str(path)) == []


def test_dedup_key_shape_matches_database_unique_constraint(tmp_path):
    """save_dividends() dedups on (date, isin, amount_original, currency_original) —
    confirm the parser always emits those four fields for every record."""
    rows = [
        {
            "Datum": "01-02-2026",
            "Tijd": "00:00",
            "Valutadatum": "01-02-2026",
            "Product": "iShares Core MSCI World",
            "ISIN": "IE00B4L5Y983",
            "Omschrijving": "Dividend",
            "FX": None,
            "Mutatie": "EUR",
            "Bedrag": 5.0,
            "Saldo": None,
        }
    ]
    path = _write_xlsx(tmp_path, rows)
    divs = dividend_parser.parse_dividends(path)
    assert len(divs) == 1
    for key in ("date", "isin", "amount_original", "currency_original"):
        assert divs[0].get(key) is not None


def _row(date, desc, ccy, amount, isin="", product="", fx=None):
    return {
        "Datum": date,
        "Tijd": "00:00",
        "Valutadatum": date,
        "Product": product,
        "ISIN": isin,
        "Omschrijving": desc,
        "FX": fx,
        "Mutatie": ccy,
        "Bedrag": amount,
        "Saldo": 0.0,
    }


def test_a_foreign_dividend_survives_an_fx_row_that_lands_late(tmp_path):
    """The conversion booked more than a week later — a date range that cuts
    between the two, which is what an export per calendar year does every
    December. The payment used to be dropped entirely, so every dividend total
    came out short with nothing on screen to say so."""
    path = _write_xlsx(
        tmp_path,
        [
            _row("02-03-2026", "Dividend", "USD", 24.00, "US0378331005", "Apple Inc"),
            _row("11-03-2026", "Valuta Debitering", "USD", -24.00, fx=1.0850),
        ],
    )
    divs = dividend_parser.parse_dividends(path)
    assert len(divs) == 1
    assert divs[0]["isin"] == "US0378331005"
    assert divs[0]["net_eur"] == round(24.00 / 1.0850, 4)


def test_a_rate_inside_the_week_still_wins_over_a_later_one(tmp_path):
    path = _write_xlsx(
        tmp_path,
        [
            _row("02-03-2026", "Dividend", "USD", 24.00, "US0378331005", "Apple Inc"),
            _row("03-03-2026", "Valuta Debitering", "USD", -24.00, fx=1.1000),
            _row("20-03-2026", "Valuta Debitering", "USD", -10.00, fx=1.2000),
        ],
    )
    divs = dividend_parser.parse_dividends(path)
    assert divs[0]["net_eur"] == round(24.00 / 1.1000, 4)


def test_a_currency_with_no_rate_at_all_is_reported_not_just_dropped(tmp_path):
    path = _write_xlsx(
        tmp_path,
        [
            _row("02-03-2026", "Dividend", "USD", 24.00, "US0378331005", "Apple Inc"),
            _row("05-03-2026", "Dividend", "EUR", 30.00, "NL0010273215", "ASML"),
        ],
    )
    warnings = []
    divs = dividend_parser.parse_dividends(path, warnings=warnings)
    assert [d["isin"] for d in divs] == ["NL0010273215"]
    assert len(warnings) == 1
    assert warnings[0]["currency"] == "USD"
    assert warnings[0]["amount"] == 24.00


def test_two_tax_rows_equally_far_from_two_payments_do_not_pile_up(tmp_path):
    """Both landed on the first payment, which then read as heavily taxed while
    the second read as untaxed. The year total was right the whole time."""
    path = _write_xlsx(
        tmp_path,
        [
            _row("10-03-2026", "Dividend", "EUR", 100.00, "NL0009690239", "VanEck REIT"),
            _row("12-03-2026", "Dividend", "EUR", 60.00, "NL0009690239", "VanEck REIT"),
            _row("11-03-2026", "Dividendbelasting", "EUR", -15.00, "NL0009690239", "VanEck REIT"),
            _row("11-03-2026", "Dividendbelasting", "EUR", -9.00, "NL0009690239", "VanEck REIT"),
        ],
    )
    divs = dividend_parser.parse_dividends(path)
    by_date = {d["date"]: d for d in divs}
    assert by_date["2026-03-10"]["tax_eur"] == -15.0
    assert by_date["2026-03-12"]["tax_eur"] == -9.0
    assert round(sum(d["tax_eur"] for d in divs), 2) == -24.0


def test_a_nearer_payment_still_wins_over_an_untaxed_further_one(tmp_path):
    path = _write_xlsx(
        tmp_path,
        [
            _row("10-03-2026", "Dividend", "EUR", 100.00, "NL0009690239", "VanEck REIT"),
            _row("14-03-2026", "Dividend", "EUR", 60.00, "NL0009690239", "VanEck REIT"),
            _row("10-03-2026", "Dividendbelasting", "EUR", -15.00, "NL0009690239", "VanEck REIT"),
            _row("10-03-2026", "Dividendbelasting", "EUR", -9.00, "NL0009690239", "VanEck REIT"),
        ],
    )
    divs = dividend_parser.parse_dividends(path)
    by_date = {d["date"]: d for d in divs}
    # Both tax rows sit on the 10th; distance beats spreading them out.
    assert by_date["2026-03-10"]["tax_eur"] == -24.0
    assert by_date["2026-03-14"]["tax_eur"] == 0.0
