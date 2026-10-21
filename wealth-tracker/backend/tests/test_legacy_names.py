"""A database and auth config from before the English rename open under the new names."""

import json
import sqlite3

import yaml

from app.core import auth_store, config
from domain import database
from domain.money import accounts

OLD_SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE rekeningen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, soort TEXT NOT NULL, aanbieder TEXT NOT NULL, naam TEXT NOT NULL,
    iban TEXT, valuta TEXT NOT NULL DEFAULT 'EUR', extern_id TEXT, actief INTEGER NOT NULL DEFAULT 1,
    aangemaakt_op TEXT NOT NULL, UNIQUE(iban));
CREATE TABLE rekening_saldi (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rekening_id INTEGER NOT NULL REFERENCES rekeningen(id),
    datum TEXT NOT NULL, saldo REAL NOT NULL, bron TEXT NOT NULL, UNIQUE(rekening_id, datum));
CREATE TABLE bank_transacties (
    id INTEGER PRIMARY KEY AUTOINCREMENT, rekening_id INTEGER NOT NULL REFERENCES rekeningen(id),
    datum TEXT NOT NULL, rentedatum TEXT, bedrag REAL NOT NULL, valuta TEXT NOT NULL DEFAULT 'EUR',
    naam TEXT NOT NULL, tegenpartij_iban TEXT, omschrijving TEXT NOT NULL DEFAULT '', code TEXT, soort TEXT,
    categorie_auto TEXT, categorie_handmatig TEXT, type TEXT, dedup_hash TEXT NOT NULL, raw TEXT,
    bron TEXT NOT NULL DEFAULT 'import', categorie_bron TEXT, UNIQUE(dedup_hash));
CREATE INDEX idx_bank_transacties_datum ON bank_transacties(datum);
CREATE TABLE categorieen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, groep TEXT NOT NULL, naam TEXT NOT NULL, type TEXT NOT NULL,
    volgorde INTEGER NOT NULL DEFAULT 0, UNIQUE(naam));
CREATE TABLE bank_toestemmingen (
    id INTEGER PRIMARY KEY AUTOINCREMENT, bank TEXT NOT NULL, land TEXT NOT NULL, state TEXT UNIQUE,
    redirect_url TEXT, sessie_id TEXT, geldig_tot TEXT, status TEXT NOT NULL, fout TEXT,
    aangemaakt_op TEXT NOT NULL, laatst_opgehaald TEXT);
CREATE TABLE budgetten (groep TEXT PRIMARY KEY, bedrag REAL NOT NULL);
CREATE VIEW bank_transacties_getypeerd AS
    SELECT t.*, COALESCE(t.categorie_handmatig, t.categorie_auto) AS categorie_effectief, c.groep AS groep
    FROM bank_transacties t LEFT JOIN categorieen c ON c.naam = COALESCE(t.categorie_handmatig, t.categorie_auto);

INSERT INTO rekeningen (soort, aanbieder, naam, iban, aangemaakt_op) VALUES ('bank', 'ing', 'Betaalrekening', 'NL00DEMO0000000001', '2026-01-01');
INSERT INTO rekeningen (soort, aanbieder, naam, aangemaakt_op) VALUES ('contant', 'handmatig', 'Portemonnee', '2026-01-01');
INSERT INTO rekeningen (soort, aanbieder, naam, aangemaakt_op) VALUES ('schuld', 'handmatig', 'Studieschuld', '2026-01-01');
INSERT INTO rekening_saldi (rekening_id, datum, saldo, bron) VALUES (2, '2026-02-01', 40, 'handmatig');
INSERT INTO categorieen (groep, naam, type) VALUES ('Boodschappen', 'Supermarkt', 'UITGAVE');
INSERT INTO categorieen (groep, naam, type) VALUES ('Inkomsten', 'Salaris', 'INKOMSTEN');
INSERT INTO bank_transacties (rekening_id, datum, bedrag, naam, dedup_hash, categorie_auto, categorie_bron)
    VALUES (1, '2026-02-03', 25.5, 'ALBERT HEIJN', 'h1', 'Supermarkt', 'regel');
INSERT INTO bank_transacties (rekening_id, datum, bedrag, naam, dedup_hash, categorie_auto, categorie_bron, bron)
    VALUES (1, '2026-02-04', 12, 'Bakker', 'h2', 'Supermarkt', 'geleerd', 'handmatig');
INSERT INTO bank_toestemmingen (bank, land, status, aangemaakt_op) VALUES ('ING', 'NL', 'actief', '2026-01-01');
INSERT INTO budgetten (groep, bedrag) VALUES ('Boodschappen', 400);
INSERT INTO settings VALUES ('standaardregels_versie', '7');
INSERT INTO settings VALUES ('maandindeling', 'salaris');
INSERT INTO settings VALUES ('salarisdag', '24');
INSERT INTO settings VALUES ('voorkeur:ai_labelen', '{"aan": true}');
INSERT INTO settings VALUES ('voorkeur:uitgaven_overzicht', '{"versie": 4, "grafieken": [{"id": "koers", "zichtbaar": false, "inst": {}}]}');
INSERT INTO settings VALUES ('onboarding', '{"keuze": "allebei", "klaar": true, "stap": 2}');
"""


def _old_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(OLD_SCHEMA)
    return conn


def _settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def test_an_old_database_is_renamed_in_place():
    conn = _old_db()
    database.init_db(conn)

    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert {
        "accounts",
        "account_balances",
        "bank_transactions",
        "categories",
        "bank_consents",
        "budgets",
        "bank_transactions_typed",
    } <= tables
    assert not tables & {"rekeningen", "rekening_saldi", "bank_transacties", "categorieen", "bank_transacties_getypeerd"}

    assert [(a["name"], a["kind"], a["provider"]) for a in accounts.load_accounts(conn)] == [
        ("Betaalrekening", "bank", "ing"),
        ("Portemonnee", "cash", "manual"),
        ("Studieschuld", "debt", "manual"),
    ]
    assert conn.execute("SELECT source FROM account_balances").fetchone()[0] == "manual"
    rows = conn.execute(
        "SELECT name, source, category_source, group_name, type_effective FROM bank_transactions_typed ORDER BY id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("ALBERT HEIJN", "import", "rule", "Boodschappen", "EXPENSE"),
        ("Bakker", "manual", "learned", "Boodschappen", "EXPENSE"),
    ]
    assert conn.execute("SELECT type FROM categories WHERE name = 'Salaris'").fetchone()[0] == "INCOME"
    assert conn.execute("SELECT status FROM bank_consents").fetchone()[0] == "active"
    assert conn.execute("SELECT group_name, amount FROM budgets").fetchone()[:] == ("Boodschappen", 400)

    s = _settings(conn)
    assert s["default_rules_version"] == "7" and s["month_periods"] == "salary" and s["salary_day"] == "24"
    assert json.loads(s["preference:ai_labelling"]) == {"on": True}
    assert json.loads(s["preference:spending_overview"]) == {"version": 4, "charts": [{"id": "price", "visible": False, "inst": {}}]}
    assert json.loads(s["onboarding"]) == {"choice": "both", "done": True, "step": 2}
    assert not {"standaardregels_versie", "maandindeling", "salarisdag", "voorkeur:ai_labelen"} & set(s)


def test_migrating_twice_changes_nothing():
    conn = _old_db()
    database.init_db(conn)
    before = (_settings(conn), [tuple(r) for r in conn.execute("SELECT * FROM bank_transactions")])
    database.init_db(conn)
    assert (_settings(conn), [tuple(r) for r in conn.execute("SELECT * FROM bank_transactions")]) == before


def test_an_old_beta_flag_reads_under_its_new_name(tmp_path, monkeypatch):
    path = tmp_path / "auth_config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"credentials": {"usernames": {"anna": {}, "bob": {}}}, "beta": {"geldzaken": ["anna"], "money": ["bob"], "returns": ["anna"]}}
        )
    )
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))
    assert auth_store.load_config()["beta"] == {"money": ["bob", "anna"], "returns": ["anna"]}
    assert auth_store.has_beta("anna", "money")


def test_requests_that_open_an_old_database_together_do_not_trip_over_each_other(tmp_path):
    import threading

    path = tmp_path / "portfolio.db"
    setup = sqlite3.connect(path)
    setup.executescript(OLD_SCHEMA)
    setup.close()
    errors, start = [], threading.Barrier(6)

    def open_it():
        conn = sqlite3.connect(path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        start.wait()
        try:
            database.init_db(conn)
            conn.execute("SELECT kind FROM accounts").fetchall()
        except Exception as e:  # noqa: BLE001 — the test collects them
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=open_it) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_an_old_token_scope_reads_under_its_new_name(tmp_path, monkeypatch):
    path = tmp_path / "auth_config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"credentials": {"usernames": {"anna": {"agent_tokens": [{"id": "a", "scope": "lezen"}, {"id": "b", "scope": "bijhouden"}]}}}}
        )
    )
    monkeypatch.setattr(config, "AUTH_CONFIG_PATH", str(path))
    tokens = auth_store.load_config()["credentials"]["usernames"]["anna"]["agent_tokens"]
    assert [t["scope"] for t in tokens] == ["read", "write"]
