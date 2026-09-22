"""The front ends' replies, held to the byte.

The v0.6.10-alpha modularization moves most of the Python implementation between files. The
one thing it must not do is change what the window and the panel in Codex are handed - a
renamed key, a reordered list, a sentence rebuilt slightly differently, and a front end that
was written against the old shape quietly shows something else.

Every test in the suite says something about one behaviour. This one says nothing about any:
it records both surfaces in full, from a machine held still (`goldensession.py`), and fails
on a single byte. That is the point. A split that is really only a split leaves it green
without anybody thinking about it, and a split that is not leaves a diff that has to be read.

When a reply is *meant* to change, rerun `python tests/goldensession.py --write` in the same
commit. The diff in `fixtures/golden/` is then the review.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
for entry in (str(HERE.parent / "src"), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import goldensession  # noqa: E402


def first_difference(produced: str, stored: str) -> str:
    """The line that moved, cut to something a failure message can hold."""
    new, old = produced.splitlines(), stored.splitlines()
    for number, (left, right) in enumerate(zip(new, old), 1):
        if left != right:
            for column, (a, b) in enumerate(zip(left, right), 1):
                if a != b:
                    break
            else:
                column = min(len(left), len(right)) + 1
            return ("line %d, character %d\n    golden: %s\n    now   : %s"
                    % (number, column, right[max(0, column - 60):column + 60],
                       left[max(0, column - 60):column + 60]))
    if len(new) != len(old):
        longer, shorter = (new, old) if len(new) > len(old) else (old, new)
        return "%d lines now, %d in the golden; first extra line: %s" % (
            len(new), len(old), longer[len(shorter)][:160])
    return "the files differ in their line endings alone"


class GoldenReplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.produced = goldensession.produce()

    def check(self, path):
        self.assertTrue(path.exists(), "%s is missing; run `python tests/goldensession.py --write`"
                        % path.name)
        stored = path.read_text(encoding="utf-8")
        produced = self.produced[path]
        if produced != stored:
            self.fail("the replies changed:\n  %s\n\nIf this change is meant, rerun\n"
                      "  python tests/goldensession.py --write\nin the same commit, and read the diff."
                      % first_difference(produced, stored))

    def test_the_window_gets_exactly_what_it_got(self):
        self.check(goldensession.WINDOW)

    def test_the_panel_gets_exactly_what_it_got(self):
        self.check(goldensession.PANEL)

    def test_the_same_machine_twice_says_the_same_thing(self):
        """A golden that is not reproducible is a red suite on somebody else's computer.

        Everything a reply could take from the machine is pinned in `goldensession.Frozen`;
        this is what notices when a new one appears - a fresh timestamp, a path, an
        unordered set.
        """
        again = goldensession.produce()
        for path, text in again.items():
            with self.subTest(path.name):
                self.assertEqual(text, self.produced[path],
                                 "two runs on one machine disagreed:\n  %s"
                                 % first_difference(text, self.produced[path]))


class CoverageTests(unittest.TestCase):
    """A surface the golden does not cover is a surface a split can change silently."""

    def test_every_window_command_is_recorded(self):
        from codex_auto_resume import controlcli
        asked = {command for command, _argument in goldensession.WINDOW_SESSION}
        for command in controlcli.PLAIN + controlcli.WITH_ARGUMENT:
            with self.subTest(command):
                self.assertIn(command, asked, "add it to goldensession.WINDOW_SESSION and rewrite "
                                              "the golden; a bridge command with no golden is one "
                                              "a refactor can change without anybody seeing")

    def test_every_panel_tool_is_recorded(self):
        from codex_auto_resume import mcpserver
        called = {name for name, _arguments in goldensession.PANEL_CALLS}
        for tool in mcpserver.TOOLS:
            with self.subTest(tool["name"]):
                self.assertIn(tool["name"], called, "add it to goldensession.PANEL_CALLS and "
                                                    "rewrite the golden")

    def test_refusals_are_recorded_too(self):
        """What a front end shows when something is wrong is part of the surface."""
        window = goldensession.WINDOW.read_text(encoding="utf-8")
        self.assertIn('"ok": false', window)
        self.assertIn('"error_code"', window)
        panel = goldensession.PANEL.read_text(encoding="utf-8")
        self.assertIn('"isError": true', panel)
        self.assertIn('"code": -32700', panel, "the parse error's own shape")


if __name__ == "__main__":
    unittest.main()
