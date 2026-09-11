#!/usr/bin/env python3
"""MCP server for Magic Compact: exposes read_omitted_content and list_omitted_content tools."""
import json
import sys
from pathlib import Path

CACHE_DIR = Path.home() / ".local" / "share" / "devin" / "magic-compact"


def load_cache(session_id: str) -> dict:
    cache_file = CACHE_DIR / f"{session_id}.json"
    if not cache_file.exists():
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}


def handle_initialize(req: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "magic-compact", "version": "1.0.0"},
        },
    }


def handle_tools_list(req: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "result": {
            "tools": [
                {
                    "name": "read_omitted_content",
                    "description": (
                        "Read original tool input or output content that was cached "
                        "by Magic Compact during compaction. Use this to retrieve "
                        "large tool outputs that were pruned from context."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The session ID to look up cached content for.",
                            },
                            "content_id": {
                                "type": "string",
                                "description": "The omitted content ID (e.g. 'omitted-001').",
                            },
                        },
                        "required": ["session_id", "content_id"],
                    },
                },
                {
                    "name": "list_omitted_content",
                    "description": (
                        "List all cached tool outputs for a session. Returns content IDs "
                        "with tool names and output sizes."
                    ),
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "session_id": {
                                "type": "string",
                                "description": "The session ID to list cached content for.",
                            },
                        },
                        "required": ["session_id"],
                    },
                },
            ]
        },
    }


def handle_tools_call(req: dict) -> dict:
    params = req.get("params", {})
    name = params.get("name", "")
    args = params.get("arguments", {})

    if name == "read_omitted_content":
        session_id = args.get("session_id", "")
        content_id = args.get("content_id", "")
        if not session_id or not content_id:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: both session_id and content_id are required.",
                        }
                    ]
                },
            }
        cache = load_cache(session_id)
        entry = cache.get("entries", {}).get(content_id)
        if entry:
            tool_name = entry.get("tool_name", "?")
            tool_input = json.dumps(entry.get("tool_input", {}), indent=2)
            output = entry.get("output", "")
            text = (
                f"Tool: {tool_name}\n\n"
                f"Input:\n{tool_input}\n\n"
                f"Output:\n{output}"
            )
        else:
            text = f"No omitted content found for Content ID: {content_id}"
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": text}]},
        }

    elif name == "list_omitted_content":
        session_id = args.get("session_id", "")
        if not session_id:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": "Error: session_id is required.",
                        }
                    ]
                },
            }
        cache = load_cache(session_id)
        entries = cache.get("entries", {})
        if not entries:
            text = f"No cached tool outputs for session {session_id}."
        else:
            lines = [f"Cached tool outputs for session {session_id} ({len(entries)} items):"]
            for cid, entry in entries.items():
                tool = entry.get("tool_name", "?")
                size = len(entry.get("output", ""))
                lines.append(f"  {cid}: {tool} ({size} chars)")
            lines.append(
                "\nUse read_omitted_content with session_id and content_id to retrieve specific content."
            )
            text = "\n".join(lines)
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": text}]},
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "error": {"code": -32601, "message": f"Unknown tool: {name}"},
        }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")

        if method == "initialize":
            response = handle_initialize(req)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        elif method == "tools/list":
            response = handle_tools_list(req)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        elif method == "tools/call":
            response = handle_tools_call(req)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        elif method == "notifications/initialized":
            # Notification — no response needed
            pass
        elif method == "ping":
            response = {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        else:
            # Only respond if this is a request (has an id), not a notification
            if req.get("id") is not None:
                response = {
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "error": {"code": -32601, "message": f"Unknown method: {method}"},
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()


if __name__ == "__main__":
    main()
