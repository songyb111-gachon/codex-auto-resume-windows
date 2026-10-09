"""Use a reset credit when the limit a person picked is reached (v0.6.14): reset_credit, at P8 and P7.

Held against the shipped definition and statement and against core's own engine, store and simulated Codex home
(takingcase.py), with this capability's session a fake that answers what each test tells it: off, nothing is read
or spent; on, a rule counts the fills of its window from its adoption and, at its own, while a recovery waits for
usage, spends one credit - only with the window still full and the count and the expiry readable, one a filling,
two a day and seven a week, written before it is asked and asked inside core's errand guard, on its own only once
MR passed and the person did not ask to be asked first - and then looks early at the waiting recovery, which goes
at once; an answer that cannot be known is asked once more with the same key where MR passed, and otherwise turns
it off; and Codex refusing the method spends nothing and asks again never.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume.codex.errors import AdapterError  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative  # noqa: E402
from codex_auto_resume_advanced.codex import protocol  # noqa: E402
from codex_auto_resume_advanced.engine import credits as reset_credit  # noqa: E402
from codex_auto_resume_advanced.engine.resetwatch import POLL  # noqa: E402
from codex_auto_resume_advanced.registry import EARLY_RESET, RESET_CREDIT  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ArmingState, Measurement, OffReason, RuleReason,  # noqa: E402
                                                   RuleState, SpendOutcome, Verdict)
from test_engine import T1, TURN_A  # noqa: E402
from codexsim import RESET as _RESET  # noqa: E402
RESET = int(_RESET)

READ, CONSUME = "account/rateLimits/read", "account/rateLimitResetCredit/consume"
FIVE = ("codex", 300)


def usage(used, reset_at, *, count=2, listed=True, expires=1_900_000_000):
    """Codex's usage reply: one 5-hour window, and the reset credits - with an id and a title this edition never
    keeps."""
    credits_ = [{"id": "rc_secret", "title": "for ExampleUser", "grantedAt": 1, "expiresAt": expires,
                 "resetType": "codexRateLimits", "status": "available"}] * min(count, 1)
    return {"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": used, "windowDurationMins": 300,
                                                          "resetsAt": reset_at}}},
            "rateLimitResetCredits": {"availableCount": count, "credits": credits_ if listed else None}}


class FakeCodex:
    """The capability's session: usage replies in turn and consume answers in turn - the last of each repeating -
    and every call written down, and what a guard said when the consume was written."""

    def __init__(self, reads, consumes=({"outcome": "reset"},)):
        self.reads, self.consumes, self.calls, self.opened = list(reads), list(consumes), [], 0
        self.on_submit = None

    def __enter__(self):
        self.opened += 1
        return self

    def __exit__(self, *unused):
        return False

    @staticmethod
    def _next(queue_):
        reply = queue_.pop(0) if len(queue_) > 1 else queue_[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    def call(self, method, params=None):
        self.calls.append((method, params))
        return self._next(self.reads)

    def submit(self, method, params=None):
        self.calls.append((method, params))
        if self.on_submit is not None:
            self.on_submit(params)
        return len(self.calls)

    def receive(self, method, sequence, params=None, seconds=25):
        return self._next(self.consumes)

    def consumed(self):
        return [params for method, params in self.calls if method == CONSUME]


class CreditCase(TakingCase):
    DEFINITION = RESET_CREDIT

    def setUp(self):
        super().setUp()
        self.measured = {Measurement.MU: (Verdict.PASS, ac.ENGINE), Measurement.MN: (Verdict.PASS, ac.ENGINE),
                         Measurement.MR: (Verdict.PASS, ac.ENGINE)}
        self.codex = FakeCodex([usage(40, RESET + 3600)])
        patcher = patch.object(reset_credit.ResetCredit, "_session", lambda code: self.codex)
        patcher.start()
        self.addCleanup(patcher.stop)

    def armed(self, h=None, state="armed"):
        h = h or self.h
        plug = self.advanced(h)
        runtime = plug.runtime
        definition = runtime.registry.get(self.cap)
        self.arm(plug, state=state, warnings=list(runtime.arming.warnings(definition)))
        self.plugged(plug, h)
        return plug

    def rule(self, plug, ordinal=1, **changes):
        return plug.runtime.state.add_reset_rule(self.cap, "codex", 300, ordinal, **changes)

    def waiting(self, h=None):
        """A usage-limited recovery that waits for its reset, an hour ahead."""
        h = h or self.h
        h.home.fail_usage(T1, TURN_A)
        h.backend.loaded_map[T1] = "loaded"
        h.backend.after_accept = "queue"
        h.tick()
        self.assertEqual(h.record()["state"], "waiting_reset")

    def fill(self, plug, *, then=None):
        """The rule adopted on a window 40 % used, then the window full at the next poll: the fill it waits for."""
        self.codex.reads = [usage(40, RESET + 3600), usage(100, RESET + 3600)] + list(then or [usage(100, RESET + 3600)])
        self.h.tick()
        self.h.tick(advance=POLL)

    def found(self, plug, rule):
        return plug.runtime.state.reset_rule(rule)


class OffTests(CreditCase):
    def test_off_nothing_is_read_and_nothing_is_spent(self):
        plug = self.advanced()
        self.plugged(plug)
        self.waiting()
        self.h.tick(advance=POLL)
        self.assertEqual(self.codex.calls, [])
        self.assertFalse(plug.runtime.state.exists())


class SpendTests(CreditCase):
    def test_the_fill_it_waits_for_spends_one_credit_and_the_waiting_recovery_goes_at_once(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.fill(plug, then=[usage(100, RESET + 3600), usage(0, None, count=1)])
        consumed = self.codex.consumed()
        self.assertEqual(len(consumed), 1)
        self.assertEqual(set(consumed[0]), {"idempotencyKey"}, "Codex picks the credit: no credit id is held")
        done = self.found(plug, rule)
        self.assertEqual((done["state"], done["reason"]), (RuleState.DONE, RuleReason.SPENT))
        spend = plug.runtime.state.credit_spends()[0]
        self.assertEqual((spend["outcome"], spend["occasion"], spend["attempt_id"]),
                         (SpendOutcome.RESET, 1, consumed[0]["idempotencyKey"]))
        self.assertEqual(plug.runtime.state.windows()[FIVE]["resets"], 1, "its own reset closes the window")
        self.h.backend.usage_result = {"available": True, "reset_at": None, "limit_type": "exposed_windows", "reason": "ok"}
        self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1, "looked at early, and sent")
        self.assertLess(self.h.now, RESET)
        self.assertEqual(plug.runtime.state.samples(self.cap), {"hit": 1, "spent": 1})

    def test_a_window_full_when_the_rule_is_made_is_not_its_next_limit(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.reads = [usage(100, RESET + 3600)]
        self.h.tick()
        self.h.tick(advance=POLL)
        self.assertEqual(self.codex.consumed(), [])
        self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["base"]), (RuleState.COUNTING, 1))

    def test_with_no_recovery_waiting_nothing_is_spent(self):
        """The owner's rule: the chosen limit filling with nothing waiting spends nothing."""
        plug = self.armed()
        rule = self.rule(plug)
        self.fill(plug)
        self.assertEqual(self.codex.consumed(), [])
        self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["reason"]),
                         (RuleState.READY, RuleReason.NOTHING_WAITING))

    def test_until_mr_passes_or_when_asked_to_ask_it_asks_first(self):
        for how in ("mr not passed", "ask first"):
            with self.subTest(how):
                h = self.fresh()
                if how == "mr not passed":
                    self.measured = {Measurement.MU: (Verdict.PASS, ac.ENGINE)}
                self.waiting(h)
                plug = self.armed(h)
                rule = self.rule(plug, ask_first=how == "ask first")
                self.h, saved = h, self.h
                try:
                    self.fill(plug)
                finally:
                    self.h = saved
                self.assertEqual(self.codex.consumed(), [])
                self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["reason"]),
                                 (RuleState.READY, RuleReason.ASK_FIRST))
                self.measured[Measurement.MR] = (Verdict.PASS, ac.ENGINE)

    def test_a_count_or_an_expiry_it_cannot_read_spends_nothing(self):
        for reply, reason in ((usage(100, RESET + 3600, listed=False), RuleReason.EXPIRY_UNKNOWN),
                              (dict(usage(100, RESET + 3600), rateLimitResetCredits=None), RuleReason.COUNT_UNKNOWN),
                              (usage(100, RESET + 3600, count=2, listed=True, expires="soon"), RuleReason.EXPIRY_UNKNOWN)):
            with self.subTest(reason=reason):
                h = self.fresh()
                self.waiting(h)
                plug = self.armed(h)
                rule = self.rule(plug)
                self.h, saved = h, self.h
                try:
                    self.fill(plug, then=[reply])
                finally:
                    self.h = saved
                self.assertEqual(self.codex.consumed(), [])
                self.assertEqual(self.found(plug, rule)["reason"], reason)

    def test_none_left_ends_it_and_asks_codex_nothing(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.fill(plug, then=[usage(100, RESET + 3600, count=0)])
        self.assertEqual(self.codex.consumed(), [])
        self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["reason"]),
                         (RuleState.DONE, RuleReason.NO_CREDIT))

    def test_two_a_day_at_most(self):
        self.waiting()
        plug = self.armed()
        state = plug.runtime.state
        other = self.rule(plug, ordinal=2)
        for occasion in (7, 8):
            spend = state.add_credit_spend(other, "codex", 300, occasion, "0a1b2c3d-0001-4000-8000-00000000000%d" % occasion,
                                           at=self.h.now - 3600)
            state.finish_credit_spend(spend, SpendOutcome.RESET)
        rule = self.rule(plug)
        self.fill(plug)
        self.assertEqual(self.codex.consumed(), [])
        self.assertEqual(self.found(plug, rule)["reason"], RuleReason.BOUND)

    def test_the_spend_is_written_before_codex_is_asked_and_inside_the_guard(self):
        self.waiting()
        plug = self.armed()
        self.rule(plug)
        seen = []
        self.codex.on_submit = lambda params: seen.append(
            [spend["attempt_id"] for spend in plug.runtime.state.credit_spends()])
        self.fill(plug)
        self.assertEqual(seen, [[self.codex.consumed()[0]["idempotencyKey"]]])

    def test_a_guard_that_refuses_asks_codex_nothing_and_keeps_no_spend(self):
        """Observe only, set in the store, refuses the errand's one write (store/plugclaims.py)."""
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.reads = [usage(40, RESET + 3600)]
        self.h.tick()
        self.h.store.set_observe_only(True)
        self.codex.reads = [usage(100, RESET + 3600)]
        self.h.tick(advance=POLL)
        self.assertEqual(self.codex.consumed(), [])
        self.assertEqual(plug.runtime.state.credit_spends(), [])
        self.assertEqual(self.found(plug, rule)["state"], RuleState.READY, "it waits, and tries again")

    def test_codex_refusing_the_method_spends_nothing_and_asks_again_never(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.consumes = [protocol._refused_by_codex(CONSUME, -32601)]
        self.fill(plug)
        self.assertEqual(len(self.codex.consumed()), 1)
        self.assertEqual(self.found(plug, rule)["reason"], RuleReason.NO_METHOD)
        self.assertEqual(plug.runtime.state.credit_spends(), [])
        self.h.tick(advance=POLL)
        self.assertEqual(len(self.codex.consumed()), 1)

    def test_use_now_spends_nothing_while_no_recovery_waits_and_one_once_a_recovery_does(self):
        """The owner's rule holds for a click too: no credit is used unless a recovery is waiting for usage."""
        from codex_auto_resume_advanced.control import resets
        plug = self.armed()
        self.rule(plug)
        self.fill(plug)
        clicked = resets.credit_now(plug.runtime, {"generation": plug.runtime.state.meta()["generation"]})
        self.assertTrue(clicked["done"], clicked)
        self.h.tick(advance=5)
        self.assertEqual(self.codex.consumed(), [])
        now = self.found(plug, clicked["rule"])
        self.assertEqual((now["state"], now["reason"]), (RuleState.READY, RuleReason.NOTHING_WAITING))
        self.waiting()
        self.assertEqual(len(self.codex.consumed()), 1)
        self.assertEqual(self.found(plug, clicked["rule"])["reason"], RuleReason.SPENT)

    def test_a_due_rule_that_cannot_spend_reads_usage_at_most_once_in_five_minutes(self):
        """Observe only refuses its one write at every look; it reads again five minutes on, not at every tick."""
        from codex_auto_resume_advanced.engine.resetwatch import READ_SPACING
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.reads = [usage(40, RESET + 3600)]
        self.h.tick()
        self.h.store.set_observe_only(True)
        self.codex.reads = [usage(100, RESET + 3600)]
        self.h.tick(advance=POLL)
        self.assertEqual(self.found(plug, rule)["state"], RuleState.READY)

        def reads():
            return len([call for call in self.codex.calls if call[0] == READ])
        before, opened = reads(), self.codex.opened
        for _ in range(12):
            self.h.tick(advance=5)
        self.assertEqual((reads() - before, self.codex.opened - opened), (0, 0))
        self.h.now += READ_SPACING
        self.h.tick()
        self.assertEqual(reads() - before, 1)
        self.assertEqual(self.codex.consumed(), [])


class UnknownTests(CreditCase):
    def test_an_error_codex_answers_but_no_such_method_is_unknown_and_never_spent_under_a_second_key(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.consumes = [protocol._refused_by_codex(CONSUME, -32603), {"outcome": "alreadyRedeemed"}]
        self.fill(plug)
        (spend,) = plug.runtime.state.credit_spends()
        self.assertEqual(spend["outcome"], None, "Codex's error says nothing of what it spent")
        self.assertNotEqual(self.found(plug, rule)["reason"], RuleReason.NO_METHOD)
        from codex_auto_resume_advanced.control import resets
        resets.credit_now(plug.runtime, {"rule": rule, "generation": plug.runtime.state.meta()["generation"]})
        self.h.tick(advance=5)
        self.assertEqual(len(self.codex.consumed()), 1, "a click spends no second key for the same filling")
        self.h.tick(advance=reset_credit.UNKNOWN_AFTER)
        keys = [params["idempotencyKey"] for params in self.codex.consumed()]
        self.assertEqual((len(keys), len(set(keys))), (2, 1), "asked once more, with its own key")
        self.assertEqual(plug.runtime.state.credit_spends()[0]["outcome"], SpendOutcome.ALREADY_REDEEMED)

    def test_an_answer_that_cannot_be_known_is_asked_again_with_its_own_key_where_mr_passed(self):
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        self.codex.consumes = [AdapterError("protocol_timeout"), {"outcome": "alreadyRedeemed"}]
        self.fill(plug)
        self.assertEqual(plug.runtime.state.credit_spends()[0]["outcome"], None)
        self.h.tick(advance=reset_credit.UNKNOWN_AFTER)
        keys = [params["idempotencyKey"] for params in self.codex.consumed()]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 1, "never a second key for one occasion")
        self.assertEqual(plug.runtime.state.credit_spends()[0]["outcome"], SpendOutcome.ALREADY_REDEEMED)
        self.assertEqual(self.found(plug, rule)["reason"], RuleReason.SPENT)

    def test_without_mr_an_unknown_answer_ends_the_rule_and_turns_it_off(self):
        self.measured = {Measurement.MU: (Verdict.PASS, ac.ENGINE)}
        self.waiting()
        plug = self.armed()
        rule = self.rule(plug)
        state = plug.runtime.state
        spend = state.add_credit_spend(rule, "codex", 300, 0, "0a1b2c3d-0001-4000-8000-000000000099", at=self.h.now)
        self.codex.reads = [usage(40, RESET + 3600)]
        self.h.tick(advance=reset_credit.UNKNOWN_AFTER)
        self.assertEqual(self.codex.consumed(), [], "asked again never")
        self.assertEqual(state.credit_spends()[0]["outcome"], SpendOutcome.UNKNOWN)
        self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["reason"]),
                         (RuleState.DONE, RuleReason.UNKNOWN))
        row = state.arming()[self.cap]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        self.assertIsNotNone(spend)


class ScheduleTests(CreditCase):
    def code(self, plug):
        return plug.runtime._code_of(plug.runtime.registry.get(self.cap))

    def test_early_for_fifteen_minutes_after_its_reset_then_defer(self):
        plug = self.armed()
        code = self.code(plug)
        record = {"category": "usage_limit", "state": "waiting_reset", "interruption_id": ac.KEY}
        due = self.h.now + 3600
        self.assertIs(code.schedule(record, due), DEFER, "no reset of its own yet")
        state = plug.runtime.state
        rule = self.rule(plug)
        spend = state.add_credit_spend(rule, "codex", 300, 1, "0a1b2c3d-0001-4000-8000-000000000001")
        state.finish_credit_spend(spend, SpendOutcome.RESET)
        self.assertIs(code.schedule(record, due), Alternative.EARLY)
        for other in (dict(record, category="network_transient"), dict(record, state="queued")):
            self.assertIs(code.schedule(other, due), DEFER)
        self.assertIs(code.schedule(record, self.h.now - 1), DEFER, "due already: nothing to look early at")
        self.h.now += reset_credit.EARLY_FOR
        self.assertIs(code.schedule(record, due), DEFER)

    def test_early_reset_lets_go_of_a_look_this_took(self):
        early = EARLY_RESET.make(None)
        early.probe_at, early.released = self.h.now, {ac.KEY}
        early.not_taken({"interruption_id": ac.KEY})
        self.assertEqual(early.released, set())
        self.assertIs(early.gate("usage", {"interruption_id": ac.KEY}, {"schedule": ("PASS", "plugged")}), DEFER)


class SessionTests(unittest.TestCase):
    def test_its_session_reads_usage_and_spends_and_nothing_else(self):
        allowed = protocol.methods_for_capability("reset_credit")
        self.assertEqual(allowed - {"initialize", "initialized"}, {READ, CONSUME})

    def test_the_one_write_and_its_answer_are_apart(self):
        session = protocol.Session.__new__(protocol.Session)
        session.allowed = protocol.methods_for_capability("reset_credit")
        session.sequence, session._subscribed, written = 0, [], []
        session._write = written.append
        import queue as queue_module
        session.responses = queue_module.Queue()
        sequence = session.submit(CONSUME, {"idempotencyKey": "k"})
        self.assertEqual(written, [{"id": sequence, "method": CONSUME, "params": {"idempotencyKey": "k"}}])
        session.responses.put({"id": sequence, "result": {"outcome": "reset"}})
        self.assertEqual(session.receive(CONSUME, sequence), {"outcome": "reset"})
        with self.assertRaises(protocol.SessionRefused):
            session.submit("thread/queue/add", {})


if __name__ == "__main__":
    unittest.main()
