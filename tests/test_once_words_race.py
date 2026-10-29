"""v0.6.18 (audit R1): words for this time a person writes while the watcher is mid-dispatch are sent or stay.

The watcher reads a waiting recovery's words before its claim (A26) and takes them off the file as the continuation
carrying them is handed to Codex. A person who adds, edits or takes away the words between that read and the claim
used to lose them: the old words were sent and the new ones deleted with them, or the continuation went without the
words just added and they were deleted with the record. Now the watcher looks at the file again under its lock after
the claim and gives the claim back when the words moved, so the next continuation carries what the person wrote; and
the Dashboard checks that the recovery still waits under that same lock, so a claim can never fall between its check
and its write.

Against the real Store, Codex home and LocalSource (test_engine.Harness) and the real side file, as
tests/test_once_words_engine.py; in a module of its own, since that one is held to v0.6.10's scenario list.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codexsim import BASE, RESET  # noqa: E402
from codex_auto_resume import oncewords  # noqa: E402
from codex_auto_resume.control import ControlError  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402
from test_control import KEY, THREAD, ControlTestCase  # noqa: E402
from test_once_words_engine import WORDS, OnceWordsEngineCase  # noqa: E402

NEW_WORDS = "Then update the changelog too."


class BetweenReadAndClaimTests(OnceWordsEngineCase):
    def write_during_the_claim(self, text):
        """The person's write lands after the engine read the words and before its claim."""
        store = self.h.engine.store
        original = store.reserve_detailed

        def reserve(key, *args, **kwargs):
            if text is None:
                self.words_file().remove(key)
            else:
                self.words_file().put(key, text, now=BASE)
            store.reserve_detailed = original
            return original(key, *args, **kwargs)
        store.reserve_detailed = reserve

    def test_words_edited_in_between_are_never_deleted_and_the_new_ones_are_sent(self):
        self.h.engine.options["thread_cooldown_seconds"] = 0
        row = self.waiting()
        self.add(row)
        self.write_during_the_claim(NEW_WORDS)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [], "the old words are not sent in place of the new")
        self.assertEqual(self.words_file().words(row["interruption_id"]), NEW_WORDS, "the new words stay")
        self.assertIn(self.h.record()["state"], ("waiting_retry",))
        for _ in range(3):
            if self.h.backend.send_calls:
                break
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        prompt = self.h.backend.send_calls[0][1]
        self.assertIn(NEW_WORDS, prompt)
        self.assertNotIn(WORDS, prompt)
        self.assertIsNone(self.words_file().words(row["interruption_id"]))

    def test_words_added_in_between_are_sent_not_deleted_with_the_record(self):
        self.h.engine.options["thread_cooldown_seconds"] = 0
        row = self.waiting()
        self.write_during_the_claim(NEW_WORDS)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(self.words_file().words(row["interruption_id"]), NEW_WORDS)
        for _ in range(3):
            if self.h.backend.send_calls:
                break
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertIn(NEW_WORDS, self.h.backend.send_calls[0][1])
        self.assertIsNone(self.words_file().words(row["interruption_id"]))

    def test_words_taken_away_in_between_are_not_sent(self):
        self.h.engine.options["thread_cooldown_seconds"] = 0
        row = self.waiting()
        self.add(row)
        self.write_during_the_claim(None)
        self.h.now = RESET + 61
        self.h.tick()
        for _ in range(3):
            if self.h.backend.send_calls:
                break
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertNotIn(WORDS, self.h.backend.send_calls[0][1])

    def test_words_left_alone_go_on_the_first_continuation_as_before(self):
        row = self.waiting()
        self.add(row)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertIn(WORDS, self.h.backend.send_calls[0][1])


class DashboardChecksUnderTheLockTests(ControlTestCase):
    def setUp(self):
        super().setUp()
        self.register()

    def test_a_claim_that_lands_before_the_write_refuses_the_words_instead_of_keeping_them_for_nothing(self):
        original = oncewords.OnceWords._change

        def claimed_first(held, change):
            # The watcher's claim lands after the Dashboard's first look and before the file is written.
            with Store(self.paths.state_dir) as store:
                if store.get(KEY)["state"] != "submitting":
                    store.set_enabled(True, 100.0)
                    self.assertTrue(store.reserve(KEY, 1000.0))
            return original(held, change)

        with patch.object(oncewords.OnceWords, "_change", claimed_first):
            with self.assertRaises(ControlError) as caught:
                self.control.set_once_words(KEY, THREAD, WORDS)
        self.assertEqual(caught.exception.code, "being_sent")
        self.assertIsNone(self.control.once_words(KEY)["text"], "nothing held for a recovery being sent")

    def test_a_recovery_still_waiting_takes_them(self):
        self.assertTrue(self.control.set_once_words(KEY, THREAD, WORDS)["set"])
        self.assertEqual(self.control.once_words(KEY)["text"], WORDS)


if __name__ == "__main__":
    unittest.main()
