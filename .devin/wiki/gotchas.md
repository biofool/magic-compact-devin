# Gotchas — magic-compact-devin

2026-10 security audit: hook + mcp_server input-handling hardening.

2026-10-12 adversarial review fixes:
- `post_edit_lint`: repo-venv `ruff` lookup confined to the git root
  (a venv planted in an ancestor dir no longer executes); yaml check
  no-ops without PyYAML; `compile()` fallback instead of `py_compile`
  (no `__pycache__` writes); edited paths resolved to absolute (no `-`
  flag injection); non-dict `tool_input` guarded.
- `post_tool_hook`: corrupt caches quarantined (`.corrupt`), sessions
  capped at 100 entries, files older than 30 days swept, per-session
  token (`.token`, mode 600) issued for MCP reads.
- `post_compaction_hook`: handoff re-injected inside
  `<handoff-document>` untrusted markers, capped at 32 KB; session token
  passed to context.
- `mcp_server`: `token` arg required (constant-time compare), non-dict
  requests/params no longer crash the loop, tool errors return
  `isError`, notifications never get responses, `-32700` on parse errors.
- `.gitignore`: `.env*`, `*.key`, `*.pem`, `credentials*.json`,
  `service-account*.json`, `secrets*.json`.
- Residual risk: a venv planted *inside* a hostile repo still runs when
  editing that repo; do not work in untrusted clones.

Self-check: `python3 tests/selfcheck.py`.

## Standing rules
- Never commit secrets (`.env`, `*.key`, `credentials*.json` are gitignored).
- Never read or log secret values — key names and lengths only.
- Security fixes land reviewed-but-uncommitted first, then roll dev → main.
