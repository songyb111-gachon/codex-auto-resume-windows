r"""The icon reuses the settings window that is open (v0.6.20, issue #55).

The report: Open Dashboard, the item for what is waiting and the popup's Dashboard button each opened one more
window beside the one already on screen. The cause was that the window has no single-instance rule of its own
and ui/tray/dashboard.py started a process on every open. Since v0.6.20 open_dashboard asks a window of the same
program first (win/handover.py), and the window answers (gui/WindowReopen.cs, TakeOpenRequest).

The window stand-in here is a real window of this test process, off every screen and never activated, registered
under a Windows Forms class name so the hand-over finds it the way it finds the settings window: by the program its
process runs (this Python) and by its class. It shows nothing and asks nothing. No real window is started: every
process start is replaced.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import itertools
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

import guiscan
from codex_auto_resume import config
from codex_auto_resume.ui import tray
from codex_auto_resume.ui.tray import dashboard, menu
from codex_auto_resume.win import handover

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
POWERSHELL = (Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
              / "WindowsPowerShell" / "v1.0" / "powershell.exe")
WINDOWS = os.name == "nt"

_LRESULT = C.c_ssize_t
_WNDPROC = C.WINFUNCTYPE(_LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
WM_CLOSE, WM_DESTROY = 0x0010, 0x0002
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
SW_SHOWNOACTIVATE = 4
_names = itertools.count(1)


class _WndClass(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", _WNDPROC), ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int),
                ("hInstance", W.HINSTANCE), ("hIcon", W.HICON), ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH),
                ("lpszMenuName", W.LPCWSTR), ("lpszClassName", W.LPCWSTR)]


class _CopyData(C.Structure):
    _fields_ = [("dwData", C.c_size_t), ("cbData", W.DWORD), ("lpData", C.c_void_p)]


def _user32():
    user32 = C.WinDLL("user32", use_last_error=True)
    user32.DefWindowProcW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    user32.DefWindowProcW.restype = _LRESULT
    user32.RegisterClassW.argtypes = (C.POINTER(_WndClass),)
    user32.RegisterClassW.restype = W.ATOM
    user32.UnregisterClassW.argtypes = (W.LPCWSTR, W.HINSTANCE)
    user32.CreateWindowExW.argtypes = (W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int,
                                       W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID)
    user32.CreateWindowExW.restype = W.HWND
    user32.ShowWindow.argtypes = (W.HWND, C.c_int)
    user32.DestroyWindow.argtypes = (W.HWND,)
    user32.PostMessageW.argtypes = (W.HWND, W.UINT, W.WPARAM, W.LPARAM)
    user32.GetMessageW.argtypes = (C.c_void_p, W.HWND, W.UINT, W.UINT)
    user32.TranslateMessage.argtypes = (C.c_void_p,)
    user32.DispatchMessageW.argtypes = (C.c_void_p,)
    return user32


class StandIn:
    """A window of this process that answers an open request as the settings window does - TAKEN, or (`takes`
    False) nothing, as a window from before v0.6.20 - and remembers each page it was asked for."""

    def __init__(self, takes=True):
        self.takes, self.asked, self.hwnd = takes, [], None
        self.name = "WindowsForms10.CarHandoverStandIn.%d.%d" % (os.getpid(), next(_names))
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="handover-stand-in", daemon=True)

    def __enter__(self):
        self._thread.start()
        if not self._ready.wait(10) or not self.hwnd:
            raise RuntimeError("the stand-in window was not made")
        return self

    def __exit__(self, *_):
        if self.hwnd:
            self._user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self._thread.join(10)

    def _proc(self, hwnd, message, wparam, lparam):
        try:
            if message == handover.WM_COPYDATA and lparam:
                copy = _CopyData.from_address(lparam)
                if copy.dwData == handover.OPEN_REQUEST_MARK:
                    text = C.wstring_at(copy.lpData, copy.cbData // 2) if copy.cbData else ""
                    self.asked.append(text)
                    return handover.OPEN_REQUEST_TAKEN if self.takes else 0
            if message == WM_CLOSE:
                self._user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0
        except Exception:
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _run(self):
        user32 = self._user32 = _user32()
        self._wndproc = _WNDPROC(self._proc)
        klass = _WndClass()
        klass.lpfnWndProc = self._wndproc
        klass.lpszClassName = self.name
        kernel32 = C.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes, kernel32.GetModuleHandleW.restype = (W.LPCWSTR,), W.HMODULE
        klass.hInstance = kernel32.GetModuleHandleW(None)
        try:
            if not user32.RegisterClassW(C.byref(klass)):
                return
            # Off every screen, never activated, with no taskbar button: visible to Windows, seen by nobody.
            self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, self.name, "stand-in", WS_POPUP,
                                               -32000, -32000, 1, 1, None, None, klass.hInstance, None)
            if self.hwnd:
                user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        finally:
            self._ready.set()
        message = W.MSG()
        while user32.GetMessageW(C.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(C.byref(message))
            user32.DispatchMessageW(C.byref(message))
        user32.UnregisterClassW(self.name, klass.hInstance)


def stand_in_for(case, target, name, value):
    patcher = patch.object(target, name, value)
    patcher.start()
    case.addCleanup(patcher.stop)


def own_windows_only(case):
    """windows_of narrowed to this process, so a run of this module in another process cannot answer for ours."""
    real = handover.windows_of
    stand_in_for(case, handover, "windows_of", lambda exe: [(w, pid) for w, pid in real(exe) if pid == os.getpid()])


class Started:
    """subprocess.Popen in dashboard.py, replaced: nothing is ever started."""

    def __init__(self):
        self.calls = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(list(arguments))
        return types.SimpleNamespace(pid=0)


class ScratchHome(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name) / "home"
        self.home.mkdir()
        (self.home / "CodexAutoResumeSettings.exe").write_bytes(b"MZ")      # a file to find; never run
        self.started = Started()
        stand_in_for(self, dashboard.subprocess, "Popen", self.started)


# ------------------------------------------------------------------------- the open path
class OpenAsksFirstTests(ScratchHome):
    def test_a_window_that_takes_the_request_means_nothing_is_started(self):
        asked = []
        with patch.object(handover, "hand_over", lambda exe, page=None: asked.append((Path(exe), page)) or True):
            self.assertTrue(tray.open_dashboard(self.home, "pending"))
            self.assertTrue(tray.open_dashboard(self.home))
        self.assertEqual(asked, [(self.home / "CodexAutoResumeSettings.exe", "pending"),
                                 (self.home / "CodexAutoResumeSettings.exe", None)])
        self.assertEqual(self.started.calls, [])

    def test_with_no_window_to_take_it_one_is_started_as_before(self):
        with patch.object(handover, "hand_over", lambda exe, page=None: False):
            self.assertTrue(tray.open_dashboard(self.home, "pending"))
        self.assertEqual(self.started.calls, [[str(self.home / "CodexAutoResumeSettings.exe"), "--page=pending"]])

    def test_a_page_not_of_the_window_is_refused_before_anything_is_asked(self):
        with patch.object(handover, "hand_over", lambda exe, page=None: self.fail("asked")):
            with self.assertRaises(ValueError):
                tray.open_dashboard(self.home, "--chat=x")

    def test_nothing_installed_asks_nothing_and_starts_nothing(self):
        (self.home / "CodexAutoResumeSettings.exe").unlink()
        with patch.object(handover, "hand_over", lambda exe, page=None: self.fail("asked")):
            self.assertFalse(tray.open_dashboard(self.home, "pending"))
        self.assertEqual(self.started.calls, [])


@unittest.skipUnless(WINDOWS, "a Windows window answers the request")
class RunningWindowTests(ScratchHome):
    """The real hand-over, against the stand-in: the program it looks for is this Python's."""

    def setUp(self):
        super().setUp()
        own_windows_only(self)
        real = handover.hand_over
        # open_dashboard looks for the scratch home's window program; the stand-in runs in this Python.
        stand_in_for(self, handover, "hand_over", lambda exe, page=None: real(Path(sys.executable), page))

    def test_a_second_open_while_one_runs_starts_no_process_and_brings_that_page(self):
        with StandIn() as window:
            self.assertTrue(tray.open_dashboard(self.home, "pending"))
            self.assertTrue(tray.open_dashboard(self.home))
        self.assertEqual(window.asked, ["pending", ""])
        self.assertEqual(self.started.calls, [])

    def test_every_tray_item_that_shows_something_goes_to_the_open_window(self):
        """Open Dashboard, the waiting item and the popup's Dashboard button, as the watcher wires them."""
        icon = types.SimpleNamespace(on_open=lambda: tray.open_dashboard(self.home),
                                     on_pending=lambda: tray.open_dashboard(self.home, "pending"),
                                     on_stop=None, on_toggle=None, control=None, log=lambda text: None)
        with StandIn() as window:
            menu.MenuMixin._act(icon, menu.MENU_OPEN, False)
            menu.MenuMixin._act(icon, menu.MENU_PENDING, False)
        self.assertEqual(window.asked, ["", "pending"])
        self.assertEqual(self.started.calls, [])

    def test_a_window_from_before_that_does_not_answer_leaves_the_open_as_it_was(self):
        with StandIn(takes=False) as window:
            self.assertTrue(tray.open_dashboard(self.home, "history"))
        self.assertEqual(window.asked, ["history"])
        self.assertEqual(len(self.started.calls), 1)


@unittest.skipUnless(WINDOWS, "Windows' windows")
class HandoverTests(unittest.TestCase):
    def setUp(self):
        own_windows_only(self)

    def test_the_window_is_found_by_the_program_its_process_runs(self):
        with StandIn() as window:
            self.assertIn((window.hwnd, os.getpid()), handover.windows_of(sys.executable))
            # Another program's path - the same name in another folder - finds nothing of this process.
            with tempfile.TemporaryDirectory() as other:
                self.assertEqual(handover.windows_of(Path(other) / Path(sys.executable).name), [])
            self.assertTrue(handover.hand_over(sys.executable, "settings"))
        self.assertEqual(window.asked, ["settings"])

    def test_one_program_under_another_spelling_is_the_same_program(self):
        spelled = Path(str(Path(sys.executable)).upper())
        self.assertEqual(handover.spelled(spelled), handover.spelled(sys.executable))
        with StandIn() as window:
            self.assertTrue(handover.hand_over(spelled))
        self.assertEqual(window.asked, [""])

    def test_no_window_open_is_no_hand_over(self):
        self.assertFalse(handover.hand_over(sys.executable, "pending"))


# ------------------------------------------------------------------------- Pause and Resume
class PauseResumeTests(ScratchHome):
    def test_pause_and_resume_from_the_menu_act_directly_and_open_no_window(self):
        toggled = []
        icon = types.SimpleNamespace(on_open=lambda: tray.open_dashboard(self.home),
                                     on_pending=lambda: tray.open_dashboard(self.home, "pending"),
                                     on_stop=None, on_toggle=toggled.append, control=None,
                                     log=lambda text: self.fail(text))
        with patch.object(handover, "hand_over", lambda exe, page=None: self.fail("a window was asked")):
            menu.MenuMixin._act(icon, menu.MENU_TOGGLE, False)      # running -> pause
            menu.MenuMixin._act(icon, menu.MENU_TOGGLE, True)       # paused -> resume
        self.assertEqual(toggled, [False, True])
        self.assertEqual(self.started.calls, [])

    @unittest.skipUnless(WINDOWS, "the icon is a Windows notification-area icon")
    def test_the_watchers_toggle_changes_the_paused_state_and_starts_nothing(self):
        from codex_auto_resume import app
        from codex_auto_resume.control import Control

        def enabled(paths):
            # The state itself, read as the watcher reads it: no status, which would ask Windows about autostart.
            with Control(paths)._open(legacy_ok=True) as store:
                return bool(store.settings()["enabled"])

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        codex = Path(folder.name) / "codex"
        codex.mkdir()
        local = Path(folder.name) / "local"
        local.mkdir()
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(local)})
        environment.start()
        self.addCleanup(environment.stop)
        paths = config.Paths(Path(folder.name) / "watcher")
        instance = app.App(paths, codex_home=codex, enable_logging=False)
        made = {}

        class Recorder:
            def __init__(self, **kwargs):
                made.update(kwargs)

            def start(self):
                return True

        with patch.object(tray, "Tray", Recorder), \
             patch.object(handover, "hand_over", lambda exe, page=None: self.fail("a window was asked")):
            instance._start_tray(stop=None)
            made["on_toggle"](False)                                  # Pause
            self.assertFalse(enabled(paths))
            made["on_toggle"](True)                                   # Resume
            self.assertTrue(enabled(paths))
        self.assertEqual(self.started.calls, [])


# ------------------------------------------------------------------------- the window's side
class WindowSideTests(unittest.TestCase):
    def test_the_window_takes_the_request_before_anything_else_it_handles(self):
        body = guiscan.member_body("SettingsForm", "WndProc")
        self.assertTrue(body.split("{", 1)[1].lstrip().startswith(
            "if (m.Msg == WM_COPYDATA && TakeOpenRequest(ref m)) return;"), body[:300])
        take = guiscan.member_body("SettingsForm", "TakeOpenRequest")
        self.assertIn("if (copy.Data.ToInt64() != OpenRequestMark) return false;", take)
        # A window nobody uses refuses, and the watcher starts one as it always did.
        self.assertIn("if (Soft.StillReady != null || auditing || !shown || IsDisposed || Disposing) return false;", take)
        self.assertIn("m.Result = (IntPtr)OpenRequestTaken;", take)
        self.assertLess(take.index("m.Result = (IntPtr)OpenRequestTaken;"), take.index("BeginInvoke("))
        forward = guiscan.member_body("SettingsForm", "ComeForwardOn")
        self.assertIn("ShowPage(page);", forward)
        self.assertIn("HostApp.ComeForward(this);", forward)
        self.assertIn("ChangeWindowMessageFilterEx(Handle, WM_COPYDATA, MessageFilterAllow, IntPtr.Zero);",
                      guiscan.member_body("SettingsForm", "AcceptOpenRequests"))
        # Asked as it is first shown, and from then on (a window not yet shown refuses).
        self.assertRegex(guiscan.type_body("SettingsForm", "gui/SettingsApp.cs"), r"shown = true;\s*//[^\n]*\s*AcceptOpenRequests\(\);")

    def test_the_mark_and_the_answer_are_the_same_on_both_sides(self):
        window = guiscan.type_body("SettingsForm", "gui/WindowReopen.cs")

        def constant(name):
            found = re.search(r"internal const (?:int|long) %s = (0x[0-9A-Fa-f]+);" % name, window)
            self.assertIsNotNone(found, name)
            return int(found.group(1), 16)

        self.assertEqual(constant("WM_COPYDATA"), handover.WM_COPYDATA)
        self.assertEqual(constant("OpenRequestMark"), handover.OPEN_REQUEST_MARK)
        self.assertEqual(constant("OpenRequestTaken"), handover.OPEN_REQUEST_TAKEN)


PROBE = r"""
$ErrorActionPreference = 'Stop'
$assembly = [Reflection.Assembly]::LoadFile($env:CAR_EXE)
$form = $assembly.GetType('CodexAutoResume.SettingsForm', $true)
$page = $form.GetMethod('OpenRequestPage', [Reflection.BindingFlags]'Static,NonPublic,Public')
if (-not $page) { throw 'SettingsForm has no OpenRequestPage' }
$out = New-Object System.Collections.ArrayList
foreach ($text in @('overview', 'pending', 'history', 'statistics', 'diagnostics', 'settings', '', 'advanced',
                    'Pending', '--page=pending', 'x')) {
    $answer = $page.Invoke($null, [object[]]@([string]$text))
    # Pairs, not a hashtable: PowerShell's keys ignore case, and 'Pending' would overwrite 'pending'.
    [void]$out.Add(@($text, $(if ($answer -eq $null) { '<null>' } else { [string]$answer })))
}
[void]$out.Add(@('<null>', $(if ($page.Invoke($null, [object[]]@($null)) -eq $null) { '<null>' } else { 'taken' })))
ConvertTo-Json -InputObject $out -Compress
"""


@unittest.skipUnless(CSC.is_file() and POWERSHELL.is_file(), "needs the in-box compiler and PowerShell")
class WindowDecisionTests(unittest.TestCase):
    """The compiled window's own rule for what it takes, called through reflection: no window is made."""

    def test_the_window_takes_its_pages_or_none_and_nothing_else(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            exe = Path(folder) / "CodexAutoResumeSettings.exe"
            subprocess.run([str(CSC), "/nologo", "/target:winexe", "/platform:x64", "/out:" + str(exe),
                            "/reference:System.dll", "/reference:System.Drawing.dll",
                            "/reference:System.Windows.Forms.dll", *[str(path) for path in guiscan.sources()]],
                           check=True, capture_output=True, timeout=300,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            probe = Path(folder) / "probe.ps1"
            probe.write_text(PROBE, encoding="utf-8")
            result = subprocess.run([str(POWERSHELL), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                     "-File", str(probe)], capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=300, env=dict(os.environ, CAR_EXE=str(exe)),
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        answer = dict(json.loads(result.stdout))
        for page in tray.PAGES:
            self.assertEqual(answer[str(page)], str(page))
        self.assertEqual(answer[""], "")
        for refused in ("advanced", "Pending", "--page=pending", "x", "<null>"):
            self.assertEqual(answer[refused], "<null>", refused)


if __name__ == "__main__":
    unittest.main()
