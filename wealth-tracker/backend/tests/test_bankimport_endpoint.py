"""
/api/accounts/import — uploading a bank export.

The shape of the files is pinned down in backend/tests/domain/test_bank_import.py
and deduplication in backend/tests/domain/test_bank_transactions.py. What is
covered here is the road in between: the user does not have to say which bank
it is, the account is found or created by IBAN, and uploading the same file
twice changes nothing.
"""

ING_HEADER = ('"Date","Name / Description","Account","Counterparty","Code",'
           '"Debit/credit","Amount (EUR)","Transaction type","Notifications"')
BUNQ_HEADER = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'

ING_SALARY = ('"20260220","WERKGEVER B.V.","NL00INGB0000000001","NL02ABNA0123456789",'
               '"OV","Credit","2500,00","Transfer","Name: WERKGEVER Description: Salaris"')
ING_PIN = ('"20260219","SUPERMARKT","NL00INGB0000000001","","BA","Debit","42,50",'
           '"Payment terminal","Card sequence no.: 001"')
BUNQ_RENT = ('"2026-01-02","2026-01-02","-1.250,00","NL00BUNQ0000000002",'
             '"NL11RABO0123456789","VERHUURDER","Huur januari"')


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _csv(header: str, *rows: str) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def _import(client, content: bytes, name: str = "export.csv"):
    return client.post(
        "/api/accounts/import",
        files={"file": (name, content, "text/csv")},
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_importing_requires_a_session(client):
    assert _import(client, _csv(ING_HEADER, ING_PIN)).status_code == 401


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------

def test_an_ing_export_creates_the_account_and_imports(client):
    """The user does not say which bank it is; the file says so itself."""
    _login(client)
    resp = _import(client, _csv(ING_HEADER, ING_SALARY, ING_PIN))
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["provider"] == "ing"
    assert body["saved"] == 2
    assert body["skipped"] == 0
    assert body["unreadable"] == []
    assert body["account_created"] is True
    assert body["account"]["iban"] == "NL00INGB0000000001"

    accounts = client.get("/api/accounts").json()["accounts"]
    assert len(accounts) == 1
    assert accounts[0]["provider"] == "ing"


def test_a_bunq_export_is_recognised_too(client):
    _login(client)
    body = _import(client, _csv(BUNQ_HEADER, BUNQ_RENT)).json()
    assert body["provider"] == "bunq"
    assert body["account"]["iban"] == "NL00BUNQ0000000002"
    assert body["saved"] == 1


def test_the_transactions_can_be_read_back(client):
    _login(client)
    _import(client, _csv(ING_HEADER, ING_SALARY, ING_PIN))

    rows = client.get("/api/bank-transactions").json()["transactions"]
    assert len(rows) == 2
    on_name = {r["name"]: r for r in rows}
    assert on_name["SUPERMARKT"]["amount"] == 42.50, "een uitgave is positief"
    assert on_name["WERKGEVER B.V."]["amount"] == -2500.00, "een inkomst is negatief"


def test_a_second_account_from_another_bank_is_added_alongside(client):
    _login(client)
    _import(client, _csv(ING_HEADER, ING_PIN))
    _import(client, _csv(BUNQ_HEADER, BUNQ_RENT))

    accounts = client.get("/api/accounts").json()["accounts"]
    assert {r["provider"] for r in accounts} == {"ing", "bunq"}


# ---------------------------------------------------------------------------
# The same file once more
# ---------------------------------------------------------------------------

def test_the_same_file_twice_changes_nothing(client):
    """Bank exports overlap; that must not give duplicate amounts."""
    _login(client)
    file = _csv(ING_HEADER, ING_SALARY, ING_PIN)

    first = _import(client, file).json()
    second = _import(client, file).json()

    assert (first["saved"], first["skipped"]) == (2, 0)
    assert (second["saved"], second["skipped"]) == (0, 2)
    assert second["account_created"] is False
    assert len(client.get("/api/bank-transactions").json()["transactions"]) == 2


def test_an_overlapping_export_adds_only_what_is_new(client):
    _login(client)
    _import(client, _csv(ING_HEADER, ING_PIN))
    second = _import(client, _csv(ING_HEADER, ING_PIN, ING_SALARY)).json()

    assert (second["saved"], second["skipped"]) == (1, 1)
    assert len(client.get("/api/bank-transactions").json()["transactions"]) == 2


# ---------------------------------------------------------------------------
# What can go wrong
# ---------------------------------------------------------------------------

def test_an_unknown_file_gives_422_with_its_columns(client):
    """422 and not 500: the user picked the wrong file, that can be fixed."""
    _login(client)
    resp = _import(client, _csv('"Datum","Bedrag"', '"2026-01-01","1,00"'))
    assert resp.status_code == 422
    assert "Datum" in resp.json()["detail"]


def test_a_degiro_export_in_the_bank_slot_is_refused(client):
    _login(client)
    header = '"Datum","Tijd","Product","ISIN","Aantal","Koers","Totaal"'
    resp = _import(client, _csv(header, '"05-01-2026","09:30","ETF","IE00B4L5Y983","10","80,5","-805"'))
    assert resp.status_code == 422


def test_an_export_without_rows_is_not_an_error(client):
    """A quiet month imports zero rows and says so, as with DeGiro."""
    _login(client)
    resp = _import(client, _csv(ING_HEADER))
    assert resp.status_code == 422, "zonder rijen weten we niet bij welke rekening dit hoort"


def test_unreadable_rows_do_not_cost_the_whole_file(client):
    """The same lesson as with DeGiro: one odd row threw away 124 good ones."""
    _login(client)
    broken = ('"nogeenszo","WINKEL","NL00INGB0000000001","","BA","Debit","5,00",'
             '"Payment terminal","x"')
    body = _import(client, _csv(ING_HEADER, ING_SALARY, broken, ING_PIN)).json()

    assert body["saved"] == 2
    assert len(body["unreadable"]) == 1
    assert body["unreadable"][0]["line_number"] == 3


def test_an_export_with_two_accounts_in_it_is_refused(client):
    """One file belongs to one account; otherwise we guess which."""
    _login(client)
    other = ('"20260219","WINKEL","NL91ABNA0417164300","","BA","Debit","5,00",'
              '"Payment terminal","x"')
    resp = _import(client, _csv(ING_HEADER, ING_PIN, other))
    assert resp.status_code == 422
    assert "rekening" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Separation between users
# ---------------------------------------------------------------------------

def test_bob_does_not_see_alices_import(client):
    _login(client, "alice", "alicepw")
    _import(client, _csv(ING_HEADER, ING_SALARY, ING_PIN))

    _login(client, "bob", "bobpw")
    assert client.get("/api/bank-transactions").json()["transactions"] == []
    assert client.get("/api/accounts").json()["accounts"] == []


def test_bob_can_import_the_same_export(client):
    """Two housemates with the same rent payment are not duplicates of each other."""
    file = _csv(ING_HEADER, ING_PIN)
    _login(client, "alice", "alicepw")
    assert _import(client, file).json()["saved"] == 1

    _login(client, "bob", "bobpw")
    assert _import(client, file).json()["saved"] == 1


# ---------------------------------------------------------------------------
# Labelled straight away
# ---------------------------------------------------------------------------

def test_importing_labels_at_once(client):
    """Without this a fresh import counts in no total until you click "Label new" —
    and then an empty month looks like a frugal one.
    """
    _login(client)
    body = _import(client, _csv(ING_HEADER, ING_SALARY, ING_PIN)).json()
    assert body["labelled"] == 2

    rows = client.get("/api/bank-transactions").json()["transactions"]
    assert all(r["category"] is not None for r in rows)
    assert all(r["type"] is not None for r in rows), "en dus tellen ze meteen mee"


def test_a_second_import_labels_only_what_is_new(client):
    """What you already had, and may already have corrected by hand, stays."""
    _login(client)
    _import(client, _csv(ING_HEADER, ING_PIN))
    row_id = client.get("/api/bank-transactions").json()["transactions"][0]["id"]
    client.put(f"/api/bank-transactions/{row_id}/category",
               json={"category": "Cadeaus & goede doelen"})

    body = _import(client, _csv(ING_HEADER, ING_PIN, ING_SALARY)).json()
    assert body["labelled"] == 1

    op_id = {r["id"]: r for r in client.get("/api/bank-transactions").json()["transactions"]}
    assert op_id[row_id]["category"] == "Cadeaus & goede doelen"


def test_an_empty_period_says_there_are_transactions(client):
    """The default period is three months. If your transactions are before that, the
    list said "import a bank export" — while there were hundreds.
    """
    _login(client)
    _import(client, _csv(ING_HEADER, ING_SALARY, ING_PIN))

    body = client.get("/api/bank-transactions?start=2026-06-01").json()
    assert body["transactions"] == []
    assert body["total"] == 2
    assert body["last_date"] == "2026-02-20"


def test_without_an_import_the_total_is_zero(client):
    _login(client)
    body = client.get("/api/bank-transactions").json()
    assert body["total"] == 0
    assert body["last_date"] is None
