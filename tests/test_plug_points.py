"""Where core asks the edition's plug, and what it does with each answer (v0.6.11, P2-P13).

tests/test_edition.py holds the interface - NULL, the closed sets, the guard core holds a plug
in - and tests/test_neutral_plug.py holds that a plug which always defers changes nothing in any
scenario. This holds each point where it stands in core, against the same real store, Codex home
and simulated backend the engine's scenarios use (tests/codexsim.py):

* nothing is asked while recovery is paused, and nothing about a record its conversation's
  switch or a cancel has stopped: the consent gate comes first;
* at the schedule and the gates, a plug is asked only once core's own gate has passed, and
  HOLD - the one answer it has - keeps the record waiting for one poll and nothing more;
* its words go out only as a person's Custom message would; a channel it names gets the one
  send, after the one claim and the pre-send look, inside the launch guard;
* its ledger is asked inside the claim, can refuse one and never grant one, and what it writes
  there commits with the claim or not at all - and the standard edition's is never asked;
* a surface shows what it adds under one key, and nothing when it adds nothing; MCP offers its
  well-declared tools after core's and hands it the calls to them, checked as core's are; the start
  route's refusal and the launcher's exit code are what they were, whatever it answers.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
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

from codexsim import RESET  # noqa: E402
from test_control import ControlTestCase  # noqa: E402
from test_engine import T1, T2, TURN_A, EngineCase  # noqa: E402
from codex_auto_resume import (config, continuation, control, controlcli, diagnostics,  # noqa: E402
                               edition, mcpserver, settings, windows)
from codex_auto_resume.domain.plug import (DEFER, EXTRA, Alternative, Plug, Point,  # noqa: E402
                                           Surface, guard)
from codex_auto_resume.engine import Engine  # noqa: E402
from codex_auto_resume.mcp.tools import TOOLS as MCP_TOOLS  # noqa: E402
from codex_auto_resume.runtime.app import App  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
POLL = 60
# The gates core puts to the plug, in the order it does - each once core's own has passed.
ASKED_GATES = ("submission_safe", "chain_budget", "no_progress_budget", "thread_available",
               "attempt_budget", "usage")


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

    def hooks(self):
        return [hook for hook, _ in self.asked]

    def gates(self):
        return [arguments[0] for hook, arguments in self.asked if hook == "gate"]


def attach(path, name):
    """An ATTACH of the file at `path` as `name`, which the statement names: the claim lets a
    ledger's ATTACH on only once it has read which file it is (store/claims.py)."""
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
        """Nothing can relax a gate yet, so a gate core refuses is not asked about at all."""
        self.h.home.fail_usage(T1)
        self.h.tick()
        self.h.now = RESET + 61                                    # due, but never loaded
        plug = Asked()
        self.plugged(plug)
        self.h.tick()
        self.assertEqual(plug.gates(), ["submission_safe", "chain_budget", "no_progress_budget"])
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
                "claim_ledger", "partition")})):
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
        for hook in ("schedule", "gate", "text", "sender", "claim_ledger", "partition"):
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
        reached = []

        def tick(view):
            for way in (lambda: view._store, lambda: view.get.__self__,
                        lambda: view._read("get").__self__):
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

    def test_the_refusal_stands_whatever_the_plug_answers(self):
        """Asked only where core refuses - with the setting on and nothing running - and no
        route of a plug's is carried out yet."""
        job = {"in_job": True, "kill_on_close": True, "breakaway_ok": False}
        for answer in (DEFER, Alternative.HOLD, "wmi", RuntimeError("no")):
            with self.subTest(answer=answer):
                plug = Asked(start_route=answer)
                layer = control.Control(self.paths, plug=plug)
                layer.update_settings({"start_with_codex": True})
                with patch.object(control.Control, "_launch_watcher") as launch:
                    decision = layer._start_for_codex(dict(job))
                launch.assert_not_called()
                self.assertEqual(decision, "not started: this Codex ends what its plugins start")
                self.assertEqual(plug.asked, [("start_route", (job,))])

    def test_a_start_core_makes_or_declines_itself_asks_nothing(self):
        plug = Asked()
        layer = control.Control(self.paths, plug=plug)
        self.assertEqual(layer._start_for_codex({"in_job": False}), "off")
        layer.update_settings({"start_with_codex": True})
        with patch.object(control.Control, "_launch_watcher",
                          return_value=type("Process", (), {"pid": 7})()):
            self.assertEqual(layer._start_for_codex({"in_job": False}), "started pid 7")
        self.assertEqual(plug.asked, [])


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


if __name__ == "__main__":
    unittest.main()
