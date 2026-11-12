"""v0.6.23: the watcher shows each notice an edition's plug adds once per what it says, however long it runs. Until
v0.6.23 the keys it had shown were kept in a set that refused every key after the 65th, so a watcher alive for a week
or two (the meter warns up to about five times a day) never showed a near-limit, account or update notice again. Now
the keys are remembered newest last, a key still being sent kept newest, and only the oldest is forgotten.

    PYTHONPATH="src;tests" python -m unittest test_plug_notices_bound
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from codex_auto_resume.runtime import plugnotices  # noqa: E402


class Watcher:
    """The App's part _unshown reads: its __dict__."""


def meter(*keys):
    return {"meter": {"notices": [{"key": key} for key in keys]}}


def shown(owner, added):
    return [notice["key"] for notice in plugnotices._unshown(owner, added, "meter", "_near_limit_shown")]


class ShownOnceHoweverLong(unittest.TestCase):

    def test_two_hundred_distinct_keys_are_each_shown_once(self):
        """Fails with the old bound: 65 of the 200 were shown, then none."""
        watcher = Watcher()
        keys = ["5h:300:%d" % (1_800_000_000 + 18_000 * n) for n in range(200)]
        said = []
        for key in keys:
            said += shown(watcher, meter(key))
            said += shown(watcher, meter(key))  # the plug repeats it in the next snapshot
        self.assertEqual(said, keys)

    def test_the_memory_keeps_only_the_most_recent_keys(self):
        watcher = Watcher()
        for n in range(500):
            shown(watcher, meter("k%d" % n))
        self.assertEqual(len(watcher._near_limit_shown), plugnotices.SHOWN_KEYS)
        self.assertEqual(list(watcher._near_limit_shown)[-1], "k499")
        self.assertNotIn("k0", watcher._near_limit_shown)

    def test_a_key_still_being_sent_is_not_forgotten_by_newer_ones(self):
        """A notice the plug still holds is kept newest at each sighting, so many newer keys do not show it again."""
        watcher = Watcher()
        self.assertEqual(shown(watcher, meter("held")), ["held"])
        for n in range(3 * plugnotices.SHOWN_KEYS):
            self.assertEqual(shown(watcher, meter("held", "new%d" % n)), ["new%d" % n])

    def test_the_bound_is_the_number_the_docstring_says(self):
        self.assertEqual(plugnotices.SHOWN_KEYS, 64)
        source = (ROOT / "src" / "codex_auto_resume" / "runtime" / "plugnotices.py").read_text(encoding="utf-8")
        self.assertNotIn("at most 64", source)
        self.assertIn("SHOWN_KEYS = 64", source)

    def test_parts_are_remembered_apart(self):
        watcher = Watcher()
        self.assertEqual([n["key"] for n in plugnotices._unshown(watcher, {"update": {"notices": [{"key": "a"}]}},
                                                                   "update")], ["a"])
        self.assertEqual(shown(watcher, meter("a")), ["a"])


if __name__ == "__main__":
    unittest.main()
