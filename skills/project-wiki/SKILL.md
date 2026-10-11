---
name: project-wiki
description: Mini-wiki for project knowledge — a small page-set under .devin/wiki/ that replaces monolithic CLAUDE.md/AGENTS.md project sections. Use to init, read, update, or lint a repo wiki, or migrate CLAUDE.md/AGENTS.md content into one.
argument-hint: "[init|read|update|lint|migrate]"
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

# project-wiki — mini-wiki per repo

## Layout

```
.devin/wiki/
  INDEX.md         # page map — one line per page, ALWAYS current
  conventions.md   # code style, conventions, anti-patterns
  commands.md      # build / test / lint / deploy commands
  architecture.md  # repo map, key flows, entry points
  gotchas.md       # hard-won pitfalls, prior incidents
  decisions.md     # dated, append-only decision log
  runbooks.md      # repeated procedures (deploys, credential setup)
```

Six content pages is the default ceiling — a page that stops being
scannable gets split, not padded. Not every page must exist; create what
the repo needs and list only real pages in INDEX.md.

## Contract

- **INDEX.md is the router.** One line per page: `` `page.md` — what it holds ``.
  Agents scan INDEX first, then read only the page they need. An INDEX
  line that describes a page that doesn't exist, or a page with no INDEX
  line, is a defect.
- **decisions.md is append-only** — newest on top, every entry dated
  (`## 2026-10-11 — title`), never rewrite history.
- **Date-stamp staleable facts** — anything that can rot (versions,
  endpoints, IPs, quotas) carries `(<date>)`.
- **No secrets** — names, file locations, and value lengths only, per the
  global secrets rule.
- **Generated/derived data doesn't belong** — link the source file or
  script instead of copying values that will drift.

## CLAUDE.md / AGENTS.md become routers

After migration they keep: the shared global-rules block (verbatim —
don't edit), critical safety rules, the 3–5 most load-bearing commands
(build/test/deploy), and a pointer:

```markdown
## Project wiki

Project knowledge lives in `.devin/wiki/` — read `INDEX.md` and load only
the page you need. Learned facts go to the owning page + an INDEX line.
```

Everything else (architecture details, workflow conventions, history,
gotchas, runbooks) moves to the owning wiki page.

## Global wiki

Cross-project knowledge lives at `~/.config/devin/wiki/` (INDEX.md there
too). Facts that apply to more than one repo go global; repo-specific
facts stay local. When unsure, keep it local — promote on the second
cross-repo use.

## Lint

Run `python3 <plugin>/src/wiki_lint.py [wiki-dir]` — checks: INDEX lines
resolve, pages are indexed, decisions are dated, no orphaned content.
Run it after any structural wiki edit.
