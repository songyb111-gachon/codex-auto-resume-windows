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

    def test_it_says_whether_the_pieces_outside_the_state_file_are_there(self):
        """The four questions asked first of a machine where nothing is happening.

        A sign-in entry that is missing, a notification handler that belongs to another
        copy, an MCP launcher that was never unpacked, a window speaking the wrong
        language. Each used to need somebody walked through the registry over a support
        thread; none of them is visible in a record or a log.
        """
        found = json.loads(self.bundle_text())["installation"]
        self.assertEqual(
            sorted(found),
            ["bundled_runtime", "language", "mcp_launcher", "mcp_manifest",
             "notification_identity", "owner_marker", "protocol_handler", "runtime_record",
             "settings_window", "startup_entry"])
        # This home is a temporary directory with nothing installed into it.
        for name in ("owner_marker", "runtime_record", "mcp_manifest", "mcp_launcher",
                     "settings_window", "bundled_runtime"):
            self.assertIs(found[name], False, name)
        for name in ("startup_entry", "protocol_handler", "notification_identity"):
            self.assertIn(found[name], ("ours", "another", "absent", "unreadable"), name)
        self.assertIn(found["language"], ("en", "ko"))

    def test_it_says_whether_a_registration_is_ours_and_never_where_it_points(self):
        """A registry value is a command line with an install path in it. What is useful is
        whether it names this installation; what is dangerous is the rest of it."""
        found = json.loads(self.bundle_text())["installation"]
        for name in ("startup_entry", "protocol_handler", "notification_identity"):
            value = found[name]
            self.assertNotIn("\\", str(value), name)
            self.assertNotIn(":", str(value), name)

    def test_it_never_overwrites_a_file(self):
        target = Path(self.temporary.name) / "exists.json"
        target.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            diagnostics.write(self.control, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
