"""Garmin sync from inside `web`: "Nu synchroniseren" on the site and a daily run for every connected user.

The Railway `sync` cron (tools/sync.py `run_all_users`) does the same; whichever runs first, the other finds nothing new.
One sync per user at a time (lock); progress is kept in memory for the Connections page.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from tools import db
from tools.secretbox import default_key
from tools.sync import run_db_sync

TZ = ZoneInfo("Europe/Amsterdam")
DAILY_HOUR = 6  # local time; the cron runs at 04:00 UTC, so in summer this usually finds it already done
CHECK_EVERY_S = 15 * 60


class SyncRunner:
    def __init__(self, engine, stores, key: str | None = None, client_factory=None, **sync_kwargs):
        """`client_factory` and `sync_kwargs` (e.g. read_streams) replace the real Garmin pieces in tests."""
        self.engine = engine
        self.sync_kwargs = sync_kwargs
        self.stores = stores
        self.key = key if key is not None else default_key()
        self.client_factory = client_factory
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()
        self.running: dict[int, str] = {}  # user id -> started at (ISO)
        self.progress: dict[int, dict] = {}  # user id -> {step, done, total} of the running sync

    def _lock(self, user_id: int) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(user_id, threading.Lock())

    def sync_user(self, user_id: int, since=None) -> int | None:
        """Run now in this thread. None when a sync for this user is already running."""
        lock = self._lock(user_id)
        if not lock.acquire(blocking=False):
            return None
        self.running[user_id] = datetime.now(TZ).isoformat(timespec="seconds")
        try:
            kw = dict(self.sync_kwargs, **({"client_factory": self.client_factory} if self.client_factory else {}))

            def progress(step: str, done: int | None = None, total: int | None = None) -> None:
                self.progress[user_id] = {"step": step, "done": done, "total": total}

            return run_db_sync(db.Scope(self.engine, user_id), self.key, None, since=since, progress=progress, **kw)
        except Exception as err:  # the sync records its own failures; this only guards the thread
            print(f"sync gebruiker {user_id}: MISLUKT ({type(err).__name__}: {err})", flush=True)
            return 1
        finally:
            self.running.pop(user_id, None)
            self.progress.pop(user_id, None)
            self.stores.get(user_id).invalidate()
            lock.release()

    def start_user(self, user_id: int, since=None) -> bool:
        """In the background. False when one is already running."""
        if self._lock(user_id).locked():
            return False
        threading.Thread(target=self.sync_user, args=(user_id, since), name=f"sync-{user_id}", daemon=True).start()
        return True

    def due_users(self, now: datetime | None = None) -> list[int]:
        """Connected, not suspended users whose last sync is not from today, once it is past DAILY_HOUR."""
        now = now or datetime.now(TZ)
        if now.hour < DAILY_HOUR:
            return []
        today = now.date().isoformat()
        connected = set(db.user_ids_with_setting(self.engine, "garmin_tokens")) | set(db.user_ids_with_setting(self.engine, "wahoo_tokens"))
        out = []
        for u in db.list_users(self.engine):
            if u["id"] in connected and not u["suspended"] and (u["last_sync"] or "")[:10] < today:
                out.append(u["id"])
        return out

    def run_due(self, now: datetime | None = None) -> list[int]:
        done = []
        for uid in self.due_users(now):
            if self.sync_user(uid) is not None:
                done.append(uid)
        return done

    def start_daily(self) -> None:
        def loop():
            time.sleep(60)  # let the site start first
            while True:
                try:
                    self.run_due()
                except Exception as err:
                    print(f"dagelijkse sync: {type(err).__name__}: {err}", flush=True)
                time.sleep(CHECK_EVERY_S)

        threading.Thread(target=loop, name="daily-sync", daemon=True).start()
