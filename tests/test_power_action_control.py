"""v0.6.12: the power action's file and the control layer's five ways of writing it.

Armed only from the Dashboard (the bridge's actor) and refused while an administrator's DisablePowerAction
is set, while an older watcher holds the state, or when Windows will not do it for this account; turned
off from anywhere, always; stopped for one batch by the nonce its notice carries, so a notice of a batch
that is over stops nothing; ended and shown by the watcher. The file is content-free, read strictly, and
a file that cannot be believed is off and never rewritten until the next arming. Windows is a fake port
here: no test asks this PC what it can do.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import srcscan  # noqa: E402
from codex_auto_resume import control, diagnostics, managed, poweraction  # noqa: E402
from codex_auto_resume.control import policy as control_policy, poweraction as control_power  # noqa: E402
from codex_auto_resume.domain import ids  # noqa: E402
from codex_auto_resume.openstate import UPGRADE_PENDING  # noqa: E402
from codex_auto_resume.windows import AdapterError  # noqa: E402
from test_control import KEY, OTHER_KEY, THREAD, ControlTestCase, detection  # noqa: E402

CHOICE = {"action": "sleep", "after": "all_recovered", "repeat": "once", "grace_minutes": 5}


class FakePort:
    """win/powerdown.py, as a test needs it: what is offered, and never an action."""

    def __init__(self, offered=poweraction.ACTIONS, reason="no_privilege"):
        self.offered, self.reason, self.asked = set(offered), reason, []

    def available(self, action):
        self.asked.append(action)
        return (True, None) if action in self.offered else (False, self.reason)

    def act(self, action):
        raise AssertionError("the control layer never acts")


class PowerControlCase(ControlTestCase):
    def setUp(self):
        super().setUp()
        self.port = FakePort()
        self.control.power_port = self.port

    @property
    def file(self) -> Path:
        return self.paths.power_action_file

    def stored(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))

    def arm(self, **changes):
        return self.control.arm_power_action(dict(CHOICE, **changes))

    def refusal(self, call, *args, **kwargs):
        with self.assertRaises(control.ControlError) as caught:
            call(*args, **kwargs)
        return caught.exception.code

    def manage(self, **values):
        stand_in = patch.object(control_policy, "managed_policy", return_value=managed.Managed(**values))
        stand_in.start()
        self.addCleanup(stand_in.stop)


# ------------------------------------------------------------------------------ the defaults
class DefaultsTests(PowerControlCase):
    def test_with_no_file_nothing_is_said_and_nothing_is_written(self):
        self.assertNotIn("power_action", self.control.get_status())
        self.assertIsNone(self.control.power_view())
        self.assertEqual(self.control.read_power_action(), (poweraction.READ_MISSING, None))
        self.assertFalse(self.file.exists())
        self.assertNotIn("power_action", diagnostics.collect(self.control)["status"])
        self.assertEqual(self.port.asked, [], "the status asks Windows nothing")

    def test_the_options_say_what_windows_offers_and_what_holds_it(self):
        self.control.power_port = FakePort(offered=("shut_down",), reason="no_sleep_state")
        options = self.control.power_options()
        self.assertEqual(options["actions"], [
            {"value": "sleep", "available": False, "reason": "no_sleep_state"},
            {"value": "hibernate", "available": False, "reason": "no_sleep_state"},
            {"value": "shut_down", "available": True, "reason": None}])
        self.assertEqual((options["managed"], options["upgrade_pending"]), (False, False))
        self.assertEqual(options["view"], {"armed": None, "shown": None, "last": None})
        self.manage(disable_power_action=True)
        self.assertTrue(self.control.power_options()["managed"])

    def test_a_port_that_raises_or_answers_oddly_offers_nothing(self):
        class Odd:
            def available(self, action):
                if action == "sleep":
                    raise OSError("no")
                return True, "a reason nobody wrote"
        self.control.power_port = Odd()
        self.assertEqual([(entry["available"], entry["reason"]) for entry in self.control.power_options()["actions"]],
                         [(False, None), (True, None), (True, None)])

    def test_owned_state_files_list_it_and_its_temporary_files(self):
        """A purge takes it (D10); the installer's ordinary uninstall keeps state, and it with it."""
        self.assertTrue(self.paths.owns(self.paths.state_dir), "ensure() marks config/ as ours")
        self.arm()
        stray = self.paths.state_dir / "power-action.12345.tmp"
        stray.write_text("{}", encoding="utf-8")
        owned = self.paths.owned_state_files()
        self.assertIn(self.file, owned)
        self.assertIn(stray, owned)
        self.assertEqual(self.file.name, "power-action.json")


# ------------------------------------------------------------------------------ arming
class ArmTests(PowerControlCase):
    def test_arming_writes_the_choice_a_fresh_nonce_and_the_open_usage_limits(self):
        self.register()
        self.register(key=OTHER_KEY, category="network_transient")
        view = self.arm(repeat="always", grace_minutes=2)
        document = self.stored()
        armed = document["armed"]
        self.assertTrue(ids.is_power_nonce(armed["nonce"]))
        self.assertEqual(armed["carried"], [KEY], "the usage limit open now, never a temporary error")
        self.assertEqual((armed["action"], armed["after"], armed["repeat"], armed["grace_seconds"]),
                         ("sleep", "all_recovered", "always", 120))
        self.assertEqual(armed["since"], armed["armed_at"])
        self.assertIsNone(armed["stop_at"])
        self.assertEqual(view, poweraction.view(document))
        self.assertEqual(self.control.get_status()["power_action"], view)
        self.assertEqual(self.port.asked, ["sleep"], "Windows is asked again as it is armed")

    def test_the_file_is_content_free_and_the_nonce_reaches_no_surface(self):
        self.register()
        self.arm()
        text = self.file.read_text(encoding="utf-8")
        self.assertNotIn(THREAD, text)
        nonce = self.stored()["armed"]["nonce"]
        self.assertNotIn(nonce, json.dumps(self.control.get_status()))
        self.assertNotIn(nonce, json.dumps(self.control.power_options()))
        self.assertNotIn(nonce, json.dumps(diagnostics.collect(self.control)["status"]))
        self.assertEqual(diagnostics.collect(self.control)["status"]["power_action"]["armed"]["action"], "sleep")

    def test_a_second_arming_replaces_the_first_and_keeps_the_last_end(self):
        self.arm()
        first = self.stored()["armed"]["nonce"]
        self.assertTrue(self.control.power_batch_end(first, "lapsed"))
        self.arm(action="shut_down")
        document = self.stored()
        self.assertNotEqual(document["armed"]["nonce"], first)
        self.assertEqual(document["armed"]["action"], "shut_down")
        self.assertEqual(document["last"]["result"], "lapsed")

    def test_only_the_dashboard_arms(self):
        for actor in ("mcp", "tray", "toast", "card", "watcher", None):
            with self.subTest(actor=actor):
                self.assertEqual(self.refusal(self.control.arm_power_action, dict(CHOICE), actor=actor),
                                 "request_failed")
        self.assertFalse(self.file.exists())
        callers = set()
        for name, path in srcscan.modules().items():
            if "arm_power_action(" in srcscan.read(path).replace("disarm_power_action(", ""):
                callers.add(name)
        self.assertEqual(callers, {"codex_auto_resume.control.poweraction", "codex_auto_resume.controlcli"},
                         "only the bridge may call it")

    def test_a_choice_that_is_not_one_is_refused(self):
        for bad in ({}, dict(CHOICE, grace_minutes=True), dict(CHOICE, grace_minutes=3), dict(CHOICE, action="reboot"),
                    dict(CHOICE, extra=1), dict(CHOICE, repeat=["once"]), "sleep", None):
            with self.subTest(bad=bad):
                self.assertEqual(self.refusal(self.control.arm_power_action, bad), "request_failed")
        self.assertFalse(self.file.exists())

    def test_an_administrator_s_key_refuses_an_arming(self):
        self.manage(disable_power_action=True)
        self.assertEqual(self.refusal(self.arm), "managed_by_policy")
        self.assertFalse(self.file.exists())

    def test_an_older_watcher_holding_the_state_refuses_an_arming_and_not_a_disarming(self):
        self.arm()
        refused = control.ControlError(UPGRADE_PENDING, code="upgrade_pending")
        with patch.object(control.Control, "_open", side_effect=refused):
            self.assertEqual(self.refusal(self.arm), "upgrade_pending")
            self.assertEqual(self.control.disarm_power_action("tray"), {"changed": True})

    def test_an_action_windows_will_not_do_is_refused(self):
        self.control.power_port = FakePort(offered=("sleep",))
        self.assertEqual(self.refusal(self.arm, action="hibernate"), "power_unavailable")
        self.assertFalse(self.file.exists())
        self.assertEqual(self.arm(action="sleep")["armed"]["action"], "sleep")

    def test_without_the_lock_nothing_is_written(self):
        class Busy:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                raise AdapterError("mutex_busy")

            def __exit__(self, *args):
                pass
        with patch.object(control_power, "Mutex", Busy):
            self.assertEqual(self.refusal(self.arm), "state_busy")
            self.assertEqual(self.refusal(self.control.disarm_power_action, "mcp"), "state_busy")
        self.assertFalse(self.file.exists())

    def test_a_write_windows_refuses_leaves_nothing_behind(self):
        pauses = []
        with patch.object(control_power.os, "replace", side_effect=PermissionError("denied")) as replace,                 patch.object(control_power.time, "sleep", side_effect=pauses.append):
            self.assertEqual(self.refusal(self.arm), "request_failed")
        self.assertEqual(replace.call_count, control_power.REPLACE_TRIES, "tried for half a second, then refused")
        self.assertEqual(pauses, [control_power.REPLACE_PAUSE] * (control_power.REPLACE_TRIES - 1))
        self.assertFalse(self.file.exists())
        self.assertEqual(list(self.paths.state_dir.glob("power-action.*.tmp")), [])

    def test_a_reader_holding_the_file_delays_a_stop_and_never_loses_it(self):
        """Windows refuses to replace a file a reader holds open, for as long as its one read takes: the
        stop is tried again and written, where it was once refused and lost."""
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        real, refused, pauses = os.replace, [], []

        def held_for_three_tries(source, target):
            if len(refused) < 3:
                refused.append(target)
                raise PermissionError("another process holds the file")
            real(source, target)
        with patch.object(control_power.os, "replace", side_effect=held_for_three_tries),                 patch.object(control_power.time, "sleep", side_effect=pauses.append):
            self.assertEqual(self.control.stop_power_countdown(nonce), control.STOPPED)
        self.assertEqual(len(refused), 3)
        self.assertEqual(len(pauses), 3)
        self.assertIsNotNone(self.stored()["armed"]["stop_at"])
        self.assertEqual(list(self.paths.state_dir.glob("power-action.*.tmp")), [])

    @unittest.skipUnless(sys.platform == "win32", "Windows refuses to replace an open file")
    def test_a_real_reader_on_windows_holds_the_write_only_while_it_reads(self):
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        real, refused = os.replace, []
        reader = open(self.file, encoding="utf-8")       # as read_text holds it, for its one read
        self.addCleanup(reader.close)

        def reader_done_after_the_first_refusal(source, target):
            try:
                real(source, target)
            except PermissionError:
                refused.append(target)
                reader.close()
                raise
        with patch.object(control_power.os, "replace", side_effect=reader_done_after_the_first_refusal):
            self.assertEqual(self.control.stop_power_countdown(nonce), control.STOPPED)
        self.assertEqual(len(refused), 1, "the open reader did refuse the first replace")
        self.assertIsNotNone(self.stored()["armed"]["stop_at"])


# ------------------------------------------------------------------------------ turning it off
class DisarmTests(PowerControlCase):
    def test_anyone_may_turn_it_off_and_the_last_end_is_kept(self):
        for actor in control.DISARM_ACTORS:
            with self.subTest(actor=actor):
                self.arm()
                nonce = self.stored()["armed"]["nonce"]
                self.control.power_show(nonce, {"phase": "waiting", "waiting_for": "no_batch", "grace_until": None})
                self.assertEqual(self.control.disarm_power_action(actor), {"changed": True})
                document = self.stored()
                self.assertEqual((document["armed"], document["shown"]), (None, None))
                self.assertEqual(self.control.disarm_power_action(actor), {"changed": False})
        self.assertEqual(self.refusal(self.control.disarm_power_action, "a model"), "request_failed")

    def test_it_may_be_turned_off_while_an_administrator_holds_it(self):
        self.arm()
        self.manage(disable_power_action=True)
        self.assertEqual(self.control.disarm_power_action("dashboard"), {"changed": True})

    def test_with_no_file_turning_it_off_writes_nothing(self):
        self.assertEqual(self.control.disarm_power_action("mcp"), {"changed": False})
        self.assertFalse(self.file.exists())


# ------------------------------------------------------------------------------ a notice's stop
class StopTests(PowerControlCase):
    def test_the_armed_batch_s_nonce_stops_it_and_any_other_is_ignored(self):
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        # The nonce is random hex, and one with no letter (about 1 in 1,800) is its own upper case: it
        # is then the nonce itself and stops the batch (main run 37772380007). Only a letter has a case.
        cased = nonce.upper()
        for other in ["0" * 16, "nonsense", None, 12] + ([cased] if cased != nonce else []):
            with self.subTest(other=other):
                self.assertEqual(self.control.stop_power_countdown(other), control.IGNORED)
        self.assertIsNone(self.stored()["armed"]["stop_at"])
        self.assertEqual(self.control.stop_power_countdown(nonce, actor="toast"), control.STOPPED)
        stopped = self.stored()["armed"]["stop_at"]
        self.assertIsNotNone(stopped)
        self.assertEqual(self.control.stop_power_countdown(nonce, actor="card"), control.STOPPED)
        self.assertEqual(self.stored()["armed"]["stop_at"], stopped, "the first press is kept")
        self.assertEqual(self.refusal(self.control.stop_power_countdown, nonce, actor="mcp"), "request_failed")

    def test_after_an_always_batch_ends_its_old_nonce_stops_nothing(self):
        self.arm(repeat="always")
        old = self.stored()["armed"]["nonce"]
        self.assertTrue(self.control.power_batch_end(old, "done"))
        following = self.stored()["armed"]
        self.assertNotEqual(following["nonce"], old)
        self.assertEqual((following["carried"], following["stop_at"]), ([], None))
        self.assertGreaterEqual(following["since"], following["armed_at"])
        self.assertEqual(self.control.stop_power_countdown(old), control.IGNORED)
        self.assertIsNone(self.stored()["armed"]["stop_at"])
        self.assertFalse(self.control.power_batch_end(old, "skipped"), "an older batch ends nothing")

    def test_a_stop_with_nothing_armed_is_ignored(self):
        self.assertEqual(self.control.stop_power_countdown("a" * 16), control.IGNORED)
        self.assertFalse(self.file.exists())


# ------------------------------------------------------------------------------ the watcher's writes
class WatcherWriteTests(PowerControlCase):
    def test_a_once_is_spent_at_its_end_and_the_end_is_remembered(self):
        self.arm(action="hibernate")
        nonce = self.stored()["armed"]["nonce"]
        self.assertFalse(self.control.power_batch_end(nonce, "not_a_result"))
        self.assertFalse(self.control.power_batch_end("f" * 16, "done"))
        self.assertTrue(self.control.power_batch_end(nonce, "not_met", now=2_000_000_000.0))
        document = self.stored()
        self.assertIsNone(document["armed"])
        self.assertEqual(document["last"], {"action": "hibernate", "result": "not_met", "at": 2_000_000_000.0})
        self.assertFalse(self.control.power_batch_end(nonce, "done"), "spent")

    def test_what_is_shown_is_written_only_when_it_changed_and_only_for_its_batch(self):
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        shown = {"phase": "waiting", "waiting_for": "person_active", "grace_until": None}
        self.assertTrue(self.control.power_show(nonce, shown))
        before = self.file.stat().st_mtime_ns
        self.assertFalse(self.control.power_show(nonce, shown), "unchanged: not written")
        self.assertEqual(self.file.stat().st_mtime_ns, before)
        self.assertFalse(self.control.power_show("f" * 16, dict(shown, waiting_for="no_batch")))
        self.assertFalse(self.control.power_show(nonce, {"phase": "counting"}))
        self.assertFalse(self.control.power_show(nonce, dict(shown, phase="grace")), "grace needs its time")
        for until in (float("nan"), float("inf")):
            with self.subTest(until=until):
                self.assertFalse(self.control.power_show(nonce, dict(shown, phase="grace", grace_until=until)),
                                 "a time that is not a number is never written")
        self.assertEqual(self.file.stat().st_mtime_ns, before)
        self.assertEqual(self.control.get_status()["power_action"]["shown"], shown)

    def test_a_countdown_that_runs_out_ends_done_unless_a_stop_came_first(self):
        """Step 16's write, made before anything is done: done - or skipped when a stop was written for
        the batch meanwhile, read again under the lock - and None for a batch that is over."""
        self.arm(repeat="always")
        first = self.stored()["armed"]["nonce"]
        self.assertIsNone(self.control.power_batch_finish("f" * 16))
        self.assertIsNone(self.control.power_batch_finish("not a nonce"))
        self.assertEqual(self.control.power_batch_finish(first), "done")
        document = self.stored()
        self.assertEqual((document["last"]["action"], document["last"]["result"]), ("sleep", "done"))
        second = document["armed"]["nonce"]
        self.assertNotEqual(second, first, "an Always's next batch has a nonce of its own")
        self.assertIsNone(self.control.power_batch_finish(first), "an older batch ends nothing")
        self.assertEqual(self.control.stop_power_countdown(second, actor="toast"), "stopped")
        self.assertEqual(self.control.power_batch_finish(second), "skipped")
        self.assertEqual(self.stored()["last"]["result"], "skipped")
        self.assertIsNone(self.stored()["armed"]["stop_at"], "the next batch starts unstopped")

    def test_a_busy_lock_ends_nothing(self):
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        with patch.object(control_power, "Mutex", side_effect=AdapterError("mutex_busy")):
            self.assertIsNone(self.control.power_batch_finish(nonce))
            self.assertFalse(self.control.power_refused())
        self.assertEqual(self.stored()["armed"]["nonce"], nonce)

    def test_a_refusal_is_remembered_only_over_a_done(self):
        self.assertFalse(self.control.power_refused(), "no file")
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        self.assertFalse(self.control.power_refused(), "nothing ended yet")
        self.assertTrue(self.control.power_batch_end(nonce, "not_met"))
        self.assertFalse(self.control.power_refused(), "only a done can have been refused")
        self.arm()
        self.assertEqual(self.control.power_batch_finish(self.stored()["armed"]["nonce"]), "done")
        self.assertTrue(self.control.power_refused(now=2_000_000_000.0))
        self.assertEqual(self.stored()["last"], {"action": "sleep", "result": "failed", "at": 2_000_000_000.0})
        self.assertFalse(self.control.power_refused(), "said once")


# ------------------------------------------------------------------------------ reading the file
class FileTests(PowerControlCase):
    def write(self, text):
        self.file.write_text(text, encoding="utf-8")

    def test_a_file_that_cannot_be_believed_is_off_and_left_as_it_is(self):
        self.arm()
        good = self.stored()
        for name, text in (("not json", "{"), ("a list", "[]"),
                           ("bool for int", json.dumps(dict(good, armed=dict(good["armed"], grace_seconds=True)))),
                           ("an unknown key", json.dumps(dict(good, extra=1))),
                           ("a future since", json.dumps(dict(good, armed=dict(good["armed"], armed_at=4e9, since=4e9)))),
                           # A JSON integer too large to be a float: refused, where it once raised OverflowError
                           # from every reader and from the watcher's look.
                           ("a stop too large", json.dumps(dict(good, armed=dict(good["armed"], stop_at=10 ** 400)))),
                           ("a last time too large",
                            json.dumps(dict(good, last={"action": "sleep", "result": "done", "at": 10 ** 400}))),
                           ("too large", json.dumps(dict(good)) + " " * poweraction.FILE_LIMIT)):
            with self.subTest(name):
                self.write(text)
                self.assertEqual(self.control.read_power_action()[0], poweraction.READ_INVALID)
                self.assertEqual(self.control.get_status()["power_action"],
                                 {"armed": None, "shown": None, "last": None})
                self.assertEqual(self.control.power_options()["view"], {"armed": None, "shown": None, "last": None})
                self.assertEqual(self.control.disarm_power_action("mcp"), {"changed": False})
                self.assertEqual(self.control.stop_power_countdown(good["armed"]["nonce"]), control.IGNORED)
                self.assertFalse(self.control.power_batch_end(good["armed"]["nonce"], "done"))
                self.assertEqual(self.file.read_text(encoding="utf-8"), text, "never rewritten")
        self.arm()
        self.assertEqual(self.control.read_power_action()[0], poweraction.READ_OK, "the next arming starts again")
        self.assertIsNone(self.stored()["last"], "nothing of the refused file is kept")

    def test_a_link_in_place_of_the_file_is_never_read(self):
        target = self.home / "elsewhere.json"
        self.arm()
        from codex_auto_resume import config
        with patch.object(config, "is_link", return_value=True):     # a junction or a link, as config sees one
            self.assertEqual(self.control.read_power_action(), (poweraction.READ_INVALID, None))
        target.write_text(self.file.read_text(encoding="utf-8"), encoding="utf-8")
        self.file.unlink()
        try:
            os.symlink(target, self.file)
        except (OSError, NotImplementedError):
            return              # a real link needs a privilege this account may not hold; the stand-in held
        self.assertEqual(self.control.read_power_action()[0], poweraction.READ_INVALID)

    def test_a_file_that_cannot_be_read_just_now_is_unreadable(self):
        self.arm()
        with patch.object(Path, "read_text", side_effect=PermissionError("locked")):
            self.assertEqual(self.control.read_power_action(), (poweraction.READ_UNREADABLE, None))

    def test_every_write_leaves_no_temporary_file(self):
        self.arm()
        nonce = self.stored()["armed"]["nonce"]
        self.control.power_show(nonce, {"phase": "grace", "waiting_for": None, "grace_until": 2_000_000_000.0})
        self.control.stop_power_countdown(nonce)
        self.control.power_batch_end(nonce, "skipped")
        self.assertEqual(list(self.paths.state_dir.glob("power-action.*.tmp")), [])


class BoundaryTests(unittest.TestCase):
    def test_only_the_control_layer_and_the_watcher_reach_the_port_and_only_the_watcher_acts(self):
        importers = {name for name, path in srcscan.modules().items()
                     if any(entry.target == "codex_auto_resume.win.powerdown" for entry in srcscan.imports(path))}
        # v0.6.12 stage 2: the watcher's side (runtime/afterwork.py) is the one place that asks for the action.
        self.assertEqual(importers, {"codex_auto_resume.control.poweraction", "codex_auto_resume.runtime.afterwork"})
        text = Path(control_power.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".act(", text)
        self.assertNotIn("subprocess", text)
        acting = {name for name, path in srcscan.modules().items() if "._port.act(" in srcscan.read(path)
                  or "powerdown.act(" in srcscan.read(path)}
        self.assertEqual(acting, {"codex_auto_resume.runtime.afterwork"})

    def test_only_the_dashboards_bridge_arms_it(self):
        """H14: armed only in the Dashboard. The bridge's power-arm is the one caller of arm_power_action;
        the MCP server, the icon, the notices and the watcher may only turn it off or stop it."""
        callers = {name for name, path in srcscan.modules().items()
                   if "arm_power_action(" in srcscan.read(path).replace("disarm_power_action(", "")
                   and name != "codex_auto_resume.control.poweraction"}
        self.assertEqual(callers, {"codex_auto_resume.controlcli"})
        from codex_auto_resume import controlcli
        self.assertIn("power-arm", controlcli.WITH_ARGUMENT)
        self.assertIn("power-disarm", controlcli.WITH_ARGUMENT)
        self.assertIn("power-action", controlcli.PLAIN)

    def test_nothing_here_sends(self):
        text = Path(control_power.__file__).read_text(encoding="utf-8")
        for word in ("continuation", "backend", "send(", "engine"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
