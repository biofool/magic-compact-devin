# magic-compact-devin

A Devin CLI plugin for lossless context compaction. It pre-caches large
tool outputs to disk and re-injects a handoff document plus a retrieval
index after compaction, so the agent does not lose working context.

License: proprietary (Aiki Field) — see `LICENSE`.

## Requirements

- Devin CLI (`devin`) with plugin support.
- Python 3 on `PATH` (standard library only — no pip install needed).

## Install

From GitHub:

```bash
devin plugins install biofool/magic-compact-devin
```

From a local checkout:

```bash
devin plugins install /path/to/magic-compact-devin
```

Manage it with `devin plugins list`, `devin plugins info magic-compact`,
`devin plugins update`, `devin plugins remove`.

## How it works in a session

Once installed, everything is automatic except the compaction step:

1. **During the session** — a `PostToolUse` hook
   (`src/post_tool_hook.py`) caches large tool outputs to
   `~/.local/share/devin/magic-compact/<session-id>.json`.
   A second hook (`src/post_edit_lint.py`) lints each edited file.
2. **Before compacting** — run the `/magic-compact` skill (or ask the
   agent to). The skill writes a structured handoff document to
   `~/.local/share/devin/magic-compact/<session-id>-handoff.md`.
3. **Compact** — the user runs `/compact`. The agent cannot run it
   itself.
4. **After compaction** — a `PostCompaction` hook
   (`src/post_compaction_hook.py`) re-injects the handoff document and an
   index of cached outputs into context.
5. **Retrieval** — the agent calls the `read_omitted_content` or
   `list_omitted_content` MCP tools (served by `src/mcp_server.py`) to
   pull back any cached output by content ID. Both tools require the
   per-session `token` that the PostCompaction hook injects — other
   sessions cannot read this session's cache.

## Included skills

- `/magic-compact` — write the handoff document, then prompt you to run
  `/compact`.
- `/verify-change` — pre-completion gate: deterministic checks plus an
  adversarial review of the diff before claiming work is done.
- `/adversarial-review` — whole-repo defect hunt with file:line evidence
  and ticket triage.
- `/project-wiki` — create, update, or lint a per-repo mini-wiki under
  `.devin/wiki/`.

## Utility script

```bash
python3 src/wiki_lint.py [wiki-dir]   # default .devin/wiki
```

Checks that `INDEX.md` covers every page, links resolve, decisions are
dated, and pages stay under 200 lines (opt out with
`<!-- wiki-lint: long -->`).

## Deployment notes

- There is nothing to deploy. The plugin runs locally inside Devin CLI
  sessions. Hooks are invoked by the CLI per `hooks.json`; the MCP server
  is spawned per `.mcp.json`.
- Cache files live per session under
  `~/.local/share/devin/magic-compact/`.

## Caveats

- Cache retention is bounded: at most 100 entries per session, and files
  older than 30 days are swept on each write. Cache files are mode `0600`
  in a `0700` dir, and credential-looking content is redacted before it
  is persisted — but treat the cache as sensitive anyway.
- Everything is best-effort: hooks exit silently on malformed input, and
  a missing cache just means nothing is re-injected.
- The lint hook only runs checks for tools that exist on the machine
  (`ruff`, `php`, `node`, `shellcheck`, `gofmt`, PyYAML). Missing tools
  are skipped, not errors.
- Thresholds are fixed in `src/post_tool_hook.py` (default 128 words /
  1024 chars; 512/4096 for subagent outputs; `read`/`notebook_read` always
  cached; `todo_write`, `ask_user_question`, etc. never cached).
- The session-ID lookup in the `/magic-compact` skill walks the process
  ancestors to match a lock file in
  `~/.local/share/devin/cli/session_locks/`.
- `MAGIC_COMPACT_CACHE_DIR` overrides the cache location for all three
  components (hooks + MCP server).
- Self-check: `python3 tests/selfcheck.py` exercises the security
  invariants (venv confinement, cache perms, token gate, truncation).
