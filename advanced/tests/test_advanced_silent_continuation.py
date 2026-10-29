"""Continue with no words (v0.6.16-beta.4): P15's SILENT while on, until Codex refuses a turn with no input - then
DEFER in this process, so the next attempt carries words, and the capability turns off (REFUSED_BY_CODEX) - or, kept
on (v0.6.19-beta.3), notes it and stays on, still answering DEFER; listed beside marker-free continuation.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative  # noqa: E402
from codex_auto_resume_advanced import registry  # noqa: E402
from codex_auto_resume_advanced.codex import headless, protocol  # noqa: E402
from codex_auto_resume_advanced.engine.silent import SilentContinuation  # noqa: E402
from codex_auto_resume_advanced.registry import SILENT_CONTINUATION  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, ArmingWarning, JournalCode,  # noqa: E402
                                                   Measurement, OffReason, Refusal, Verdict)
from test_advanced_headless import CLIENT, RouteCase  # noqa: E402


class Flag(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, headless, "EMPTY_REFUSED", headless.EMPTY_REFUSED)
        headless.EMPTY_REFUSED = False


class CodeTests(Flag):
    def test_silent_until_codex_refuses_a_turn_with_no_input(self):
        code = SilentContinuation(None)
        self.assertIs(code.delivery({}), Alternative.SILENT)
        headless.EMPTY_REFUSED = True
        self.assertIs(code.delivery({}), DEFER, "the next attempt carries words")


class RouteTests(RouteCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, headless, "EMPTY_REFUSED", headless.EMPTY_REFUSED)
        headless.EMPTY_REFUSED = False

    def test_a_refused_turn_with_no_input_is_remembered_and_one_with_words_is_not(self):
        """Fails with the flag reverted: Codex refusing no words would be met again on every attempt."""
        refusing = {"turn/start": protocol._refused_by_codex("turn/start", -32600)}
        self.assertEqual(self.resume(self.route(replies=refusing))["outcome"], "not_started")
        self.assertFalse(headless.EMPTY_REFUSED, "words were given: not this refusal")
        answered = self.route(replies=refusing).resume(
            "0a1b2c3d-0001-7000-8000-000000000001", still_unloaded=lambda: True, words="", client_id=CLIENT)
        self.assertEqual(answered["outcome"], "not_started")
        self.assertTrue(headless.EMPTY_REFUSED)

    def test_no_words_starts_the_turn_with_no_input_under_the_client_id(self):
        self.resume(self.route(), words="")
        params = dict(self.servers[0].calls)["turn/start"]
        self.assertEqual((params["input"], params["clientUserMessageId"]), ([], CLIENT))
        self.ended()


class TripTests(TakingCase):
    DEFINITION = SILENT_CONTINUATION

    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, headless, "EMPTY_REFUSED", headless.EMPTY_REFUSED)
        headless.EMPTY_REFUSED = False

    def on(self):
        plug = self.advanced()
        definition = plug.runtime.registry.get(self.cap)
        result = plug.runtime.arming.arm(
            self.cap, state="armed", revision=definition.revision, generation=plug.runtime.state.meta()["generation"],
            acknowledged_version=ENGINE, actor=Actor.DASHBOARD,
            warnings=[str(word) for word in plug.runtime.arming.warnings(definition)])
        self.assertTrue(result["done"], result)
        plug.runtime.states(fresh=True)
        return plug

    def test_codex_refusing_no_input_turns_it_off(self):
        plug = self.on()
        plug.runtime.moved({"interruption_id": "%064x" % 1, "state": "submitting"}, "waiting_retry")
        self.assertEqual(plug.runtime.states(fresh=True)[self.cap], ArmingState.ARMED, "nothing refused yet")
        headless.EMPTY_REFUSED = True
        plug.runtime.moved({"interruption_id": "%064x" % 1, "state": "submitting"}, "waiting_retry")
        self.assertEqual(plug.runtime.states(fresh=True).get(self.cap, ArmingState.OFF), ArmingState.OFF)
        self.assertEqual(plug.runtime.state.arming()[self.cap]["reason"], OffReason.REFUSED_BY_CODEX)

    def kept(self, plug):
        kept = plug.runtime.arming.set_keep_on(self.cap, True, generation=plug.runtime.state.meta()["generation"],
                                               confirmed=["keep_on"], actor=Actor.DASHBOARD)
        self.assertEqual((kept["done"], kept["refusal"]), (True, None))
        plug.runtime.states(fresh=True)
        return plug

    def test_it_may_be_kept_on_and_is_listed_beside_marker_free_continuation(self):
        """The owner's word of 2026-10-24 (v0.6.19-beta.3): Keep on is offered for it. Fails with Keep on refused for it
        again. DECISIONS Q12: beside the other continuation that goes without a marker."""
        plug = self.kept(self.on())
        self.assertTrue(plug.runtime.state.arming()[self.cap]["keep_on"])
        shown = registry.SHOWN_ORDER
        self.assertEqual(shown.index(self.cap), shown.index("marker_free_continuation") + 1)

    def test_kept_on_codex_refusing_no_input_is_a_note_and_the_next_attempt_carries_words(self):
        """Fails with the refusal turning it off whatever Keep on says: kept on, it stays on with the note journalled
        once, and it answers DEFER from then on, so no empty turn is tried again."""
        plug = self.kept(self.on())
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        self.assertIs(code.delivery({}), Alternative.SILENT)
        self.h.now += 5                                  # Codex refuses after it was kept on
        headless.EMPTY_REFUSED = True
        plug.runtime.moved({"interruption_id": "%064x" % 1, "state": "submitting"}, "waiting_retry")
        plug.runtime.moved({"interruption_id": "%064x" % 2, "state": "submitting"}, "waiting_retry")
        self.h.now += 5
        self.assertEqual(plug.runtime.states(fresh=True)[self.cap], ArmingState.ARMED)
        row = plug.runtime.state.arming()[self.cap]
        self.assertEqual((row["state"], row["keep_on"], row["reason"]),
                         (ArmingState.ARMED, True, OffReason.REFUSED_BY_CODEX))
        kept = [line for line in plug.runtime.state.journal(capability=self.cap) if line["code"] == JournalCode.KEPT]
        self.assertEqual(len(kept), 1)
        self.assertTrue(headless.EMPTY_REFUSED, "kept on is no new choice: the refusal is remembered")
        self.assertIs(code.delivery({}), DEFER)

    def test_unmeasured_on_this_codex_is_a_warning_never_a_refusal(self):
        plug = self.advanced()
        definition = plug.runtime.registry.get(self.cap)
        self.assertIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))
        self.measured = {Measurement.M3B: (Verdict.PASS, ENGINE)}
        self.assertNotIn(ArmingWarning.UNMEASURED, plug.runtime.arming.warnings(definition))


if __name__ == "__main__":
    unittest.main()
