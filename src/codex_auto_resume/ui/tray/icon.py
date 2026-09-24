"""The icon itself: one thread, one hidden window, and the life of both.

Everything Windows says to this product's notification-area icon arrives at `_wndproc` below
and leaves as a call into one of the mixins beside it. `Tray` is composed here rather than in
the package's `__init__`, so that the front holds no code of its own.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import os
import threading
import time
from pathlib import Path

from .animation import AnimationMixin
from .cards import CardsMixin
from .clicks import ClicksMixin
from .menu import APP_MODE_DEFAULT, MenuMixin
from .model import snapshot_from  # noqa: F401
from .motion import build_icon_frames
from .stored import StoredMixin
from .win32 import (CALLBACK,
                    IDI_APPLICATION,
                    IMAGE_ICON,
                    LR_LOADFROMFILE,
                    MSG,
                    NIF_ICON,
                    NIF_MESSAGE,
                    NIF_SHOWTIP,
                    NIF_TIP,
                    NIM_ADD,
                    NIM_DELETE,
                    NIM_MODIFY,
                    NIM_SETVERSION,
                    NIN_KEYSELECT,
                    NIN_SELECT,
                    NOTIFYICONDATAW,
                    NOTIFYICON_VERSION_4,
                    NOTIFY_FOR_THIS_SESSION,
                    SM_CXSMICON,
                    SM_CYSMICON,
                    TIMER_FRAME,
                    TIMER_TICK,
                    WM_CLOSE,
                    WM_CONTEXTMENU,
                    WM_DESTROY,
                    WM_LBUTTONDBLCLK,
                    WM_LBUTTONUP,
                    WM_RBUTTONUP,
                    WM_TIMER,
                    WM_TRAY_FRAMES,
                    WM_WTSSESSION_CHANGE,
                    WTS_CONSOLE_CONNECT,
                    WTS_CONSOLE_DISCONNECT,
                    WTS_REMOTE_CONNECT,
                    WTS_REMOTE_DISCONNECT,
                    WTS_SESSION_LOCK,
                    WTS_SESSION_UNLOCK,
                    _dll)
from .words import tooltip
from ...win.dll import LRESULT, WNDCLASSW, WNDPROC


class Tray(MenuMixin, StoredMixin, CardsMixin, ClicksMixin, AnimationMixin):
    """One icon, one hidden window, one thread - and, once clicked, one popup on it."""


    def __init__(self, *, icon_path=None, strings=None, on_open=None, on_toggle=None, on_stop=None,
                 on_pending=None, log=None, control=None, pending_source=None, on_dashboard=None,
                 inbox=None, on_notice_action=None, on_notice_complete=None):
        self.icon_path = Path(icon_path) if icon_path else None
        self.strings = strings or {}
        self.on_open, self.on_toggle, self.on_stop = on_open, on_toggle, on_stop
        self.on_pending = on_pending
        self.log = log or (lambda *args: None)
        # The popup's only way to act: the shared control layer, plus the read-only source
        # `list_pending` uses to attach conversation names. Without a control there is no
        # popup, and a double click opens the Dashboard as it did before v0.6.3.
        self.control = control
        self.pending_source = pending_source
        self.on_dashboard = on_dashboard
        self._snapshot = {}
        self._lock = threading.Lock()
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._proc = None           # keeps the callback alive for the window's life
        self._icon = None
        self._icon_owned = False
        self._failed = False        # the icon shows a failure nobody has seen (_failure_unseen)
        self._shown_icon = None
        self._last_tip = None
        self._taskbar_created = None
        self._class_name = None
        self._version4 = False
        self._popup = None
        self._popup_failed = False
        self._settings_stamp = None   # the settings file as last read: (mtime, size), or None
        self._settings_values = None
        self._menu_mode = APP_MODE_DEFAULT   # what this process's menus were last asked to be
        self._menu_theming = True            # False once Windows could not be asked
        # v0.6.5: the icon's motion. Until its frame table is built (off this thread) the icon is
        # the .ico, and if the table cannot be built it stays that way. Once it is, every icon shown is one composed frame, made into
        # an HICON as it is shown and destroyed once the shell holds the next: two at most.
        self._frames = None           # IconFrames once built; False when it could not be
        self._frames_result = None    # what the building thread left: (frames, reason)
        self._frame_icon = None       # the composed frame on show, if any
        self._frame_key = None
        self._icon_state = None
        self._state_since = time.monotonic()
        self._epoch = time.monotonic()      # the motion's clock: breaths and turns count from here
        self._motion_allowed = False
        self._motion_ms = None              # the frame timer's interval while it runs
        self._session_locked = False
        self._session_away = False
        self._session_watch = False
        self._motion_read_failed = False    # said once until the settings file can be read again
        self._placement = None              # IconPlacement once the icon has something to move
        # v0.6.5: the notification card. With an inbox, this thread hosts the cards once its window
        # exists (notice_window.CardStack attaches itself to the inbox); a card's button calls
        # `on_notice_action(uri)` and each notice the stack took is ended by
        # `on_notice_complete(notice, shown)`, both on worker threads. No inbox, or a stack that
        # could not be made: no card, and every notification stays today's toast.
        self.inbox = inbox
        self.on_notice_action = on_notice_action
        self.on_notice_complete = on_notice_complete
        self._cards = None

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

    def set_strings(self, strings: dict) -> None:
        """Adopt a new vocabulary, after the Interface language changed."""
        with self._lock:
            self.strings = dict(strings or {})
            # Forget the last tooltip so the next tick rewrites it even if the numbers in
            # it have not moved.
            self._last_tip = None
        popup = self._popup
        if popup is not None:
            popup.set_strings(strings)

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
        user32.DestroyIcon.argtypes = [W.HICON]
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
        self._shown_icon = self._icon
        self._notify(NIM_ADD)
        self._set_version()
        self._host_cards()
        user32.SetTimer(self._hwnd, TIMER_TICK, 1000, None)
        self._watch_session()
        if self._icon_owned:
            # Only for our own mark: a missing .ico keeps Windows' generic icon, unmoved.
            self._build_frames_later(user32.GetSystemMetrics(SM_CXSMICON))



    def _load_icon(self):
        user32 = _dll("user32")
        width, height = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        if self.icon_path and self.icon_path.is_file():
            handle = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, width, height, LR_LOADFROMFILE)
            if handle:
                self._icon_owned = True
                return handle
        self._icon_owned = False            # a shared system icon is never destroyed
        return user32.LoadIconW(None, C.c_void_p(IDI_APPLICATION))

    def _data(self, flags):
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = CALLBACK
        data.hIcon = self._shown_icon or self._icon
        data.szTip = tooltip(self._shown(), self.strings, time.time())
        return data

    def _shown(self) -> dict:
        """The last tick's snapshot as the icon shows it: with whether a failure nobody has seen is on it."""
        with self._lock:
            snapshot = dict(self._snapshot)
        snapshot["failed"] = self._failed
        return snapshot

    def _notify(self, action):
        # NIF_SHOWTIP: under version 4 the shell hides the standard tooltip unless asked.
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        self._last_tip = data.szTip
        return _dll("shell32").Shell_NotifyIconW(action, C.byref(data))

    def _set_version(self):
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uVersion = NOTIFYICON_VERSION_4
        self._version4 = bool(_dll("shell32").Shell_NotifyIconW(NIM_SETVERSION, C.byref(data)))

    def _refresh(self):
        with self._lock:
            snapshot = dict(self._snapshot)
        self._failed = self._failure_unseen(snapshot)
        snapshot["failed"] = self._failed
        text = tooltip(snapshot, self.strings, time.time())
        changed, replaced = False, []
        if self._frames:
            self._observe(snapshot)
            changed, replaced = self._frame_for(time.monotonic())
        if text != self._last_tip or changed:
            self._notify(NIM_MODIFY)
        for handle in replaced:
            if handle:
                _dll("user32").DestroyIcon(handle)      # only after the shell holds the new one
        self._sync_motion()



    def _watch_session(self):
        """Hear when the session is locked or disconnected: nobody sees the icon move then."""
        try:
            wts = _dll("wtsapi32")
            wts.WTSRegisterSessionNotification.argtypes = [W.HWND, W.DWORD]
            wts.WTSRegisterSessionNotification.restype = W.BOOL
            self._session_watch = bool(wts.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION))
        except Exception:
            self._session_watch = False           # then the lock is simply not known; nothing else changes

    def _session_changed(self, event):
        if event == WTS_SESSION_LOCK:
            self._session_locked = True
        elif event == WTS_SESSION_UNLOCK:
            self._session_locked = False
        elif event in (WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT):
            self._session_away = True
        elif event in (WTS_CONSOLE_CONNECT, WTS_REMOTE_CONNECT):
            self._session_away = False
        else:
            return
        self._refresh()



    def _wndproc(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        try:
            if message == CALLBACK:
                event = lparam & 0xFFFF
                if self._version4:
                    if event in (NIN_SELECT, NIN_KEYSELECT):
                        self._select(keyboard=event == NIN_KEYSELECT)
                    elif event == WM_LBUTTONDBLCLK:
                        self._double_click()
                    elif event == WM_CONTEXTMENU:
                        self._hide_popup()
                        self._menu()
                else:
                    if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        self._hide_popup()
                        self._menu()
                    elif event == WM_LBUTTONUP:
                        self._select()
                    elif event == WM_LBUTTONDBLCLK:
                        self._double_click()
                return 0
            if message == WM_TIMER:
                if wparam == TIMER_FRAME:
                    self._animate()
                else:
                    self._refresh()
                return 0
            if message == WM_TRAY_FRAMES:
                self._frames_built()
                return 0
            if message == WM_WTSSESSION_CHANGE:
                self._session_changed(wparam)
                return 0
            if self._taskbar_created and message == self._taskbar_created:
                self._hide_popup()
                self._notify(NIM_ADD)
                self._set_version()
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.KillTimer(hwnd, TIMER_TICK)
                user32.KillTimer(hwnd, TIMER_FRAME)
                self._motion_ms = None
                if self._session_watch:
                    try:
                        wts = _dll("wtsapi32")
                        wts.WTSUnRegisterSessionNotification.argtypes = [W.HWND]
                        wts.WTSUnRegisterSessionNotification(hwnd)
                    except Exception:
                        pass
                    self._session_watch = False
                self._drop_cards()
                popup, self._popup = self._popup, None
                if popup is not None:
                    try:
                        popup.destroy()
                    except Exception as exc:
                        self.log("tray popup cleanup failed (%s)" % type(exc).__name__)
                data = NOTIFYICONDATAW()
                data.cbSize = C.sizeof(NOTIFYICONDATAW)
                data.hWnd = hwnd
                data.uID = 1
                _dll("shell32").Shell_NotifyIconW(NIM_DELETE, C.byref(data))
                if self._frame_icon:
                    user32.DestroyIcon(self._frame_icon)
                    self._frame_icon = self._frame_key = None
                if self._icon and self._icon_owned:
                    user32.DestroyIcon(self._icon)
                self._icon = self._shown_icon = None
                user32.PostQuitMessage(0)
                return 0
        except Exception as exc:
            self.log("tray message failed (%s)" % type(exc).__name__)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)
