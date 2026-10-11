# Uses beyond compaction recovery

The session cache (`~/.local/share/devin/magic-compact/<session>.json`,
mode 0600 since 2026-10-12) is more than a compaction fallback.

## Live heartbeat for supervised agents

`<session>.json` updates within seconds of each tool call — including
sub-agent calls. A watchdog (Devin stall check, ChaosEngine, a cron
supervisor) can use file mtime as a liveness signal that stays accurate
while a sub-agent runs, where a doc-write check goes blind.

```bash
stat -c %Y ~/.local/share/devin/magic-compact/<session>.json
```

## Per-session audit trail

Each entry records tool_name + tool_input + (secret-scrubbed) output —
exactly which commands an agent ran and what came back. Useful for
reviewing overnight runs after the fact.

## Cross-session search — `mc search`

`src/mc.py` searches all cached outputs without re-running the command:

```bash
python3 src/mc.py search "gcloud"              # all sessions
python3 src/mc.py search "ERROR" --session my-session-id
python3 src/mc.py search "status.*200" --regex -i --limit 10
```

Prints `session_id`, `content_id`, tool, size, dup count, first matching
line. File perms (0600) are the auth boundary — no token needed locally.

## Automatic handoff on every todo_write

Devin has no PreCompaction hook, so `post_tool_hook` refreshes an
`<!-- auto-todos -->` block in `<session>-handoff.md` on every
`todo_write` call. A handoff always exists; `/magic-compact` is still
available for a richer manual handoff and its sections are preserved —
the auto block only replaces itself.

## Post-edit lint in Claude Code

`src/post_edit_lint.py` accepts Claude's tool names (Edit, Write,
MultiEdit, NotebookEdit). Wired into `~/.claude/settings.json`
(2026-10-12) so it covers every repo, not just this one. Caveat: it
flags lint errors already present in a file, which can pull the agent
into unrelated fixes.
