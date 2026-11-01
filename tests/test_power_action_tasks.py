"""v0.6.21 (Discussion #57): the power action armed for tasks a person picked - core's half.

The advanced edition's page arms core's one power action for tasks a person picked (`tasks` True in the arming) and
its plug answers how they stand (P21, PowerTasks). Core keeps everything else: the stop for one batch, DisablePowerAction,
a pause, every recovery open anywhere waiting first, Codex's history and turns and queue, Windows' idle and the
countdown. These tests hold that half, and that the standard edition is unchanged: an arming without `tasks` asks no
plug and decides exactly as before, the standard plug (NULL) can never write a tasks arming, and a file the standard
edition writes reads and shows byte for byte as it did.

The control layer is the real one on a scratch home; Windows is a fake port, Codex a fake engine, the store a fake
that hands out rows, and the plug a stand-in whose answers each test sets. Nothing here asks this PC anything.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import control, l10n, notify, poweraction  # noqa: E402
from codex_auto_resume.domain import plug as plugmodule  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, NULL, Plug, Point, guard  # noqa: E402
from codex_auto_resume.domain.power_vocabulary import PowerEnd, PowerTasks, PowerWait  # noqa: E402
from codex_auto_resume.runtime.afterwork import AfterWork  # noqa: E402
from test_power_action_control import CHOICE, FakePort as ControlPort, PowerControlCase  # noqa: E402
from test_power_action_watcher import HOUR, NONCE, OTHER_THREAD, THREAD, WatcherCase  # noqa: E402


class TasksPlug(Plug):
    """A plug that wants P21 (or not) and answers what a test sets, writing down each question."""
    __slots__ = ("wanted", "answer", "asked")

    def __init__(self, wanted=True, answer=DEFER):
        self.wanted, self.answer, self.asked = wanted, answer, []

    def wants(self, point):
        return self.wanted and point == Point.POWER

    def power(self, facts):
        self.asked.append(dict(facts))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def answer(word, threads=(THREAD,)):
    return {"tasks": word, "threads": list(threads)}


def armed(now, **changes):
    found = {"nonce": NONCE, "action": "sleep", "after": "all_recovered", "repeat": "once", "grace_seconds": 120,
             "armed_at": now - HOUR, "since": now - HOUR, "carried": [], "stop_at": None, "tasks": True}
    found.update(changes)
    return found


def document(arming):
    return {"format": poweraction.FORMAT, "armed": arming, "shown": None, "last": None}


# ------------------------------------------------------------------------------ the pure decision
class DecideTests(unittest.TestCase):
    """poweraction.decide for an arming for tasks: the plug's word, with core's records between, and core's own
    steps before it - each test fails with the tasks branch reverse-applied (the usage-limit batch decides instead)."""

    def setUp(self):
        self.now = 1_790_000_000.0

    def decide(self, tasks, rows=(), **facts):
        arming = facts.pop("arming", None) or armed(self.now)
        return poweraction.decide(poweraction.Facts(now=self.now, read=poweraction.READ_OK, document=document(arming),
                                                    rows=tuple(rows), tasks=tasks, **facts))

    def record(self, state, **changes):
        row = {"interruption_id": "%064x" % 7, "thread_id": OTHER_THREAD, "state": state, "category": "usage_limit",
               "detected_at": self.now - 600, "outcome_at": None, "last_error": None, "queue_id": None,
               "submitted_at": None}
        row.update(changes)
        return row

    def test_no_word_or_unknown_waits(self):
        """Condition 1 fails closed: the plug said nothing (off, unreadable) or could not tell."""
        for word in (None, PowerTasks.UNKNOWN.value, "done", 3):
            with self.subTest(word):
                self.assertEqual((self.decide(word).verdict, self.decide(word).word),
                                 (poweraction.WAIT, PowerWait.TASKS_UNKNOWN))

    def test_a_task_still_running_waits(self):
        found = self.decide(PowerTasks.RUNNING.value)
        self.assertEqual((found.verdict, found.word), (poweraction.WAIT, PowerWait.TASKS_RUNNING))

    def test_every_task_ended_as_counted_goes_on_to_codex_and_windows(self):
        self.assertEqual(self.decide(PowerTasks.MET.value).verdict, poweraction.GO)

    def test_one_ended_otherwise_ends_the_batch_not_met(self):
        found = self.decide(PowerTasks.NOT_MET.value)
        self.assertEqual((found.verdict, found.word), (poweraction.END, PowerEnd.NOT_MET))

    def test_a_recovery_open_anywhere_waits_first(self):
        """Condition 3: no recovery waiting or in flight anywhere - a watched task's own usage limit included."""
        for state in ("waiting_for_reset", "claimed", "following_recovery_turn"):
            with self.subTest(state):
                found = self.decide(PowerTasks.MET.value, rows=[self.record(state)])
                self.assertEqual((found.verdict, found.word), (poweraction.WAIT, PowerWait.RECOVERY_OPEN))
        found = self.decide(PowerTasks.NOT_MET.value, rows=[self.record("waiting_for_reset")])
        self.assertEqual(found.word, PowerWait.RECOVERY_OPEN, "a not-met ending waits for the recovery too")

    def test_an_uncertain_submission_followed_waits(self):
        row = self.record("submission_unknown", submitted_at=self.now - 600)
        found = self.decide(PowerTasks.MET.value, rows=[dict(row, state="submission_unknown")])
        self.assertEqual(found.verdict, poweraction.WAIT)

    def test_cores_own_steps_come_first(self):
        """Condition 8 (DisablePowerAction), a stop, a pause and a tick that failed, before the plug's word."""
        met = PowerTasks.MET.value
        self.assertEqual(self.decide(met, managed=True).verdict, poweraction.OFF)
        stopped = self.decide(met, arming=armed(self.now, stop_at=self.now - 5))
        self.assertEqual((stopped.verdict, stopped.word), (poweraction.END, PowerEnd.SKIPPED))
        self.assertEqual(self.decide(met, paused=True).word, PowerWait.PAUSED)
        self.assertEqual(self.decide(met, ok=False).verdict, poweraction.WAIT)

    def test_no_usage_limit_and_no_lapse_for_tasks(self):
        """A tasks arming has no batch of records: a day without a usage limit does not lapse it."""
        late = armed(self.now, armed_at=self.now - 3 * 24 * HOUR, since=self.now - 3 * 24 * HOUR)
        self.assertEqual(self.decide(PowerTasks.RUNNING.value, arming=late).word, PowerWait.TASKS_RUNNING)

    def test_an_arming_without_tasks_decides_as_it_always_did(self):
        """The standard edition unchanged: the plug's word is not read for any other arming."""
        plain = armed(self.now)
        del plain["tasks"]
        for word in (None, PowerTasks.MET.value, PowerTasks.NOT_MET.value, PowerTasks.RUNNING.value):
            with self.subTest(word):
                found = self.decide(word, arming=plain)
                self.assertEqual((found.verdict, found.word), (poweraction.WAIT, PowerWait.NO_BATCH))


class FileTests(unittest.TestCase):
    def setUp(self):
        self.now = 1_790_000_000.0

    def read(self, arming):
        return poweraction.read_document(json.loads(json.dumps(document(arming))), self.now)

    def test_a_tasks_arming_is_a_once_carrying_nothing_with_tasks_true(self):
        self.assertIsNotNone(self.read(armed(self.now)))
        for changes in ({"tasks": False}, {"tasks": 1}, {"tasks": "true"}, {"repeat": "always"},
                        {"carried": ["%064x" % 1]}):
            with self.subTest(changes):
                self.assertIsNone(self.read(armed(self.now, **changes)))

    def test_a_standard_file_reads_and_shows_as_before(self):
        plain = armed(self.now)
        del plain["tasks"]
        read = self.read(plain)
        self.assertEqual(read["armed"], plain)
        self.assertNotIn("tasks", poweraction.view(read)["armed"])
        self.assertEqual(poweraction.view(self.read(armed(self.now)))["armed"]["tasks"], True)
        self.assertNotIn("nonce", poweraction.view(self.read(armed(self.now)))["armed"])


# ------------------------------------------------------------------------------ the plug's answer, checked
class GuardTests(unittest.TestCase):
    def test_null_and_a_plug_that_does_not_want_it_are_never_asked(self):
        self.assertIsNone(guard(NULL).power({"nonce": NONCE}))
        quiet = TasksPlug(wanted=False, answer=answer("met"))
        self.assertIsNone(guard(quiet).power({"nonce": NONCE}))
        self.assertEqual(quiet.asked, [])
        self.assertIs(plugmodule.consult(NULL, Point.POWER, {}), DEFER)

    def test_only_the_exact_shape_is_taken(self):
        taken = guard(TasksPlug(answer=answer("met", (THREAD, THREAD, OTHER_THREAD)))).power({"nonce": NONCE})
        self.assertEqual(taken, {"tasks": "met", "threads": (THREAD, OTHER_THREAD)})
        for bad in (DEFER, None, "met", {"tasks": "met"}, {"tasks": "done", "threads": []},
                    {"tasks": "met", "threads": ["C:\\x"]}, {"tasks": "met", "threads": [THREAD] * 65},
                    {"tasks": "met", "threads": [], "more": 1}, RuntimeError("no")):
            with self.subTest(bad):
                self.assertIsNone(guard(TasksPlug(answer=bad)).power({"nonce": NONCE}))


# ------------------------------------------------------------------------------ the control layer
class ArmTests(PowerControlCase):
    def test_the_standard_plug_can_never_write_a_tasks_arming(self):
        code = self.refusal(self.control.arm_power_action, dict(CHOICE), tasks=True)
        self.assertEqual(code, "request_failed")
        self.assertFalse(self.file.exists())
        tired = control.Control(self.paths, plug=TasksPlug(wanted=False))
        tired.power_port = self.port
        self.assertEqual(self.refusal(tired.arm_power_action, dict(CHOICE), tasks=True), "request_failed")
        self.assertEqual(self.refusal(self.control.arm_power_action, dict(CHOICE), tasks="yes"), "request_failed")

    def test_a_plug_that_answers_arms_a_once_carrying_nothing(self):
        layer = control.Control(self.paths, plug=TasksPlug())
        layer.power_port = ControlPort()
        view = layer.arm_power_action(dict(CHOICE, repeat="always"), tasks=True)
        stored = self.stored()["armed"]
        self.assertIs(stored["tasks"], True)
        self.assertEqual((stored["repeat"], stored["carried"]), ("once", []))
        self.assertEqual(view["armed"]["tasks"], True)
        # One time: spent at its end, as any Once is.
        self.assertTrue(layer.power_batch_end(stored["nonce"], PowerEnd.NOT_MET.value))
        self.assertIsNone(self.stored()["armed"])

    def test_a_tasks_arming_is_stopped_for_its_batch_and_turned_off_anywhere(self):
        layer = control.Control(self.paths, plug=TasksPlug())
        layer.power_port = ControlPort()
        layer.arm_power_action(dict(CHOICE), tasks=True)
        nonce = self.stored()["armed"]["nonce"]
        self.assertEqual(layer.stop_power_countdown("0" * 16 if nonce != "0" * 16 else "1" * 16), "ignored")
        self.assertEqual(layer.stop_power_countdown(nonce, actor="card"), "stopped")
        self.assertIsNotNone(self.stored()["armed"]["stop_at"])
        self.assertEqual(self.control.disarm_power_action("tray"), {"changed": True})

    def test_a_standard_arming_is_written_as_before(self):
        self.arm()
        self.assertNotIn("tasks", self.stored()["armed"])


# ------------------------------------------------------------------------------ the watcher
class WatcherTests(WatcherCase):
    def setUp(self):
        super().setUp()
        self.plug = TasksPlug(answer=answer("met"))
        self.control = control.Control(self.paths, plug=self.plug)
        self.work = AfterWork(control=self.control, log=self.lines.append, notice=self.notice, port=self.port,
                              clock=lambda: self.clock[0])

    def arm_tasks(self, **changes):
        self.arm(tasks=True, **changes)

    def test_a_tasks_arming_asks_the_plug_with_its_nonce_and_times_only(self):
        self.arm_tasks()
        self.look()
        self.assertEqual(len(self.plug.asked), 1)
        self.assertEqual(set(self.plug.asked[0]), {"nonce", "armed_at", "now"})
        self.assertEqual(self.plug.asked[0]["nonce"], NONCE)

    def test_any_other_arming_never_asks_the_plug(self):
        self.ready()
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual(self.plug.asked, [], "the standard edition's arming asks nothing new")

    def test_met_counts_down_with_the_watched_threads_and_a_notice_for_the_tasks(self):
        self.plug.answer = answer("met", (THREAD, OTHER_THREAD))
        self.arm_tasks()
        self.look()
        self.assertTrue(self.work.counting)
        self.assertEqual(self.engine.asked[-1][0], tuple(sorted((THREAD, OTHER_THREAD))),
                         "condition 5: their histories caught up")
        grace = self.grace_notices()
        self.assertEqual(len(grace), 1)
        self.assertIs(grace[0][1].get("tasks"), True)
        self.assertEqual(grace[0][1]["nonce"], NONCE, "the Stop of this one batch")

    def test_conditions_two_and_four_any_turn_or_queued_input_waits(self):
        self.arm_tasks()
        for found, word in (({"history": True, "running": 1, "queued": 0}, PowerWait.TURN_RUNNING),
                            ({"history": True, "running": 0, "queued": 2}, PowerWait.QUEUED_INPUT),
                            ({"history": False, "running": None, "queued": None}, PowerWait.HISTORY_BEHIND)):
            with self.subTest(word):
                self.engine.answer = found
                self.look(advance=30.0)
                self.assertFalse(self.work.counting)
                self.assertEqual(self.stored()["shown"]["waiting_for"], word)

    def test_condition_six_nobody_used_the_pc_for_two_minutes(self):
        self.arm_tasks()
        self.port.idle = 30.0
        self.look()
        self.assertFalse(self.work.counting)
        self.assertEqual(self.stored()["shown"]["waiting_for"], PowerWait.PERSON_ACTIVE)

    def test_condition_seven_the_countdown_runs_out_and_acts_once(self):
        self.arm_tasks()
        self.count_down()
        self.assertEqual([event for event in self.events if event[0] == "act"], [("act", "sleep")])
        self.assertIsNone(self.stored()["armed"], "spent: one time")
        self.look(advance=30.0)
        self.assertEqual(len([event for event in self.events if event[0] == "act"]), 1)

    def test_a_stop_during_the_countdown_ends_that_batch_skipped(self):
        self.arm_tasks()
        self.look()
        self.assertTrue(self.work.counting)
        self.assertEqual(self.control.stop_power_countdown(NONCE, actor="toast"), "stopped")
        self.look(advance=15.0)
        self.assertFalse(self.work.counting)
        self.assertEqual(self.stored()["last"]["result"], PowerEnd.SKIPPED)
        self.assertNotIn("act", [event[0] for event in self.events])

    def test_running_or_no_answer_waits_and_does_nothing(self):
        self.arm_tasks()
        for word, waits in (("running", PowerWait.TASKS_RUNNING), (DEFER, PowerWait.TASKS_UNKNOWN),
                            (RuntimeError("no"), PowerWait.TASKS_UNKNOWN)):
            with self.subTest(waits):
                self.plug.answer = answer(word) if isinstance(word, str) else word
                self.look(advance=30.0)
                self.assertFalse(self.work.counting)
                self.assertEqual(self.stored()["shown"]["waiting_for"], waits)
        self.assertEqual(self.port.calls, [], "Windows is asked nothing while it waits")

    def test_not_met_ends_it_with_a_notice_for_the_tasks(self):
        self.plug.answer = answer("not_met")
        self.arm_tasks()
        self.look()
        self.assertIsNone(self.stored()["armed"])
        self.assertEqual(self.stored()["last"]["result"], PowerEnd.NOT_MET)
        not_met = [notice for notice in self.notices if notice[0] == "power_not_met"]
        self.assertEqual(len(not_met), 1)
        self.assertIs(not_met[0][1].get("tasks"), True)

    def test_disable_power_action_holds_it_and_asks_nothing(self):
        from codex_auto_resume import managed
        self.managed = managed.Managed(disable_power_action=True)
        self.arm_tasks()
        self.look()
        self.assertEqual((self.plug.asked, self.port.calls), ([], []))

    def test_nothing_is_sent(self):
        """The watcher's look has no send path: the engine is asked activity alone, and the plug its word."""
        self.arm_tasks()
        self.count_down()
        self.assertEqual({name for name in dir(self.engine) if name == "dispatch"}, set())
        self.assertTrue(all(len(call) == 2 for call in self.engine.asked))


class NoticeWordsTests(unittest.TestCase):
    def test_the_countdown_and_not_met_notices_say_they_are_for_the_tasks(self):
        tasks = notify.power_content("power_grace", {"action": "sleep", "until": 1_790_000_000.0, "nonce": NONCE,
                                                      "tasks": True})
        plain = notify.power_content("power_grace", {"action": "sleep", "until": 1_790_000_000.0, "nonce": NONCE})
        text = json.dumps(tasks, ensure_ascii=False)
        self.assertIn(l10n.message("toast_power_grace_body_tasks"), text)
        self.assertNotIn(l10n.message("toast_power_grace_body_tasks"), json.dumps(plain, ensure_ascii=False))
        self.assertIn(notify.power_stop_uri(NONCE), text, "the same Stop, for this batch")
        not_met = json.dumps(notify.power_content("power_not_met", {"action": "sleep", "tasks": True}),
                             ensure_ascii=False)
        self.assertIn(l10n.message("toast_power_not_met_tasks"), not_met)


if __name__ == "__main__":
    unittest.main()
