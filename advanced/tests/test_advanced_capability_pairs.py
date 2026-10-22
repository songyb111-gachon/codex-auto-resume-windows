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


if __name__ == "__main__":
    unittest.main()
