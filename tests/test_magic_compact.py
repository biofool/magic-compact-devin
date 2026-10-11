#!/usr/bin/env python3
"""Tests for magic-compact hooks: secret scrubbing, dedup, locking, perms,
index capping, session-file traversal guard."""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import post_compaction_hook  # noqa: E402
import post_tool_hook  # noqa: E402


class CacheDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._orig = post_tool_hook.CACHE_DIR
        post_tool_hook.CACHE_DIR = self.dir

    def tearDown(self):
        post_tool_hook.CACHE_DIR = self._orig
        self._tmp.cleanup()

    def _add(self, session_id: str, output: str, tool: str = "read",
             prompt_id: str = "p1") -> dict:
        """Simulate one main()-time cache write (without stdin plumbing)."""
        output = post_tool_hook.scrub_secrets(output)
        digest = post_tool_hook._digest(output)

        def _up(cache):
            for _cid, entry in cache["entries"].items():
                if entry.get("digest") == digest and entry.get("tool_name") == tool:
                    entry["count"] = entry.get("count", 1) + 1
                    entry["prompt_id"] = prompt_id
                    return
            cid = f"omitted-{cache['next_id']:03d}"
            cache["next_id"] += 1
            cache["entries"][cid] = {
                "tool_name": tool, "tool_input": {}, "output": output,
                "prompt_id": prompt_id, "digest": digest, "count": 1,
            }

        return post_tool_hook.update_cache(session_id, _up)


class TestScrub(unittest.TestCase):
    def test_env_key_redacted(self):
        out = post_tool_hook.scrub_secrets("GEMINI_API_KEY=AIzaSyD-realvalue1234567890")
        self.assertIn("<redacted>", out)
        self.assertNotIn("realvalue", out)

    def test_env_placeholder_kept(self):
        line = "GEMINI_API_KEY=<your-key-here>"
        self.assertEqual(post_tool_hook.scrub_secrets(line), line)

    def test_env_numeric_config_kept(self):
        line = "SMTP_PORT=587"
        self.assertEqual(post_tool_hook.scrub_secrets(line), line)

    def test_env_nonsecret_key_kept(self):
        line = "GCP_PROJECT=quantum-aikido-coaching"
        self.assertEqual(post_tool_hook.scrub_secrets(line), line)

    def test_pem_redacted(self):
        pem = ("-----BEGIN RSA PRIVATE KEY-----\n"
               "MIIEpAIBAAKCAQEA7secretkeymaterial\n"
               "-----END RSA PRIVATE KEY-----")
        out = post_tool_hook.scrub_secrets(pem)
        self.assertNotIn("secretkeymaterial", out)
        self.assertIn("<redacted by magic-compact>", out)

    def test_token_prefixes(self):
        for tok in ("sk-abcdefghijklmnop1234", "ghp_" + "a" * 36,
                    "xoxb-1234567890-abc", "AKIAIOSFODNN7EXAMPLE"):
            self.assertNotIn(tok, post_tool_hook.scrub_secrets(f"token: {tok} done"))

    def test_json_pair_redacted(self):
        out = post_tool_hook.scrub_secrets('{"api_key": "realsecretvalue123"}')
        self.assertIn("<redacted>", out)
        self.assertNotIn("realsecretvalue", out)

    def test_json_placeholder_kept(self):
        line = '"password": "changeme"'
        self.assertEqual(post_tool_hook.scrub_secrets(line), line)


class TestSessionFile(unittest.TestCase):
    def test_traversal_rejected(self):
        for bad in ("../etc", "a/b", "..", "x\\y", ""):
            self.assertIsNone(post_tool_hook._session_file(bad))

    def test_normal_id_ok(self):
        self.assertIsNotNone(post_tool_hook._session_file("tough-tangerine"))


class TestDedupAndNormalize(CacheDirTestCase):
    def test_duplicate_output_merges(self):
        self._add("s1", "x" * 2000)
        cache = self._add("s1", "x" * 2000)
        self.assertEqual(len(cache["entries"]), 1)
        entry = next(iter(cache["entries"].values()))
        self.assertEqual(entry["count"], 2)
        self.assertEqual(entry["prompt_id"], "p1")

    def test_distinct_outputs_kept(self):
        self._add("s1", "a" * 2000)
        cache = self._add("s1", "b" * 2000)
        self.assertEqual(len(cache["entries"]), 2)

    def test_normalize_renames_timestamp(self):
        cache = {"next_id": 2, "entries": {"omitted-001": {
            "tool_name": "read", "output": "y", "timestamp": "pid-9"}}}
        post_tool_hook._normalize(cache)
        entry = cache["entries"]["omitted-001"]
        self.assertEqual(entry["prompt_id"], "pid-9")
        self.assertNotIn("timestamp", entry)
        self.assertIn("digest", entry)

    def test_normalize_merges_legacy_dupes(self):
        cache = {"next_id": 3, "entries": {
            "omitted-001": {"tool_name": "read", "output": "same"},
            "omitted-002": {"tool_name": "read", "output": "same"},
        }}
        post_tool_hook._normalize(cache)
        self.assertEqual(list(cache["entries"]), ["omitted-001"])
        self.assertEqual(cache["entries"]["omitted-001"]["count"], 2)


class TestConcurrencyAndPerms(CacheDirTestCase):
    def test_concurrent_writers_no_lost_entries(self):
        errors = []

        def worker(i):
            try:
                for j in range(5):
                    self._add("s1", f"payload-{i}-{j}-" + "z" * 500)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        cache = post_tool_hook.load_cache("s1")
        self.assertEqual(len(cache["entries"]), 20)

    def test_file_perms(self):
        self._add("s1", "x" * 2000)
        cache_file = self.dir / "s1.json"
        lock_file = self.dir / "s1.lock"
        self.assertEqual(oct(cache_file.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(lock_file.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(self.dir.stat().st_mode & 0o777), "0o700")

    def test_dir_mode_repaired(self):
        self.dir.mkdir(exist_ok=True)
        os.chmod(self.dir, 0o775)
        self._add("s1", "x" * 2000)
        self.assertEqual(oct(self.dir.stat().st_mode & 0o777), "0o700")


class TestIndexCap(unittest.TestCase):
    def test_index_capped(self):
        entries = {f"omitted-{i:03d}": {"tool_name": "read", "output": "x" * 100}
                   for i in range(1, 31)}
        lines = post_compaction_hook.index_lines(entries)
        shown = [ln for ln in lines if ln.startswith("- `")]
        self.assertEqual(len(shown), post_compaction_hook.MAX_INDEX_ENTRIES)
        self.assertTrue(any("most recent" in ln for ln in lines))
        self.assertIn("omitted-030", "\n".join(shown))

    def test_index_under_cap(self):
        entries = {"omitted-001": {"tool_name": "read", "output": "x"}}
        lines = post_compaction_hook.index_lines(entries)
        self.assertEqual(len([ln for ln in lines if ln.startswith("- `")]), 1)

    def test_index_shows_count(self):
        entries = {"omitted-001": {"tool_name": "read", "output": "x", "count": 3}}
        self.assertIn("x3", post_compaction_hook.index_lines(entries)[-1])


if __name__ == "__main__":
    unittest.main()
