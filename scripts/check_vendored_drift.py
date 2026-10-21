#!/usr/bin/env python3
"""check_vendored_drift.py — detect drift between canonical tool scripts and
their vendored copies across repos (issue #2).

Canonical sources (in THIS repo):
    src/post_edit_lint.py   -> vendored as .claude/hooks/post_edit_lint.py
    scripts/jev_review.py   -> vendored as scripts/jev_review.py

For each target repo the script reports, per file:
    OK        byte-identical to canonical
    DRIFT     different hash (prints both __version__ stamps if present)
    MISSING   no vendored copy

Usage:
    python3 scripts/check_vendored_drift.py <repo> [<repo> ...]
    python3 scripts/check_vendored_drift.py --all <parent-dir>   # every git repo in dir
    python3 scripts/check_vendored_drift.py --print-versions     # canonical stamps

Exit 0 when nothing drifts, 1 on any DRIFT (MISSING is informational only).
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

CANON_ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    "src/post_edit_lint.py": ".claude/hooks/post_edit_lint.py",
    "scripts/jev_review.py": "scripts/jev_review.py",
}

_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_of(path: Path) -> str:
    try:
        m = _VERSION_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return "?"
    return m.group(1) if m else "unstamped"


def check_repo(repo: Path) -> int:
    drifted = 0
    for canon_rel, vend_rel in TARGETS.items():
        canon = CANON_ROOT / canon_rel
        vend = repo / vend_rel
        label = f"{repo.name}:{vend_rel}"
        if not vend.is_file():
            print(f"  MISSING  {label}")
            continue
        if sha256(vend) == sha256(canon):
            print(f"  OK       {label}")
        else:
            print(f"  DRIFT    {label}  (canon v{version_of(canon)}, vendored v{version_of(vend)})")
            drifted = 1
    return drifted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repos", nargs="*", help="repo directories to check")
    ap.add_argument("--all", metavar="DIR", help="check every git repo directly under DIR")
    ap.add_argument("--print-versions", action="store_true", help="print canonical __version__ stamps and exit")
    args = ap.parse_args()

    if args.print_versions:
        for rel in TARGETS:
            print(f"{rel}: v{version_of(CANON_ROOT / rel)}")
        return 0

    repos = [Path(r) for r in args.repos]
    if args.all:
        parent = Path(args.all)
        repos += sorted(
            p for p in parent.iterdir() if p.is_dir() and (p / ".git").exists()
        )
    if not repos:
        ap.error("no repos given — pass paths or --all DIR")

    drift = 0
    for repo in repos:
        if not (repo / ".git").exists():
            print(f"  SKIP     {repo} (not a git repo)")
            continue
        drift |= check_repo(repo.resolve())
    return drift


if __name__ == "__main__":
    sys.exit(main())
