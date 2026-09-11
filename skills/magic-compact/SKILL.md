---
name: magic-compact
description: Lossless context compaction — write a handoff document then compact
argument-hint: "[N]"
triggers:
  - user
allowed-tools:
  - read
  - write
  - edit
  - exec
  - grep
  - glob
---

Perform a lossless context compaction. Follow these steps exactly:

## Step 1: Determine the session ID

Run this shell command to find the current session ID:
```bash
ls -t ~/.local/share/devin/cli/session_locks/ | head -1 | sed 's/\.lock$//'
```

## Step 2: Write a handoff document

Write a structured handoff document to `~/.local/share/devin/magic-compact/<SESSION_ID>-handoff.md` (replace `<SESSION_ID>` with the actual session ID from step 1). Create the directory if it does not exist.

The handoff document MUST include these sections:

- **Active Tasks**: What you are currently working on and the status of each task
- **Key Decisions**: Important decisions made during this session and their rationale
- **Files Modified**: List of files you have read, edited, or created, with their current state
- **Pending Work**: What remains to be done, in order of priority
- **Important Context**: Any critical context that would be lost during compaction — error messages, test outputs, API responses, design constraints, user preferences
- **Cached Tool Outputs**: Note that large tool outputs have been automatically cached by the Magic Compact PostToolUse hook. After compaction, use the `read_omitted_content` MCP tool with the session ID to retrieve them. Use `list_omitted_content` to see all cached content IDs.

## Step 3: Inform the user

Tell the user:
"Handoff document written to `~/.local/share/devin/magic-compact/<SESSION_ID>-handoff.md`. Now run `/compact` to compact the conversation. After compaction, the handoff document and cached tool output list will be automatically re-injected into your context."

Do NOT run `/compact` yourself — it is a user-side slash command that only the user can invoke.
