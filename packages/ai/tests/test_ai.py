"""trackerai_ai.ask with a stand-in client: the API is never called in tests."""

import anthropic
import httpx2
import pytest

import trackerai_ai
from trackerai_ai import AiError, ask


class Response:
    def __init__(self, data):
        self.data = data

    def to_dict(self):
        return self.data


class Messages:
    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.answer, Exception):
            raise self.answer
        return Response(self.answer)


class Client:
    def __init__(self, answer):
        self.messages = Messages(answer)
        self.beta = type("Beta", (), {"messages": self.messages})()


def message(content, stop="end_turn", **usage):
    return {"model": "claude-test", "content": content, "stop_reason": stop,
            "usage": {"input_tokens": 100, "output_tokens": 20, **usage}}


def test_structured_output_and_counts():
    c = Client(message([{"type": "text", "text": '{"items": [1]}'}], cache_read_input_tokens=50))
    r = ask({"model": "m", "max_tokens": 10, "messages": []}, client=c)
    assert r.json() == {"items": [1]} and (r.tokens_in, r.tokens_out, r.model) == (150, 20, "claude-test")
    assert r.request_ms >= 0 and not r.fallback
    assert c.messages.calls[0] == {"model": "m", "max_tokens": 10, "messages": []}  # plain create, no fallback fields


def test_fallbacks_go_through_the_beta_with_the_default_form():
    c = Client(message([{"type": "text", "text": "{}"}], iterations=[{"type": "message"}, {"type": "fallback_message"}]))
    r = ask({"model": "m", "max_tokens": 10, "messages": []}, fallbacks=True, client=c)
    assert c.messages.calls[0]["betas"] == ["server-side-fallback-2026-07-01"] and c.messages.calls[0]["fallbacks"] == "default"
    assert r.fallback


def test_tool_input():
    r = ask({"model": "m", "max_tokens": 10, "messages": []},
            client=Client(message([{"type": "tool_use", "name": "labels", "input": {"labels": [2]}}], stop="tool_use")))
    assert r.tool_input("labels") == {"labels": [2]} and r.tool_input("other") == {}


@pytest.mark.parametrize("answer, code", [
    (message([], stop="refusal", ) | {"stop_details": {"category": "bio"}}, "refused"),
    (message([{"type": "text", "text": '{"a":'}], stop="max_tokens"), "truncated"),
])
def test_refused_or_cut_off_is_an_error(answer, code):
    with pytest.raises(AiError) as e:
        ask({"model": "m", "max_tokens": 10, "messages": []}, client=Client(answer))
    assert e.value.code == code


def test_api_errors_become_codes():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    with pytest.raises(AiError) as e:
        ask({"model": "m", "max_tokens": 1, "messages": []}, client=Client(anthropic.APITimeoutError(request)))
    assert e.value.code == "unreachable"
    status = anthropic.AuthenticationError("bad key", response=httpx2.Response(401, request=request), body=None)
    with pytest.raises(AiError) as e:
        ask({"model": "m", "max_tokens": 1, "messages": []}, client=Client(status))
    assert (e.value.code, e.value.status) == ("rejected", 401)


def test_invalid_json_and_no_key(monkeypatch):
    r = ask({"model": "m", "max_tokens": 1, "messages": []}, client=Client(message([{"type": "text", "text": "nope"}])))
    with pytest.raises(AiError) as e:
        r.json()
    assert e.value.code == "invalid"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not trackerai_ai.available()
    with pytest.raises(AiError) as e:
        ask({"model": "m", "max_tokens": 1, "messages": []})
    assert e.value.code == "unavailable"
