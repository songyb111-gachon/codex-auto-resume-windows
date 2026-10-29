"""NeutralPlug, share 2 of 4: the scenarios of tests/test_neutral_plug.py's SHARES[1], each the same with a plug that defers.

Every scenario in this share is run as it is written, once with NULL and once with a plug that is asked at every point
and defers at every one of them (and, in the advanced lane, a third time with the advanced package's own plug, nothing
on), and the runs have to leave the same rows and make the same calls of Codex (tests/neutral.py). The comparison was
one test of every scenario, and one file is what scripts/test_parts.py deals into a CI part; tests/test_neutral_plug.py
holds that the four shares together are every scenario exactly once.

    PYTHONPATH=src;tests python -m unittest test_neutral_plug_2
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import test_neutral_plug  # noqa: E402 - its cases are not bound here, so they run in their own module alone

SHARE = 2


class NeutralPlugShareTests(unittest.TestCase):
    def test_every_scenario_of_this_share_is_the_same_with_a_plug_that_always_defers(self):
        test_neutral_plug.check_share(self, SHARE)


if __name__ == "__main__":
    unittest.main()
