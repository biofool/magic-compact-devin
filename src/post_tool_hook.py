#!/usr/bin/env python3
"""PostToolUse hook: cache large tool outputs for later retrieval after compaction."""
import fcntl
import hashlib
import json
import os
import re
import secrets
import sys
import tempfile
import time
from pathlib import Path

CACHE_DIR = Path(os.environ.get(
    "MAGIC_COMPACT_CACHE_DIR",
    Path.home() / ".local" / "share" / "devin" / "magic-compact"))
MAX_ENTRIES = 100          # per session; oldest content IDs evicted first
MAX_FILE_AGE_DAYS = 30     # cache/handoff/token/lock files older than this are swept

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

# --- Secret scrubbing -------------------------------------------------------
# The cache persists tool output to disk. Anything that looks like a real
# credential is redacted before it is written — the agent can re-run the tool
# if it needs the value again, and the transcript already held it live.

# KEY=value lines where the key name screams "credential". The bare-name
# branch covers PASSWORD=/SECRET=/TOKEN= with no underscore suffix.
_ENV_KEY_RE = re.compile(
    r"^(\s*(?:export\s+)?(?:"
    r"[A-Za-z_][A-Za-z0-9_]*"
    r"(?:_KEY|_TOKEN|_SECRET|_PASSWORD|_PASSWD|_PWD|_CREDENTIALS?|PRIVATE_KEY|API_KEY|AUTH_TOKEN|ACCESS_KEY)"
    r"[A-Za-z0-9_]*"
    r"|(?:PASSWORD|PASSWD|PWD|SECRET|TOKEN|CREDENTIALS|API[-_]?KEY|ACCESS[-_]?KEY)"
    r")\s*=\s*)(.+?)\s*$"
)
# JSON/YAML-ish "key": "value" / key: value forms — quoted OR unquoted values.
_JSON_KEY_RE = re.compile(
    r"((?:api[_-]?key|token|secret|password|passwd|credential|private[_-]?key|access[_-]?key)"
    r"[\"']?\s*[:=]\s*[\"']?)([^\s\"']{8,})([\"']?)",
    re.IGNORECASE,
)
# Well-known token prefixes.
_TOKEN_RE = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9_-]{16,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[A-Z0-9]{16}"
    r"|AIza[A-Za-z0-9_-]{30,}"
    r"|ya29\.[A-Za-z0-9_-]{20,}"
    r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"  # JWT
    r"|glpat-[A-Za-z0-9_-]{15,}"
    r"|pypi-[A-Za-z0-9_-]{15,}"
    r"|whsec_[A-Za-z0-9_-]{15,}"
    r"|(?:postgres|mysql|mongodb|redis|amqp)://[^\s:@/]+:[^\s@]+@"  # credentialed URI
    r")\b"
)
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
# Values that look like a credential slot but are clearly not real.
_PLACEHOLDER_RE = re.compile(
    r"^('''|\"\"|''|<[^>]*>|\$\{[^}]*\}|\$\([^)]*\)|"
    r"(?i:your[-_ ].*|xxx+|<+.*>+|changeme|change[-_ ]?me|example|test|dummy|"
    r"placeholder|redacted|<redacted>|none|null|true|false|\d+))$"
)


def _looks_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value.strip().strip("\"'")))


def _redact_env_line(match: re.Match) -> str:
    if _looks_placeholder(match.group(2)):
        return match.group(0)
    return match.group(1) + "<redacted>"


def _redact_json_pair(match: re.Match) -> str:
    if _looks_placeholder(match.group(2)):
        return match.group(0)
    return match.group(1) + "<redacted>" + match.group(3)


def scrub_obj(o):
    """Scrub every string inside a JSON-like structure (tool_input)."""
    if isinstance(o, str):
        return scrub_secrets(o)
    if isinstance(o, list):
        return [scrub_obj(x) for x in o]
    if isinstance(o, dict):
        return {k: scrub_obj(v) for k, v in o.items()}
    return o


def scrub_secrets(text: str) -> str:
    """Redact credential material from output before it is persisted."""
    text = _PEM_RE.sub(
        "-----BEGIN PRIVATE KEY-----\n<redacted by magic-compact>\n-----END PRIVATE KEY-----",
        text,
    )
    text = _TOKEN_RE.sub("<redacted>", text)
    text = _JSON_KEY_RE.sub(_redact_json_pair, text)
    return "\n".join(
        _ENV_KEY_RE.sub(_redact_env_line, line) if "=" in line else line
        for line in text.split("\n")
    )


# --- Cache IO ---------------------------------------------------------------

def word_count(text: str) -> int:
    trimmed = text.strip()
    return len(trimmed.split()) if trimmed else 0


def exceeds_threshold(text: str, limit: dict) -> bool:
    return word_count(text) > limit["words"] or len(text) > limit["chars"]


def _session_file(session_id: str, suffix: str = ".json") -> Path | None:
    """Cache path for a session; None if session_id would escape CACHE_DIR."""
    if not isinstance(session_id, str) or not session_id \
            or "/" in session_id or "\\" in session_id or ".." in session_id:
        return None
    return CACHE_DIR / f"{session_id}{suffix}"


def _digest(output: str) -> str:
    # "replace" not "surrogateescape": lone surrogates outside U+DC80–DCFF
    # (legal in JSON input) would raise UnicodeEncodeError and kill the hook.
    return hashlib.sha256(output.encode("utf-8", "replace")).hexdigest()[:16]


def _empty_cache(session_id: str) -> dict:
    return {"version": 1, "session_id": session_id, "next_id": 1, "entries": {}}


def _normalize(cache: dict) -> dict:
    """Repair older entries in place: rename misnamed fields, add digests,
    merge exact-duplicate outputs into one entry with a hit count."""
    entries = cache.setdefault("entries", {})
    by_digest: dict[str, str] = {}
    for cid in sorted(entries):
        entry = entries[cid]
        if "prompt_id" not in entry and "timestamp" in entry:
            entry["prompt_id"] = entry.pop("timestamp")
        output = entry.get("output", "")
        digest = entry.setdefault("digest", _digest(output))
        canonical = by_digest.get(digest)
        if canonical is None or entry.get("tool_name") != entries[canonical].get("tool_name"):
            by_digest.setdefault(digest, cid)
            entry.setdefault("count", 1)
        else:
            entries[canonical]["count"] = entries[canonical].get("count", 1) + entry.get("count", 1)
            del entries[cid]
    return cache


def load_cache(session_id: str) -> dict:
    cache_file = _session_file(session_id)
    if cache_file is None or not cache_file.exists():
        return _empty_cache(session_id)
    try:
        with open(cache_file) as f:
            cache = json.load(f)
    except json.JSONDecodeError:
        # Don't silently drop a corrupt cache (e.g. killed mid-write) — move it
        # aside so the next save starts clean but the data is recoverable.
        try:
            os.replace(cache_file, cache_file.with_name(cache_file.name + ".corrupt"))
        except OSError:
            pass
        return _empty_cache(session_id)
    except IOError:
        return _empty_cache(session_id)
    if not isinstance(cache, dict) or not isinstance(cache.get("entries"), dict):
        return _empty_cache(session_id)
    return _normalize(cache)


def _ensure_token(session_id: str) -> None:
    """Write a random per-session credential (0600) that the MCP server
    requires before serving cached content. The compaction hook re-injects it
    into this session's own context, so only this session's agent can read it."""
    token_file = _session_file(session_id, ".token")
    if token_file is None or token_file.exists():
        return
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=".tok-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(16))
        os.chmod(tmp, 0o600)
        os.replace(tmp, token_file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _sweep() -> None:
    """Delete cache/handoff files older than MAX_FILE_AGE_DAYS.
    Never touches *.lock (a deleted live lock breaks flock mutual exclusion)
    or *.token (a deleted credential locks the session out of its own cache)."""
    cutoff = time.time() - MAX_FILE_AGE_DAYS * 86400
    try:
        for p in CACHE_DIR.iterdir():
            try:
                if p.suffix in (".lock", ".token"):
                    continue
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink()
            except OSError:
                pass
    except OSError:
        pass


def save_cache(session_id: str, cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_DIR.stat().st_mode & 0o077:
        os.chmod(CACHE_DIR, 0o700)
    cache_file = _session_file(session_id)
    if cache_file is None:
        return
    fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(cache, f, indent=2)
        os.chmod(tmp, 0o600)
        os.replace(tmp, cache_file)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _ensure_token(session_id)
    _sweep()


TODOS_OPEN = "<!-- auto-todos -->"
TODOS_CLOSE = "<!-- /auto-todos -->"


def _format_todos(todos: list) -> str:
    mark = {"completed": "x", "in_progress": "~"}
    lines = []
    for t in todos:
        if isinstance(t, dict):
            lines.append(f"- [{mark.get(t.get('status'), ' ')}] {t.get('content', '')}")
    return "\n".join(lines)


def update_handoff_todos(session_id: str, todos: list) -> None:
    """Refresh the auto-todos block in <session>-handoff.md.

    Devin has no PreCompaction hook, so the todo list is the cheapest always-
    fresh handoff: every todo_write rewrites one marker-delimited section and
    leaves the rest of the handoff (e.g. one written by /magic-compact) intact.
    Runs under the same session lock as cache writes; atomic 0600 replace.
    """
    section = (f"{TODOS_OPEN}\n## Current todos\n\n"
               f"{_format_todos(todos)}\n{TODOS_CLOSE}")
    lock_path = _session_file(session_id, ".lock")
    handoff_file = _session_file(session_id, "-handoff.md")
    if lock_path is None or handoff_file is None:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_fd:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            existing = ""
            try:
                existing = handoff_file.read_text()
            except OSError:
                pass
            if TODOS_OPEN in existing and TODOS_CLOSE in existing:
                body = re.sub(
                    re.escape(TODOS_OPEN) + r".*?" + re.escape(TODOS_CLOSE),
                    section, existing, flags=re.DOTALL)
            else:
                body = (existing.rstrip() + "\n\n" + section + "\n") if existing else section + "\n"
            fd, tmp = tempfile.mkstemp(dir=CACHE_DIR, prefix=".ho-")
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(body)
                os.chmod(tmp, 0o600)
                os.replace(tmp, handoff_file)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def update_cache(session_id: str, update) -> dict:
    """Read-modify-write the session cache under an exclusive flock."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _session_file(session_id, ".lock")
    if lock_path is None:
        return _empty_cache(session_id)
    with open(lock_path, "a") as lock_fd:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            cache = _normalize(load_cache(session_id))
            update(cache)
            entries = cache["entries"]
            if len(entries) > MAX_ENTRIES:
                # IDs are %03d-padded so lexicographic order == age order.
                keep = sorted(entries)[-MAX_ENTRIES:]
                cache["entries"] = {c: entries[c] for c in keep}
            save_cache(session_id, cache)
            return cache
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    session_id = data.get("session_id", "")

    if not session_id:
        sys.exit(0)

    # todo_write is never cached as content — instead it keeps the
    # auto-todos block in the session handoff file fresh (see above).
    if tool_name == "todo_write":
        todos = data.get("tool_input", {}).get("todos")
        if isinstance(todos, list):
            update_handoff_todos(session_id, todos)
        sys.exit(0)

    if tool_name in NEVER_CACHE:
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

    output = scrub_secrets(output)
    tool_input = scrub_obj(tool_input)
    digest = _digest(output)
    prompt_id = data.get("prompt_id", "")

    def _add(cache: dict) -> None:
        for cid, entry in cache["entries"].items():
            if entry.get("digest") == digest and entry.get("tool_name") == tool_name:
                entry["count"] = entry.get("count", 1) + 1
                entry["prompt_id"] = prompt_id
                return
        content_id = f"omitted-{cache['next_id']:03d}"
        cache["next_id"] += 1
        cache["entries"][content_id] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "output": output,
            "prompt_id": prompt_id,
            "digest": digest,
            "count": 1,
        }

    update_cache(session_id, _add)
    sys.exit(0)


if __name__ == "__main__":
    main()
