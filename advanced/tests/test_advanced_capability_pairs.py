"""Two capabilities on at once, where one keeps the other from working (the v0.6.17 audit of capability pairs, the
owner's question after issue #42: "could other advanced capabilities overlap the way #42 did?").

Each test arms two shipped capabilities - their shipped definitions and statements - against core's own engine, store
and simulated Codex home (takingcase.py, test_advanced_goal.py), or against the runtime alone (advancedcase.py), and
asserts what a person who turned both on would expect. Each fails today, so each is marked expectedFailure with the
finding it shows; the fix that makes one pass removes its marker (an unexpected success fails the run).

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from takingcase import TakingCase  # noqa: E402
from test_advanced_goal import GoalCase  # noqa: E402
from test_advanced_usage import Session, UsageCase, reply  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402
from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume_advanced import runtime, statement  # noqa: E402
from codex_auto_resume_advanced.codex.turns import Turns  # noqa: E402
from codex_auto_resume_advanced.engine import foropen  # noqa: E402
from codex_auto_resume_advanced.registry import (COMPACT_CONTINUE, GOAL_CONTINUATION, HEADLESS_RUN,  # noqa: E402
                                                 MARKER_FREE, OTHER_SESSIONS, PARALLEL_DISPATCH, QUEUE_FOR_OPEN,
                                                 RESET_CREDIT, SILENT_CONTINUATION, USAGE_METER, USAGE_PAUSE)
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingWarning, JournalCode, Measurement,  # noqa: E402
                                                   SpendOutcome, Verdict)
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import DEFER  # noqa: E402
from codex_auto_resume_advanced.codex import headless  # noqa: E402
from codex_auto_resume_advanced.engine.markerfree import MarkerFreeContinuation  # noqa: E402
from advancedcase import ENGINE  # noqa: E402
from sessionsim import holding_sessions  # noqa: E402
from test_advanced_parallel import T1 as P1, T2 as P2, ParallelCase  # noqa: E402
from test_engine import T1  # noqa: E402
from test_route_unheld import UnheldCase  # noqa: E402
from test_silent_core import Silent  # noqa: E402

CONTEXT_FULL = json.dumps({"codexErrorInfo": "contextWindowExceeded"})


class CompactBesideQueueForOpenTests(TakingCase):
    """Finding P-5: queue_for_open answers QUEUE_FOR_OPEN at P16 for a record of any kind (engine/foropen.py, no
    category check, though its definition says usage-limited), and core asks P3 thread_available only where P16 named
    no route (core's engine/dispatch.py) - so compact_continue's hold until the person's /compact is never asked, and
    core's continuation is queued, uncompacted, into a conversation whose context window is full."""
    DEFINITION = COMPACT_CONTINUE
    BESIDE = (QUEUE_FOR_OPEN,)

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def armed(self, h=None, state="armed"):
        plug = super().armed(h, state=state)
        plug.runtime._code_of(self.DEFINITION)._turns = Turns((h or self.h).home.root)
        return plug

    # Fixed in v0.6.17 (#47): queue_for_open takes up usage-limited records only, so compact's hold is asked again.
    def test_a_full_context_window_is_not_queued_for_open_uncompacted(self):
        plug = self.armed()
        self.failing(CONTEXT_FULL)
        self.h.tick()
        (row,) = self.h.records()
        self.assertEqual(row["category"], "terminal_invalid")
        self.h.backend.loaded_map[T1] = "notLoaded"          # the app runs and does not hold the conversation
        self.h.backend.after_accept = "queue"
        for _ in range(30):
            self.h.tick(advance=60)
        self.assertEqual(self.h.backend.send_calls, [], "held until a compaction turn is the latest")
        self.assertEqual(self.h.record()["last_error"], "notLoaded", "it waits for the app, as A11 says")
        self.assertIsNone(plug.runtime.state.override(row["interruption_id"], QUEUE_FOR_OPEN.id), "never queued")
        self.h.backend.loaded_map[T1] = "loaded"             # opened: compact_continue's hold is asked, and holds
        for _ in range(5):
            self.h.tick(advance=60)
        self.assertEqual(self.h.backend.send_calls, [], "held in the app until the person compacts")
        self.assertIn((JournalCode.ACTED, Point.GATES, Alternative.HOLD), self.journal(plug))

    def test_a_usage_limited_conversation_is_still_queued_for_open_beside_it(self):
        plug = self.armed()
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.backend.after_accept = "queue"
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "queued", self.h.record()["last_error"])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual([spend[0] for spend in self.spends(plug)], [QUEUE_FOR_OPEN.id])


class GoalBesideQueueForOpenTests(GoalCase):
    """Finding P-4: goal_continuation sets a conversation's goal active at P16 and says the goal and the standard
    continuation never both run (its P3 thread_available hold). Once the goal reads active its P16 answers DEFER, the
    next armed answer - queue_for_open's - is taken, and core never asks P3 thread_available for a P16 answer: the
    standard continuation is queued for open beside the goal Codex carries on when the app opens the conversation."""
    registry = (GOAL_CONTINUATION, QUEUE_FOR_OPEN)
    # A measurement neither capability rests on, standing in for MQG where the vocabulary does not have it yet.
    STAND_IN = Measurement.MN

    def both(self):
        plug, fake = self.armed()
        definition = plug.runtime.registry.get(QUEUE_FOR_OPEN.id)
        self.arm(plug, capability=QUEUE_FOR_OPEN.id,
                 warnings=[str(word) for word in plug.runtime.arming.warnings(definition)])
        plug.runtime._code_of(QUEUE_FOR_OPEN)._home = self.h.home.root      # the harness's goals, never this PC's
        self.h.backend.after_accept = "queue"
        self.h.tick()
        self.assertEqual(len(fake.sets()), 1, "the goal set active")
        for _ in range(25):
            self.h.tick(advance=61)
        self.assertEqual(self.status(), "active")
        return plug, fake

    def qfo_journal(self, plug):
        return [line["code"] for line in plug.runtime.state.journal(capability=QUEUE_FOR_OPEN.id)]

    def assert_one_continuation(self, plug, code):
        self.assertEqual(self.h.backend.send_calls, [], "the standard continuation is not queued beside the goal")
        self.assertEqual([spend[0] for spend in self.spends(plug)], [GOAL_CONTINUATION.id], "the goal carried it")
        self.assertEqual(self.qfo_journal(plug).count(code), 1, "why it stood aside, once")

    def assert_both(self, plug):
        self.assertEqual(len(self.h.backend.send_calls), 1, "queued for opening beside the goal: MQG ran it once")
        self.assertEqual(self.h.record()["state"], "queued")
        self.assertEqual(sorted(spend[0] for spend in self.spends(plug)), [GOAL_CONTINUATION.id, QUEUE_FOR_OPEN.id])
        self.assertNotIn("qfo.goal_unmeasured", self.qfo_journal(plug))

    # Fixed in v0.6.17 (#47): while MQG has no pass on this Codex, queue_for_open leaves an active goal to carry it.
    def test_a_goal_set_active_is_not_also_queued_for_open(self):
        plug, _fake = self.both()
        self.assert_one_continuation(plug, "qfo.goal_unmeasured")

    def test_measured_as_two_turns_it_still_stands_aside_and_says_so(self):
        self.measured[self.STAND_IN] = (Verdict.FAIL, ENGINE)
        with patch.object(foropen, "MQG", self.STAND_IN):
            plug, _fake = self.both()
        self.assert_one_continuation(plug, "qfo.goal_two_turns")

    def test_measured_as_one_turn_both_apply(self):
        self.measured[self.STAND_IN] = (Verdict.PASS, ENGINE)
        with patch.object(foropen, "MQG", self.STAND_IN):
            plug, _fake = self.both()
        self.assert_both(plug)

    def test_one_turn_on_another_codex_is_not_measured_here(self):
        self.measured[self.STAND_IN] = (Verdict.PASS, "codex-cli 0.1.0")
        with patch.object(foropen, "MQG", self.STAND_IN):
            plug, _fake = self.both()
        self.assert_one_continuation(plug, "qfo.goal_unmeasured")

    @unittest.skipUnless(hasattr(Measurement, "MQG"), "Measurement.MQG arrives with v0617-queue")
    def test_mqg_passed_by_its_own_id_and_both_apply(self):
        self.assertIs(foropen.MQG, Measurement.MQG)
        self.measured[Measurement.MQG] = (Verdict.PASS, ENGINE)
        plug, _fake = self.both()
        self.assert_both(plug)


class GoalBesideOtherSessionsTests(GoalCase):
    """Finding P-3: goal_continuation's channel at P5 (M2b passed, the goal paused by the usage limit) is a send of a
    conversation the app holds; for one another Codex session holds, other_sessions' TO_SESSION goes only core's
    ordinary way (core's engine/foropen._not_for_open), so a channel named there left the record waiting "held by
    another session" for ever. Settled by the runtime's rule for answers core cannot carry together (runtime.CONFLICTS,
    v0.6.17 #42, branch v0617-queue): the goal's channel stands aside for that send, `overruled` in its journal - goal.py
    is unchanged. Until that rule is merged the session test is skipped; it fails on a runtime without it."""
    registry = (GOAL_CONTINUATION, OTHER_SESSIONS)

    def fresh(self, **kwargs):
        # Who holds a conversation "elsewhere", as the real Backend keeps it (tests/sessionsim.py).
        made = super().fresh(**kwargs)
        holding_sessions(made.backend)
        return made

    def both(self, loaded):
        self.measured[Measurement.M2B] = (Verdict.PASS, ENGINE)
        plug, fake = self.armed(loaded=loaded)
        definition = plug.runtime.registry.get(OTHER_SESSIONS.id)
        self.arm(plug, capability=OTHER_SESSIONS.id,
                 warnings=[str(word) for word in plug.runtime.arming.warnings(definition)])
        return plug, fake

    @unittest.skipUnless(hasattr(runtime, "CONFLICTS"), "runtime.CONFLICTS (v0617-queue, #42) settles P-3: not merged")
    def test_a_conversation_another_session_holds_is_sent_for_it_to_take(self):
        plug, fake = self.both(loaded=False)
        self.h.backend.loaded_map[T1] = "elsewhere"          # a terminal's or VS Code's session holds it
        self.h.backend.after_accept = "queue"
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "queued", row["last_error"])
        self.assertEqual(len(self.h.backend.send_calls), 1, "core's own send, for that session to take")
        self.assertEqual(machine.decode_gates(row["gate_eval"])["thread_available"], (machine.PASS, machine.SESSION))
        self.assertEqual(fake.sets(), [], "the goal is not set for a conversation the app does not hold")
        self.assertEqual(fake.adds(), [])
        self.assertEqual(self.status(), "usage_limited")
        self.assertEqual([spend[0] for spend in self.spends(plug)], [OTHER_SESSIONS.id])
        self.assertIn((JournalCode.OVERRULED, Point.SENDER, OTHER_SESSIONS.id), self.journal(plug))

    def test_a_conversation_the_app_holds_still_gets_the_goal_s_channel(self):
        plug, fake = self.both(loaded=True)
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(fake.methods(), ["thread/goal/set", "thread/queue/add"])
        self.assertEqual(self.status(), "active")


class SilentBesideMarkerFreeTests(ac.AdvancedCase):
    """Finding P-6: marker_free_continuation answers CLIENT_ID at P15 for every record, before silent_continuation in
    the registry's order, and the first armed answer wins - so a headless route's P15 (core's engine/routes._silent),
    which takes SILENT alone, never gets it: Continue with no words never acts while the marker-free one is on."""

    def both(self):
        self.compat = ac.view(capability="recovery_turn_tracking")
        runtime = self.runtime(MARKER_FREE, SILENT_CONTINUATION)
        runtime.arming.catalogs = statement.CATALOGS
        for definition in (MARKER_FREE, SILENT_CONTINUATION):
            result = runtime.arming.arm(definition.id, state="armed", revision=definition.revision,
                                        generation=runtime.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                        warnings=[str(word) for word in runtime.arming.warnings(definition)],
                                        actor=Actor.DASHBOARD)
            self.assertTrue(result["done"], result)
        runtime.states(fresh=True)
        return runtime

    def marker_free_lines(self, runtime):
        return [(line["code"], line["point"]) for line in runtime.state.journal(capability=MARKER_FREE.id)]

    # Fixed in v0.6.17 (#47): a route's P15 says `route` (core's routes._silent), where only SILENT is taken.
    def test_a_route_is_answered_silent_with_marker_free_on(self):
        runtime = self.both()
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit", "route": True}
        self.assertIs(runtime.ask(Point.DELIVERY, record), Alternative.SILENT)
        self.assertNotIn((JournalCode.ACTED, Point.DELIVERY), self.marker_free_lines(runtime),
                         "marker-free never said it acted on a route it cannot serve")

    def test_a_channel_send_that_carries_words_still_goes_marker_free(self):
        runtime = self.both()
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit"}
        self.assertIs(runtime.ask(Point.DELIVERY, record), Alternative.CLIENT_ID)
        self.assertIn((JournalCode.ACTED, Point.DELIVERY), self.marker_free_lines(runtime))


class _RouteOnly:
    """headless_run's code in a test: P16 names the test's route where the app is closed, and no errand."""

    def __init__(self, route):
        self.route = route

    def unloaded(self, record):
        return self.route if record.get("app") is False else DEFER

    def tick(self, view):
        return DEFER


class _Adds:
    """marker-free continuation's app-server session in a test: thread/queue/add puts the item into the harness's
    Codex queue under the client id it came with, as Codex's own does, and says which thread it was made on."""

    def __init__(self, case):
        self.case = case

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def call(self, method, params):
        self.case.adds.append((params["threadId"], params.get("clientUserMessageId"), params["input"][0]["text"],
                               threading.current_thread() is threading.main_thread()))
        return {"queuedSubmissionId": self.case.h.home.enqueue(params["threadId"], params["input"][0]["text"],
                                                               client_id=params.get("clientUserMessageId"))}


def _compat(*capabilities):
    return {"status": "ok", "engine": {"found": True, "version": ENGINE},
            "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"} for name in capabilities}}


class SilentRouteBesideMarkerFreeTests(TakingCase, UnheldCase):
    """P-6 against core's own engine: a route that takes words (headless_run's), with silent_continuation and
    marker_free_continuation both on - the route is handed no words and no marker, the turn proven by the client id
    core derives; and a conversation the app holds still goes marker-free through the channel, with its words."""
    DEFINITION = SILENT_CONTINUATION
    BESIDE = (HEADLESS_RUN, MARKER_FREE)

    def setUp(self):
        super().setUp()
        self.compat = _compat(*{definition.compat for definition in (*self.BESIDE, self.DEFINITION)})
        self.addCleanup(setattr, headless, "EMPTY_REFUSED", headless.EMPTY_REFUSED)
        headless.EMPTY_REFUSED = False
        self.adds = []
        patcher = patch.object(MarkerFreeContinuation, "_session", lambda _self: _Adds(self))
        patcher.start()
        self.addCleanup(patcher.stop)

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def all_on(self):
        plug = self.armed()
        route = Silent(self.h)
        plug.runtime._code[HEADLESS_RUN.id] = _RouteOnly(route)
        return plug, route

    def lines(self, plug, capability):
        return [(line["code"], line["point"], line["answer"]) for line in plug.runtime.state.journal(capability=capability)]

    def test_a_silent_route_goes_with_no_words_and_no_marker(self):
        """Fails with the fix reverted: marker-free's CLIENT_ID wins the route's P15, and the route is handed the
        words and the marker."""
        plug, route = self.all_on()
        self.closed()
        self.h.tick()
        (call,) = route.calls
        row = self.h.record()
        derived = ids.continuation_client_id(row["interruption_id"])
        self.assertEqual(call["words"], "", "no words, so no marker and no id carried as words")
        self.assertEqual(call["client_id"], derived)
        self.assertEqual(row["recovery_client_id"], derived)
        self.assertEqual(row["state"], "turn_started", "proven by the turn the route returned")
        self.assertEqual(self.adds, [], "nothing went through marker-free's channel")
        self.assertIn((JournalCode.ACTED, Point.DELIVERY, Alternative.SILENT), self.lines(plug, self.cap))
        self.assertNotIn(JournalCode.ACTED, [line[0] for line in self.lines(plug, MARKER_FREE.id)])
        self.assertEqual(sorted(spend[0] for spend in self.spends(plug)), [HEADLESS_RUN.id, self.cap])

    def test_a_conversation_the_app_holds_still_goes_marker_free_with_its_words(self):
        plug, route = self.all_on()
        self.ready_after_reset()
        self.h.tick()
        self.assertEqual(route.calls, [])
        self.assert_no_send()
        ((thread, client, words, _main),) = self.adds
        row = self.h.record()
        self.assertEqual((thread, client), (T1, ids.continuation_client_id(row["interruption_id"])))
        self.assertTrue(words.strip())
        self.assertNotIn(ids.MARKER_PREFIX, words)
        self.assertIn((JournalCode.ACTED, Point.DELIVERY, Alternative.CLIENT_ID), self.lines(plug, MARKER_FREE.id))
        self.assertNotIn(JournalCode.ACTED, [line[0] for line in self.lines(plug, self.cap)])


class ParallelBesideMarkerFreeTests(ParallelCase):
    """Finding P-7: core pooled only its own backend's sends, carrying the marker (engine/delivery._pooled), and
    marker_free_continuation makes every send a channel send - so parallel_dispatch never pooled one while it was on,
    and the journal still said it acted. MQP (2026-10-19, codex-cli 0.163.0-alpha.10.2) measured several
    thread/queue/add calls at once, each in a session of its own under its own client id: each accepted, each only in
    its own conversation. Where it passed the channel's sends are pooled and paid as core's own; elsewhere they go one
    at a time and the journal says why."""
    DEFINITION = PARALLEL_DISPATCH
    BESIDE = (MARKER_FREE,)

    def setUp(self):
        super().setUp()
        self.compat = _compat(PARALLEL_DISPATCH.compat, MARKER_FREE.compat)
        self.measured = {Measurement.M7: (Verdict.PASS, ENGINE)}
        self.adds = []
        patcher = patch.object(MarkerFreeContinuation, "_session", lambda _self: _Adds(self))
        patcher.start()
        self.addCleanup(patcher.stop)

    def both(self, mqp=None):
        if mqp is not None:
            self.measured[Measurement.MQP] = (mqp, ENGINE)
        plug = self.armed()
        self.due()
        self.h.tick()
        return plug

    def parallel_lines(self, plug):
        return [(line["code"], line["point"], line["answer"], line["reason"])
                for line in plug.runtime.state.journal(capability=self.cap)]

    def paid(self, plug, capability):
        return sorted(thread for cap, thread, _key in self.spends(plug) if cap == capability)

    def test_mqp_passed_two_conversations_channel_sends_are_pooled_and_each_paid_once(self):
        """Fails with the fix reverted: both adds made one after another on the tick thread, parallel paid nothing."""
        plug = self.both(Verdict.PASS)
        self.assert_no_send()
        self.assertEqual(sorted(thread for thread, _client, _words, _main in self.adds), [P1, P2], "each sent once")
        self.assertFalse(any(main for _thread, _client, _words, main in self.adds), "each waited on a worker")
        self.assertEqual(len({client for _thread, client, _words, _main in self.adds}), 2, "each under its own id")
        self.assertEqual(self.paid(plug, self.cap), [P1, P2], "parallel paid once for each pooled claim")
        self.assertEqual(self.paid(plug, MARKER_FREE.id), [P1, P2])
        lines = self.parallel_lines(plug)
        self.assertEqual([line[:3] for line in lines].count((JournalCode.ACTED, Point.CONCURRENCY, Point.CONCURRENCY)),
                         2, "acted, once for each record it pooled")
        self.assertNotIn(JournalCode.OVERRULED, [line[0] for line in lines])
        self.assertEqual({row["state"] for row in self.h.store.records_in({"queued"})}, {"queued"})
        self.assertEqual(len(self.h.store.records_in({"queued"})), 2)

    def assert_one_at_a_time(self, plug, reason):
        self.assert_no_send()
        self.assertEqual(sorted(thread for thread, _client, _words, _main in self.adds), [P1, P2])
        self.assertTrue(all(main for _thread, _client, _words, main in self.adds), "inline, one at a time")
        self.assertEqual(self.paid(plug, self.cap), [], "nothing pooled, nothing paid")
        lines = self.parallel_lines(plug)
        self.assertNotIn(JournalCode.ACTED, [line[0] for line in lines], "never 'acted' for a tick it pooled nothing")
        self.assertIn((JournalCode.OVERRULED, Point.CONCURRENCY, MARKER_FREE.id, reason), lines)

    def test_mqp_unmeasured_one_at_a_time_and_the_journal_says_why(self):
        """Fails with the fix reverted: the journal said parallel acted, and nothing said why it pooled nothing."""
        self.assert_one_at_a_time(self.both(), ArmingWarning.UNMEASURED)

    def test_mqp_failed_one_at_a_time_and_the_journal_says_why(self):
        self.assert_one_at_a_time(self.both(Verdict.FAIL), ArmingWarning.MEASUREMENT_FAILED)

    def test_mqp_passed_on_another_codex_is_not_measured_here(self):
        self.measured[Measurement.MQP] = (Verdict.PASS, "another Codex")
        self.assert_one_at_a_time(self.both(), ArmingWarning.UNMEASURED)


class PauseBesideResetCreditTests(UsageCase):
    """Finding P-8: usage_pause holds every core record (P3 HOLD) until the meter's next reading shows the window reset
    (engine/usage.py, _mark and holding), and the meter reads only while the Codex app runs, every Poll minutes (15 by
    default). reset_credit's spend resets the window and answers EARLY for fifteen minutes (engine/credits.py): with no
    reading in them, every one of those minutes is held, and the credit spent buys no early look."""

    def setUp(self):
        ac.AdvancedCase.setUp(self)
        self.compat = {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
                       "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                        for name in ("usage_probe", "exact_thread_recovery")}}
        self.rt = self.runtime(RESET_CREDIT, USAGE_METER, USAGE_PAUSE)
        self.rt.arming.catalogs = statement.CATALOGS
        self.answer, self.calls, self.app = reply(), [], True
        code = self.rt._code_of(USAGE_METER)
        code._session = lambda: Session(self.answer, self.calls)
        code._app_running = lambda: self.app

    # Fixed in v0.6.17 (#44): a reset spend of the held window lets the pause go (engine/usage.py).
    def test_a_credit_spent_is_not_held_for_its_whole_early_window(self):
        self.on("usage_pause")
        self.on("reset_credit")
        self.answer = reply(five=100)
        self.look()
        self.look()                                   # the pause's own tick marks the window
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit",
                  "state": "waiting_reset"}
        self.assertIs(self.rt.ask(Point.GATES, "submission_safe", record, {}), Alternative.HOLD)
        # What reset_credit's look writes when Codex resets the window for its credit.
        spend = self.rt.state.add_credit_spend(1, "codex", 300, 0, str(uuid.uuid4()), at=self.now)
        self.assertTrue(self.rt.state.finish_credit_spend(spend, SpendOutcome.RESET, at=self.now))
        self.app = False                              # the Codex app closed: the meter reads nothing
        self.assertIs(self.rt.ask(Point.SCHEDULE, record, self.now + 3600), Alternative.EARLY)
        held = []
        for _ in range(15):
            self.now += 60
            self.look()
            held.append(self.rt.ask(Point.GATES, "submission_safe", record, {}) is Alternative.HOLD)
        self.assertFalse(all(held), "some minute of the credit's early window is not held")


class AnalyticsBesideMeterAndPauseTests(UsageCase):
    """v0.6.20, usage_analytics (observe-only): on beside the meter it requires and the stop near a limit, each still
    does all it did alone - the meter keeps its reading and warns once, the stop holds a record at its percentage -
    and the analytics keep that same reading as their samples. Nothing of theirs is an answer at any point."""

    def setUp(self):
        ac.AdvancedCase.setUp(self)
        from codex_auto_resume_advanced.registry import USAGE_ANALYTICS
        self.compat = {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
                       "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                        for name in ("usage_probe", "exact_thread_recovery")}}
        self.rt = self.runtime(USAGE_METER, USAGE_PAUSE, USAGE_ANALYTICS)
        self.rt.arming.catalogs = statement.CATALOGS
        self.answer, self.calls, self.app = reply(), [], True
        code = self.rt._code_of(USAGE_METER)
        code._session = lambda: Session(self.answer, self.calls)
        code._app_running = lambda: self.app
        self.rt._code_of(USAGE_ANALYTICS)._homes = lambda: []

    def test_both_apply_to_the_same_reading(self):
        self.on("usage_pause")
        self.on("usage_analytics")
        self.answer = reply(five=99)
        self.look()
        self.look()                                   # the stop's own tick marks the window
        rows = self.rt.state.meter()
        self.assertEqual(rows[("codex", 300)]["used_percent"], 99.0)
        self.assertEqual(rows[("codex", 300)]["warned_reset_at"], rows[("codex", 300)]["reset_at"])
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit",
                  "state": "waiting_reset"}
        self.assertIs(self.rt.ask(Point.GATES, "submission_safe", record, {}), Alternative.HOLD)
        samples = self.rt.state.usage_samples()
        self.assertIn((300, 99.0), [(row["minutes"], row["used_percent"]) for row in samples])


# v0.6.19 W4 (plans/v0619-design/D-watcher-ops.md): the watcher operations beside what they meet.
class CrashRestartBesideStartWithCodexTests(ac.AdvancedCase):
    """crash_restart and start_with_codex: COMPOSE. Start with Codex starts this installation's launcher through WMI,
    outside Codex's job (P9); the launcher it started asks P13, and crash_restart supervises the watcher from there - one
    answers at P9, the other at P13, about one launcher, and neither stands aside."""

    def setUp(self):
        super().setUp()
        from codex_auto_resume_advanced.registry import CRASH_RESTART, START_WITH_CODEX
        self.compat = ac.view(capability="engine_present")
        self.rt = self.runtime(START_WITH_CODEX, CRASH_RESTART)
        self.rt.arming.catalogs = statement.CATALOGS
        code = self.rt._code_of(CRASH_RESTART)
        code._stop = type("Stop", (), {"hold": lambda self: True, "signalled": lambda self: False,
                                       "wait": lambda self, seconds: False})()
        code._notify = lambda paths: None

    def on(self, capability):
        definition = self.rt.registry.get(capability)
        result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)], actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def test_both_on_the_launcher_started_with_codex_supervises_the_watcher(self):
        from codex_auto_resume_advanced.control.codexstart import StartWithCodex
        self.on("start_with_codex")
        self.on("crash_restart")
        self.assertIsInstance(self.rt.start_route({"in_job": True, "kill_on_close": True, "breakaway_ok": False,
                                                   "silent_breakaway_ok": False}), StartWithCodex)
        self.assertIs(self.rt.supervise({"phase": "start"}), Alternative.SUPERVISE)
        self.assertIs(self.rt.supervise({"phase": "ended", "exit_code": 1, "clean": False}), Alternative.RESTART)
        overruled = [line for line in self.rt.state.journal() if line["code"] == JournalCode.OVERRULED]
        self.assertEqual(overruled, [])


class WakeBesideTheResetCapabilitiesTests(ac.AdvancedCase):
    """wake_for_reset beside reset_credit, reset_message and usage_pause: COMPOSE. Each keeps its own due time - a
    credit's or a message's rule (`due_at`), the forced stop's held window (the meter's `paused_reset_at`) - and core
    keeps its waiting usage-limit records'; the wake timer is set for the earliest of them all, read through the same
    view, so whichever acts first finds the PC awake, and none of them is changed by it."""

    class Timer:
        def __init__(self):
            self.due = None

        def allowed(self):
            return True

        def set(self, when):
            self.due = when
            return True

        def cancel(self):
            found, self.due = self.due is not None, None
            return found

    class View:
        def __init__(self, rows):
            self.rows = rows

        def records_in(self, states):
            return [row for row in self.rows if row["state"] in states]

    def setUp(self):
        super().setUp()
        from codex_auto_resume_advanced.registry import WAKE_FOR_RESET
        self.compat = {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
                       "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                        for name in ("engine_present", "usage_probe")}}
        self.rt = self.runtime(WAKE_FOR_RESET, RESET_CREDIT)
        self.rt.arming.catalogs = statement.CATALOGS
        self.code = self.rt._code_of(WAKE_FOR_RESET)
        self.code._timer = self.timer = self.Timer()
        self.code._start = lambda target: None

    def on(self, capability):
        definition = self.rt.registry.get(capability)
        result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)], actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def errand(self, rows):
        self.code.tick(self.View(rows)).run(lambda: None)

    def test_the_timer_is_set_for_the_earliest_due_time_of_them_all(self):
        self.on("wake_for_reset")
        self.on("reset_credit")
        core = {"state": "waiting_reset", "category": "usage_limit", "next_check_at": self.now + 3 * 3600}
        self.errand([core])
        self.assertEqual(self.timer.due, self.now + 3 * 3600 - 120)
        rule = self.rt.state.add_reset_rule("reset_credit", "codex", 300, 1)
        self.assertTrue(self.rt.state.change_rule(rule, due_at=self.now + 2 * 3600))
        self.errand([core])
        self.assertEqual(self.timer.due, self.now + 2 * 3600 - 120, "the credit's rule comes first")
        self.rt.state.save_meter([{"bucket": "codex", "window_minutes": 10080, "used_percent": 97.0,
                                   "reset_at": int(self.now + 3600)}])
        self.assertTrue(self.rt.state.mark_meter("codex", 10080, paused_reset_at=int(self.now + 3600)))
        self.errand([core])
        self.assertEqual(self.timer.due, int(self.now + 3600) - 120, "the forced stop's held window comes first")
        self.assertEqual([row["due_at"] for row in self.rt.state.reset_rules()], [self.now + 2 * 3600],
                         "the credit's rule is unchanged")


# ------------------------------------------------------------------------------ the in-app chat (v0.6.19)
from test_advanced_chat import ChatCase, FakeSession  # noqa: E402
from codex_auto_resume_advanced.engine import chat as chat_engine  # noqa: E402
from codex_auto_resume_advanced.ledger import held_by_records  # noqa: E402
from codex_auto_resume_advanced.state.records import own_paced  # noqa: E402
from codex_auto_resume_advanced.registry import (CODEX_CHAT, CRASH_RESTART, KEEP_GOING,  # noqa: E402
                                                 LONG_RESET_MESSAGE, PROMPT_QUEUE, RESET_MESSAGE, SEND_NOW,
                                                 USAGE_WRAP_UP, WAKE_FOR_RESET)
from codex_auto_resume_advanced.vocabulary import BridgeCommand, ChatReason, ChatState, Refusal  # noqa: E402
from codex_auto_resume_advanced import surfaces  # noqa: E402


def _core_connection(test, plug, with_queue=True):
    """A connection of core's shape - an interruptions table, the edition's file attached - as core's claim has."""
    import sqlite3
    connection = sqlite3.connect(":memory:", isolation_level=None)
    test.addCleanup(connection.close)
    connection.execute("CREATE TABLE interruptions (thread_id TEXT, state TEXT, queue_id TEXT, submitted_at REAL, "
                       "last_claim_at REAL, attempt_count INTEGER)")
    test.assertTrue(plug.runtime.state.attach(connection))
    return connection


class _ChatPair(ChatCase):
    """The chat beside one other capability: both shipped definitions armed, against core's own engine and store."""

    def chat_record(self, plug, key):
        return chat_engine.handed(plug.runtime.state.chat_by_record(key))

    def claim(self, plug, key, now):
        """`key` claimed as core's claim claims a record of the edition's: True where it may go now."""
        connection = _core_connection(self, plug)
        connection.execute("BEGIN IMMEDIATE")
        try:
            return plug.runtime.state.claim_record(connection, key, now)
        finally:
            connection.execute("COMMIT")

    def delivered_chat(self, plug):
        """A chat message sent and delivered, then a minute on: its claim is a minute old."""
        key = self.waiting(plug)
        self.h.tick()
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.assertEqual(plug.runtime.state.chat_by_record(key)["reason"], ChatReason.DELIVERED)
        self.h.now += 60
        return key


class ChatBesidePromptQueueTests(_ChatPair):
    """codex_chat and prompt_queue: COMPOSE. Two kinds of a person's own message for one conversation: one in flight
    at a time across both (whichever is claimed first goes, the other waits for it), each sent once, and neither
    paces the other - a queued prompt keeps core's fifteen minutes and five a day among the prompts and recoveries, and
    a chat message is counted in none of them (state/records.own_paced; fixed here: it was)."""
    BESIDE = (PROMPT_QUEUE,)

    def add_prompt(self, plug):
        argument = dict(thread_id=T1, words="Then run the linter too.", trigger="after_turn",
                        generation=plug.runtime.state.meta()["generation"])
        result = surfaces.bridge(plug.runtime, "advanced-prompt-add", argument)
        self.assertTrue(result["done"], result)

    def test_a_prompt_after_a_chat_message_is_not_held_fifteen_minutes_by_it(self):
        """Fails with own_paced reverted: the prompt would wait core's fifteen minutes after the chat's claim."""
        plug = self.armed()
        self.delivered_chat(plug)
        self.add_prompt(plug)
        self.h.tick(advance=30)
        self.assertEqual(len(self.h.backend.send_calls), 1, "the prompt went at once")

    def test_both_waiting_one_goes_at_a_time_and_each_once(self):
        plug = self.armed()
        self.waiting(plug)
        self.add_prompt(plug)
        self.h.tick()
        self.assertEqual(len(self.calls) + len(self.h.backend.send_calls), 1, "one in flight in the conversation")
        for _ in range(2):
            self.h.home.dispatch(T1)
            for _ in range(4):
                self.h.tick(advance=30)
        self.assertEqual((len(self.calls), len(self.h.backend.send_calls)), (1, 1), "both went, each once")


class ChatBesideMarkerFreeTests(_ChatPair):
    """codex_chat and marker_free_continuation: COMPOSE. Both carry words with no marker through thread/queue/add; a
    chat message goes through the chat's own channel under the id core derives from its record (P5 and P15 for the
    edition's own records are the chat's alone, runtime._own_record_answer), and marker-free keeps every recovery."""
    BESIDE = (MARKER_FREE,)

    def test_a_chat_message_goes_through_the_chat_s_channel_under_its_own_id(self):
        plug = self.armed()
        other = []
        plug.runtime._code_of(MARKER_FREE)._open = lambda: FakeSession(self.h, other)
        key = self.waiting(plug)
        self.h.tick()
        self.assertEqual(other, [], "marker-free's channel carried nothing of the chat's")
        ((method, params),) = self.calls
        self.assertEqual(params["clientUserMessageId"], ids.continuation_client_id(key))
        recovery = {"interruption_id": "ab" * 32, "thread_id": T1}
        self.assertIs(plug.runtime.ask(Point.SENDER, recovery, object()), plug.runtime._code_of(MARKER_FREE))


class ChatBesideSilentTests(_ChatPair):
    """codex_chat and silent_continuation: COMPOSE. SILENT is a route's answer at P15; a chat message is asked P15
    as the chat's own record and is CLIENT_ID - its words always go, with no marker."""
    BESIDE = (SILENT_CONTINUATION,)

    def test_a_chat_message_keeps_its_words(self):
        plug = self.armed()
        key = self.waiting(plug, words="Explain the failing test.")
        self.assertIs(plug.runtime.ask(Point.DELIVERY, self.chat_record(plug, key)), Alternative.CLIENT_ID)
        self.h.tick()
        self.assertEqual(self.calls[0][1]["input"][0]["text"], "Explain the failing test.")


class ChatBesideQueueForOpenTests(_ChatPair):
    """codex_chat and queue_for_open: COMPOSE. Both wait for the app to hold the conversation: queue_for_open queues a
    usage-limited recovery for the moment it is opened (P16, never asked for the edition's own records), and a chat
    message waits - never queued for opening - and goes once the app holds the conversation."""
    BESIDE = (QUEUE_FOR_OPEN,)

    def test_a_chat_message_waits_for_the_app_and_is_never_queued_for_opening(self):
        plug = self.armed()
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.waiting(plug)
        for _ in range(5):
            self.h.tick(advance=60)
        self.assertEqual((self.calls, self.h.backend.send_calls), ([], []))
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=60)
        self.assertEqual(len(self.calls), 1)


class ChatBesideGoalTests(_ChatPair):
    """codex_chat and goal_continuation: COMPOSE. The goal's route, hold and channel (P16, P3, P5) are a recovery's;
    a chat message is the person's own and goes through the chat's channel beside an active goal, as a message typed
    in Codex would."""
    BESIDE = (GOAL_CONTINUATION,)

    def test_a_chat_message_goes_through_the_chat_s_channel_with_the_goal_on(self):
        plug = self.armed()
        key = self.waiting(plug)
        self.assertIs(plug.runtime.ask(Point.SENDER, self.chat_record(plug, key), object()),
                      plug.runtime._code_of(CODEX_CHAT).channel)
        self.h.tick()
        self.assertEqual(len(self.calls), 1)


class ChatBesideRecordsTests(_ChatPair):
    """codex_chat beside keep_going, usage_wrap_up, reset_message (with long_reset_message) and send_now: COMPOSE.
    One in flight in a conversation across every record and core's rows - a chat message in flight holds the others,
    and theirs hold it - and a chat message's claim counts in nobody else's five a day or fifteen minutes (fixed
    here): a continuation kept going, a wrap-up, a reset message or a recovery sent now goes a minute after a chat
    message as it would with the chat off."""
    BESIDE = (KEEP_GOING, USAGE_METER, USAGE_WRAP_UP, RESET_MESSAGE, LONG_RESET_MESSAGE, SEND_NOW)

    def test_another_record_is_not_paced_by_a_chat_message(self):
        """Fails with own_paced reverted: each would be held fifteen minutes by the chat's claim."""
        plug = self.armed()
        self.delivered_chat(plug)
        for index, capability in enumerate(("keep_going", "usage_wrap_up", "reset_message")):
            key = "%064x" % (index + 7)
            self.assertTrue(plug.runtime.state.add_record(key, capability, T1, at=self.h.now))
            with self.subTest(capability=capability):
                self.assertTrue(self.claim(plug, key, self.h.now), "claimed a minute after the chat's")
                self.assertTrue(plug.runtime.state.move_record(key, "finished", at=self.h.now))
            with plug.runtime.state._transaction() as connection:     # its own claim aged out, for the next one
                connection.execute("UPDATE records SET claimed_at=? WHERE record_id=?", (self.h.now - 3 * 86400, key))

    def test_a_recovery_sent_now_waits_only_while_a_chat_message_is_in_flight(self):
        """Fails with own_paced reverted: the chat's finished claim would hold core's recovery fifteen minutes."""
        plug = self.armed()
        key = self.waiting(plug)
        self.h.tick()
        connection = _core_connection(self, plug)
        own = own_paced(plug.runtime.registry)
        self.assertTrue(held_by_records(connection, T1, self.h.now, own), "one in flight")
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.assertEqual(plug.runtime.state.chat_by_record(key)["state"], ChatState.DONE)
        self.assertFalse(held_by_records(connection, T1, self.h.now + 60, own))

    def test_longer_messages_does_not_lengthen_a_chat_message(self):
        """SPLIT: Longer messages lengthens a reset message and a queued prompt; a chat message stays at A27's 2,000
        characters, all the state's chat table holds (state/schema.CHAT_WORDS) - a longer one would need its table
        made again, for one capability's limit. The page shows it as its words_limit."""
        from codex_auto_resume_advanced.control import chat as control
        plug = self.armed()
        argument = dict(thread_id=T1, words="x" * 2001, generation=plug.runtime.state.meta()["generation"])
        with patch.object(control, "switched_off", lambda runtime, thread: False):
            refused = surfaces.bridge(plug.runtime, BridgeCommand.ADVANCED_CHAT_SEND, argument)
        self.assertEqual(refused["refusal"], Refusal.PROMPT_REFUSED)
        self.assertEqual(control.WORDS, 2000)


class ChatBesideUsagePauseTests(_ChatPair):
    """codex_chat and usage_pause: COMPOSE. The forced stop near a limit holds the edition's continuations, never a
    person's message (engine/usage.holds): a chat message is the person's own instruction, as one typed in Codex is."""
    BESIDE = (USAGE_METER, USAGE_PAUSE)

    def test_a_chat_message_is_not_held_by_the_forced_stop(self):
        plug = self.armed()
        key = self.waiting(plug)
        pause = plug.runtime._code_of(USAGE_PAUSE)
        with patch.object(type(pause), "holding", lambda self: True):
            self.assertFalse(pause.holds(self.chat_record(plug, key)))
            self.assertTrue(pause.holds(dict(self.chat_record(plug, key), purpose="continuation")))


class ChatBesideWakeForResetTests(_ChatPair):
    """codex_chat and wake_for_reset: COMPOSE, the chat not counted. A chat message written while the limit is full
    has no due time of its own: it waits at core's usage gate with no schedule (the house rule: no second scheduler),
    so the wake timer is set for the reset rules, the forced stop's window and core's usage-limit records alone, and a
    waiting chat message goes at the first look once the PC is awake."""
    BESIDE = (WAKE_FOR_RESET,)

    def test_a_waiting_chat_message_sets_no_wake_timer(self):
        plug = self.armed()
        self.waiting(plug)
        wake = plug.runtime._code_of(WAKE_FOR_RESET)
        due = []
        wake._timer = type("Timer", (), {"allowed": lambda s: True, "set": lambda s, when: due.append(when) or True,
                                         "cancel": lambda s: False})()
        wake._start = lambda target: None
        errand = wake.tick(type("View", (), {"records_in": lambda s, states: []})())
        if errand is not DEFER and errand is not None:
            errand.run(lambda: None)
        self.assertEqual(due, [], "nothing of the chat's has a time to wake for")


class ChatBesideCrashRestartTests(_ChatPair):
    """codex_chat and crash_restart: COMPOSE. A watcher restarted while a chat message is in flight finds it in the
    state with no words, follows it by its client id and never sends it again: delivered once Codex shows it, or
    unproven a day on. (Codex's queue id is in the first watcher's memory alone, so one Codex never took is not taken
    back after a restart - it ends unproven, never resent.)"""
    BESIDE = (CRASH_RESTART,)

    def test_a_restart_while_a_message_is_in_flight_never_sends_it_again(self):
        plug = self.armed()
        key = self.waiting(plug)
        self.h.tick()
        self.assertEqual(len(self.calls), 1)
        again = self.advanced(self.h)                     # the restarted watcher: the same state, nothing in memory
        again.runtime._code_of(CODEX_CHAT).channel._open = lambda: FakeSession(self.h, self.calls)
        self.plugged(again, self.h)
        for _ in range(5):
            self.h.tick(advance=60)
        self.assertEqual(len(self.calls), 1, "never sent again")
        self.h.home.dispatch(T1)
        self.h.tick(advance=2)
        self.assertEqual(again.runtime.state.chat_by_record(key)["reason"], ChatReason.DELIVERED)


# ---------------------------------------------------------------- open_to_send (v0.6.19, issue #50)
from test_advanced_open_target import OpenCase  # noqa: E402
from codex_auto_resume_advanced.registry import OPEN_TO_SEND  # noqa: E402,F401
from codex_auto_resume_advanced.engine import opentarget  # noqa: E402


class OpenToSendBesideQueueForOpenTests(OpenCase):
    """COMPOSE (memory capabilities-compose): queue_for_open queues the continuation for when the conversation is opened,
    and open_to_send opens it - the open is the trigger, as M1 and MQO measured, so the one queued item is all that is
    ever sent for it."""
    BESIDE = (QUEUE_FOR_OPEN,)

    def test_opening_delivers_what_queue_for_opening_queued_and_nothing_is_sent_twice(self):
        self.armed()
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.backend.after_accept = "queue"
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "queued", row["last_error"])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.h.tick(advance=5)
        self.assertEqual(self.opened, [T1], "the queued conversation opened")
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1, "no second send")


class OpenToSendBesideOtherSessionsTests(OpenCase):
    """EXCLUSIVE by its rule: a conversation another session holds (a terminal's, VS Code's) is never opened in the app -
    core waits for it with held_by_other_session, never notLoaded, and other_sessions is the one to act on it."""
    BESIDE = (OTHER_SESSIONS,)

    def test_a_conversation_another_session_holds_is_not_opened(self):
        self.armed()
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "elsewhere"
        for _ in range(4):
            self.h.tick(advance=61)
        self.assertEqual(self.opened, [])


class OpenToSendBesideHeadlessRunTests(OpenCase, UnheldCase):
    """EXCLUSIVE where headless_run takes it: with Codex closed and nothing holding the conversation, headless_run's route
    runs it at P16, before P8's errand - so even with Also start Codex on the conversation is not opened as well
    (headless first; the owner may change that)."""
    BESIDE = (HEADLESS_RUN,)

    def setUp(self):
        super().setUp()
        self.compat = _compat(*{definition.compat for definition in (*self.BESIDE, self.DEFINITION)})

    def test_a_conversation_headless_run_takes_is_not_opened(self):
        plug = self.armed()
        self.choose(plug, "open_start_codex", opentarget.ON)
        route = Silent(self.h)
        plug.runtime._code[HEADLESS_RUN.id] = _RouteOnly(route)
        self.running = False
        self.closed()
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(route.calls), 1, "headless_run ran it")
        self.assertEqual(self.opened, [])


# ------------------------------------------------------------------ v0.6.20: push_notices and status_feed (the courier)
class CourierBesideEveryCapabilityTests(ac.AdvancedCase):
    """COMPOSE, none needed: push_notices and status_feed only observe. Neither answers at a point that decides or sends
    (P20 is told and its answer never read; P8's errands only start the courier), so with either on beside any other
    capability, every answer the other gives at every point is the one it gives alone."""

    def test_they_answer_at_no_deciding_point(self):
        from codex_auto_resume_advanced.registry import PUSH_NOTICES, STATUS_FEED
        self.assertEqual(PUSH_NOTICES.points, frozenset({Point.NOTICE, Point.TICK}))
        self.assertEqual(STATUS_FEED.points, frozenset({Point.TICK}))
        for definition in (PUSH_NOTICES, STATUS_FEED):
            self.assertEqual(definition.requires, ())

    def test_beside_every_shipped_capability_the_other_answers_as_it_does_alone(self):
        from codex_auto_resume_advanced import registry as shipped
        from codex_auto_resume_advanced.registry import PUSH_NOTICES, STATUS_FEED
        courier = {PUSH_NOTICES.id, STATUS_FEED.id}
        others = [definition for definition in shipped.DEFINITIONS if definition.id not in courier]
        for definition in others:
            with self.subTest(definition.id):
                # Neither of the courier's two is ever asked at a point the other answers at but P8, where errands join.
                shared = (PUSH_NOTICES.points | STATUS_FEED.points) & definition.points
                self.assertLessEqual(shared, frozenset({Point.TICK, Point.NOTICE}))
                self.assertNotIn(Point.NOTICE, definition.points)


class RemoteBesideEveryCapabilityTests(ac.AdvancedCase):
    """COMPOSE, none needed (v0.6.22, D-remote.md): the loopback API only observes, and what widens it only reduces. It
    answers at no point that decides or sends: P8's errand only starts its process, the other two answer at none. A pause
    or a cancel through it is core's own, as a person's in the Dashboard is, so with it on beside any other capability,
    every answer the other gives at every point is the one it gives alone."""

    def test_they_answer_at_no_deciding_point(self):
        from codex_auto_resume_advanced.registry import LOCAL_API, LOCAL_API_ACTIONS, LOCAL_API_LAN
        self.assertEqual(LOCAL_API.points, frozenset({Point.TICK}))
        self.assertEqual((LOCAL_API_ACTIONS.points, LOCAL_API_LAN.points), (frozenset(), frozenset()))

    def test_beside_every_shipped_capability_only_p8_is_shared_and_the_wake_timer_stays_last(self):
        from codex_auto_resume_advanced import registry as shipped
        from codex_auto_resume_advanced.registry import LOCAL_API
        for definition in shipped.DEFINITIONS:
            if definition.id != LOCAL_API.id:
                with self.subTest(definition.id):
                    self.assertLessEqual(LOCAL_API.points & definition.points, frozenset({Point.TICK}))
        ticking = [definition.id for definition in shipped.DEFINITIONS if Point.TICK in definition.points]
        self.assertEqual(ticking[-1], "wake_for_reset")

    def test_its_errand_keeps_nothing_another_capability_reads(self):
        """What it writes is its own journal lines: no record, no claim, no spend, no due time another's errand reads."""
        import inspect
        from codex_auto_resume_advanced.engine import remote
        source = inspect.getsource(remote)
        for word in ("claim", "dispatch", "spend", "records", "continuations", "prompts", "resets"):
            self.assertNotIn(word, source)


# ---------------------------------------------------------------- v0.6.20: account_switch (plans/v0619-design/D-account.md)
class AccountBesideResetsAndPauseTests(UsageCase):
    """account_switch beside reset_credit, reset_message and usage_pause: COMPOSE, each still doing its own. Another
    account signed in holds core's waiting usage-limit records and every reset rule still counting - held in the reset
    actions' own words, as over a gap in the count (state/resets.py has no word of its own for a change of account, and
    count_gap is what a count that cannot be carried over is), Go on counting the person's - while usage_pause's own
    hold of core's records at P3 still answers beside it. reset_message's rule is held the same way
    (test_advanced_account.ResetRuleTests)."""

    class View:
        def records_in(self, wanted):
            return [{"interruption_id": ac.KEY, "category": "usage_limit", "state": "waiting_reset"}]

    def setUp(self):
        ac.AdvancedCase.setUp(self)
        from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH
        from test_advanced_account import ONE, OTHER, Secrets
        from codex_auto_resume_advanced.codex import account
        self.compat = {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
                       "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                        for name in ("usage_probe", "exact_thread_recovery")}}
        self.rt = self.runtime(ACCOUNT_SWITCH, RESET_CREDIT, USAGE_METER, USAGE_PAUSE)
        self.rt.arming.catalogs = statement.CATALOGS
        self.answer, self.calls, self.app = reply(), [], True
        meter = self.rt._code_of(USAGE_METER)
        meter._session = lambda: Session(self.answer, self.calls)
        meter._app_running = lambda: self.app
        self.signed, self.other, self.holds = ONE, OTHER, []
        code = self.rt._code_of(ACCOUNT_SWITCH)
        code._read = lambda paths: account.parse(self.signed)
        code._secrets = self.rt.arming.secrets = Secrets()
        code._hold = lambda paths, keys, now: self.holds.append(list(keys)) or len(keys)

    def tick(self):
        answer = self.rt.tick(self.View())
        if answer is not DEFER:
            answer.run(lambda: None)
        self.rt.states(fresh=True)

    def test_a_counting_credit_rule_is_held_and_core_s_records_too(self):
        from codex_auto_resume_advanced.vocabulary import RuleReason, RuleState
        self.on("reset_credit", "account_switch")
        rule = self.rt.state.add_reset_rule("reset_credit", "codex", 300, 2, at=self.now)
        self.tick()
        self.signed = self.other
        self.now += 1800
        self.tick()
        held = self.rt.state.reset_rule(rule)
        self.assertEqual((held["state"], held["reason"]), (RuleState.HELD, RuleReason.COUNT_GAP))
        self.assertEqual(self.holds, [[ac.KEY]])

    def test_the_pause_still_holds_beside_the_account_s_hold(self):
        self.on("usage_pause", "account_switch")
        self.answer = reply(five=100)
        self.tick()
        self.tick()                                   # the pause's own tick marks the window
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit",
                  "state": "waiting_reset"}
        self.assertIs(self.rt.ask(Point.GATES, "submission_safe", record, {}), Alternative.HOLD)
        self.signed = self.other
        self.now += 1800
        self.tick()
        self.assertEqual(self.holds, [[ac.KEY]], "core's record is held for the person")
        self.assertIs(self.rt.ask(Point.GATES, "submission_safe", record, {}), Alternative.HOLD,
                      "and the pause still holds it at P3 until its window resets")


# v0.6.20: Continue inside the turn (stop_hook_continuation, D-stop-hook.md) beside the capabilities its design pairs it
# with. COMPOSE with capacity_retry, unknown_failure_budget and marker_free_continuation: the hook's continuation is the
# first attempt at a failure, and theirs come after it under the same caps on one conversation - each of the hook's
# counts there as a claim. EXCLUSIVE with keep_going by nature: a turn that ended normally is never the hook's.
from test_advanced_hook_claim import HookClaimCase  # noqa: E402
from codex_auto_resume import settings as core_settings  # noqa: E402
from codex_auto_resume_advanced.hook import handler as hook_handler  # noqa: E402
from codex_auto_resume_advanced.vocabulary import HookOutcome  # noqa: E402


class StopHookBesideTheRetriesTests(HookClaimCase):
    """capacity_retry, unknown_failure_budget and marker_free_continuation each carry a later send in the conversation;
    the hook's block before them is a claim they wait fifteen minutes after, and none of them is undone by it."""

    def test_the_hook_s_continuation_is_a_claim_the_others_sends_wait_for(self):
        self.due()
        other = dict(self.failure(), interruption_id="%064x" % 11)
        self.assertEqual(self.hook(other, turn="55555555-5555-4555-8555-555555555555"), HookOutcome.BLOCKED)
        # Core's record of the conversation - whichever capability's words or channel its send would carry - is held.
        self.assertEqual(self.ledger(), Alternative.HOLD)
        self.assertIs(self.ledger(now=self.h.now + 901), DEFER)

    def test_the_kinds_they_take_up_are_not_the_hook_s_and_capacity_s_is_both_in_turn(self):
        values = dict(core_settings.DEFAULTS)
        for kind in ("unknown", "terminal_failure", "usage_limit", "rate_limit_transient"):
            with self.subTest(kind):
                self.assertFalse(hook_handler.continues({"category": kind}, values))
        self.assertTrue(hook_handler.continues({"category": "server_5xx"}, values),
                        "Codex at capacity: the hook first, inside the turn; capacity_retry's waits after it")


class StopHookBesideKeepGoingTests(unittest.TestCase):
    """A Stop hook on every normal stop would turn every turn into a loop: a turn that completed is keep_going's alone."""

    def test_a_turn_that_ended_normally_is_never_claimed(self):
        from codex_auto_resume.codex.values import normalize
        thread, turn = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
        claims = []
        hands = hook_handler.Hands(
            armed=lambda: True, settings=lambda: dict(core_settings.DEFAULTS),
            latest=lambda _thread: normalize({"thread_id": thread, "turn_id": turn, "status": "completed",
                                              "started_at": 1_790_000_000.0, "completed_at": 1_790_000_010.0,
                                              "rollout_ordinal": 3}),
            claim=lambda *arguments: claims.append(arguments) or HookOutcome.BLOCKED)
        stop = {"hook_event_name": "Stop", "session_id": thread, "turn_id": turn}
        self.assertIsNone(hook_handler.decide(stop, hands))
        self.assertEqual(claims, [])



# ------------------------------------------------------------------ v0.6.20: the four not audited before (the pair audit
# of 2026-10-31, plans/v0620-capability-pairs.md): model_fallback, window_anchor, steer_send, every_conversation.
from codex_auto_resume_advanced.registry import CAPACITY_RETRY, MODEL_FALLBACK  # noqa: E402
from test_advanced_headless import SAVED, Server  # noqa: E402
from test_advanced_model_fallback import Codes  # noqa: E402

DEFAULT_MODEL = "the-default-model"
WORDS = "Continue.\n\n[codex-auto-resume:0123456789abcdef]"


class FallbackBesideHeadlessRunTests(ac.AdvancedCase):
    """Finding V20-1, SPLIT: model_fallback answers P16 before headless_run (registry order) for an unheld conversation
    at capacity past the Attempts - and where that conversation is on Codex's default model already, its route starts
    nothing (codex/headless.py: no other model to fall back to). Core gives the claim back and the record waits; at its
    next look model_fallback answered again, so headless_run - whose turn on the same model is what that case needs -
    was passed over, and each answer was a claim that cost core's spacing and caps. Each now acts on its own cases:
    a conversation found on the default is headless_run's (or core's) from then on."""
    THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
    OTHER = "0a1b2c3d-0001-7000-8000-000000000002"
    TURN = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        super().setUp()
        self.compat = _compat(MODEL_FALLBACK.compat, HEADLESS_RUN.compat)
        self.rt = self.runtime(MODEL_FALLBACK, HEADLESS_RUN)
        self.rt.arming.catalogs = statement.CATALOGS
        for name, value in (("INTERRUPT_SECONDS", 0.5), ("APP_LOOK_SECONDS", 0.0)):
            self.addCleanup(setattr, headless, name, getattr(headless, name))
            setattr(headless, name, value)
        self.follower = headless.Follower(poll=0.01)
        self.models, self.servers = {}, []

        def opening(capability):
            self.servers.append(_ByThread(capability, self.models))
            return self.servers[-1]
        fallback = self.rt._code_of(MODEL_FALLBACK)
        fallback._turns, fallback._open, fallback.follower = Codes("serverOverloaded"), opening, self.follower
        fallback._app = lambda: False
        run = self.rt._code_of(HEADLESS_RUN)
        run._open, run.follower, run._app = opening, self.follower, lambda: False
        for definition in (MODEL_FALLBACK, HEADLESS_RUN):
            result = self.arm(self.rt, definition.id, warnings=[str(w) for w in self.rt.arming.warnings(definition)])
            self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def record(self, thread, key=7):
        return {"interruption_id": "%064x" % key, "thread_id": thread, "turn_id": self.TURN, "category": "server_5xx",
                "chain_continuations": 2, "holder": "none", "app": False}

    def route(self, record):
        self.rt.tick(None)                                   # a new look: what was taken last time is forgotten
        return self.rt.ask(Point.UNLOADED, record)

    def resume(self, route, thread):
        answered = route.resume(thread, still_unloaded=lambda: True, words=WORDS, client_id=None)
        if answered.get("outcome") == "ran":
            deadline = time.monotonic() + 5
            while self.follower.live() is not None and time.monotonic() < deadline:
                time.sleep(0.01)
        return answered

    def test_a_conversation_on_the_default_model_already_is_headless_run_s_after_one_look(self):
        """Fails with the fix reverted: model_fallback answers again and again, and starts nothing each time."""
        self.models[self.THREAD] = DEFAULT_MODEL
        first = self.route(self.record(self.THREAD))
        self.assertEqual(first.capability, MODEL_FALLBACK.id)
        self.assertEqual(self.resume(first, self.THREAD)["outcome"], "not_started", "nothing to fall back to")
        self.assertNotIn("turn/start", self.servers[-1].methods())
        again = self.route(self.record(self.THREAD))
        self.assertEqual(again.capability, HEADLESS_RUN.id, "the same model again is headless_run's turn")
        self.assertEqual(self.resume(again, self.THREAD)["outcome"], "ran")
        started = dict(self.servers[-1].calls)["turn/start"]
        self.assertNotIn("model", started, "on the conversation's own model")

    def test_a_conversation_on_another_model_still_falls_back(self):
        self.models[self.THREAD] = DEFAULT_MODEL
        self.resume(self.route(self.record(self.THREAD)), self.THREAD)
        self.models[self.OTHER] = "the-threads-model"
        other = self.route(self.record(self.OTHER, key=8))
        self.assertEqual(other.capability, MODEL_FALLBACK.id, "each conversation on its own")
        self.assertEqual(self.resume(other, self.OTHER)["outcome"], "ran")
        self.assertEqual(dict(self.servers[-1].calls)["turn/start"]["model"], DEFAULT_MODEL)


class _ByThread(Server):
    """A route's session whose thread/resume answers for the conversation asked - its saved settings, on the model the
    test gave it - and whose model/list names DEFAULT_MODEL Codex's default."""

    def __init__(self, capability, models):
        super().__init__(capability, replies={"model/list": {"data": [{"model": DEFAULT_MODEL, "isDefault": True}]}})
        self.models = models

    def call(self, method, params=None):
        answer = super().call(method, params)
        return dict(SAVED, model=self.models[params["threadId"]]) if method == "thread/resume" else answer



from test_advanced_window_anchor import AnchorCase  # noqa: E402
from codex_auto_resume_advanced.engine import anchor as anchor_engine  # noqa: E402
from codex_auto_resume_advanced.registry import ACCOUNT_SWITCH, WINDOW_ANCHOR  # noqa: E402
from codex_auto_resume_advanced.vocabulary import OptionKey  # noqa: E402


class _AnchorBeside(AnchorCase):
    """window_anchor beside the capabilities in BESIDE: its own harness (test_advanced_window_anchor.AnchorCase - every
    usage read a fake session, every request a stub process), with them armed in one runtime."""
    BESIDE = ()

    def setUp(self):
        super().setUp()
        self.rt.state.close()
        self.rt = self.runtime(*self.BESIDE, WINDOW_ANCHOR)
        self.rt.arming.catalogs = statement.CATALOGS
        self.wire()

    def beside(self, capability):
        definition = self.rt.registry.get(capability)
        result = self.arm(self.rt, capability, warnings=[str(w) for w in self.rt.arming.warnings(definition)])
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)


class AnchorBesideAccountSwitchTests(_AnchorBeside):
    """Finding V20-2, COMPOSE: the 5-hour window is the signed-in account's, but window_anchor kept one start, one fixed
    reset and one reset seen whatever account they were of - so after account_switch saw another account signed in,
    a time picked within five hours of a start made on the other account was refused `skip_once` though this account's
    window was idle, and the reset seen was the other account's. account_switch's mechanism now carries it: the change
    it sees is stamped, and window_anchor lets the other account's window stamps go."""
    BESIDE = (ACCOUNT_SWITCH,)

    def setUp(self):
        super().setUp()
        from test_advanced_account import ONE, OTHER, Secrets
        from codex_auto_resume_advanced.codex import account
        self.signed, self.other = ONE, OTHER
        code = self.rt._code_of(ACCOUNT_SWITCH)
        code._read = lambda paths: account.parse(self.signed)
        code._secrets = self.rt.arming.secrets = Secrets()
        code._hold = lambda paths, keys, now: len(keys)

    def two_times(self):
        self.beside("account_switch")
        self.on(anchor_at_1=anchor_engine.encode_time(7, 0), anchor_at_2=anchor_engine.encode_time(8, 0),
                anchor_after_reset=2)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)

    def test_another_account_s_idle_window_is_started_at_the_next_time_picked(self):
        """Fails with the fix reverted: refused skip_once for the start made on the other account an hour before."""
        self.two_times()
        first_fixed = self.stamped(OptionKey.ANCHOR_FIXED_AT)
        self.signed, self.world.running_until = self.other, None    # another account, its window idle
        self.now = float(anchor_engine.midnight(self.now) + 8 * 3600 - 30)
        self.run_through()
        self.assertEqual(len(self.world.started), 2, "the other account's window started too")
        self.assertNotIn("anchor.skip_once", self.codes())
        self.assertEqual(self.codes()[-2:], ["anchor.started", "anchor.fixed"])
        self.assertNotEqual(self.stamped(OptionKey.ANCHOR_FIXED_AT), first_fixed, "the reset this account's start fixed")

    def test_the_same_account_still_starts_one_window_once(self):
        self.two_times()
        self.world.running_until = None
        self.now = float(anchor_engine.midnight(self.now) + 8 * 3600 - 30)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        self.assertEqual(self.codes()[-1], "anchor.skip_once")


class AnchorBesideUsagePauseTests(_AnchorBeside):
    """window_anchor beside usage_pause: SPLIT by what each touches. The pause holds this product's continuations while
    a window it marked has not reset; the anchor starts only an idle 5-hour window, so a pause of the 5-hour window
    and a start never meet, and a pause of the weekly window (under 100 %) leaves an idle 5-hour window to start -
    while the pause still holds core's records at P3 beside it. A start costs under 1 % (MANCHOR)."""
    BESIDE = (USAGE_METER, USAGE_PAUSE)

    def test_a_held_weekly_window_does_not_stop_a_start_and_the_pause_still_holds(self):
        self.beside("usage_meter")
        self.beside("usage_pause")
        self.rt.state.save_meter([{"bucket": "codex", "window_minutes": 10080, "used_percent": 96.0,
                                   "reset_at": int(self.now + 86400)}])
        self.assertTrue(self.rt.state.mark_meter("codex", 10080, paused_reset_at=int(self.now + 86400)))
        self.world.week = 96.0
        self.on(anchor_at_1=anchor_engine.encode_time(7, 0), anchor_after_reset=2)
        self.run_through()
        self.assertEqual(len(self.world.started), 1)
        record = {"interruption_id": ac.KEY, "thread_id": ac.THREAD, "category": "usage_limit",
                  "state": "waiting_reset"}
        self.assertIs(self.rt.ask(Point.GATES, "submission_safe", record, {}), Alternative.HOLD)


class FallbackBesideCapacityRetryTests(ac.AdvancedCase):
    """model_fallback beside capacity_retry: COMPOSE. capacity_retry takes a capacity failure up at P17 (CAPACITY:
    sooner retries on the same model); the record keeps its kind (server_5xx), so once its task has had the Attempts
    and nothing holds the conversation with Codex closed, model_fallback's turn on Codex's default is still P16's."""

    def test_a_task_capacity_retry_took_up_falls_back_past_the_attempts(self):
        self.compat = _compat(MODEL_FALLBACK.compat, CAPACITY_RETRY.compat)
        rt = self.runtime(CAPACITY_RETRY, MODEL_FALLBACK)
        rt.arming.catalogs = statement.CATALOGS
        code = rt._code_of(MODEL_FALLBACK)
        code._turns, code._app = Codes("serverOverloaded"), lambda: False
        code._open, code.follower = (lambda capability: None), headless.Follower(poll=0.01)
        for definition in (CAPACITY_RETRY, MODEL_FALLBACK):
            result = self.arm(rt, definition.id, warnings=[str(w) for w in rt.arming.warnings(definition)])
            self.assertTrue(result["done"], result)
        rt.states(fresh=True)
        key = "%064x" % 7
        facts = {"category": "server_5xx", "code": "serverOverloaded", "takes": frozenset({Alternative.CAPACITY}),
                 "interruption_id": key,
                 "thread_id": FallbackBesideHeadlessRunTests.THREAD, "completed_at": self.now + 1}
        self.assertIs(rt.ask(Point.ADMISSION, facts), Alternative.CAPACITY, "capacity_retry takes it up")
        record = {"interruption_id": key, "thread_id": FallbackBesideHeadlessRunTests.THREAD,
                  "turn_id": FallbackBesideHeadlessRunTests.TURN, "category": "server_5xx", "chain_continuations": 2,
                  "holder": "none", "app": False}
        route = rt.ask(Point.UNLOADED, record)
        self.assertEqual((route.capability, route.mode), (MODEL_FALLBACK.id, headless.FALLBACK))


from test_advanced_steer_send import SteerCase  # noqa: E402
from codex_auto_resume_advanced.registry import STEER_SEND  # noqa: E402
from codex_auto_resume_advanced.vocabulary import SteerState  # noqa: E402


class SteerBesideUsagePauseTests(SteerCase):
    """steer_send beside usage_pause (and the prompt queue it needs): SPLIT by whose words. The pause holds this
    product's continuations; a steer is a person's own line, as a queued prompt is, which the pause leaves alone - so a
    held window neither holds nor refuses it, and it is written once, while the pause still holds core's records."""
    BESIDE = (PROMPT_QUEUE, USAGE_METER, USAGE_PAUSE)

    def setUp(self):
        super().setUp()
        self.compat = _compat(*{definition.compat for definition in (*self.BESIDE, STEER_SEND)})

    def test_a_steer_is_written_while_a_window_is_held(self):
        plug, runtime = self.on()
        runtime._code_of(USAGE_METER)._app_running = lambda: False       # the meter reads nothing here
        runtime.state.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 97.0,
                                   "reset_at": int(self.h.now + 3600)}])
        self.assertTrue(runtime.state.mark_meter("codex", 300, paused_reset_at=int(self.h.now + 3600)))
        self.assertTrue(runtime._code_of(USAGE_PAUSE).holding(), "the window is held")
        self.assertTrue(self.ask(runtime)["done"])
        self.h.tick()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.rows(runtime)[0]["state"], SteerState.ACCEPTED)
        self.assertTrue(runtime._code_of(USAGE_PAUSE).holding(), "and still held for core's records")


from codex_auto_resume_advanced.registry import EVERY_CONVERSATION  # noqa: E402
from test_session_kinds import CLI, add_thread  # noqa: E402


class EveryConversationBesideOtherSessionsTests(TakingCase):
    """every_conversation beside other_sessions: COMPOSE. Each widens a different check of the one place core judges a
    conversation (codex/eligibility.row_problem): other_sessions which sources (P18: a terminal's, VS Code's),
    every_conversation which labels (P19) - so a terminal's conversation with a label the standard edition does not
    know is taken up with both on, and with either alone it is not. every_conversation sends nothing itself, so no
    unit of any ceiling is ever spent in its name."""
    DEFINITION = EVERY_CONVERSATION
    BESIDE = (OTHER_SESSIONS,)

    def fresh(self, **kwargs):
        made = super().fresh(**kwargs)
        holding_sessions(made.backend)
        return made

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def setUp(self):
        super().setUp()
        self.compat = _compat(EVERY_CONVERSATION.compat, OTHER_SESSIONS.compat)

    def test_a_terminal_s_conversation_with_a_new_label_is_taken_up_with_both_on(self):
        plug = self.armed()
        add_thread(self.h.home, T1, **CLI, thread_source="a_label_from_tomorrow")
        self.ready_after_reset(self.h, thread_id=T1)
        self.h.tick()
        self.assertEqual(len(self.h.records(T1)), 1)
        for _ in range(3):
            self.h.tick(advance=60)
        self.assertNotIn(EVERY_CONVERSATION.id, [spend[0] for spend in self.spends(plug)])

    def test_with_either_alone_it_is_not(self):
        for alone in (EVERY_CONVERSATION, OTHER_SESSIONS):
            with self.subTest(alone.id):
                h = self.fresh()
                plug = self.advanced(h)
                self.arm(plug, capability=alone.id)
                self.plugged(plug, h)
                add_thread(h.home, T1, **CLI, thread_source="a_label_from_tomorrow")
                self.ready_after_reset(h, thread_id=T1)
                h.tick()
                self.assertEqual(h.records(T1), [])


class WakeBesideAnchorTests(WakeBesideTheResetCapabilitiesTests):
    """wake_for_reset beside window_anchor: COMPOSE (the owner's word of 2026-10-31, "예, 함께 동작"). While both stand on,
    the wake timer is set for window_anchor's next time picked too - and, with Start right after a reset on, for the
    reset it waits for (plus the minute it waits after one) - read from its own choices and stamps, never written; so a
    PC asleep at a time picked still has its window started, and core's own due times still come first where earlier."""

    def setUp(self):
        super().setUp()
        self.rt.state.close()
        self.compat = _compat("engine_present", "usage_probe")
        self.rt = self.runtime(WAKE_FOR_RESET, WINDOW_ANCHOR)
        self.rt.arming.catalogs = statement.CATALOGS
        self.code = self.rt._code_of(WAKE_FOR_RESET)
        self.code._timer = self.timer = self.Timer()
        self.code._start = lambda target: None
        self.now = float(anchor_engine.midnight(ac.NOW) + 6 * 3600)          # 06:00 local

    def choose(self, key, value):
        self.rt.state.set_option("window_anchor", OptionKey(key), value, generation=self.rt.state.meta()["generation"],
                                 actor=Actor.DASHBOARD)

    def test_the_timer_wakes_the_pc_for_a_time_picked_and_for_the_reset_it_waits_for(self):
        """Fails with the fix reverted: no timer at all - nothing of core's or the reset actions' waits."""
        self.on("wake_for_reset")
        self.on("window_anchor")
        self.choose("anchor_at_1", anchor_engine.encode_time(7, 0))
        self.errand([])
        seven = anchor_engine.midnight(self.now) + 7 * 3600
        self.assertEqual(self.timer.due, seven - 120, "07:00, less the lead")
        self.assertTrue(self.rt.state.stamp("window_anchor", OptionKey.ANCHOR_SEEN_RESET, int(self.now + 1800)))
        self.errand([])
        self.assertEqual(self.timer.due, int(self.now + 1800) + anchor_engine.AFTER_RESET - 120,
                         "the reset it saw comes first: Start right after a reset is on by default")
        self.choose("anchor_after_reset", 2)
        self.errand([])
        self.assertEqual(self.timer.due, seven - 120, "with it off, the time picked alone")
        core = {"state": "waiting_reset", "category": "usage_limit", "next_check_at": self.now + 600}
        self.errand([core])
        self.assertEqual(self.timer.due, self.now + 600 - 120, "core's earlier due time still first")

    def test_a_time_already_handled_wakes_for_tomorrow_s(self):
        self.on("wake_for_reset")
        self.on("window_anchor")
        self.choose("anchor_at_1", anchor_engine.encode_time(7, 0))
        seven = anchor_engine.midnight(self.now) + 7 * 3600
        self.assertTrue(self.rt.state.stamp("window_anchor", OptionKey.ANCHOR_SLOT_DONE, seven))
        self.errand([])
        self.assertEqual(self.timer.due, seven + 86400 - 120)

    def test_with_window_anchor_off_its_times_wake_nothing(self):
        self.on("wake_for_reset")
        self.choose("anchor_at_1", anchor_engine.encode_time(7, 0))
        self.errand([])
        self.assertIsNone(self.timer.due)

    # The reset capabilities' own test, which this class's runtime does not carry.
    test_the_timer_is_set_for_the_earliest_due_time_of_them_all = None


from test_advanced_subagent import CHILDREN, SubagentCase  # noqa: E402
from codex_auto_resume_advanced.registry import SUBAGENT_PARENT  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Measurement as _Measurement, Verdict as _Verdict  # noqa: E402

NEW_LABEL = "a_label_from_tomorrow"


class SubagentFollowUpBesideEveryConversationTests(SubagentCase):
    """subagent_parent's follow-up to a parent that finished (5b) beside every_conversation: COMPOSE (the owner's word
    of 2026-10-31, "정식 전에 고치기"). 5b picked its parents from every conversation with a turn lately, judged by
    nothing, so a parent core never takes up - a label the standard edition does not know, with every_conversation off
    - got a continuation that waited for good. It now judges a parent as core does (core's reader, P19's widening while
    every_conversation is on), as empty_response and the wrap-up do, and one already waiting for a parent core no longer
    takes up is withdrawn."""
    BESIDE = (EVERY_CONVERSATION,)

    def setUp(self):
        super().setUp()
        self.measured = {_Measurement.MS: (_Verdict.PASS, ENGINE)}
        self.compat = _compat(SUBAGENT_PARENT.compat, EVERY_CONVERSATION.compat)

    def finished(self, label):
        self.h.home.add_thread(T1, thread_source=label)
        self.spawned(CHILDREN[:1])
        self.h.home.add_turn(T1, completed=int(self.h.now))
        for _ in range(3):
            self.h.tick(advance=61)

    def waiting(self, plug):
        return [row for row in plug.runtime.state.continuations(capability=SUBAGENT_PARENT.id)
                if row["thread_id"] == T1 and row["record_state"] == "waiting"]

    def test_a_parent_core_never_takes_up_gets_no_follow_up_that_waits_for_good(self):
        """Fails with the fix reverted: a continuation for that parent, waiting, never sent."""
        plug = self.on()
        plug.runtime.arming.disarm(EVERY_CONVERSATION.id, actor=Actor.DASHBOARD)
        plug.runtime.states(fresh=True)
        self.finished(NEW_LABEL)
        self.assertEqual(self.waiting(plug), [])
        self.assertEqual(self.h.backend.send_calls, [])

    def test_with_every_conversation_on_that_parent_is_followed_up(self):
        self.on()
        self.finished(NEW_LABEL)
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])
        self.assertEqual(len(self.lines(self.h.backend.send_calls[0][1])), 1)


class _PowerTasksPair(ac.AdvancedCase):
    """power_after_tasks (v0.6.20, Discussion #57) armed beside another: its runtime, its code given the test's own
    Codex history and core records, and core's power action file on the scratch home."""
    TURN = "11111111-1111-7111-8111-111111111111"
    RECOVERY = "22222222-2222-7222-8222-222222222222"

    class Statuses:
        def __init__(self, statuses):
            self.statuses = statuses

        def status(self, thread, turn):
            return self.statuses.get(turn)

    def setUp(self):
        super().setUp()
        from codex_auto_resume import managed
        from codex_auto_resume.control import policy as control_policy, poweraction as control_power
        from codex_auto_resume_advanced.registry import POWER_AFTER_TASKS
        self.paths.ensure()
        for stand_in in (patch.object(control_power.PowerActionMixin, "power_port", _AlwaysOffered()),
                         patch.object(control_policy, "managed_policy", return_value=managed.NONE)):
            stand_in.start()
            self.addCleanup(stand_in.stop)
        self.compat = {"status": "ok", "engine": {"found": True, "version": ac.ENGINE},
                       "capabilities": {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"}
                                        for name in ("recovery_turn_tracking", "usage_probe", "loaded_state_detection")}}
        self.plug_ = self.plug(POWER_AFTER_TASKS, *self.beside())
        self.rt = self.plug_.runtime
        self.rt.arming.catalogs = statement.CATALOGS
        self.statuses = self.Statuses({self.TURN: "failed"})
        self.records = []
        from codex_auto_resume_advanced.engine import powertasks
        self.powertasks = powertasks
        code = self.rt._code_of(POWER_AFTER_TASKS)
        code._records, code._turns = (lambda: self.records), self.statuses

    def beside(self):
        return ()

    def on(self, capability):
        definition = self.rt.registry.get(capability)
        result = self.rt.arming.arm(capability, state="armed", revision=definition.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(definition)], actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)
        self.rt.states(fresh=True)

    def arm_tasks(self):
        """Core's power action armed for one task, as the card arms it, and the list written under its nonce."""
        from codex_auto_resume.control import Control
        from codex_auto_resume_advanced.control.powertasks import _plug_of
        Control(self.paths, plug=_plug_of(self.rt)).arm_power_action(
            {"action": "sleep", "after": "any_end", "repeat": "once", "grace_minutes": 5}, tasks=True)
        armed = self.stored()["armed"]
        self.assertTrue(self.powertasks.write(self.paths, {
            "format": self.powertasks.FORMAT, "nonce": armed["nonce"], "armed_at": armed["armed_at"], "failed": False,
            "interrupted": False, "tasks": [{"thread_id": ac.THREAD, "turn_id": self.TURN}]}))
        return armed["nonce"]

    def stored(self):
        return json.loads(self.paths.power_action_file.read_text(encoding="utf-8"))

    def answer(self, nonce):
        from codex_auto_resume.domain.plug import guard
        return guard(self.plug_).power({"nonce": nonce})


class _AlwaysOffered:
    def available(self, action):
        return True, None

    def act(self, action):
        raise AssertionError("nothing here acts")


class PowerTasksBesideThePowerActionTests(_PowerTasksPair):
    """power_after_tasks beside the standard power action after recoveries: ONE POWER ACTION AT A TIME. Both are the one
    arming of config/power-action.json: arming either replaces the other, as a second arming always did; the list of an
    arming that was replaced answers nothing for the new one, and an arming without `tasks` never asks the plug."""

    def test_settings_arming_after_a_tasks_arming_replaces_it_and_the_list_decides_nothing(self):
        from codex_auto_resume import poweraction
        from codex_auto_resume.control import Control
        self.on("power_after_tasks")
        nonce = self.arm_tasks()
        Control(self.paths).arm_power_action({"action": "sleep", "after": "all_recovered", "repeat": "once",
                                              "grace_minutes": 5})
        armed = self.stored()["armed"]
        self.assertFalse(poweraction.for_tasks(armed), "the usage-limit batch decides it")
        self.assertEqual(self.answer(armed["nonce"])["tasks"], "unknown", "the old list is another arming's")
        self.assertNotEqual(armed["nonce"], nonce)

    def test_a_tasks_arming_after_settings_arming_replaces_it(self):
        from codex_auto_resume import poweraction
        from codex_auto_resume.control import Control
        Control(self.paths).arm_power_action({"action": "hibernate", "after": "all_recovered", "repeat": "always",
                                              "grace_minutes": 10})
        self.on("power_after_tasks")
        self.arm_tasks()
        armed = self.stored()["armed"]
        self.assertTrue(poweraction.for_tasks(armed))
        self.assertEqual((armed["action"], armed["repeat"]), ("sleep", "once"))


class PowerTasksBesideRecoveryTests(_PowerTasksPair):
    """power_after_tasks beside a recovery capability (reset_credit): RECOVERY FIRST. A watched task cut off by a usage
    limit is recovered as the other capability and core recover it; while its record waits, the plug says running and
    core waits for the recovery anyway; once recovered, the task's end is its recovery turn's."""

    def beside(self):
        return (RESET_CREDIT,)

    def test_a_watched_task_waits_for_its_recovery_then_its_recovery_turn_decides(self):
        from codex_auto_resume import poweraction
        self.on("power_after_tasks")
        self.on("reset_credit")
        nonce = self.arm_tasks()
        waiting = {"interruption_id": "%064x" % 9, "thread_id": ac.THREAD, "turn_id": self.TURN, "state": "waiting_reset",
                   "recovery_turn_id": None, "parent_interruption_id": None, "detected_at": 1000, "category": "usage_limit",
                   "outcome_at": None, "last_error": None, "queue_id": None, "submitted_at": None}
        self.records = [waiting]
        self.assertEqual(self.answer(nonce)["tasks"], "running")
        found = poweraction.decide(poweraction.Facts(now=ac.NOW, read=poweraction.READ_OK,
                                                     document={"armed": self.stored()["armed"]}, rows=(waiting,),
                                                     tasks="met"))
        self.assertEqual(found.word, "recovery_open", "core waits for any recovery, whatever the plug says")
        self.records = [dict(waiting, state="recovered", recovery_turn_id=self.RECOVERY)]
        self.statuses.statuses[self.RECOVERY] = "inProgress"
        self.assertEqual(self.answer(nonce)["tasks"], "running")
        self.statuses.statuses[self.RECOVERY] = "completed"
        self.assertEqual(self.answer(nonce), {"tasks": "met", "threads": (ac.THREAD,)})
        self.assertEqual(self.rt.registry.at(Point.POWER)[0].id, "power_after_tasks", "the other answers nothing there")


if __name__ == "__main__":
    unittest.main()
