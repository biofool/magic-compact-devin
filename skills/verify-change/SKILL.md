---
name: verify-change
description: Adversarial pre-completion gate — deterministic checks plus a self-review of the diff before claiming a change is done. Use after any non-trivial edit, before committing, or when told "verify".
argument-hint: ""
triggers:
  - user
allowed-tools:
  - exec
  - read
  - grep
  - edit
---

# verify-change — don't trust, verify

The goal is to catch AI slop before it enters the codebase. Run this gate
before reporting a task complete or committing. It is cheap and ordered —
stop at the first failure, fix, restart.

## 1. Deterministic checks (run, don't assume)

- Lint hooks already fire post-edit (plugin `post_edit_lint` /
  `.claude/hooks/post_edit_lint.py`). If any finding was emitted, it is a
  defect — fix it, do not rationalize it.
- Run the repo's own gates from its CLAUDE.md/AGENTS.md: tests, typecheck,
  lint, build. If the repo documents none, run the closest cheap check
  (`pytest`, `php -l`, `node --check`, `bash -n`, `go vet`, ruff).
- A claim of "works" without a command output proving it is not verified.

## 2. Adversarial diff review

`git diff` (and `git status` for untracked). For every hunk, ask:

- Does this do what the user asked — all of it, nothing extra?
- Edge cases: empty input, missing file, network down, zero/negative,
  non-ASCII, concurrent callers?
- Callers: did I grep every caller of what I changed? Signatures, imports,
  fixtures, docs that reference it?
- Leftovers: debug prints, TODOs, commented-out code, hardcoded paths
  that belong in env/config, secrets or tokens?
- Silent failures: every caught exception logged or deliberately
  documented? (house rule: never fail silently)

## 3. Honest report

State what was verified and HOW (command + result), and what was skipped
and why. If something could not be verified, say so explicitly — do not
round up to "done".
