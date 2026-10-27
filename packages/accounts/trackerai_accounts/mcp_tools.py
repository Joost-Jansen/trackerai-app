"""What every TrackerAI MCP server says about its tools, the same in each app.

`describe` adds to each tool:
  * MCP tool annotations: `readOnlyHint` for a tool that changes nothing, `destructiveHint` for one that deletes or
    overwrites, `openWorldHint` for one that reaches outside the tracker (a sync with a bank or a watch). Assistants
    use them to ask before a change: Gemini Enterprise asks for confirmation on a destructive tool, Claude and
    ChatGPT show which tools only read.
  * with OAuth on, the scope a tool needs (`securitySchemes`), so an assistant can ask for write access only when a
    tool needs it.
The apps keep their own lists of which tools write; this only describes them.
"""

from __future__ import annotations


def describe(
    tools: list[dict],
    app: str,
    writes: set[str],
    destructive: set[str] = frozenset(),
    open_world: set[str] = frozenset(),
    oauth: bool = False,
) -> list[dict]:
    out = []
    for t in tools:
        name = t["name"]
        writing = name in writes
        tool = {
            **t,
            "annotations": {
                **(t.get("annotations") or {}),
                "title": (t.get("annotations") or {}).get("title") or name.replace("_", " ").capitalize(),
                "readOnlyHint": not writing,
                "destructiveHint": writing and name in destructive,
                "openWorldHint": name in open_world,
            },
        }
        if oauth:
            tool["securitySchemes"] = [{"type": "oauth2", "scopes": [f"{app}:write" if writing else f"{app}:read"]}]
        out.append(tool)
    return out
