"""Restart the watcher if it stops unexpectedly (v0.6.19, crash_restart; plans/v0619-design/D-watcher-ops.md A).

P13's answers, held against the shipped definition and statement and the edition's own runtime: SUPERVISE at the start
while it stands on; RESTART once a supervised watcher ended abnormally - not clean, an exit code none of 0, 3, 4, 5, no
stop asked through the stop event - at most three an hour, each a `restarts` row written first; the fourth left stopped
with one notice of its own kind. The stop event, the wait and the notice are fakes: nothing real is opened or shown.

    CODEX_AR_EDITION=advanced PYTHONPATH="src;advanced/src" python -m unittest discover -s advanced/tests
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import advancedcase as ac  # noqa: E402
from codex_auto_resume import l10n, notice_kinds, notifier, notify  # noqa: E402
from codex_auto_resume.domain.plug import DEFER, Alternative, Point  # noqa: E402
from codex_auto_resume_advanced import plug as advanced, registry, statement  # noqa: E402
from codex_auto_resume_advanced.engine import supervise  # noqa: E402
from codex_auto_resume_advanced.registry import CRASH_RESTART  # noqa: E402
from codex_auto_resume_advanced.state import StateError  # noqa: E402
from codex_auto_resume_advanced.vocabulary import Actor, CapabilityKind  # noqa: E402
from codex_auto_resume_advanced.win import stopflag  # noqa: E402

CAP = "crash_restart"
START = {"phase": "start"}


def ended(code=1, clean=False):
    return {"phase": "ended", "exit_code": code, "clean": clean}


class Stop:
    """The stop event as the supervisor sees it: held or not, signalled or not, and the waits asked of it."""

    def __init__(self):
        self.held, self.set, self.set_during_wait, self.waits = False, False, False, []

    def hold(self):
        self.held = True
        return True

    def signalled(self):
        return self.set

    def wait(self, seconds):
        self.waits.append(seconds)
        return self.set or self.set_during_wait


class DefinitionTests(unittest.TestCase):
    def test_a_route_at_p13_departing_from_f6_and_f8_shown_after_start_with_codex(self):
        self.assertEqual((CRASH_RESTART.kind, CRASH_RESTART.points, CRASH_RESTART.compat),
                         (CapabilityKind.ROUTE, frozenset({Point.SUPERVISION}), "engine_present"))
        self.assertEqual(CRASH_RESTART.departs_from, ("F6", "F8"))
        self.assertEqual((CRASH_RESTART.measurements, CRASH_RESTART.options, CRASH_RESTART.requires), ((), (), ()))
        self.assertIn(CAP, registry.REGISTRY.ids)
        order = registry.SHOWN_ORDER
        self.assertEqual(order[order.index("start_with_codex") + 1], CAP)
        self.assertEqual(registry.REGISTRY.at(Point.SUPERVISION), (CRASH_RESTART,))
        self.assertEqual(statement.CATALOGS.missing(CRASH_RESTART), [])

    def test_its_notice_is_a_kind_of_its_own_in_every_language(self):
        advanced.register_notice_kinds()
        kind = notice_kinds.kind_of("restart_gave_up")
        self.assertEqual((kind.id, kind.notices), ("restart_gave_up", ("restart_gave_up",)))
        for locale in l10n.LOCALES:
            with self.subTest(locale=locale):
                self.assertTrue(l10n.text("msg.toast_restart_gave_up", locale).strip())
                self.assertTrue(l10n.text("msg.toast_restart_gave_up_body", locale).strip())


class SuperviseCase(ac.AdvancedCase):
    def setUp(self):
        super().setUp()
        self.compat = ac.view(capability="engine_present")
        self.plug = advanced.AdvancedPlug(self.paths, **dict(self.options(CRASH_RESTART), catalogs=statement.CATALOGS))
        self.addCleanup(lambda: self.plug._runtime and self.plug._runtime.state.close())
        self.rt = self.plug.runtime
        self.code = self.rt._code_of(CRASH_RESTART)
        self.stop = self.code._stop = Stop()
        self.notices = []
        self.code._notify = self.notices.append

    def on(self, state="armed"):
        result = self.rt.arming.arm(CAP, state=state, revision=CRASH_RESTART.revision,
                                    generation=self.rt.state.meta()["generation"], acknowledged_version=ac.ENGINE,
                                    warnings=[str(w) for w in self.rt.arming.warnings(CRASH_RESTART)],
                                    actor=Actor.DASHBOARD)
        self.assertTrue(result["done"], result)

    def rows(self):
        return self.rt.state.restarts_since(0.0 + 1)

    def restarted(self):
        return [row for row in self.rows() if row["restarted"]]


class OffTests(SuperviseCase):
    def test_off_it_answers_nothing_and_nothing_is_written(self):
        self.assertIs(self.plug.supervise(START), DEFER)
        self.assertIs(self.plug.supervise(ended()), DEFER)
        self.assertEqual((self.rows(), self.stop.held), ([], False))

    def test_watched_it_is_only_journalled(self):
        self.on(state="shadow")
        self.assertIs(self.plug.supervise(START), DEFER)
        self.assertIs(self.plug.supervise(ended()), DEFER)
        self.assertEqual(self.rows(), [])


class OnTests(SuperviseCase):
    def test_on_it_supervises_and_holds_the_stop_event_from_the_start(self):
        """Fails with the capability's start answer reverted: the launcher runs the watcher alone."""
        self.on()
        self.assertIs(self.plug.supervise(START), Alternative.SUPERVISE)
        self.assertTrue(self.stop.held)

    def test_an_abnormal_end_restarts_after_the_delay_and_is_counted_first(self):
        self.on()
        self.plug.supervise(START)
        self.assertIs(self.plug.supervise(ended(1)), Alternative.RESTART)
        self.assertEqual(self.stop.waits, [supervise.RESTART_DELAY])
        self.assertEqual([(row["exit_code"], row["restarted"]) for row in self.rows()], [(1, 1)])
        with self.rt.state._read() as connection:
            codes = [row[0] for row in connection.execute("SELECT code FROM journal")]
        self.assertIn("crash.restarted", codes)

    def test_the_exit_codes_and_ends_never_restarted(self):
        """0 done, 3 another watcher holds the home, 4 the state is newer (relaunched once by the launcher), 5 the
        memory guard; a clean end in the heartbeat; something that is not a code."""
        self.on()
        self.plug.supervise(START)
        for facts in (ended(0), ended(3), ended(4), ended(5), ended(1, clean=True), ended(-1073741819, clean=True),
                      {"phase": "ended", "exit_code": "1", "clean": False}, {"phase": "ended", "clean": False},
                      {"phase": "later"}, "ended"):
            with self.subTest(facts=facts):
                self.assertIs(self.plug.supervise(facts), DEFER)
        self.assertEqual(self.rows(), [])

    def test_a_crash_with_no_heartbeat_read_or_one_still_running_restarts(self):
        self.on()
        self.plug.supervise(START)
        for facts in (ended(1, clean=None), ended(-1073741819, clean=False), ended(2)):
            with self.subTest(facts=facts):
                self.now += 60
                self.assertIs(self.plug.supervise(facts), Alternative.RESTART)

    def test_a_stop_asked_before_or_during_the_delay_is_never_restarted(self):
        self.on()
        self.plug.supervise(START)
        self.stop.set = True
        self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.stop.waits, [], "seen before any wait")
        self.stop.set, self.stop.set_during_wait = False, True
        self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.rows(), [], "nothing counted for a restart not made")

    def test_three_an_hour_then_left_stopped_with_one_notice(self):
        """Fails with the cap reverted: a fourth restart in the hour."""
        self.on()
        self.plug.supervise(START)
        for _ in range(3):
            self.now += 60
            self.assertIs(self.plug.supervise(ended(1)), Alternative.RESTART)
        self.now += 60
        self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.notices, [self.paths])
        self.assertEqual([row["restarted"] for row in self.rows()], [1, 1, 1, 0])
        with self.rt.state._read() as connection:
            codes = [row[0] for row in connection.execute("SELECT code FROM journal")]
        self.assertIn("crash.gave_up", codes)

    def test_an_hour_after_the_first_restart_another_is_allowed(self):
        self.on()
        self.plug.supervise(START)
        for _ in range(3):
            self.now += 60
            self.plug.supervise(ended(1))
        self.now += supervise.HOUR - 110          # the first restart is now more than an hour ago
        self.assertIs(self.plug.supervise(ended(1)), Alternative.RESTART)
        self.assertEqual(self.notices, [])

    def test_restart_is_answered_only_in_a_launcher_it_supervised_in(self):
        """A watcher run in the launcher's own process - the start answered before it was turned on - is never
        counted or restarted."""
        self.on()
        self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.rows(), [])

    def test_a_restart_that_cannot_be_counted_is_not_made(self):
        self.on()
        self.plug.supervise(START)
        with patch.object(type(self.rt.state), "restart_noted", side_effect=StateError("locked")):
            self.assertIs(self.plug.supervise(ended(1)), DEFER)
        with patch.object(type(self.rt.state), "restarts_since", side_effect=StateError("locked")):
            self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.rt.states(fresh=True).get(CAP), "armed", "a state it cannot write does not trip it")

    def test_turned_off_while_it_supervises_the_next_end_is_left_alone(self):
        self.on()
        self.plug.supervise(START)
        self.rt.arming.disarm(CAP, actor=Actor.DASHBOARD)
        self.assertIs(self.plug.supervise(ended(1)), DEFER)
        self.assertEqual(self.rows(), [])

    def test_with_no_usable_watcher_report_codex_is_checked_here_and_it_still_supervises(self):
        """At sign-in no watcher has run for a while, so its report of Codex is stale: P13 is read as P9 is (issue #31's
        lesson), with a check made here, or an armed crash restart would be held back at every start."""
        from codex_auto_resume.compat.report import unusable_view
        self.on()
        checked = []
        self.rt.arming._live = lambda: checked.append(1) or ac.view(capability="engine_present")
        self.compat = unusable_view("stale", engine={"found": True, "version": ac.ENGINE})
        self.assertIs(self.plug.supervise(START), Alternative.SUPERVISE)
        self.assertEqual(checked, [1])

    def test_the_restarts_are_written_by_crash_restart_alone_and_only_while_it_is_on(self):
        other = self.rt.state.scoped("start_with_codex", on=lambda: True)
        with self.assertRaises(StateError):
            other.restarts.noted(1, True)
        off = self.rt.state.scoped(CAP, on=lambda: False)
        with self.assertRaises(StateError):
            off.restarts.noted(1, True)
        self.assertEqual(self.rows(), [])


class NoticeTests(ac.AdvancedCase):
    def test_the_notice_is_windows_toast_with_one_button_to_the_overview(self):
        shown = []
        with patch.object(notifier, "deliver", side_effect=lambda notice, **k: shown.append((notice, k)) or
                          ("toast", True)):
            self.assertTrue(supervise.gave_up_notice(self.paths))
        ((notice, options),) = shown
        self.assertEqual((notice.kind, notice.key), ("restart_gave_up", None))
        self.assertEqual((options["inbox"], options["setting"]), (None, False))
        content = dict(notice.content)
        self.assertIn(notify.open_uri("overview"), str(content))

    def test_the_notifications_switch_silences_it(self):
        from codex_auto_resume import config, settings
        with patch.object(config, "load_settings", return_value=dict(settings.DEFAULTS, notifications=False)), \
                patch.object(notifier, "deliver") as deliver:
            self.assertFalse(supervise.gave_up_notice(self.paths))
        deliver.assert_not_called()


class StopFlagTests(ac.AdvancedCase):
    class Kernel:
        def __init__(self, signalled=False, opened=True):
            self.calls, self.signalled, self.opened = [], signalled, opened

        def CreateEventW(self, security, manual, initial, name):
            self.calls.append(("create", manual, initial, name))
            return 77

        def OpenEventW(self, access, inherit, name):
            self.calls.append(("open", access, name))
            return 88 if self.opened else 0

        def WaitForSingleObject(self, handle, millis):
            self.calls.append(("wait", handle, millis))
            return 0 if self.signalled else 0x102

        def CloseHandle(self, handle):
            self.calls.append(("close", handle))
            return 1

    def test_held_from_the_start_with_the_watcher_s_own_name_and_looked_at_without_waiting(self):
        kernel = self.Kernel()
        flag = stopflag.StopFlag(self.paths, kernel=kernel)
        self.assertTrue(flag.hold())
        self.assertFalse(flag.signalled())
        kernel.signalled = True
        self.assertTrue(flag.signalled())
        name = stopflag.event_name(self.paths)
        self.assertTrue(name.startswith("Local\\codex-auto-resume-stop-"))
        self.assertEqual(kernel.calls, [("create", True, False, name), ("wait", 77, 0), ("wait", 77, 0)])
        for verb in ("set", "reset"):
            self.assertFalse(any(call[0] == verb for call in kernel.calls), "never signalled or reset here")

    def test_the_delay_is_a_wait_on_the_event(self):
        kernel = self.Kernel(signalled=True)
        flag = stopflag.StopFlag(self.paths, kernel=kernel)
        flag.hold()
        self.assertTrue(flag.wait(5))
        self.assertEqual(kernel.calls[-1], ("wait", 77, 5000))

    def test_not_held_it_is_opened_by_name_looked_at_and_closed(self):
        kernel = self.Kernel(signalled=True)
        flag = stopflag.StopFlag(self.paths, kernel=kernel)
        self.assertTrue(flag.signalled())
        self.assertEqual([call[0] for call in kernel.calls], ["open", "wait", "close"])
        self.assertFalse(stopflag.StopFlag(self.paths, kernel=self.Kernel(opened=False)).signalled())


if __name__ == "__main__":
    unittest.main()
