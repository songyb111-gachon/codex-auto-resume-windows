"""Released calls, share 3 of 4: at the defaults, the scenarios of tests/test_released_calls.py's SHARES[2] ask Codex what v0.6.10 asked.

Every scenario in this share runs twice, in worker processes of its own: against the tagged v0.6.10 package and against
this checkout, and the calls each made of its Codex backend must be the same, scenario by scenario, with only the
marker shortened (tests/test_released_calls.py says why, and what an amended scenario may differ in). The comparison was
one test of every scenario, and one file is what scripts/test_parts.py deals into a CI part; tests/test_released_calls.py
holds that the four shares together are every scenario exactly once.

    PYTHONPATH=src;tests python -m unittest test_released_calls_3
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import test_released_calls  # noqa: E402 - its cases are not bound here, so they run in their own module alone

SHARE = 3


class ReleasedCallsShareTests(unittest.TestCase):
    def test_at_the_defaults_every_scenario_of_this_share_asks_codex_what_v0_6_10_asked(self):
        test_released_calls.check_share(self, SHARE)


if __name__ == "__main__":
    unittest.main()
