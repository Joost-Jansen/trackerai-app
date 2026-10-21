"""
db.py: the one seam between wealth-tracker's queries and the database behind them (step 11.7 of docs/PLAN.md).

Every user's data lives in SQLite today, one file per user (database.connect). With WEALTH_DATABASE_URL set it
lives in Postgres instead: one `wealth` database, one schema per user (`u_<folder>`), so each user's tables stay
apart exactly as their files do and no query needs a user column.

The code was written against sqlite3, so the Postgres connection here speaks that shape:

    conn.execute(sql, params)      `?` placeholders; rows by name and by index (row["isin"], row[0], dict(row))
    cursor.fetchone/fetchall       cursor.rowcount, cursor.description, iteration
    conn.commit/rollback/close     `with conn:` commits on success and rolls back on an error, as sqlite3 does
    conn.executescript(sql)        several statements, no parameters
    conn.in_transaction            conn.total_changes (rows changed through this connection)

What it does not translate is SQL that only SQLite knows (INSERT OR REPLACE, strftime, PRAGMA, AUTOINCREMENT,
cursor.lastrowid without RETURNING): step 11.7b gives those a form both accept. `IntegrityError` and
`OperationalError` below catch either database's error.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

try:  # psycopg is only needed on Postgres; SQLite installations run without it.
    import psycopg
    from psycopg import sql as pgsql
except ImportError:  # pragma: no cover - the image always has it
    psycopg = None
    pgsql = None

URL_VAR = "WEALTH_DATABASE_URL"

IntegrityError: tuple[type[BaseException], ...] = (sqlite3.IntegrityError,)
OperationalError: tuple[type[BaseException], ...] = (sqlite3.OperationalError,)
if psycopg is not None:
    IntegrityError += (psycopg.IntegrityError,)
    # What sqlite3 calls an OperationalError: also "no such table" and "duplicate column", which Postgres files
    # under ProgrammingError.
    OperationalError += (
        psycopg.OperationalError,
        psycopg.errors.UndefinedTable,
        psycopg.errors.UndefinedColumn,
        psycopg.errors.DuplicateColumn,
        psycopg.errors.DuplicateTable,
    )


def postgres_url() -> str:
    return os.environ.get(URL_VAR, "").strip()


def on_postgres() -> bool:
    """True when the users' data lives in Postgres (WEALTH_DATABASE_URL), False for SQLite files."""
    return bool(postgres_url())


def schema_for(folder: str) -> str:
    """A user's schema: `u_` and the data folder's name, lowercased. Folder names are [A-Za-z0-9_-]{1,40}
    (database._safe_user), so `-` becomes `_` and the result is always a plain identifier."""
    if not isinstance(folder, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", folder):
        raise ValueError(f"Invalid data folder for a schema: {folder!r}")
    # WEALTH_SCHEMA_PREFIX: tests give every test its own schemas in one database; empty in production.
    prefix = re.sub(r"[^a-z0-9_]", "", os.environ.get("WEALTH_SCHEMA_PREFIX", "").lower())
    return prefix + "u_" + folder.lower().replace("-", "_")


# --- SQL from the sqlite3 shape to psycopg's ---------------------------------------------------------------------

_TOKENS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/|\?|(?<!:):[A-Za-z_]\w*|%", re.S)


def translate(sql: str, has_params: bool) -> str:
    """`?` becomes `%s`, a named `:isin` becomes `%(isin)s`, and, when there are parameters, a literal `%` becomes
    `%%` (psycopg formats the whole string then, quotes included). Placeholders inside quotes or comments are left
    alone."""

    def swap(m: re.Match) -> str:
        tok = m.group(0)
        if tok == "?":
            return "%s"
        if tok.startswith(":"):
            return f"%({tok[1:]})s"
        if tok == "%":
            return "%%" if has_params else "%"
        return tok.replace("%", "%%") if has_params else tok

    return _TOKENS.sub(swap, sql)


def _params(params):
    """sqlite3 takes a sequence (for ?) or a mapping (for :name); so does psycopg."""
    if params is None:
        return ()
    return params if isinstance(params, Mapping) else tuple(params)


_WRITES = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)

# --- What only SQLite says, in Postgres's words (on the Postgres connection only) --------------------------------

_LITERALS = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.S)

# SQLite's catalog as Postgres's, for the current (the user's) schema: tables, views and indexes.
_SQLITE_MASTER = (
    "(SELECT 'table'::text AS type, c.relname::text AS name, c.relname::text AS tbl_name, NULL::text AS sql"
    " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE n.nspname = current_schema() AND c.relkind = 'r'"
    " UNION ALL SELECT 'view', c.relname::text, c.relname::text, NULL"
    " FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE n.nspname = current_schema() AND c.relkind = 'v'"
    " UNION ALL SELECT 'index', ic.relname::text, t.relname::text, NULL"
    " FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_class t ON t.oid = i.indrelid"
    " JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = current_schema()) AS sqlite_master"
)
_NOW_TEXT = "(to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS'))"

_CODE_REWRITES = [
    # A rowid table: its integer key fills itself. BY DEFAULT, so an explicit id (a migration copy) still goes in.
    (re.compile(r"\bINTEGER\s+PRIMARY\s+KEY(\s+AUTOINCREMENT)?\b", re.I), "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"),
    # wealth-tracker's REFERENCES only document a relationship: SQLite runs with foreign_keys off and the code deletes
    # children itself (accounts.delete_account), and old data has rows whose parent is gone. Postgres would enforce
    # them, so they are left out there too.
    (
        re.compile(
            r"\s+REFERENCES\s+\w+\s*\([^)]*\)(\s+ON\s+(DELETE|UPDATE)\s+(CASCADE|SET\s+NULL|SET\s+DEFAULT|"
            r"RESTRICT|NO\s+ACTION))*",
            re.I,
        ),
        "",
    ),
    (re.compile(r"\bBLOB\b", re.I), "BYTEA"),
    # SQLite's REAL is an 8-byte float; Postgres's REAL is 4 bytes, which loses money's cents and breaks equality.
    (re.compile(r"\bREAL\b", re.I), "DOUBLE PRECISION"),
    # SQLite's CURRENT_TIMESTAMP is UTC text, 'YYYY-MM-DD HH:MM:SS'; the columns that default to it are TEXT.
    (re.compile(r"\bDEFAULT\s+CURRENT_TIMESTAMP\b", re.I), "DEFAULT " + _NOW_TEXT),
    # `x IS ?`: equal, NULL included. Postgres says IS [NOT] DISTINCT FROM for that (IS NULL stays as it is).
    (re.compile(r"\bIS\s+NOT\s+(?=\?|:[A-Za-z_])", re.I), "IS DISTINCT FROM "),
    (re.compile(r"\bIS\s+(?=\?|:[A-Za-z_])", re.I), "IS NOT DISTINCT FROM "),
    # SQLite's LIKE ignores ASCII case; Postgres's ILIKE does too.
    (re.compile(r"\bLIKE\b", re.I), "ILIKE"),
    (re.compile(r"\bsqlite_master\b", re.I), _SQLITE_MASTER),
]


def dialect(sql: str) -> str:
    """The SQLite-only words outside quotes and comments, in Postgres's (see _CODE_REWRITES)."""
    out, last = [], 0
    for m in _LITERALS.finditer(sql):
        out.append(_rewrite_code(sql[last : m.start()]))
        out.append(m.group(0))
        last = m.end()
    out.append(_rewrite_code(sql[last:]))
    return "".join(out)


def _rewrite_code(code: str) -> str:
    for pattern, repl in _CODE_REWRITES:
        code = pattern.sub(repl, code)
    return code


_PRAGMA = re.compile(r"^\s*PRAGMA\s+(\w+)\s*(?:\(\s*\"?(\w+)\"?\s*\)|=\s*\S+)?\s*;?\s*$", re.I)
_BEGIN = re.compile(r"^\s*BEGIN(\s+(IMMEDIATE|EXCLUSIVE|DEFERRED))?(\s+TRANSACTION)?\s*;?\s*$", re.I)
_UPSERT = re.compile(r"^\s*(?:INSERT\s+OR\s+(IGNORE|REPLACE)|(REPLACE))\s+INTO\s+\"?(\w+)\"?\s*(\(([^)]*)\))?", re.I)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+\"?(\w+)\"?", re.I)
_DDL = re.compile(r"^\s*(CREATE|ALTER|DROP)\b", re.I)
_RETURNING = re.compile(r"\bRETURNING\b", re.I)


class Row(Sequence):
    """sqlite3.Row's shape: by index, by column name, keys(), and dict(row)."""

    __slots__ = ("_names", "_values")

    def __init__(self, names: tuple[str, ...], values: tuple):
        self._names = names
        self._values = values

    def keys(self) -> list[str]:
        return list(self._names)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._values[self._names.index(key)]
            except ValueError:
                raise IndexError(f"No item with that key: {key!r}") from None
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def __eq__(self, other) -> bool:
        if isinstance(other, Row):
            return self._names == other._names and self._values == other._values
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self._names, self._values))

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values))!r})"


class Cursor:
    def __init__(self, conn: PgConnection):
        self._conn = conn
        self._cur = conn._raw.cursor()
        self.lastrowid = None
        self._static: list[Row] | None = None  # the answer to a PRAGMA, made here instead of by Postgres
        self._static_names: tuple[str, ...] = ()

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> Cursor:
        values = _params(params)
        self.lastrowid, self._static = None, None
        if m := _PRAGMA.match(sql):
            return self._pragma(m.group(1).lower(), m.group(2))
        if m := _BEGIN.match(sql):
            # psycopg is always in a transaction already. BEGIN IMMEDIATE (one writer at a time, a migration's
            # guard) becomes a lock on the user's schema that lasts until this transaction ends.
            if (m.group(2) or "").upper() in ("IMMEDIATE", "EXCLUSIVE"):
                self._cur.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()))")
            return self._answer((), [])
        text, want_id = self._conn._prepare(sql, many=False)
        self._guarded(translate(text, bool(values)), values or None)
        if want_id:
            row = self._cur.fetchone()
            self.lastrowid = row[0] if row else None
        self._count(sql)
        return self

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> Cursor:
        rows = [_params(p) for p in seq]
        self.lastrowid, self._static = None, None
        if rows:
            text, _ = self._conn._prepare(sql, many=True)
            self._guarded(translate(text, True), rows, many=True)
            self._count(sql)
        return self

    def _guarded(self, text: str, values, many: bool = False) -> None:
        """One statement inside a savepoint. A failed statement leaves an SQLite transaction as it was, and the code
        relies on that (it catches IntegrityError and carries on); in Postgres it would abort the whole transaction,
        so the failure is rolled back to just before the statement."""
        self._cur.execute("SAVEPOINT wealth_stmt")
        try:
            if many:
                self._cur.executemany(text, values)
            else:
                self._cur.execute(text, values)
        except Exception:
            self._conn._raw.execute("ROLLBACK TO SAVEPOINT wealth_stmt")
            raise
        self._conn._raw.execute("RELEASE SAVEPOINT wealth_stmt")

    def _count(self, sql: str) -> None:
        if _WRITES.match(sql) and self._cur.rowcount and self._cur.rowcount > 0:
            self._conn._changes += self._cur.rowcount
        if _DDL.match(sql):
            self._conn._catalog.clear()

    def _answer(self, names: tuple[str, ...], rows: list[tuple]) -> Cursor:
        self._static_names = names
        self._static = [Row(names, tuple(r)) for r in rows]
        return self

    def _pragma(self, name: str, arg: str | None) -> Cursor:
        """table_info and index_list answered from Postgres's catalog in SQLite's shape; the rest (busy_timeout,
        journal_mode, foreign_keys) mean nothing here."""
        if name == "table_info" and arg:
            info = self._conn._table(arg)
            rows = [
                (i, c, t, int(nn), d, (info["pk"].index(c) + 1) if c in info["pk"] else 0) for i, (c, t, nn, d) in enumerate(info["detail"])
            ]
            return self._answer(("cid", "name", "type", "notnull", "dflt_value", "pk"), rows)
        if name == "index_list" and arg:
            rows = [(i, n, int(u), o, 0) for i, (n, u, o) in enumerate(self._conn._table(arg)["indexes"])]
            return self._answer(("seq", "name", "unique", "origin", "partial"), rows)
        return self._answer((), [])

    def _names(self) -> tuple[str, ...]:
        if self._static is not None:
            return self._static_names
        return tuple(d.name for d in (self._cur.description or ()))

    def fetchone(self):
        if self._static is not None:
            return self._static.pop(0) if self._static else None
        values = self._cur.fetchone()
        return Row(self._names(), tuple(values)) if values is not None else None

    def fetchall(self) -> list[Row]:
        if self._static is not None:
            rows, self._static = self._static, []
            return rows
        names = self._names()
        return [Row(names, tuple(v)) for v in self._cur.fetchall()]

    def fetchmany(self, size: int = 1) -> list[Row]:
        if self._static is not None:
            rows, self._static = self._static[:size], self._static[size:]
            return rows
        names = self._names()
        return [Row(names, tuple(v)) for v in self._cur.fetchmany(size)]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self) -> int:
        return -1 if self._static is not None else self._cur.rowcount

    @property
    def description(self):
        """sqlite3's shape: a 7-tuple per column, the name first."""
        names = self._names()
        return tuple((n, None, None, None, None, None, None) for n in names) if names else None

    def close(self) -> None:
        self._cur.close()


class PgConnection:
    """A Postgres connection to one user's schema, in sqlite3.Connection's shape (see the module docstring)."""

    def __init__(self, raw, schema: str):
        self._raw = raw
        self.schema = schema
        self._changes = 0
        self._catalog: dict[str, dict] = {}
        self.row_factory = None  # sqlite3 code sets it; rows are always Row here

    def _table(self, name: str) -> dict:
        """One table of the user's schema from Postgres's catalog: its columns, primary key, unique column sets,
        indexes (name, unique, SQLite's origin: pk, u for a constraint, c for CREATE INDEX) and identity column."""
        name = name.lower()
        if name not in self._catalog:
            cur = self._raw.cursor()
            detail = cur.execute(
                "SELECT a.attname, upper(format_type(a.atttypid, a.atttypmod)), a.attnotnull,"
                " pg_get_expr(d.adbin, d.adrelid), a.attidentity"
                " FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
                " JOIN pg_namespace n ON n.oid = c.relnamespace"
                " LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum"
                " WHERE n.nspname = current_schema() AND c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped"
                " ORDER BY a.attnum",
                (name,),
            ).fetchall()
            indexes = cur.execute(
                "SELECT ic.relname, i.indisunique, i.indisprimary, con.contype,"
                " array(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(n, o)"
                "       JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.n ORDER BY k.o)"
                " FROM pg_index i JOIN pg_class ic ON ic.oid = i.indexrelid JOIN pg_class t ON t.oid = i.indrelid"
                " JOIN pg_namespace n ON n.oid = t.relnamespace"
                " LEFT JOIN pg_constraint con ON con.conindid = i.indexrelid"
                " WHERE n.nspname = current_schema() AND t.relname = %s ORDER BY ic.relname",
                (name,),
            ).fetchall()
            pk = next((list(cols) for _, _, primary, _, cols in indexes if primary), [])
            self._catalog[name] = {
                "columns": [r[0] for r in detail],
                "detail": [(r[0], r[1], r[2], r[3]) for r in detail],
                "identity": next((r[0] for r in detail if r[4]), None),
                "pk": pk,
                "unique": [list(cols) for _, unique, primary, _, cols in indexes if unique and not primary],
                "indexes": [
                    (n, unique, "pk" if primary else ("u" if contype == "u" else "c")) for n, unique, primary, contype, _ in indexes
                ],
            }
        return self._catalog[name]

    def _prepare(self, sql: str, many: bool) -> tuple[str, bool]:
        """The statement in Postgres's words, and whether it now ends in RETURNING the new row's id (lastrowid)."""
        text = dialect(sql).rstrip().rstrip(";").rstrip()
        if m := _UPSERT.match(sql):
            mode = (m.group(1) or "REPLACE").upper()
            table = m.group(3).lower()
            text = re.sub(r"^\s*(?:INSERT\s+OR\s+(?:IGNORE|REPLACE)|REPLACE)\s+INTO", "INSERT INTO", text, count=1, flags=re.I)
            if mode == "IGNORE":
                text += " ON CONFLICT DO NOTHING"
            else:
                # SQLite replaces the row that collides on its key; Postgres updates it in place.
                info = self._table(table)
                target = info["pk"] or (info["unique"][0] if info["unique"] else [])
                names = [c.strip().strip('"').lower() for c in m.group(5).split(",")] if m.group(5) else info["columns"]
                if target:
                    sets = [c for c in names if c not in target]
                    action = ("DO UPDATE SET " + ", ".join(f"{c} = EXCLUDED.{c}" for c in sets)) if sets else "DO NOTHING"
                    text += f" ON CONFLICT ({', '.join(target)}) {action}"
        want_id = False
        if not many and not _RETURNING.search(text) and (ins := _INSERT.match(text)):
            identity = self._table(ins.group(1))["identity"]
            if identity:
                text += f" RETURNING {identity}"
                want_id = True
        return text, want_id

    def cursor(self) -> Cursor:
        return Cursor(self)

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> Cursor:
        return self.cursor().execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> Cursor:
        return self.cursor().executemany(sql, seq)

    def executescript(self, script: str) -> Cursor:
        """Several statements at once, without parameters (psycopg runs a parameterless multi-statement string)."""
        cur = self.cursor()
        cur._cur.execute(dialect(script))
        self._catalog.clear()
        self.commit()
        return cur

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    @property
    def in_transaction(self) -> bool:
        return self._raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE

    @property
    def total_changes(self) -> int:
        return self._changes

    def __enter__(self) -> PgConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


def connect_postgres(folder: str, url: str | None = None) -> PgConnection:
    """One user's schema in the `wealth` database, made on first use."""
    if psycopg is None:  # pragma: no cover
        raise RuntimeError(f"{URL_VAR} is set but psycopg is not installed")
    schema = schema_for(folder)
    raw = psycopg.connect(url or postgres_url(), autocommit=False)
    _sqlite_types(raw)
    ident = pgsql.Identifier(schema)
    try:
        raw.execute(pgsql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(ident))
        raw.commit()
    except psycopg.errors.UniqueViolation:
        # Two first requests for one user at once: IF NOT EXISTS is not atomic in Postgres; the other one made it.
        raw.rollback()
    _ensure_compat(raw)
    raw.execute(pgsql.SQL("SET search_path TO {}, {}").format(ident, pgsql.Identifier(COMPAT_SCHEMA)))
    raw.commit()
    return PgConnection(raw, schema)


# What SQLite has and Postgres lacks, as functions of a schema behind every user's on the search path.
COMPAT_SCHEMA = "wealth_compat"
_COMPAT_SQL = f"""
CREATE SCHEMA IF NOT EXISTS {COMPAT_SCHEMA};
-- A comparison is 0 or 1 in SQLite, so SUM(a = b) counts. A boolean is not a number in Postgres; this SUM counts the
-- true ones (NULL over no rows, as SUM is).
CREATE OR REPLACE FUNCTION {COMPAT_SCHEMA}.sum_bool_step(bigint, boolean) RETURNS bigint
    LANGUAGE sql IMMUTABLE AS 'SELECT COALESCE($1, 0) + CASE WHEN $2 THEN 1 ELSE 0 END';
CREATE OR REPLACE AGGREGATE {COMPAT_SCHEMA}.sum(boolean) (SFUNC = {COMPAT_SCHEMA}.sum_bool_step, STYPE = bigint);
-- MAX(a, b) and MIN(a, b) with two or three arguments: SQLite's scalar larger and smaller (NULL if any is NULL).
CREATE OR REPLACE FUNCTION {COMPAT_SCHEMA}.max(anyelement, anyelement) RETURNS anyelement LANGUAGE sql IMMUTABLE
    AS 'SELECT CASE WHEN $1 IS NULL OR $2 IS NULL THEN NULL ELSE GREATEST($1, $2) END';
CREATE OR REPLACE FUNCTION {COMPAT_SCHEMA}.max(anyelement, anyelement, anyelement) RETURNS anyelement
    LANGUAGE sql IMMUTABLE
    AS 'SELECT CASE WHEN $1 IS NULL OR $2 IS NULL OR $3 IS NULL THEN NULL ELSE GREATEST($1, $2, $3) END';
CREATE OR REPLACE FUNCTION {COMPAT_SCHEMA}.min(anyelement, anyelement) RETURNS anyelement LANGUAGE sql IMMUTABLE
    AS 'SELECT CASE WHEN $1 IS NULL OR $2 IS NULL THEN NULL ELSE LEAST($1, $2) END';
CREATE OR REPLACE FUNCTION {COMPAT_SCHEMA}.min(anyelement, anyelement, anyelement) RETURNS anyelement
    LANGUAGE sql IMMUTABLE
    AS 'SELECT CASE WHEN $1 IS NULL OR $2 IS NULL OR $3 IS NULL THEN NULL ELSE LEAST($1, $2, $3) END';
"""
_compat_ready = False


def _ensure_compat(raw) -> None:
    """Make wealth_compat once per process; a lock keeps two first connections from making it at the same time."""
    global _compat_ready
    if _compat_ready:
        return
    raw.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (COMPAT_SCHEMA,))
    raw.execute(_COMPAT_SQL)
    raw.commit()
    _compat_ready = True


def _sqlite_types(raw) -> None:
    """Values in and out as SQLite has them: True/False as 1/0 (the columns are INTEGER), dates and times as text
    (sqlite3's adapters: '2026-10-09', '2026-10-09 17:00:00'), and NUMERIC results (ROUND, SUM of a cast) as float."""
    from datetime import date, datetime

    from psycopg.adapt import Dumper
    from psycopg.types.numeric import FloatLoader

    int8, text = psycopg.adapters.types["int8"].oid, psycopg.adapters.types["text"].oid

    class BoolAsInt(Dumper):
        oid = int8

        def dump(self, obj):
            return b"1" if obj else b"0"

    class DateAsText(Dumper):
        oid = text

        def dump(self, obj):
            return (obj.isoformat(" ") if isinstance(obj, datetime) else obj.isoformat()).encode()

    raw.adapters.register_dumper(bool, BoolAsInt)
    raw.adapters.register_dumper(date, DateAsText)
    raw.adapters.register_dumper(datetime, DateAsText)
    raw.adapters.register_loader("numeric", FloatLoader)


# --- A user's schema as a whole: for the admin panels, the account export and deleting an account -----------------


def open_existing(folder: str, url: str | None = None) -> PgConnection | None:
    """The user's schema when it exists, else None: like opening an SQLite file read-only, it never makes one."""
    schema = schema_for(folder)
    raw = psycopg.connect(url or postgres_url(), autocommit=False)
    _sqlite_types(raw)
    if raw.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone() is None:
        raw.close()
        return None
    _ensure_compat(raw)
    raw.execute(pgsql.SQL("SET search_path TO {}, {}").format(pgsql.Identifier(schema), pgsql.Identifier(COMPAT_SCHEMA)))
    raw.commit()
    return PgConnection(raw, schema)


def schema_bytes(folder: str, url: str | None = None) -> int:
    """What the user's tables and indexes take on disk (0 without a schema): the database size of the admin panels."""
    with psycopg.connect(url or postgres_url()) as raw:
        row = raw.execute(
            "SELECT COALESCE(SUM(pg_total_relation_size(c.oid)), 0) FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relkind IN ('r', 'm')",
            (schema_for(folder),),
        ).fetchone()
    return int(row[0])


def drop_schema(folder: str, url: str | None = None) -> None:
    """Delete a user's tables, all of them, for good: deleting an account."""
    with psycopg.connect(url or postgres_url(), autocommit=True) as raw:
        raw.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(pgsql.Identifier(schema_for(folder))))


def swap_schema(staging: str, final: str, url: str | None = None) -> None:
    """Put a schema built aside in place of another, in one transaction: a request reads the old one or the new one,
    never half of either (the example account's weekly rebuild)."""
    old, new = pgsql.Identifier(schema_for(final)), pgsql.Identifier(schema_for(staging))
    with psycopg.connect(url or postgres_url()) as raw:
        raw.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (schema_for(final),))
        raw.execute(pgsql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(old))
        raw.execute(pgsql.SQL("ALTER SCHEMA {} RENAME TO {}").format(new, old))
