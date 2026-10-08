"""Once more when unsure (v0.6.14, stage 3b): RESEND at P7 for an uncertain continuation core proves
it may send once more, and what stops it.

Held against the shipped definition and statement and against core's own engine, store and
simulated Codex home (takingcase.py): off, an uncertain continuation is only followed, as in the
standard edition; armed, it goes once more after fifteen minutes, with its words and marker, paid for
with one unit and recorded as a resend in the claim; watched, it only journals; never for a record
another capability's channel paid for, never twice, never by a second capability; its resend gone
unknown turns it off, and so does a resend found twice - kept on or not.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume import config, machine  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import policy  # noqa: E402
from codex_auto_resume_advanced.engine.oncemore import OnceMore  # noqa: E402
from codex_auto_resume_advanced.registry import ONCE_MORE, Registry  # noqa: E402
from codex_auto_resume_advanced.state import AdvancedState  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingState, JournalCode, KeepOn,  # noqa: E402
                                                   OffReason, OverrideKind, Refusal)
from test_engine import T1  # noqa: E402

CAP = "once_more_when_unsure"


class OnceMoreCase(TakingCase):
    DEFINITION = ONCE_MORE

    def uncertain(self, h=None):
        """A usage-limited conversation whose continuation went out with an unknown answer; Codex
        accepts the next send."""
        h = h or self.h
        self.due(h)
        h.backend.default_outcome = "unknown"
        h.tick()
        row = h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("submission_unknown", "queue_result_unknown_do_not_resend"))
        h.backend.default_outcome = "accepted"
        return row

    def past_fifteen_minutes(self, h=None):
        """The watch's first look at it, and its next, past fifteen minutes."""
        h = h or self.h
        h.tick(advance=1)
        h.tick(advance=900)

    def hours(self, hours, h=None, step=900):
        h = h or self.h
        for _ in range(int(hours * 3600 // step)):
            h.tick(advance=step)

    def resends(self, plug):
        if not plug.runtime.state.exists():
            return []
        with plug.runtime.state._read() as connection:
            return [tuple(row) for row in connection.execute(
                "SELECT interruption_id, capability, used_at IS NULL FROM overrides WHERE kind=?",
                (OverrideKind.RESEND_ONCE,))]


class OffTests(OnceMoreCase):
    def test_off_an_uncertain_continuation_is_only_followed(self):
        plug = self.advanced()
        self.plugged(plug)
        self.uncertain()
        self.hours(7)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.assertFalse(plug.runtime.state.exists(), "nothing was ever turned on")


class ArmedTests(OnceMoreCase):
    def test_it_goes_once_after_fifteen_minutes_with_its_marker_paid_with_one_unit(self):
        plug = self.armed()
        first = self.uncertain()
        key = first["interruption_id"]
        self.h.tick(advance=1)
        self.h.tick(advance=898)
        self.assertEqual(len(self.h.backend.send_calls), 1, "nothing before fifteen minutes")
        self.h.tick(advance=2)
        self.assertEqual(len(self.h.backend.send_calls), 2)
        self.assertEqual(self.h.backend.send_calls[1], self.h.backend.send_calls[0], "the same words and marker")
        self.assertTrue(machine.was_resent(self.h.record()))
        self.assertEqual(self.spends(plug), [(CAP, T1, key)])
        self.assertEqual(self.resends(plug), [(key, CAP, 1)], "recorded in the claim, watched for a duplicate")
        self.assertIn((JournalCode.ACTED, Point.SCHEDULE, Alternative.RESEND), self.journal(plug))
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.hours(7)
        self.assertEqual(len(self.h.backend.send_calls), 2, "never a third")
        self.assertEqual(plug.runtime.state.arming()[CAP]["state"], ArmingState.ARMED)
        self.assertEqual(self.resends(plug), [(key, CAP, 1)], "watched for a second copy for a day")
        self.hours(18)
        self.assertEqual(self.resends(plug), [(key, CAP, 0)], "and no longer after it")

    def test_the_unit_is_spent_before_the_continuation_goes_again(self):
        plug = self.armed()
        key = self.uncertain()["interruption_id"]
        seen = []
        self.h.backend.on_send = lambda thread, prompt: seen.append((self.spends(plug), self.resends(plug)))
        self.past_fifteen_minutes()
        self.assertEqual(seen, [([(CAP, T1, key)], [(key, CAP, 1)])])

    def test_past_its_ceiling_nothing_is_sent_again(self):
        plug = self.armed()
        self.uncertain()
        self.fill(plug, ONCE_MORE.ceilings.per_conversation, at=self.h.now - 3600)
        self.hours(7)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertIn((JournalCode.CEILING, Point.SCHEDULE, Alternative.RESEND), self.journal(plug))


class ShadowNeverActsTests(OnceMoreCase):
    def test_watched_it_journals_what_it_would_have_done_and_sends_nothing_again(self):
        plug = self.armed(state="shadow")
        self.uncertain()
        self.hours(7)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertIn((JournalCode.WOULD_HAVE, Point.SCHEDULE, Alternative.RESEND), self.journal(plug))
        self.assertEqual((self.spends(plug), self.resends(plug)), ([], []))


class OnlyOnceTests(OnceMoreCase):
    def test_a_record_this_edition_resent_is_never_resent_by_another(self):
        """The claim holds a second resend of one record, whoever pays: RESEND_ONCE is any capability's."""
        plug = self.armed()
        row = dict(self.uncertain())
        runtime = plug.runtime
        other = "b" * 64
        with self.h.store._transaction() as connection:
            self.assertIs(runtime.ledger.claim(connection, row, self.h.now, {CAP: {Alternative.RESEND}}), DEFER)
        with self.h.store._transaction() as connection:
            self.assertIs(runtime.ledger.claim(connection, row, self.h.now + 1, {CAP: {Alternative.RESEND}}),
                          Alternative.HOLD, "never twice")
            self.assertIs(runtime.ledger.claim(connection, dict(row, interruption_id=other), self.h.now + 1,
                                               {CAP: {Alternative.RESEND}}), DEFER, "another record is another")
        self.assertTrue(runtime.state.resent(row["interruption_id"]))
        due = dict(row, submitted_at=self.h.now - 1000, last_claim_at=self.h.now - 1000)
        code = ac.code_of(runtime, CAP)
        self.assertIs(code.schedule(due, due["submitted_at"]), DEFER, "and never asked again")
        self.assertIs(code.schedule(dict(due, interruption_id="c" * 64), due["submitted_at"]), Alternative.RESEND)

    def test_its_resend_gone_unknown_turns_it_off_and_nothing_goes_a_third_time(self):
        plug = self.armed()
        self.uncertain()
        self.h.backend.default_outcome = "unknown"
        self.past_fifteen_minutes()
        self.assertEqual(len(self.h.backend.send_calls), 2)
        stored = plug.runtime.state.arming()[CAP]
        self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        self.hours(7)
        self.assertEqual(len(self.h.backend.send_calls), 2)


class DuplicateTests(OnceMoreCase):
    def test_a_resend_found_twice_turns_it_off_kept_on_or_not(self):
        for kept in (False, True):
            with self.subTest(kept=kept):
                h = self.fresh()
                plug = self.armed(h)
                if kept:
                    runtime = plug.runtime
                    self.assertTrue(runtime.arming.set_keep_on(
                        CAP, True, generation=runtime.state.meta()["generation"], confirmed=["keep_on"],
                        actor=Actor.DASHBOARD)["done"])
                row = self.uncertain(h)
                h.backend.turn_status = "completed"
                self.past_fifteen_minutes(h)
                self.follow(h)
                self.assertEqual(h.record()["state"], "recovered")
                h.home.add_turn(T1, None, "completed", user_text="go on\n\n" + row["marker"])
                h.tick(advance=61)
                self.assertEqual(h.record()["last_error"], "duplicate_marker")
                h.tick(advance=1)
                stored = plug.runtime.state.arming()[CAP]
                self.assertEqual((stored["state"], stored["reason"]), (ArmingState.OFF, OffReason.DUPLICATE_SEEN))
                self.assertEqual(self.resends(plug), [(row["interruption_id"], CAP, 0)], "the watch on it closed")
                self.assertIn(JournalCode.TRIPPED, [line["code"] for line in plug.runtime.state.journal()])


class ChannelTests(unittest.TestCase):
    """What a channel or a route paid for did more than queue words: never sent once more by this
    capability (Keep on's Send again of that very channel is the one way, test_advanced_keep_on)."""

    def test_a_send_a_channel_or_a_route_paid_for_is_never_asked_again(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        where = temporary.name
        sender = ac.definition(id="test_channel", journal_prefix="tc", points=frozenset({Point.SENDER}))
        route = ac.definition(id="test_route", journal_prefix="tr", points=frozenset({Point.UNLOADED}))
        words = ac.definition(id="test_words", journal_prefix="tx", points=frozenset({Point.TEXT}))
        state = AdvancedState(config.Paths(Path(where) / "home"),
                              registry=Registry((sender, route, words, ONCE_MORE)), clock=lambda: ac.NOW)
        self.addCleanup(state.close)
        state.move("test_words", ArmingState.SHADOW, actor=Actor.DASHBOARD, revision=1, at=ac.NOW)
        keys = {name: ("%064x" % index) for index, name in enumerate(("test_channel", "test_route", "test_words"), 1)}
        with state._transaction() as connection:
            for capability, key in keys.items():
                state.record_spend(connection, "main", capability, ac.THREAD, key, ac.NOW - 1000)
        self.assertTrue(state.channel_paid(keys["test_channel"], ac.NOW - 1000))
        self.assertTrue(state.channel_paid(keys["test_route"], ac.NOW - 1000))
        self.assertFalse(state.channel_paid(keys["test_words"], ac.NOW - 1000), "words alone are core's send")
        self.assertFalse(state.channel_paid(keys["test_channel"], ac.NOW - 2000), "another claim of it")
        self.assertTrue(state.channel_paid(keys["test_channel"], None), "a claim time that cannot be read")
        code = OnceMore(None)
        code.bind(state.scoped(CAP))
        record = {"interruption_id": keys["test_channel"], "state": "submission_unknown",
                  "last_error": "queue_result_unknown_do_not_resend", "queue_id": None, "first_queued_at": None,
                  "recovery_client_id": None, "submitted_at": ac.NOW - 1000, "last_claim_at": ac.NOW - 1000,
                  "cancel_requested": 0, "hold": None, "gate_eval": None}
        self.assertIs(code.schedule(record, record["submitted_at"]), DEFER)
        self.assertIs(code.schedule(dict(record, interruption_id=keys["test_words"]), ac.NOW - 1000),
                      Alternative.RESEND)


class CodeTests(unittest.TestCase):
    class Scoped:
        def __init__(self, now, *, resent=False, paid=False, broken=False):
            self.at, self._resent, self._paid, self._broken = now, resent, paid, broken

        def now(self):
            return self.at

        def resent(self, key):
            if self._broken:
                raise RuntimeError("locked")
            return self._resent

        def channel_paid(self, key, claimed_at):
            return self._paid

    def record(self, **changes):
        sent = 10_000.0
        return dict({"interruption_id": ac.KEY, "state": "submission_unknown",
                     "last_error": "queue_result_unknown_do_not_resend", "queue_id": None, "first_queued_at": None,
                     "recovery_client_id": None, "submitted_at": sent, "last_claim_at": sent,
                     "cancel_requested": 0, "hold": None, "gate_eval": None}, **changes)

    def code(self, now=10_000.0 + 1000, **scoped):
        made = OnceMore(None)
        made.bind(self.Scoped(now, **scoped))
        return made

    def test_resend_only_for_an_uncertain_submission_core_could_send_once_more(self):
        self.assertIs(self.code().schedule(self.record(), 10_000.0), Alternative.RESEND)
        for changes in ({"state": "waiting_reset"}, {"state": "queued"}, {"last_error": "duplicate_marker"},
                        {"queue_id": "0a1b2c3d-0001-7000-8000-00000000000a"}, {"first_queued_at": 10_001.0},
                        {"cancel_requested": 1}, {"submitted_at": 10_000.0 + 600},
                        {"submitted_at": 10_000.0 - 6 * 3600}):
            with self.subTest(changes):
                self.assertIs(self.code().schedule(self.record(**changes), 10_000.0), DEFER)

    def test_never_send_now_never_twice_never_for_a_channel_and_never_unbound(self):
        self.assertIsNot(self.code().schedule(self.record(state="waiting_backoff"), 10_000.0), Alternative.SEND_NOW)
        self.assertIs(self.code(resent=True).schedule(self.record(), 10_000.0), DEFER)
        self.assertIs(self.code(paid=True).schedule(self.record(), 10_000.0), DEFER)
        self.assertIs(self.code(broken=True).schedule(self.record(), 10_000.0), DEFER, "a state it cannot read")
        self.assertIs(OnceMore(None).schedule(self.record(), 10_000.0), DEFER)
        self.assertIs(self.code().schedule("not a record", 10_000.0), DEFER)


class PolicyTests(OnceMoreCase):
    def test_not_allowed_it_reads_off_and_sends_nothing_again(self):
        plug = self.armed()
        self.uncertain()
        self.policy = policy.Policy(allowed=frozenset({"capacity_retry"}))
        plug.runtime.states(fresh=True)
        self.hours(2)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        result = plug.runtime.arming.arm(CAP, state="armed", revision=1, generation=plug.runtime.state.meta()
                                         ["generation"], acknowledged_version=ac.ENGINE, actor=Actor.DASHBOARD)
        self.assertEqual(result["refusal"], Refusal.NOT_ALLOWED_BY_POLICY)

    def test_it_is_never_given_send_again_which_would_be_itself(self):
        plug = self.armed()
        runtime = plug.runtime
        found = runtime.arming.set_keep_on(CAP, True, send_again=True, generation=runtime.state.meta()["generation"],
                                           confirmed=["keep_on", "send_again"], actor=Actor.DASHBOARD)
        self.assertEqual(found["refusal"], Refusal.INVALID_REQUEST)
        self.assertEqual([str(word) for word in KeepOn], ["keep_on", "send_again"])


class HookTests(OnceMoreCase):
    def test_a_hook_that_raises_trips_it_and_sends_nothing_again(self):
        plug = self.armed()
        self.uncertain()
        with patch.object(OnceMore, "schedule", side_effect=RuntimeError("boom")):
            self.past_fifteen_minutes()
        self.assertEqual(plug.runtime.state.arming()[CAP]["reason"], OffReason.HOOK_EXCEPTION)
        self.hours(2)
        self.assertEqual(len(self.h.backend.send_calls), 1)


if __name__ == "__main__":
    unittest.main()
