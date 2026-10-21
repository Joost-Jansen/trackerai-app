"""
Tests for database.py — in particular, that per-user data is fully isolated
now that there's no ambient "current user" state (see database.py's module
docstring). Every test points database._HERE at a temp directory so nothing
touches the real data/ folder.
"""

import os
import sqlite3
import threading

import pytest

from domain import database

# About SQLite itself (its files, WAL, locks, threads): not run when the suite runs on Postgres (WEALTH_DATABASE_URL).
sqlite_only = pytest.mark.skipif(bool(os.environ.get("WEALTH_DATABASE_URL")), reason="about SQLite itself")


@pytest.fixture(autouse=True)
def _isolated_data_root(tmp_path, monkeypatch):
    """Redirect database._HERE so tests never touch the real data/ folder."""
    monkeypatch.setattr(database, "_HERE", str(tmp_path))


def _new_conn(username: str) -> sqlite3.Connection:
    conn = database.connect(username)
    database.init_db(conn)
    return conn


# ---------------------------------------------------------------------------
# Basic plumbing
# ---------------------------------------------------------------------------


def test_safe_user_rejects_path_traversal():
    with pytest.raises(ValueError):
        database._safe_user("../../etc")
    with pytest.raises(ValueError):
        database._safe_user("")
    with pytest.raises(ValueError):
        database._safe_user("a" * 41)
    assert database._safe_user("alice_1") == "alice_1"


def test_connect_rejects_unsafe_username(tmp_path):
    with pytest.raises(ValueError):
        database.connect("../evil")


@sqlite_only
def test_connect_defaults_to_rejecting_cross_thread_use():
    """The default must keep sqlite3's guard, so opting out stays a decision."""
    conn = database.connect("alice")
    errors: list[Exception] = []

    def touch():
        try:
            conn.execute("SELECT 1")
        except Exception as e:  # noqa: BLE001 - the point is which one
            errors.append(e)

    t = threading.Thread(target=touch)
    t.start()
    t.join()
    conn.close()
    assert errors and isinstance(errors[0], sqlite3.ProgrammingError)


def test_connect_can_allow_cross_thread_use():
    """Both real callers hand a connection between threads and depend on this.

    app.py caches one in st.session_state while Streamlit runs every rerun on a
    fresh thread; backend/app/deps.py yields one from a threadpool task whose
    teardown may land on another. Neither ever has two threads on it at once —
    this only lifts sqlite3's owning-thread check, and both broke without it.
    """
    conn = database.connect("alice", same_thread_only=False)
    database.init_db(conn)
    results: list[int] = []
    errors: list[Exception] = []

    def touch():
        try:
            results.append(conn.execute("SELECT 1").fetchone()[0])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    for _ in range(3):  # a fresh thread each time, as a rerun would be
        t = threading.Thread(target=touch)
        t.start()
        t.join()

    # Closing from yet another thread is what actually raised in get_db.
    closer = threading.Thread(target=conn.close)
    closer.start()
    closer.join()

    assert not errors, errors
    assert results == [1, 1, 1]


def test_init_db_creates_expected_tables():
    conn = _new_conn("alice")
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cursor.fetchall()}
    assert {
        "transactions",
        "prices",
        "dividends",
        "asset_categories",
        "settings",
        "ticker_overrides",
        "etf_api_cache",
    } <= tables
    conn.close()


# ---------------------------------------------------------------------------
# CRUD round-trips
# ---------------------------------------------------------------------------


def test_settings_roundtrip_and_default():
    conn = _new_conn("alice")
    assert database.load_setting(conn, "missing_key", "fallback") == "fallback"
    database.save_setting(conn, "some_key", "secret123")
    assert database.load_setting(conn, "some_key") == "secret123"
    # overwrite
    database.save_setting(conn, "some_key", "new-value")
    assert database.load_setting(conn, "some_key") == "new-value"
    conn.close()


def test_ticker_override_roundtrip_and_delete():
    conn = _new_conn("alice")
    assert database.load_ticker_overrides(conn) == {}
    database.save_ticker_override(conn, "IE00B4L5Y983", "IWDA.AS")
    assert database.load_ticker_overrides(conn) == {"IE00B4L5Y983": "IWDA.AS"}
    database.delete_ticker_override(conn, "IE00B4L5Y983")
    assert database.load_ticker_overrides(conn) == {}
    conn.close()


def test_bond_isins_reads_both_spellings():
    """ "Bond" and "Bonds" both mean bonds, and a real database holds either.

    The Rebalancing tab saved "Bond" until it was rebuilt around "Stocks"/"Bonds"
    (5f136d3, 2026-07-16); the Benchmarks tab went on matching "Bond" alone, so
    its default-on "Exclude bond positions" checkbox excluded nothing and every
    benchmark line quietly included the bonds it claimed to leave out. Reading
    one spelling is the bug, not an implementation detail.
    """
    conn = _new_conn("alice")
    database.save_asset_category(conn, "OLD", "Bond")  # pre-rebuild row
    database.save_asset_category(conn, "NEW", "Bonds")  # post-rebuild row
    database.save_asset_category(conn, "EQ", "Stocks")

    assert database.bond_isins(conn) == {"OLD", "NEW"}
    conn.close()


def test_bond_isins_of_an_unclassified_portfolio_is_empty():
    conn = _new_conn("alice")
    assert database.bond_isins(conn) == set()
    conn.close()


def test_asset_category_upsert_preserves_broad_region():
    """save_asset_category must not reset broad_region set by save_broad_region."""
    conn = _new_conn("alice")
    database.save_broad_region(conn, "IE00B4L5Y983", "Europe")
    database.save_asset_category(conn, "IE00B4L5Y983", "Stocks")
    assert database.load_asset_categories(conn) == {"IE00B4L5Y983": "Stocks"}
    assert database.load_broad_regions(conn) == {"IE00B4L5Y983": "Europe"}
    conn.close()


def test_etf_api_cache_respects_max_age(monkeypatch):
    conn = _new_conn("alice")
    database.save_etf_api_cache(conn, "IWDA", '{"foo": "bar"}')
    assert database.load_etf_api_cache(conn, "IWDA", max_age_days=7) == '{"foo": "bar"}'

    # Backdate fetched_at beyond the TTL window.
    cursor = conn.cursor()
    cursor.execute("UPDATE etf_api_cache SET fetched_at = '2000-01-01T00:00:00' WHERE ticker = 'IWDA'")
    conn.commit()
    assert database.load_etf_api_cache(conn, "IWDA", max_age_days=7) is None

    database.clear_etf_api_cache(conn)
    assert database.load_etf_api_cache(conn, "IWDA", max_age_days=3650) is None
    conn.close()


# ---------------------------------------------------------------------------
# Generic remote-call cache (get_or_fetch)
# ---------------------------------------------------------------------------


def test_get_or_fetch_calls_once_then_serves_from_cache():
    conn = _new_conn("alice")
    calls = []

    def fetch():
        calls.append(1)
        return {"a": [1, 2, 3]}

    assert database.get_or_fetch(conn, "k", 3600, fetch) == {"a": [1, 2, 3]}
    assert database.get_or_fetch(conn, "k", 3600, fetch) == {"a": [1, 2, 3]}
    assert len(calls) == 1, "second call should have been served from the cache"
    conn.close()


def test_get_or_fetch_refetches_once_stale():
    conn = _new_conn("alice")
    calls = []

    def fetch():
        calls.append(1)
        return len(calls)

    assert database.get_or_fetch(conn, "k", 3600, fetch) == 1
    # ttl=0: the row is stale the instant it is written.
    assert database.get_or_fetch(conn, "k", 0, fetch) == 2
    assert len(calls) == 2
    conn.close()


def test_get_or_fetch_keys_are_independent():
    conn = _new_conn("alice")
    assert database.get_or_fetch(conn, "a", 3600, lambda: "first") == "first"
    assert database.get_or_fetch(conn, "b", 3600, lambda: "second") == "second"
    assert database.get_or_fetch(conn, "a", 3600, lambda: "ignored") == "first"
    conn.close()


def test_get_or_fetch_does_not_cache_a_failure():
    """One bad network moment must not pin an error for the whole TTL."""
    conn = _new_conn("alice")

    def tree():
        raise RuntimeError("yfinance is down")

    with pytest.raises(RuntimeError):
        database.get_or_fetch(conn, "k", 3600, tree)

    assert database.get_or_fetch(conn, "k", 3600, lambda: "recovered") == "recovered"
    conn.close()


def test_get_or_fetch_refetches_over_a_corrupt_row():
    conn = _new_conn("alice")
    database.get_or_fetch(conn, "k", 3600, lambda: {"ok": True})
    conn.execute("UPDATE api_cache SET payload = ? WHERE key = ?", ("{not json", "k"))
    conn.commit()

    assert database.get_or_fetch(conn, "k", 3600, lambda: {"ok": "again"}) == {"ok": "again"}
    conn.close()


def test_clear_api_cache_by_prefix_leaves_other_keys():
    conn = _new_conn("alice")
    database.get_or_fetch(conn, "benchmarks:2021", 3600, lambda: 1)
    database.get_or_fetch(conn, "other:thing", 3600, lambda: 2)

    database.clear_api_cache(conn, "benchmarks:")
    assert database.get_or_fetch(conn, "benchmarks:2021", 3600, lambda: 99) == 99  # re-fetched
    assert database.get_or_fetch(conn, "other:thing", 3600, lambda: 99) == 2  # untouched
    conn.close()


def test_save_transactions_dedup_and_reupload():
    conn = _new_conn("alice")
    txs = [
        {
            "order_ref": "abc",
            "date": "2026-01-05",
            "time": "09:00",
            "name": "iShares Core MSCI World",
            "isin": "IE00B4L5Y983",
            "exchange": "EAM",
            "execution_venue": "EAM",
            "transaction_type": "BUY",
            "quantity": 10.0,
            "price": 80.0,
            "local_value": -800.0,
            "value_eur": -800.0,
            "exchange_rate": 1.0,
            "autofx_cost": None,
            "transaction_fee": -1.0,
            "total_eur": -801.0,
        }
    ]
    saved, skipped = database.save_transactions(conn, txs)
    assert (saved, skipped) == (1, 0)

    # Re-uploading the same export is a no-op.
    saved2, skipped2 = database.save_transactions(conn, txs)
    assert (saved2, skipped2) == (0, 1)

    loaded = database.load_transactions(conn)
    assert len(loaded) == 1
    assert loaded[0]["isin"] == "IE00B4L5Y983"

    # A row without a date is unusable and must be skipped, not inserted.
    saved3, skipped3 = database.save_transactions(conn, [{"date": None, "isin": "X"}])
    assert (saved3, skipped3) == (0, 1)
    conn.close()


def test_save_dividends_dedup():
    conn = _new_conn("alice")
    div = {
        "date": "2026-02-01",
        "isin": "IE00B4L5Y983",
        "name": "iShares Core MSCI World",
        "currency_original": "EUR",
        "amount_original": 12.5,
        "gross_eur": 12.5,
        "tax_eur": -1.5,
        "net_eur": 11.0,
    }
    saved, skipped = database.save_dividends(conn, [div])
    assert (saved, skipped) == (1, 0)
    saved2, skipped2 = database.save_dividends(conn, [div])
    assert (saved2, skipped2) == (0, 1)  # re-uploading the same export is a no-op

    assert database.load_dividends_by_isin(conn) == {"IE00B4L5Y983": 11.0}
    conn.close()


def test_two_payments_of_one_size_on_one_day_are_both_kept():
    """Count-based, like save_transactions: a file contributes only the copies
    it has beyond what is stored. The UNIQUE constraint this replaced could not
    tell a second upload of one payment from a second payment, so it dropped
    the latter and left every dividend total short — while reporting it as a
    duplicate skipped, which reads as things having gone right."""
    conn = _new_conn("alice")
    div = {
        "date": "2026-02-01",
        "isin": "IE00B4L5Y983",
        "name": "iShares Core MSCI World",
        "currency_original": "EUR",
        "amount_original": 12.5,
        "gross_eur": 12.5,
        "tax_eur": 0.0,
        "net_eur": 12.5,
    }
    saved, skipped = database.save_dividends(conn, [div, dict(div)])
    assert (saved, skipped) == (2, 0)
    assert database.load_dividends_by_isin(conn) == {"IE00B4L5Y983": 25.0}

    # And re-uploading that same file still adds nothing.
    saved2, skipped2 = database.save_dividends(conn, [div, dict(div)])
    assert (saved2, skipped2) == (0, 2)
    assert database.load_dividends_by_isin(conn) == {"IE00B4L5Y983": 25.0}
    conn.close()


def test_an_existing_database_loses_the_unique_constraint_on_open():
    """The migration runs on init_db, like the transactions one before it."""
    conn = _new_conn("alice")
    conn.execute("DROP TABLE dividends")
    conn.execute("""
        CREATE TABLE dividends (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT    NOT NULL,
            isin              TEXT    NOT NULL,
            name              TEXT,
            currency_original TEXT,
            amount_original   REAL,
            gross_eur         REAL,
            tax_eur           REAL,
            net_eur           REAL    NOT NULL,
            UNIQUE(date, isin, amount_original, currency_original)
        )
    """)
    conn.execute("""
        INSERT INTO dividends (date, isin, name, currency_original,
                               amount_original, gross_eur, tax_eur, net_eur)
        VALUES ('2025-01-01', 'X', 'Old row', 'EUR', 5.0, 5.0, 0.0, 5.0)
    """)
    conn.commit()

    database.init_db(conn)

    # The row survived the rebuild, and the constraint is gone.
    assert database.load_dividends_by_isin(conn) == {"X": 5.0}
    cur = conn.cursor()
    cur.execute("PRAGMA index_list(dividends)")
    assert not any(i["origin"] == "u" and i["unique"] for i in cur.fetchall())
    conn.close()


# ---------------------------------------------------------------------------
# Cross-user isolation — the one bug class that must never regress now that
# there's no ambient "current user" thread-local state.
# ---------------------------------------------------------------------------


def test_two_users_get_physically_separate_databases():
    conn_a = _new_conn("alice")
    conn_b = _new_conn("bob")

    database.save_setting(conn_a, "secret", "alice-only")
    assert database.load_setting(conn_b, "secret") is None

    database.save_transactions(
        conn_a,
        [
            {
                "order_ref": None,
                "date": "2026-01-01",
                "time": None,
                "name": "Alice's fund",
                "isin": "IE00ALICE0001",
                "exchange": None,
                "execution_venue": None,
                "transaction_type": "BUY",
                "quantity": 1.0,
                "price": 1.0,
                "local_value": -1.0,
                "value_eur": -1.0,
                "exchange_rate": None,
                "autofx_cost": None,
                "transaction_fee": None,
                "total_eur": -1.0,
            }
        ],
    )

    assert len(database.load_transactions(conn_a)) == 1
    assert len(database.load_transactions(conn_b)) == 0

    conn_a.close()
    conn_b.close()


def test_concurrent_writes_from_two_users_never_cross(tmp_path, monkeypatch):
    """
    Defense-in-depth regression test: spin up two threads, each opening its
    own connection for a different user and writing/reading concurrently.
    With no shared/global state left in database.py, there is nothing for the
    threads to race on — this asserts that guarantee holds in practice.
    """
    monkeypatch.setattr(database, "_HERE", str(tmp_path))

    errors: list[Exception] = []

    def _worker(username: str, isin: str, n: int):
        try:
            conn = _new_conn(username)
            for i in range(n):
                database.save_setting(conn, "marker", f"{username}-{i}")
                database.save_transactions(
                    conn,
                    [
                        {
                            "order_ref": None,
                            "date": "2026-01-01",
                            "time": None,
                            "name": username,
                            "isin": isin,
                            "exchange": None,
                            "execution_venue": None,
                            "transaction_type": "BUY",
                            "quantity": 1.0,
                            "price": 1.0,
                            "local_value": -1.0,
                            "value_eur": -1.0,
                            "exchange_rate": None,
                            "autofx_cost": None,
                            "transaction_fee": None,
                            "total_eur": -1.0,
                        }
                    ],
                )
                got = database.load_setting(conn, "marker")
                if got != f"{username}-{i}":
                    errors.append(AssertionError(f"{username}: expected marker '{username}-{i}', got {got!r}"))
            conn.close()
        except Exception as e:  # pragma: no cover - surfaced via `errors`
            errors.append(e)

    t1 = threading.Thread(target=_worker, args=("alice", "IE00ALICE0001", 25))
    t2 = threading.Thread(target=_worker, args=("bob", "IE00BOB000001", 25))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, errors

    conn_a = database.connect("alice")
    conn_b = database.connect("bob")
    isins_a = {t["isin"] for t in database.load_transactions(conn_a)}
    isins_b = {t["isin"] for t in database.load_transactions(conn_b)}
    assert isins_a == {"IE00ALICE0001"}
    assert isins_b == {"IE00BOB000001"}
    conn_a.close()
    conn_b.close()


def test_concurrent_opens_migrate_the_dividends_table_exactly_once(tmp_path):
    """init_db runs on every request and the dashboard opens four connections at
    once, so the first page load after the upgrade has several of them reaching
    the rename together."""
    import concurrent.futures

    conn = _new_conn("alice")
    conn.execute("DROP TABLE dividends")
    conn.execute("""
        CREATE TABLE dividends (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            date              TEXT    NOT NULL,
            isin              TEXT    NOT NULL,
            name              TEXT,
            currency_original TEXT,
            amount_original   REAL,
            gross_eur         REAL,
            tax_eur           REAL,
            net_eur           REAL    NOT NULL,
            UNIQUE(date, isin, amount_original, currency_original)
        )
    """)
    for i in range(50):
        conn.execute(
            "INSERT INTO dividends (date, isin, name, currency_original,"
            " amount_original, gross_eur, tax_eur, net_eur)"
            " VALUES (?, 'X', 'Fund', 'EUR', ?, ?, 0.0, ?)",
            (f"2025-01-{i % 28 + 1:02d}", float(i), float(i), float(i)),
        )
    conn.commit()
    conn.close()

    def open_once():
        c = database.connect("alice", same_thread_only=False)
        try:
            database.init_db(c)
            return c.execute("SELECT COUNT(*) FROM dividends").fetchone()[0]
        finally:
            c.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        counts = [f.result() for f in [pool.submit(open_once) for _ in range(6)]]

    assert counts == [50] * 6, "no open may see a half-migrated table"

    conn = database.connect("alice")
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA index_list(dividends)")
        assert not any(i["origin"] == "u" and i["unique"] for i in cur.fetchall())
        assert conn.execute("SELECT COUNT(*) FROM dividends").fetchone()[0] == 50
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'dividends_old'").fetchone()[0] == 0
    finally:
        conn.close()


def _tx(**remaining) -> dict:
    base = {
        "order_ref": "o-1",
        "date": "2026-08-11",
        "time": "16:00",
        "name": "PICTET MONEY MARKET",
        "isin": "LU0128494944",
        "exchange": "KFS",
        "execution_venue": None,
        "transaction_type": "BUY",
        "quantity": 10.0,
        "price": 150.0,
        "local_value": -1500.0,
        "value_eur": -1500.0,
        "exchange_rate": None,
        "autofx_cost": None,
        "transaction_fee": None,
        "total_eur": -1500.0,
    }
    base.update(remaining)
    return base


@pytest.mark.parametrize("bad", [float("nan"), None, float("inf")])
def test_save_transactions_skips_unusable_quantity_instead_of_failing(bad):
    """
    quantity is NOT NULL and sqlite binds a float NaN as NULL, so one bad row
    used to raise IntegrityError out of the whole INSERT loop — rolling back
    every good row in the file and answering the upload with a 500.
    """
    conn = _new_conn("tim")
    saved, skipped = database.save_transactions(conn, [_tx(quantity=bad, order_ref="o-bad"), _tx(order_ref="o-good")])

    assert saved == 1
    assert skipped == 1
    rows = conn.execute("SELECT order_ref FROM transactions").fetchall()
    assert [r[0] for r in rows] == ["o-good"]
    conn.close()


def test_home_exchange_ignores_the_literal_none_a_blank_cell_leaves_behind():
    """
    An empty "Beurs" cell used to be stored as the string "None". Because the
    home venue is the *most frequent* value, those rows outvoted the one real
    exchange — and a venue of "None" matches nothing in the venue table, so the
    position silently lost its authoritative ticker.
    """
    conn = _new_conn("tim")
    rows = [_tx(isin="US5801351017", exchange="None", order_ref=f"phantom-{i}", quantity=0.0, price=None, total_eur=None) for i in range(8)]
    rows.append(_tx(isin="US5801351017", exchange="NSY", order_ref="real"))
    database.save_transactions(conn, rows)

    assert database.load_home_exchanges(conn)["US5801351017"] == "NSY"
    conn.close()


def test_home_exchange_still_picks_the_most_traded_real_venue():
    """The filter must not disturb an ordinary two-venue position."""
    conn = _new_conn("tim")
    rows = [_tx(isin="NL0011872643", exchange="XET", order_ref=f"x-{i}") for i in range(2)]
    rows += [_tx(isin="NL0011872643", exchange="EAM", order_ref=f"e-{i}") for i in range(5)]
    database.save_transactions(conn, rows)

    assert database.load_home_exchanges(conn)["NL0011872643"] == "EAM"
    conn.close()
