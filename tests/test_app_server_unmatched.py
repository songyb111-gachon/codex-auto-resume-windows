"""#58's follow-up: the Codex app runs and no server of its can be matched, and every surface says that.

On a reporter's PC the app ran its engine from its own package, pairing found no server, and the Dashboard said "The Codex
app is not running." beside the open app. v0.6.21 fixed that one layout; Codex moves its internals without notice, so the
next such change must say what is true. Here the processes are stubs and the transport, the pairing and the engine are
real, over codexsim, as in tests/test_engine_children.py - a module of its own because that one is frozen
(tests/neutral.py). No test reads this PC's processes: `inventory` and `process_identity` are stubs throughout.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
for entry in (str(Path(_HERE).parent / "src"), _HERE):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codexsim import CodexHome, SimBackend  # noqa: E402
from codex_auto_resume import l10n, logbook, machine  # noqa: E402
from codex_auto_resume.codex import pairing, transport  # noqa: E402
from codex_auto_resume.domain import vocabulary as words  # noqa: E402
from codex_auto_resume.domain.errors import AdapterError  # noqa: E402
from codex_auto_resume.engine.freshness import FreshnessMixin  # noqa: E402
from codex_auto_resume.ownreport import evidence  # noqa: E402
from test_engine import EngineCase, T1  # noqa: E402

NATIVE = r"C:\Program Files"
PACKAGE = NATIVE + r"\WindowsApps\OpenAI.Codex_26.1104.1000.0_x64__2p2nqsd0c76g0\app"
STORE_APP = PACKAGE + r"\ChatGPT.exe"
RENDERER = dict(pid=11, parent=10, path=STORE_APP)
MAIN = dict(pid=10, parent=1, path=STORE_APP)
ENGINE = r"C:\FakeLocalAppData\OpenAI\Codex\bin\abcdef0123456789\codex.exe"
ELSEWHERE = PACKAGE + r"\somewhere-new\codex.exe"
UNMATCHED = "app_server_unmatched"
CLOSED = "desktop_app_unavailable"


class ThroughTheTransport(SimBackend):
    """codexsim's backend, except that who the app is, and what that look found, come from the real transport."""

    def __init__(self, home, real):
        super().__init__(home)
        self.real = real

    def app_identity(self):
        self.identity_calls += 1
        return self.real.app_identity()

    @property
    def app_look(self):
        return self.real.app_look


class LookCase(unittest.TestCase):
    """A real backend whose process list is `self.rows`; `self.listings` counts every time it is read."""

    def real_backend(self, home_root):
        self.rows, self.listings = [], 0
        real = transport.Backend(home_root, Path(ENGINE))

        def inventory():
            self.listings += 1
            if isinstance(self.rows, Exception):
                raise self.rows
            return [dict(row) for row in self.rows]

        identities = {10: {"pid": 10, "created": 100, "path": STORE_APP.lower()},
                      20: {"pid": 20, "created": 200, "path": ENGINE.lower()}}
        for stub in (patch.dict(os.environ, {"ProgramW6432": NATIVE}),
                     patch.object(transport, "inventory", side_effect=inventory),
                     patch.object(pairing, "process_identity", side_effect=lambda pid: dict(identities[pid]))):
            stub.start()
            self.addCleanup(stub.stop)
        compatible = patch.object(real, "_compatible")
        compatible.start()
        self.addCleanup(compatible.stop)
        return real


class BackendLookTests(LookCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.backend = self.real_backend(temp.name)

    def look(self, *rows):
        self.rows = list(rows)
        return self.backend.app_identity()

    def test_no_process_of_the_app_is_closed(self):
        self.assertIsNone(self.look())
        self.assertEqual(self.backend.app_look, "closed")

    def test_the_main_with_no_server_at_the_engine_is_unmatched(self):
        self.assertIsNone(self.look(MAIN, dict(pid=20, parent=10, path=ELSEWHERE)))
        self.assertEqual(self.backend.app_look, "unmatched")

    def test_the_main_with_no_codex_child_at_all_is_unmatched(self):
        self.assertIsNone(self.look(MAIN))
        self.assertEqual(self.backend.app_look, "unmatched")

    def test_a_process_of_the_package_with_no_one_main_is_unmatched(self):
        """Fails with `app_running` read as "exactly one main": two windows' mains are still an open app."""
        self.assertIsNone(self.look(RENDERER))
        self.assertEqual(self.backend.app_look, "unmatched")
        self.assertIsNone(self.look(MAIN, dict(MAIN, pid=12)))
        self.assertEqual(self.backend.app_look, "unmatched")

    def test_a_server_paired_is_matched(self):
        self.assertIsNotNone(self.look(MAIN, dict(pid=20, parent=10, path=ENGINE)))
        self.assertEqual(self.backend.app_look, "matched")

    def test_a_look_that_read_no_rows_says_nothing_of_the_app(self):
        self.look(MAIN)
        self.rows = AdapterError("process_inventory_unavailable")
        self.assertIsNone(self.backend.app_identity())
        self.assertIsNone(self.backend.app_look)

    def test_an_engine_that_fails_its_checks_starts_no_look_and_says_nothing(self):
        self.look(MAIN)
        listed = self.listings
        with patch.object(self.backend, "_compatible", side_effect=AdapterError("codex_binary_unavailable")):
            self.assertIsNone(self.backend.app_identity())
        self.assertIsNone(self.backend.app_look)
        self.assertEqual(self.listings, listed)

    def test_each_look_reads_the_process_list_once_whatever_it_finds(self):
        """Fails if telling the cases apart read the process list a second time: it must start no more processes."""
        for rows in ((), (MAIN,), (RENDERER,), (MAIN, dict(pid=20, parent=10, path=ENGINE))):
            before = self.listings
            self.look(*rows)
            self.assertEqual(self.listings, before + 1, rows)

    def test_an_app_elsewhere_is_still_what_the_watcher_looks_for_again(self):
        self.look(MAIN, dict(pid=20, parent=10, path=ELSEWHERE))
        self.assertEqual(self.backend.served_elsewhere, frozenset({ELSEWHERE}))


class EngineWaitTests(LookCase, EngineCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        home = CodexHome(Path(temp.name) / "codex-home")
        self.real = self.real_backend(home.root)
        self.h = self.fresh(home=home, backend=ThroughTheTransport(home, self.real))
        self.root = self.h.root

    def waits(self, *rows):
        self.rows = list(rows)
        self.ready_after_reset()
        for _ in range(3):
            self.h.tick(advance=60)
        self.assert_no_send()
        return self.h.record()

    def test_with_no_app_the_words_stay_what_they_were(self):
        row = self.waits()
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_app", CLOSED))
        self.assertEqual(machine.decode_gates(row["gate_eval"])["thread_available"], ("WAIT", CLOSED))

    def test_with_the_app_open_and_no_server_matched_it_says_so_and_sends_nothing(self):
        """The reverse-applied product has this say desktop_app_unavailable: the words #58's reporter was shown."""
        row = self.waits(MAIN, dict(pid=20, parent=10, path=ELSEWHERE))
        self.assertEqual((row["state"], row["last_error"]), ("waiting_for_app", UNMATCHED))
        self.assertEqual(machine.decode_gates(row["gate_eval"])["thread_available"], ("WAIT", UNMATCHED))
        self.assertEqual(self.h.backend.send_calls, [])

    def test_each_look_of_the_engine_costs_one_listing(self):
        self.waits(MAIN)
        self.assertEqual(self.listings, self.h.backend.identity_calls)

    def test_the_reason_follows_what_the_next_look_finds(self):
        self.assertEqual(self.waits(MAIN)["last_error"], UNMATCHED)
        self.rows = []
        self.h.tick(advance=3600)
        self.assertEqual(self.h.record()["last_error"], CLOSED)
        self.rows = [MAIN]
        self.h.tick(advance=3600)
        self.assertEqual(self.h.record()["last_error"], UNMATCHED)

    def test_a_server_matched_after_all_goes_on_as_ever(self):
        self.assertEqual(self.waits(MAIN)["last_error"], UNMATCHED)
        self.rows = [MAIN, dict(pid=20, parent=10, path=ENGINE)]
        identity = {"pid": 10, "created": 100, "path": STORE_APP.lower(),
                    "server": {"pid": 20, "created": 200, "path": ENGINE.lower()}}
        self.h.backend.app = identity
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=3600)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])


def no_app_reason(backend) -> str:
    return FreshnessMixin._no_app_reason(types.SimpleNamespace(backend=backend))


class WordsTests(unittest.TestCase):
    def test_a_backend_that_cannot_say_says_what_it_always_said(self):
        """codexsim's backend, frozen at v0.6.10's, has no such attribute."""
        self.assertEqual(no_app_reason(object()), CLOSED)
        for look in (None, "closed", "matched", "anything else"):
            self.assertEqual(no_app_reason(types.SimpleNamespace(app_look=look)), CLOSED, look)
        self.assertEqual(no_app_reason(types.SimpleNamespace(app_look="unmatched")), UNMATCHED)

    def test_it_is_a_reason_of_the_vocabulary_and_the_gates(self):
        self.assertIn(UNMATCHED, machine.REASONS)
        self.assertEqual(machine.gate(machine.WAIT, UNMATCHED), ("WAIT", UNMATCHED))
        self.assertEqual(machine.public_code({"state": "waiting_for_app", "last_error": UNMATCHED}), "waiting_thread")
        self.assertEqual(machine.public_reason({"state": "waiting_for_app", "last_error": UNMATCHED}), UNMATCHED)

    def test_the_sentences_tell_the_two_cases_apart_in_every_language(self):
        english = l10n.catalog("en")
        self.assertEqual(english["why." + CLOSED], "The Codex app is not running.")
        self.assertEqual(english["why." + UNMATCHED],
                         "The Codex app is running, but this product could not match its server, so nothing was sent.")
        for locale in l10n.LOCALES:
            words = l10n.catalog(locale)
            self.assertTrue(words["why." + UNMATCHED].strip(), locale)
            self.assertNotEqual(words["why." + UNMATCHED], words["why." + CLOSED], locale)
            if locale != l10n.DEFAULT:
                self.assertNotEqual(words["why." + UNMATCHED], english["why." + UNMATCHED], locale)

    def test_the_log_says_it_too(self):
        said = logbook.render("00000000-0000-0000-0000-000000000000", "waiting_for_app", UNMATCHED)
        self.assertIn("is running, but its Codex server could not be matched", said)
        self.assertNotIn("not running", said)


class ReportTests(unittest.TestCase):
    """What a report sends is the project's and the reporter's, and both name the word (reporter 1.5.5)."""

    def test_a_report_carries_the_word_by_its_name(self):
        self.assertIn(UNMATCHED, evidence.REASONS)
        self.assertEqual(evidence.known(UNMATCHED, evidence.REASONS), UNMATCHED)
        self.assertIn(CLOSED, evidence.REASONS)
        self.assertEqual(evidence.REASONS, frozenset(str(word) for word in words.ReasonCode), "no reason is left out")


if __name__ == "__main__":
    unittest.main()
