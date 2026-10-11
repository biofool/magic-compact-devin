#!/usr/bin/env python3
"""MCP server for Magic Compact: exposes read_omitted_content and list_omitted_content tools.

Cached outputs may contain sensitive data, so reads require the per-session
token written by post_tool_hook (<session>.token, mode 0600) and re-injected
into the owning session's context by post_compaction_hook.
"""
import hmac
import json
import os
import sys
from pathlib import Path

CACHE_DIR = Path(os.environ.get(
    "MAGIC_COMPACT_CACHE_DIR",
    Path.home() / ".local" / "share" / "devin" / "magic-compact"))


def _session_file(session_id: str, suffix: str = ".json") -> Path | None:
    """Cache path for a session; None if session_id would escape CACHE_DIR."""
    if not isinstance(session_id, str) or not session_id \
            or "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    return CACHE_DIR / f"{session_id}{suffix}"


def load_cache(session_id: str) -> dict:
    cache_file = _session_file(session_id)
    if cache_file is None or not cache_file.exists():
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}
    try:
        with open(cache_file) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}


def _authorized(session_id: str, token) -> str | None:
    """None if the caller may read this session's cache, else an error string."""
    token_file = _session_file(session_id, ".token")
    if token_file is None:
        return "invalid session_id."
    if not token_file.exists():
        return "cache is locked: no credential issued for this session yet."
    try:
        expected = token_file.read_text().strip()
    except IOError:
        return "cache credential unreadable."
    if not isinstance(token, str) or not hmac.compare_digest(token, expected):
        return "invalid session token."
    return None


def _result(req: dict, text: str, is_error: bool = False) -> dict:
    result = {"content": [{"type": "text", "text": text}]}
    if is_error:
        result["isError"] = True
    return {"jsonrpc": "2.0", "id": req.get("id"), "result": result}


def _error(req: dict, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req.get("id"),
            "error": {"code": code, "message": message}}


def _respond(req: dict, payload: dict) -> None:
    """Write the response only if req is a request (has an id) — notifications
    must not get a response even for initialize/ping."""
    if req.get("id") is not None:
        sys.stdout.write(json.dumps(payload) + "\n")
        sys.stdout.flush()


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


_TOKEN_PROP = {
    "type": "string",
    "description": "Per-session credential injected into context by the PostCompaction hook.",
}
_SESSION_PROP = {
    "type": "string",
    "description": "The session ID to look up cached content for.",
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
                            "session_id": _SESSION_PROP,
                            "content_id": {
                                "type": "string",
                                "description": "The omitted content ID (e.g. 'omitted-001').",
                            },
                            "token": _TOKEN_PROP,
                        },
                        "required": ["session_id", "content_id", "token"],
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
                            "session_id": _SESSION_PROP,
                            "token": _TOKEN_PROP,
                        },
                        "required": ["session_id", "token"],
                    },
                },
            ]
        },
    }


def handle_tools_call(req: dict) -> dict:
    params = req.get("params")
    if not isinstance(params, dict):
        return _error(req, -32602, "params must be an object")
    name = params.get("name", "")
    args = params.get("arguments")
    if not isinstance(args, dict):
        args = {}

    if name == "read_omitted_content":
        session_id = args.get("session_id", "")
        content_id = args.get("content_id", "")
        if not session_id or not content_id:
            return _result(req, "Error: both session_id and content_id are required.",
                           is_error=True)
        denied = _authorized(session_id, args.get("token"))
        if denied:
            return _result(req, f"Error: {denied}", is_error=True)
        entry = load_cache(session_id).get("entries", {}).get(content_id)
        if entry:
            tool_name = entry.get("tool_name", "?")
            tool_input = json.dumps(entry.get("tool_input", {}), indent=2)
            output = entry.get("output", "")
            text = f"Tool: {tool_name}\n\nInput:\n{tool_input}\n\nOutput:\n{output}"
        else:
            text = f"No omitted content found for Content ID: {content_id}"
        return _result(req, text)

    elif name == "list_omitted_content":
        session_id = args.get("session_id", "")
        if not session_id:
            return _result(req, "Error: session_id is required.", is_error=True)
        denied = _authorized(session_id, args.get("token"))
        if denied:
            return _result(req, f"Error: {denied}", is_error=True)
        entries = load_cache(session_id).get("entries", {})
        if not entries:
            text = f"No cached tool outputs for session {session_id}."
        else:
            lines = [f"Cached tool outputs for session {session_id} ({len(entries)} items):"]
            for cid, entry in entries.items():
                tool = entry.get("tool_name", "?")
                size = len(entry.get("output", ""))
                count = entry.get("count", 1)
                suffix = f" x{count}" if count > 1 else ""
                lines.append(f"  {cid}: {tool} ({size} chars{suffix})")
            lines.append(
                "\nUse read_omitted_content with session_id, content_id and token "
                "to retrieve specific content."
            )
            text = "\n".join(lines)
        return _result(req, text)

    else:
        return _error(req, -32601, f"Unknown tool: {name}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            # Parse errors get a response even without a request id.
            sys.stdout.write(json.dumps(
                {"jsonrpc": "2.0", "id": None,
                 "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(req, dict):
            continue

        method = req.get("method", "")

        if method == "initialize":
            _respond(req, handle_initialize(req))
        elif method == "tools/list":
            _respond(req, handle_tools_list(req))
        elif method == "tools/call":
            try:
                _respond(req, handle_tools_call(req))
            except Exception as e:
                _respond(req, _error(req, -32603, f"Internal error: {e}"))
        elif method == "ping":
            _respond(req, {"jsonrpc": "2.0", "id": req.get("id"), "result": {}})
        elif method == "notifications/initialized":
            pass
        else:
            _respond(req, _error(req, -32601, f"Unknown method: {method}"))


if __name__ == "__main__":
    main()
