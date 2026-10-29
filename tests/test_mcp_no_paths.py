"""v0.6.18 (audit M1): no MCP reply carries the codex_exe path a person chose.

The Codex homes left every MCP reply in v0.6.15-beta because their folders are paths, which may hold the Windows
user name, and these replies are part of what Codex sends on. The codex_exe setting is such a path too, and
get_status, open_settings and update_settings still returned it whole. Now they say only "<set>", or None for
none, as diagnostics do; the Dashboard, which writes it, still reads it whole.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import settings  # noqa: E402
from test_mcp import McpTestCase  # noqa: E402

USER = "ExampleUser"


class NoPathTests(McpTestCase):
    def setUp(self):
        super().setUp()
        self.engine = r"D:\%s\bin\codex.exe" % USER        # a path that names the person
        values = dict(settings.defaults(), codex_exe=self.engine)
        self.paths.settings_file.write_text(json.dumps(values), encoding="utf-8")
        self.assertEqual(self.control.get_settings()["codex_exe"], self.engine, "the Dashboard reads it whole")

    def test_no_reply_carries_the_path(self):
        for name, arguments in (("get_status", {}), ("open_settings", {}),
                                ("update_settings", {"max_no_progress": 8})):
            with self.subTest(tool=name):
                reply = self.call(name, arguments)
                self.assertNotIn("error", reply)
                text = json.dumps(reply)
                self.assertNotIn(USER, text)
                self.assertNotIn("codex.exe", text)
                self.assertIn('"codex_exe": "<set>"', text)

    def test_none_set_says_none(self):
        self.paths.settings_file.write_text(json.dumps(settings.defaults()), encoding="utf-8")
        self.assertIn('"codex_exe": null', json.dumps(self.call("get_status")))


if __name__ == "__main__":
    unittest.main()
