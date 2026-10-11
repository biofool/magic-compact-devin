# Technology Underpinnings — magic-compact-devin

## Overview

A Devin CLI plugin (declared in `.devin-plugin/plugin.json`) built from
three standard plugin surfaces: hooks (`hooks.json`), an MCP server
(`.mcp.json`), and skills (`skills/*/SKILL.md`). All code is Python 3,
standard library only — no dependencies, no build step.

## Features and implementation

### 1. Lossless context compaction

Three pieces work together around Devin CLI's `/compact`:

- **`src/post_tool_hook.py`** — registered as a `PostToolUse` hook in
  `hooks.json` (5s timeout). Reads the hook payload (JSON) on stdin.
  Caches tool output to
  `~/.local/share/devin/magic-compact/<session-id>.json` when it exceeds
  a threshold: 128 words / 1024 chars by default, 512 / 4096 for
  `run_subagent`/`read_subagent`, always for `read`/`notebook_read`
  (file contents can go stale), never for a hardcoded list
  (`NEVER_CACHE`: `todo_write`, `ask_user_question`, `skill`, MCP listing
  tools, `request_scope`, `exit_plan_mode`). Entries are keyed
  `omitted-NNN` via a `next_id` counter.
- **`src/post_compaction_hook.py`** — registered as a `PostCompaction`
  hook. Reads `<session-id>-handoff.md` and the JSON cache, then emits a
  `hookSpecificOutput.additionalContext` JSON payload on stdout that
  Devin CLI injects back into the post-compaction context: the handoff
  text plus a one-line index per cached entry (ID, tool name, size).
- **`skills/magic-compact/SKILL.md`** — the user-facing skill. Finds the
  session ID by taking the newest file in
  `~/.local/share/devin/cli/session_locks/`, writes a structured handoff
  document (Active Tasks, Key Decisions, Files Modified, Pending Work,
  Important Context), then tells the user to run `/compact` — the skill
  deliberately does not compact itself.

### 2. MCP retrieval server

**`src/mcp_server.py`** — a hand-rolled JSON-RPC 2.0 server over stdio
(protocol version `2024-11-05`), spawned per `.mcp.json`. Handles
`initialize`, `tools/list`, `tools/call`, `ping`, and
`notifications/initialized`; unknown methods get `-32601`. Exposes two
tools that read the same cache files the hooks write:

- `read_omitted_content(session_id, content_id)` — returns tool name,
  input, and full output for one entry.
- `list_omitted_content(session_id)` — returns the index of all entries.

### 3. Post-edit lint hook

**`src/post_edit_lint.py`** — a second `PostToolUse` hook (30s timeout)
that fires on edit tools (`edit`, `write`, `notebook_edit`,
`str_replace`, and the Claude-Code names `Edit`, `Write`, `MultiEdit`,
`NotebookEdit`). Dispatches one fast check per file type, using
`shutil.which` so every check no-ops when the tool is absent:

| File type | Check |
|---|---|
| `.py` | `ruff check` — prefers `<repo>/.venv/bin/ruff` (also `backend/.venv`, `venv/`), falls back to PATH `ruff`, then `py_compile` |
| `.php` | `php -l` |
| `.js/.mjs/.cjs` | `node --check` |
| `.sh/.bash` | `bash -n`, then `shellcheck -S error` if installed |
| `.json` | `python -m json.tool` |
| `.go` | `gofmt -l` (reports "not gofmt-clean") |
| `.yml/.yaml` | `yaml.safe_load` via PyYAML |

Findings go to stderr with exit code 2 so the agent sees them and can
fix its own edit. Output is truncated at 1200 chars; subprocesses time
out at 20s. An identical vendored copy lives at
`.claude/hooks/post_edit_lint.py` and is wired for Claude Code via
`.claude/settings.json` (matcher `Edit|Write|MultiEdit|NotebookEdit`) —
the repo dogfoods its own hook.

### 4. Quality-gate skills

Markdown skills with YAML frontmatter (`name`, `description`,
`argument-hint`, `triggers`, `allowed-tools`):

- **`skills/verify-change/SKILL.md`** — ordered pre-completion gate:
  check lint-hook findings, run the repo's own test/lint/build gates,
  then an adversarial `git diff` review (edge cases, callers, leftovers,
  silent failures), then an honest report of what was and was not
  verified.
- **`skills/adversarial-review/SKILL.md`** — whole-repo review playbook:
  fan out subagents per repo/subsystem, hunt five defect classes
  (security, error handling, correctness, concurrency, dead code),
  require file:line evidence per finding, triage top findings into
  `gh` issues.
- **`skills/project-wiki/SKILL.md`** — mini-wiki convention for
  `.devin/wiki/` (INDEX.md router, append-only dated decisions.md, six
  content pages max), plus rules for migrating content out of
  CLAUDE.md/AGENTS.md.

### 5. Wiki lint utility

**`src/wiki_lint.py`** — standalone script (not a hook). Validates a
wiki directory: every `*.md` page is listed in `INDEX.md` and vice
versa, no dead `.md` links, `decisions.md` headings carry a
`YYYY-MM-DD` date, pages stay under 200 lines unless they contain the
`<!-- wiki-lint: long -->` opt-out marker. Exit 1 on findings.

### 6. Rules

`AGENTS.md` carries a single always-on rule: chat replies use ~80%
Simplified Technical English. Devin CLI picks it up as part of the
plugin.

## Shared implementation details

- **Session-keyed JSON cache**: `load_cache`/`save_cache` in
  `post_tool_hook.py` and `mcp_server.py` share the same on-disk shape:
  `{version, session_id, next_id, entries}`.
- **Path-traversal guard**: `_session_file()` in all three Python files
  rejects `session_id` values containing `/`, `\`, or `..`, so cache
  paths cannot escape `~/.local/share/devin/magic-compact/`.
- **Fail-quiet hooks**: hooks exit 0 on malformed stdin or missing files
  — a broken hook must never block the session. The lint hook uses exit
  2 only when it has real findings to report.
- **Repo layout**:
  - `.devin-plugin/plugin.json` — plugin manifest (name, version).
  - `hooks.json`, `.mcp.json` — hook and MCP wiring.
  - `src/` — four Python files (two compaction hooks, lint hook, MCP
    server, wiki linter).
  - `skills/` — four skills.
  - `.claude/` — Claude Code settings + vendored lint hook.
  - `wiki/` — this repo's own mini-wiki (Home, Architecture,
    Development, Security pages).
