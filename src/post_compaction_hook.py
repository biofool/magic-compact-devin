#!/usr/bin/env python3
"""PostCompaction hook: re-inject handoff document and cached content index."""
import json
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".local" / "share" / "devin" / "magic-compact"


def load_cache(session_id: str) -> dict | None:
    cache_file = CACHE_DIR / f"{session_id}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def read_handoff(session_id: str) -> str | None:
    handoff_file = CACHE_DIR / f"{session_id}-handoff.md"
    if not handoff_file.exists():
        return None
    try:
        with open(handoff_file) as f:
            return f.read()
    except IOError:
        return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = data.get("session_id", "")
    if not session_id:
        sys.exit(0)

    parts = []

    # Re-inject handoff document
    handoff = read_handoff(session_id)
    if handoff:
        parts.append(
            "## Magic Compact — Handoff Document\n\n"
            "The following handoff document was written before compaction. "
            "Use it to restore your working context:\n\n"
            f"{handoff}"
        )

    # Re-inject cached content index
    cache = load_cache(session_id)
    if cache and cache.get("entries"):
        entries = cache["entries"]
        lines = [
            "## Magic Compact — Cached Tool Outputs\n",
            "Large tool outputs from before compaction have been cached. "
            "Use the `read_omitted_content` MCP tool to retrieve them.\n",
            f"Session ID: `{session_id}`\n",
            f"Cached content ({len(entries)} items):\n",
        ]
        for cid, entry in entries.items():
            tool = entry.get("tool_name", "?")
            size = len(entry.get("output", ""))
            lines.append(f"- `{cid}`: {tool} ({size} chars)")
        lines.append("\nTo retrieve: call `read_omitted_content` with `session_id` and `content_id`.")
        lines.append("To list all: call `list_omitted_content` with `session_id`.")
        parts.append("\n".join(lines))

    if parts:
        context = "\n\n---\n\n".join(parts)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostCompaction",
                "additionalContext": context,
            }
        }
        sys.stdout.write(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
