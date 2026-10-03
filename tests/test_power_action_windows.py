"""v0.6.12: the power action's Windows calls (win/powerdown.py) - what they are, and that no test makes one.

Every call goes through `powerdown._call`, and a fake Windows stands in for it here: no test reads this
PC's token or power capabilities, counts its sessions, or puts it to sleep. `act` refuses on its own
whenever unittest is loaded; the tests that look at what `act` would pass also replace the loader and
ctypes.WinDLL with ones that fail, so a call that went around the fake would raise instead of acting.

What is held: the module reaches only ctypes, os and sys; every library is loaded from System32 alone;
there is no force flag, no hybrid sleep and no wake-timer change; without SeShutdownPrivilege nothing is
offered, whatever the power capabilities say; and no product module imports unittest, so the guard
never stands in the way of the real watcher.
"""
from __future__ import annotations

import ast
import ctypes as C
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import srcscan  # noqa: E402
from codex_auto_resume import poweraction  # noqa: E402
from codex_auto_resume.win import powerdown  # noqa: E402

SRC = Path(_HERE).parent / "src" / "codex_auto_resume"
SOURCE = (SRC / "win" / "powerdown.py").read_text(encoding="utf-8")
SHUTDOWN_LUID = 19                       # SE_SHUTDOWN_PRIVILEGE's LUID on every Windows
OTHER_LUID = 23                          # SeChangeNotifyPrivilege, which every token holds


class FakeWindows:
    """Stands in for `powerdown._call`: each documented function the module may call, answered from
    what the test says, every call recorded. A name not here fails the test."""

    def __init__(self, *, privileges=(OTHER_LUID, SHUTDOWN_LUID), s1=False, s2=False, s3=True, s4=True,
                 hiberfile=True, aoac=False, ticks=10_000, last_input=4_000, sessions=((0, 0), (1, 0)),
                 own_session=1, not_all_assigned=False, refuse=()):
        self.privileges, self.ticks, self.last_input = privileges, ticks, last_input
        self.states = {"SystemS1": s1, "SystemS2": s2, "SystemS3": s3, "SystemS4": s4,
                       "HiberFilePresent": hiberfile, "AoAc": aoac}
        self.sessions, self.own_session = sessions, own_session
        self.not_all_assigned, self.refuse = not_all_assigned, set(refuse)
        self.calls, self.closed, self.freed, self.kept = [], [], 0, []

    def __call__(self, dll, name, result, *arguments):
        answer = getattr(self, "w_" + name, None)
        if answer is None:
            raise AssertionError("powerdown called %s!%s, which the fake does not know" % (dll, name))

        def function(*args):
            self.calls.append((dll, name, args))
            if name in self.refuse:
                return 0
            return answer(*args)
        return function

    def names(self):
        return [name for _dll, name, _args in self.calls]

    # -------------------------------------------------------------- kernel32 and advapi32
    def w_GetCurrentProcess(self):
        return -1

    def w_GetCurrentProcessId(self):
        return 4242

    def w_OpenProcessToken(self, process, access, handle):
        handle._obj.value = 777
        self.access = access
        return 1

    def w_CloseHandle(self, handle):
        self.closed.append(getattr(handle, "value", handle))
        return 1

    def w_LookupPrivilegeValueW(self, system, name, luid):
        assert system is None and name == "SeShutdownPrivilege"
        luid._obj.LowPart, luid._obj.HighPart = SHUTDOWN_LUID, 0
        return 1

    def w_GetTokenInformation(self, token, kind, buffer, length, needed):
        assert kind == 3
        data = len(self.privileges).to_bytes(4, "little") + b"".join(
            luid.to_bytes(4, "little") + (0).to_bytes(4, "little", signed=True) + (0).to_bytes(4, "little")
            for luid in self.privileges)
        needed._obj.value = len(data)
        if buffer is None:
            C.set_last_error(122)                  # ERROR_INSUFFICIENT_BUFFER
            return 0
        C.memmove(buffer, data, len(data))
        return 1

    def w_AdjustTokenPrivileges(self, token, disable_all, change, length, previous, returned):
        self.kept.append(("adjust", bool(disable_all), change._obj.Luid.LowPart, change._obj.Attributes))
        C.set_last_error(1300 if self.not_all_assigned else 0)
        return 1

    def w_ProcessIdToSessionId(self, process, session):
        session._obj.value = self.own_session
        return 1

    def w_GetTickCount(self):
        return self.ticks

    # -------------------------------------------------------------- user32, powrprof, wtsapi32
    def w_GetLastInputInfo(self, last):
        assert last._obj.cbSize == C.sizeof(last._obj)
        last._obj.dwTime = self.last_input
        return 1

    def w_GetPwrCapabilities(self, found):
        for name, value in self.states.items():
            setattr(found._obj, name, int(value))
        return 1

    def w_WTSEnumerateSessionsW(self, server, reserved, version, listing, count):
        assert server is None and reserved == 0 and version == 1
        table = (powerdown._Session * max(1, len(self.sessions)))()
        for index, (session, state) in enumerate(self.sessions):
            table[index].SessionId, table[index].State = session, state
        self.table = table
        listing._obj.contents = table[0]
        count._obj.value = len(self.sessions)
        return 1

    def w_WTSFreeMemory(self, listing):
        self.freed += 1

    def w_SetSuspendState(self, hibernate, force, wake_disabled):
        self.kept.append(("suspend", hibernate, force, wake_disabled))
        return 1

    def w_ExitWindowsEx(self, flags, reason):
        self.kept.append(("exit", flags, reason))
        return 1


def failing_loader(*args, **kwargs):
    raise AssertionError("a real Windows library was loaded in a test")


class Acting:
    """`act` with the unittest guard lifted - and every way to reach a real library made to fail."""

    def __init__(self, fake):
        self.fake = fake
        self.patches = [patch.object(powerdown, "_call", fake), patch.object(powerdown, "_load", failing_loader),
                        patch.object(C, "WinDLL", failing_loader),
                        patch.object(powerdown, "sys", types.SimpleNamespace(modules={}))]

    def __enter__(self):
        self.assert_safe()
        for item in self.patches:
            item.start()
        return self.fake

    def __exit__(self, *unused):
        for item in reversed(self.patches):
            item.stop()

    @staticmethod
    def assert_safe():
        """The fake is the only way in: the module names no library loader but `_load`."""
        assert "windll" not in SOURCE and "oledll" not in SOURCE and "LoadLibrary" not in SOURCE
        assert SOURCE.count("C.WinDLL(") == 1


# ------------------------------------------------------------------------------ the module
class ShapeTests(unittest.TestCase):
    def imports(self):
        tree = ast.parse(SOURCE)
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                found.add(("." * node.level) + (node.module or "").split(".")[0])
        return found

    def test_it_imports_only_ctypes_os_and_sys(self):
        self.assertEqual(self.imports(), {"__future__", "ctypes", "os", "sys"})

    def test_every_library_is_loaded_from_system32_alone(self):
        self.assertEqual(powerdown.LOAD_LIBRARY_SEARCH_SYSTEM32, 0x800)
        loads = [node for node in ast.walk(ast.parse(SOURCE)) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == "WinDLL"]
        self.assertEqual(len(loads), 1)
        self.assertEqual({keyword.arg: ast.unparse(keyword.value) for keyword in loads[0].keywords},
                         {"use_last_error": "True", "winmode": "LOAD_LIBRARY_SEARCH_SYSTEM32"})
        self.assertNotIn("library()", SOURCE)
        self.assertNotIn("windll", SOURCE)

    def test_no_force_flag_and_no_process_starter(self):
        for word in ("EWX_FORCE", "FORCEIFHUNG", "0x4 ", "0x10", "InitiateSystemShutdown", "subprocess",
                     "os.system", "startfile", "ShellExecute", "CreateProcess", "WinExec", "spawn",
                     "powercfg", "shutdown.exe", "rundll32", "schtasks", "Hybrid"):
            with self.subTest(word=word):
                self.assertNotIn(word, SOURCE)
        self.assertEqual(powerdown.EWX_POWEROFF, 0x8)
        self.assertEqual(powerdown.SHTDN_REASON_MAJOR_APPLICATION | powerdown.SHTDN_REASON_FLAG_PLANNED,
                         0x80040000)

    def test_its_words_are_the_power_action_s(self):
        self.assertEqual((powerdown.SLEEP, powerdown.HIBERNATE, powerdown.SHUT_DOWN), poweraction.ACTIONS)
        self.assertEqual((powerdown.NO_PRIVILEGE, powerdown.NO_SLEEP_STATE, powerdown.HIBERNATE_OFF),
                         poweraction.UNAVAILABLE)

    def test_the_power_capabilities_are_windows_own_layout(self):
        self.assertEqual(C.sizeof(powerdown._PowerCapabilities), 76)
        self.assertEqual(C.sizeof(powerdown._TokenPrivilege), 16)

    def test_no_product_module_imports_unittest_so_the_guard_never_holds_the_watcher(self):
        for name, path in srcscan.modules().items():
            for entry in srcscan.imports(path):
                with self.subTest(module=name):
                    self.assertNotEqual(entry.target.split(".")[0], "unittest")

    def test_no_engine_module_names_win_powerdown(self):
        for path in (SRC / "engine").glob("*.py"):
            self.assertNotIn("powerdown", path.read_text(encoding="utf-8"), path.name)


# ------------------------------------------------------------------------------ offering
class AvailableTests(unittest.TestCase):
    def available(self, fake, action):
        with patch.object(powerdown, "_call", fake), patch.object(powerdown, "_load", failing_loader):
            return powerdown.available(action)

    def test_without_the_shutdown_privilege_nothing_is_offered_whatever_windows_can_do(self):
        for action in poweraction.ACTIONS:
            with self.subTest(action=action):
                fake = FakeWindows(privileges=(OTHER_LUID,), s1=True, s2=True, s3=True, s4=True, hiberfile=True)
                self.assertEqual(self.available(fake, action), (False, "no_privilege"))
                self.assertNotIn("GetPwrCapabilities", fake.names(), "the privilege is asked first")
                self.assertIn(777, fake.closed, "the token is closed")

    def test_a_token_that_cannot_be_read_offers_nothing(self):
        for refused in ("OpenProcessToken", "LookupPrivilegeValueW", "GetTokenInformation"):
            with self.subTest(refused=refused):
                fake = FakeWindows(refuse=(refused,))
                self.assertEqual(self.available(fake, "shut_down"), (False, "no_privilege"))

    def test_with_the_privilege_each_action_is_what_windows_reports(self):
        cases = [({}, {"sleep": (True, None), "hibernate": (True, None), "shut_down": (True, None)}),
                 ({"s3": False, "s1": True}, {"sleep": (True, None)}),
                 ({"s3": False, "aoac": True}, {"sleep": (False, "no_sleep_state")}),
                 ({"hiberfile": False}, {"hibernate": (False, "hibernate_off")}),
                 ({"s4": False}, {"hibernate": (False, "hibernate_off")})]
        for changes, expected in cases:
            for action, answer in expected.items():
                with self.subTest(changes=changes, action=action):
                    self.assertEqual(self.available(FakeWindows(**changes), action), answer)
        fake = FakeWindows(refuse=("GetPwrCapabilities",))
        self.assertEqual(self.available(fake, "sleep"), (False, "no_sleep_state"))
        self.assertEqual(self.available(FakeWindows(refuse=("GetPwrCapabilities",)), "shut_down"), (True, None))

    def test_a_word_that_is_no_action_is_never_offered(self):
        fake = FakeWindows()
        self.assertEqual(self.available(fake, "restart"), (False, None))
        self.assertEqual(fake.calls, [])

    def test_only_reading_is_asked_of_the_token_to_offer(self):
        fake = FakeWindows()
        self.available(fake, "sleep")
        self.assertEqual(fake.access, powerdown.TOKEN_QUERY)
        self.assertNotIn("AdjustTokenPrivileges", fake.names())


class PresenceTests(unittest.TestCase):
    def test_idle_is_the_time_since_the_last_input_and_wraps_with_the_tick_count(self):
        for ticks, last, expected in ((10_000, 4_000, 6.0), (500, (1 << 32) - 1_500, 2.0), (7, 7, 0.0)):
            with self.subTest(ticks=ticks, last=last):
                with patch.object(powerdown, "_call", FakeWindows(ticks=ticks, last_input=last)):
                    self.assertEqual(powerdown.idle_seconds(), expected)
        with patch.object(powerdown, "_call", FakeWindows(refuse=("GetLastInputInfo",))):
            self.assertIsNone(powerdown.idle_seconds())

    def test_other_sessions_count_everyone_but_this_one_and_the_services(self):
        sessions = ((0, 0), (1, 0), (2, 0), (3, 4), (4, 1), (5, 6))      # active, disconnected, others
        fake = FakeWindows(sessions=sessions, own_session=1)
        with patch.object(powerdown, "_call", fake):
            self.assertEqual(powerdown.other_sessions(), 2)
        self.assertEqual(fake.freed, 1)
        alone = FakeWindows(sessions=((0, 0), (1, 0)), own_session=1)
        with patch.object(powerdown, "_call", alone):
            self.assertEqual(powerdown.other_sessions(), 0)
        with patch.object(powerdown, "_call", FakeWindows(refuse=("WTSEnumerateSessionsW",))):
            self.assertIsNone(powerdown.other_sessions())


# ------------------------------------------------------------------------------ acting
class ActTests(unittest.TestCase):
    def test_the_guard_refuses_while_unittest_is_loaded_and_asks_windows_nothing(self):
        """The guard alone refuses: the fake Windows here would take every action, as it does below with the
        guard lifted, and every real loader fails - so without the guard this test fails, and acts on nothing."""
        self.assertIn("unittest", sys.modules)
        Acting.assert_safe()
        fake = FakeWindows()
        with patch.object(powerdown, "_call", fake), patch.object(powerdown, "_load", failing_loader),                 patch.object(C, "WinDLL", failing_loader):
            for action in poweraction.ACTIONS:
                with self.subTest(action=action):
                    self.assertIs(powerdown.act(action), False)
        self.assertEqual(fake.calls, [], "Windows was asked nothing")
        for action in poweraction.ACTIONS:
            with self.subTest(lifted=action):
                with Acting(FakeWindows()) as lifted:
                    self.assertIs(powerdown.act(action), True, "the same fake takes it once the guard is lifted")
                self.assertNotEqual(lifted.calls, [])

    def test_sleep_and_hibernate_never_force_and_leave_wake_timers_as_windows_has_them(self):
        for action, hibernate in (("sleep", False), ("hibernate", True)):
            with self.subTest(action=action):
                with Acting(FakeWindows()) as fake:
                    self.assertIs(powerdown.act(action), True)
                self.assertEqual(fake.kept, [("adjust", False, SHUTDOWN_LUID, powerdown.SE_PRIVILEGE_ENABLED),
                                             ("suspend", hibernate, False, False),
                                             ("adjust", False, SHUTDOWN_LUID, 0)])
                self.assertEqual(fake.access, powerdown.TOKEN_ADJUST_PRIVILEGES | powerdown.TOKEN_QUERY)
                self.assertIn(777, fake.closed)

    def test_a_shut_down_is_a_planned_power_off_with_no_force(self):
        with Acting(FakeWindows()) as fake:
            self.assertIs(powerdown.act("shut_down"), True)
        self.assertEqual(fake.kept[1], ("exit", 0x8, 0x80040000))
        self.assertEqual(fake.kept[-1], ("adjust", False, SHUTDOWN_LUID, 0))

    def test_a_privilege_not_assigned_does_nothing_and_closes_the_token(self):
        with Acting(FakeWindows(not_all_assigned=True)) as fake:
            self.assertIs(powerdown.act("shut_down"), False)
        self.assertNotIn("ExitWindowsEx", fake.names())
        self.assertNotIn("SetSuspendState", fake.names())
        self.assertEqual(powerdown.last_error(), 1300)
        self.assertIn(777, fake.closed)

    def test_a_refusal_disables_the_privilege_again(self):
        with Acting(FakeWindows(refuse=("SetSuspendState",))) as fake:
            self.assertIs(powerdown.act("sleep"), False)
        self.assertEqual(fake.kept[-1], ("adjust", False, SHUTDOWN_LUID, 0))
        self.assertIn(777, fake.closed)

    def test_a_word_that_is_no_action_is_never_done(self):
        with Acting(FakeWindows()) as fake:
            self.assertIs(powerdown.act("restart"), False)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
