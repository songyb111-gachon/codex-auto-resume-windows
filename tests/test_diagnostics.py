"""The diagnostics file: useful to read, and safe to share once read.

It is written locally and never sent. What is tested is the redaction: no conversation
id, record id, path, Windows user name or e-mail address survives into the file, while
aliases stay consistent so one recovery can still be followed through it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from codex_auto_resume import config, control, diagnostics
from codex_auto_resume.store import Store

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
KEY = "ab" * 32


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = config.Paths(Path(self.temporary.name) / "home")
        self.paths.ensure()
        with Store(self.paths.state_dir) as store:
            store.register({"thread_id": THREAD, "turn_id": TURN, "completed_at": 110.0,
                            "started_at": 105.0, "ordinal": 2, "interruption_id": KEY,
                            "reset_at": None, "limit_type": "x", "uncertain": False,
                            "category": "server_5xx"}, 100.0)
        self.paths.log_file.write_text(
            "[2026-09-12 10:00:00] %s waiting_backoff (interruption %s)\n"
            "[2026-09-12 10:00:01] opened C:\\Users\\SomeoneElse\\.codex\\state_5.sqlite for tester\n"
            "[2026-09-12 10:00:02] mail someone@example.com\n" % (THREAD, KEY[:12]), encoding="utf-8")
        self.control = control.Control(self.paths)
        for name, value in (("watcher_running", False), ("startup_enabled", False)):
            guard = patch.object(control.Control, name, return_value=value)
            guard.start()
            self.addCleanup(guard.stop)

    def bundle_text(self):
        with patch.dict(os.environ, {"USERNAME": "tester"}):
            target = diagnostics.write(self.control, Path(self.temporary.name) / "out" / "d.json")
        return target.read_text(encoding="utf-8")

    def test_nothing_identifying_survives(self):
        text = self.bundle_text()
        for secret in (THREAD, TURN, KEY, KEY[:12], "SomeoneElse", "someone@example.com", "tester",
                       str(self.paths.home)):
            self.assertNotIn(secret, text, secret)
        self.assertIn("<path>", text)
        self.assertIn("<email>", text)

    def test_aliases_are_consistent_inside_one_file(self):
        bundle = json.loads(self.bundle_text())
        record = bundle["records"][0]
        self.assertTrue(record["record"].startswith("record-"))
        self.assertIn(record["record"], [event["interruption_id"] for event in bundle["events"]])
        self.assertIn(record["thread"], "\n".join(bundle["logs"]["auto-resume.log"]))

    def test_aliases_differ_between_files(self):
        first = json.loads(self.bundle_text())["records"][0]["record"]
        second_path = Path(self.temporary.name) / "out" / "e.json"
        with patch.dict(os.environ, {"USERNAME": "tester"}):
            diagnostics.write(self.control, second_path)
        second = json.loads(second_path.read_text(encoding="utf-8"))["records"][0]["record"]
        self.assertNotEqual(first, second, "an alias must not be a stable fingerprint of the id")

    def test_it_never_overwrites_a_file(self):
        target = Path(self.temporary.name) / "exists.json"
        target.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            diagnostics.write(self.control, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
