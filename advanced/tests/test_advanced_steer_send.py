"""Steer the running turn (v0.6.20, issue #50 item 2 - steer_send): a line the person writes in the prompt queue's editor,
added at once to the turn running in a conversation the Codex app holds, through the app's own IPC pipe - with the
warning that the app never shows the steered line (MSTEER2 failed not_as_expected), and every steer kept with its words
for History.

What is held: the capability is offered with MSTEER2's failure as a warning the person confirms, never a refusal; only
the watcher's P8 errand writes a steer, exactly once a request, claimed before the write; never written again once it may
have been (an unanswered write, a pipe failing after the write, a watcher stopped after the claim); refused with its own
reason where no turn runs, the app does not hold the conversation, the pipe is not there, core's guard holds it, it waited
too long or the capability was turned off; and History's three outcomes - accepted, may have been delivered, refused -
never folded into one.

Held against core's own engine and store (takingcase.py); Codex's history, the holder count, the app's identity check and
the pipe are the test's own (engine/steer.py's seams, and fakeipc's scratch pipe), so nothing here reaches a real Codex.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests -p test_advanced_steer_send.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from codex_auto_resume_advanced import arming, registry, statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import ipc  # noqa: E402
from codex_auto_resume_advanced.control import steer as steer_control  # noqa: E402
from codex_auto_resume_advanced.engine import steer as steer_engine  # noqa: E402
from codex_auto_resume_advanced.measured import MEASURED  # noqa: E402
from codex_auto_resume_advanced.registry import PROMPT_QUEUE, STEER_SEND, problems  # noqa: E402
from codex_auto_resume_advanced.state import schema  # noqa: E402
from codex_auto_resume_advanced.vocabulary import (Actor, ArmingWarning, Measurement, SteerReason, SteerState,  # noqa: E402
                                                   Verdict)
from test_engine import T1  # noqa: E402

ADVANCED_SRC = Path(ac.ROOT) / "advanced" / "src" / "codex_auto_resume_advanced"
WORDS = "Also: end your reply with the single word ok."
# The pipe's own steer, before any test replaces it.
REAL_STEER = ipc.steer_turn


class DefinitionTests(unittest.TestCase):
    def test_it_is_offered_whole_and_names_what_it_departs_from(self):
        self.assertEqual(problems(STEER_SEND), [])
        self.assertIs(registry.REGISTRY.get("steer_send"), STEER_SEND, "offered, not hidden: the owner's decision")
        for standard in ("A4", "B3", "A2", "A1", "A8", "A17", "A20", "A26", "D2", "H6"):
            self.assertIn(standard, STEER_SEND.departs_from)
        self.assertEqual(STEER_SEND.measurements, (Measurement.MIPC, Measurement.MSTEER2))
        self.assertEqual(STEER_SEND.requires, ("prompt_queue",), "written in the prompt queue's editor")
        shown = [definition.id for definition in registry.shown(registry.REGISTRY)]
        self.assertEqual(shown[shown.index("prompt_queue") + 1], "steer_send")

    def test_its_statement_and_words_are_in_every_language(self):
        self.assertEqual(statement.CATALOGS.missing(STEER_SEND), [])
        keys = [key for key in statement.PAGE_KEYS if ".steer" in key or "steer_" in key or key.endswith(".steer")]
        self.assertGreaterEqual(len(keys), 20)
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                own = statement.CATALOGS.own(locale)
                self.assertTrue(own[statement.name_key("steer_send")].strip())
                for key in keys:
                    self.assertTrue(own.get(key, "").strip(), key)
                self.assertIn("{words}", own["page.steer.sent"])

    def test_the_warning_is_said_first_in_the_statement_and_in_the_editor(self):
        own = statement.CATALOGS.own("en")
        self.assertIn("does not show the steered line", own["statement.steer_send.does"])
        self.assertIn("only History", own["statement.steer_send.does"])
        self.assertIn("does not show the steered line", own["page.editor.steer.warning"])
        for state in ("accepted", "unconfirmed", "refused", "waiting"):
            self.assertIn("page.steer.state." + state, statement.PAGE_KEYS)
        self.assertNotIn("page.steer.state.seen", statement.PAGE_KEYS, "observed is not available (#50)")

    def test_msteer2s_failure_is_a_warning_the_person_confirms_never_a_refusal(self):
        """MSTEER2 is recorded failed (not_as_expected): arming shows MEASUREMENT_FAILED, the existing mechanism."""
        self.assertEqual(MEASURED[Measurement.MSTEER2][0], Verdict.FAIL)
        view = ac.view(capability=STEER_SEND.compat, version=MEASURED[Measurement.MSTEER2][1])
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, arming.warnings_for(STEER_SEND, view, MEASURED))


class StructureTests(unittest.TestCase):
    def test_only_the_watchers_errand_and_the_measurement_call_the_pipes_steer(self):
        """The bridge's request writes a row and wakes the watcher; it never reaches the pipe (A1's spirit kept: only the
        watcher sends)."""
        callers = set()
        for path in ADVANCED_SRC.rglob("*.py"):
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            if re.search(r"\bsteer_turn\(|ipc\.steer_turn\b", text) and path.name != "ipc.py":
                callers.add(path.relative_to(ADVANCED_SRC).as_posix())
        self.assertEqual(callers, {"engine/steer.py", "measure.py"})
        control = (ADVANCED_SRC / "control" / "steer.py").read_text(encoding="utf-8")
        self.assertNotRegex(control, r"\bipc\b")
        self.assertEqual(STEER_SEND.points, frozenset({registry.Point.TICK}), "P8's errand, run by core with its guards")

    def test_the_steers_table_is_version_9_and_still_readable_from_7(self):
        self.assertEqual((schema.SCHEMA_VERSION, schema.READABLE_FROM), (9, 7))
        self.assertEqual(set(schema.TABLES) - set(schema.TABLES_V8), {"steers"})
        self.assertEqual(schema.TABLES_V8, {name: columns for name, columns in schema.TABLES.items() if name != "steers"})


class _Channel:
    """A stand-in for ipc.Channel: the app's answers to initialize and to the owner, then - for the steer - `steer`
    (an exception the read raises, or None for success)."""

    def __init__(self, steer=None):
        self.steer, self.written, self._last = steer, [], None

    def write(self, message):
        self.written.append(message.get("method") or message.get("type"))
        self._last = message

    def read(self, seconds=None):
        method, key = self._last.get("method"), self._last.get("requestId")
        if method == "thread-follower-steer-turn" and self.steer is not None:
            raise self.steer
        if method == "initialize":
            return {"type": "response", "requestId": key, "resultType": "success", "result": {"clientId": "us"}}
        if method == "thread-owner-discovery":
            return {"type": "response", "requestId": key, "resultType": "success", "handledByClientId": "owner"}
        return {"type": "response", "requestId": key, "resultType": "success", "result": {}}

    def close(self):
        pass


class PipeTests(unittest.TestCase):
    def test_a_pipe_failing_after_the_steer_was_written_is_unconfirmed_never_broken(self):
        """Fails with ipc.steer_turn's v0.6.20 change reverted: a write that may have gone in would read as nothing written,
        and a caller could write it again."""
        channel = _Channel(steer=ipc._Failed(ipc.Stop.BROKEN))
        self.assertEqual(ipc.steer_turn(T1, WORDS, channel=channel), ipc.Stop.UNCONFIRMED)
        self.assertEqual(channel.written.count("thread-follower-steer-turn"), 1)
        self.assertEqual(ipc.steer_turn(T1, WORDS, channel=_Channel(steer=RuntimeError("cut"))), ipc.Stop.UNCONFIRMED)
        self.assertEqual(ipc.steer_turn(T1, WORDS, channel=_Channel()), ipc.Steer.STEERED)

    def test_each_word_of_the_pipe_comes_to_one_outcome(self):
        self.assertEqual(steer_engine.outcome(ipc.Steer.STEERED), (SteerState.ACCEPTED, None))
        self.assertEqual(steer_engine.outcome(ipc.Stop.UNCONFIRMED), (SteerState.UNCONFIRMED, None))
        self.assertEqual(steer_engine.outcome(ipc.Stop.NO_PIPE), (SteerState.REFUSED, SteerReason.NO_PIPE))
        self.assertEqual(steer_engine.outcome(ipc.Stop.NO_CLIENT), (SteerState.REFUSED, SteerReason.NOT_HELD))
        self.assertEqual(steer_engine.outcome(ipc.Stop.HELD), (SteerState.REFUSED, SteerReason.HELD))
        for word in (ipc.Stop.REFUSED, ipc.Stop.VERSION_MISMATCH, ipc.Stop.BROKEN, ipc.Stop.NO_ANSWER):
            self.assertEqual(steer_engine.outcome(word), (SteerState.REFUSED, SteerReason.APP_REFUSED))


class SteerCase(TakingCase):
    DEFINITION = STEER_SEND
    BESIDE = (PROMPT_QUEUE,)

    def setUp(self):
        super().setUp()
        self.measured = {Measurement.MIPC: (Verdict.PASS, ac.ENGINE), Measurement.MSTEER2: (Verdict.FAIL, ac.ENGINE),
                         Measurement.MT: (Verdict.PASS, ac.ENGINE)}
        self.status = "inProgress"
        self.holders = 1
        self.app_holds = True
        self.answer = ipc.Steer.STEERED
        self.calls = []
        # A fakeipc.FakeApp to steer through for real, "none" for a pipe that is not there, or None for `answer`.
        self.app = None
        for target, name, value in ((steer_engine, "latest_status", lambda home, thread: self.status),
                                    (steer_control, "latest_status", lambda home, thread: self.status),
                                    (steer_engine, "holders", lambda home, thread: self.holders),
                                    (steer_engine, "held_by_app", lambda paths, thread: self.app_holds),
                                    (steer_engine.ipc, "steer_turn", self.steer)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def steer(self, thread, text, *, message=None, channel=None, gate=None):
        self.calls.append((thread, text, message))
        if self.app is not None:
            if self.app == "none":
                with mock.patch.object(ipc, "PIPE", r"\\.\pipe\car-test-steer-none-%d" % id(self)):
                    return REAL_STEER(thread, text, message=message, gate=gate)
            return REAL_STEER(thread, text, message=message, channel=ipc.Channel(self.app.name), gate=gate)
        if gate is not None:
            with gate() as permitted:
                if permitted is not True:
                    return ipc.Stop.HELD
        answer = self.answer
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def on(self):
        plug = self.armed()
        return plug, plug.runtime

    def ask(self, runtime, words=WORDS, thread=T1):
        return surfaces.bridge(runtime, "advanced-steer", {"thread_id": thread, "words": words,
                                                           "generation": runtime.state.meta()["generation"]})

    def rows(self, runtime):
        return runtime.state.steers(0)


class SendTests(SteerCase):
    def test_the_arming_flow_carries_msteer2s_warning_and_turns_it_on_once_confirmed(self):
        plug = self.advanced()
        self.arm(plug, capability="prompt_queue")
        warnings = plug.runtime.arming.warnings(STEER_SEND)
        self.assertIn(ArmingWarning.MEASUREMENT_FAILED, warnings)
        refused = plug.runtime.arming.arm("steer_send", state="armed", revision=1,
                                          generation=plug.runtime.state.meta()["generation"],
                                          acknowledged_version=ac.ENGINE, warnings=[], actor=Actor.DASHBOARD)
        self.assertFalse(refused["done"], "unconfirmed, the warning is shown again")
        self.assertIn(str(ArmingWarning.MEASUREMENT_FAILED), refused["warnings"])
        self.arm(plug)
        self.assertEqual(plug.runtime.states(fresh=True)["steer_send"], "armed")

    def test_one_request_is_written_exactly_once_by_the_watcher(self):
        plug, runtime = self.on()
        asked = self.ask(runtime)
        self.assertTrue(asked["done"], asked)
        self.assertEqual(self.calls, [], "the bridge sends nothing")
        (row,) = self.rows(runtime)
        self.assertEqual(row["state"], SteerState.REQUESTED)
        self.h.tick()
        self.assertEqual(self.calls, [(T1, WORDS, row["client_id"])])
        for _ in range(3):
            self.h.tick(advance=5)
        self.assertEqual(len(self.calls), 1, "never asked again")
        (row,) = self.rows(runtime)
        self.assertEqual((row["state"], row["reason"], row["words"]), (SteerState.ACCEPTED, None, WORDS))
        self.assertIsNotNone(row["finished_at"])

    def test_an_unanswered_write_is_may_have_been_delivered_and_never_written_again(self):
        for answer in (ipc.Stop.UNCONFIRMED, RuntimeError("the pipe broke")):
            with self.subTest(answer=answer):
                self.calls.clear()
                self.h = self.fresh()
                plug, runtime = self.on()
                self.answer = answer
                self.assertTrue(self.ask(runtime)["done"])
                for _ in range(4):
                    self.h.tick(advance=5)
                self.assertEqual(len(self.calls), 1)
                (row,) = self.rows(runtime)
                self.assertEqual(row["state"], SteerState.UNCONFIRMED)

    def test_a_watcher_stopped_after_the_claim_never_writes_it(self):
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        (row,) = self.rows(runtime)
        self.assertTrue(runtime.state.claim_steer(row["steer_id"]), "claimed, then the watcher stopped")
        self.assertFalse(runtime.state.claim_steer(row["steer_id"]), "one claim")
        self.h.tick()
        self.assertEqual(self.calls, [])
        (row,) = self.rows(runtime)
        self.assertEqual(row["state"], SteerState.UNCONFIRMED, "it may have been written")

    def test_a_steer_another_errand_claimed_is_not_written(self):
        """Fails with the claim taken out of engine/steer.py: two errands could write one steer."""
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        with mock.patch.object(type(runtime.state), "claim_steer", lambda state, steer_id: False):
            self.h.tick()
        self.assertEqual(self.calls, [])

    def test_refused_with_why_where_no_turn_runs_or_the_app_does_not_hold_it(self):
        for change, reason in ((dict(status="completed"), SteerReason.NO_TURN),
                               (dict(holders=0), SteerReason.NOT_HELD),
                               (dict(holders=None), SteerReason.NOT_HELD),
                               (dict(app_holds=False), SteerReason.NOT_HELD),
                               (dict(answer=ipc.Stop.NO_PIPE), SteerReason.NO_PIPE),
                               (dict(answer=ipc.Stop.NO_CLIENT), SteerReason.NOT_HELD),
                               (dict(answer=ipc.Stop.VERSION_MISMATCH), SteerReason.APP_REFUSED)):
            with self.subTest(change=change):
                self.calls.clear()
                self.status, self.holders, self.app_holds, self.answer = "inProgress", 1, True, ipc.Steer.STEERED
                self.h = self.fresh()
                plug, runtime = self.on()
                self.assertTrue(self.ask(runtime)["done"])
                for name, value in change.items():
                    setattr(self, name, value)
                self.h.tick()
                (row,) = self.rows(runtime)
                self.assertEqual((row["state"], row["reason"]), (SteerState.REFUSED, reason))
                written = "answer" in change
                self.assertEqual(len(self.calls), 1 if written else 0, "checked before anything is written")

    def test_a_steer_waits_two_minutes_at_most(self):
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        self.h.now += steer_engine.EXPIRES + 1
        self.h.tick()
        (row,) = self.rows(runtime)
        self.assertEqual((row["state"], row["reason"]), (SteerState.REFUSED, SteerReason.EXPIRED))
        self.assertEqual(self.calls, [])

    def test_a_pause_holds_it_and_nothing_is_written(self):
        """Paused, the watcher asks nothing of the plug: nothing is written; resumed within two minutes, it goes once."""
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        self.h.store.set_enabled(False, self.h.now)
        self.h.tick()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.rows(runtime)[0]["state"], SteerState.REQUESTED)
        self.h.store.set_enabled(True, self.h.now)
        self.h.tick()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.rows(runtime)[0]["state"], SteerState.ACCEPTED)

    def test_cores_guard_refusing_it_writes_nothing_and_says_held(self):
        """Observe only, quiet hours or an administrator's DisableAutoResume refuse the errand's guard: never written."""
        from contextlib import contextmanager
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])

        @contextmanager
        def refused():
            yield False
        written = []
        with mock.patch.object(steer_engine.ipc, "steer_turn", lambda *a, gate=None, **k: (
                written.append(1) if gate is None else None) or REAL_STEER(*a, gate=gate, channel=_Channel(), **k)):
            ac.code_of(runtime, "steer_send").send(mock.MagicMock(thread_enabled=lambda thread: True), refused)
        (row,) = self.rows(runtime)
        self.assertEqual((row["state"], row["reason"]), (SteerState.REFUSED, SteerReason.HELD))
        self.assertEqual(written, [])

    def test_turned_off_a_waiting_steer_is_refused_and_never_sent(self):
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        runtime.arming.disarm("steer_send", actor=Actor.DASHBOARD)
        runtime.states(fresh=True)
        runtime.arming.sweep(mock.MagicMock())
        self.h.tick()
        (row,) = self.rows(runtime)
        self.assertEqual((row["state"], row["reason"]), (SteerState.REFUSED, SteerReason.TURNED_OFF))
        self.assertEqual(self.calls, [])

    def test_through_a_scratch_pipe_one_steer_request_reaches_the_owner(self):
        """The whole route, the pipe the test's own (fakeipc): initialize, the owner, one steer to that owner."""
        if sys.platform != "win32":
            self.skipTest("a Windows named pipe")
        import fakeipc
        self.app = fakeipc.FakeApp({})
        self.addCleanup(self.app.close)
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        self.h.tick()
        (row,) = self.rows(runtime)
        self.assertEqual(row["state"], SteerState.ACCEPTED)
        self.assertEqual([seen[0] for seen in self.app.seen].count("thread-follower-steer-turn"), 1)
        params = self.app.seen[-1][2]
        self.assertEqual((params["conversationId"], params["clientUserMessageId"]), (T1, row["client_id"]))
        self.assertEqual(params["input"][0]["text"], WORDS)

    def test_no_pipe_is_refused_and_says_so(self):
        if sys.platform != "win32":
            self.skipTest("a Windows named pipe")
        self.app = "none"
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        self.h.tick()
        (row,) = self.rows(runtime)
        self.assertEqual((row["state"], row["reason"]), (SteerState.REFUSED, SteerReason.NO_PIPE))


class RequestTests(SteerCase):
    def test_refused_at_once_where_no_turn_runs_and_nothing_waits(self):
        plug, runtime = self.on()
        self.status = "completed"
        asked = self.ask(runtime)
        self.assertEqual((asked["done"], asked["refusal"]), (False, "no_turn_running"))
        self.assertEqual(self.rows(runtime), [])

    def test_refused_unless_on_and_one_waits_at_most(self):
        plug = self.advanced()
        self.arm(plug, capability="prompt_queue")
        self.assertEqual(self.ask(plug.runtime)["refusal"], "not_on")
        plug, runtime = self.on()
        self.assertTrue(self.ask(runtime)["done"])
        self.assertEqual(self.ask(runtime)["refusal"], "being_sent", "one waiting in that conversation")
        self.assertEqual(self.ask(runtime, words="")["refusal"], "prompt_refused")
        self.assertEqual(self.ask(runtime, thread="not-a-thread")["refusal"], "invalid_request")

    def test_the_caps_hold_per_conversation(self):
        plug, runtime = self.on()
        for index in range(steer_engine.PER_CONVERSATION):
            runtime.state.add_steer(T1, "line %d" % index, "00000000-0000-7000-8000-%012d" % index, at=self.h.now - 60)
            runtime.state.settle_steer(index + 1, SteerState.REFUSED, SteerReason.NO_TURN, at=self.h.now - 59)
        self.assertEqual(self.ask(runtime)["refusal"], "queue_full")


class HistoryTests(SteerCase):
    def test_history_lists_each_steer_with_its_words_and_three_outcomes_never_folded(self):
        plug, runtime = self.on()
        made = []
        for index, (state, reason) in enumerate(((SteerState.ACCEPTED, None), (SteerState.UNCONFIRMED, None),
                                                 (SteerState.REFUSED, SteerReason.NOT_HELD))):
            steer = runtime.state.add_steer(T1, "words %d" % index, "00000000-0000-7000-8000-00000000000%d" % index,
                                            at=self.h.now + index)
            if state != SteerState.REFUSED:
                self.assertTrue(runtime.state.claim_steer(steer))
            self.assertTrue(runtime.state.settle_steer(steer, state, reason, at=self.h.now + index + 1))
            made.append(steer)
        waiting = runtime.state.add_steer(T1, "still to go", "00000000-0000-7000-8000-000000000009", at=self.h.now + 9)
        shown = surfaces.bridge(runtime, "advanced-prompts", {})
        self.assertTrue(shown["done"])
        steers = shown["steers"]
        self.assertEqual([row["steer_id"] for row in steers], [waiting] + made[::-1], "newest first")
        self.assertEqual([row["state"] for row in steers],
                         ["requested", "refused", "unconfirmed", "accepted"])
        self.assertEqual([row["words"] for row in steers], ["still to go", "words 2", "words 1", "words 0"])
        self.assertEqual(steers[1]["reason"], "not_held")
        self.assertEqual({row["thread_id"] for row in steers}, {T1})
        self.assertEqual(surfaces.status(runtime).get("steers_waiting"), 1)

    def test_only_a_claimed_steer_settles_accepted_or_unconfirmed(self):
        plug, runtime = self.on()
        steer = runtime.state.add_steer(T1, WORDS, "00000000-0000-7000-8000-000000000001")
        self.assertFalse(runtime.state.settle_steer(steer, SteerState.ACCEPTED), "never written, never accepted")
        self.assertTrue(runtime.state.claim_steer(steer))
        self.assertTrue(runtime.state.settle_steer(steer, SteerState.ACCEPTED))
        self.assertFalse(runtime.state.settle_steer(steer, SteerState.REFUSED, SteerReason.NO_TURN), "settled once")


if __name__ == "__main__":
    unittest.main()
