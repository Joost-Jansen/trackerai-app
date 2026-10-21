"""An in-memory sliding-window rate limiter: at most `max_events` per key within `window_s` seconds.

    logins = Limiter(10, 15 * 60)
    if logins.blocked(name): refuse
    ...on a failure: logins.hit(name)

In memory, so a restart forgets it; the durable layer is a rate-limit rule at the edge (Cloudflare). Memory is bounded:
at most `max_keys` keys are kept, the stalest are dropped first.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable


class Limiter:
    def __init__(self, max_events: int, window_s: float, max_keys: int = 10_000, clock: Callable[[], float] = time.monotonic):
        self.max_events = max_events
        self.window_s = window_s
        self.max_keys = max_keys
        self._clock = clock
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float] | None:
        q = self._events.get(key)
        if q is None:
            return None
        while q and now - q[0] >= self.window_s:
            q.popleft()
        if not q:
            del self._events[key]
            return None
        return q

    def blocked(self, key: str) -> bool:
        """True when `key` already used up its events in the current window."""
        with self._lock:
            q = self._recent(key, self._clock())
            return q is not None and len(q) >= self.max_events

    def hit(self, key: str) -> bool:
        """Record one event for `key`. True while it is within the limit, False once this event went over it."""
        with self._lock:
            now = self._clock()
            q = self._recent(key, now)
            if q is None:
                q = self._events[key] = deque()
            else:
                self._events.move_to_end(key)
            q.append(now)
            over = len(q) > self.max_events
            if over:
                q.popleft()  # keep the window's worth only: memory per key stays bounded
            while len(self._events) > self.max_keys:
                self._events.popitem(last=False)
            return not over

    def remaining_s(self, key: str) -> int:
        """Seconds until `key` gets an event back (0 when it is not blocked): for a Retry-After header."""
        with self._lock:
            now = self._clock()
            q = self._recent(key, now)
            if q is None or len(q) < self.max_events:
                return 0
            return max(1, int(self.window_s - (now - q[0])) + 1)

    def reset(self, key: str | None = None) -> None:
        """Forget `key`, or everything when key is None."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)
