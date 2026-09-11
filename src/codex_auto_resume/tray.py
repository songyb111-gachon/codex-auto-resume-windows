"""The watcher's notification-area icon.

Owned by the watcher process and by nothing else: it appears when a watcher starts and
disappears when it stops, so it can never show a watcher that is not there - which a
separate tray process could. It runs its own message loop on its own thread, and every
action it offers goes through the same control layer as every other interface.

It decides nothing. It shows what the last tick found - paused or not, how many
recoveries are waiting, when the next one is due - and counts that time down locally.
Reaching zero only means the watcher looks again; nothing is sent because of it.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
from pathlib import Path
import subprocess
import threading
import time

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_APP = 0x8000
CALLBACK = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512
TIP_CHARS = 128

MENU_OPEN, MENU_TOGGLE, MENU_STOP = 1, 2, 3
_DLLS = {}


def _dll(name):
    """This module's own handle on a system DLL.

    `ctypes.windll` is shared by the whole process, and the argument types set here
    would silently change how every other module's calls into the same DLL convert
    their arguments. A private handle keeps these declarations to this file.
    """
    if name not in _DLLS:
        _DLLS[name] = C.WinDLL(name, use_last_error=True)
    return _DLLS[name]

LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASSW(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR)]


class GUID(C.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", C.c_ubyte * 8)]


class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("uFlags", W.UINT),
                ("uCallbackMessage", W.UINT), ("hIcon", W.HICON), ("szTip", W.WCHAR * TIP_CHARS),
                ("dwState", W.DWORD), ("dwStateMask", W.DWORD), ("szInfo", W.WCHAR * 256),
                ("uVersion", W.UINT), ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", W.HICON)]


class MSG(C.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", W.WPARAM), ("lParam", W.LPARAM),
                ("time", W.DWORD), ("pt", W.POINT)]


def countdown(seconds: float) -> str:
    """A short, locale-neutral duration: 45s, 12:04, 3:05:00."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    if minutes:
        return "%d:%02d" % (minutes, secs)
    return "%ds" % secs


def tooltip(snapshot: dict, strings: dict, now: float) -> str:
    """What hovering over the icon says. Built from the last tick; counted down locally."""
    title = strings.get("tray.title", "Codex Auto Resume")
    if not snapshot:
        return title
    if not snapshot.get("enabled", True):
        line = strings.get("tray.paused", "Paused")
    else:
        waiting, running = snapshot.get("waiting", 0), snapshot.get("running", 0)
        parts = []
        if running:
            parts.append(strings.get("tray.running", "{n} running in Codex").replace("{n}", str(running)))
        if waiting:
            parts.append(strings.get("tray.waiting", "{n} waiting").replace("{n}", str(waiting)))
            due = snapshot.get("next_at")
            if due:
                parts.append(strings.get("tray.next", "next check in {time}")
                             .replace("{time}", countdown(due - now)))
        line = " · ".join(parts) if parts else strings.get("tray.idle", "Nothing waiting")
    return (title + "\n" + line)[:TIP_CHARS - 1]


class Tray:
    """One icon, one hidden window, one thread."""

    def __init__(self, *, icon_path=None, strings=None, on_open=None, on_toggle=None, on_stop=None,
                 log=None):
        self.icon_path = Path(icon_path) if icon_path else None
        self.strings = strings or {}
        self.on_open, self.on_toggle, self.on_stop = on_open, on_toggle, on_stop
        self.log = log or (lambda *args: None)
        self._snapshot = {}
        self._lock = threading.Lock()
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._proc = None           # keeps the callback alive for the window's life
        self._icon = None
        self._last_tip = None
        self._taskbar_created = None
        self._class_name = None

    # ----------------------------------------------------------------- public
    def start(self) -> bool:
        if os.name != "nt":
            return False
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        return self._ready.wait(5) and self._hwnd is not None

    def update(self, snapshot: dict) -> None:
        with self._lock:
            self._snapshot = dict(snapshot)

    def stop(self) -> None:
        if self._hwnd:
            _dll("user32").PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(5)

    # ---------------------------------------------------------------- window
    def _run(self):
        try:
            self._create()
        except Exception as exc:          # a missing tray must never stop the watcher
            self.log("tray unavailable (%s)" % type(exc).__name__)
            self._ready.set()
            return
        self._ready.set()
        user32 = _dll("user32")
        message = MSG()
        while user32.GetMessageW(C.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(C.byref(message))
            user32.DispatchMessageW(C.byref(message))
        # The class name is this icon's own; free it so the next icon can register.
        user32.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
        user32.UnregisterClassW(self._class_name, _dll("kernel32").GetModuleHandleW(None))

    def _create(self):
        user32, kernel32 = _dll("user32"), _dll("kernel32")
        user32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.restype = W.HWND
        user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
                                           C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
        user32.LoadImageW.restype = W.HANDLE
        user32.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
        user32.LoadIconW.restype = W.HICON
        user32.LoadIconW.argtypes = [W.HINSTANCE, W.LPVOID]
        user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user32.TrackPopupMenu.argtypes = [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, W.LPVOID]
        user32.AppendMenuW.argtypes = [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR]
        user32.CreatePopupMenu.restype = W.HMENU
        user32.DestroyMenu.argtypes = [W.HMENU]
        user32.SetTimer.argtypes = [W.HWND, C.c_size_t, W.UINT, W.LPVOID]
        user32.KillTimer.argtypes = [W.HWND, C.c_size_t]
        user32.RegisterWindowMessageW.restype = W.UINT
        _dll("shell32").Shell_NotifyIconW.argtypes = [W.DWORD, C.POINTER(NOTIFYICONDATAW)]
        kernel32.GetModuleHandleW.restype = W.HMODULE
        instance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        # Unique per icon, not per process: an icon started after another one in the
        # same process must not collide with a class the first one registered.
        self._class_name = "CodexAutoResumeTray-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self._class_name
        if not user32.RegisterClassW(C.byref(klass)):
            raise OSError("RegisterClassW")
        # A hidden top-level window, not a message-only one: only a real top-level
        # window hears "TaskbarCreated", which is how the icon comes back after Explorer
        # restarts.
        self._hwnd = user32.CreateWindowExW(0, klass.lpszClassName, "Codex Auto Resume", 0,
                                            0, 0, 0, 0, None, None, instance, None)
        if not self._hwnd:
            raise OSError("CreateWindowExW")
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._icon = self._load_icon()
        self._notify(NIM_ADD)
        user32.SetTimer(self._hwnd, 1, 1000, None)

    def _load_icon(self):
        user32 = _dll("user32")
        width, height = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        if self.icon_path and self.icon_path.is_file():
            handle = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, width, height, LR_LOADFROMFILE)
            if handle:
                return handle
        return user32.LoadIconW(None, C.c_void_p(IDI_APPLICATION))

    def _data(self, flags):
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = CALLBACK
        data.hIcon = self._icon
        with self._lock:
            snapshot = dict(self._snapshot)
        data.szTip = tooltip(snapshot, self.strings, time.time())
        return data

    def _notify(self, action):
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self._last_tip = data.szTip
        return _dll("shell32").Shell_NotifyIconW(action, C.byref(data))

    def _refresh(self):
        with self._lock:
            snapshot = dict(self._snapshot)
        text = tooltip(snapshot, self.strings, time.time())
        if text != self._last_tip:
            self._notify(NIM_MODIFY)

    def _menu(self):
        user32 = _dll("user32")
        with self._lock:
            snapshot = dict(self._snapshot)
        menu = user32.CreatePopupMenu()
        try:
            status = tooltip(snapshot, self.strings, time.time()).split("\n", 1)[-1]
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, status)
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_OPEN,
                               self.strings.get("menu.open", "Open Codex Auto Resume"))
            paused = not snapshot.get("enabled", True)
            user32.AppendMenuW(menu, MF_STRING, MENU_TOGGLE,
                               self.strings.get("menu.resume", "Resume recovery") if paused
                               else self.strings.get("menu.pause", "Pause recovery"))
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_STOP, self.strings.get("menu.stop", "Stop the watcher"))
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            # Without this the menu does not close when the user clicks elsewhere.
            user32.SetForegroundWindow(self._hwnd)
            chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                           point.x, point.y, 0, self._hwnd, None)
            user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        self._act(chosen, paused)

    def _act(self, chosen, paused):
        action = {MENU_OPEN: self.on_open, MENU_STOP: self.on_stop}.get(chosen)
        try:
            if chosen == MENU_TOGGLE and self.on_toggle:
                self.on_toggle(paused)          # paused -> resume; running -> pause
            elif action:
                action()
        except Exception as exc:
            self.log("tray action failed (%s)" % type(exc).__name__)

    def _wndproc(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        try:
            if message == CALLBACK:
                event = lparam & 0xFFFF
                if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                elif event in (WM_LBUTTONDBLCLK,) and self.on_open:
                    self._act(MENU_OPEN, False)
                return 0
            if message == WM_TIMER:
                self._refresh()
                return 0
            if self._taskbar_created and message == self._taskbar_created:
                self._notify(NIM_ADD)
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.KillTimer(hwnd, 1)
                data = NOTIFYICONDATAW()
                data.cbSize = C.sizeof(NOTIFYICONDATAW)
                data.hWnd = hwnd
                data.uID = 1
                _dll("shell32").Shell_NotifyIconW(NIM_DELETE, C.byref(data))
                user32.PostQuitMessage(0)
                return 0
        except Exception as exc:
            self.log("tray message failed (%s)" % type(exc).__name__)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


def snapshot_from(store, now: float) -> dict:
    """What the icon shows, from our own store only: no Codex read, no content."""
    from . import machine
    waiting, running, due = 0, 0, []
    for row in store.pending():
        if row["state"] in machine.WAITING:
            waiting += 1
            at = machine.eligible_at(row)
            if at:
                due.append(at)
        else:
            running += 1
    return {"enabled": store.settings()["enabled"], "waiting": waiting, "running": running,
            "next_at": min(due) if due else None}


def open_dashboard(home: Path) -> bool:
    """Start the settings window, if it is installed beside the watcher."""
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    subprocess.Popen([str(exe)], cwd=str(home), close_fds=True)
    return True
