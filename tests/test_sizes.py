"""A line budget for every module.

The v0.6.5 split exists because files grew until nobody could hold one in their head - the
popup reached nearly three thousand lines - and nothing said stop. This does: no module may
be longer than BUDGET lines. The modules that already are sit in OVERSIZED with today's
length as a ceiling, and each one is held to exactly that length. Growing past it fails;
shrinking below it fails too, until the ceiling is lowered to the new length in the same
commit; coming under the budget fails until it is taken off the list. So the list only
shrinks, every ceiling only comes down, and a file that was split - even partly - cannot
quietly grow back to the size it was.

v0.6.7 raised one ceiling on purpose - notice_window.py, for the card's breathing light - and
v0.6.8 raised tray.py's, store.py's and control.py's, for a failure's sweep and for a failure
that stays red until it is seen.

Since v0.6.8 the budget waits for the split, v0.6.10's alpha (HOLDS_FROM). The user: "리팩터링
이전까진 줄 수 제한 신경쓰지마" - so until the manifest reaches it, a module may grow, a new one may
be over the budget and a ceiling may be left above a module that shrank; the ceilings below are what
the modules were when the budget stopped holding, for the split to start from.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # srcscan lives next to this file

import srcscan  # noqa: E402

BUDGET = 700
# The release from which the budget holds again: the refactoring, v0.6.10-alpha.
HOLDS_FROM = (0, 6, 10)


def budget_holds() -> bool:
    from codex_auto_resume import config
    number = config.version().split("-", 1)[0]
    return tuple(int(part) for part in number.split(".")) >= HOLDS_FROM


def hold(test):
    """Runs `test` only once the budget holds again."""
    def held(self):
        if not budget_holds():
            self.skipTest("the line budget waits for the refactoring, v0.6.10-alpha")
        return test(self)
    held.__name__, held.__doc__ = test.__name__, test.__doc__
    return held

# Today's length of each module over the budget, as a ceiling. Lower a ceiling in the commit
# that shrinks its module; delete the entry when it is under the budget; never raise one.
OVERSIZED = {
    "codex_auto_resume/tray.py": 1171,
    "codex_auto_resume/brand.py": 979,
    "codex_auto_resume/notice_window.py": 929,
    "codex_auto_resume/windows.py": 989,
    "codex_auto_resume/compat.py": 824,
    "codex_auto_resume/control.py": 1083,
    "codex_auto_resume/cli.py": 721,
    "codex_auto_resume/compatio.py": 727,
}


def lengths():
    return {srcscan.relative(path): len(srcscan.read(path).splitlines()) for path in srcscan.package_files()}


class SizeTests(unittest.TestCase):
    @hold
    def test_no_module_is_longer_than_the_budget(self):
        over = {name: length for name, length in lengths().items()
                if length > BUDGET and name not in OVERSIZED}
        self.assertEqual(over, {}, "split it, or it joins the modules the v0.6.5 split exists to undo")

    @hold
    def test_no_oversized_module_grows(self):
        measured = lengths()
        for name, ceiling in OVERSIZED.items():
            with self.subTest(name):
                self.assertIn(name, measured, "the module is gone or moved; take it off OVERSIZED")
                self.assertLessEqual(measured[name], ceiling, "it grew; it was already over the budget")

    @hold
    def test_every_ceiling_is_the_length_its_module_has_now(self):
        """A ceiling left above a module that shrank is room to grow back into: split 1,500 of
        the popup's 2,946 lines out, leave the ceiling, and a later commit can put them back
        without a failure."""
        measured = lengths()
        for name, ceiling in OVERSIZED.items():
            with self.subTest(name):
                self.assertGreaterEqual(measured.get(name, ceiling), ceiling,
                                        "it shrank to %s lines; lower its ceiling to that in this commit"
                                        % measured.get(name))

    def test_the_budget_waits_for_the_refactoring_and_no_longer(self):
        from codex_auto_resume import config
        number = tuple(int(part) for part in config.version().split("-", 1)[0].split("."))
        self.assertEqual(budget_holds(), number >= (0, 6, 10))
        self.assertEqual(HOLDS_FROM, (0, 6, 10), "the refactoring is v0.6.10-alpha (docs/ROADMAP.md)")

    def test_the_list_of_oversized_modules_only_shrinks(self):
        measured = lengths()
        for name in OVERSIZED:
            with self.subTest(name):
                self.assertGreater(measured.get(name, 0), BUDGET,
                                   "it is within the budget now; take it off OVERSIZED")


if __name__ == "__main__":
    unittest.main()
