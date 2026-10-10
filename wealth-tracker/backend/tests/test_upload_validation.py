"""
Upload validation: what the sheet tells you when a file is wrong.

Background — the mobile bug this came from. The file input used to carry
accept=".xlsx", which greyed out the DeGiro export in the iOS Files picker:
DeGiro writes a technically sloppy package ([Content_Types].xml is not the
first zip part, no default styles), so iOS never types it as a spreadsheet,
and unlike desktop there is no "show all files" escape. The filter is gone,
which means the backend is now the only thing standing between a stray file
and a silent no-op — hence these tests.

The first one is the regression guard that matters: a real DeGiro export,
warts and all, must keep importing.
"""

import io
import os

import openpyxl
import pytest

from domain import database


def _xlsx(headers: list[str], rows: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


_TRANSACTION_HEADERS = [
    "Datum", "Tijd", "Product", "ISIN", "Beurs", "Uitvoeringsplaats", "Aantal",
    "Koers", "Unnamed: 8", "Lokale waarde", "Unnamed: 10", "Waarde EUR",
    "Wisselkoers", "AutoFX Kosten", "Transactiekosten en/of kosten van derden EUR",
    "Totaal EUR", "Order ID",
]
_TRANSACTION_ROW = [
    "11-06-2026", "10:31", "ISHARES CORE EURO STOXX 50", "IE0008471009", "EAM",
    "XAMS", 9, 62.02, "EUR", -558.18, "EUR", -558.18, None, 0.0, -3.0, -561.18,
    "8578dd38-aaad-4656-8837-a3ce43031ea7",
]

# The account statement shares Datum/Product/ISIN with the transaction export;
# only Omschrijving vs Aantal tells them apart.
_ACCOUNT_HEADERS = [
    "Datum", "Tijd", "Valutadatum", "Product", "ISIN", "Omschrijving", "FX",
    "Mutatie", "Unnamed: 8", "Saldo", "Unnamed: 10", "Order Id",
]


def _login(client):
    client.post("/api/auth/login", json={"username": "alice", "password": "alicepw"})


def _post(client, endpoint: str, filename: str, payload: bytes):
    return client.post(f"/api/uploads/{endpoint}", files={"files": (filename, payload)})


def test_a_real_degiro_export_still_imports(client):
    """The whole point of dropping the accept filter: this file must work."""
    real = os.path.join(os.path.dirname(database.__file__), "uploads", "Transactions (7).xlsx")
    if not os.path.exists(real):
        pytest.skip("no real DeGiro export checked out to test against")

    _login(client)
    with open(real, "rb") as f:
        resp = _post(client, "transactions", "Transactions.xlsx", f.read())

    assert resp.status_code == 200
    assert resp.json()["results"][0]["saved"] == 1


def test_the_name_ios_gives_a_second_download_still_parses(client):
    """
    Safari on iOS appends the duplicate counter *after* the extension, so a
    re-downloaded export arrives as "Transactions.xlsx 2" — a name that ends
    in no extension at all. pandas sniffs the content rather than the name,
    and nothing here may start deciding by extension instead.
    """
    _login(client)
    resp = _post(client, "transactions", "Transactions.xlsx 2",
                 _xlsx(_TRANSACTION_HEADERS, [_TRANSACTION_ROW]))

    assert resp.status_code == 200
    assert resp.json()["results"][0]["saved"] == 1


def test_a_file_that_is_not_a_spreadsheet_says_so(client):
    _login(client)
    resp = _post(client, "transactions", "Transactions.xlsx", b"<html>not a spreadsheet</html>")

    assert resp.status_code == 422
    assert "kan ik niet openen" in resp.json()["detail"]


def test_the_account_statement_in_the_transactions_slot_is_named(client):
    """The two DeGiro exports look alike; uploading the wrong one is easy."""
    _login(client)
    resp = _post(client, "transactions", "Account.xlsx", _xlsx(_ACCOUNT_HEADERS, []))

    assert resp.status_code == 422
    assert "transactieoverzicht" in resp.json()["detail"]


def test_the_transaction_export_in_the_dividend_slot_is_named(client):
    _login(client)
    resp = _post(client, "dividends", "Transactions.xlsx",
                 _xlsx(_TRANSACTION_HEADERS, [_TRANSACTION_ROW]))

    assert resp.status_code == 422
    assert "rekeningoverzicht" in resp.json()["detail"]


def test_an_export_with_no_rows_is_accepted_not_rejected(client):
    """A quiet month is not an error — it imports zero rows and says so."""
    _login(client)
    resp = _post(client, "transactions", "Transactions.xlsx", _xlsx(_TRANSACTION_HEADERS, []))

    assert resp.status_code == 200
    assert resp.json()["results"][0] == {
        "filename": "Transactions.xlsx", "saved": 0, "skipped": 0, "unparsed": [],
    }


def test_a_rejected_file_does_not_count_as_an_import(client):
    """
    prices_status dates "last import" from the newest file in the upload
    dir, so a rejected upload left on disk would claim an import that never
    happened.
    """
    _login(client)
    assert client.get("/api/prices/status").json()["last_import"] is None

    _post(client, "transactions", "Transactions.xlsx", b"not a spreadsheet at all")

    assert client.get("/api/prices/status").json()["last_import"] is None
    assert os.listdir(database.user_upload_dir("alice")) == []


def test_a_traversing_filename_cannot_escape_the_upload_dir(client):
    """The browser picks the filename, and iOS hands over odd ones."""
    _login(client)
    resp = _post(client, "transactions", "../../../../evil.xlsx",
                 _xlsx(_TRANSACTION_HEADERS, [_TRANSACTION_ROW]))

    assert resp.status_code == 200
    assert resp.json()["results"][0]["filename"] == "evil.xlsx"
    # Stored inside the upload dir (and deleted after the import, S3), never above it.
    root = database.data_root()
    found = [os.path.join(d, f) for d, _, files in os.walk(os.path.dirname(root)) for f in files if f == "evil.xlsx"]
    assert found == []


def test_csv_upload_and_duplicate(client):
    import csv
    _login(client)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(_TRANSACTION_HEADERS)
    writer.writerow([str(v).replace(".", ",") if isinstance(v, float) else v for v in _TRANSACTION_ROW])
    payload = stream.getvalue().encode("utf-8-sig")
    first = _post(client, "transactions", "Transactions.csv", payload)
    assert first.status_code == 200, first.text
    assert first.json()["results"][0]["saved"] == 1
    second = _post(client, "transactions", "Transactions.csv", payload)
    assert second.status_code == 200
    assert second.json()["results"][0]["saved"] == 0
    assert second.json()["results"][0]["skipped"] == 1
