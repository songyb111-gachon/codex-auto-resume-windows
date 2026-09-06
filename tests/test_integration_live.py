"""Opt-in, READ-ONLY integration checks against the real local environment.

Set CODEX_AR_LIVE=1 to run. These tests NEVER send a continuation, never queue,
never write to any Codex database, and never touch any conversation. They only
exercise the real read paths: official-binary discovery, desktop app pairing,
loaded-state classification of existing writer locks, live usage read, and a
read-only detection pass over the real history. This satisfies the rule that any
integration touching a real conversation must use a disposable/test thread only:
here nothing is delivered at all.

The one delivery proof (a fixed marker to a disposable test thread) was completed
and recorded in Phase 2A; it is intentionally NOT repeated here, both to avoid a
duplicate resume and because that disposable thread is currently notLoaded.
"""
from __future__ import annotations

import os
from pathlib import Path
import unittest

from codex_auto_resume import config
from codex_auto_resume import failures as failure_kinds
from codex_auto_resume.windows import Backend, Mutex, StopEvent

LIVE = os.environ.get("CODEX_AR_LIVE") == "1"


@unittest.skipUnless(LIVE and os.name == "nt", "set CODEX_AR_LIVE=1 on Windows to run live read-only checks")
class LiveReadOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = config.codex_home()

        def compatible(path):
            Backend(cls.home, path)._compatible()

        cls.exe = config.discover_codex_exe(None, compatible)
        cls.backend = Backend(cls.home, cls.exe)

    def test_official_binary_discovered_and_version_pinned(self):
        # discover_codex_exe already ran _compatible(); a second call must be cached/consistent.
        self.backend._compatible()
        self.assertTrue(str(self.exe).lower().endswith("codex.exe"))

    def test_app_pairing_is_unambiguous_or_absent(self):
        identity = self.backend.app_identity()
        if identity is None:
            self.skipTest("ChatGPT app not running; pairing check not applicable")
        self.assertIn("chatgpt.exe", identity["path"])
        self.assertEqual(identity["server"]["path"], str(self.exe).lower())
        self.assertGreaterEqual(identity["server"]["created"], identity["created"])

    def test_loaded_state_classification_of_existing_locks(self):
        identity = self.backend.app_identity()
        if identity is None:
            self.skipTest("ChatGPT app not running")
        lock_dir = self.home / "thread-writer-locks"
        locks = [p for p in lock_dir.glob("*.lock") if not p.name.startswith(".")] if lock_dir.is_dir() else []
        classifications = set()
        for lock in locks[:20]:
            state = self.backend.loaded(lock.stem, identity)
            self.assertIn(state, ("loaded", "notLoaded", "unknown"))
            classifications.add(state)
        # A random non-existent thread id must be notLoaded (no holder), never a false 'loaded'.
        absent = self.backend.loaded("00000000-0000-7000-8000-000000000000", identity)
        self.assertIn(absent, ("notLoaded", "unknown"))
        self.assertNotEqual(absent, "loaded")

    def test_live_usage_read_is_shape_safe(self):
        usage = self.backend.usage()
        self.assertIn(usage.get("available"), (True, False, None))
        self.assertIn("reason", usage)
        # No account identifiers or credit fields leak into the parsed result.
        text = repr(usage)
        for forbidden in ("accountId", "token", "upsell", "email"):
            self.assertNotIn(forbidden, text)

    def test_detection_pass_is_read_only_and_never_sends(self):
        import time
        from codex_auto_resume.source import LocalSource
        source = LocalSource(self.home)
        # Reads the real history read-only; returns eligible interruptions (possibly none).
        failures = source.latest_failures(time.time() - 30 * 86400)
        self.assertIsInstance(failures, list)
        for record in failures:
            self.assertEqual(len(record["thread_id"]), 36)
            self.assertTrue(failure_kinds.is_recoverable(record["category"]))

    def test_single_instance_mutex_and_stop_event_roundtrip(self):
        # Named-mutex acquisition works live; cross-PROCESS single-instance refusal is
        # covered by tests.test_engine.SingleInstanceTests (a Windows mutex is re-entrant
        # within one thread, so a same-thread re-acquire is expected to succeed).
        name = str(Path(self.home) / "live-selftest")
        with Mutex(name, timeout=0) as mutex:
            self.assertIsNotNone(mutex.handle)
        with StopEvent(name) as event:
            self.assertFalse(event.wait(0.05))
            self.assertTrue(StopEvent(name).signal())
            self.assertTrue(event.wait(1))


if __name__ == "__main__":
    unittest.main()
