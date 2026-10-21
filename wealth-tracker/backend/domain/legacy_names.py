"""
legacy_names.py — brings a database from before the English rename up to date.

Until October 2026 the money tables, their columns, some stored codes and a few
settings keys were Dutch (rekeningen.soort = 'contant', categorieen.type =
'UITGAVE', ...). init_db() calls migrate() first, so an existing database on
the Pi or on Railway is renamed in place the first time the new code opens it.
Every step checks what is there, so running it again does nothing.
"""

import json
import sqlite3

TABLES = {
    "rekeningen": "accounts",
    "rekening_saldi": "account_balances",
    "bank_transacties": "bank_transactions",
    "ai_voorstellen": "ai_suggestions",
    "ai_controles": "ai_checks",
    "regel_voorstellen": "rule_suggestions",
    "categorieen": "categories",
    "rekening_mutaties": "account_entries",
    "bank_koppelingen": "bank_connections",
    "bank_toestemmingen": "bank_consents",
    "bank_toestemming_rekeningen": "bank_consent_accounts",
    "budgetten": "budgets",
    "vaste_lasten_keuze": "fixed_cost_choices",
    "schuld_schema": "debt_schedules",
    "regels": "rules",
}

COLUMNS = {
    "accounts": {
        "soort": "kind",
        "aanbieder": "provider",
        "naam": "name",
        "valuta": "currency",
        "extern_id": "external_id",
        "actief": "active",
        "aangemaakt_op": "created_at",
    },
    "account_balances": {"rekening_id": "account_id", "datum": "date", "saldo": "balance", "bron": "source"},
    "bank_transactions": {
        "rekening_id": "account_id",
        "datum": "date",
        "rentedatum": "interest_date",
        "bedrag": "amount",
        "valuta": "currency",
        "naam": "name",
        "tegenpartij_iban": "counterparty_iban",
        "omschrijving": "description",
        "soort": "kind",
        "categorie_auto": "category_auto",
        "categorie_handmatig": "category_manual",
        "bron": "source",
        "categorie_bron": "category_source",
    },
    "ai_suggestions": {
        "transactie_id": "transaction_id",
        "categorie": "category",
        "zekerheid": "confidence",
        "gemaakt_op": "created_at",
        "reden": "reason",
    },
    "ai_checks": {
        "transactie_id": "transaction_id",
        "categorie": "category",
        "zekerheid": "confidence",
        "huidig": "current",
        "besluit": "decision",
        "gemaakt_op": "created_at",
        "reden": "reason",
    },
    "rule_suggestions": {"sleutel": "key", "patroon": "pattern", "categorie": "category", "gemaakt_op": "created_at"},
    "categories": {"groep": "group_name", "naam": "name", "volgorde": "sort_order"},
    "account_entries": {"rekening_id": "account_id", "datum": "date", "bedrag": "amount", "omschrijving": "description", "sleutel": "key"},
    "bank_connections": {"aanbieder": "provider", "sleutel": "key", "aangemaakt_op": "created_at"},
    "bank_consents": {
        "land": "country",
        "sessie_id": "session_id",
        "geldig_tot": "valid_until",
        "fout": "error",
        "aangemaakt_op": "created_at",
        "laatst_opgehaald": "last_fetched",
    },
    "bank_consent_accounts": {"toestemming_id": "consent_id", "rekening_id": "account_id"},
    "budgets": {"groep": "group_name", "bedrag": "amount"},
    "fixed_cost_choices": {"sleutel": "key", "vast": "is_fixed"},
    "debt_schedules": {"rekening_id": "account_id", "rente": "interest", "aflossing": "repayment", "vanaf": "from_date"},
    "rules": {
        "prio": "priority",
        "veld": "field",
        "patroon": "pattern",
        "richting": "direction",
        "categorie": "category",
        "actief": "active",
    },
}

INDEXES = {"idx_bank_transacties_datum": "idx_bank_transactions_date"}

VIEWS = ("bank_transacties_getypeerd",)

# Stored codes per column: old value -> new value.
VALUES = {
    ("accounts", "kind"): {"contant": "cash", "handmatig": "manual", "schuld": "debt"},
    ("accounts", "provider"): {"handmatig": "manual"},
    ("account_balances", "source"): {"handmatig": "manual"},
    ("bank_transactions", "source"): {"handmatig": "manual"},
    ("bank_transactions", "category_source"): {"regel": "rule", "geleerd": "learned"},
    ("bank_transactions", "type"): {"UITGAVE": "EXPENSE", "INKOMSTEN": "INCOME", "INTERN": "INTERNAL"},
    ("categories", "type"): {"UITGAVE": "EXPENSE", "INKOMSTEN": "INCOME", "INTERN": "INTERNAL"},
    ("bank_consents", "status"): {"wacht": "waiting", "actief": "active", "verlopen": "expired", "fout": "error"},
    ("ai_checks", "decision"): {"voorstel": "suggestion", "origineel": "original", "anders": "otherwise"},
    ("rule_suggestions", "status"): {"aangenomen": "accepted", "afgewezen": "rejected"},
}

SETTINGS_KEYS = {
    "standaardregels_versie": "default_rules_version",
    "categorie_hernoemd": "category_renamed",
    "maandindeling": "month_periods",
    "salarisdag": "salary_day",
    "salariscategorie": "salary_category",
    "voorkeur:uitgaven_overzicht": "preference:spending_overview",
    "voorkeur:ai_labelen": "preference:ai_labelling",
}
SETTINGS_VALUES = {"month_periods": {"kalender": "calendar", "salaris": "salary"}}

# JSON stored in settings: keys and string values renamed recursively.
_ONBOARDING = {"keuze": "choice", "klaar": "done", "stap": "step", "beleggingen": "investments", "geldzaken": "money", "allebei": "both"}
_SPENDING = {
    "versie": "version",
    "grafieken": "charts",
    "zichtbaar": "visible",
    "koers": "price",
    "maand": "month",
    "groep": "group_name",
    "verdeling": "distribution",
    "vastvariabel": "fixed_variable",
    "wanneer": "when",
    "vastelasten": "fixedcosts",
    "inkomsten": "income",
    "alle": "all",
}
_AI = {"aan": "on"}
JSON_SETTINGS = {"onboarding": _ONBOARDING, "preference:spending_overview": _SPENDING, "preference:ai_labelling": _AI}


def _exists(conn: sqlite3.Connection, kind: str, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?", (kind, name)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _rename_json(value, words: dict):
    if isinstance(value, dict):
        return {words.get(k, k): _rename_json(v, words) for k, v in value.items()}
    if isinstance(value, list):
        return [_rename_json(v, words) for v in value]
    if isinstance(value, str):
        return words.get(value, value)
    return value


def _needed(conn: sqlite3.Connection) -> bool:
    return any(_exists(conn, "table", old) for old in TABLES) or _needs_values(conn)


def migrate(conn: sqlite3.Connection) -> None:
    """Renames what is still Dutch. A no-op on a new or already migrated database.

    The first requests after an update arrive together, each opening the
    database: the write lock makes one of them do the work and the others find
    nothing left to do."""
    if not _needed(conn):
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        if _needed(conn):
            _migrate(conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate(conn: sqlite3.Connection) -> None:
    for view in VIEWS:
        conn.execute(f'DROP VIEW IF EXISTS "{view}"')  # init_db() recreates it under its new name
    for old, new in TABLES.items():
        if _exists(conn, "table", old) and not _exists(conn, "table", new):
            conn.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
    for table, renames in COLUMNS.items():
        if not _exists(conn, "table", table):
            continue
        present = _columns(conn, table)
        for old, new in renames.items():
            if old in present and new not in present:
                conn.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
    for old in INDEXES:
        conn.execute(f'DROP INDEX IF EXISTS "{old}"')  # init_db() creates the new one
    _migrate_values(conn)


def _needs_values(conn: sqlite3.Connection) -> bool:
    if not _exists(conn, "table", "settings"):
        return False
    keys = list(SETTINGS_KEYS)
    if conn.execute(f"SELECT 1 FROM settings WHERE key IN ({','.join('?' * len(keys))})", keys).fetchone():
        return True
    return conn.execute("SELECT 1 FROM settings WHERE key = 'onboarding' AND value LIKE '%\"keuze\"%'").fetchone() is not None


def _migrate_values(conn: sqlite3.Connection) -> None:
    for (table, column), mapping in VALUES.items():
        if not _exists(conn, "table", table) or column not in _columns(conn, table):
            continue
        for old, new in mapping.items():
            conn.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE "{column}" = ?', (new, old))
    if not _exists(conn, "table", "settings"):
        return
    for old, new in SETTINGS_KEYS.items():
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (old,)).fetchone()
        if row is None:
            continue
        conn.execute("DELETE FROM settings WHERE key = ?", (old,))
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (new, row[0]))
    for key, mapping in SETTINGS_VALUES.items():
        for old, new in mapping.items():
            conn.execute("UPDATE settings SET value = ? WHERE key = ? AND value = ?", (new, key, old))
    for key, words in JSON_SETTINGS.items():
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None or not row[0]:
            continue
        try:
            value = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        renamed = _rename_json(value, words)
        if renamed != value:
            conn.execute("UPDATE settings SET value = ? WHERE key = ?", (json.dumps(renamed, ensure_ascii=False), key))
