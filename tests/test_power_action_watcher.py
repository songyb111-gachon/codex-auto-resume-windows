"""v0.6.12: the watcher's side of the power action after usage-limit recoveries (runtime/afterwork.py).

AfterWork is asked once a tick, after keeping this PC awake, on the ticking thread. These tests hold what
it asks and in what order - nothing at all without a file, Codex and Windows only once every check of
its own has passed - how a countdown starts and every way it ends (a pause, Observe only, a tick that
failed, input, a gap between two looks, a new recovery, a stop), and how it acts: the end written in
the file before anything is done, the keep-awake request let go and the last notice raised before
Windows is asked, a write that fails doing nothing, a refusal said and never retried. Above all the
real click: pressing the notice's stop button is input too, and the two in one look end the batch
skipped - never an action, and never a second countdown.

The control layer is the real one, on a scratch home; Windows is a fake port, Codex a fake engine and the
store a fake that hands out rows. Nothing here asks this PC anything, and nothing can act: the real
port refuses inside a test, and none is used.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from codex_auto_resume import config, control, managed, notifier, poweraction, settings  # noqa: E402
from codex_auto_resume.control import poweraction as control_power  # noqa: E402
from codex_auto_resume.runtime import afterwork as afterwork_module, app as app_module, loop  # noqa: E402
from codex_auto_resume.runtime.afterwork import AfterWork  # noqa: E402
from codex_auto_resume.windows import AdapterError  # noqa: E402

THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
OTHER_THREAD = "0a1b2c3d-0002-7000-8000-000000000002"
NONCE = "fedcba9876543210"
HOUR = 3600.0


def key(n) -> str:
    return "%064x" % n


class FakePort:
    """win/powerdown.py's names, writing down every call, the thread it came from and what the file said."""

    def __init__(self, events, file):
        self.events, self.file = events, file
        self.calls, self.idle, self.others, self.offered, self.accepts = [], 600.0, 0, True, True
        self.error = 1314

    def _note(self, name, *values):
        self.calls.append((name, threading.get_ident()) + values)

    def available(self, action):
        self._note("available", action)
        return (True, None) if self.offered else (False, "no_privilege")

    def other_sessions(self):
        self._note("other_sessions")
        return self.others

    def idle_seconds(self):
        self._note("idle_seconds")
        return self.idle

    def act(self, action):
        stored = json.loads(self.file.read_text(encoding="utf-8")) if self.file.exists() else None
        self._note("act", action, stored)
        self.events.append(("act", action))
        return self.accepts

    def last_error(self):
        return self.error

    def names(self):
        return [call[0] for call in self.calls]


class FakeEngine:
    """engine.activity and the options the power action reads, from a test's own answers."""

    def __init__(self):
        self.options = {"unknown_reconcile_window_seconds": 24 * HOUR}
        self.answer = {"history": True, "running": 0, "queued": 0}
        self.asked = []

    def activity(self, threads=()):
        self.asked.append((tuple(threads), threading.get_ident()))
        return dict(self.answer)


class FakeStore:
    """The store's two reads the power action makes: the switches, and every record."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.switches = {"enabled": True, "observe_only": False}
        self.reads = 0

    def settings(self):
        return dict(self.switches)

    def all_records(self):
        self.reads += 1
        return [dict(row) for row in self.rows]


class FakeWaking:
    def __init__(self, events):
        self.events = events

    def let_go(self):
        self.events.append(("let_go",))


class WatcherCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.paths = config.Paths(Path(folder.name))
        self.paths.ensure()
        self.control = control.Control(self.paths)
        self.events, self.lines, self.notices = [], [], []
        self.port = FakePort(self.events, self.paths.power_action_file)
        self.engine, self.store = FakeEngine(), FakeStore()
        self.waking = FakeWaking(self.events)
        self.clock = [time.time()]
        self.work = AfterWork(control=self.control, log=self.lines.append, notice=self.notice,
                              port=self.port, clock=lambda: self.clock[0])
        self.settings = settings.defaults()
        self.managed = managed.NONE

    @property
    def now(self) -> float:
        return self.clock[0]

    def notice(self, event, detail, final=False):
        self.notices.append((event, dict(detail), final, threading.get_ident()))
        if final:
            self.events.append(("final", event))
        return True

    def grace_notices(self):
        return [notice for notice in self.notices if notice[0] == "power_grace"]

    # ---------------------------------------------------------------- the file and the records
    def arm(self, **changes):
        armed = {"nonce": NONCE, "action": "sleep", "after": "all_recovered", "repeat": "once",
                 "grace_seconds": 120, "armed_at": self.now - HOUR, "since": self.now - HOUR, "carried": [],
                 "stop_at": None}
        armed.update(changes)
        self.paths.power_action_file.write_text(json.dumps(
            {"format": poweraction.FORMAT, "armed": armed, "shown": None, "last": None}), encoding="utf-8")

    def stored(self):
        return json.loads(self.paths.power_action_file.read_text(encoding="utf-8"))

    def row(self, n=1, state="recovered", *, thread=THREAD, category="usage_limit", detected=None):
        detected = self.now - 600 if detected is None else detected
        terminal = state in poweraction.TERMINAL
        return {"interruption_id": key(n), "thread_id": thread, "state": state, "category": category,
                "detected_at": detected, "outcome_at": self.now - 300 if terminal else None, "last_error": None,
                "queue_id": None, "submitted_at": None}

    def ready(self, **arming):
        """Armed, one usage-limit recovery that recovered, nothing in Codex, nobody at this PC."""
        self.arm(**arming)
        self.store.rows = [self.row()]

    # ---------------------------------------------------------------- looking
    def look(self, ok=True, *, advance=0.0, idle_grows=True):
        if advance:
            self.clock[0] += advance
            if idle_grows:
                self.port.idle += advance
        self.work.look(self.store, self.engine, ok=ok, waking=self.waking, settings=self.settings,
                       managed=self.managed)

    def count_down(self):
        """Look until the countdown runs out, every 15 s as the loop then does."""
        self.look()
        self.assertTrue(self.work.counting)
        for _ in range(20):
            if not self.work.counting:
                break
            self.look(advance=15.0)


# ------------------------------------------------------------------------------ the defaults
class DefaultTests(WatcherCase):
    def test_without_a_file_only_the_file_is_looked_for(self):
        for _ in range(5):
            self.look(advance=30.0)
        self.assertEqual(self.port.calls, [], "Windows is asked nothing")
        self.assertEqual(self.engine.asked, [], "Codex is asked nothing")
        self.assertEqual(self.store.reads, 0, "no record is read")
        self.assertEqual((self.notices, self.lines), ([], []))
        self.assertFalse(self.paths.power_action_file.exists(), "and nothing is written")
        self.assertEqual(self.work.cap(30), 30)

    def test_nothing_armed_asks_nothing_either(self):
        self.paths.power_action_file.write_text(json.dumps(poweraction.blank()), encoding="utf-8")
        self.look()
        self.assertEqual((self.port.calls, self.engine.asked, self.store.reads), ([], [], 0))

    def test_a_file_that_cannot_be_believed_is_off_and_logged_once(self):
        self.paths.power_action_file.write_text("{not json", encoding="utf-8")
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual(self.port.calls, [])
        self.assertEqual(len([line for line in self.lines if "cannot be read" in line]), 1)
        self.assertEqual(self.paths.power_action_file.read_text(encoding="utf-8"), "{not json")

    def test_a_time_too_large_to_be_a_number_is_off_and_raises_nothing(self):
        """A JSON integer too large for a float once raised OverflowError from every look."""
        self.ready(stop_at=10 ** 400)
        text = self.paths.power_action_file.read_text(encoding="utf-8")
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual((self.port.calls, self.notices), ([], []))
        self.assertEqual(len([line for line in self.lines if "cannot be read" in line]), 1)
        self.assertEqual(len(self.lines), 1, "and nothing failed")
        self.assertEqual(self.paths.power_action_file.read_text(encoding="utf-8"), text)

    def test_an_administrators_key_holds_it_inert(self):
        self.ready()
        self.managed = managed.Managed(disable_power_action=True)
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual((self.port.calls, self.engine.asked, self.store.reads), ([], [], 0))
        self.assertIsNotNone(self.stored()["armed"], "inert, not deleted")
        self.assertEqual(len([line for line in self.lines if "turned off (managed)" in line]), 1)


# ------------------------------------------------------------------------------ the countdown
class CountdownTests(WatcherCase):
    def test_a_ready_batch_counts_down_once_then_acts(self):
        self.ready()
        self.look()
        self.assertTrue(self.work.counting)
        self.assertEqual(len(self.grace_notices()), 1)
        event, detail, final, _ = self.grace_notices()[0]
        self.assertEqual(detail, {"action": "sleep", "until": self.now + 120, "nonce": NONCE})
        self.assertFalse(final)
        self.assertEqual(self.stored()["shown"], {"nonce": NONCE, "phase": "grace", "waiting_for": None,
                                                 "grace_until": self.now + 120})
        self.assertEqual(self.engine.asked[0][0], (THREAD,), "the batch's own conversation is checked")
        for _ in range(8):
            self.look(advance=15.0)
            self.assertEqual(len(self.grace_notices()), 1, "the countdown's notice is raised once")
        acts = [call for call in self.port.calls if call[0] == "act"]
        self.assertEqual(len(acts), 1)
        self.assertEqual(acts[0][2], "sleep")
        self.assertFalse(self.work.counting)
        self.assertIsNone(self.stored()["armed"], "a Once is spent")
        self.assertEqual(self.stored()["last"]["result"], "done")
        for _ in range(5):
            self.look(advance=15.0)
        self.assertEqual(len([call for call in self.port.calls if call[0] == "act"]), 1, "never again")

    def test_the_end_is_written_before_windows_is_asked(self):
        self.ready()
        self.count_down()
        act = next(call for call in self.port.calls if call[0] == "act")
        written = act[3]
        self.assertIsNone(written["armed"])
        self.assertEqual(written["last"]["result"], "done")

    def test_let_go_and_the_last_notice_come_before_the_action(self):
        self.ready()
        self.count_down()
        self.assertEqual(self.events, [("let_go",), ("final", "power_now"), ("act", "sleep")])
        final = [notice for notice in self.notices if notice[0] == "power_now"]
        self.assertEqual([(notice[1], notice[2]) for notice in final], [({"action": "sleep"}, True)])

    def test_a_write_that_fails_does_nothing(self):
        self.ready()
        self.look()
        self.assertTrue(self.work.counting)

        class Busy:
            def __init__(self, *args, **kwargs):
                raise AdapterError("mutex_busy")
        with patch.object(control_power, "Mutex", Busy):
            for _ in range(10):
                self.look(advance=15.0)
        self.assertNotIn("act", self.port.names())
        self.assertNotIn(("let_go",), self.events)
        self.assertEqual([notice for notice in self.notices if notice[0] == "power_now"], [])
        self.assertIsNotNone(self.stored()["armed"])

    def test_a_refusal_is_said_and_never_retried(self):
        self.ready(repeat="always")
        self.port.accepts = False
        self.count_down()
        self.assertEqual(self.port.names().count("act"), 1)
        self.assertEqual(self.stored()["last"]["result"], "failed")
        self.assertIn("power_failed", [notice[0] for notice in self.notices])
        self.assertTrue(any("Windows refused the power action (error 1314)" in line for line in self.lines))
        for _ in range(10):
            self.look(advance=15.0)
        self.assertEqual(self.port.names().count("act"), 1, "the batch is spent")

    def test_the_fifteen_second_cap_holds_only_while_counting_down(self):
        self.assertEqual(self.work.cap(30), 30)
        self.ready()
        self.look()
        self.assertEqual(self.work.cap(30), poweraction.COUNTDOWN_LOOK_SECONDS)
        self.assertEqual(self.work.cap(5), 5)
        self.store.switches["enabled"] = False
        self.look(advance=15.0)
        self.assertEqual(self.work.cap(30), 30)

    def test_a_watcher_stop_never_acts(self):
        self.ready()
        self.look()
        self.work.stop()
        self.assertFalse(self.work.counting)
        self.assertNotIn("act", self.port.names())
        self.assertEqual(self.stored()["shown"]["waiting_for"], "watcher")
        self.assertTrue(any("countdown ended: watcher_stopped" in line for line in self.lines))

    def test_every_call_is_made_on_the_thread_that_looks(self):
        self.ready()
        done = []

        def tick():
            self.look()
            for _ in range(10):
                self.look(advance=15.0)
            done.append(threading.get_ident())
        worker = threading.Thread(target=tick)
        worker.start()
        worker.join(30)
        self.assertEqual(len(done), 1)
        self.assertEqual({call[1] for call in self.port.calls}, {done[0]})
        self.assertEqual({asked[1] for asked in self.engine.asked}, {done[0]})
        self.assertEqual({notice[3] for notice in self.notices}, {done[0]})


class EndsTests(WatcherCase):
    """Every way a countdown ends, and that nothing is done for any of them."""

    def started(self, **arming):
        self.ready(**arming)
        self.look()
        self.assertTrue(self.work.counting)

    def ended(self, why):
        self.assertFalse(self.work.counting, why)
        self.assertNotIn("act", self.port.names())

    def test_a_pause_ends_it(self):
        self.started()
        self.store.switches["enabled"] = False
        self.look(advance=15.0)
        self.ended("paused")
        self.assertEqual(self.stored()["shown"]["waiting_for"], "paused")

    def test_observe_only_in_the_state_or_the_settings_ends_it(self):
        for where in ("state", "settings"):
            with self.subTest(where=where):
                self.setUp()
                self.started()
                if where == "state":
                    self.store.switches["observe_only"] = True
                else:
                    self.settings = dict(self.settings, observe_only=True)
                self.look(advance=15.0)
                self.ended(where)

    def test_an_administrators_pause_ends_it(self):
        self.started()
        self.managed = managed.Managed(disable_auto_resume=True)
        self.look(advance=15.0)
        self.ended("managed pause")

    def test_a_tick_that_failed_ends_it(self):
        self.started()
        self.look(ok=False, advance=15.0)
        self.ended("tick failed")

    def test_input_ends_it_and_the_next_one_waits_for_two_quiet_minutes(self):
        self.started()
        self.port.idle = 3.0
        self.look(advance=15.0, idle_grows=False)
        self.ended("input")
        self.assertEqual(self.stored()["shown"]["waiting_for"], "person_active")
        self.look(advance=15.0)
        self.assertFalse(self.work.counting, "18 s without input is not two minutes")
        self.assertEqual(len(self.grace_notices()), 1)

    def test_a_gap_between_two_looks_ends_it(self):
        self.started()
        self.look(advance=poweraction.GAP_SECONDS + 1)
        self.ended("gap")
        self.started()
        self.clock[0] -= 200.0                  # the clock set back
        self.look()
        self.ended("clock back")

    def test_a_new_recovery_ends_it(self):
        self.started()
        self.store.rows.append(self.row(2, "waiting_reset", detected=self.now))
        self.look(advance=15.0)
        self.ended("a new recovery")
        self.assertEqual(self.stored()["shown"]["waiting_for"], "recovery_open")

    def test_a_turn_running_or_a_history_behind_ends_it(self):
        for answer, word in (({"history": True, "running": 1, "queued": 0}, "turn_running"),
                             ({"history": False, "running": 0, "queued": 0}, "history_behind"),
                             ({"history": None, "running": None, "queued": None}, "codex_unknown")):
            with self.subTest(word=word):
                self.setUp()
                self.started()
                self.engine.answer = answer
                self.look(advance=15.0)
                self.ended(word)
                self.assertEqual(self.stored()["shown"]["waiting_for"], word)

    def test_turned_off_from_anywhere_ends_it(self):
        self.started()
        self.control.disarm_power_action("tray")
        self.look(advance=15.0)
        self.ended("disarmed")
        self.assertTrue(any("turned off (turned_off)" in line for line in self.lines))

    def test_windows_unable_ends_the_batch_and_says_so(self):
        self.ready()
        self.port.offered = False
        self.look()
        self.ended("unavailable")
        self.assertIsNone(self.stored()["armed"])
        self.assertEqual(self.stored()["last"]["result"], "unavailable")
        self.assertEqual([notice[0] for notice in self.notices], ["power_failed"])

    def test_a_once_whose_recoveries_ended_otherwise_ends_not_met_and_says_so(self):
        self.arm()
        self.store.rows = [self.row(1, "failed")]
        self.look()
        self.ended("not met")
        self.assertEqual(self.stored()["last"]["result"], "not_met")
        self.assertEqual([notice[0] for notice in self.notices], ["power_not_met"])
        self.assertEqual(self.port.calls, [], "the policy decides before Windows is asked")

    def test_an_always_that_ends_not_met_raises_no_notice(self):
        self.arm(repeat="always")
        self.store.rows = [self.row(1, "failed")]
        self.look()
        self.assertEqual(self.notices, [])
        self.assertNotEqual(self.stored()["armed"]["nonce"], NONCE, "the next batch has its own nonce")


# ------------------------------------------------------------------------------ the stop
class StopTests(WatcherCase):
    def press(self):
        """The notice's button, as notifier.activate presses it: the stop written for this nonce."""
        self.assertEqual(self.control.stop_power_countdown(NONCE, actor="toast"), "stopped")

    def test_the_real_click_never_acts_and_never_counts_down_again(self):
        """Pressing the button is input. Both in one look: the batch ends skipped, before the input
        could end only the countdown - and no countdown, and no notice of one, follows."""
        for repeat in ("once", "always"):
            with self.subTest(repeat=repeat):
                self.setUp()
                self.ready(repeat=repeat)
                self.look()
                self.assertEqual(len(self.grace_notices()), 1)
                self.press()
                self.port.idle = 0.5            # the click itself
                self.look(advance=10.0, idle_grows=False)
                self.assertFalse(self.work.counting)
                self.assertEqual(self.stored()["last"]["result"], "skipped")
                self.port.idle = 600.0          # nobody touches the PC again
                for _ in range(30):
                    self.look(advance=15.0)
                self.assertNotIn("act", self.port.names())
                self.assertEqual(len(self.grace_notices()), 1, "no second countdown")
                if repeat == "once":
                    self.assertIsNone(self.stored()["armed"])
                else:
                    self.assertNotEqual(self.stored()["armed"]["nonce"], NONCE)
                    self.assertEqual(self.stored()["armed"]["carried"], [])

    def test_a_stop_in_the_same_look_as_the_countdowns_end_still_wins(self):
        self.ready()
        self.look()
        self.press()
        self.look(advance=200.0, idle_grows=True)
        self.assertNotIn("act", self.port.names())
        self.assertEqual(self.stored()["last"]["result"], "skipped")

    def test_a_stop_written_while_the_end_is_written_is_still_honoured(self):
        """Step 16 rereads under the lock: a stop that came after the look began is found there."""
        self.ready()
        self.look()
        finish = self.control.power_batch_finish

        def stopped_first(nonce, now=None):
            self.press()
            return finish(nonce, now)
        with patch.object(self.control, "power_batch_finish", side_effect=stopped_first):
            for _ in range(10):
                self.look(advance=15.0)
        self.assertNotIn("act", self.port.names())
        self.assertEqual(self.stored()["last"]["result"], "skipped")

    def test_a_stop_before_any_countdown_ends_the_batch_too(self):
        self.ready()
        self.store.rows = [self.row(1, "waiting_reset")]
        self.look()
        self.press()
        self.look(advance=30.0)
        self.assertEqual(self.stored()["last"]["result"], "skipped")
        self.store.rows = [self.row(1, "recovered")]
        for _ in range(10):
            self.look(advance=15.0)
        self.assertEqual(self.grace_notices(), [])
        self.assertNotIn("act", self.port.names())

    def test_an_older_batchs_notice_stops_nothing(self):
        self.arm(repeat="always")
        self.store.rows = [self.row(1, "failed")]
        self.look()                               # not met: the next batch, a new nonce
        self.assertEqual(self.control.stop_power_countdown(NONCE, actor="toast"), "ignored")
        self.assertIsNone(self.stored()["armed"]["stop_at"])


# ------------------------------------------------------------------------------ waiting
class WaitingTests(WatcherCase):
    def test_each_wait_is_shown_and_logged_once_per_change(self):
        self.arm()
        self.store.rows = [self.row(1, "waiting_reset")]
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual(self.stored()["shown"]["waiting_for"], "recovery_open")
        self.assertEqual(len([line for line in self.lines if "waits: recovery_open" in line]), 1)
        self.assertEqual(self.port.calls, [], "Windows is asked only once the batch has ended")
        self.assertEqual(self.engine.asked, [], "and Codex too")

    def test_no_batch_yet_waits(self):
        self.arm()
        self.look()
        self.assertEqual(self.stored()["shown"]["waiting_for"], "no_batch")

    def test_a_shut_down_waits_while_anybody_else_is_signed_in_and_asks_no_more(self):
        self.ready(action="shut_down")
        for others in (1, None):
            with self.subTest(others=others):
                self.port.others, self.port.calls = others, []
                self.look(advance=30.0)
                self.assertFalse(self.work.counting)
                self.assertEqual(self.stored()["shown"]["waiting_for"], "other_people")
                self.assertNotIn("idle_seconds", self.port.names())

    def test_sleep_never_asks_who_else_is_signed_in(self):
        self.ready()
        self.look()
        self.assertNotIn("other_sessions", self.port.names())

    def test_windows_not_saying_whether_anyone_is_here_waits(self):
        self.ready()
        self.port.idle = None
        self.look()
        self.assertFalse(self.work.counting)
        self.assertEqual(self.stored()["shown"]["waiting_for"], "idle_unknown")

    def test_an_arming_made_in_the_dashboard_is_logged_once(self):
        self.arm(since=self.now - 60, armed_at=self.now - 60, carried=[key(5)])
        for _ in range(3):
            self.look(advance=30.0)
        self.assertEqual(len([line for line in self.lines if "armed in the Dashboard: sleep; 1 " in line]), 1)


# ------------------------------------------------------------------------------ the loop and the notices
class LoopTests(unittest.TestCase):
    def test_it_looks_after_keeping_awake_and_before_the_heartbeat(self):
        source = inspect.getsource(loop.WatchLoop._loop)
        self.assertLess(source.index("self._keep_awake("), source.index("self._after_work("))
        self.assertLess(source.index("self._after_work("), source.index("self._heartbeat("))
        self.assertLess(source.index("self._poll_interval("), source.index("afterwork.cap("))
        self.assertLess(source.index("afterwork.cap("), source.index("self._between_ticks("))
        self.assertIn("afterwork = None if once else self._new_afterwork()", source)
        self.assertIn("afterwork.stop()", source.split("finally:")[-1])

    def test_a_failing_look_ends_the_countdown_and_costs_nothing_else(self):
        failures, halted = [], []

        class Broken:
            def look(self, *args, **kwargs):
                raise OSError("no")

            def halt(self, reason="failed"):
                halted.append(reason)
        host = types.SimpleNamespace(settings={}, managed=managed.NONE,
                                     _record_failure=lambda label: failures.append(label))
        loop.WatchLoop._after_work(host, Broken(), None, None, True, None)
        self.assertEqual((failures, halted), (["the power action"], ["failed"]))
        loop.WatchLoop._after_work(host, None, None, None, True, None)

    def test_the_watcher_builds_one_with_the_control_layer_and_its_own_notices(self):
        host = types.SimpleNamespace(paths=config.Paths(Path(tempfile.gettempdir()) / "no-such-home"),
                                     plug=None, logger=types.SimpleNamespace(info=lambda line: None),
                                     _watcher_notice=lambda *args, **kwargs: True,
                                     _record_failure=lambda label: None)
        made = loop.WatchLoop._new_afterwork(host)
        self.assertIsInstance(made, AfterWork)
        self.assertIs(made._port, afterwork_module.powerdown)

    def test_power_notices_are_raised_whatever_the_switches_say(self):
        delivered = []
        host = types.SimpleNamespace(settings=dict(settings.defaults(), notifications=False), _inbox=None)
        with patch.object(notifier, "deliver", lambda notice, **kwargs: delivered.append(notice.kind) or ("toast", True)):
            for event in notifier.POWER_EVENTS:
                app_module.App._show_watcher_notice(host, event, {"action": "sleep", "until": time.time(),
                                                                  "nonce": NONCE}, final=True)
            app_module.App._show_watcher_notice(host, "memory_warning", {"used": 1, "limit": 1}, final=True)
        self.assertEqual(delivered, list(notifier.POWER_EVENTS), "the memory guard's still obeys them")


if __name__ == "__main__":
    unittest.main()
