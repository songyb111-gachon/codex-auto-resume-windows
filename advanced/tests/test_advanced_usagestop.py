"""The forced stop near a usage limit (v0.6.16-beta.4, item (h) of the owner's additions to issue #29): usage_pause, through
core's own engine and a simulated Codex home - each running turn stopped once for its window through the Codex app's
channel (a seam here, and a scratch pipe of the test's own in the last test, never the real one), the fallback to the
hold with its notice, the queue to Resume, and the one continuation after the reset by a turn the app starts.

    PYTHONPATH=src;advanced/src python -m unittest discover -s advanced/tests -p test_advanced_usagestop.py
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from takingcase import TakingCase  # noqa: E402
from codex_auto_resume.domain.plug import Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import statement, surfaces  # noqa: E402
from codex_auto_resume_advanced.codex import ipc  # noqa: E402
from codex_auto_resume_advanced.registry import USAGE_METER, USAGE_PAUSE, USAGE_WRAP_UP  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, OptionKey  # noqa: E402
from test_advanced_usage import _view_all  # noqa: E402
from test_engine import T1  # noqa: E402

CORE = {"interruption_id": "a" * 64, "thread_id": T1}


def _through(gate, record, answer):
    """A seam's request as ipc makes it: written inside core's errand guard, never where it refuses (HELD)."""
    if gate is not None:
        with gate() as permitted:
            if permitted is not True:
                return ipc.Stop.HELD
            record()
    else:
        record()
    return answer


class StopCase(TakingCase):
    DEFINITION = USAGE_PAUSE
    BESIDE = (USAGE_METER,)

    def setUp(self):
        super().setUp()
        self.compat = _view_all()
        self.stops, self.starts = [], []
        self.stop_answer = ipc.Stop.STOPPED
        self.start_answer = ipc.Start.STARTED

    def arm(self, plug, state="armed", capability=None, **changes):
        definition = plug.runtime.registry.get(capability or self.cap)
        changes.setdefault("warnings", [str(w) for w in plug.runtime.arming.warnings(definition)])
        return super().arm(plug, state=state, capability=capability, **changes)

    def code(self, plug):
        return plug.runtime._code_of(plug.runtime.registry.get(self.cap))

    def running(self, percent=98):
        """A turn running in T1, the five-hour window at `percent`, the stop's seams recording."""
        plug = self.armed()
        from codex_auto_resume import settings
        values = settings.defaults()
        values["continuation_language"] = "en"
        settings.save(plug.paths.settings_file, values)
        code = self.code(plug)
        code._home = self.h.home.root
        code._stop = lambda thread, turn, gate=None: _through(gate, lambda: self.stops.append((thread, turn)),
                                                              self.stop_answer)
        code._start = lambda thread, text, gate=None: _through(gate, lambda: self.starts.append((thread, text)),
                                                               self.start_answer)
        self.h.backend.loaded_map[T1] = "loaded"
        turn = self.h.home.add_turn(T1, status="inProgress", progress=False)
        self.reset = int(self.h.now) + 3600
        plug.runtime.state.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": percent,
                                        "reset_at": self.reset}], at=self.h.now)
        return plug, turn

    def journal(self, plug):
        return [entry["code"] for entry in plug.runtime.state.journal()]

    def kinds(self, plug):
        view = surfaces.meter_view(plug.runtime)
        return [notice["kind"] for notice in view.get("meter", {}).get("notices", [])]

    def after_reset(self, plug, turn, status="interrupted"):
        """The stopped turn ended as the app ends one, and the window's reset passed."""
        self.h.home.set_turn(T1, turn, status=status, completed_at=int(self.h.now))
        self.h.now = self.reset + 120
        plug.runtime.state.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 1,
                                        "reset_at": self.reset + 5 * 3600}], at=self.h.now)


class StopTests(StopCase):
    def test_at_the_stop_percentage_each_running_turn_is_stopped_once_and_the_window_held(self):
        plug, turn = self.running()
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.stops, [(T1, turn)], "once for the window, naming the running turn")
        self.assertIs(plug.runtime.ask(Point.GATES, "usage", CORE, {}), Alternative.HOLD)
        codes = self.journal(plug)
        self.assertIn("pause.stopped", codes)
        self.assertNotIn("pause.resume_unproven", codes, "the turn started after the reset lets the queue go")
        self.assertEqual(self.kinds(plug), [])

    def test_below_it_nothing_is_stopped(self):
        self.running(percent=96)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.stops, [])

    def test_where_it_cannot_stop_it_holds_and_says_so(self):
        self.stop_answer = ipc.Stop.NO_CLIENT
        plug, _turn = self.running()
        for _ in range(2):
            self.h.tick(advance=61)
        self.assertIs(plug.runtime.ask(Point.GATES, "usage", CORE, {}), Alternative.HOLD)
        self.assertIn("pause.not_stopped", self.journal(plug))
        self.assertEqual(self.kinds(plug), ["not_stopped"])
        self.assertEqual(plug.runtime.state.continuations(capability=self.cap, pending=None), [],
                         "nothing it did not stop is continued by it")

    def test_a_stop_with_no_answer_in_time_is_kept_as_one_that_may_have_been_made(self):
        """The app may have stopped it, and paused its queue: it is continued after the reset like a stopped one, so
        that queue is let go - never left with nothing to say or to do."""
        self.stop_answer = ipc.Stop.UNCONFIRMED
        plug, turn = self.running()
        for _ in range(2):
            self.h.tick(advance=61)
        self.assertIn("pause.stop_unconfirmed", self.journal(plug))
        (row,) = plug.runtime.state.continuations(capability=self.cap, pending=None)
        self.assertEqual(row["kind"], "after_reset")
        self.after_reset(plug, turn)
        for _ in range(2):
            self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1)

    def test_a_window_switched_off_is_never_stopped(self):
        """Switched off in its own choices (v0.6.16 final)."""
        plug, _turn = self.running()
        assert plug.runtime.arming.set_option("usage_pause", OptionKey.WINDOW_FIVE_HOUR, 2,
                                              generation=plug.runtime.state.meta()["generation"],
                                              actor=Actor.DASHBOARD)["done"]
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.stops, [])

    def test_the_meters_window_switch_leaves_the_stop_alone(self):
        """v0.6.16 final: the meter's five-hour switch off stops only its warnings - the turn is stopped all the same."""
        plug, _turn = self.running()
        assert plug.runtime.arming.set_option("usage_meter", OptionKey.WINDOW_FIVE_HOUR, 2,
                                              generation=plug.runtime.state.meta()["generation"],
                                              actor=Actor.DASHBOARD)["done"]
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(self.stops), 1)


class OncePerResetTests(StopCase):
    def test_a_window_switched_off_and_on_again_does_not_stop_a_turn_the_person_resumed(self):
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.assertEqual(len(self.stops), 1)
        self.h.home.set_turn(T1, turn, status="interrupted", completed_at=int(self.h.now))
        self.h.home.add_turn(T1, status="inProgress", progress=False)        # the person pressed Resume
        for value in (2, 1):
            assert plug.runtime.arming.set_option("usage_pause", OptionKey.WINDOW_FIVE_HOUR, value,
                                                  generation=plug.runtime.state.meta()["generation"],
                                                  actor=Actor.DASHBOARD)["done"]
            self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.assertEqual(len(self.stops), 1, "one stop per window per reset")
        self.assertIs(plug.runtime.ask(Point.GATES, "usage", CORE, {}), Alternative.HOLD, "held again all the same")


class AfterResetTests(StopCase):
    def test_a_stopped_conversation_is_continued_once_after_the_reset_by_a_turn_the_app_starts(self):
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        (row,) = plug.runtime.state.continuations(capability=self.cap, pending=None)
        self.assertEqual((row["kind"], row["chain"]), ("after_reset", 300))
        self.h.tick(advance=61)
        self.assertEqual(self.starts, [], "not before the window resets")
        self.after_reset(plug, turn)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1)
        thread, text = self.starts[0]
        self.assertEqual(thread, T1)
        self.assertTrue(text.startswith(statement.CATALOGS.text("continue.after_reset", "en") + "\n\n"), text)
        self.assertIn("[codex-auto-resume:", text)
        self.assertIn("pause.continued", self.journal(plug))
        self.assertEqual(self.h.backend.send_calls, [], "never through the queue the app paused")

    def test_newer_work_wins_and_nothing_is_sent(self):
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        self.h.home.add_turn(T1)                                # the person went on working
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.starts, [])
        (row,) = plug.runtime.state.continuations(capability=self.cap, pending=None)
        self.assertEqual(row["reason"], "superseded")

    def test_where_the_app_does_not_have_it_open_it_waits_and_says_so(self):
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        self.start_answer = ipc.Stop.NO_CLIENT
        self.h.tick(advance=61)
        self.assertIn("not_continued", self.kinds(plug))
        self.start_answer = ipc.Start.STARTED
        self.h.tick(advance=301)
        self.assertEqual(len(self.starts), 2, "tried again once it is open")
        self.assertIn("pause.continued", self.journal(plug))

    def test_a_failing_start_is_asked_again_later_not_every_tick(self):
        """Each start may wait for the app's answers inside the watcher's tick: one that fails is asked again after
        five minutes, then ten, twenty - up to an hour."""
        plug, turn = self.running()
        # The meter reads no fresh usage here: its own reading after its spacing would hold a window again, and
        # nothing of the stop's own starts while one holds (v0.6.18, test_advanced_stop_held_windows).
        plug.runtime._code_of(plug.runtime.registry.get("usage_meter"))._app_running = lambda: False
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        self.start_answer = ipc.Stop.NO_ANSWER
        self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1, "not again within five minutes")
        self.h.tick(advance=180)
        self.h.tick(advance=1)
        self.assertEqual(len(self.starts), 2, "again after five")
        for _ in range(8):
            self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 2, "then after ten")
        self.h.tick(advance=180)
        self.h.tick(advance=1)
        self.assertEqual(len(self.starts), 3)


class CoreGuardTests(StopCase):
    """The stop and the start after the reset are each written inside core's errand guard, as credits' request is:
    Observe only, a Pause, an administrator's DisableAutoResume and quiet hours hold them as they hold every send."""

    def test_observe_only_stops_nothing(self):
        plug, _turn = self.running()
        self.h.store.set_observe_only(True)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.stops, [])
        self.assertIn("pause.held", self.journal(plug))
        self.assertIs(plug.runtime.ask(Point.GATES, "usage", CORE, {}), Alternative.HOLD, "the window is held still")

    def test_observe_only_starts_nothing_after_the_reset_and_the_start_waits_for_it_to_end(self):
        plug, turn = self.running()
        self.h.tick(advance=61)
        self.h.tick(advance=61)
        self.after_reset(plug, turn)
        self.h.store.set_observe_only(True)
        for _ in range(3):
            self.h.tick(advance=61)
        self.assertEqual(self.starts, [])
        self.h.store.set_observe_only(False)
        self.h.tick(advance=61)
        self.assertEqual(len(self.starts), 1, "asked once observing ends")

    def test_an_administrators_disable_holds_both(self):
        plug, turn = self.running()
        with patch.object(type(self.h.engine), "errand_held", lambda _self: True):
            for _ in range(2):
                self.h.tick(advance=61)
            self.assertEqual(self.stops, [])
            self.after_reset(plug, turn)
            for _ in range(2):
                self.h.tick(advance=61)
        self.assertEqual(self.starts, [])


class NoContinuationTests(StopCase):
    """Continue after the reset off (the wrap-up's choice): nothing will start a turn there, which is what lets the
    paused queue go - so the person is asked to press Resume in Codex."""
    BESIDE = (USAGE_METER, USAGE_WRAP_UP)

    def test_with_continue_after_the_reset_off_the_person_is_asked_to_press_resume(self):
        plug, _turn = self.running()
        assert plug.runtime.arming.set_option("usage_wrap_up", OptionKey.WRAP_AFTER_RESET, 2,
                                              generation=plug.runtime.state.meta()["generation"],
                                              actor=Actor.DASHBOARD)["done"]
        for _ in range(2):
            self.h.tick(advance=61)
        self.assertEqual(len(self.stops), 1)
        self.assertIn("pause.resume_unproven", self.journal(plug))
        self.assertEqual(self.kinds(plug), ["press_resume"])
        self.assertEqual(plug.runtime.state.continuations(capability=self.cap, pending=None), [])

    def test_a_stop_with_no_answer_asks_for_resume_too_where_nothing_will_continue_it(self):
        self.stop_answer = ipc.Stop.UNCONFIRMED
        plug, _turn = self.running()
        assert plug.runtime.arming.set_option("usage_wrap_up", OptionKey.WRAP_AFTER_RESET, 2,
                                              generation=plug.runtime.state.meta()["generation"],
                                              actor=Actor.DASHBOARD)["done"]
        for _ in range(2):
            self.h.tick(advance=61)
        self.assertEqual(self.kinds(plug), ["press_resume"])


@unittest.skipUnless(sys.platform == "win32", "a Windows named pipe")
class ThroughThePipeTests(StopCase):
    def test_the_stop_goes_through_the_apps_channel(self):
        import fakeipc
        app = fakeipc.FakeApp()
        self.addCleanup(app.close)
        plug, turn = self.running()
        self.code(plug)._stop = None                            # the real ipc.stop_turn, to a scratch pipe
        with patch.object(ipc, "PIPE", app.name):
            self.h.tick(advance=61)
            self.h.tick(advance=61)
        self.assertEqual([seen[0] for seen in app.seen],
                         ["initialize", "thread-owner-discovery", "thread-follower-interrupt-turn"])
        self.assertEqual(app.seen[-1][2], {"conversationId": T1, "mode": "system", "expectedTurnId": turn})
        self.assertEqual(self.kinds(plug), [])


if __name__ == "__main__":
    unittest.main()
