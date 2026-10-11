---
name: adversarial-review
description: Whole-repo adversarial code review — hunt real defects (security, error handling, correctness, contracts, dead code) with file:line evidence, then triage findings into tickets. Use for "review this codebase adversarially", periodic audits, or after the post-edit lint hook is not enough.
argument-hint: "[repo-path]"
triggers:
  - user
allowed-tools:
  - exec
  - read
  - grep
  - run_subagent
  - todo_write
---

# adversarial-review — whole-repo defect hunt

Deterministic hooks catch per-edit mistakes; this is the periodic deep
pass that catches what hooks can't: contract drift, cross-file bugs,
auth gaps, silent failure chains.

## Method

1. **Orient**: read `.devin/wiki/INDEX.md` + architecture.md + gotchas.md
   first. Skip repos with no wiki — tell the user to migrate first.
2. **Fan out**: launch one `subagent_explore` per repo (background,
   parallel). For a big monorepo, split by subsystem instead.
3. **Defect classes** (tune per stack):
   - *Security*: injection sinks, auth/session gaps, secret leakage into
     logs/responses, unvalidated inputs, XSS, path traversal, open
     redirects, missing rate limits.
   - *Error handling*: silent except/catch (house rule: never fail
     silently), swallowed auth failures, unhandled None from externals.
   - *Correctness*: money/quota arithmetic, timezone/naive-datetime,
     off-by-one in limits/windows, contract drift (test doubles vs prod,
     client vs server API).
   - *Concurrency*: shared mutable state, race conditions, double-processing.
   - *Dead/broken*: unreachable code, stale imports, TODO/FIXME debt,
     config reads outside the config module.
4. **Evidence contract** — every finding must have: file:line, quoted
   snippet, severity (1=critical / 2=high / 3=medium), 1-line fix. Drop
   anything guarded elsewhere. Max ~15 findings, severity-ordered.
5. **Triage** — verify the top findings yourself before acting:
   a claim with wrong line numbers or a guard you find in 30 seconds is
   a false positive; discard it. Convert real findings to `gh` issues
   (one per finding for ≤5, or one grouped issue for more).
6. **Report** — severity histogram, the 3 worst findings verbatim,
   ticket URLs, overall risk paragraph.

## Recurrence

Monthly per active repo, or after large merges. Track the last-review
date in the repo's `.devin/wiki/decisions.md` so the next run can focus
on the delta (`git log --since`).

## What this is NOT

- Not a substitute for tests — findings get tickets, not silent fixes.
- Not style review — ponytail-review / linters own that.
- Not a fix pass — review and implement are separate sessions.
