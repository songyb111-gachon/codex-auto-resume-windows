"""v0.6.23 (audit C3): a look at the words for this time that cannot be had after the claim gives the claim back once.

After its claim the watcher looks at the words file again under its lock (engine/delivery.py `_once_words_moved`) and
gives the claim back when the words moved. Where that look could not be had - the lock held past LOCK_SECONDS, or the
file unreadable just now (an antivirus scanning the fresh file) - it went on, so words a person wrote just before the
claim were left out of the continuation and pruned with the record. Now such a look gives the claim back as a move
does (one poll later, never a send); a second look that cannot be had goes on as before, so a file that stays
unreadable never holds a recovery for good.

Against the real Store, Codex home and LocalSource (test_engine.Harness) and the real side file, as
tests/test_once_words_race.py; in a module of its own, since tests/test_once_words_engine.py is held to v0.6.10's list.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codexsim import BASE, RESET  # noqa: E402
from test_once_words_engine import OnceWordsEngineCase  # noqa: E402

NEW_WORDS = "Then update the changelog too."


class UnreadableLookTests(OnceWordsEngineCase):
    def looks_fail(self, times):
        """The engine's look after the claim cannot be had its next `times` times; real after that."""
        words = self.h.engine.once_words
        real, left = words.unchanged, [times]

        def unchanged(key, seen):
            if left[0]:
                left[0] -= 1
                return None
            return real(key, seen)
        words.unchanged = unchanged

    def write_during_the_claim(self, text):
        store = self.h.engine.store
        original = store.reserve_detailed

        def reserve(key, *args, **kwargs):
            self.words_file().put(key, text, now=BASE)
            store.reserve_detailed = original
            return original(key, *args, **kwargs)
        store.reserve_detailed = reserve

    def send_within(self, ticks):
        for _ in range(ticks):
            if self.h.backend.send_calls:
                break
            self.h.tick(advance=61)

    def test_words_added_just_before_the_claim_are_sent_not_pruned_when_the_look_fails(self):
        self.h.engine.options["thread_cooldown_seconds"] = 0
        row = self.waiting()
        self.write_during_the_claim(NEW_WORDS)
        self.looks_fail(1)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [], "nothing goes on a look that could not be had")
        self.assertEqual(self.words_file().words(row["interruption_id"]), NEW_WORDS, "the words stay")
        self.send_within(3)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertIn(NEW_WORDS, self.h.backend.send_calls[0][1])
        self.assertIsNone(self.words_file().words(row["interruption_id"]))

    def test_a_look_that_never_can_be_had_holds_the_recovery_one_poll_only(self):
        self.h.engine.options["thread_cooldown_seconds"] = 0
        self.waiting()
        self.looks_fail(1000)
        self.h.now = RESET + 61
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.send_within(3)
        self.assertEqual(len(self.h.backend.send_calls), 1, "a file that stays unreadable never holds it for good")


if __name__ == "__main__":
    unittest.main()
