"""Keep on (v0.6.13, the owner's K8, amending K7): a capability a person keeps on does not turn
itself off. Each of K7's five is noted instead - a new statement revision, a warning the person did
not confirm that says what it stands on went wrong, a hook that raises, a send it paid for gone
submission_unknown, a new Codex version - the most serious kept, with no generation and once for each
rise, until the person arms it again; a hook that raises costs only the record it raised for. What
cannot be read still holds it back, the policy reads it down first, the ceilings stay, and every move
to off - the person's, from any surface - takes it away.

Run from the repository root:

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy, surfaces  # noqa: E402
from codex_auto_resume_advanced.arming import standing  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (KEPT_NOTICES, Actor, ArmingState, ArmingWarning,  # noqa: E402
                                                   JournalCode, KeepOn, Measurement, OffReason, Refusal,
                                                   Verdict)

RECORD = {"interruption_id": ac.KEY, "thread_id": ac.THREAD}
OTHER = {"interruption_id": "b" * 64, "thread_id": ac.THREAD}
CONFIRMED = [str(KeepOn.KEEP_ON)]


class CoreView:
    """Core's view of its records as the sweep reads it: every record in `state`."""

    def __init__(self, state):
        self.state = state

    def get(self, key):
        return {"interruption_id": key, "state": self.state, "last_claim_at": None}


class KeepOnCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.rt = self.runtime()

    def row(self, capability="test_wake"):
        return self.rt.state.arming().get(capability)

    def generation(self):
        return self.rt.state.meta()["generation"]

    def keep(self, keep_on=True, capability="test_wake", **changes):
        request = dict(generation=self.generation(), confirmed=CONFIRMED, actor=Actor.DASHBOARD)
        request.update(changes)
        return self.rt.arming.set_keep_on(capability, keep_on, **request)

    def armed(self, state="armed", keep=True):
        self.assertTrue(self.arm(self.rt, state=state)["done"])
        if keep:
            self.assertTrue(self.keep()["done"])

    def kept_lines(self):
        return [entry for entry in self.rt.state.journal() if entry["code"] == JournalCode.KEPT]

    def paid(self, key=ac.KEY):
        self.now += 10
        with self.rt.state._transaction() as connection:
            self.rt.state.record_spend(connection, "main", "test_wake", ac.THREAD, key, self.now)


class SettingTests(KeepOnCase):
    def test_it_is_off_by_default_and_shown_in_the_lists(self):
        self.armed(keep=False)
        (item,) = self.rt.arming.listing()["capabilities"]
        self.assertEqual((item["keep_on"], item["notice"]), (False, None))
        self.assertFalse(self.row()["keep_on"])
        self.assertTrue(self.keep()["done"])
        (item,) = self.rt.arming.listing()["capabilities"]
        self.assertEqual((item["keep_on"], item["notice"]), (True, None))
        mcp = surfaces.answer(self.rt, "mcp", {"request": "call", "tool": "list_advanced_capabilities",
                                                 "arguments": {}})
        self.assertIs(mcp["data"]["capabilities"][0]["keep_on"], True)

    def test_only_the_dashboard_for_one_on_or_watched_after_its_warning_and_generation(self):
        self.assertEqual(self.keep()["refusal"], Refusal.NOT_ON, "nothing to keep on")
        self.armed(state="shadow", keep=False)
        for changes, refusal in (({"actor": Actor.MCP}, Refusal.NOT_THE_DASHBOARD),
                                 ({"actor": Actor.TRAY}, Refusal.NOT_THE_DASHBOARD),
                                 ({"confirmed": None}, Refusal.STALE_CONFIRMATION),
                                 ({"confirmed": ["keep_on", "other"]}, Refusal.STALE_CONFIRMATION),
                                 ({"generation": None}, Refusal.INVALID_REQUEST),
                                 ({"generation": "1"}, Refusal.INVALID_REQUEST)):
            with self.subTest(changes=changes):
                self.assertEqual(self.keep(**changes)["refusal"], refusal)
                self.assertFalse(self.row()["keep_on"])
        self.assertEqual(self.keep(generation=self.generation() - 1)["refusal"], Refusal.STALE_GENERATION)
        self.assertEqual(self.rt.arming.set_keep_on("test_wake", "yes", generation=self.generation(),
                                                    confirmed=CONFIRMED, actor=Actor.DASHBOARD)["refusal"],
                         Refusal.INVALID_REQUEST)
        self.assertEqual(self.keep(capability="nothing")["refusal"], Refusal.UNKNOWN_CAPABILITY)
        before = self.generation()
        found = self.keep()
        self.assertEqual((found["done"], found["generation"]), (True, before + 1))
        self.assertTrue(self.row()["keep_on"])
        since = self.row()["since"]
        self.now += 100
        self.assertTrue(self.keep(False, generation=None, confirmed=None)["done"], "letting go needs nothing")
        self.assertEqual((self.row()["keep_on"], self.row()["since"]), (False, since), "since is never touched")

    def test_the_policy_refuses_it_as_it_refuses_an_arm(self):
        self.armed(keep=False)
        for given, refusal in ((policy.Policy(forbid=True), Refusal.FORBIDDEN_BY_POLICY),
                               (policy.Policy(allowed=frozenset({"other"})), Refusal.NOT_ALLOWED_BY_POLICY),
                               (policy.Policy(force_shadow=True), Refusal.SHADOW_FORCED_BY_POLICY)):
            with self.subTest(given):
                self.policy = given
                self.assertEqual(self.keep()["refusal"], refusal)
        self.policy = policy.NONE
        self.assertTrue(self.keep()["done"])

    def test_every_move_to_off_takes_it_away_and_an_arm_keeps_it(self):
        for how in ("disarm", "all off", "mcp", "mcp all off", "edition entered", "tripped unkept"):
            with self.subTest(how):
                self.setUp()
                self.armed()
                if how == "disarm":
                    self.rt.arming.disarm("test_wake", actor=Actor.TRAY)
                elif how == "all off":
                    self.rt.arming.all_off(actor=Actor.CARD)
                elif how == "mcp":
                    surfaces.answer(self.rt, "mcp", {"request": "call", "tool": "disarm_advanced_capability",
                                                     "arguments": {"capability": "test_wake"}})
                elif how == "mcp all off":
                    surfaces.answer(self.rt, "mcp", {"request": "call", "tool": "disarm_all_advanced",
                                                     "arguments": {}})
                elif how == "edition entered":
                    self.rt.arming.edition_entered()
                else:
                    self.rt.state.move("test_wake", ArmingState.OFF, actor=Actor.TRIPWIRE,
                                       reason=OffReason.HOOK_EXCEPTION)
                self.assertEqual(self.row()["state"], ArmingState.OFF)
                self.assertTrue(self.arm(self.rt)["done"])
                self.assertFalse(self.row()["keep_on"], "turned on again, it is not kept on")
        self.setUp()
        self.armed()
        self.assertTrue(self.arm(self.rt, state="shadow")["done"])
        self.assertTrue(self.row()["keep_on"], "moving between on and watching keeps it")

    def test_it_is_set_through_the_bridge_and_no_mcp_tool_reaches_it(self):
        self.armed(keep=False)
        found = surfaces.answer(self.rt, "bridge", {"command": "advanced-keep-on", "argument": {
            "capability": "test_wake", "keep_on": True, "generation": self.generation(),
            "confirmed": CONFIRMED}})
        self.assertTrue(found["done"])
        self.assertTrue(self.row()["keep_on"])
        refused = surfaces.answer(self.rt, "bridge", {"command": "advanced-keep-on", "argument": {
            "capability": "test_wake", "keep_on": False, "generation": None, "warnings": []}})
        self.assertEqual(refused["refusal"], Refusal.INVALID_REQUEST)
        tools = {tool["name"] for tool in surfaces.TOOLS}
        self.assertEqual(len(tools), 3)
        for tool in tools:
            self.assertNotIn("keep", tool)


class KeptTests(KeepOnCase):
    """Each of K7's five turns a capability off; kept on, it stays where it stands, noted."""

    def assert_kept(self, notice, state=ArmingState.ARMED):
        row = self.row()
        self.assertEqual((row["state"], row["reason"]), (state, notice))
        self.assertEqual(self.rt.arming.current()["test_wake"], state)

    def five(self, how, runtime):
        """Bring about one of the five on `runtime`; the runtime that holds the capability then."""
        if how == "statement changed":
            return self.runtime(ac.definition(revision=2))
        if how == "failed here":
            self.compat = ac.view("FAILED_HERE", reason="local_check_failed_here")
        elif how == "codex changed":
            self.compat = ac.view(version="0.156.0")
        elif how == "hook raised":
            ac.code_of(runtime).answers["gate"] = RuntimeError("broken")
            self.assertIs(runtime.ask(Point.GATES, "usage", RECORD, {}), DEFER)
        elif how == "paid send unknown":
            self.paid()
            runtime.moved(dict(RECORD, state="submitting"), "submission_unknown")
        return runtime

    NOTICES = {"statement changed": OffReason.STATEMENT_CHANGED, "failed here": OffReason.FAILED_HERE,
               "codex changed": OffReason.ENGINE_CHANGED, "hook raised": OffReason.HOOK_EXCEPTION,
               "paid send unknown": OffReason.SUBMISSION_UNKNOWN}

    def test_each_of_the_five_is_noted_where_without_it_it_turns_off(self):
        for how, notice in self.NOTICES.items():
            for kept in (False, True):
                with self.subTest(how, kept=kept):
                    self.setUp()
                    self.armed(keep=kept)
                    runtime = self.five(how, self.rt)
                    self.rt = runtime
                    states = runtime.arming.current()
                    row = self.row()
                    if kept:
                        self.assertEqual((states["test_wake"], row["state"], row["reason"]),
                                         (ArmingState.ARMED, ArmingState.ARMED, notice))
                        self.assertEqual(len(self.kept_lines()), 1)
                    else:
                        self.assertEqual((states["test_wake"], row["state"]), (ArmingState.OFF, ArmingState.OFF))

    def test_two_notices_that_hold_together_write_once_the_higher_and_raise_no_generation(self):
        self.armed()
        asked = self.generation()
        self.paid()
        self.compat = ac.view(version="0.156.0")
        for _ in range(20):
            self.now += 1
            self.rt.tick(CoreView("submission_unknown"))
        row = self.row()
        self.assertEqual((row["state"], row["reason"]), (ArmingState.ARMED, OffReason.ENGINE_CHANGED))
        self.assertEqual(self.generation(), asked, "a notice decides nothing a request decides")
        self.assertEqual([entry["reason"] for entry in self.kept_lines()], [OffReason.ENGINE_CHANGED],
                         "the higher, once - never once a tick, and never flipping between the two")
        # An arm made against the generation read before them is not stale.
        self.assertTrue(self.arm(self.rt, generation=asked, acknowledged_version="0.156.0")["done"])
        row = self.row()
        self.assertEqual((row["reason"], row["keep_on"]), (None, True), "the arm clears it and keeps it on")

    def test_a_notice_only_rises(self):
        self.armed()
        self.assertTrue(self.rt.state.note_kept("test_wake", OffReason.SUBMISSION_UNKNOWN))
        self.assertFalse(self.rt.state.note_kept("test_wake", OffReason.HOOK_EXCEPTION), "lower")
        self.assertFalse(self.rt.state.note_kept("test_wake", OffReason.SUBMISSION_UNKNOWN), "the same")
        self.assertTrue(self.rt.state.note_kept("test_wake", OffReason.STATEMENT_CHANGED))
        self.assertEqual(self.row()["reason"], OffReason.STATEMENT_CHANGED)
        self.assertEqual(KEPT_NOTICES[0], OffReason.STATEMENT_CHANGED)
        self.assertEqual(set(KEPT_NOTICES) - {OffReason.ENGINE_CHANGED}, {
            reason for reason in OffReason if reason in ("statement_changed", "failed_here", "local_check_failed",
                                                         "incompatible", "measurement_failed",
                                                         "submission_unknown", "hook_exception")})

    def test_what_cannot_be_read_still_holds_it_back_and_the_policy_reads_it_down(self):
        self.armed()
        self.compat = ac.view(version=None)
        self.assertEqual(self.rt.arming.current()["test_wake"], ArmingState.OFF)
        self.assertEqual((self.row()["state"], self.row()["reason"]), (ArmingState.ARMED, None))
        self.compat = ac.view("UNKNOWN")
        self.assertEqual(self.rt.arming.current()["test_wake"], ArmingState.OFF)
        self.compat = ac.view()
        self.assertEqual(self.rt.arming.current()["test_wake"], ArmingState.ARMED)
        for given, state in ((policy.Policy(forbid=True), ArmingState.OFF),
                             (policy.Policy(allowed=frozenset()), ArmingState.OFF),
                             (policy.Policy(force_shadow=True), ArmingState.SHADOW)):
            with self.subTest(given):
                self.policy = given
                self.compat = ac.view(version="0.156.0")
                self.assertEqual(self.rt.arming.current()["test_wake"], state)
                self.assertEqual(self.row()["reason"], None, "read down first: nothing is noted")
        self.policy = policy.NONE
        self.assertEqual(self.rt.arming.current()["test_wake"], ArmingState.ARMED)

    def test_a_hook_that_raises_skips_that_record_alone(self):
        self.armed()
        code = ac.code_of(self.rt)
        def gate(name, record, facts):
            if record["interruption_id"] == ac.KEY:
                raise RuntimeError("broken")
            return Alternative.HOLD
        code.answers["gate"] = gate
        self.assertIs(self.rt.ask(Point.GATES, "usage", RECORD, {}), DEFER)
        self.assertIs(self.rt.ask(Point.GATES, "usage", OTHER, {}), Alternative.HOLD)
        asked = len(code.asked)
        self.assertIs(self.rt.ask(Point.GATES, "usage", RECORD, {}), DEFER)
        self.assertEqual(len(code.asked), asked, "passed over for that record, not asked again")
        self.assertEqual(self.row()["reason"], OffReason.HOOK_EXCEPTION)

    def test_kept_on_through_a_paid_send_gone_unknown_it_stays_on_and_pays_nothing_more(self):
        self.armed()
        self.paid()
        self.rt.moved(dict(RECORD, state="submitting"), "submission_unknown")
        self.rt.tick(CoreView("submission_unknown"))
        self.assertEqual((self.row()["state"], self.row()["reason"]), (ArmingState.ARMED, OffReason.SUBMISSION_UNKNOWN))
        self.assertEqual(self.rt.state.spent("test_wake", ac.THREAD)["conversation_day"], 1)

    def test_its_ceilings_still_hold(self):
        self.armed()
        code = ac.code_of(self.rt)
        code.answers["text"] = "Please go on."
        for index in range(self.rt.registry.get("test_wake").ceilings.per_conversation):
            self.paid("%064x" % (index + 1))
        record = dict(RECORD, category="usage_limit")
        self.assertIs(self.rt.ask(Point.TEXT, record, "core's words"), DEFER, "no unit left: kept on, still not taken")

    def test_standing_is_pure_and_kept_on_reads_the_five_as_notices(self):
        row = {"state": ArmingState.ARMED, "statement_revision": 1, "engine_version": ac.ENGINE, "keep_on": True}
        self.assertEqual(standing(ac.definition(), row, policy.NONE, ac.view()), (ArmingState.ARMED, None, None, None))
        self.assertEqual(standing(ac.definition(revision=2), row, policy.NONE, ac.view(version="0.156.0")),
                         (ArmingState.ARMED, None, None, OffReason.STATEMENT_CHANGED), "the first notice found wins")
        failed = {Measurement.M2: (Verdict.FAIL, ac.ENGINE)}
        measured = ac.definition(measurements=(Measurement.M2,))
        self.assertEqual(standing(measured, row, policy.NONE, ac.view(), failed),
                         (ArmingState.ARMED, None, None, OffReason.MEASUREMENT_FAILED))
        self.assertEqual(standing(ac.definition(), row, policy.NONE, ac.view(version=None)),
                         (ArmingState.OFF, None, ArmingWarning.ENGINE_UNKNOWN, None))
        self.assertEqual(standing(ac.definition(revision=2), row, policy.Policy(force_shadow=True), ac.view()),
                         (ArmingState.SHADOW, None, None, None))


if __name__ == "__main__":
    unittest.main()
