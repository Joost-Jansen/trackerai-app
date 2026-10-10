"""
migrate_pg.py: every user's SQLite file into their Postgres schema, once, checked (step 11.7d of docs/PLAN.md).

    python -m domain.migrate_pg          copy whoever is not in Postgres yet, and print what happened

The API runs the same at startup when WEALTH_DATABASE_URL is set and WEALTH_MIGRATE_FROM_SQLITE=on (app/main.py),
before it answers its healthcheck. The api has a volume, so Railway stops the old deployment before the new one
starts: a failed copy means the API is down until it is rolled back. So first a dry run: with
WEALTH_MIGRATION_CHECK_URL set (and WEALTH_DATABASE_URL not), the API serves from SQLite as always and, in the
background, copies everyone into Postgres, checks it, drops it again and logs `[migrate-check]` with the result.

Per user:
- the SQLite file is only read (`mode=ro`); it stays on the volume as the fallback;
- the schema gets today's tables (database.init_db), then each table of the file is copied in, its rows exactly;
- each table is checked: the same number of rows and the same checksum over all of them, read back from Postgres;
- a user whose copy is checked gets a `_migrated_from_sqlite` table with the counts, and is skipped next time;
- anything wrong (a table or column the schema does not have, a value Postgres refuses, a checksum that differs)
  drops that user's schema again and stops the run with the reason.

The example account (`_example`) is not copied: it is rebuilt from scratch every week.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone

from domain import database, db

MARK = "_migrated_from_sqlite"
SKIP_PREFIX = "_example"


class MigrationError(RuntimeError):
    pass


def sqlite_users(root: str | None = None) -> list[str]:
    """The data folders that have an SQLite database, the example account's left out."""
    users_dir = os.path.join(root or database.data_root(), "users")
    if not os.path.isdir(users_dir):
        return []
    return sorted(
        name for name in os.listdir(users_dir)
        if not name.startswith(SKIP_PREFIX) and os.path.isfile(os.path.join(users_dir, name, "portfolio.db"))
    )


def _float_text(value: float) -> str:
    """A float as Postgres writes it into a TEXT column (shortest form, 5.0 as '5')."""
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if math.isnan(value):
        return "NaN"
    text = repr(float(value))
    return text[:-2] if text.endswith(".0") else text


def _canonical(value, pg_type: str):
    """One value as both sides should hold it, for the checksum: what SQLite stored, read the way the Postgres column
    keeps it (SQLite lets any column hold any type; Postgres converts on the way in)."""
    if value is None:
        return None
    if isinstance(value, memoryview):
        value = bytes(value)
    if pg_type.startswith(("DOUBLE", "REAL", "NUMERIC")):
        return repr(float(value))
    if pg_type.startswith(("BIGINT", "INTEGER", "SMALLINT")):
        return int(value)
    if pg_type == "BYTEA":
        return bytes(value).hex() if not isinstance(value, str) else value.encode().hex()
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, float):
        return _float_text(value)
    return str(value)


def _checksum(rows: list[tuple], types: list[str]) -> str:
    canon = sorted(json.dumps([_canonical(v, t) for v, t in zip(row, types)]) for row in rows)
    return hashlib.sha256("\n".join(canon).encode()).hexdigest()


def _sqlite_tables(src: sqlite3.Connection) -> list[str]:
    return [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def _copy_table(src: sqlite3.Connection, dst: db.PgConnection, table: str) -> dict:
    info = dst._table(table)
    if not info["columns"]:
        raise MigrationError(f"table {table} is in the SQLite file but not in the schema init_db makes")
    src_cols = [r[1] for r in src.execute(f'PRAGMA table_info("{table}")')]
    missing = [c for c in src_cols if c.lower() not in info["columns"]]
    if missing:
        raise MigrationError(f"{table}: columns {missing} are in the SQLite file but not in the schema")
    cols = [c.lower() for c in src_cols]
    types = [dict((c, t) for c, t, _, _ in info["detail"])[c] for c in cols]
    rows = [tuple(r) for r in src.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in src_cols)} FROM "{table}"')]

    raw = dst._raw
    raw.execute(f'DELETE FROM "{table}"')  # init_db may have put rows in (default categories): the file's win
    if rows:
        placeholders = ", ".join(["%s"] * len(cols))
        quoted = ", ".join(f'"{c}"' for c in cols)
        with raw.cursor() as cur:
            cur.executemany(f'INSERT INTO "{table}" ({quoted}) VALUES ({placeholders})',
                            [tuple(bytes(v) if isinstance(v, memoryview) else v for v in r) for r in rows])
    if info["identity"] and info["identity"] in cols:
        ident = info["identity"]
        # The next new row continues after the copied ones, as SQLite's would.
        raw.execute(f'SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE(MAX("{ident}"), 0) + 1, false)'
                    f' FROM "{table}"', (f'"{dst.schema}"."{table}"', ident))

    back = [tuple(r) for r in raw.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"')]
    if len(back) != len(rows):
        raise MigrationError(f"{table}: {len(rows)} rows in SQLite, {len(back)} in Postgres")
    want, got = _checksum(rows, types), _checksum(back, types)
    if want != got:
        raise MigrationError(f"{table}: the rows differ after the copy (checksum {want[:12]} vs {got[:12]})")
    return {"rows": len(rows), "checksum": want[:16]}


def migrate_user(folder: str, url: str | None = None, keep: bool = True) -> dict | None:
    """Copy one user, checked. None when they are in Postgres already. `keep=False` is a dry run: the copy is checked
    and then dropped again, and nothing is marked."""
    path = database.db_path_for_user(folder)  # validates the name
    dst = db.connect_postgres(folder, url)
    try:
        dst.execute("BEGIN IMMEDIATE")  # one copier per user: a lock on the schema for this transaction
        if dst._table(MARK)["columns"]:
            dst.rollback()
            return None
        dst.rollback()
        database.init_db(dst)
        dst.commit()
        src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            dst.execute("BEGIN IMMEDIATE")
            report = {table: _copy_table(src, dst, table) for table in _sqlite_tables(src)}
        finally:
            src.close()
        if not keep:
            dst.rollback()
            dst.close()
            db.drop_schema(folder, url)
            return report
        dst._raw.execute(f'CREATE TABLE "{MARK}" (at TEXT, report TEXT)')
        dst._raw.execute(f'INSERT INTO "{MARK}" VALUES (%s, %s)',
                         (datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(report)))
        dst.commit()
        return report
    except Exception:
        dst.rollback()
        dst.close()
        db.drop_schema(folder, url)  # no half copy stays behind; the next run starts this user afresh
        raise
    finally:
        try:
            dst.close()
        except Exception:  # noqa: BLE001 - closed above on the failure path
            pass


def migrate_all(root: str | None = None) -> dict:
    """Everyone not in Postgres yet. Stops at the first user whose copy fails, with the reason."""
    if not db.on_postgres():
        raise MigrationError(f"{db.URL_VAR} is not set: nowhere to copy to")
    done, skipped = {}, []
    for folder in sqlite_users(root):
        try:
            report = migrate_user(folder)
        except Exception as e:
            raise MigrationError(f"user {folder}: {e}") from e
        if report is None:
            skipped.append(folder)
        else:
            done[folder] = {t: r["rows"] for t, r in report.items()}
    return {"copied": done, "already": skipped}


def check_all(url: str, root: str | None = None) -> dict:
    """A dry run of the move, while the app goes on using SQLite: everyone copied into Postgres at `url`, checked,
    and dropped again. Users already moved are left alone. Raises MigrationError with the first user that fails."""
    checked, skipped = {}, []
    for folder in sqlite_users(root):
        try:
            report = migrate_user(folder, url, keep=False)
        except Exception as e:
            raise MigrationError(f"user {folder}: {e}") from e
        if report is None:
            skipped.append(folder)
        else:
            checked[folder] = {t: r["rows"] for t, r in report.items()}
    return {"checked": checked, "already": skipped}


def main() -> int:
    try:
        result = migrate_all()
    except MigrationError as e:
        print(f"[migrate] stopped: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
