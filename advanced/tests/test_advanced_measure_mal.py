"""MAL looks at the account on a fresh session each time, for up to ten minutes (v0.6.21).

The 2026-11-01 MAL on codex-cli 0.166.0-alpha.5.1 (plans/measure-20261101-result.md): the probe kept one app-server for
its five minutes, and a running app-server never reads the sign-in from disk again on account/read - it answered "signed
in" for four minutes after `codex logout` had removed the sign-in, so signed_out_seen, signed_in_again_seen and
plan_after said nothing. The browser sign-in also ended one second past the five minutes. Here each look opens its own
session, as the account card's read does (codex/account.read), and the window is ten minutes.

Every session is a fake whose account is read from a fake "disk" when it opens - as a real app-server's is - and no
Codex runs.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_advanced_measure_stage4 import THREAD, VERSIONS, Backend  # noqa: E402
from codex_auto_resume_advanced import measure  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement  # noqa: E402

ADDRESS = "someone@example.com"


def signed(plan):
    return {"account": {"type": "chatgpt", "email": ADDRESS, "planType": plan}, "requiresOpenaiAuth": True}


class Disk:
    """The sign-in on disk as `codex logout` and `codex login` leave it: each read the probe makes moves it on by one
    step of `steps` (then stays on the last), as time passes while the person signs out and in."""

    def __init__(self, *steps):
        self.steps = list(steps)

    def now(self):
        return self.steps[0]

    def tick(self):
        if len(self.steps) > 1:
            self.steps.pop(0)


class CachedSession:
    """An app-server: the account is read from the disk when it starts, and account/read answers that ever after."""

    def __init__(self, disk, broken=False):
        self.disk, self.account, self.broken = disk, disk.now(), broken
        self.reads = 0

    def __enter__(self):
        if self.broken:
            raise OSError("the server did not start")
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params=None):
        if method not in protocol.methods_for(Measurement.MAL):
            raise protocol.SessionRefused("not permitted for this measurement")
        assert params == {}, "refreshToken is never sent"
        self.reads += 1
        self.disk.tick()
        return json.loads(json.dumps(self.account))


class MalCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.dir, ignore_errors=True))
        for name, value in (("_MAL_SECONDS", 0.5), ("_MAL_POLL_SECONDS", 0.0)):
            patcher = patch.object(measure, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sessions = []

    def run_mal(self, disk, broken=()):
        def factory(measured):
            self.sessions.append(CachedSession(disk, broken=len(self.sessions) in broken))
            return self.sessions[-1]
        summary = measure.run(Measurement.MAL, session_factory=factory, backend=Backend(), versions=VERSIONS,
                              thread=THREAD, clock=lambda: 1_800_000_000.0, directory=self.dir)
        text = Path(summary["recorded"]).read_text(encoding="utf-8")
        self.assertNotIn(ADDRESS, text)
        self.assertNotIn(THREAD, text)
        return json.loads(text)


class FreshSessionTests(MalCase):
    def test_a_sign_out_and_in_on_disk_is_seen_though_a_running_server_never_rereads_it(self):
        """Fails with the one-server probe restored: its server keeps answering the sign-in it started with, so neither
        the sign-out nor the sign-in after it is seen - the 2026-11-01 run's blind fields."""
        disk = Disk(signed("plus"), {"account": None}, {"account": None}, signed("pro"))
        record = self.run_mal(disk)
        observed = record["observed"]
        self.assertEqual(record["verdict"], "blocked", record)
        self.assertEqual((observed["plan_before"], observed["signed_out_seen"], observed["signed_in_again_seen"],
                          observed["plan_after"], observed["fresh_session_each_read"]),
                         ("plus", True, True, "pro", True))
        self.assertGreater(len(self.sessions), 2)
        self.assertTrue(all(session.reads == 1 for session in self.sessions), "one read per session, never two")
        self.assertEqual(observed["reads"], len(self.sessions) - 1)

    def test_a_look_whose_server_does_not_start_is_counted_and_the_watch_goes_on(self):
        disk = Disk(signed("plus"), {"account": None}, {"account": None}, signed("plus"))
        record = self.run_mal(disk, broken=(1,))
        observed = record["observed"]
        self.assertEqual((observed["reads_failed"], observed["signed_out_seen"], observed["signed_in_again_seen"]),
                         (1, True, True))

    def test_signed_out_at_the_start_is_left_to_the_person_after_one_read(self):
        record = self.run_mal(Disk({"account": None}))
        self.assertEqual((record["verdict"], record["observed"]["signed_in_before"], len(self.sessions)),
                         ("blocked", False, 1))


class WindowAndNoteTests(unittest.TestCase):
    def test_the_window_is_ten_minutes(self):
        """Fails with the five-minute window restored (the 2026-11-01 sign-in ended 1 s past it)."""
        self.assertEqual(measure._MAL_SECONDS, 600.0)

    def test_the_note_names_the_steps_the_measurement_session_takes(self):
        disk = Disk(signed("plus"))
        with patch.object(measure, "_MAL_SECONDS", 0.0):
            verdict, _observed, note = measure._mal(measure.Context(
                Measurement.MAL, session_factory=lambda measured: CachedSession(disk)))
        self.assertEqual(str(verdict), "blocked")
        for words in ("`codex logout`", "`codex login`", "app's own engine", "LOCALAPPDATA", "never a codex on PATH",
                      "ten minutes", "in the browser only", "never with the app's own sign-in buttons",
                      "without a restart"):
            self.assertIn(words, note)
        self.assertNotIn("\\", note, "a record's note holds no path")


if __name__ == "__main__":
    unittest.main()
