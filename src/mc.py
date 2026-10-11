#!/usr/bin/env python3
"""mc — magic-compact cache CLI.

  mc search <pattern> [--session ID] [--limit N] [--regex] [--input]

Searches every session's cached tool outputs for a pattern — e.g. find last
week's gcloud output without re-running the command. Cached secrets are
already redacted at write time by post_tool_hook; this tool reads the same
0600 files the MCP server serves, but as the local user (no token needed —
file perms are the auth boundary).
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

CACHE_DIR = Path(os.environ.get(
    "MAGIC_COMPACT_CACHE_DIR",
    Path.home() / ".local" / "share" / "devin" / "magic-compact"))

EXCERPT_CHARS = 160


def _iter_sessions(session: str | None):
    if not CACHE_DIR.is_dir():
        return
    files = [CACHE_DIR / f"{session}.json"] if session else sorted(CACHE_DIR.glob("*.json"))
    for f in files:
        if f.is_file() and not f.name.startswith("."):
            yield f.stem, f


def _find_line(text: str, matcher) -> str:
    for line in text.splitlines():
        if matcher(line):
            s = line.strip()
            return s if len(s) <= EXCERPT_CHARS else s[:EXCERPT_CHARS] + "…"
    return ""


def cmd_search(args) -> int:
    try:
        rx = re.compile(args.pattern if args.regex else re.escape(args.pattern),
                        re.IGNORECASE if args.ignore_case else 0)
    except re.error as e:
        print(f"bad pattern: {e}", file=sys.stderr)
        return 2
    hits = 0
    for sid, f in _iter_sessions(args.session):
        try:
            cache = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for cid in sorted(cache.get("entries", {})):
            entry = cache["entries"][cid]
            hay = [entry.get("output", "")]
            if args.input:
                hay.append(json.dumps(entry.get("tool_input", "")))
            line = next((l for l in (_find_line(h, rx.search) for h in hay) if l), "")
            if not line:
                continue
            count = entry.get("count", 1)
            suffix = f" x{count}" if count > 1 else ""
            print(f"{sid}  {cid}  {entry.get('tool_name', '?')} "
                  f"({len(entry.get('output', ''))} chars{suffix})")
            print(f"    {line}")
            hits += 1
            if hits >= args.limit:
                print(f"… stopped at --limit {args.limit}")
                return 0
    if not hits:
        print("no matches")
    return 0 if hits else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="mc", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="search cached tool outputs across sessions")
    s.add_argument("pattern")
    s.add_argument("--session", help="restrict to one session id")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--regex", action="store_true", help="pattern is a regex")
    s.add_argument("-i", "--ignore-case", action="store_true")
    s.add_argument("--input", action="store_true",
                   help="also search tool_input (off by default)")
    s.set_defaults(fn=cmd_search)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
