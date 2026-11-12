"""v0.6.23 second round M5: a put-back left waiting writes its journal line once, not every minute.

A switch whose target did not sign in, with its put-back's restart held because someone used the PC, was settled again
at every look (LOOK_EVERY, 60 s) and journalled `autoswch.not_put_back` each time - up to 1,440 rows a day of the
journal's 5,000 shared by every capability. Now each switch left is journalled once, and every repeat only counted for
the day (Scoped.sample), as other frequent words are.

Every home is a temporary folder and every sign-in file a fixture of no one's (test_advanced_autoswitch.EngineCase).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_advanced_autoswitch as engine_tests  # noqa: E402
from test_advanced_autoswitch_swap import ONE, TWO  # noqa: E402
from codex_auto_resume_advanced.codex import restart as restarts  # noqa: E402
from codex_auto_resume_advanced.engine import autoswitch  # noqa: E402

SIGNED_OUT = {"present": False, "plan_word": None, "email": None, "kind": None}


class Scoped(engine_tests.Scoped):
    def __init__(self, *arguments):
        super().__init__(*arguments)
        self.sampled = []

    def sample(self, code):
        self.sampled.append(code)
        return True


class APutBackLeftWaiting(engine_tests.EngineCase):
    def setUp(self):
        super().setUp()
        self.scoped = Scoped()
        self.code.bind(self.scoped)
        self.held = True
        made, reads = [], []

        def restart(between):
            made.append(1)
            if len(made) > 1 and self.held:
                return None                                  # someone uses the PC: the put-back waits
            between()
            return restarts.RESTARTED, restarts.CLOSED

        def read_real():
            reads.append(1)
            return self.fake.read_real() if len(reads) <= 2 else SIGNED_OUT
        self.code._restart, self.code._read_real = restart, read_real

    def looks(self, count):
        for _look in range(count):
            self.scoped.clock += autoswitch.LOOK_EVERY
            self.look([engine_tests.waiting("b", detected=self.scoped.clock - autoswitch.SETTLE)])

    def test_two_hours_of_looks_write_one_line(self):
        """Fails with every look counted: 1 + 120 lines (a day's were 1,441)."""
        self.look()
        self.assertEqual(self.scoped.counted, ["not_put_back"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), TWO, "the copy that did not sign in waits in place")
        self.looks(120)
        self.assertEqual(self.scoped.counted, ["not_put_back"])
        self.assertEqual(self.scoped.sampled, ["not_put_back"] * 120, "each repeat counted for the day")

    def test_the_put_back_when_it_comes_is_still_journalled(self):
        self.look()
        self.looks(3)
        self.held = False
        self.looks(1)
        self.assertEqual(self.scoped.counted, ["not_put_back", "not_signed_in"])
        self.assertEqual((self.codex / "auth.json").read_bytes(), ONE)


if __name__ == "__main__":
    unittest.main()
