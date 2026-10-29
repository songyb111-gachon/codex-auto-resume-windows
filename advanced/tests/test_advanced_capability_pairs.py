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


if __name__ == "__main__":
    unittest.main()
