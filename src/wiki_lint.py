#!/usr/bin/env python3
"""Lint a mini-wiki dir: INDEX coverage, dead links, undated decisions,
oversized pages. Usage: wiki_lint.py [wiki-dir] (default .devin/wiki)."""

import re
import sys
from pathlib import Path

MAX_PAGE_LINES = 200


def lint(wiki: Path) -> list[str]:
    problems = []
    index = wiki / "INDEX.md"
    if not index.is_file():
        return ["INDEX.md missing"]
    pages = sorted(p.name for p in wiki.glob("*.md") if p.name != "INDEX.md")
    indexed = set(re.findall(r"`([^`]+\.md)`", index.read_text()))
    for p in pages:
        if p not in indexed:
            problems.append(f"{p}: exists but not listed in INDEX.md")
    for name in indexed:
        if name not in pages:
            problems.append(f"INDEX.md lists {name} — file missing")
    for p in wiki.glob("*.md"):
        text = p.read_text()
        for link in re.findall(r"\]\(([^)]+\.md)\)", text):
            if not (wiki / link).is_file() and not link.startswith(("http", "/")):
                problems.append(f"{p.name}: dead link {link}")
        if len(text.splitlines()) > MAX_PAGE_LINES:
            problems.append(f"{p.name}: {len(text.splitlines())} lines — split it")
    dec = wiki / "decisions.md"
    if dec.is_file():
        for line in dec.read_text().splitlines():
            if line.startswith("##") and not re.search(r"\d{4}-\d{2}-\d{2}", line):
                problems.append(f"decisions.md: undated entry '{line.strip()[:60]}'")
    return problems


def main() -> int:
    wiki = Path(sys.argv[1] if len(sys.argv) > 1 else ".devin/wiki")
    if not wiki.is_dir():
        print(f"no wiki at {wiki}")
        return 1
    problems = lint(wiki)
    for p in problems:
        print(f"  {p}")
    print("wiki-lint: clean" if not problems else f"wiki-lint: {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
