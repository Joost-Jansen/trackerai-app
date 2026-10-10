"""
An account uploaded later makes the transfers to it internal.

On real data: a bunq account got money from another bunq account in the user's
own name ("J. de Vries"). As long as that other account was not in the app, the
rule for private persons recognised that as "received from friends" — income.
After uploading that account only the transfers that were still unknown
became internal; those with a category stayed income, together well over
eleven thousand euros.

Made-up IBANs and names.
"""

BUNQ_HEADER = '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"'

SAVINGS = "NL00BUNQ0000000040"
PAY = "NL00BUNQ0000000009"
UNKNOWN_ELSEWHERE = "NL00BUNQ0000000018"


def _csv(*rows) -> bytes:
    return ("\n".join([BUNQ_HEADER, *rows]) + "\n").encode("utf-8")


def _row(date, amount, account, counterparty, name, oms=""):
    return f'"{date}","{date}","{amount}","{account}","{counterparty}","{name}","{oms}"'


SAVINGS_ACCOUNT = _csv(
    _row("2025-11-30", "9.553,88", SAVINGS, PAY, "A. Voorbeeld"),
    _row("2026-02-25", "1.674,02", SAVINGS, PAY, "A. Voorbeeld"),
    _row("2025-12-30", "9,89", SAVINGS, UNKNOWN_ELSEWHERE, "A. Voorbeeld"),
)
CURRENT_ACCOUNT = _csv(_row("2026-09-04", "-7,99", PAY, "", "WINKEL 1 BV", "WINKEL 1"))


def _login(client, user="alice", pw="alicepw"):
    assert client.post("/api/auth/login", json={"username": user, "password": pw}).status_code == 200


def _upload(client, name, content):
    r = client.post("/api/uploads/bank", files=[("files", (name, content, "text/csv"))])
    assert r.status_code == 200, r.text
    assert "error" not in r.json()["results"][0], r.text


def _on_counterparty(client) -> dict[str, list[dict]]:
    off: dict[str, list[dict]] = {}
    for t in client.get("/api/bank-transactions").json()["transactions"]:
        off.setdefault(t["counterparty_iban"] or "", []).append(t)
    return off


def test_at_first_money_from_an_unknown_account_is_income(client):
    _login(client)
    _upload(client, "savings.csv", SAVINGS_ACCOUNT)
    assert all(t["type"] == "INCOME" for t in _on_counterparty(client)[PAY])


def test_after_uploading_that_account_it_is_internal(client):
    _login(client)
    _upload(client, "savings.csv", SAVINGS_ACCOUNT)
    _upload(client, "pay.csv", CURRENT_ACCOUNT)
    rows = _on_counterparty(client)[PAY]
    assert len(rows) == 2
    assert all(t["type"] == "INTERNAL" for t in rows)


def test_a_counterparty_not_known_yet_stays_as_it_was(client):
    _login(client)
    _upload(client, "savings.csv", SAVINGS_ACCOUNT)
    _upload(client, "pay.csv", CURRENT_ACCOUNT)
    assert _on_counterparty(client)[UNKNOWN_ELSEWHERE][0]["type"] == "INCOME"


def test_labelling_new_reports_the_coverage_of_everything(client):
    """Not of the handful of rows this round went through: those are exactly the unknown ones."""
    _login(client)
    _upload(client, "savings.csv", SAVINGS_ACCOUNT)
    _upload(client, "pay.csv", CURRENT_ACCOUNT)
    everything = client.get("/api/bank-transactions").json()["transactions"]
    unknown = sum(1 for t in everything if t["category"] in (None, "Onbekend"))

    report = client.post("/api/categories/relabel").json()
    assert report["unknown"] == unknown
    assert report["coverage"] == round((len(everything) - unknown) / len(everything) * 100, 1)


def test_a_category_you_set_yourself_stays(client):
    _login(client)
    _upload(client, "savings.csv", SAVINGS_ACCOUNT)
    first = _on_counterparty(client)[PAY][0]
    r = client.put(f"/api/bank-transactions/{first['id']}/category", json={"category": "Salaris"})
    assert r.status_code == 200, r.text

    _upload(client, "pay.csv", CURRENT_ACCOUNT)
    after = next(t for t in _on_counterparty(client)[PAY] if t["id"] == first["id"])
    assert after["category"] == "Salaris" and after["type"] == "INCOME"
