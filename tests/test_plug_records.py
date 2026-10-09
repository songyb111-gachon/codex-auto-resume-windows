"""P2 carried out (v0.6.14): a record of the edition's plug's own - a message a person wrote - tried like
core's own records, through core's gates, the one claim and the one send, and watched until it is found.

The plug here is a test's own (`Records`): it hands over the records it is told to, claims at P11 what
it is asked to, and keeps every move core tells it at P14. Nothing reaches a real Codex: the engine runs
against codexsim, as every engine scenario does.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from test_engine import T1, T2, EngineCase  # noqa: E402
from test_plug_points import Asked, PluggedCase  # noqa: E402
from codex_auto_resume import continuation, l10n  # noqa: E402
from codex_auto_resume.domain import ids, plughands  # noqa: E402
from codex_auto_resume.domain.plug import (ALTERNATIVES, BACKEND, DEFER, Alternative, Point, RecordMove,  # noqa: E402
                                           guard)

KEY = "c0ffee11" * 8
OTHER = "beef2222" * 8
WORDS = "Please pick up where we left off: run the tests again."


def record(key=KEY, thread=T1, words=WORDS, state="waiting", sent_at=None, **changes):
    made = {"record_id": key, "thread_id": thread, "marker": ids.short_marker(key), "state": state,
            "words": words, "sent_at": sent_at}
    made.update(changes)
    return made


class Records(Asked):
    """A plug with records of its own: `handed` is what P2 answers, `ledger` what P11 answers to a
    record's claim and launch (DEFER: claimed), and `moves` every move core tells of one."""
    __slots__ = ("handed", "ledger", "moves", "phases")

    def __init__(self, handed=(), *, ledger=DEFER, **answers):
        super().__init__(**answers)
        self.handed, self.ledger, self.moves, self.phases = list(handed), ledger, [], []

    def records(self, view):
        self.asked.append(("records", (view,)))
        return list(self.handed)

    def claim_ledger(self, connection, record, now, carried):
        self.asked.append(("claim_ledger", (connection, record, now, carried)))
        if isinstance(record, dict) and "phase" in record:
            self.phases.append((record["phase"], record["record_id"], carried))
            answer = self.ledger
            if isinstance(answer, Exception):
                raise answer
            return answer(record) if callable(answer) else answer
        return DEFER

    def moved(self, record, state):
        self.asked.append(("moved", (record, state)))
        if isinstance(record, dict) and "record_id" in record:
            self.moves.append((str(state), record.get("gate"), record.get("reason")))


class RecordCase(PluggedCase):
    def setUp(self):
        super().setUp()
        self.h.home.add_turn(T1)
        self.h.backend.loaded_map[T1] = "loaded"

    def plug(self, *handed, h=None, **answers):
        made = Records(handed or (record(),), **answers)
        self.plugged(made, h)
        return made


class WaitingTests(RecordCase):
    def test_the_words_a_blank_line_and_the_marker_go_once_through_the_one_send(self):
        plug = self.plug()
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [(T1, WORDS + "\n\n" + ids.short_marker(KEY))])
        self.assertEqual(plug.moves, [("sent", None, None)])
        self.assertEqual([phase for phase, _key, _carried in plug.phases], ["claim", "launch"])
        self.assertEqual({carried for _p, _k, carried in plug.phases}, {frozenset({Point.RECORDS})})

    def test_each_gate_holds_it_and_says_which(self):
        cases = {
            "paused": (lambda h: h.store.set_enabled(False, h.now), None),        # P2 is not asked then
            "thread off": (lambda h: h.store.set_thread_enabled(T1, False, at=h.now), ("consent", "thread_disabled")),
            "quiet hours": (lambda h: setattr(h.engine, "quiet_until", lambda now: now + 60),
                            ("schedule", "quiet_hours")),
            "engine": (lambda h: setattr(h.engine, "engine_state", lambda: "incompatible"),
                       ("engine_compatible", "engine_incompatible")),
            "home lock": (lambda h: setattr(h.engine, "home_lock", lambda: False),
                          ("single_owner", "home_lock_unavailable")),
            "stale": (lambda h: h.home.make_stale(T1), ("identity", "projection_stale")),
            "no app": (lambda h: setattr(h.backend, "app", None), ("thread_available", "desktop_app_unavailable")),
            "not loaded": (lambda h: h.backend.loaded_map.update({T1: "notLoaded"}), ("thread_available", "notLoaded")),
            "queued": (lambda h: h.home.enqueue(T1, "someone else's"), ("no_newer_user_work", "user_input_queued")),
            "offline": (lambda h: setattr(h.engine, "offline", lambda: True), ("usage", "offline")),
            "no usage": (lambda h: h.backend.usage_result.update(available=False), ("usage", "usage_unavailable")),
        }
        for how, (make, said) in cases.items():
            with self.subTest(how):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.plug(h=h)
                make(h)
                h.tick()
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual(plug.phases, [], "never claimed")
                self.assertEqual(plug.moves, [] if said is None else [("waiting",) + said])

    def test_nothing_of_cores_in_flight_in_the_conversation_and_the_claim_asks_again(self):
        self.send_and_hold()                                  # core's own continuation, queued on T1
        plug = self.plug()
        self.h.tick()
        self.assertEqual(len(self.h.backend.send_calls), 1, "only core's")
        self.assertEqual(plug.moves, [("waiting", "submission_safe", "other_recovery_in_flight")])
        key = self.h.record()["interruption_id"]
        self.assertTrue(self.h.store.others_in_flight(T1, KEY))
        self.assertEqual(self.h.store.reserve_record(record(), self.h.now, ledger=guard(plug)),
                         (False, "submission_safe", "other_recovery_in_flight"))
        self.assertIsNotNone(key)

    def test_a_ledger_that_holds_or_raises_holds_it_and_null_claims_none(self):
        for ledger in (Alternative.HOLD, RuntimeError("broken ledger")):
            with self.subTest(ledger=ledger):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.plug(h=h, ledger=ledger)
                h.tick()
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual(plug.moves, [("waiting", "submission_safe", "held")])
        self.assertEqual(self.h.store.reserve_record(record(), self.h.now, ledger=None),
                         (False, "submission_safe", "held"))

    def test_the_claim_reads_consent_and_quiet_hours_again(self):
        plug = Records()
        self.h.store.set_thread_enabled(T1, False, at=self.h.now)
        self.assertEqual(self.h.store.reserve_record(record(), self.h.now, ledger=guard(plug)),
                         (False, "consent", "thread_disabled"))
        self.h.store.set_thread_enabled(T1, True, at=self.h.now)
        self.assertEqual(self.h.store.reserve_record(record(), self.h.now, ledger=guard(plug),
                                                     quiet_until=self.h.now + 60),
                         (False, "schedule", "quiet_hours"))
        self.assertEqual(self.h.store.reserve_record(record(), self.h.now, ledger=guard(plug)), (True, None, None))

    def test_a_pause_or_the_conversation_switched_off_before_the_launch_sends_nothing(self):
        for how in ("pause after the claim", "switched off at the launch"):
            with self.subTest(how):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.plug(h=h)
                if how == "pause after the claim":
                    real = h.store.reserve_record

                    def reserve(*arguments, **keywords):
                        found = real(*arguments, **keywords)
                        h.store.set_enabled(False, h.now)
                        return found
                    patch.object(h.store, "reserve_record", reserve).start()
                    self.addCleanup(patch.stopall)
                else:
                    real_look = h.engine._record_problem

                    def look(record_, app):
                        found = real_look(record_, app)
                        h.store.set_thread_enabled(T1, False, at=h.now)
                        return found
                    h.engine._record_problem = look
                h.tick()
                self.assertEqual(h.backend.send_calls, [])
                self.assertEqual(plug.moves[-1][0], "released")

    def test_what_came_of_the_send_is_told(self):
        for outcome, move in (("accepted", "sent"), ("unknown", "sent"), ("not_started", "not_started"),
                              ("raise", "sent")):
            with self.subTest(outcome):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                h.backend.default_outcome = outcome
                plug = self.plug(h=h)
                h.tick()
                self.assertEqual(plug.moves, [(move, None, None)])

    def test_observe_only_sends_nothing_and_says_so_once(self):
        self.h.store.set_observe_only(True)
        plug = self.plug()
        self.h.tick()
        self.h.tick(advance=60)
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(plug.moves, [("waiting", "consent", "observe_only")] * 2)
        self.assertEqual([entry for entry in self.h.logs if entry[1] == "plug_record_would_send"],
                         [(T1, "plug_record_would_send", None)])

    def test_a_channel_named_for_one_is_never_used(self):
        sent = []

        class Channel:
            def send(self, *arguments, **keywords):
                sent.append(arguments)
                return {"outcome": "accepted"}
        plug = self.plug(sender=Channel())
        self.h.tick()
        self.assertEqual((sent, self.h.backend.send_calls), ([], []))
        self.assertEqual(plug.moves, [("waiting", "submission_safe", "held")])
        self.assertEqual(plug.phases, [])

    def test_no_words_channel_route_or_delivery_of_the_plugs_is_asked_for_one(self):
        plug = self.plug(text="other words", delivery=Alternative.CLIENT_ID)
        self.h.tick()
        asked = [hook for hook, arguments in plug.asked
                 if arguments and isinstance(arguments[0], dict) and "record_id" in arguments[0]]
        self.assertNotIn("text", asked)
        self.assertNotIn("delivery", asked)
        self.assertNotIn("unloaded", asked)
        self.assertNotIn("schedule", asked)
        self.assertEqual(self.h.backend.send_calls[0][1], WORDS + "\n\n" + ids.short_marker(KEY))

    def test_a_copy_of_its_marker_in_codex_already_is_sent_not_a_second_send(self):
        self.h.home.enqueue(T1, WORDS + "\n\n" + ids.short_marker(KEY))
        plug = self.plug()
        self.h.tick()
        self.assertEqual(self.h.backend.send_calls, [])
        self.assertEqual(plug.moves, [("sent", "submission_safe", "duplicate_owner")])


    def test_a_record_whose_words_fail_is_never_tried(self):
        for words in ("[codex-auto-resume:00", continuation.build("usage_limit", style="minimal")):
            with self.subTest(words=words[:30]):
                h = self.fresh()
                h.home.add_turn(T1)
                h.backend.loaded_map[T1] = "loaded"
                plug = self.plug(record(words=words), h=h)
                h.tick()
                self.assertEqual((h.backend.send_calls, plug.moves, plug.phases), ([], [], []))


class InFlightTests(RecordCase):
    def test_its_marker_in_codex_history_is_delivered(self):
        plug = self.plug()
        self.h.tick()                                          # sent, and the app took it at once
        plug.handed = [record(state="in_flight", words=None, sent_at=self.h.now)]
        plug.moves.clear()
        self.h.tick(advance=5)
        self.assertEqual(plug.moves, [("delivered", None, None)])
        self.assertEqual(len(self.h.backend.send_calls), 1, "never sent again")

    def test_none_a_day_after_it_was_sent_is_unproven_and_never_sent_again(self):
        plug = self.plug(record(state="in_flight", words=None, sent_at=self.h.now - 86400 + 30))
        self.h.tick()
        self.assertEqual(plug.moves, [])
        self.h.tick(advance=60)
        self.assertEqual(plug.moves, [("unproven", None, None)])
        self.assertEqual(self.h.backend.send_calls, [])


class CheckedTests(unittest.TestCase):
    """What core takes from P2's answer (plughands.records_of), and the words it sends (validate_prompt)."""

    def test_records_leave_the_decision_table_for_a_value_core_checks(self):
        self.assertNotIn(Point.RECORDS, ALTERNATIVES)
        self.assertEqual(guard(Records([record()])).records(None), (record(),))
        self.assertEqual(guard(None).records(None), ())

    def test_a_malformed_record_is_dropped_and_the_rest_are_taken(self):
        bad = [record(marker=ids.marker(KEY)), record(key="A" * 64), record(key="ab"), record(thread="T1"),
               record(state="done"), record(words=None), record(words=""), record(words="x" * 8193),
               record(state="in_flight"), record(state="waiting", sent_at=5.0), dict(record(), extra=1),
               {k: v for k, v in record().items() if k != "sent_at"}, record(state="in_flight", words=None,
                                                                             sent_at="soon"), "record", None]
        for found in bad:
            with self.subTest(found=found):
                self.assertEqual(plughands.records_of([found]), ())
        good = record(OTHER)
        self.assertEqual(plughands.records_of([good] + bad), (good,))
        self.assertEqual(plughands.records_of(bad[:4] + [good]), (good,))
        self.assertEqual(plughands.records_of([record()] * 3), (record(),), "one id, once")
        many = [record("%016x" % n * 4) for n in range(1, 12)]
        self.assertEqual(len(plughands.records_of(many)), plughands.RECORDS_LIMIT)
        for answer in (DEFER, None, {"record_id": KEY}, "records", record()):
            self.assertEqual(plughands.records_of(answer), ())

    def test_a_record_core_takes_is_a_copy(self):
        handed = record()
        taken = plughands.records_of([handed])[0]
        handed["words"] = "changed afterwards"
        self.assertEqual(taken["words"], WORDS)

    def test_a_persons_words_are_sent_as_written_and_the_products_own_never_are(self):
        self.assertEqual(continuation.validate_prompt(WORDS), WORDS)
        self.assertEqual(continuation.validate_prompt("  {reason} as typed\n\tsecond line"), "  {reason} as typed\n\tsecond line")
        self.assertEqual(continuation.PROMPT_LIMIT, 8192 - len("\n\n" + ids.short_marker(KEY)))
        self.assertEqual(continuation.validate_prompt("x" * continuation.PROMPT_LIMIT), "x" * continuation.PROMPT_LIMIT)
        refused = {"x" * (continuation.PROMPT_LIMIT + 1): "too_long", "   \n\t": "empty", "": "empty",
                   "a\x00b": "control", "a\x1bb": "control", "a\x7fb": "control", 5: "not_text",
                   "see " + ids.short_marker(KEY): "marker", "[codex-auto-resume:": "marker"}
        minimal = l10n.text("continuation.minimal", "ko")
        refused[minimal] = "product_text"
        refused["  " + continuation.build("usage_limit", locale="de", style="standard").upper() + " "] = "product_text"
        for text, code in refused.items():
            with self.subTest(text=str(text)[:40]):
                with self.assertRaises(continuation.PromptError) as raised:
                    continuation.validate_prompt(text)
                self.assertEqual(raised.exception.code, code)

    def test_the_backend_stands_in_for_the_sender_as_ever(self):
        self.assertIs(guard(Records()).sender(record(), "backend"), "backend")
        self.assertIsNot(BACKEND, None)


if __name__ == "__main__":
    unittest.main()
