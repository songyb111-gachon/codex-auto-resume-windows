"""Why the community report's filing gates stand, said to the person they stop (v0.6.23, the owner's decision of
2026-11-10): the gates stay as they are, and the comment says what they are for in one plain sentence."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "src"))

import community_file as filer  # noqa: E402

SENTENCE = "keeps one account or one script from outweighing everyone else's reports"


class GateReasonTests(unittest.TestCase):
    def test_the_gates_are_where_they_were(self):
        self.assertEqual((filer.MIN_AGE_DAYS, filer.PER_REPORTER, filer.PER_VERSION, filer.WINDOW_DAYS), (30, 3, 5, 7))

    def test_every_comment_a_gate_writes_says_why(self):
        for name, text in (("young", filer.TEXTS["young"] % "2026-12-01"), ("one", filer.TEXTS["one"] % "7"),
                           ("reporter", filer.TEXTS[filer.QUEUED] % (filer.WAITING["reporter"], "on 2026-12-01")),
                           ("version", filer.TEXTS[filer.QUEUED] % (filer.WAITING["version"], "on 2026-12-01"))):
            with self.subTest(name):
                self.assertEqual(text.count(SENTENCE), 1)
                self.assertIsNone(filer.FORBIDDEN.search(text), "the comment could not be posted")
                self.assertNotIn("..", text)

    def test_the_other_waits_do_not_claim_it(self):
        for name in ("paused", "red", "unlisted", "full"):
            self.assertNotIn(SENTENCE, filer.WAITING[name], name)


if __name__ == "__main__":
    unittest.main()
