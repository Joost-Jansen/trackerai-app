# trackerai-ai

One Claude client for every trackerai backend: wealth-tracker's transaction labelling and health-tracker's meal photos
call the Messages API through here, with the official SDK (`anthropic`, pinned in `pyproject.toml`).

```python
from trackerai_ai import AiError, ask, available

if available():  # ANTHROPIC_API_KEY is set
    result = ask(body, timeout=30, retries=1, fallbacks=True)
    data = result.json()  # structured output (output_config.format)
    labels = result.tool_input("labels")  # or what Claude filled in for a tool
    log(result.model, result.request_ms, result.tokens_in, result.tokens_out)
```

`body` is the request as the Messages API documents it; the app decides the model, the prompt and what to store. A
refused or cut-off answer raises `AiError` (`refused`, `truncated`) instead of returning half an answer; network and
API errors raise it too (`unreachable`, `rejected`, `unavailable` without a key). `fallbacks=True` asks the API to re-run
a refused request on Anthropic's recommended model for that refusal (`fallbacks: "default"`, Claude API only).

Install it next to the other shared packages (both apps' Dockerfiles and CI do): `pip install packages/ai`.
Tests: `pip install -e "packages/ai[test]" && python -m pytest -q packages/ai/tests` (the API is never called).
