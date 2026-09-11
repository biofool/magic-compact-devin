#!/usr/bin/env python3
"""PostToolUse hook: cache large tool outputs for later retrieval after compaction."""
import json
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".local" / "share" / "devin" / "magic-compact"

DEFAULT_THRESHOLD = {"words": 128, "chars": 1024}
AGENT_THRESHOLD = {"words": 512, "chars": 4096}

# Never cache these — they should stay in context or are redundant/reloadable
NEVER_CACHE = {
    "ask_user_question",
    "todo_write",
    "skill",
    "mcp_list_servers",
    "mcp_list_tools",
    "request_scope",
    "exit_plan_mode",
}

# Always cache these — file contents may change and become stale
ALWAYS_CACHE = {"read", "notebook_read"}

# Higher threshold for subagent outputs
AGENT_TOOLS = {"run_subagent", "read_subagent"}


def word_count(text: str) -> int:
    trimmed = text.strip()
    return len(trimmed.split()) if trimmed else 0


def exceeds_threshold(text: str, limit: dict) -> bool:
    return word_count(text) > limit["words"] or len(text) > limit["chars"]


def load_cache(session_id: str) -> dict:
    cache_file = CACHE_DIR / f"{session_id}.json"
    if not cache_file.exists():
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}


def save_cache(session_id: str, cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{session_id}.json"
    with open(cache_file, "w") as f:
        json.dump(cache, f, indent=2)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id", "")

    if not session_id or tool_name in NEVER_CACHE:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    tool_response = data.get("tool_response", {})
    output = tool_response.get("output", "")

    if not output or not isinstance(output, str):
        sys.exit(0)

    # Determine whether to cache
    if tool_name in ALWAYS_CACHE:
        should_cache = True
    elif tool_name in AGENT_TOOLS:
        should_cache = exceeds_threshold(output, AGENT_THRESHOLD)
    else:
        should_cache = exceeds_threshold(output, DEFAULT_THRESHOLD)

    if not should_cache:
        sys.exit(0)

    # Cache the output
    cache = load_cache(session_id)
    content_id = f"omitted-{cache['next_id']:03d}"
    cache["next_id"] += 1
    cache["entries"][content_id] = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "output": output,
        "timestamp": data.get("prompt_id", ""),
    }
    save_cache(session_id, cache)
    sys.exit(0)


if __name__ == "__main__":
    main()
