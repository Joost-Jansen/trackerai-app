"""One Claude client for every trackerai backend: health-tracker's photo analysis (Voeding) and wealth-tracker's
transaction labelling call the Messages API through here.

    from trackerai_ai import AiError, ask, available

    if available():
        result = ask({"model": "...", "max_tokens": 2000, "messages": [...], "output_config": {...}}, timeout=30, retries=1)
        data = result.json()           # structured output (output_config.format)
        data = result.tool_input("x")  # or what Claude filled in for tool x

What it does for every caller: the official SDK (`anthropic`) with the key from ANTHROPIC_API_KEY, a timeout and a
number of retries per call, the time and the tokens it took (`Result`, for a caller's own log), refusals and cut-off
answers as errors instead of half an answer, and one error type with a code an app can translate. `fallbacks=True`
asks the API to re-run a refused request on Anthropic's recommended model for that refusal (server side, Claude API
only), for the models that take it.

The app decides what to ask, which model and what to store; nothing here knows about meals or transactions.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field

import anthropic

FALLBACK_BETA = "server-side-fallback-2026-07-01"  # with fallbacks: "default" (the array form takes another header)

_lock = threading.Lock()
_clients: dict[tuple[float, int], anthropic.Anthropic] = {}


class AiError(Exception):
    """`code`: unavailable (no API key), unreachable (network, timeout), rejected (the API said no: key, credit, a bad
    request), refused (Claude declined), truncated (hit max_tokens), invalid (no usable answer in the response)."""

    def __init__(self, code: str, detail: str = "", status: int | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail, self.status = code, detail, status


@dataclass
class Result:
    message: dict  # the response as the API returned it (content, usage, stop_reason, model, ...)
    model: str
    request_ms: int
    tokens_in: int
    tokens_out: int
    stop_reason: str | None
    fallback: bool = False  # another model answered after a refusal
    extra: dict = field(default_factory=dict)

    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.message.get("content", []) if b.get("type") == "text")

    def json(self) -> dict:
        """The structured output (output_config.format json_schema): the text as JSON."""
        try:
            value = json.loads(self.text())
        except ValueError as e:
            raise AiError("invalid", "the answer is not JSON") from e
        if not isinstance(value, dict):
            raise AiError("invalid", "the answer is not a JSON object")
        return value

    def tool_input(self, name: str) -> dict:
        """What Claude filled in for tool `name` ({} when it did not use it)."""
        for block in self.message.get("content", []):
            if block.get("type") == "tool_use" and block.get("name") == name:
                return block.get("input") or {}
        return {}


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _client(timeout: float, retries: int) -> anthropic.Anthropic:
    key = (timeout, retries)
    with _lock:
        if key not in _clients:
            _clients[key] = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"), timeout=timeout, max_retries=retries)
        return _clients[key]


def ask(body: dict, *, timeout: float = 60, retries: int = 1, fallbacks: bool = False, client=None) -> Result:
    """One Messages API request. `body` is the request as the API documents it (model, max_tokens, system, messages,
    tools, output_config, ...). `client`: an object with `.messages.create` / `.beta.messages.create` (tests).
    Raises AiError; never returns a refused or cut-off answer."""
    if client is None:
        if not available():
            raise AiError("unavailable", "no ANTHROPIC_API_KEY on this server")
        client = _client(timeout, retries)
    started = time.monotonic()
    try:
        if fallbacks:
            response = client.beta.messages.create(**body, betas=[FALLBACK_BETA], fallbacks="default")
        else:
            response = client.messages.create(**body)
    except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:  # timeout first: it is a connection error too
        raise AiError("unreachable", type(e).__name__) from e
    except anthropic.APIStatusError as e:
        raise AiError("rejected", f"{e.status_code} {getattr(e, 'message', '')}"[:300], e.status_code) from e
    elapsed = round((time.monotonic() - started) * 1000)
    message = response.to_dict() if hasattr(response, "to_dict") else dict(response)
    usage = message.get("usage") or {}
    iterations = usage.get("iterations") or []
    result = Result(
        message=message,
        model=message.get("model") or body.get("model", ""),
        request_ms=elapsed,
        tokens_in=int(usage.get("input_tokens") or 0)
        + int(usage.get("cache_read_input_tokens") or 0)
        + int(usage.get("cache_creation_input_tokens") or 0),
        tokens_out=int(usage.get("output_tokens") or 0),
        stop_reason=message.get("stop_reason"),
        fallback=any((it or {}).get("type") == "fallback_message" for it in iterations),
    )
    if result.stop_reason == "refusal":
        category = ((message.get("stop_details") or {}).get("category")) or ""
        raise AiError("refused", category)
    if result.stop_reason == "max_tokens":
        raise AiError("truncated", f"max_tokens {body.get('max_tokens')}")
    return result
