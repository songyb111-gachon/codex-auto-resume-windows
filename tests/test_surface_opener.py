"""The Dashboard opener under CODEX_AR_CORE=rust equals the reference's, call for call (S6.4e).

`tests/rustdiff/surfaceproxy.py` answers `ui.tray.dashboard.open_dashboard`, `open_chat`, `PAGES` and `ROW_DIALOGS` from
car-watcher's dashboard.rs (the harness's copy over a scratch world), asking the hand-over back of the test's
`win.handover.hand_over` and handing the start it would make to the test's `subprocess.Popen`. This file holds that wrapper
to the Python original (`__wrapped__`) on the same recording stand-ins: the same result or the same refusal (class and
message), the same hand-over calls with the same arguments (positional, the exe a Path), the same starts with the same
keywords, and an exception the test's hand-over raises reaching the caller alike.

Without the variable the proxy is not installed and every test here is skipped (the shipped edition never sees it).
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

from codex_auto_resume import machine
from codex_auto_resume.ui.popup import model as popup_model
from codex_auto_resume.ui.tray import dashboard
from codex_auto_resume.win import handover

PROXIED = bool(getattr(dashboard.open_dashboard, "rust_core", None))
KEY, THREAD = "ab" * 32, "12345678-89ab-7cde-8f01-23456789abcd"
EXE = "CodexAutoResumeSettings.exe"
PAGES = [None, "pending", "history", "settings", "nope", "", "Pending", "--page=x"]
ROWS = [None, ("message", KEY, THREAD), ("once_words", KEY, THREAD), ["message", KEY, THREAD], ("settings", KEY, THREAD),
        ("message", KEY.upper(), THREAD), ("message", KEY), "message", 7, ("message", KEY, THREAD + " --page=x")]


class Broke(Exception):
    pass


class Recorder:
    """The test's hand-over and process start, recording each call as it was made."""

    def __init__(self, answer):
        self.answer, self.handed, self.started = answer, [], []

    def hand_over(self, *args, **kwargs):
        self.handed.append((args, kwargs))
        if self.answer == "raise":
            raise Broke("the stand-in broke")
        return self.answer

    def popen(self, *args, **kwargs):
        self.started.append((args, kwargs))
        return types.SimpleNamespace(pid=0)


def outcome(call):
    try:
        return ("ok", call())
    except Exception as error:
        return ("raised", type(error).__name__, str(error))


@unittest.skipUnless(PROXIED, "CODEX_AR_CORE=rust only: the proxy is not installed")
class OpenerAskBackTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.installed = Path(folder.name) / "installed home"
        self.installed.mkdir()
        (self.installed / EXE).write_bytes(b"MZ")      # a file to find; never run
        self.bare = Path(folder.name) / "bare"
        self.bare.mkdir()

    def run_both(self, call, answer):
        seen = []
        for function in (call, call.__wrapped__):
            recorder = Recorder(answer)
            with patch.object(handover, "hand_over", recorder.hand_over), \
                    patch.object(dashboard.subprocess, "Popen", recorder.popen):
                said = outcome(function)
            seen.append((said, recorder.handed, recorder.started))
        return seen

    def test_open_dashboard_asks_and_starts_as_the_reference_does(self):
        checked = 0
        for home in (self.installed, self.bare):
            for page in PAGES:
                for row in ROWS:
                    for answer in (True, False, 1, 0, "", "raise"):
                        def call(home=home, page=page, row=row):
                            return dashboard.open_dashboard(home, page, row=row)
                        call.__wrapped__ = (lambda home=home, page=page, row=row:
                                            dashboard.open_dashboard.__wrapped__(home, page, row=row))
                        with self.subTest(home=home.name, page=page, row=row, answer=answer):
                            rust, python = self.run_both(call, answer)
                            self.assertEqual(rust, python)
                            checked += 1
        self.assertEqual(checked, 2 * len(PAGES) * len(ROWS) * 6)

    def test_open_dashboard_with_its_page_given_by_keyword_or_left_out(self):
        for answer in (True, False):
            for call, original in ((lambda: dashboard.open_dashboard(self.installed),
                                    lambda: dashboard.open_dashboard.__wrapped__(self.installed)),
                                   (lambda: dashboard.open_dashboard(self.installed, page="history"),
                                    lambda: dashboard.open_dashboard.__wrapped__(self.installed, page="history")),
                                   (lambda: dashboard.open_dashboard(str(self.installed), None, None),
                                    lambda: dashboard.open_dashboard.__wrapped__(str(self.installed), None, None))):
                call.__wrapped__ = original
                with self.subTest(answer=answer):
                    rust, python = self.run_both(call, answer)
                    self.assertEqual(rust, python)

    def test_open_chat_starts_as_the_reference_does(self):
        for home in (self.installed, self.bare):
            for thread in (THREAD, THREAD.upper(), "{%s}" % THREAD, "", None, 7, "not a conversation"):
                def call(home=home, thread=thread):
                    return dashboard.open_chat(home, thread)
                call.__wrapped__ = lambda home=home, thread=thread: dashboard.open_chat.__wrapped__(home, thread)
                with self.subTest(home=home.name, thread=thread):
                    rust, python = self.run_both(call, True)
                    self.assertEqual(rust, python)

    def test_the_pages_and_the_dialogs_are_the_ports(self):
        self.assertEqual(dashboard.PAGES, tuple(machine.PAGES))
        self.assertEqual(dashboard.ROW_DIALOGS, tuple(popup_model.ROW_DIALOGS))
        self.assertIsInstance(dashboard.PAGES, tuple)

    def test_a_start_the_port_could_not_make_still_answers_true(self):
        """dashboard.rs drops a failed start's error (`let _ = ...`), where the reference raises it: the proxy answers as
        the port does (diffs_ui_opener's expected failure names the difference)."""
        def refused(*args, **kwargs):
            raise OSError("not started")
        with patch.object(handover, "hand_over", lambda exe, page=None, row=None: False), \
                patch.object(dashboard.subprocess, "Popen", refused):
            self.assertTrue(dashboard.open_dashboard(self.installed, "pending"))
            self.assertTrue(dashboard.open_chat(self.installed, THREAD))
            with self.assertRaises(OSError):
                dashboard.open_dashboard.__wrapped__(self.installed, "pending")


if __name__ == "__main__":
    unittest.main()
