"""
safe_regex.py — the patterns of labelling rules, which users (and their AI
assistants, through MCP) type themselves.

A regular expression can take exponential time on the wrong input
(catastrophic backtracking, "ReDoS"): `(a|aa)+$` against forty a's keeps a
server busy for minutes. Rules run over every transaction on every relabel,
so one bad rule could hang the app for everyone. Three layers:

  * **When a rule is made** (`check`): at most MAX_LENGTH characters, it must
    compile, and a repeated group that itself contains a repeat (`(a+)+`,
    `(\\w*\\s?)*`, `(.*,){20}`, `(a|aa)+`) is refused: that shape is where backtracking
    explodes, and a labelling rule never needs it.
  * **When it runs** (`search`): with the `regex` module and a timeout per
    match; a match that runs out of time counts as no match. Existing rules,
    made before the check, are covered by this.
  * Patterns are compiled once and cached.

Semantics stay those of Python's `re` (the `regex` module's VERSION0), case
insensitive, as before.
"""

from __future__ import annotations

import functools
import logging
import re

try:  # Python 3.11+
    import re._parser as _sre_parse  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    import sre_parse as _sre_parse  # type: ignore[no-redef]

try:
    import regex as _engine
except ImportError:  # pragma: no cover - regex is in the requirements
    _engine = None

from domain.i18n import tr

MAX_LENGTH = 500
TIMEOUT_SECONDS = 0.05
_log = logging.getLogger(__name__)

_REPEATS = {_sre_parse.MAX_REPEAT, _sre_parse.MIN_REPEAT}
_POSSESSIVE = getattr(_sre_parse, "POSSESSIVE_REPEAT", None)
if _POSSESSIVE is not None:
    _REPEATS.add(_POSSESSIVE)


def _items(value):
    """Child sub-patterns of one parsed node."""
    if isinstance(value, _sre_parse.SubPattern):
        yield value
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _items(v)


def _has_repeat(sub) -> bool:
    """A repeat or an alternation of sequences: inside another repeat, either one
    lets the engine split the same text in exponentially many ways."""
    for op, av in sub:
        if op in _REPEATS and av[1] > 1:
            return True
        if op == _sre_parse.BRANCH:
            return True
        if any(_has_repeat(child) for child in _items(av)):
            return True
    return False


def _nested_repeat(sub) -> bool:
    for op, av in sub:
        if op in _REPEATS and av[1] > 1:
            if any(_has_repeat(child) for child in _items(av[2])):
                return True
        if any(_nested_repeat(child) for child in _items(av)):
            return True
    return False


def check(pattern: str) -> None:
    """ValueError (in the reader's language) when the pattern is not acceptable for a rule."""
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError(tr("A pattern can't be empty."))
    if len(pattern) > MAX_LENGTH:
        raise ValueError(tr("A pattern is at most {0} characters.", MAX_LENGTH))
    try:
        re.compile(pattern, re.IGNORECASE)
        parsed = _sre_parse.parse(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValueError(tr("Unusable pattern: {0}", e)) from e
    if _nested_repeat(parsed):
        raise ValueError(tr("This pattern repeats a group that repeats itself, which can take very long. Write it without the nesting, e.g. 'ALBERT HEIJN|JUMBO'."))


@functools.lru_cache(maxsize=2048)
def _compiled(pattern: str):
    if _engine is not None:
        return _engine.compile(pattern, _engine.IGNORECASE | _engine.VERSION0)
    return re.compile(pattern, re.IGNORECASE)


def search(pattern: str, text: str) -> bool:
    """Whether `pattern` occurs in `text`, case insensitive. A broken pattern or
    one that runs out of time is no match."""
    try:
        rx = _compiled(pattern)
    except (re.error, Exception):
        return False
    try:
        if _engine is not None:
            return rx.search(text or "", timeout=TIMEOUT_SECONDS) is not None
        return rx.search(text or "") is not None
    except TimeoutError:
        _log.warning("labelling rule timed out and counts as no match: %r", pattern[:80])
        return False
