"""Open a waiting conversation in Codex (v0.6.19, issue #50, open_to_send): a recovery or a scheduled message that waits
only because the Codex app does not have its conversation open gets that exact conversation opened through Codex's own
link - once, only where the app is KNOWN not to hold it, only while the PC is idle, the `codex:` handler registered and
Codex running (unless Also start Codex is on) - with its caps kept on disk; and nothing is sent until core's own loaded
check passes on a later tick: opening is never proof of loading. Built, and hidden until MOPEN passes.

Held against core's own engine, store and simulated Codex home (takingcase.py); Windows - the idle time, the handler, the
app's processes and the link itself - is the test's own (the module's seams), so nothing here opens anything.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src;tests" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from codex_auto_resume import machine  # noqa: E402
from codex_auto_resume_advanced import registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import opentarget  # noqa: E402
from codex_auto_resume_advanced.registry import OPEN_TO_SEND, QUEUE_FOR_OPEN, Registry, offered, problems  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, Measurement, OpenOutcome, OptionKey, Verdict  # noqa: E402
from codex_auto_resume import l10n  # noqa: E402
from test_engine import T1  # noqa: E402


class HiddenTests(unittest.TestCase):
    def test_it_waits_hidden_on_mopen_and_is_offered_whole_on_a_pass(self):
        """Fails with the gate reverted: a capability whose route is not measured would be offered."""
        self.assertIsNone(registry.REGISTRY.get("open_to_send"))
        self.assertNotIn(OPEN_TO_SEND, registry.DEFINITIONS)
        self.assertIn((OPEN_TO_SEND, Measurement.MOPEN), registry.WAITING)
        self.assertEqual(offered({}), ())
        self.assertEqual(offered({Measurement.MOPEN: (Verdict.FAIL, "x")}), ())
        let_out = offered({Measurement.MOPEN: (Verdict.PASS, "x")})
        self.assertEqual(let_out, (OPEN_TO_SEND,))
        made = Registry(registry.DEFINITIONS + let_out)
        shown = [definition.id for definition in registry.shown(made)]
        self.assertEqual(shown[shown.index("queue_for_open") + 1], "open_to_send", "placed after queue for opening")

    def test_its_definition_and_statement_are_complete(self):
        self.assertEqual(problems(OPEN_TO_SEND), [])
        self.assertEqual(OPEN_TO_SEND.departs_from, ("0.5", "B16", "C4", "F6"))
        self.assertEqual(OPEN_TO_SEND.measurements, (Measurement.MOPEN,))
        self.assertEqual(statement.CATALOGS.missing(OPEN_TO_SEND), [])
        for locale in l10n.LOCALES:
            with self.subTest(locale):
                own = statement.CATALOGS.own(locale)
                self.assertTrue(own[statement.name_key("open_to_send")].strip())
                for key in ("page.option.open_idle_minutes", "page.option.open_start_codex"):
                    self.assertTrue(own[key].strip())
        options = {option.key: option for option in OPEN_TO_SEND.options}
        self.assertEqual((options[OptionKey.OPEN_IDLE_MINUTES].choices, options[OptionKey.OPEN_IDLE_MINUTES].default),
                         ((2, 5, 15), 5))
        self.assertEqual(options[OptionKey.OPEN_START_CODEX].default, opentarget.OFF, "off by default")


class CandidateTests(unittest.TestCase):
    """The candidate rule alone, on core's own stored vector."""

    def row(self, available, state="waiting_for_loaded_thread", **other):
        gates = {"thread_available": list(available)}
        gates.update({name: list(value) for name, value in other.items()})
        import json
        return {"state": state, "gate_eval": json.dumps(gates), "queue_id": None, "thread_id": T1,
                "interruption_id": "i1"}

    def test_known_not_loaded_alone_is_a_candidate(self):
        self.assertEqual(opentarget.core_candidate(self.row((machine.WAIT, "notLoaded"), consent=(machine.PASS, "ok")),
                                                   False), "waiting")

    def test_unknown_or_ambiguous_never_opens(self):
        """Fails with the rule loosened to any thread_available wait: an unknown loaded state would open."""
        for available in ((machine.UNKNOWN, "loaded_state_unknown"), (machine.WAIT, "held_by_other_session"),
                          (machine.UNKNOWN, "not_checked")):
            with self.subTest(available=available):
                self.assertIsNone(opentarget.core_candidate(self.row(available), True))

    def test_any_other_failing_gate_is_no_candidate(self):
        row = self.row((machine.WAIT, "notLoaded"), attempt_budget=(machine.WAIT, "daily_submission_cap"))
        self.assertIsNone(opentarget.core_candidate(row, False))

    def test_the_app_closed_is_one_only_with_also_start_codex(self):
        row = self.row((machine.WAIT, "desktop_app_unavailable"), state="waiting_for_app")
        self.assertIsNone(opentarget.core_candidate(row, False))
        self.assertEqual(opentarget.core_candidate(row, True), "waiting")

    def test_a_message_held_for_a_running_turn_is_none(self):
        row = {"record_state": "waiting", "gate": "thread_available", "gate_reason": "notLoaded", "reason": None}
        self.assertTrue(opentarget.own_candidate(row, False))
        self.assertFalse(opentarget.own_candidate(dict(row, reason="turn_running"), False))
        self.assertFalse(opentarget.own_candidate(dict(row, gate_reason="loaded_state_unknown"), True))


class OpenCase(TakingCase):
    DEFINITION = OPEN_TO_SEND

    def setUp(self):
        super().setUp()
        self.idle = 3600.0
        self.handler = True
        self.running = True
        self.opened = []
        self.loads = True
        for name, value in (("idle_seconds", lambda: self.idle), ("handler_registered", lambda: self.handler),
                            ("app_running", lambda: self.running), ("open_link", self.open_link)):
            patcher = mock.patch.object(opentarget, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def open_link(self, thread_id):
        self.opened.append(thread_id)
        if self.loads:
            self.h.backend.loaded_map[thread_id] = "loaded"
        return True

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(word) for word in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def waiting(self):
        """A usage-limited conversation past its reset that the running app does not hold: it waits for it (A11)."""
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.tick()
        self.assertEqual(self.h.record()["last_error"], "notLoaded")

    def opens(self, plug):
        return plug.runtime.state.opens(0)


class OpenTests(OpenCase):
    def test_it_opens_the_exact_conversation_once_and_core_sends_on_a_later_tick(self):
        """Fails with the capability reverted: the conversation waits for a person to open it."""
        plug = self.armed()
        self.waiting()
        self.h.tick(advance=5)
        self.assertEqual(self.opened, [T1], "opened at the next tick's errand, once the gates said why it waits")
        self.assertEqual(self.h.backend.send_calls, [], "nothing sent on the open itself")
        self.h.tick(advance=61)
        self.assertEqual(len(self.h.backend.send_calls), 1, "the ordinary next check found it loaded and sent")
        self.assertEqual([row["outcome"] for row in self.opens(plug)], [OpenOutcome.LOADED])
        self.assertEqual(self.opened, [T1], "once")

    def test_opening_is_never_proof_of_loading(self):
        """The link opened and the conversation still not loaded: nothing is sent, and after two looks it is not_loaded."""
        plug = self.armed()
        self.loads = False
        self.waiting()
        for _ in range(3):
            self.h.tick(advance=5)
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual([row["outcome"] for row in self.opens(plug)], [OpenOutcome.NOT_LOADED])

    def test_off_or_watched_it_never_opens(self):
        self.plugged(self.advanced())
        self.waiting()
        self.assertEqual(self.opened, [])

    def test_watched_it_never_opens(self):
        self.armed(state="shadow")
        self.waiting()
        self.h.tick(advance=5)
        self.assertEqual(self.opened, [])

    def test_unknown_loaded_state_never_opens(self):
        self.armed()
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "ambiguous"
        for _ in range(3):
            self.h.tick(advance=60)
        self.assertEqual(self.opened, [])


class RuleTests(OpenCase):
    def test_only_while_the_pc_has_been_idle_for_the_minutes_chosen(self):
        plug = self.armed()
        self.idle = 4 * 60.0                                 # under the default five minutes
        self.waiting()
        self.assertEqual(self.opened, [])
        self.idle = None                                     # unknown never opens
        self.h.tick(advance=60)
        self.assertEqual(self.opened, [])
        self.choose(plug, OptionKey.OPEN_IDLE_MINUTES, 2)
        self.idle = 4 * 60.0
        self.h.tick(advance=60)
        self.assertEqual(self.opened, [T1])

    def test_never_without_a_codex_handler(self):
        self.armed()
        self.handler = False
        self.waiting()
        self.h.tick(advance=60)
        self.assertEqual(self.opened, [])

    def test_codex_not_running_holds_it_unless_also_start_codex(self):
        plug = self.armed()
        self.running = None                                  # the process list unreadable: not known to run
        self.waiting()
        self.assertEqual(self.opened, [])
        self.choose(plug, OptionKey.OPEN_START_CODEX, opentarget.ON)
        self.h.tick(advance=60)
        self.assertEqual(self.opened, [T1])

    def test_with_also_start_codex_a_closed_app_is_opened_at_the_conversation(self):
        plug = self.armed()
        self.choose(plug, OptionKey.OPEN_START_CODEX, opentarget.ON)
        self.running = False
        self.ready_after_reset(loaded=False)
        self.h.backend.app = None                            # Codex closed: nothing is loaded
        self.h.tick()
        self.assertEqual(self.h.record()["last_error"], "desktop_app_unavailable")
        self.h.tick(advance=5)
        self.assertEqual(self.opened, [T1])

    def test_a_pause_holds_it(self):
        """A Pause beats every capability: core asks the plug nothing while recovery is paused."""
        self.armed()
        self.idle = 0.0
        self.waiting()
        self.h.store.set_enabled(False, self.h.now)
        self.idle = 3600.0
        for _ in range(3):
            self.h.tick(advance=60)
        self.assertEqual(self.opened, [])


class CapTests(OpenCase):
    def test_the_caps_hold_and_are_kept_across_a_restart(self):
        """Ten minutes between opens, an hour a conversation, three a record: kept on disk, so a watcher that starts again
        keeps them. Fails with the caps read from memory: the new process would open again at once."""
        plug = self.armed()
        self.loads = False
        self.waiting()
        self.h.tick(advance=5)
        self.assertEqual(len(self.opened), 1)
        for _ in range(5):
            self.h.tick(advance=60)
        self.assertEqual(len(self.opened), 1, "an hour between two opens of one conversation")
        again = self.armed()                                 # a new process on the same home
        self.assertEqual(len(self.opens(again)), 1)
        self.h.tick(advance=60)
        self.assertEqual(len(self.opened), 1, "the restart keeps the caps")
        for _ in range(4):
            self.h.tick(advance=3601)
        self.assertEqual(len(self.opened), opentarget.PER_RECORD, "three for one record, and no more")

    def test_a_dozen_a_day_and_ten_minutes_apart(self):
        plug = self.armed()
        state = plug.runtime.state
        for index in range(opentarget.PER_DAY):
            state.add_open("0a1b2c3d-0001-7000-8000-%012d" % (index + 10), "%064x" % (index + 1),
                           at=self.h.now - 3600 - index)
        self.waiting()
        self.assertEqual(self.opened, [], "twelve in the last day")


class ComposeTests(OpenCase):
    BESIDE = (QUEUE_FOR_OPEN,)

    def test_opening_delivers_what_queue_for_opening_queued_and_nothing_is_sent_twice(self):
        """Both on (memory capabilities-compose): queue_for_open queues the continuation for when the conversation is
        opened, and open_to_send opens it - the open is the trigger, so the one queued item is all that is sent."""
        plug = self.armed()
        self.ready_after_reset(loaded=False)
        self.h.backend.loaded_map[T1] = "notLoaded"
        self.h.backend.after_accept = "queue"
        self.h.tick()
        row = self.h.record()
        self.assertEqual(row["state"], "queued", row["last_error"])
        self.assertEqual(len(self.h.backend.send_calls), 1)
        self.h.tick(advance=5)
        self.assertEqual(self.opened, [T1])
        for _ in range(3):
            self.h.tick(advance=5)
        self.assertEqual(len(self.h.backend.send_calls), 1, "no second send")


if __name__ == "__main__":
    unittest.main()
