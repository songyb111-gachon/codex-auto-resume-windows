"""A message of a person's own, sent when the window they picked resets (v0.6.14): reset_message at P8, P2, P3.

Held against the shipped definition and statement and against core's own engine, store and simulated Codex home
(takingcase.py), this capability's usage reads a fake that answers what each test tells it: off or watched,
nothing is sent; on, a message counts the resets of its window from its adoption and, at its own, goes once,
exactly as written with its marker after a blank line, through core's gates and its one claim - and, when a
continuation waits in that conversation for the same reset, only the message goes, at the very tick; its words
leave the state at its send, at a cancel, at expiry and when the capability is turned off; a conversation switched
off cancels it; one that never started waits again with its words; one that cannot be proven a day after it was
sent turns the capability off; one in flight holds core's claims on that conversation; and its words reach no
log, journal, diagnostics export, status or MCP reply.

    PYTHONPATH=src python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Surface, guard  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402
from codex_auto_resume_advanced.engine import resetmessage  # noqa: E402
from codex_auto_resume_advanced.engine.resetwatch import CLOSE_AFTER, POLL  # noqa: E402
from codex_auto_resume_advanced.registry import LONG_RESET_MESSAGE, RESET_MESSAGE  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (ArmingState, Measurement, OffReason, RecordState,  # noqa: E402
                                                   RuleReason, RuleState, Verdict)
from test_engine import T1, T2, TURN_A  # noqa: E402
from codexsim import RESET as _RESET  # noqa: E402

RESET = int(_RESET)
WORDS = "SENTINEL-7f3a: please rerun the migration from step four."


def usage(used, reset_at):
    return {"rateLimitsByLimitId": {"codex": {"primary": {"usedPercent": used, "windowDurationMins": 300,
                                                          "resetsAt": reset_at}}},
            "rateLimitResetCredits": {"availableCount": 0, "credits": []}}


class FakeCodex:
    def __init__(self, *reads):
        self.reads, self.calls = list(reads), []

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params=None):
        self.calls.append((method, params))
        reply = self.reads.pop(0) if len(self.reads) > 1 else self.reads[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


class MessageCase(TakingCase):
    DEFINITION = RESET_MESSAGE
    BESIDE = (LONG_RESET_MESSAGE,)

    def setUp(self):
        super().setUp()
        self.measured = {Measurement.MU: (Verdict.PASS, ac.ENGINE)}
        self.codex = FakeCodex(usage(40, RESET))
        patcher = patch.object(resetmessage.ResetMessage, "_session", lambda code: self.codex)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.h.home.add_turn(T1)
        self.h.backend.loaded_map[T1] = "loaded"

    def armed(self, h=None, state="armed", long=False):
        h = h or self.h
        plug = self.advanced(h)
        runtime = plug.runtime
        if long:
            self.arm(plug, capability=LONG_RESET_MESSAGE.id,
                     warnings=list(runtime.arming.warnings(LONG_RESET_MESSAGE)))
        self.arm(plug, state=state, warnings=list(runtime.arming.warnings(RESET_MESSAGE)))
        self.plugged(plug, h)
        return plug

    def message(self, plug, words=WORDS, thread=T1, ordinal=1):
        key = secrets.token_hex(32)
        rule = plug.runtime.state.add_reset_rule(self.cap, "codex", 300, ordinal, thread_id=thread, words=words,
                                                 record_id=key)
        return rule, key

    def found(self, plug, rule):
        return plug.runtime.state.reset_rule(rule)

    def adopt_then_reset(self):
        """The rule adopted on the window open until RESET, then the clock at RESET + a minute: its reset."""
        self.h.tick()
        self.h.now = RESET + CLOSE_AFTER
        self.h.tick()


class SendTests(MessageCase):
    def test_at_the_reset_it_picked_the_words_go_once_with_the_marker_and_its_words_leave_the_state(self):
        plug = self.armed()
        rule, key = self.message(plug)
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(self.found(plug, rule)["base"], 0)
        self.h.now = RESET + CLOSE_AFTER
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [(T1, WORDS + "\n\n" + ids.short_marker(key))])
        sent = self.found(plug, rule)
        self.assertEqual((sent["state"], sent["words"], sent["record_state"]),
                         (RuleState.READY, None, RecordState.IN_FLIGHT))
        self.assertIsNotNone(sent["sent_at"])
        self.h.tick(advance=5)
        done = self.found(plug, rule)
        self.assertEqual((done["state"], done["reason"], done["record_state"]),
                         (RuleState.DONE, RuleReason.DELIVERED, RecordState.FINISHED))
        self.h.tick(advance=3600)
        self.assertEqual(len(self.h.backend.send_calls), 1, "never twice")
        self.assertEqual(plug.runtime.state.samples(self.cap), {"due": 1, "sent": 1, "delivered": 1})

    def test_the_nth_reset_from_its_adoption(self):
        plug = self.armed()
        rule, _key = self.message(plug, ordinal=2)
        self.adopt_then_reset()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(self.found(plug, rule)["state"], RuleState.COUNTING)
        self.codex.reads = [usage(5, RESET + 5 * 3600)]
        self.h.tick(advance=POLL)                              # the next window, opened by use
        self.assertEqual(self.h.backend.send_calls, [])
        self.h.now = RESET + 5 * 3600 + CLOSE_AFTER
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_only_the_message_goes_when_a_continuation_waits_for_the_same_reset_at_the_very_tick(self):
        """The owner's answer: the person's message, in the continuation's place - even at the tick both fall due."""
        self.h.home.fail_usage(T1, TURN_A)
        self.h.backend.after_accept = "dispatch"
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "waiting_reset")
        plug = self.armed()
        rule, key = self.message(plug)
        self.h.tick()
        self.h.now = RESET + CLOSE_AFTER
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [(T1, WORDS + "\n\n" + ids.short_marker(key))])
        for _ in range(6):
            self.h.tick(advance=60)
        self.assertEqual(len(self.h.backend.send_calls), 1, "the continuation never went")
        self.assertEqual(self.found(plug, rule)["reason"], RuleReason.DELIVERED)
        self.assertIn(self.h.record()["state"], ("superseded_by_user", "superseded"))

    def test_a_continuation_waiting_for_another_reset_is_not_held(self):
        plug = self.armed()
        rule, _key = self.message(plug, ordinal=2)
        self.h.tick()
        code = plug.runtime._code_of(plug.runtime.registry.get(self.cap))
        record = {"thread_id": T1, "category": "usage_limit", "reset_at": RESET, "interruption_id": ac.KEY}
        self.assertIs(code.gate("usage", record, {}), DEFER, "its next reset is not the message's")
        self.assertIs(code.gate("usage", dict(record, thread_id=T2), {}), DEFER)
        self.assertIs(code.gate("schedule", record, {}), DEFER)
        plug.runtime.state.change_rule(rule, ordinal=1)
        self.assertIs(code.gate("usage", record, {}), Alternative.HOLD)
        self.assertIs(code.gate("usage", dict(record, reset_at=RESET + 3 * 3600), {}), DEFER, "another reset")

    def test_one_that_never_started_waits_again_with_its_words(self):
        plug = self.armed()
        rule, _key = self.message(plug)
        self.h.backend.default_outcome = "not_started"
        self.adopt_then_reset()
        waiting = self.found(plug, rule)
        self.assertEqual((waiting["state"], waiting["words"], waiting["record_state"], waiting["reason"]),
                         (RuleState.READY, WORDS, RecordState.WAITING, RuleReason.NOT_STARTED))

    def test_one_in_flight_holds_cores_own_claims_on_the_conversation(self):
        """One in flight in a conversation, across both stores: core's claim there is held (ledger.py)."""
        plug = self.armed()
        self.message(plug)
        self.h.backend.after_accept = "queue"
        self.adopt_then_reset()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.failing(json.dumps({"codexErrorInfo": "internalServerError"}))
        self.h.tick()
        row = self.h.record()
        self.assertEqual(self.h.store.reserve_detailed(row["interruption_id"], self.h.now + 3600, ledger=guard(plug)),
                         (False, "submission_safe", "held"))


class EndTests(MessageCase):
    def test_a_conversation_switched_off_cancels_it_and_its_words(self):
        plug = self.armed()
        rule, _key = self.message(plug)
        self.h.tick()
        self.h.store.set_thread_enabled(T1, False, at=self.h.now)
        self.h.now = RESET + CLOSE_AFTER
        self.h.tick()
        gone = self.found(plug, rule)
        self.assertEqual((gone["state"], gone["reason"], gone["words"]),
                         (RuleState.CANCELLED, RuleReason.CONVERSATION_OFF, None))
        self.assertEqual(self.h.backend.send_calls, [])

    def test_it_expires_unsent_eight_days_on(self):
        plug = self.armed()
        rule, _key = self.message(plug, ordinal=9)
        self.h.tick()
        self.h.now += resetmessage.KEEP_FOR
        self.h.tick()
        self.assertEqual((self.found(plug, rule)["reason"], self.found(plug, rule)["words"]), (RuleReason.EXPIRED, None))

    def test_turned_off_or_watched_it_is_cancelled_with_its_words_and_nothing_is_sent(self):
        for how in ("off", "watched"):
            with self.subTest(how):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.armed(h)
                rule, _key = self.message(plug)
                if how == "off":
                    plug.runtime.arming.disarm(self.cap, actor="dashboard")
                else:
                    self.arm(plug, state="shadow", warnings=list(plug.runtime.arming.warnings(RESET_MESSAGE)))
                h.tick()
                gone = plug.runtime.state.reset_rule(rule)
                self.assertEqual((gone["state"], gone["reason"], gone["words"]),
                                 (RuleState.CANCELLED, RuleReason.TURNED_OFF, None))
                h.now = RESET + CLOSE_AFTER
                h.tick()
                self.assertEqual(h.backend.send_calls, [])

    def test_a_long_message_goes_only_while_longer_reset_messages_is_on(self):
        long_words = "x" * 2001
        for long, sent in ((False, 0), (True, 1)):
            with self.subTest(long=long):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.armed(h, long=long)
                rule, _key = self.message(plug, words=long_words)
                h.tick()
                h.now = RESET + CLOSE_AFTER
                h.tick()
                self.assertEqual(len(h.backend.send_calls), sent)
                if not long:
                    self.assertEqual(plug.runtime.state.reset_rule(rule)["reason"], RuleReason.TURNED_OFF)

    def test_unproven_a_day_after_it_was_sent_it_turns_the_capability_off(self):
        plug = self.armed()
        rule, _key = self.message(plug)
        self.h.backend.after_accept = "queue"
        self.adopt_then_reset()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.h.home.queued(T1)
        for queued in list(self.h.home.queued(T1)):
            self.h.home.remove_queued(queued)                  # it never arrives
        self.h.now += 86400
        self.h.tick()
        self.assertEqual((self.found(plug, rule)["state"], self.found(plug, rule)["reason"]),
                         (RuleState.DONE, RuleReason.UNKNOWN))
        row = plug.runtime.state.arming()[self.cap]
        self.assertEqual((row["state"], row["reason"]), (ArmingState.OFF, OffReason.SUBMISSION_UNKNOWN))
        self.assertEqual(len(self.h.backend.send_calls), 1, "never sent again")


class WordsTests(MessageCase):
    def test_the_words_reach_no_log_journal_export_status_or_mcp_reply(self):
        plug = self.armed()
        self.message(plug)
        self.adopt_then_reset()
        runtime = plug.runtime
        found = {"log": json.dumps(self.h.logs),
                 "journal": json.dumps(runtime.state.journal(capability=self.cap)),
                 "diagnostics": json.dumps(surfaces.diagnostics(runtime)),
                 "status": json.dumps(plug.surface(Surface.STATUS, {})),
                 "mcp": json.dumps(plug.surface(Surface.MCP, {"request": "call", "tool": "list_advanced_capabilities",
                                                              "arguments": {}})),
                 "listing": json.dumps(runtime.arming.listing())}
        for where, text in found.items():
            with self.subTest(where):
                self.assertNotIn("SENTINEL-7f3a", text)
        self.assertEqual(len(self.h.backend.send_calls), 1)


class LedgerTests(MessageCase):
    def test_its_claim_is_paid_for_as_a_send(self):
        plug = self.armed()
        self.message(plug)
        self.adopt_then_reset()
        self.assertEqual([row[0] for row in self.spends(plug)], [self.cap])

    def claim(self, plug, record, phase):
        connection = sqlite3.connect(self.h.store.path, isolation_level=None)
        connection.row_factory = sqlite3.Row                  # as core's own connection reads its rows
        self.addCleanup(connection.close)
        connection.execute("BEGIN IMMEDIATE")
        try:
            return plug.runtime.ledger.record(connection, dict(record, phase=phase), self.h.now)
        finally:
            connection.execute("COMMIT")

    def test_the_ledger_claims_a_due_message_once_launches_it_once_and_holds_one_turned_off(self):
        plug = self.armed()
        state = plug.runtime.state
        rule, key = self.message(plug)
        record = {"record_id": key, "thread_id": T1}
        self.assertIs(self.claim(plug, record, "claim"), Alternative.HOLD, "not due yet")
        state.change_rule(rule, state=RuleState.READY, due_at=self.h.now)
        self.assertIs(self.claim(plug, record, "launch"), Alternative.HOLD, "not claimed yet")
        self.assertIs(self.claim(plug, record, "claim"), DEFER)
        self.assertEqual(state.reset_rule(rule)["record_state"], RecordState.IN_FLIGHT)
        self.assertIs(self.claim(plug, record, "claim"), Alternative.HOLD, "claimed once")
        self.assertIs(self.claim(plug, dict(record, thread_id=T2), "launch"), Alternative.HOLD, "its own conversation")
        self.assertIs(self.claim(plug, record, "launch"), DEFER)
        self.assertIsNotNone(state.reset_rule(rule)["launching_at"])
        self.assertIs(self.claim(plug, record, "launch"), Alternative.HOLD, "launched once")
        other, other_key = self.message(plug, thread=T2)
        state.change_rule(other, state=RuleState.READY, due_at=self.h.now)
        plug.runtime.arming.disarm(self.cap, actor="dashboard")
        self.assertIs(self.claim(plug, {"record_id": other_key, "thread_id": T2}, "claim"), Alternative.HOLD)

    def test_a_record_of_its_own_is_asked_nothing_at_p4_p5_p15_or_p16(self):
        plug = self.armed()
        runtime = plug.runtime
        own = {"record_id": ac.KEY, "thread_id": T1}
        self.assertIs(runtime.ask(resetmessage_point("SENDER"), own, "backend"), "backend")
        for name in ("TEXT", "DELIVERY", "UNLOADED"):
            arguments = (own, "words") if name == "TEXT" else (own,)
            self.assertIs(runtime.ask(resetmessage_point(name), *arguments), DEFER)


def resetmessage_point(name):
    from codex_auto_resume.domain.plug import Point
    return Point[name]


if __name__ == "__main__":
    unittest.main()
