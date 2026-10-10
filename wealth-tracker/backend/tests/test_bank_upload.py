"""
/api/uploads/bank — bank exports from the Update panel, several at once.

Reading is pinned down in backend/tests/domain/test_bank_import_ing_saving.py.
Here: which accounts are added, which balances, that a second upload changes
nothing, that a bad file does not hold back the rest, and that net worth counts
the savings accounts.
"""

IBAN = "NL00INGB0000000001"

PAY_HEADER = ('"Date";"Name / Description";"Account";"Counterparty";"Code";'
              '"Debit/credit";"Amount (EUR)";"Transaction type";"Notifications";'
              '"Resulting balance";"Tag"')
SAVINGS_HEADER = ('"Date";"Description";"Account";"Account name";"Counterparty";"Debit/credit";'
             '"Amount";"Currency";"Transaction type";"Notifications";"Resulting balance"')
BALANCE_HEADER = '"Date";"Account";"Account name";"Currency";"Book balance"'


def _csv(header, *rows) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


# The current account, newest on top as ING delivers it. On the 20th first the
# supermarket (balance 500), then the salary (balance 3000): the closing balance
# is 3000.
PAY = _csv(
    PAY_HEADER,
    f'"20260220";"WERKGEVER B.V.";"{IBAN}";"NL02ABNA0123456789";"OV";"Credit";"2500,00";"Online Banking";"Salaris";"3.000,00";""',
    f'"20260220";"SUPERMARKT";"{IBAN}";"";"BA";"Debit";"42,50";"Payment terminal";"Card 001";"500,00";""',
    f'"20260219";"Oranje Spaarrekening";"{IBAN}";"";"GT";"Debit";"100,00";"Online Banking";"To Oranje spaarrekening";"542,50";""',
)


def _savings(date, number, direction, amount, balance, kind="Deposit"):
    counterparty = "" if kind == "Interest" else IBAN
    oms = "Interest" if kind == "Interest" else f"Transfer from current account {IBAN}"
    return (f'"{date}";"{oms}";"{number}";"savings account";"{counterparty}";"{direction}";'
            f'"{amount}";"EUR";"{kind}";"";"{balance}"')


SAVINGS = _csv(
    SAVINGS_HEADER,
    _savings("2026-08-25", "A 111-22233", "Credit", "350,00", "1.350,00"),
    _savings("2026-08-25", "A 111-22233", "Debit", "100,00", "1.000,00", kind="Withdrawal"),
    _savings("2026-07-01", "A 111-22233", "Credit", "1,10", "1.100,00", kind="Interest"),
    _savings("2026-08-20", "B 444-55566", "Credit", "50,00", "50,00"),
)

OVERVIEW = _csv(
    BALANCE_HEADER,
    '"2026-09-03";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"',
    '"2026-09-02";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"',
    '"2026-09-01";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"',
    '"2026-08-25";"A11122233";"Oranje Spaarrekening";"EUR";"1.350,00"',
    '"2026-08-24";"A11122233";"Oranje Spaarrekening";"EUR";"1.100,00"',
    '"2026-08-23";"A11122233";"Oranje Spaarrekening";"EUR";"1.100,00"',
    '"2026-09-03";"B44455566";"Oranje Spaarrekening";"EUR";"50,00"',
    '"2026-08-20";"B44455566";"Oranje Spaarrekening";"EUR";"50,00"',
    '"2026-08-19";"B44455566";"Oranje Spaarrekening";"EUR";"0,00"',
)


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload(client, *files: tuple[str, bytes]):
    r = client.post("/api/uploads/bank",
                    files=[("files", (name, content, "text/csv")) for name, content in files])
    assert r.status_code == 200, r.text
    return {x["file"]: x for x in r.json()["results"]}


def _accounts(client) -> list[dict]:
    return client.get("/api/accounts").json()["accounts"]


def _balances(client, account_id) -> dict[str, float]:
    return {s["date"]: s["balance"] for s in client.get(f"/api/accounts/{account_id}/balances").json()["balances"]}


def _savings_account(client, final: str) -> dict:
    return next(r for r in _accounts(client) if r["name"].endswith(final))


# ---------------------------------------------------------------------------

def test_without_a_session_nothing(client):
    r = client.post("/api/uploads/bank", files=[("files", ("x.csv", PAY, "text/csv"))])
    assert r.status_code == 401


def test_three_files_at_once(client):
    _login(client)
    res = _upload(client, ("pay.csv", PAY), ("savings.csv", SAVINGS), ("balances.csv", OVERVIEW))
    assert not any("error" in v for v in res.values())
    assert res["balances.csv"]["kind"] == "balances"
    assert res["savings.csv"]["saved"] == 4
    # One current account and two savings accounts, each once.
    assert len(_accounts(client)) == 3


def test_each_savings_account_gets_its_own_account_with_the_last_digits(client):
    _login(client)
    _upload(client, ("balances.csv", OVERVIEW))
    names = sorted(r["name"] for r in _accounts(client))
    assert names == ["Oranje Spaarrekening ···2233", "Oranje Spaarrekening ···5566"]


def test_the_balance_overview_stores_only_the_changes_and_the_last_day(client):
    _login(client)
    _upload(client, ("balances.csv", OVERVIEW))
    a = _balances(client, _savings_account(client, "2233")["id"])
    assert a == {"2026-08-23": 1100.0, "2026-08-25": 1350.0, "2026-09-03": 1350.0}
    b = _balances(client, _savings_account(client, "5566")["id"])
    assert b == {"2026-08-19": 0.0, "2026-08-20": 50.0, "2026-09-03": 50.0}


def test_the_balance_after_the_last_booking_of_the_day_counts(client):
    _login(client)
    _upload(client, ("pay.csv", PAY))
    pay = next(r for r in _accounts(client) if r["iban"] == IBAN)
    assert _balances(client, pay["id"]) == {"2026-02-19": 542.5, "2026-02-20": 3000.0}
    assert pay["balance"] == 3000.0


def test_savings_transactions_and_overview_complement_each_other(client):
    _login(client)
    _upload(client, ("savings.csv", SAVINGS), ("balances.csv", OVERVIEW))
    a = _balances(client, _savings_account(client, "2233")["id"])
    assert a["2026-07-01"] == 1100.0          # only from the transactions
    assert a["2026-08-23"] == 1100.0          # only from the overview
    assert a["2026-08-25"] == 1350.0          # from both, and they agree


def test_uploading_again_changes_nothing(client):
    _login(client)
    files = (("pay.csv", PAY), ("savings.csv", SAVINGS), ("balances.csv", OVERVIEW))
    _upload(client, *files)
    before = {r["id"]: _balances(client, r["id"]) for r in _accounts(client)}
    second = _upload(client, *files)
    assert second["savings.csv"]["saved"] == 0 and second["pay.csv"]["saved"] == 0
    assert len(_accounts(client)) == 3
    assert {r["id"]: _balances(client, r["id"]) for r in _accounts(client)} == before


def test_a_bad_file_does_not_hold_back_the_rest(client):
    _login(client)
    res = _upload(client, ("rommel.csv", b"a,b,c\n1,2,3\n"), ("balances.csv", OVERVIEW))
    assert "error" in res["rommel.csv"]
    assert res["balances.csv"]["balances"] == 6


def test_transfers_to_the_current_account_are_internal_even_if_it_comes_later(client):
    """First the savings accounts, only then the current account: as soon as that IBAN
    is known, the savings transfers are no longer spending or income.
    """
    _login(client)
    _upload(client, ("savings.csv", SAVINGS))
    _upload(client, ("pay.csv", PAY))
    savings_ids = {r["id"] for r in _accounts(client) if r["iban"] is None}
    rows = [t for t in client.get("/api/bank-transactions").json()["transactions"]
             if t["account_id"] in savings_ids and t["name"] != "Interest"]
    assert rows and all(t["type"] == "INTERNAL" for t in rows)


def test_interest_on_a_savings_account_is_income(client):
    _login(client)
    _upload(client, ("savings.csv", SAVINGS))
    interest = next(t for t in client.get("/api/bank-transactions").json()["transactions"] if t["name"] == "Interest")
    assert interest["type"] == "INCOME"


def test_net_worth_counts_the_savings_accounts(client):
    _login(client)
    _upload(client, ("pay.csv", PAY), ("savings.csv", SAVINGS), ("balances.csv", OVERVIEW))
    assert client.get("/api/net-worth").json()["now"]["bank"] == 3000.0 + 1350.0 + 50.0


def test_everyone_their_own_accounts(client):
    _login(client)
    _upload(client, ("balances.csv", OVERVIEW))
    client.post("/api/auth/logout")
    _login(client, "bob", "bobpw")
    assert _accounts(client) == []
