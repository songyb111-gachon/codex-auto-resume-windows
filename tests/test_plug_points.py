"""Where core asks the edition's plug, and what it does with each answer (v0.6.11, P2-P14).

tests/test_edition.py holds the interface - NULL, the closed sets, the guard core holds a plug
in - and tests/test_neutral_plug.py holds that a plug which always defers changes nothing in any
scenario. This holds each point where it stands in core, against the same real store, Codex home
and simulated backend the engine's scenarios use (tests/codexsim.py):

* nothing is asked while recovery is paused, and nothing about a record its conversation's
  switch or a cancel has stopped: the consent gate comes first;
* at the schedule and the gates, a plug is asked only once core's own gate has passed, and
  HOLD keeps the record waiting for one poll and nothing more;
* a failure core never recovers alone is put to it (P17, v0.6.13) only once that failure passed
  every check core makes of one, with what core would carry out; taken up, it is a core record
  of its own kind that known_failure puts to the plug again, and that ends unsent without it;
* its words go out only as a person's Custom message would; a channel it names gets the one
  send, after the one claim and the pre-send look, inside the launch guard;
* a continuation it asks to send with no marker (P15) goes through its channel under the client
  id core derives from the interruption, and is followed, taken back and proven by that id alone
  - and never sent twice, whatever becomes of the plug;
* its ledger is asked inside the claim, can refuse one and never grant one, and what it writes
  there commits with the claim or not at all - and the standard edition's is never asked;
* every move of a record the engine writes is told to it once written, a Pause's too, and
  never to NULL - so it learns what became of a record from core, not from the journal;
* a surface shows what it adds under one key, and nothing when it adds nothing; MCP offers its
  well-declared tools after core's and hands it the calls to them, checked as core's are; the start
  route's refusal and the launcher's exit code are what they were, whatever it answers.
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)        # codexsim and the engine's harness live next to this file

from codexsim import BASE, RESET  # noqa: E402
import srcscan  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_engine import T1, T2, TURN_A, EngineCase, archive, fail_turn  # noqa: E402
from test_ports import ENGINE_TO_STORE  # noqa: E402
from codex_auto_resume import (config, continuation, control, controlcli, diagnostics,  # noqa: E402
                               edition, ladder, managed, mcpserver, settings, startup, windows)
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.domain.plug import (DEFER, EXTRA, PACED_AS, Alternative, DamagedPlug,  # noqa: E402
                                           Guarded, Plug, PlugFailure, Point, Surface, guard)
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.engine.options import VIEW_READS  # noqa: E402
from codex_auto_resume.machine import STATES, WAITING  # noqa: E402
from codex_auto_resume.mcp.tools import TOOLS as MCP_TOOLS  # noqa: E402
from codex_auto_resume.runtime.app import App  # noqa: E402
from codex_auto_resume.store import Store  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLL = 60
# The gates core puts to the plug, in the order it does - each once core's own has passed.
ASKED_GATES = ("submission_safe", "known_failure", "chain_budget", "no_progress_budget",
               "thread_available", "attempt_budget", "usage")


class Asked(Plug):
    """A plug that remembers every question, and answers what it is told to at each hook -
    NULL's answer everywhere else. An answer that is an exception is raised."""
    __slots__ = ("asked", "answers")

    def __init__(self, **answers):
        self.asked, self.answers = [], answers

    def _answer(self, hook, *arguments):
        self.asked.append((hook, arguments))
        if hook in self.answers:
            answer = self.answers[hook]
            if isinstance(answer, Exception):
                raise answer
            return answer(*arguments) if callable(answer) else answer
        return getattr(Plug, hook)(self, *arguments)

    def records(self, view):
        return self._answer("records", view)

    def gate(self, name, record, facts):
        return self._answer("gate", name, record, facts)

    def text(self, record, text):
        return self._answer("text", record, text)

    def sender(self, record, backend):
        return self._answer("sender", record, backend)

    def outcome(self, record, outcome):
        return self._answer("outcome", record, outcome)

    def schedule(self, record, due):
        return self._answer("schedule", record, due)

    def tick(self, view):
        return self._answer("tick", view)

    def start_route(self, request):
        return self._answer("start_route", request)

    def surface(self, name, facts):
        return self._answer("surface", name, facts)

    def claim_ledger(self, connection, record, now, carried):
        return self._answer("claim_ledger", connection, record, now, carried)

    def partition(self, records):
        return self._answer("partition", records)

    def supervise(self, facts):
        return self._answer("supervise", facts)

    def moved(self, record, state):
        return self._answer("moved", record, state)

    def delivery(self, record):
        return self._answer("delivery", record)

    def unloaded(self, record):
        return self._answer("unloaded", record)

    def admission(self, failure):
        return self._answer("admission", failure)

    def wants(self, point):
        """Not a hook: what it is told to say, or NULL's False, and never written down as asked."""
        wanted = self.answers.get("wants", False)
        return wanted(point) if callable(wanted) else wanted

    def hooks(self):
        return [hook for hook, _ in self.asked]

    def gates(self):
        return [arguments[0] for hook, arguments in self.asked if hook == "gate"]


def attach(path, name):
    """An ATTACH of the file at `path` as `name`, which the statement names: the claim lets a
    ledger's ATTACH on only once it has read which file it is (store/ledger.py)."""
    return "ATTACH DATABASE '%s' AS %s" % (str(path).replace("'", "''"), name)


def holding(name):
    """Hold at gate `name` (or the schedule), and nowhere else."""
    if name == "schedule":
        return Asked(schedule=Alternative.HOLD)
    return Asked(gate=lambda gate, record, facts: Alternative.HOLD if gate == name else DEFER)


class PluggedCase(EngineCase):
    def plugged(self, plug, h=None):
        """The harness's engine, rebuilt with `plug`: everything else as the scenarios have it."""
        h = h or self.h
        h.engine = Engine(h.store, h.source, h.backend, clock=lambda: h.now,
                          log=lambda *args: h.logs.append(args), options=h.options,
                          notify=lambda *args: h.notifications.append(args), plug=plug)
        return h.engine

    def due(self, h=None):
        """A usage-limit failure, registered, with its reset past: due at the next tick."""
        self.ready_after_reset(h)


class ConsentFirstTests(PluggedCase):
    def test_a_paused_watcher_asks_the_plug_nothing(self):
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertEqual(plug.asked, [])
        self.assert_no_send()

    def test_a_conversation_switched_off_or_cancelled_is_never_put_to_the_plug(self):
        for stop in ("thread", "cancel"):
            with self.subTest(stop):
                h = self.fresh()
                self.due(h)
                if stop == "thread":
                    h.store.set_thread_enabled(T1, False, at=h.now)
                else:
                    h.store.cancel_interruption(h.record()["interruption_id"], h.now)
                plug = Asked()
                self.plugged(plug, h)
                h.tick()
                self.assertEqual(set(plug.hooks()) & {"schedule", "gate", "text", "sender",
                                                      "claim_ledger"}, set())
                self.assertEqual(h.backend.send_calls, [])


class GateTests(PluggedCase):
    def test_each_gate_is_asked_once_in_order_after_the_schedule(self):
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(plug.gates(), list(ASKED_GATES))
        order = plug.hooks()
        self.assertLess(order.index("schedule"), order.index("gate"))
        self.assertLess(order.index("gate"), order.index("text"))
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_gate_core_refuses_is_not_put_to_the_plug(self):
        """A gate core refuses is not asked about at all - known_failure for a record P17 took up
        aside, which is asked so the plug can take it up again (KnownFailureTests)."""
        self.h.home.fail_usage(T1)
        self.h.tick()
        self.h.now = RESET + 61                                    # due, but never loaded
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(plug.gates(), ["submission_safe", "known_failure", "chain_budget",
                                        "no_progress_budget"])
        self.assertEqual(self.h.record()["last_error"], "notLoaded")

    def test_hold_keeps_the_record_waiting_one_poll_as_it_was(self):
        for name in ("schedule",) + ASKED_GATES:
            with self.subTest(name):
                h = self.fresh()
                self.due(h)
                before = h.record()
                self.plugged(holding(name), h)
                h.tick()
                after = h.record()
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual((after["state"], after["last_error"], after["attempt_count"]),
                                 (before["state"], before["last_error"], before["attempt_count"]))
                self.assertEqual(after["next_retry_at"], h.now + POLL)
                self.assertEqual(json.loads(after["gate_eval"])[name], ["WAIT", "held"])
                # Not now is all it meant: the standard edition sends it at the next poll.
                self.plugged(None, h)
                h.tick(advance=POLL)
                self.assertEqual(len(h.backend.send_calls), 1)
                self.assertEqual(h.record()["state"], "queued")

    def test_a_plug_whose_every_hook_raises_is_the_standard_edition(self):
        sent = []
        for plug in (None, Asked(**{hook: RuntimeError("broken") for hook in (
                "records", "gate", "text", "sender", "outcome", "schedule", "tick",
                "claim_ledger", "partition", "moved")})):
            h = self.fresh()
            self.due(h)
            engine = self.plugged(plug, h)
            h.tick()
            self.follow(h)
            sent.append((h.backend.send_calls, h.record()["state"]))
            if plug is not None:
                self.assertGreater(engine.plug.failures, 5)
        self.assertEqual(sent[0], sent[1])
        self.assertEqual(sent[0][1], "recovered")


class WordsTests(PluggedCase):
    def test_words_that_pass_as_a_custom_message_are_sent_filled_in(self):
        self.due()
        self.plugged(Asked(text="Please go on with the {category} task."))
        self.h.tick()
        marker = self.h.record()["marker"]
        self.assertEqual(self.prompt(), "Please go on with the usage_limit task.\n\n" + marker)

    def test_words_that_fill_in_to_nothing_leave_the_persons_own_style(self):
        """A dropped connection has no reset time, so "{reset_time}" says nothing for it. A
        person's Custom message falls back to the Standard text there; the plug's words fall
        back to whatever the person chose, which here is Minimal."""
        minimal = dict(settings.defaults(), continuation_style="minimal")
        sent = []
        for plug in (None, Asked(text="{reset_time}")):
            h = self.fresh()
            engine = self.plugged(plug, h)
            engine.apply_policy(minimal)
            h.home.fail_transient(T1, TURN_A)
            h.backend.loaded_map[T1] = "loaded"
            h.tick()
            h.tick(advance=300)
            sent.append(h.backend.send_calls[0][1])
        self.assertEqual(sent[1], sent[0])
        record = h.record()
        self.assertEqual(sent[1], continuation.for_settings(record["category"], minimal, row=record,
                                                            limits=engine.limits())
                         + "\n\n" + record["marker"])

    def test_words_that_would_not_pass_leave_cores_own(self):
        standard = self.fresh()
        self.due(standard)
        standard.tick()
        expected = standard.backend.send_calls[0][1]
        for words in ("", "   ", "Tell {thread_title}", "{nonsense}", "x" * 2001, 42, None):
            with self.subTest(words=words if not isinstance(words, str) else words[:20]):
                h = self.fresh()
                self.due(h)
                self.plugged(Asked(text=words), h)
                h.tick()
                self.assertEqual(h.backend.send_calls[0][1], expected)


class Channel:
    """What a plug may name at P5: something with a `send`, called the way core calls its own."""

    def __init__(self, h):
        self.h, self.calls = h, []

    def send(self, thread_id, prompt, *, launch_guard=None):
        # Read on a connection of its own, as a transport outside core would.
        with contextlib.closing(sqlite3.connect(self.h.store.path)) as connection:
            state = connection.execute("SELECT state FROM interruptions WHERE thread_id=?",
                                       (thread_id,)).fetchone()[0]
        with launch_guard as permitted:
            self.calls.append((thread_id, prompt, permitted, state))
        return {"outcome": "unknown"}


class Careless:
    """A channel that sends without entering the launch guard it is handed."""

    def __init__(self):
        self.calls = []

    def send(self, thread_id, prompt, *, launch_guard=None):
        self.calls.append(thread_id)
        return {"outcome": "accepted", "queue_id": None}


class SenderTests(PluggedCase):
    def test_a_channel_gets_the_one_send_after_the_claim_inside_the_launch_guard(self):
        self.due()
        channel = Channel(self.h)
        self.plugged(Asked(sender=channel))
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(len(channel.calls), 1)
        thread_id, prompt, permitted, state = channel.calls[0]
        self.assertEqual((thread_id, permitted, state), (T1, True, "submitting"))
        self.assertTrue(prompt.endswith(self.h.record()["marker"]))
        self.assertEqual(self.h.record()["state"], "submission_unknown")

    def test_the_pre_send_look_still_stops_a_channel(self):
        self.due()
        channel = Channel(self.h)
        engine = self.plugged(Asked(sender=channel))
        engine.presend_problem = lambda claim: ("waiting_retry", "released_before_send", POLL)
        self.h.tick()
        self.assertEqual(channel.calls, [])
        self.assertEqual(self.h.record()["state"], "waiting_retry")

    def test_a_channel_that_never_enters_the_guard_is_held_to_it_all_the_same(self):
        """A Pause that commits after the claim stops core's backend at its launch guard. A
        channel is only handed the guard; one that never entered it sent anyway. Core enters it
        for the channel, so the Pause stops both alike."""
        seen = {}
        for label in ("backend", "careless channel"):
            h = self.fresh()
            self.due(h)
            careless = Careless()
            engine = self.plugged(Asked(sender=careless) if label != "backend" else None, h)
            looked = engine.presend_problem

            def presend(claim, _h=h, _looked=looked):
                problem = _looked(claim)
                _h.store.set_enabled(False, _h.now)            # the person pauses right here
                return problem
            engine.presend_problem = presend
            h.tick()
            seen[label] = (len(h.backend.send_calls) + len(careless.calls), h.record()["state"],
                           h.record()["attempt_count"])
        self.assertEqual(seen["careless channel"], seen["backend"])
        self.assertEqual(seen["backend"][0], 0)

    def test_the_hook_is_never_handed_cores_backend(self):
        """Handed the live backend, a hook could rebind its `send` and answer DEFER, or answer
        the backend itself: the send went through the rebound method outside the launch guard,
        so a Pause after the claim did not stop it, and the claim was told it carried nothing of
        the plug's, so the ledger neither paid nor held. The hook is handed BACKEND instead."""
        seen, handed = {}, []
        for label in ("backend", "deferred", "answered"):
            h = self.fresh()
            self.due(h)
            careless = Careless()

            def sender(record, backend, _careless=careless, _label=label, _h=h):
                handed.append((backend, _h.backend))
                with contextlib.suppress(AttributeError):
                    backend.send = _careless.send            # wrap core's backend, carelessly
                return DEFER if _label == "deferred" else backend
            engine = self.plugged(Asked(sender=sender) if label != "backend" else None, h)
            looked = engine.presend_problem

            def presend(claim, _h=h, _looked=looked):
                problem = _looked(claim)
                _h.store.set_enabled(False, _h.now)            # the person pauses right here
                return problem
            engine.presend_problem = presend
            h.tick()
            seen[label] = (len(h.backend.send_calls) + len(careless.calls), h.record()["state"])
        self.assertEqual(seen["deferred"], seen["backend"])
        self.assertEqual(seen["answered"], seen["backend"])
        self.assertEqual(seen["backend"][0], 0)
        self.assertEqual(len(handed), 2)
        for given, backend in handed:
            self.assertIsNot(given, backend)

    def test_a_channel_sends_with_the_stores_write_lock_let_go(self):
        """Core reads consent for a channel under the store's write lock, and lets it go before
        the channel is called, as its backend does once it has launched. Held across the whole
        send, it kept a Pause from the settings window or the MCP server waiting on a transport
        core cannot see into, and past SQLite's ten seconds the Pause failed with recovery on."""
        self.due()
        writable = []

        class Pausing:
            def send(self, thread_id, prompt, *, launch_guard=None):
                with contextlib.closing(sqlite3.connect(path, timeout=0, isolation_level=None)) as other:
                    try:
                        other.execute("BEGIN IMMEDIATE")             # what a Pause takes first
                        other.execute("ROLLBACK")
                        writable.append(True)
                    except sqlite3.OperationalError:
                        writable.append(False)
                return {"outcome": "unknown"}
        path = self.h.store.path
        self.plugged(Asked(sender=Pausing()))
        self.h.tick()
        self.assertEqual(writable, [True])
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "submission_unknown")

    def test_what_is_not_a_channel_leaves_the_backend(self):
        self.due()
        self.plugged(Asked(sender="the app server"))
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)


class QueueAdd:
    """A channel as the advanced edition's marker-free continuation is one (P15): it puts the words
    into Codex's queue under the client id core hands it - codexsim's queue, here, as
    thread/queue/add does in Codex - and the desktop app starts them at once or leaves them queued.
    `outcome` is what it reports: accepted, unknown (nothing queued, or `queued` anyway), or
    not_started."""

    def __init__(self, h, *, outcome="accepted", queued=True, dispatch=True, client=None):
        self.h, self.outcome, self.queued, self.dispatch, self.client = h, outcome, queued, dispatch, client
        self.calls = []

    def send(self, thread_id, prompt, *, launch_guard=None, client_id=None):
        with launch_guard as permitted:
            self.calls.append((thread_id, prompt, client_id, permitted))
        if self.outcome == "not_started":
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        queue_id = None
        if self.queued:
            queue_id = self.h.home.enqueue(thread_id, prompt, client_id=self.client or client_id)
            if self.dispatch:
                self.h.home.dispatch(thread_id)
        if self.outcome == "accepted":
            return {"outcome": "accepted", "queue_id": queue_id}
        return {"outcome": "unknown"}


class DeliveryTests(PluggedCase):
    """P15: the marker, as core has always carried a continuation - or, where the plug asks for it
    and names a channel, no marker and the client id core derives from the interruption, which
    everything that follows the send looks for instead."""

    def marker_free(self, channel):
        return Asked(sender=channel, delivery=Alternative.CLIENT_ID)

    def test_no_marker_goes_out_under_the_derived_id_and_that_id_proves_it_arrived(self):
        self.due()
        key = self.h.record()["interruption_id"]
        channel = QueueAdd(self.h)
        self.plugged(self.marker_free(channel))
        self.h.tick()
        self.assert_no_send()
        ((thread_id, prompt, client_id, permitted),) = channel.calls
        self.assertEqual((thread_id, client_id, permitted), (T1, ids.continuation_client_id(key), True))
        self.assertNotIn(ids.MARKER_PREFIX, prompt)
        self.assertEqual(self.h.record()["recovery_client_id"], client_id)
        ours = self.h.turn_ids()[-1]
        self.follow()
        row = self.h.record()
        self.assertEqual((row["state"], row["recovery_turn_id"]), ("recovered", ours))
        self.h.tick(advance=3600)
        self.assertEqual(len(channel.calls), 1, "a recovered interruption is never resent")

    def test_the_same_interruption_always_has_the_same_id_and_another_never_does(self):
        self.assertEqual(ids.continuation_client_id("a" * 64), ids.continuation_client_id("a" * 64))
        self.assertNotEqual(ids.continuation_client_id("a" * 64), ids.continuation_client_id("b" * 64))
        made = ids.continuation_client_id("a" * 64)
        self.assertTrue(ids.is_uuid(made) and ids.is_client_id(made) and ids.is_delivery_proof(made))
        self.assertFalse(ids.is_delivery_proof("a"))

    def test_without_a_channel_it_is_the_marker_core_has_always_sent(self):
        """Core's own backend is `codex queue`, which takes no client id."""
        self.due()
        self.plugged(Asked(delivery=Alternative.CLIENT_ID))
        self.h.tick()
        row = self.h.record()
        self.assertTrue(self.prompt().endswith(row["marker"]))
        self.assertNotEqual(row["recovery_client_id"], ids.continuation_client_id(row["interruption_id"]))
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_any_other_answer_is_the_marker(self):
        for answer in (DEFER, Alternative.HOLD, "client_id ", "marker_free", object()):
            with self.subTest(answer=answer):
                h = self.fresh()
                self.due(h)
                channel = QueueAdd(h)
                self.plugged(Asked(sender=channel, delivery=answer), h)
                h.tick()
                ((_thread, prompt, client_id, _permitted),) = channel.calls
                self.assertIsNone(client_id)
                self.assertTrue(prompt.endswith(h.record()["marker"]))

    def test_the_ledger_is_told_the_send_carries_the_plugs_way_of_carrying_it(self):
        self.due()
        told = []

        def claim_ledger(connection, record, now, carried):
            told.append(carried)
            return DEFER
        plug = Asked(sender=QueueAdd(self.h), delivery=Alternative.CLIENT_ID, claim_ledger=claim_ledger)
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(told, [frozenset({Point.SENDER, Point.DELIVERY})])

    def test_an_uncertain_marker_free_send_is_held_as_the_marker_path_holds_one_and_never_resent(self):
        """The app server refused, timed out, or the item never showed: no id to find, so the
        record is an uncertain submission - told to the plug as one - and nothing sends it again."""
        self.due()
        channel = QueueAdd(self.h, outcome="unknown", queued=False)
        plug = self.marker_free(channel)
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.assertIn(("moved", "submission_unknown"),
                      [(hook, arguments[1]) for hook, arguments in plug.asked if hook == "moved"])
        for _ in range(12):
            self.h.tick(advance=900)
        self.assertEqual(len(channel.calls), 1)
        self.assert_no_send()
        self.assertEqual(self.h.record()["state"], "submission_unknown")

    def test_one_the_watch_finds_queued_by_its_id_after_an_unknown_answer_is_followed(self):
        self.due()
        channel = QueueAdd(self.h, outcome="unknown", dispatch=False)
        self.plugged(self.marker_free(channel))
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "submission_unknown")
        self.h.watch(advance=1)
        row = self.h.record()
        self.assertEqual(self.h.home.queued(T1), [row["queue_id"]])
        self.h.home.dispatch(T1)
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assertEqual(len(channel.calls), 1)

    def test_a_message_under_another_client_id_is_not_ours(self):
        """Only the id proves it: an item Codex holds under another client id is not our send."""
        self.due()
        channel = QueueAdd(self.h, dispatch=False, client=ids.continuation_client_id("f" * 64))
        self.plugged(self.marker_free(channel))
        self.h.tick()
        self.h.watch(advance=1)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("handed_over", "queued_item_edited"))
        self.assertEqual(len(channel.calls), 1)

    def test_a_pause_takes_a_marker_free_item_back_by_its_id(self):
        self.due()
        channel = QueueAdd(self.h, dispatch=False)
        self.plugged(self.marker_free(channel))
        self.h.tick()
        queued = self.h.home.queued(T1)
        self.assertEqual(len(queued), 1)
        self.h.store.set_enabled(False, self.h.now)
        self.h.watch(advance=1)
        self.assertEqual(self.h.backend.deleted, [(T1, queued[0])])
        self.assertEqual(self.h.record()["state"], "withdrawn_unconfirmed")

    def test_given_back_unsent_it_goes_by_its_marker_next_time_with_the_id_taken_away(self):
        self.due()
        channel = QueueAdd(self.h, outcome="not_started")
        self.plugged(self.marker_free(channel))
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "waiting_retry")
        self.assertEqual(row["recovery_client_id"], ids.continuation_client_id(row["interruption_id"]))
        self.plugged(None)
        self.h.now = max(row["next_retry_at"], self.h.now + 901)     # past the retry and the cooldown
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(row["marker"]))
        self.assertNotEqual(self.h.record()["recovery_client_id"],
                            ids.continuation_client_id(row["interruption_id"]))
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_the_standard_edition_follows_a_marker_free_send_it_did_not_make_and_sends_nothing(self):
        """EditionRoundTrip, core's half: sent with no marker, then the plug is gone - the standard
        edition's engine on the same state follows the record by the id it holds, to its end, and
        sends nothing of its own."""
        self.due()
        channel = QueueAdd(self.h, dispatch=False)
        self.plugged(self.marker_free(channel))
        self.h.tick()
        self.assertEqual(self.h.record()["state"], "queued")
        self.plugged(None)
        self.h.watch(advance=1)
        self.assertEqual(self.h.record()["state"], "queued")
        self.h.home.dispatch(T1)
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.h.tick(advance=3600)
        self.assert_no_send()
        self.assertEqual(len(channel.calls), 1)

    def test_a_copy_with_the_marker_already_there_stops_a_marker_free_send(self):
        """One with the marker already in Codex is the same continuation: never sent again with none."""
        self.due()
        row = self.h.record()
        self.h.home.add_item(T1, TURN_A, "userMessage", "go on " + row["marker"])
        channel = QueueAdd(self.h)
        self.plugged(self.marker_free(channel))
        self.h.tick()
        self.assertEqual(channel.calls, [])
        self.assertEqual((self.h.record()["state"], self.h.record()["last_error"]),
                         ("superseded", "duplicate_owner"))


class Resume:
    """A route as the advanced edition's goal continuation is one (P16): asked to continue a
    conversation the app does not hold, it reports what came of it - accepted, not_started or
    unknown - or raises. It sends nothing and queues nothing."""

    def __init__(self, outcome="accepted", before=None):
        self.outcome, self.calls, self.looks = outcome, [], []
        # Called as the route's session would start, before its look (the app opening the
        # conversation in those seconds, say).
        self.before = before

    def resume(self, thread_id, *, launch_guard=None, still_unloaded=None):
        with launch_guard as permitted:
            self.calls.append((thread_id, permitted))
        if self.before is not None:
            self.before()
        self.looks.append(still_unloaded())
        if self.looks[-1] is not True:
            return {"outcome": "not_started", "error_code": "queue_preflight_failed"}
        if self.outcome == "raise":
            raise RuntimeError("the route broke")
        if self.outcome == "not_started":
            return {"outcome": "not_started", "error_code": "queue_spawn_failed"}
        return {"outcome": self.outcome}


class UnloadedTests(PluggedCase):
    """P16: a conversation the app does not hold waits for it to be opened (A11) - unless the plug
    names a route, which core carries out as it carries out a send: every gate a send passes, the
    one claim the plug's ledger pays for, the pre-send look, and the route called once inside the
    launch guard. Nothing is queued, so nothing is watched; what came of it is settled here."""

    def due_unloaded(self, h=None):
        """A usage-limit failure whose reset has passed, in a conversation the app does not hold."""
        self.ready_after_reset(h, loaded=False)

    def test_deferring_it_waits_for_the_app_to_open_it_as_it_always_did(self):
        self.due_unloaded()
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.assert_no_send()
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"], row["attempt_count"]),
                         ("waiting_for_loaded_thread", "notLoaded", 0))
        self.assertEqual(json.loads(row["gate_eval"])["thread_available"], ["WAIT", "notLoaded"])
        self.assertEqual([arguments[0]["interruption_id"] for hook, arguments in plug.asked
                          if hook == "unloaded"], [row["interruption_id"]])

    def test_a_route_is_carried_out_once_after_the_claim_inside_the_launch_guard(self):
        self.due_unloaded()
        route = Resume()
        plug = Asked(unloaded=route)
        self.plugged(plug)
        self.h.tick()
        self.assert_no_send()
        self.assertEqual(route.calls, [(T1, True)])
        self.assertEqual(self.h.home.queued(T1), [], "a route queues nothing")
        row = self.h.record()
        # Accepted: it waits again, its claim counted - never given back.
        self.assertEqual((row["state"], row["last_error"], row["submitted_at"], row["attempt_count"]),
                         ("waiting_retry", "notLoaded", None, 1))
        self.assertIsNotNone(row["last_claim_at"])
        self.assertEqual(row["chain_continuations"], 1)
        self.assertEqual(json.loads(row["gate_eval"])["thread_available"], ["PASS", "plugged"])
        hooks = plug.hooks()
        self.assertLess(hooks.index("unloaded"), hooks.index("claim_ledger"))
        # A route is not words, a channel or a way of carrying them: none of those is asked.
        self.assertEqual(set(hooks) & {"text", "sender", "delivery"}, set())
        self.assertIn("submitting", [arguments[1] for hook, arguments in plug.asked if hook == "moved"])

    def test_the_ledger_is_told_the_claim_carries_the_route(self):
        self.due_unloaded()
        told = []

        def claim_ledger(connection, record, now, carried):
            told.append(carried)
            return DEFER
        self.plugged(Asked(unloaded=Resume(), claim_ledger=claim_ledger))
        self.h.tick()
        self.assertEqual(told, [frozenset({Point.UNLOADED})])

    def test_a_ledger_that_holds_the_claim_calls_no_route(self):
        self.due_unloaded()
        route = Resume()
        self.plugged(Asked(unloaded=route, claim_ledger=Alternative.HOLD))
        self.h.tick()
        self.assertEqual(route.calls, [])
        row = self.h.record()
        self.assertEqual((row["attempt_count"], row["submitted_at"]), (0, None))

    def test_once_resumed_the_conversations_own_next_turn_supersedes_it_and_nothing_is_sent(self):
        self.due_unloaded()
        route = Resume()
        self.plugged(Asked(unloaded=route))
        self.h.tick()
        # The app opens the conversation, and what the route set going carries it on.
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.home.add_turn(T1, status="inProgress")
        self.h.tick(advance=61)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("superseded_by_user", "later_turn_exists"))
        self.assert_no_send()
        self.assertEqual(len(route.calls), 1)

    def test_with_the_plug_gone_the_standard_edition_sends_only_what_it_would(self):
        """EditionRoundTrip, core's half: resumed through a route, then the plug is gone. The
        standard edition's engine waits for the app as it always does, keeps the claim's cooldown,
        and - nothing having carried the conversation on - sends the one continuation it would."""
        self.due_unloaded()
        self.plugged(Asked(unloaded=Resume()))
        self.h.tick()
        self.plugged(None)
        self.h.tick(advance=61)
        self.assertEqual(self.h.record()["last_error"], "notLoaded")
        self.h.backend.loaded_map[T1] = "loaded"
        self.h.tick(advance=61)
        self.assertEqual(self.h.record()["last_error"], "thread_submission_cooldown")
        self.assert_no_send()
        self.h.tick(advance=901)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertTrue(self.prompt().endswith(self.h.record()["marker"]))

    def test_a_route_that_never_started_gives_the_claim_back_and_keeps_its_time(self):
        self.due_unloaded()
        route = Resume("not_started")
        self.plugged(Asked(unloaded=route))
        self.h.tick()
        row = self.h.record()
        self.assertIn(row["state"], WAITING)
        self.assertEqual((row["last_error"], row["submitted_at"], row["chain_continuations"]),
                         ("released_before_send", None, 0))
        self.assertIsNotNone(row["last_claim_at"])
        self.h.tick(advance=61)
        self.assertEqual(len(route.calls), 1, "the claim's time still counts for the cooldown")
        self.assertEqual(self.h.record()["last_error"], "thread_submission_cooldown")

    def test_an_uncertain_route_is_held_and_never_tried_again(self):
        for outcome in ("unknown", "raise", "strange"):
            with self.subTest(outcome):
                h = self.fresh()
                self.due_unloaded(h)
                route = Resume(outcome)
                plug = Asked(unloaded=route)
                self.plugged(plug, h)
                h.tick()
                row = h.record()
                self.assertEqual((row["state"], row["last_error"]),
                                 ("submission_unknown", "queue_result_unknown_do_not_resend"))
                self.assertIn("submission_unknown",
                              [arguments[1] for hook, arguments in plug.asked if hook == "moved"])
                h.backend.loaded_map[T1] = "loaded"
                for _ in range(12):
                    h.tick(advance=900)
                self.assertEqual(len(route.calls), 1)
                self.assertEqual(h.backend.send_calls, [])

    def test_a_pause_that_commits_after_the_pre_send_look_stops_the_route_at_the_guard(self):
        self.due_unloaded()
        route = Resume()
        self.plugged(Asked(unloaded=route))
        look = Engine.presend_problem

        def look_then_pause(engine, claim):
            found = look(engine, claim)
            engine.store.set_enabled(False, engine.clock())
            return found
        with patch.object(Engine, "presend_problem", look_then_pause):
            self.h.tick()
        self.assertEqual(route.calls, [], "the route is never called once consent has gone")
        row = self.h.record()
        self.assertIn(row["state"], WAITING)
        self.assertEqual((row["last_error"], row["submitted_at"]), ("released_before_send", None))

    def test_it_is_asked_only_where_core_would_wait_for_the_app_and_consent_holds(self):
        cases = {
            "the app cannot say": lambda h: h.backend.loaded_map.__setitem__(T1, "unknown"),
            "observe only": lambda h: h.store.set_observe_only(True),
            "conversation off": lambda h: h.store.set_thread_enabled(T1, False, at=h.now),
            "loaded": lambda h: h.backend.loaded_map.__setitem__(T1, "loaded"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                h = self.fresh()
                self.due_unloaded(h)
                change(h)
                route = Resume()
                plug = Asked(unloaded=route)
                self.plugged(plug, h)
                h.tick()
                self.assertNotIn("unloaded", plug.hooks())
                self.assertEqual(route.calls, [])

    def test_a_conversation_opened_before_the_claim_is_not_resumed(self):
        """The route is for a conversation the app does not hold, rechecked under the dispatch lock."""
        self.due_unloaded()
        route = Resume()

        def opened(record):
            self.h.backend.loaded_map[T1] = "loaded"
            return route
        self.plugged(Asked(unloaded=opened))
        self.h.tick()
        self.assertEqual(route.calls, [])
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]),
                         ("waiting_for_loaded_thread", "loaded_recheck_failed"))

    def test_the_route_is_handed_cores_own_look_made_again_when_it_asks(self):
        """A route's session takes seconds to start, and the app may open the conversation in
        them. The route is handed core's look - the app that was checked still there, and saying
        notLoaded now, never the cached answer - to ask at its last moment; a route that finds the
        app holds the conversation changes nothing, and its claim is given back."""
        def app_opens_it(h):
            h.backend.loaded_map[T1] = "loaded"

        def new_app(h):
            h.backend.app = dict(h.backend.app, pid=h.backend.app.get("pid", 0) + 1)

        def look_breaks(h):
            h.backend.loaded = lambda *arguments: (_ for _ in ()).throw(OSError("gone"))

        for name, change, seen in (("still not held", None, True), ("the app opened it", app_opens_it, False),
                                   ("another app", new_app, False), ("a look that fails", look_breaks, False)):
            with self.subTest(name):
                h = self.fresh()
                self.due_unloaded(h)
                route = Resume(before=None if change is None else (lambda h=h, change=change: change(h)))
                self.plugged(Asked(unloaded=route), h)
                h.tick()
                self.assertEqual((route.calls, route.looks), ([(T1, True)], [seen]))
                row = h.record()
                if seen:
                    self.assertEqual((row["state"], row["last_error"], row["attempt_count"]),
                                     ("waiting_retry", "notLoaded", 1))
                    continue
                self.assertIn(row["state"], WAITING)
                self.assertEqual((row["last_error"], row["submitted_at"], row["chain_continuations"]),
                                 ("released_before_send", None, 0))
                self.assertEqual(h.backend.send_calls, [])

    def test_the_gates_that_follow_still_hold(self):
        cases = {
            "someone's queued input": lambda h: h.home.enqueue(T1, "mine"),
            "no usage": lambda h: h.backend.usage_result.update(available=False, reason="unavailable"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                h = self.fresh()
                self.due_unloaded(h)
                change(h)
                route = Resume()
                self.plugged(Asked(unloaded=route), h)
                h.tick()
                self.assertEqual(route.calls, [])
                row = h.record()
                self.assertIsNone(row["submitted_at"])
                self.assertIn(row["last_error"], ("user_input_queued", "usage_unavailable"))

    def test_what_is_not_a_route_is_the_wait(self):
        class Lookup:
            @property
            def resume(self):
                raise RuntimeError("no")
        for answer in ("resume", 1, object(), Lookup(), Careless(), type("N", (), {"resume": 2})()):
            with self.subTest(answer=type(answer).__name__):
                h = self.fresh()
                self.due_unloaded(h)
                self.plugged(Asked(unloaded=answer), h)
                h.tick()
                row = h.record()
                self.assertEqual((row["state"], row["last_error"], row["attempt_count"]),
                                 ("waiting_for_loaded_thread", "notLoaded", 0))

    def test_a_hook_that_raises_is_the_wait(self):
        self.due_unloaded()
        self.plugged(Asked(unloaded=RuntimeError("broke")))
        self.h.tick()
        self.assertEqual(self.h.record()["last_error"], "notLoaded")
        self.assertEqual(self.h.engine.plug.failures, 1)

class ProofReaderTests(PluggedCase):
    """The history reader looks for a proof - a marker, or a continuation's client id - and for
    nothing wider: what it is handed bounds the only message text that ever leaves Codex's
    database to our own continuation's."""

    def test_a_client_id_is_found_on_the_message_and_not_in_its_words(self):
        cid = ids.continuation_client_id("c" * 64)
        self.h.home.add_turn(T1, user_text="about " + cid)                    # quoted, not ours
        turn = self.h.home.add_turn(T1, user_text="please go on", client_id=cid)
        found = self.h.source.marker_rows(T1, cid)
        self.assertEqual([row["turn_id"] for row in found], [turn])
        self.assertEqual(found[0]["client_id"], cid)
        self.h.home.enqueue(T1, "and " + cid)                                 # quoted, not ours
        queued = self.h.home.enqueue(T1, "please go on", client_id=cid)
        self.assertEqual([row["id"] for row in self.h.source.queued_rows(T1, cid)], [queued])

    def test_nothing_wider_than_a_proof_is_looked_for(self):
        for wrong in ("a", "", "codex", T1, "[codex-auto-resume:zz]", None, 7):
            with self.subTest(wrong=wrong):
                with self.assertRaises(Exception):
                    self.h.source.marker_rows(T1, wrong)
                with self.assertRaises(Exception):
                    self.h.source.marker_presence(T1, wrong)


class LedgerTests(PluggedCase):
    def ledger(self, answer, *, fail=False):
        """A ledger in a database of its own, attached to the claim's connection."""
        path = str(Path(self.root).parent / "ledger.sqlite")

        def claim_ledger(connection, record, now, carried):
            if "ledger" not in [row[1] for row in connection.execute("PRAGMA database_list")]:
                connection.execute(attach(path, "ledger"))
            connection.execute("CREATE TABLE IF NOT EXISTS ledger.spent (id TEXT, at REAL)")
            connection.execute("INSERT INTO ledger.spent VALUES (?, ?)", (record["interruption_id"], now))
            if fail:
                raise OSError("the ledger broke after writing")
            return answer

        return path, Asked(claim_ledger=claim_ledger)

    def spent(self, path):
        with contextlib.closing(sqlite3.connect(path)) as connection:
            try:
                return connection.execute("SELECT count(*) FROM spent").fetchone()[0]
            except sqlite3.OperationalError:
                return 0

    def test_a_granted_claim_commits_what_the_ledger_wrote_with_it(self):
        self.due()
        path, plug = self.ledger(DEFER)
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.spent(path), 1)

    def test_hold_refuses_the_claim_and_takes_back_what_the_ledger_wrote(self):
        self.due()
        before = self.h.record()
        path, plug = self.ledger(Alternative.HOLD)
        self.plugged(plug)
        self.h.tick()
        after = self.h.record()
        self.assert_no_send()
        self.assertEqual((after["state"], after["last_error"], after["attempt_count"],
                          after["submitted_at"]),
                         (before["state"], before["last_error"], 0, None))
        self.assertEqual(json.loads(after["gate_eval"])["submission_safe"], ["WAIT", "held"])
        self.assertEqual(after["next_retry_at"], self.h.now + POLL)
        self.assertEqual(self.spent(path), 0)

    def test_a_ledger_that_breaks_costs_its_writes_and_not_the_claim(self):
        self.due()
        path, plug = self.ledger(Alternative.HOLD, fail=True)
        engine = self.plugged(plug)
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.spent(path), 0)
        self.assertEqual(engine.plug.failures, 1)

    def test_a_ledger_can_write_its_own_database_and_nothing_of_cores(self):
        """Handed the claim's connection, a ledger that defers could have switched a conversation
        or recovery back on, and it would have committed with the claim: granted, not refused.
        Every write, schema change and transaction statement outside its own database is refused
        while it is asked, and what it was handed is dead once it has answered."""
        self.due()
        self.h.store.set_thread_enabled(T2, False, at=self.h.now)
        path = str(Path(self.root).parent / "ledger.sqlite")
        attempts = ("UPDATE threads SET enabled=1", "UPDATE settings SET enabled=1",
                    "DELETE FROM interruptions", "INSERT INTO threads VALUES ('x', 1, 0)",
                    "CREATE TABLE main.extra (x)", "CREATE TEMP TABLE scratch (x)",
                    "CREATE TEMP TRIGGER t AFTER UPDATE ON main.interruptions "
                    "BEGIN UPDATE main.threads SET enabled=1; END",
                    "PRAGMA foreign_keys=OFF", "PRAGMA main.user_version=99",
                    "RELEASE claim_ledger", "ROLLBACK TO claim_ledger", "COMMIT", "BEGIN",
                    "DETACH DATABASE ledger")
        done, kept = [], []

        def claim_ledger(connection, record, now, carried):
            kept.append(connection)
            connection.execute(attach(path, "ledger"))
            connection.execute("CREATE TABLE IF NOT EXISTS ledger.spent (id TEXT)")
            connection.execute("INSERT INTO ledger.spent VALUES (?)", (record["interruption_id"],))
            self.assertEqual([row[1] for row in connection.execute("PRAGMA database_list")][-1], "ledger")
            for statement in attempts:
                try:
                    connection.execute(statement)
                    done.append(statement)
                except sqlite3.DatabaseError:
                    pass
            return DEFER
        engine = self.plugged(Asked(claim_ledger=claim_ledger))
        self.h.tick()
        self.assertEqual(done, [])
        self.assertEqual(engine.plug.failures, 0, "the ledger caught its refusals and deferred")
        self.assertFalse(self.h.store.thread_enabled(T2))
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.spent(path), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            kept[0].execute("UPDATE threads SET enabled=1")
        # The claim's connection is core's again: its own writes go through.
        self.h.store.set_thread_enabled(T2, True, at=self.h.now)
        self.assertTrue(self.h.store.thread_enabled(T2))

    def test_a_ledger_attaches_no_file_the_connection_has_already(self):
        """Nothing a ledger attaches can be detached. Core's own state.sqlite attached again
        under another name stayed, and needed a second write lock on its own file: every write
        transaction core began afterwards - the send the claim had just granted included - waited
        ten seconds and failed. The ledger's own file twice is the same, and a name the
        statement binds or computes cannot be read to tell which file it is."""
        self.due()
        path = Path(self.root).parent / "ledger.sqlite"
        linked = Path(self.root).parent / "linked.sqlite"
        done = []

        def claim_ledger(connection, record, now, carried):
            main = [row[2] for row in connection.execute("PRAGMA database_list") if row[1] == "main"][0]
            connection.execute(attach(path, "ledger"))
            os.link(main, linked)
            for statement, parameters in (
                    (attach(main, "again"), ()), (attach(main.upper(), "shouting"), ()),
                    (attach(linked, "linked"), ()), (attach(path, "twice"), ()),
                    ("ATTACH DATABASE ? AS bound", (str(Path(self.root).parent / "other.sqlite"),)),
                    ("ATTACH DATABASE ? || '.sqlite' AS computed",
                     (str(Path(self.root).parent / "other"),))):
                try:
                    connection.execute(statement, parameters)
                    done.append(statement)
                except sqlite3.DatabaseError:
                    pass
            return DEFER
        self.plugged(Asked(claim_ledger=claim_ledger))
        self.h.tick()
        self.assertEqual(done, [])
        names = [row[1] for row in self.h.store._connection.execute("PRAGMA database_list")]
        self.assertEqual([name for name in names if name not in ("main", "temp")], ["ledger"])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.h.record()["state"], "queued")
        self.h.store.set_thread_enabled(T2, False, at=self.h.now)
        self.assertFalse(self.h.store.thread_enabled(T2))

    def test_a_ledger_sets_no_pragma_even_through_its_own_schema(self):
        """`PRAGMA ledger.query_only=1` was judged by the schema it names, but query_only, like
        busy_timeout, trusted_schema and writable_schema, is the whole connection's - core's,
        which lives as long as the watcher. Set through the ledger's own schema it outlived the
        claim: query_only failed the claim and every later write of core's. It reads them."""
        self.due()
        path = str(Path(self.root).parent / "ledger.sqlite")
        flags = ("query_only", "ignore_check_constraints", "trusted_schema", "recursive_triggers",
                 "reverse_unordered_selects", "busy_timeout", "writable_schema", "foreign_keys")
        connection = self.h.store._connection
        before = {flag: connection.execute("PRAGMA %s" % flag).fetchone()[0] for flag in flags}
        done, read = [], []

        def claim_ledger(connection, record, now, carried):
            connection.execute(attach(path, "ledger"))
            for statement in ["PRAGMA ledger.%s=%d" % (flag, 0 if flag == "busy_timeout" else 1)
                              for flag in flags if flag != "query_only"] + [
                              "PRAGMA ledger.case_sensitive_like=1", "PRAGMA ledger.user_version=7",
                              "PRAGMA ledger.journal_mode=OFF", "PRAGMA ledger.query_only=1"]:
                try:
                    connection.execute(statement)
                    done.append(statement)
                except sqlite3.DatabaseError:
                    pass
            read.append(connection.execute("PRAGMA ledger.user_version").fetchone()[0])
            read.append(len(connection.execute("PRAGMA table_info(threads)").fetchall()) > 0)
            return DEFER
        self.plugged(Asked(claim_ledger=claim_ledger))
        self.h.tick()
        self.assertEqual(done, [])
        self.assertEqual(read, [0, True])
        self.assertEqual({flag: connection.execute("PRAGMA %s" % flag).fetchone()[0] for flag in flags},
                         before)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.h.store.set_thread_enabled(T2, False, at=self.h.now)
        self.assertFalse(self.h.store.thread_enabled(T2))

    def test_a_ledger_cannot_keep_what_it_was_handed_alive(self):
        """The handle's `close` was an attribute of the handle, so a ledger that set it to a
        no-op kept a live connection past its answer - with the authorizer gone - and wrote
        core's tables with it. Nothing can be set on the handle, and what ends it is the
        claim's own."""
        self.due()
        self.h.store.set_thread_enabled(T2, False, at=self.h.now)
        kept = []

        def claim_ledger(connection, record, now, carried):
            with contextlib.suppress(AttributeError):
                connection.close = lambda: None
            kept.append(connection)
            return DEFER
        self.plugged(Asked(claim_ledger=claim_ledger))
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            kept[0].execute("UPDATE threads SET enabled=1")
        self.assertFalse(self.h.store.thread_enabled(T2))
        for name in ("close", "_execute", "execute", "extra"):
            with self.subTest(name), self.assertRaises(AttributeError):
                setattr(kept[0], name, None)

    def test_the_ledger_is_told_which_of_the_plugs_answers_the_send_carries(self):
        """As the dispatch decided them: its words, its channel, or neither - and not words that
        fill in to nothing for the record, {reset_time} on a failure with no reset, which core
        drops for the person's own style. A ledger that paid by its own list of what it had
        answered charged for those, and held a claim of core's own words when it broke."""
        channel = Channel(None)
        for label, answers, expected in (
                ("words", {"text": "Please go on with the {category} task."}, {Point.TEXT}),
                ("channel", {"sender": channel}, {Point.SENDER}),
                ("both", {"text": "Please go on.", "sender": channel}, {Point.TEXT, Point.SENDER}),
                ("neither", {}, set()), ("dropped words", {"text": "{reset_time}"}, set())):
            with self.subTest(label):
                h = self.fresh()
                if label == "dropped words":
                    h.home.fail_transient(T1, TURN_A)
                    h.backend.loaded_map[T1] = "loaded"
                    h.tick()
                else:
                    self.due(h)
                channel.h, told = h, []

                def claim_ledger(connection, record, now, carried, _told=told):
                    _told.append(carried)
                    return DEFER
                self.plugged(Asked(claim_ledger=claim_ledger, **answers), h)
                h.tick(advance=300 if label == "dropped words" else 0)
                self.assertEqual(told, [frozenset(expected)])

    def test_a_ledger_that_breaks_holds_a_claim_that_carries_the_plugs_words_or_channel(self):
        """What the plug's words or its channel cost is paid in its ledger, before the claim is
        granted. A ledger that raised paid nothing, so what it would have paid for is not sent;
        a claim of core's own words, on core's own backend, costs the ledger's answer only."""
        channel = Channel(None)
        for answers, sends in (({"text": "Please go on with the {category} task."}, 0),
                               ({"sender": channel}, 0), ({}, 1)):
            with self.subTest(answers=sorted(answers)):
                h = self.fresh()
                self.due(h)
                channel.h, channel.calls = h, []
                before = h.record()
                engine = self.plugged(Asked(claim_ledger=OSError("advanced.sqlite is locked"),
                                            **answers), h)
                h.tick()
                self.assertEqual(len(h.backend.send_calls) + len(channel.calls), sends)
                self.assertEqual(engine.plug.failures, 1)
                if not sends:
                    after = h.record()
                    self.assertEqual((after["state"], after["attempt_count"]), (before["state"], 0))
                    self.assertEqual(json.loads(after["gate_eval"])["submission_safe"], ["WAIT", "held"])

    def test_a_hook_failing_on_another_thread_during_the_claim_is_not_the_ledger_breaking(self):
        """`failures` is one count for every thread that holds the plug - the engine's, the
        icon's, a card's. A surface that raised on the icon's thread while the ledger was
        answering took back the ledger's spend, and the claim it had paid for still went."""
        self.due()
        path = str(Path(self.root).parent / "ledger.sqlite")
        holder = {}

        def claim_ledger(connection, record, now, carried):
            connection.execute(attach(path, "ledger"))
            connection.execute("CREATE TABLE IF NOT EXISTS ledger.spent (id TEXT, at REAL)")
            connection.execute("INSERT INTO ledger.spent VALUES (?, ?)", (record["interruption_id"], now))
            icon = threading.Thread(target=lambda: holder["engine"].plug.surface(Surface.TRAY, {}))
            icon.start()
            icon.join()
            return DEFER
        holder["engine"] = self.plugged(Asked(claim_ledger=claim_ledger,
                                              surface=RuntimeError("the icon's surface broke")))
        self.h.tick()
        self.assertEqual(holder["engine"].plug.failures, 1)
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.assertEqual(self.spent(path), 1, "the send was paid for")

    def test_the_standard_editions_claim_runs_no_statement_it_did_not_run(self):
        """NULL is never asked, so its claim is the claim there always was - statement for
        statement. Any other plug's claim takes a savepoint for its ledger."""
        seen = {}
        for name, plug in (("null", None), ("plugged", Asked())):
            h = self.fresh()
            self.due(h)
            self.plugged(plug, h)
            statements = []
            h.store._connection.set_trace_callback(statements.append)
            h.tick()
            h.store._connection.set_trace_callback(None)
            seen[name] = [statement for statement in statements if "SAVEPOINT" in statement.upper()]
        self.assertEqual(seen["null"], [])
        self.assertTrue(seen["plugged"])


class TickTests(PluggedCase):
    def test_once_a_tick_the_plug_is_shown_the_store_it_cannot_write(self):
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        hooks = plug.hooks()
        self.assertEqual([hook for hook in hooks if hook in ("tick", "partition", "records")],
                         ["tick", "partition", "records"])
        view = dict(plug.asked)["tick"][0]
        self.assertIs(dict(plug.asked)["records"][0], view)
        self.assertEqual(view.now, self.h.now)
        self.assertEqual(len(view.records_in({"queued"})), 1)
        for name in ("update", "transition", "reserve_detailed", "register", "set_enabled"):
            with self.subTest(name):
                self.assertFalse(hasattr(view, name))
        (due,) = dict(plug.asked)["partition"]
        self.assertEqual([row["thread_id"] for row in due], [T1])

    def test_an_ended_recovery_turn_is_put_to_the_plug_once_with_its_outcome(self):
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.follow()
        ended = [arguments for hook, arguments in plug.asked if hook == "outcome"]
        self.assertEqual(len(ended), 1)
        record, outcome = ended[0]
        self.assertEqual((outcome, record["state"]), ("recovered", "recovered"))
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_the_standard_edition_reads_no_consent_for_an_outcome_it_asks_nobody_about(self):
        """P6 asks the plug only while consent holds, and reading consent is two transactions -
        the settings and the conversation's switch - on every recovery turn that settles. NULL
        is never asked, so the standard edition reads neither, as v0.6.10 did not: its trace
        is the one there always was, and a read that failed there could not raise out of a
        transition whose state had already been written."""
        real = Engine.allowed
        for plug, expected in ((None, 0), (Asked(), 1)):
            with self.subTest(plugged=plug is not None):
                h = self.fresh()
                self.due(h)
                self.plugged(plug, h)
                h.tick()
                asked = []

                def allowed(engine, row, _asked=asked):
                    _asked.append(row["interruption_id"])
                    return real(engine, row)
                statements = []
                h.store._connection.set_trace_callback(statements.append)
                with patch.object(Engine, "allowed", allowed):
                    self.follow(h)
                h.store._connection.set_trace_callback(None)
                self.assertEqual(h.record()["state"], "recovered")
                self.assertEqual(len(asked), expected)
                reads = sum("FROM threads" in statement and "enabled" in statement
                            for statement in statements)
                self.assertEqual(reads, expected)

    def test_a_turn_that_ends_while_recovery_is_paused_is_not_put_to_the_plug(self):
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.h.store.set_enabled(False, self.h.now)
        self.follow()
        self.assertIn(self.h.record()["state"], ("recovered", "completed_no_progress"))
        self.assertNotIn("outcome", plug.hooks())


# The store calls the engine makes that move a record (P14): the caller of each tells the plug.
# `update` moves one only when it is handed a state. `register` is not among them: it makes a
# record rather than moving one, and the plug's view of the store shows it (P2, P8).
MOVERS = frozenset({"reserve_detailed", "release_claim", "release_withdrawn", "correlate",
                    "update"})
# The store calls a person's action makes that move a record (store/actions.py): cancelling one,
# cancelling a conversation, giving the attempts back. The engine never makes them, and no plug
# is told of them: P14 tells what the engine writes.
PERSONS = frozenset({"cancel_interruption", "cancel_thread", "restore_budget_detailed"})
# Where the engine makes those calls today - so a new one is seen, and has to tell the plug too.
# v0.6.11 stage 3b: and the claim of a route the plug names for a conversation not held (P16).
MOVING = frozenset({"AnnounceMixin.transition", "AnnounceMixin._release", "DispatchMixin.dispatch",
                    "ReconcileMixin.withdraw", "ReconcileMixin.settle", "ReconcileMixin.correlate",
                    "DeliveryMixin._resume_unloaded"})


def _moves_a_record(function, call) -> bool:
    """Whether `call`, a store call in `function`, may write a record's state."""
    if call.func.attr != "update":
        return True
    if any(keyword.arg == "state" for keyword in call.keywords):
        return True
    spread = {keyword.value.id for keyword in call.keywords
              if keyword.arg is None and isinstance(keyword.value, ast.Name)}
    for node in ast.walk(function):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(target, ast.Name) and target.id in spread for target in node.targets)
                and any(isinstance(key, ast.Constant) and key.value == "state" for key in node.value.keys)):
            return True
        if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name) and node.value.id in spread
                and isinstance(node.slice, ast.Constant) and node.slice.value == "state"):
            return True
    return False


def _store_calls(statement) -> list:
    """The `self.store.<name>(...)` calls a statement makes itself - an `if`'s in its test, not
    in its branches, which are statements of their own."""
    if isinstance(statement, ast.If):
        parts = [statement.test]
    elif isinstance(statement, (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Return)):
        parts = [statement]
    else:
        parts = []
    return [node for part in parts for node in ast.walk(part)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "store"
            and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "self"]


def _tells(statement) -> bool:
    """Whether `statement` is `self.moved(...)`."""
    return (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "moved"
            and isinstance(statement.value.func.value, ast.Name)
            and statement.value.func.value.id == "self")


def _told_after(block, index) -> bool:
    """Whether the move written by `block[index]` is told at once: by the first statement of
    the `if` it is the test of, or by the statement after it - past only the `if`s that return
    when the write was refused."""
    statement = block[index]
    if isinstance(statement, ast.If) and not (isinstance(statement.test, ast.UnaryOp)
                                              and isinstance(statement.test.op, ast.Not)):
        return bool(statement.body) and _tells(statement.body[0])
    after = index + 1
    while (after < len(block) and isinstance(block[after], ast.If) and block[after].body
           and isinstance(block[after].body[-1], ast.Return)):
        after += 1
    return after < len(block) and _tells(block[after])


class MovedTests(PluggedCase):
    """P14: every move the engine writes is told to the plug once it is written - the record as
    core held it, a copy, and the state it moved to - and nothing is told to NULL.

    The journal is the witness here, and only here: a test may read it, a decision may not
    (tests/test_surface_properties.py). Every move it recorded of the engine's is a move the
    plug was told of, in the same order."""

    @staticmethod
    def told(plug, key):
        return [(arguments[0]["state"], arguments[1]) for hook, arguments in plug.asked
                if hook == "moved" and arguments[0]["interruption_id"] == key]

    @staticmethod
    def journalled(h, key):
        return [(event["from_state"], event["to_state"]) for event in h.store.events(key)
                if event["actor"] == "engine" and event["from_state"] is not None
                and event["from_state"] != event["to_state"]]

    def scenario(self, name, h):
        """Drive `h` through one of the ways a record moves, with its plug already in place."""
        if name == "sent and followed":
            h.tick()
            self.follow(h)
        elif name == "unknown, then delivered late":
            self.unknown_but_queued(h)
            h.home.dispatch(T1)
            self.follow(h)
        elif name == "withdrawn by a Pause and released":
            h.backend.after_accept = "queue"
            h.tick()
            h.store.set_enabled(False, h.now)
            h.tick(advance=1)
            h.tick(advance=181)
        elif name == "given back before the send":
            original = h.store.reserve_detailed

            def claim_then_cancel(*args, **kwargs):
                result = original(*args, **kwargs)
                if result[0]:
                    h.store.cancel_interruption(h.record()["interruption_id"], h.now)
                return result
            h.store.reserve_detailed = claim_then_cancel
            h.tick()
        elif name == "refused at the launch guard":
            original = h.engine.presend_problem

            def look_then_pause(claim):
                found = original(claim)
                h.store.set_enabled(False, h.now)
                return found
            h.engine.presend_problem = look_then_pause
            h.tick()
        elif name == "sent into another's turn":
            h.backend.after_accept = "queue"
            h.tick()
            row = h.record()
            theirs = h.home.add_turn(T1, status="inProgress", user_text="their own message")
            h.home.remove_queued(row["queue_id"])
            h.home.add_item(T1, theirs, "userMessage", self.prompt(h))
            h.tick(advance=1)

    def test_every_move_the_engine_writes_is_told_in_the_order_it_was_written(self):
        ends = {"sent and followed": "recovered", "unknown, then delivered late": "recovered",
                "withdrawn by a Pause and released": "waiting_poll",
                "given back before the send": "cancelled",
                "refused at the launch guard": "waiting_poll",
                "sent into another's turn": "handed_over"}
        for name, end in ends.items():
            with self.subTest(name):
                h = self.fresh()
                plug = Asked()
                if name != "unknown, then delivered late":
                    self.due(h)
                self.plugged(plug, h)
                self.scenario(name, h)
                key = h.record()["interruption_id"]
                self.assertEqual(h.record()["state"], end)
                told = self.told(plug, key)
                self.assertGreater(len(told), 1)
                self.assertEqual(told, self.journalled(h, key))

    def test_a_paid_send_that_went_unknown_is_told_though_the_watch_settled_it_before_p8(self):
        """The queue's answer was unknown, and Codex had the item all the same. The next watch
        settles it before P8 is asked, so at P8 the record's state says nothing of the unknown
        send - and the journal, which no decision reads, is not asked. The move was told as it
        was written."""
        seen = []
        plug = Asked(tick=lambda view: seen.append(
            {row["interruption_id"]: row["state"] for row in view.records_in(STATES)}))
        self.plugged(plug)
        self.unknown_but_queued()
        key = self.h.record()["interruption_id"]
        self.h.home.dispatch(T1)
        self.h.tick(advance=1)
        self.assertEqual(seen[-1], {key: "turn_completed"}, "P8 no longer sees the unknown send")
        told = self.told(plug, key)
        self.assertEqual(told[-3:], [("submitting", "submission_unknown"),
                                     ("submission_unknown", "turn_started"),
                                     ("turn_started", "turn_completed")])
        last_tick = len(plug.asked) - 1 - plug.hooks()[::-1].index("tick")
        (unknown,) = [index for index, (hook, arguments) in enumerate(plug.asked)
                      if hook == "moved" and arguments[1] == "submission_unknown"]
        self.assertLess(unknown, last_tick, "told before the P8 that no longer sees it was asked")

    def test_a_move_made_while_paused_is_told_and_nothing_is_asked(self):
        """A Pause beats every capability, so nothing is asked; a move is not a question, and a
        plug that missed the moves a Pause made would not know what core did."""
        self.due()
        plug = Asked()
        self.plugged(plug)
        self.h.backend.after_accept = "queue"
        self.h.tick()
        self.h.store.set_enabled(False, self.h.now)
        before = len(plug.asked)
        self.h.tick(advance=1)
        self.h.tick(advance=181)
        self.assertEqual({hook for hook, _ in plug.asked[before:]}, {"moved"})
        key = self.h.record()["interruption_id"]
        self.assertEqual(self.told(plug, key)[-2:], [("queued", "withdrawn_unconfirmed"),
                                                     ("withdrawn_unconfirmed", "waiting_poll")])

    def test_the_plug_is_handed_a_copy_and_its_answer_is_not_read(self):
        def rewriting(record, state):
            record.update(state="recovered", thread_id=T2)
            return Alternative.HOLD
        self.due()
        self.plugged(Asked(moved=rewriting))
        self.h.tick()
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")
        self.assertEqual([call[0] for call in self.h.backend.send_calls], [T1])

    def test_null_is_never_told(self):
        """NULL is not asked, as at P6: the standard edition makes no call it did not make and
        copies no record for nobody."""
        calls = []
        real = Guarded.moved

        def moved(guarded, record, state):
            calls.append(guarded.null)
            return real(guarded, record, state)
        for plug in (None, Asked()):
            h = self.fresh()
            self.due(h)
            self.plugged(plug, h)
            with patch.object(Guarded, "moved", moved):
                h.tick()
                self.follow(h)
            self.assertEqual(h.record()["state"], "recovered")
        self.assertTrue(calls)
        self.assertNotIn(True, calls)

    def test_every_store_call_that_moves_a_record_tells_the_plug(self):
        """Found in the source, not in a run: a move made on a path no scenario takes is told too.
        The store calls that write a record's state are the ones in MOVERS, read off the store's
        own statements; each function of the engine that makes one tells the plug."""
        for name in sorted(ENGINE_TO_STORE):
            source = inspect.getsource(getattr(Store, name))
            sets = re.findall(r"UPDATE interruptions SET ((?:(?!WHERE)[^\"'])*)", source)
            with self.subTest(store=name):
                if name == "update" or any(re.search(r"\bstate\s*=", assigned) for assigned in sets):
                    self.assertIn(name, MOVERS, "a store call that moves a record")
                else:
                    self.assertNotIn(name, MOVERS)
        moving = []
        for path in srcscan.files_of("codex_auto_resume.engine"):
            tree = ast.parse(srcscan.read(path))
            names = srcscan.qualnames(tree)
            for function in ast.walk(tree):
                if not isinstance(function, ast.FunctionDef):
                    continue
                for node in ast.walk(function):
                    for block in (getattr(node, field, None) for field in ("body", "orelse", "finalbody")):
                        if not isinstance(block, list):
                            continue
                        for index, statement in enumerate(block):
                            for call in _store_calls(statement):
                                if call.func.attr in MOVERS and _moves_a_record(function, call):
                                    where = "%s:%d" % (names[function], call.lineno)
                                    moving.append(names[function])
                                    with self.subTest(where):
                                        self.assertTrue(_told_after(block, index),
                                                        "moves a record and does not tell the plug")
        self.assertEqual(set(moving), MOVING)
        self.assertEqual(len(moving), 9, "every store call that moves a record, counted")

    def test_a_persons_own_moves_are_not_told_and_the_contract_says_so(self):
        """P14 tells what the engine writes. A cancel, or the attempts given back, is written by
        what the person acted through - the Dashboard, MCP, the CLI, a toast - most often in a
        process that holds no engine: it is journalled as theirs and not told, though a plug is
        loaded here, and the contract a plug's author reads says so. None of those writes moves
        a record into or out of submission_unknown, so no tripwire depends on hearing of it."""
        cases = {"cancel_interruption": ("waiting_reset", "cancelled"),
                 "restore_budget_detailed": ("retry_budget_exhausted", "waiting_reset")}
        for name, (before, after) in cases.items():
            with self.subTest(name):
                h = self.fresh()
                h.home.fail_usage(T1)
                h.tick()
                key = h.record()["interruption_id"]
                if name == "restore_budget_detailed":
                    h.store.update(key, at=h.now, state=before, last_error="recovery_budget")
                plug = Asked()
                self.plugged(plug, h)
                self.assertEqual(h.record()["state"], before)
                getattr(h.store, name)(key, h.now, actor="gui")
                h.tick(advance=1)
                self.assertEqual(self.told(plug, key), [])
                self.assertIn((before, after, "gui"),
                              [(event["from_state"], event["to_state"], event["actor"])
                               for event in h.store.events(key)])
        persons = set()
        for name, function in inspect.getmembers(Store, inspect.isfunction):
            source = inspect.getsource(function)
            sets = re.findall(r"UPDATE interruptions SET ((?:(?!WHERE)[^\"'])*)", source)
            if name in MOVERS or not any(re.search(r"\bstate\s*=", assigned) for assigned in sets):
                continue
            persons.add(name)
            self.assertNotIn("submission_unknown", re.findall(
                r"UPDATE interruptions SET [^\"]*?\bstate\s*=\s*'([a-z_]+)'", source))
        self.assertEqual(persons, PERSONS, "every store call that moves a record is the engine's "
                                           "or a person's")
        for contract in (Point.__doc__, Plug.moved.__doc__):
            self.assertRegex(" ".join(contract.split()), r"A person's own moves .* are not told")


def rewrite(value):
    """What a careless or hostile hook does to what it is handed: every record pointed at another
    conversation and another marker, every list emptied, every nested dict cleared."""
    if isinstance(value, dict):
        if "thread_id" in value:
            value.update(thread_id=T2, marker="[rewritten]")
        else:
            for nested in list(value.values()):
                rewrite(nested)
            value.clear()
    elif isinstance(value, list):
        value.clear()


class HandedCopiesTests(PluggedCase):
    """A hook is handed copies (domain/plug.py, consult). One that rewrites what it was given
    and answers DEFER has changed nothing core does: DEFER cannot relax a gate by a side effect."""

    def test_a_hook_that_rewrites_its_record_and_defers_sends_what_null_sends(self):
        for hook in ("schedule", "gate", "text", "sender", "claim_ledger", "partition", "moved"):
            with self.subTest(hook):
                h = self.fresh()
                self.due(h)
                # T2's switch is off: whatever a hook does, nothing may go there.
                h.store.set_thread_enabled(T2, False, at=h.now)

                def rewriting(*arguments):
                    for argument in arguments:
                        rewrite(argument)
                    return DEFER
                self.plugged(Asked(**{hook: rewriting}), h)
                h.tick()
                self.assertEqual([call[0] for call in h.backend.send_calls], [T1])
                self.assertTrue(h.backend.send_calls[0][1].endswith("\n\n" + h.record()["marker"]))
                self.assertEqual(h.record()["state"], "queued")

    def test_the_view_hands_over_its_reads_and_no_attribute_leads_to_the_store(self):
        """Against a hook's mistake, not its intent (engine/options.py, StoreView): no attribute
        of the view, and no read's `__self__`, is the store. A closure's cells still are, as
        everything in core's process is to code that goes looking for it."""
        self.due()
        self.h.store.set_thread_enabled(T2, False, at=self.h.now)
        reached, seen = [], set()

        def tick(view):
            seen.update(name for name in VIEW_READS if callable(getattr(view, name, None)))
            for way in (lambda: view._store, lambda: view.get.__self__,
                        lambda: view._reads["get"].__self__):
                try:
                    reached.append(way())
                except AttributeError:
                    pass
            for store in reached:
                store.set_thread_enabled(T2, True, at=view.now)
            return DEFER
        self.plugged(Asked(tick=tick))
        self.h.tick()
        self.assertEqual(reached, [])
        self.assertEqual(seen, set(VIEW_READS), "every read the view declares is one it hands over")
        self.assertFalse(self.h.store.thread_enabled(T2))
        self.assertEqual(len(self.h.backend.send_calls), 1)


class SurfaceTests(ControlTestCase):
    def test_a_surface_that_rewrites_the_facts_it_was_shown_changes_no_status(self):
        standard = self.control.get_status()
        rewriting = Asked(surface=lambda name, facts: rewrite(facts) or DEFER)
        self.assertEqual(control.Control(self.paths, plug=rewriting).get_status(), standard)

    def test_the_status_shows_what_a_plug_adds_under_its_one_key(self):
        standard = self.control.get_status()
        self.assertNotIn(EXTRA, standard)
        plugged = control.Control(self.paths, plug=Asked(surface={"on": 0, "ids": []}))
        status = plugged.get_status()
        self.assertEqual(status[EXTRA], {"on": 0, "ids": []})
        self.assertEqual({key: value for key, value in status.items() if key != EXTRA}, standard)
        class Iterating(dict):
            def __iter__(self):
                raise RuntimeError("iteration broke")

            def items(self):
                raise RuntimeError("items broke")

        for answer in (DEFER, ["x"], {"x": float("inf")}, RuntimeError("no"), Iterating(a=1)):
            with self.subTest(answer=answer):
                self.assertNotIn(EXTRA, control.Control(self.paths, plug=Asked(surface=answer)).get_status())

    def test_a_control_layer_finds_its_homes_plug_the_first_time_it_is_asked(self):
        layer = control.Control(self.paths)
        with patch.object(edition, "plug", return_value=Asked()) as found:
            first = layer.plug
            self.assertIs(layer.plug, first)
        found.assert_called_once_with(layer.paths)
        self.assertIs(control.Control(self.paths, plug=first).plug, first)

    def serve(self, layer, *requests):
        out = io.StringIO()
        controlcli.serve(layer, io.StringIO("".join(json.dumps(request) + "\n" for request in requests)), out)
        return [json.loads(line)["reply"] for line in out.getvalue().splitlines()]

    def test_a_bridge_command_of_the_plugs_own_is_answered_by_it_and_by_nothing_else(self):
        refusal = {"ok": False, "error": "unknown command", "error_code": "request_failed"}
        asked = Asked(surface=lambda name, facts: {"echo": facts} if name == Surface.BRIDGE else DEFER)
        plugged = control.Control(self.paths, plug=asked)
        self.assertEqual(self.serve(plugged, {"id": 1, "command": "measure", "argument": {"id": "m1"}}),
                         [{"ok": True, "result": {"echo": {"command": "measure",
                                                           "argument": {"id": "m1"}}}}])
        # The standard edition refuses it exactly as it refused every unknown command.
        with patch.object(edition, "plug", return_value=edition.NULL):
            standard = control.Control(self.paths)
            self.assertEqual(self.serve(standard, {"id": 1, "command": "measure", "argument": 5},
                                        {"id": 2, "command": ["measure"]}), [refusal, refusal])
        for answer in (DEFER, "yes", RuntimeError("no")):
            with self.subTest(answer=answer):
                layer = control.Control(self.paths, plug=Asked(surface=answer))
                self.assertEqual(self.serve(layer, {"id": 1, "command": "measure"}), [refusal])
        # A command of the bridge's own is never put to the plug.
        asked.asked.clear()
        self.assertTrue(self.serve(plugged, {"id": 1, "command": "settings"})[0]["ok"])
        self.assertEqual(asked.asked, [])

    def test_the_diagnostics_bundle_redacts_what_a_plug_adds(self):
        self.assertNotIn(EXTRA, diagnostics.collect(self.control))
        added = {"where": r"C:\Users\ExampleUser\secret.txt", "who": "someone@example.com", "n": 2}
        bundle = diagnostics.collect(control.Control(self.paths, plug=Asked(surface=added)))
        self.assertEqual(bundle[EXTRA], {"where": "<path>", "who": "<email>", "n": 2})

    def test_the_icon_draws_from_what_a_plug_adds_under_its_one_key(self):
        from codex_auto_resume.ui import tray
        drawn = []
        icon = type("Icon", (), {"update": lambda _self, snapshot: drawn.append(snapshot)})()
        for plug in (None, Asked(surface={"on": 1})):
            app = App.__new__(App)
            app._plug = guard(plug)
            with control.Control(self.paths)._open() as store:
                app._update_tray(icon, store)
                expected = tray.snapshot_from(store, 0.0)
        self.assertNotIn(EXTRA, drawn[0])
        self.assertEqual(drawn[1][EXTRA], {"on": 1})
        self.assertEqual(set(drawn[0]), set(expected))


class McpSurfaceTests(ControlTestCase):
    """P10 at the MCP server: a plug's tools after core's, each checked as a declaration, its
    arguments checked as core's are, and a call to one answered by the plug and nothing else."""

    TOOL = {"name": "measure_it", "title": "Measure", "description": "Reads one thing.",
            "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}},
                            "required": ["id"], "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False}}

    def converse(self, layer, *messages):
        out = io.StringIO()
        mcpserver.Server(layer, io.StringIO("".join(json.dumps(message) + "\n" for message in messages)),
                         out).serve()
        return [json.loads(line) for line in out.getvalue().splitlines()]

    def call(self, layer, name, arguments):
        (reply,) = self.converse(layer, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                         "params": {"name": name, "arguments": arguments}})
        return reply

    def offering(self, *tools, answer=None):
        def surface(name, facts):
            if name != Surface.MCP:
                return DEFER
            if facts["request"] == "tools":
                return {"tools": list(tools)}
            return answer(facts) if callable(answer) else answer
        return Asked(surface=surface)

    def calls(self, plug):
        return [arguments[1] for hook, arguments in plug.asked
                if hook == "surface" and arguments[1].get("request") == "call"]

    def test_the_standard_editions_list_and_refusals_are_what_they_always_were(self):
        with patch.object(edition, "plug", return_value=edition.NULL):
            layer = control.Control(self.paths)
            (listed,) = self.converse(layer, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(listed["result"]["tools"], json.loads(json.dumps(MCP_TOOLS)))
            reply = self.call(layer, "measure_it", {"id": "m1"})
        self.assertEqual(reply["error"], {"code": mcpserver.INVALID_PARAMS, "message": "unknown tool"})

    def test_a_plugs_tools_come_after_cores_and_only_well_declared_ones(self):
        loose = dict(self.TOOL, name="loose_tool",
                     inputSchema=dict(self.TOOL["inputSchema"], additionalProperties=True))
        unread = dict(self.TOOL, name="unread_tool", annotations={"readOnlyHint": True})
        plug = self.offering(self.TOOL, dict(self.TOOL, name="get_status"), dict(self.TOOL, name="Bad Name"),
                             loose, unread, dict(self.TOOL, extra="x", name="second_tool"),
                             dict(self.TOOL), "junk")
        (listed,) = self.converse(control.Control(self.paths, plug=plug),
                                  {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        tools = listed["result"]["tools"]
        self.assertEqual(tools[:len(MCP_TOOLS)], json.loads(json.dumps(MCP_TOOLS)))
        self.assertEqual(tools[len(MCP_TOOLS):], [self.TOOL, dict(self.TOOL, name="second_tool")])

    def test_a_call_to_a_plugs_tool_is_answered_by_the_plug(self):
        plug = self.offering(self.TOOL, answer=lambda facts: {"summary": "measured", "data": {"echo": facts}})
        reply = self.call(control.Control(self.paths, plug=plug), "measure_it", {"id": "m1"})["result"]
        self.assertEqual(reply["content"], [{"type": "text", "text": "measured"}])
        self.assertEqual(reply["structuredContent"],
                         {"echo": {"request": "call", "tool": "measure_it", "arguments": {"id": "m1"}}})

    def test_its_arguments_are_checked_before_the_plug_hears_of_the_call(self):
        plug = self.offering(self.TOOL, answer={"summary": "measured", "data": {}})
        layer = control.Control(self.paths, plug=plug)
        for arguments in ({}, {"id": "m1", "arm": True}):
            with self.subTest(arguments=arguments):
                self.assertTrue(self.call(layer, "measure_it", arguments)["result"]["isError"])
        self.assertEqual(self.calls(plug), [])

    def test_a_plug_cannot_answer_for_a_tool_of_cores(self):
        plug = self.offering(dict(self.TOOL, name="get_status"),
                             answer={"summary": "not core", "data": {}})
        reply = self.call(control.Control(self.paths, plug=plug), "get_status", {})["result"]
        self.assertNotEqual(reply["content"][0]["text"], "not core")
        self.assertEqual(self.calls(plug), [])

    def test_a_refusal_or_an_answer_of_no_known_shape_is_a_refusal(self):
        for answer, text in (({"refused": "no advanced capability has that id"}, "no advanced capability has that id"),
                             (DEFER, controlcli.GENERIC_ERROR), ({"summary": 5, "data": {}}, controlcli.GENERIC_ERROR),
                             (RuntimeError("broken"), controlcli.GENERIC_ERROR)):
            with self.subTest(answer=answer):
                def respond(facts, answer=answer):
                    if isinstance(answer, Exception):
                        raise answer
                    return answer
                reply = self.call(control.Control(self.paths, plug=self.offering(self.TOOL, answer=respond)),
                                  "measure_it", {"id": "m1"})["result"]
                self.assertTrue(reply["isError"])
                self.assertEqual(reply["content"][0]["text"], text)
                self.assertEqual(reply["structuredContent"], {"error_code": "request_failed"})


class StartRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = config.Paths(Path(self.temporary.name))
        self.paths.ensure()
        (self.paths.home / "watcher-launcher.py").write_text("# launcher\n", encoding="utf-8")
        for target, name, value in ((control.Control, "watcher_running", False),
                                    (windows, "install_in_progress", False)):
            patcher = patch.object(target, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_refusal_stands_when_the_plug_names_no_route(self):
        """Asked only where core refuses - with the setting on and nothing running. A plug that
        answers with anything core cannot call - DEFER, a word, an exception - keeps the refusal
        (Guarded.start_route drops it), and nothing is launched."""
        job = {"in_job": True, "kill_on_close": True, "breakaway_ok": False}
        for answer in (DEFER, Alternative.HOLD, "wmi", 3, object(), RuntimeError("no")):
            with self.subTest(answer=answer):
                plug = Asked(start_route=answer)
                layer = control.Control(self.paths, plug=plug)
                layer.update_settings({"start_with_codex": True})
                with patch.object(control.Control, "_launch_watcher") as launch:
                    decision = layer._start_for_codex(dict(job))
                launch.assert_not_called()
                self.assertEqual(decision, "not started: this Codex ends what its plugins start")
                self.assertEqual(plug.asked, [("start_route", (job,))])

    def test_a_named_route_is_carried_out_outside_the_job(self):
        """A route the plug names - an object with `start` - is called with the command line core
        built from the stable launcher, and the pid it hands back is the line core writes."""
        job = {"in_job": True, "kill_on_close": True, "breakaway_ok": False}
        seen = {}

        class Route:
            def start(self, command):
                seen["command"] = command
                return {"pid": 4242}

        plug = Asked(start_route=Route())
        layer = control.Control(self.paths, plug=plug)
        layer.update_settings({"start_with_codex": True})
        with patch.object(startup, "python_launcher", return_value=Path("pythonw.exe")), \
                patch.object(control.Control, "_launch_watcher") as launch:
            decision = layer._start_for_codex(dict(job))
        launch.assert_not_called()          # core never launches inside the job itself
        self.assertEqual(decision, "started through WMI pid 4242")
        self.assertIn("watcher-launcher.py", seen["command"])
        self.assertTrue(seen["command"].endswith(' "run"') or seen["command"].endswith(" run"))

    def test_a_route_that_refuses_records_the_code_and_starts_nothing(self):
        job = {"in_job": True, "kill_on_close": True, "breakaway_ok": False}

        class Route:
            def start(self, command):
                return {"code": 21}

        layer = control.Control(self.paths, plug=Asked(start_route=Route()))
        layer.update_settings({"start_with_codex": True})
        with patch.object(startup, "python_launcher", return_value=Path("pythonw.exe")):
            decision = layer._start_for_codex(dict(job))
        self.assertEqual(decision, "not started: WMI refused (21)")

    def test_a_route_is_not_taken_while_an_installation_is_in_progress(self):
        """The install lock is looked at once more immediately before the launch, so an install
        that began after the first look stops the route."""
        job = {"in_job": True, "kill_on_close": True, "breakaway_ok": False}
        started = []

        class Route:
            def start(self, command):
                started.append(command)
                return {"pid": 1}

        layer = control.Control(self.paths, plug=Asked(start_route=Route()))
        layer.update_settings({"start_with_codex": True})
        with patch.object(windows, "install_in_progress", side_effect=[False, True]):
            decision = layer._start_for_codex(dict(job))
        self.assertEqual(decision, "not started: an installation is in progress")
        self.assertEqual(started, [])

    def test_a_start_core_makes_itself_with_the_setting_on_asks_nothing(self):
        """With the setting on, core is starting on its own account: it launches itself and asks
        the plug for no route, in a job that would not end the watcher or out of one."""
        plug = Asked()
        layer = control.Control(self.paths, plug=plug)
        layer.update_settings({"start_with_codex": True})
        with patch.object(control.Control, "_launch_watcher",
                          return_value=type("Process", (), {"pid": 7})()):
            self.assertEqual(layer._start_for_codex({"in_job": False}), "started pid 7")
        self.assertEqual(plug.asked, [])

    def test_a_decline_with_the_setting_off_asks_only_for_a_route(self):
        """With the setting off, the one way core learns whether an advanced capability has turned
        the start on is to ask the plug for a route; a plug that names none is declined as "off",
        and the standard edition's NULL plug is asked nothing at all (it names no route by kind)."""
        plug = Asked()
        layer = control.Control(self.paths, plug=plug)
        self.assertEqual(layer._start_for_codex({"in_job": False}), "off")
        self.assertEqual(plug.asked, [("start_route", ({"in_job": False},))])
        standard = control.Control(self.paths)
        self.assertEqual(standard._start_for_codex({"in_job": False}), "off")


class SupervisionTests(unittest.TestCase):
    """P13 in the launcher: asked after a run of the watcher, never after another command, and
    the exit code is the watcher's whatever it answers."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        copy = self.home / "watcher-launcher.py"
        shutil.copyfile(ROOT / "scripts" / "watcher_launcher.py", copy)
        (self.home / "runtime.json").write_text(json.dumps({"home": str(self.home)}), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("watcher_launcher_supervised", copy)
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        saved = list(sys.path)
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved))
        environment = patch.dict(os.environ)
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop(self.launcher.RELAUNCH_MARK, None)

    def launch(self, argv, code, plug):
        with patch.object(self.launcher, "resolve_plugin_root", return_value=ROOT), \
                patch("codex_auto_resume.cli.main", return_value=code), \
                patch.object(self.launcher, "_relaunch_once") as relaunch, \
                patch.object(edition, "plug", return_value=plug) as found:
            returned = self.launcher.main(argv)
        return returned, relaunch, found

    def test_a_run_that_ended_is_put_to_the_plug_and_its_code_is_returned(self):
        for code in (0, 1, 3):
            for answer in (DEFER, "restart", Alternative.HOLD, RuntimeError("no")):
                with self.subTest(code=code, answer=answer):
                    plug = Asked(supervise=answer)
                    returned, relaunch, found = self.launch([], code, plug)
                    self.assertEqual(returned, code)
                    self.assertEqual(plug.asked, [("supervise", ({"exit_code": code},))])
                    self.assertEqual(found.call_args.args[0].home, self.home.resolve())
                    relaunch.assert_not_called()

    def test_the_launchers_own_relaunch_and_other_commands_ask_nothing(self):
        plug = Asked()
        returned, relaunch, _ = self.launch([], self.launcher.EXIT_SCHEMA_NEWER, plug)
        self.assertEqual(returned, self.launcher.EXIT_SCHEMA_NEWER)
        relaunch.assert_called_once()
        self.launch(["activate", "codex-auto-resume:open?page=pending"], 0, plug)
        self.assertEqual(plug.asked, [])

    def test_an_engine_from_before_editions_has_no_plug_to_ask(self):
        """Such an engine is what the launcher resolves when only an old plugin copy is left."""
        with patch.dict(sys.modules, {"codex_auto_resume.domain.plug": None}), \
                patch.object(edition, "plug") as found:
            self.launcher._supervise(self.home, 0)
        found.assert_not_called()


# ------------------------------------------------------------------------- P17 (v0.6.13 stage 3b)
UNKNOWN_CODE = json.dumps({"codexErrorInfo": "brandNewVariant"})
UNAUTHORIZED = json.dumps({"codexErrorInfo": "unauthorized"})
# Every answer core would carry out for an unknown failure with a plain code of Codex's.
TAKE_UP = frozenset({Alternative.ADMIT}) | frozenset(PACED_AS)


def failed(h, error_json=UNKNOWN_CODE, *, thread=T1, turn=TURN_A, completed=BASE):
    """A failed turn of `thread`, loaded in the app; `error_json=None` is one with no error at all."""
    h.home.add_turn(thread, turn, "failed", completed=completed, started=completed - 60,
                    error_json=error_json, progress=False)
    h.backend.loaded_map[thread] = "loaded"
    return turn


def admitting(answer=Alternative.ADMIT, again=None, **answers):
    """A plug that wants every point, takes each failure up with `answer` at P17, and again at
    known_failure with `again` - the same word unless told otherwise."""
    again = answer if again is None else again
    return Asked(wants=True, admission=answer,
                 gate=lambda name, record, facts: again if name == "known_failure" else DEFER, **answers)


def admissions(plug):
    return [arguments[0] for hook, arguments in plug.asked if hook == "admission"]


class AdmissionTests(PluggedCase):
    """P17: a failure core never recovers alone, put to the plug once it has passed every check core
    makes of one, with what core would carry out for it - and taken up only as one of those."""

    def test_it_is_asked_once_with_what_core_would_take_and_never_a_word_of_the_message(self):
        failed(self.h, json.dumps({"codexErrorInfo": "brandNewVariant", "message": "secret words"}))
        plug = Asked(wants=True)
        self.plugged(plug)
        self.h.tick()
        (facts,) = admissions(plug)
        self.assertEqual(set(facts), {"interruption_id", "thread_id", "turn_id", "category", "code",
                                      "status", "form", "has_message", "started_at", "completed_at",
                                      "ordinal", "takes", "chain"})
        self.assertEqual((facts["thread_id"], facts["turn_id"], facts["category"], facts["code"],
                          facts["status"], facts["form"], facts["has_message"], facts["chain"]),
                         (T1, TURN_A, "unknown", "brandNewVariant", None, "tagged", True, None))
        self.assertEqual(facts["takes"], TAKE_UP)
        self.assertNotIn("secret", repr(facts))
        # DEFER takes nothing up, and it is put to the plug again a minute on, not before.
        self.assertEqual(self.h.records(), [])
        self.h.tick(advance=30)
        self.assertEqual(len(admissions(plug)), 1)
        self.h.tick(advance=31)
        self.assertEqual(len(admissions(plug)), 2)
        self.assert_no_send()

    def test_it_is_never_asked_without_consent_or_while_the_plug_wants_nothing(self):
        for how in ("thread_off", "observe_only", "force_observe_only", "not_wanted"):
            with self.subTest(how):
                h = self.fresh()
                failed(h)
                plug = admitting() if how != "not_wanted" else Asked(admission=Alternative.ADMIT)
                engine = self.plugged(plug, h)
                if how == "thread_off":
                    h.store.set_thread_enabled(T1, False, at=h.now)
                elif how == "observe_only":
                    engine.apply_policy(dict(settings.defaults(), observe_only=True))
                elif how == "force_observe_only":
                    engine.apply_policy(settings.defaults(), managed.Managed(force_observe_only=True))
                h.tick()
                self.assertNotIn("admission", plug.hooks())
                self.assertEqual(h.records(), [])

    def test_wanting_nothing_it_reads_of_codex_what_the_standard_edition_reads(self):
        def reads(plug):
            h = self.fresh()
            failed(h)
            seen, real = [], h.source.latest_failures

            def recorded(*arguments, **keywords):
                seen.append((arguments, sorted(keywords.items())))
                return real(*arguments, **keywords)
            h.source.latest_failures = recorded
            self.plugged(plug, h)
            h.tick()
            return seen
        standard = reads(None)
        self.assertEqual(reads(Asked()), standard)
        self.assertEqual([keywords for _, keywords in standard], [[]])
        self.assertEqual([keywords for _, keywords in reads(Asked(wants=True))],
                         [[("admissible", True), ("shapes", True)]])

    def test_a_subagent_or_archived_conversation_is_never_put_to_it(self):
        for how in ("archived", "subagent"):
            with self.subTest(how):
                h = self.fresh()
                if how == "subagent":
                    h.home.add_thread(T1, thread_source="subagent")
                failed(h)
                if how == "archived":
                    archive(h.home, T1)
                plug = admitting()
                self.plugged(plug, h)
                h.tick()
                self.assertEqual((admissions(plug), h.records()), ([], []))

    def test_a_failure_from_more_than_an_hour_ago_is_left_alone(self):
        failed(self.h, completed=self.h.now - ladder.ADMISSION_MAX_AGE - 1)
        plug = admitting()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual((admissions(plug), self.h.records()), ([], []))

    def test_nothing_is_asked_that_core_would_not_carry_out(self):
        """No code, a message alone, a status alone, something unrecognised, a code that names a
        decision, a kind core knows needs a person, a permission refusal: `takes` is empty."""
        cases = {"absent": None,
                 "message_only": json.dumps({"message": "something went wrong"}),
                 "status_only": json.dumps({"codexErrorInfo": {"httpStatusCode": 302}}),
                 "unrecognised": json.dumps({"codexErrorInfo": {"one": 1, "two": 2}}),
                 "decision": json.dumps({"codexErrorInfo": "policyRefused"}),
                 "terminal_invalid": json.dumps({"codexErrorInfo": "badRequest"}),
                 "permission": json.dumps({"codexErrorInfo": {"brandNewVariant": {"httpStatusCode": 403}}})}
        for name, error in cases.items():
            with self.subTest(name):
                h = self.fresh()
                failed(h, error)
                plug = admitting()
                self.plugged(plug, h)
                h.tick()
                self.assertEqual((admissions(plug), h.records()), ([], []))

    def test_a_failure_core_recovers_is_registered_as_it_always_was(self):
        rows = []
        for plug in (None, admitting()):
            h = self.fresh()
            failed(h, json.dumps({"codexErrorInfo": "internalServerError"}))
            self.plugged(plug, h)
            h.tick()
            row = h.record()
            rows.append((row["category"], row["state"], row["next_retry_at"], row["last_error"]))
            if plug is not None:
                self.assertEqual(admissions(plug), [])
        self.assertEqual(rows[0], rows[1])

    def test_an_answer_outside_what_core_offered_takes_nothing(self):
        failed(self.h, UNAUTHORIZED)
        plug = admitting(Alternative.AS_TIMEOUT)
        self.plugged(plug)
        self.h.tick()
        (facts,) = admissions(plug)
        self.assertEqual((facts["category"], facts["takes"]), ("terminal_auth", {Alternative.ADMIT}))
        self.assertEqual(self.h.records(), [])

    def test_admit_takes_it_up_as_its_own_kind_and_sends_the_short_message_ten_minutes_on(self):
        failed(self.h)
        engine = self.plugged(admitting())
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["state"], row["next_retry_at"]),
                         ("unknown", "waiting_backoff", self.h.now + 600))
        self.assertIn((T1, "failure_taken_up", row["interruption_id"]), self.h.logs)
        self.h.tick(advance=599)
        self.assert_no_send()
        self.h.tick(advance=1)
        expected = continuation.for_settings("unknown", engine.policy_values, row=self.h.record(),
                                             limits=engine.limits())
        self.assertEqual(continuation.build("unknown"), "Please retry.")
        self.assertEqual(self.h.backend.send_calls, [(T1, expected + "\n\n" + row["marker"])])
        self.assertEqual(json.loads(self.h.record()["gate_eval"])["known_failure"], ["PASS", "plugged"])
        self.follow()
        self.assertEqual(self.h.record()["state"], "recovered")

    def test_as_timeout_is_paced_as_a_timeout(self):
        failed(self.h)
        engine = self.plugged(admitting(Alternative.AS_TIMEOUT))
        self.h.tick()
        row = self.h.record()
        self.assertEqual((row["category"], row["next_retry_at"]),
                         ("unknown", self.h.now + engine.first_delay("timeout")))
        self.h.tick(advance=engine.first_delay("timeout"))
        self.assertEqual(len(self.h.backend.send_calls), 1)

    def test_a_kind_switched_off_in_settings_is_not_offered(self):
        failed(self.h)
        plug = Asked(wants=True)
        engine = self.plugged(plug)
        engine.apply_policy(dict(settings.defaults(), recover_timeout=False))
        self.h.tick()
        (facts,) = admissions(plug)
        self.assertEqual(facts["takes"], TAKE_UP - {Alternative.AS_TIMEOUT})


class KnownFailureTests(PluggedCase):
    """known_failure for a record P17 took up: the one gate core refuses that is put to the plug,
    so it goes on only while the plug takes it up again - and otherwise ends, unsent."""

    def admitted(self, h=None, answer=Alternative.ADMIT, error=UNKNOWN_CODE):
        h = h or self.h
        failed(h, error)
        self.plugged(admitting(answer), h)
        h.tick()
        row = h.record()
        self.assertIsNotNone(row, "taken up")
        return row

    def test_null_a_plug_that_defers_and_one_that_fails_end_it_unsent(self):
        self.assertTrue(self.h.engine.recovers("unknown"), "no switch: it cannot be what decides")
        for plug in (None, Asked(wants=True), Asked(wants=True, gate=RuntimeError("broken")),
                     DamagedPlug(PlugFailure.SHADOWED)):
            with self.subTest(plug=type(plug).__name__):
                h = self.fresh()
                self.admitted(h)
                self.plugged(plug, h)
                h.tick(advance=600)
                row = h.record()
                self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "not_recoverable"))
                self.assertEqual(json.loads(row["gate_eval"])["known_failure"], ["BLOCK", "not_recoverable"])
                self.assert_no_send(h)

    def test_hold_keeps_it_waiting_and_a_word_its_kind_does_not_take_ends_it(self):
        h = self.fresh()
        self.admitted(h)
        self.plugged(admitting(again=Alternative.HOLD), h)
        h.tick(advance=600)
        row = h.record()
        self.assertEqual(row["state"], "waiting_backoff")
        self.assertEqual(json.loads(row["gate_eval"])["known_failure"], ["WAIT", "held"])
        h = self.fresh()
        self.admitted(h, error=UNAUTHORIZED)
        self.plugged(admitting(again=Alternative.AS_TIMEOUT), h)
        h.tick(advance=600)
        row = h.record()
        self.assertEqual((row["category"], row["state"], row["last_error"]),
                         ("terminal_auth", "terminal_failure", "not_recoverable"))
        self.assert_no_send(h)

    def test_observe_only_keeps_it_waiting_asks_no_plug_and_it_goes_once_that_is_off(self):
        for administrator in (False, True):
            with self.subTest(administrator=administrator):
                h = self.fresh()
                self.admitted(h)
                plug = admitting()
                engine = self.plugged(plug, h)
                if administrator:
                    engine.apply_policy(settings.defaults(), managed.Managed(force_observe_only=True))
                else:
                    engine.apply_policy(dict(settings.defaults(), observe_only=True))
                h.tick(advance=600)
                row = h.record()
                self.assertEqual(row["state"], "waiting_backoff")
                self.assertEqual(json.loads(row["gate_eval"])["known_failure"], ["UNKNOWN", "observe_only"])
                self.assertEqual(plug.gates(), [])
                self.assert_no_send(h)
                engine.apply_policy(settings.defaults())
                h.tick(advance=900)
                self.assertEqual(len(h.backend.send_calls), 1)

    def test_a_day_on_the_clock_ends_it_unsent_whatever_it_waited_for(self):
        self.admitted()
        self.plugged(admitting(again=Alternative.HOLD))
        self.h.tick(advance=600)
        self.assertEqual(self.h.record()["state"], "waiting_backoff")
        self.h.tick(advance=ladder.ADMITTED_MAX_SECONDS)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("terminal_failure", "admission_expired"))
        self.assert_no_send()

    def test_an_as_word_whose_kind_is_switched_off_waits_as_that_kind_does(self):
        self.admitted(answer=Alternative.AS_TIMEOUT)
        self.h.engine.apply_policy(dict(settings.defaults(), recover_timeout=False))
        self.h.tick(advance=600)
        row = self.h.record()
        self.assertEqual((row["state"], row["last_error"]), ("waiting_backoff", "category_disabled"))
        self.assertEqual(json.loads(row["gate_eval"])["known_failure"], ["BLOCK", "category_disabled"])
        self.assert_no_send()

    def test_the_claim_takes_one_only_as_a_relaxation_its_ledger_pays_for(self):
        row = self.admitted()
        ledger = guard(admitting())
        key, at = row["interruption_id"], row["next_retry_at"] + 1
        for options in ({"ledger": None, "relaxed": "admitted", "carried": {Point.GATES}},
                        {"ledger": ledger, "relaxed": "admitted", "carried": frozenset()},
                        {"ledger": ledger, "relaxed": None, "carried": {Point.GATES}},
                        {"ledger": ledger, "relaxed": "capacity", "carried": {Point.GATES}}):
            with self.subTest(options=sorted(options)):
                self.assertEqual(self.h.store.reserve_detailed(key, at, **options),
                                 (False, "known_failure", "not_recoverable"))
        self.assertEqual(self.h.store.reserve_detailed(key, at, ledger=ledger, relaxed="admitted",
                                                       carried={Point.GATES}), (True, None, None))


class ChainTests(PluggedCase):
    """What P17 is told of the task a failure continues: the record whose own continuation started
    the turn that failed - the one `register` will make it a child of."""

    def chain_failure(self, h, error=UNKNOWN_CODE):
        """A usage-limit failure whose continuation Codex runs, and whose turn then fails with
        `error`: (that record, the failed turn)."""
        h.backend.after_accept = "queue"
        self.ready_after_reset(h)
        h.tick()
        parent = h.record()
        self.assertEqual(parent["state"], "queued")
        turn = h.home.dispatch(T1, status="inProgress", progress=False)
        fail_turn(h.home, T1, turn, error_json=error)
        return parent, turn

    def test_a_recovery_turn_the_watch_correlated_is_the_chain_where_owner_alone_finds_none(self):
        parent, turn = self.chain_failure(self.h)
        plug = Asked(wants=True)
        engine = self.plugged(plug)
        self.h.tick(advance=1)
        self.assertEqual(self.h.store.get(parent["interruption_id"])["recovery_turn_id"], turn)
        self.assertIsNone(engine._owner(T1, turn), "the owner read sees only records not correlated yet")
        (facts,) = admissions(plug)
        chain = facts["chain"]
        self.assertEqual((chain["interruption_id"], chain["category"], chain["chain_started_at"]),
                         (parent["interruption_id"], "usage_limit", parent["detected_at"]))
        self.assertEqual(self.h.store.chain_parent(T1, turn), self.h.store.get(parent["interruption_id"]))

    def test_one_taken_up_continues_the_chain_register_finds(self):
        parent, turn = self.chain_failure(self.h)
        self.plugged(admitting())
        self.h.tick(advance=1)
        child = self.h.records()[-1]
        attempts = self.h.store.get(parent["interruption_id"])["recovery_attempts"]
        self.assertEqual((child["category"], child["parent_interruption_id"], child["chain_origin_id"]),
                         ("unknown", parent["interruption_id"], parent["interruption_id"]))
        self.assertEqual(child["next_retry_at"],
                         self.h.now + ladder.ADMITTED_WAITS[min(attempts, len(ladder.ADMITTED_WAITS) - 1)])

    def test_the_child_of_a_cancelled_or_spent_task_is_never_put_to_it(self):
        for how in ("cancelled", "spent"):
            with self.subTest(how):
                h = self.fresh()
                parent, _turn = self.chain_failure(h)
                plug = admitting()
                engine = self.plugged(plug, h)
                if how == "cancelled":
                    h.store.cancel_interruption(parent["interruption_id"], h.now)
                else:
                    engine.options["max_no_progress"] = 1
                h.tick(advance=1)
                self.assertEqual(admissions(plug), [])
                self.assertEqual([row["interruption_id"] for row in h.records()], [parent["interruption_id"]])

    def test_chain_parent_and_register_agree_on_every_kind_of_parent(self):
        """By the recovery turn, by the marker of a record the watch has not correlated, and none."""
        h = self.h
        parent, turn = self.chain_failure(h)
        self.assertIsNone(h.store.get(parent["interruption_id"])["recovery_turn_id"])
        owner = h.engine._owner(T1, turn)
        self.assertEqual(owner, parent["interruption_id"])
        found = h.store.chain_parent(T1, turn, owner)
        self.assertEqual(found["interruption_id"], parent["interruption_id"])
        self.assertIsNone(h.store.get(parent["interruption_id"])["recovery_turn_id"], "nothing written")
        self.assertIsNone(h.store.chain_parent(T1, turn), "no recovery turn yet, and no owner named")
        self.assertIsNone(h.store.chain_parent(T2, turn, owner), "another conversation's record")
        self.plugged(admitting())
        h.tick(advance=1)
        self.assertEqual(h.store.chain_parent(T1, turn)["interruption_id"], parent["interruption_id"])
        child = h.records()[-1]
        self.assertEqual(child["parent_interruption_id"], h.store.chain_parent(T1, turn)["interruption_id"])


if __name__ == "__main__":
    unittest.main()
