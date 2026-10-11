#!/usr/bin/env python3
"""Assert-based self-check for magic-compact security fixes.

Run: python3 tests/selfcheck.py
Exercises: venv-ruff confinement to git root, py syntax fallback without
__pycache__ writes, cache perms/quarantine/eviction/token, compaction
untrusted wrapping, MCP token gate and malformed-input handling.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import post_tool_hook as pth
import post_compaction_hook as pch
import mcp_server as mcp
import post_edit_lint as pel

failures = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        failures.append(name)


tmp = Path(tempfile.mkdtemp(prefix="mc-selfcheck-"))
CACHE = tmp / "cache"
pth.CACHE_DIR = pch.CACHE_DIR = mcp.CACHE_DIR = CACHE
# Subprocesses can't see module patches — isolate via the env override.
ENV = {**os.environ, "MAGIC_COMPACT_CACHE_DIR": str(CACHE)}

# --- _ruff: ancestor venv above the git root must not execute ---------------
outer = tmp / "outer"
repo = outer / "proj"
(repo / "pkg").mkdir(parents=True)
(repo / ".git").mkdir()
marker = outer / "PWNED"
evil = outer / ".venv" / "bin"
evil.mkdir(parents=True)
evil_ruff = evil / "ruff"
evil_ruff.write_text(f"#!/bin/sh\ntouch {marker}\n")
evil_ruff.chmod(0o755)
edited = repo / "pkg" / "m.py"
edited.write_text("x = 1\n")
pel._ruff(edited.resolve())
check("ancestor-venv ruff not executed", not marker.exists())

# --- py fallback: syntax error reported, no __pycache__ written -------------
bad = repo / "pkg" / "bad.py"
bad.write_text("def broken(:\n")
msgs = pel._py_check(bad.resolve())
check("syntax error reported", any("line" in m for m in msgs))
check("no __pycache__ side effect", not (repo / "pkg" / "__pycache__").exists())

# --- lint hook main(): non-dict tool_input, missing file --------------------
def run_hook(payload):
    return subprocess.run([sys.executable, str(SRC / "post_edit_lint.py")],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=ENV)

r = run_hook({"tool_name": "write", "tool_input": "not-a-dict"})
check("non-dict tool_input exits 0", r.returncode == 0)
r = run_hook({"tool_name": "write", "tool_input": {"file_path": "/nonexistent/x.py"}})
check("missing file exits 0", r.returncode == 0)

# --- cache: perms, token, quarantine, eviction -------------------------------
sid = "test-session-1"
big = "word " * 200


def run_post_tool(payload):
    return subprocess.run([sys.executable, str(SRC / "post_tool_hook.py")],
                          input=json.dumps(payload), capture_output=True,
                          text=True, env=ENV)

r = run_post_tool({"tool_name": "exec", "session_id": sid, "prompt_id": "p1",
                   "tool_input": {}, "tool_response": {"output": big}})
check("post_tool_hook exits 0", r.returncode == 0)
cache_file = CACHE / f"{sid}.json"
token_file = CACHE / f"{sid}.token"
check("cache file written", cache_file.exists())
check("cache file mode 600", stat.S_IMODE(cache_file.stat().st_mode) == 0o600)
check("cache dir mode 700", stat.S_IMODE(pth.CACHE_DIR.stat().st_mode) == 0o700)
check("token file written 600",
      token_file.exists() and stat.S_IMODE(token_file.stat().st_mode) == 0o600)
token = token_file.read_text().strip()

# scrub: emit a token-looking output, confirm redaction persisted
r = run_post_tool({"tool_name": "exec", "session_id": sid, "prompt_id": "p2",
                   "tool_input": {},
                   "tool_response": {"output": "API_KEY=sk-AbCdEfGhIjKlMnOpQrStUvWx\n" + big}})
cache = json.loads(cache_file.read_text())
check("token-shaped secret redacted",
      all("sk-AbCdEf" not in e.get("output", "") for e in cache["entries"].values()))

# corrupt cache is quarantined, not silently dropped
cache_file.write_text("{broken json")
loaded = pth.load_cache(sid)
check("corrupt cache -> empty", loaded["entries"] == {})
check("corrupt file quarantined", (CACHE / f"{sid}.json.corrupt").exists())

# eviction: cap at MAX_ENTRIES
pth.update_cache(sid, lambda c: c["entries"].update(
    {f"omitted-{i:03d}": {"tool_name": "exec", "output": "x" * 10}
     for i in range(200, 200 + pth.MAX_ENTRIES + 50)}))
cache = json.loads(cache_file.read_text())
check("entries capped at MAX_ENTRIES", len(cache["entries"]) <= pth.MAX_ENTRIES)

# --- compaction hook: untrusted wrap, handoff cap, token in context ---------
handoff = CACHE / f"{sid}-handoff.md"
handoff.write_text("do stuff\n" * 5000)  # > 32 KB
r = subprocess.run([sys.executable, str(SRC / "post_compaction_hook.py")],
                   input=json.dumps({"session_id": sid}), capture_output=True,
                   text=True, env=ENV)
out = json.loads(r.stdout)
ctx = out["hookSpecificOutput"]["additionalContext"]
check("handoff wrapped untrusted", "<handoff-document>" in ctx)
check("handoff truncated", "truncated" in ctx)
check("token injected for session", token in ctx)

# --- MCP server: token gate + malformed input --------------------------------
req = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
       "params": {"name": "list_omitted_content", "arguments": {"session_id": sid}}}
resp = mcp.handle_tools_call(req)
check("MCP rejects missing token", resp["result"].get("isError") is True)
resp = mcp.handle_tools_call({**req, "params": {"name": "list_omitted_content",
                              "arguments": {"session_id": sid, "token": "wrong"}}})
check("MCP rejects wrong token", resp["result"].get("isError") is True)
resp = mcp.handle_tools_call({**req, "params": {"name": "list_omitted_content",
                              "arguments": {"session_id": sid, "token": token}}})
check("MCP accepts correct token",
      resp["result"].get("isError") is not True
      and "content" in resp["result"])
resp = mcp.handle_tools_call({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": "not-a-dict"})
check("MCP non-dict params -> error", "error" in resp)
resp = mcp.handle_tools_call({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                              "params": {"name": "read_omitted_content",
                                         "arguments": {"session_id": "../x", "content_id": "y",
                                                       "token": token}}})
check("MCP traversal session_id rejected", resp["result"].get("isError") is True)

# non-dict JSON-RPC line must not crash the server loop
proc = subprocess.run([sys.executable, str(SRC / "mcp_server.py")],
                      input='[1,2,3]\n"str"\n{"jsonrpc":"2.0","id":9,"method":"ping"}\n',
                      capture_output=True, text=True, timeout=10, env=ENV)
check("MCP survives non-dict requests", proc.returncode == 0)
check("ping answered", '"id": 9' in proc.stdout or '"id":9' in proc.stdout)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("all checks passed")
