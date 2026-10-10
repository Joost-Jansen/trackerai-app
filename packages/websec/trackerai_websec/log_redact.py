"""Keep secrets out of the logs: the MCP token some clients carry in the URL (`/api/mcp/<token>`) and any
`Authorization: Bearer ...` value that ends up in a log line.

    log_redact.install()        # once, when the app is created: uvicorn's access and error loggers

uvicorn's access log formats `%s "%s %s HTTP/%s" %d` with the path as an argument, so the filter rewrites the
arguments as well as the message.
"""

from __future__ import annotations

import logging
import re

PATTERNS = (
    (re.compile(r"(/api/mcp/)[^/?#\s\"']+"), r"\1***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1***"),
)
LOGGERS = ("uvicorn.access", "uvicorn.error", "uvicorn")


def redact(text: str) -> str:
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    """Masks tokens in a record's message and its string arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
        return True


def install(loggers=LOGGERS) -> None:
    """Add the filter to each logger once (and to their handlers, which see records from child loggers too)."""
    for name in loggers:
        logger = logging.getLogger(name)
        for target in (logger, *logger.handlers):
            if not any(isinstance(f, RedactFilter) for f in target.filters):
                target.addFilter(RedactFilter())
