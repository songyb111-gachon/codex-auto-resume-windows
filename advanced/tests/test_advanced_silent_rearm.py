"""silent_continuation turned on again after Codex refused a turn with no input is asked again (v0.6.18, the advanced
audit's M2): before, the process's refusal stayed for the watcher's life, so the Dashboard showed it on while it answered
DEFER until a restart. A refusal met again turns it off again.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from codex_auto_resume.domain.plug import DEFER, Alternative  # noqa: E402
from codex_auto_resume_advanced.codex import headless  # noqa: E402
from codex_auto_resume_advanced.vocabulary import ArmingState, OffReason  # noqa: E402
import test_advanced_silent_continuation as silent_tests  # noqa: E402
from takingcase import TakingCase  # noqa: E402

RECORD = {"interruption_id": "%064x" % 1, "state": "submitting"}


class RearmTests(TakingCase):
    DEFINITION = silent_tests.SILENT_CONTINUATION
    on = silent_tests.TripTests.on

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, headless, "EMPTY_REFUSED", headless.EMPTY_REFUSED)
        headless.EMPTY_REFUSED = False

    def refused(self, plug):
        headless.EMPTY_REFUSED = True
        plug.runtime.moved(RECORD, "waiting_retry")
        self.assertEqual(plug.runtime.states(fresh=True).get(self.cap, ArmingState.OFF), ArmingState.OFF)
        self.assertEqual(plug.runtime.state.arming()[self.cap]["reason"], OffReason.REFUSED_BY_CODEX)

    def test_turned_on_again_it_answers_silent_and_a_new_refusal_trips_it_again(self):
        """Fails with the re-arm reverted: on again, it answered DEFER until the watcher restarted."""
        plug = self.on()
        self.refused(plug)
        self.h.now += 5
        self.on()                                        # on again, from the Dashboard (the same home)
        plug.runtime.states(fresh=True)
        self.assertFalse(headless.EMPTY_REFUSED, "a person's choice made since the refusal")
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        self.assertIs(code.delivery({}), Alternative.SILENT)
        self.refused(plug)
        self.assertIs(code.delivery({}), DEFER)

    def test_without_a_new_choice_it_stays_refused(self):
        plug = self.on()
        self.refused(plug)
        self.h.now += 5
        plug.runtime.states(fresh=True)
        self.assertTrue(headless.EMPTY_REFUSED)

if __name__ == "__main__":
    unittest.main()
