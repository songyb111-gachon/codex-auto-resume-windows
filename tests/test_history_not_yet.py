"""v0.6.26 final: a fresh Codex home that has no history database yet is "not yet", not a failure.

Codex makes thread_history_1.sqlite lazily, with the first conversation it saves; its start opens the state, logs,
goals, memories and queue databases only. A Codex installed fresh (PR #69 lets a Microsoft Store-only one install)
therefore has a state database and no history, and every reader of it said so as a failure: the health check said
"local history    : FAIL (SourceError)", the watcher logged "detection unavailable" every tick and, after three ticks
with the app open, raised the self-check's "history can no longer be read" with an attention light, Diagnostics said the
home "cannot be read" and the compatibility checks called the history "unavailable".

The rule is the lock folder's (compat/probes.py, update resilience #4): absent is "not yet" while the newest state
database holds no conversation; a home whose state holds one and has no history is one where Codex moved, renamed or
dropped it, and that stays the alarm it was. Every home here is a scratch one, and nothing real is asked: the process
list, the backend, the watcher probe and both registrations are stubs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import codexsim  # noqa: E402
from codex_auto_resume import checkup, cli, compat, startup  # noqa: E402
from codex_auto_resume.codex import HistoryNotYet, LocalSource, SourceError  # noqa: E402
from codex_auto_resume.commands import status  # noqa: E402
from codex_auto_resume.compat import probes  # noqa: E402
from codex_auto_resume.runtime import loop  # noqa: E402
from test_checkup import CheckupCase, NOW, QUIET  # noqa: E402
from test_doctor_closed_app import DoctorCase  # noqa: E402
from test_engine import T1, EngineCase  # noqa: E402
from test_recovery_blocked import Store, Watcher  # noqa: E402

HISTORY = "thread_history_1.sqlite"


def without_history(root: Path) -> bytes:
    """Take the history database out of a codexsim home - as a fresh Codex home has none - and give back its bytes, an
    empty history with every table, to put back where a test makes Codex save its first conversation."""
    path = Path(root) / HISTORY
    kept = path.read_bytes()
    path.unlink()
    return kept


def add_conversation(root: Path, thread_id=T1):
    """One conversation in the state database alone, as a Codex that dropped its history would leave it."""
    connection = sqlite3.connect(Path(root) / "state_5.sqlite")
    try:
        connection.execute("INSERT INTO threads (id, rollout_path, source, thread_source, archived, history_mode) "
                           "VALUES (?, '', 'vscode', 'user', 0, 'paginated')", (thread_id,))
        connection.commit()
    finally:
        connection.close()


class ReaderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "codex-home"
        codexsim.CodexHome(self.root)
        self.source = LocalSource(self.root)

    def test_a_fresh_home_has_no_history_yet(self):
        without_history(self.root)
        with self.assertRaises(HistoryNotYet):
            self.source.latest_failures(codexsim.BASE)
        # Still a SourceError, so every reader that refused before refuses as it did.
        self.assertTrue(issubclass(HistoryNotYet, SourceError))

    def test_a_home_with_a_conversation_and_no_history_is_the_refusal_it_was(self):
        without_history(self.root)
        add_conversation(self.root)
        with self.assertRaises(SourceError) as raised:
            self.source.latest_failures(codexsim.BASE)
        self.assertNotIsInstance(raised.exception, HistoryNotYet)

    def test_a_home_with_no_state_either_is_the_refusal_it_was(self):
        without_history(self.root)
        (self.root / "state_5.sqlite").unlink()
        with self.assertRaises(SourceError) as raised:
            self.source.latest_failures(codexsim.BASE)
        self.assertNotIsInstance(raised.exception, HistoryNotYet)

    def test_a_history_that_is_there_is_read_as_it_was(self):
        self.assertEqual(self.source.latest_failures(codexsim.BASE), [])


class CompatTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "codex-home"
        codexsim.CodexHome(self.root)
        self.source = LocalSource(self.root)

    def checks(self):
        found = probes.source_checks(self.source)
        return found["history_schema"], found["projection_table"]

    def test_a_fresh_homes_history_checks_do_not_apply_yet(self):
        without_history(self.root)
        self.assertEqual(self.checks(), (compat.NOT_APPLICABLE, compat.NOT_APPLICABLE))

    def test_with_a_conversation_they_stay_unavailable(self):
        without_history(self.root)
        add_conversation(self.root)
        self.assertEqual(self.checks(), (compat.UNAVAILABLE, compat.UNAVAILABLE))
        self.assertEqual(probes.source_checks(self.source)["lock_directory"], compat.FAIL)

    def test_a_history_that_is_there_passes_as_it_did(self):
        self.assertEqual(self.checks(), (compat.PASS, compat.PASS))


class DoctorTests(DoctorCase):
    def setUp(self):
        super().setUp()
        self.codex = self.home / "codex"
        codexsim.CodexHome(self.codex)
        without_history(self.codex)

    def doctor_here(self):
        args = cli.build_parser().parse_args(["--home", str(self.home), "--quiet", "doctor"])
        backend = MagicMock()
        backend.codex_exe, backend.engine_version, backend.app_look = "codex.exe", "0.0.0", "closed"
        out = io.StringIO()
        with patch.object(cli.App, "backend", return_value=backend), \
             patch.object(cli.App, "engine_moved", return_value=False), \
             patch.object(cli.App, "watcher_running", return_value=False), \
             patch.object(cli.App, "source", side_effect=lambda: LocalSource(self.codex)), \
             patch.object(status.compatio, "live_view", return_value=None), \
             patch.object(status, "app_running_now", return_value=False), \
             patch.object(startup, "protocol_value", return_value=None), \
             patch.object(startup, "current_value", return_value=None), \
             contextlib.redirect_stdout(out):
            code = cli.cmd_doctor(args)
        return code, out.getvalue()

    def test_a_fresh_home_says_not_created_yet_and_no_problem(self):
        code, said = self.doctor_here()
        self.assertIn("local history    : " + status.HISTORY_NOT_YET, said)
        self.assertEqual(status.HISTORY_NOT_YET, "not created yet (Codex makes it with the first saved conversation)")
        self.assertNotIn("FAIL", said)
        self.assertNotIn(status.PROBLEM, said)
        self.assertEqual(code, status.EXIT_OK, said)

    def test_a_home_with_a_conversation_and_no_history_still_fails(self):
        add_conversation(self.codex)
        code, said = self.doctor_here()
        self.assertIn("local history    : FAIL (SourceError)", said)
        self.assertEqual(said.splitlines()[-1], status.PROBLEM + "local history : FAIL (SourceError)")
        self.assertEqual(code, status.EXIT_ERROR)


class DiagnosticsTests(CheckupCase):
    def run_here(self):
        return checkup.run(self.control, sources=[(None, LocalSource(self.codex.root))], now=NOW,
                           presence=lambda: dict(QUIET), locale="en")

    def test_a_fresh_home_is_read_and_its_history_written_never(self):
        without_history(self.codex.root)
        result = self.run_here()
        [home] = result["homes"]
        self.assertTrue(home["readable"])
        self.assertIsNone(home["history_written"])
        self.assertEqual(result["summary"], "nothing")
        self.assertFalse(any("cannot be read" in line for line in result["lines"]), result["lines"])
        self.assertTrue(any("its history written never" in line for line in result["lines"]), result["lines"])

    def test_a_home_with_a_conversation_and_no_history_cannot_be_read_as_before(self):
        without_history(self.codex.root)
        add_conversation(self.codex.root)
        [home] = self.run_here()["homes"]
        self.assertFalse(home["readable"])


class WatcherTests(EngineCase):
    """The watcher's detection and its own judge (engine/impossible.py history_unreadable, selfcheck.json), with the
    app open throughout - the judge counts a detection that cannot read only while it runs."""

    def setUp(self):
        super().setUp()
        self.watcher = Watcher(self.root / "product")
        stub = patch.object(loop, "app_running_now", return_value=True)
        stub.start()
        self.addCleanup(stub.stop)
        self.kept = without_history(self.h.home.root)

    def ticks(self, count, engine):
        for _ in range(count):
            self.h.tick(advance=30)
            self.watcher._self_check(Store([]), engine, 500.0)
        return json.loads(self.watcher.paths.self_check_file.read_text(encoding="utf-8"))["blocked"]

    def unread_logs(self):
        return [entry for entry in self.h.logs if entry[1] == "detection_unavailable_no_submission"]

    def test_a_fresh_home_logs_nothing_and_raises_no_light(self):
        self.assertIsNone(self.ticks(5, self.h.engine))
        self.assertIs(self.h.engine.detection_failed, False)
        self.assertEqual(self.unread_logs(), [])
        written = json.loads(self.watcher.paths.self_check_file.read_text(encoding="utf-8"))
        self.assertIsNone(written["blocked"])

    def test_a_failure_is_detected_once_codex_makes_its_history(self):
        self.ticks(3, self.h.engine)
        self.assertEqual(self.h.store.all_records(), [])
        # Codex saves its first conversation: the history appears, and that conversation's turn fails.
        (self.h.home.root / HISTORY).write_bytes(self.kept)
        self.h.home.fail_usage(T1)
        self.assertIsNone(self.ticks(1, self.h.engine))
        self.assertIs(self.h.engine.detection_failed, False)
        [record] = self.h.store.all_records()
        self.assertEqual(record["thread_id"], T1)
        self.assertIn("usageLimitExceeded_detected", self.h.codes(T1))

    def test_a_home_with_a_conversation_and_no_history_is_said_as_before(self):
        add_conversation(self.h.home.root)
        self.assertIsNone(self.ticks(2, self.h.engine))
        self.assertIs(self.h.engine.detection_failed, True)
        self.assertEqual(self.ticks(1, self.h.engine), "detection_blocked:history_unreadable")
        self.assertTrue(self.unread_logs())


if __name__ == "__main__":
    unittest.main()
