"""The real popup's frames held and let go, on the C# host (S6.4d5, P6-DESIGN 3.4 "window").

Twin of tests/test_popup_motion_held.py's WindowTests: the original's body through `super()`, the popup the host's
PopupWindow with its own real windows (tests/rustdiff/hostcardwindow.py, HostProbe.cs `popup_live`), far off every screen,
never activated, destroyed by the original's own `finally`, through gui_lock.sh (the main session's word of 2026-11-28).
What changed, and only that:

* `tray_popup.Popup` is a HostCardPopup for the test's body: made from its control layer, strings and `held`; its
  `create` is the host's (made already), its model the reference's, whose read outcome is sent as the core's snapshot;
* the test's own SendMessageW to the window (a tick, from outside) is made for real, the host's popup asked first with
  the test's `held` and clock of that moment (the host cannot call back into the test) and read again after it;
* `pump` runs the host's messages for the same time.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "tests"), str(ROOT / "tests" / "rustdiff")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import surfacehost  # noqa: E402

if os.name == "nt":
    import hostcardwindow  # noqa: E402
    import test_popup_motion_held as original  # noqa: E402  (a module name: its classes are not collected here)
    BASE = original.WindowTests
else:
    BASE = unittest.TestCase

ON_HOST = unittest.skipUnless(os.name == "nt" and surfacehost.CSC.is_file(), "the host's surfaces need the in-box C# compiler")


class _HostPopupClass:
    """tray_popup.Popup as the test's body makes one: a HostCardPopup, its `create` a no-op (the host made its windows)."""

    def __init__(self, made):
        self.made = made

    def __call__(self, control=None, strings=None, held=None, **extra):
        window = hostcardwindow.HostCardPopup(control=None, strings=strings, held=held, log=extra.get("log"))
        window.control = control
        window.create = lambda: None
        self.made.append(window)
        return window

    def __getattr__(self, name):
        return getattr(original.tray_popup.Popup, name)


@ON_HOST
class WindowOnHostTests(BASE):  # noqa: F821 (BASE is deleted below, so the original is not collected twice)
    def setUp(self):
        super().setUp()
        self.made = []
        real = ctypes.WinDLL

        def windll(name, *args, **kwargs):
            library = real(name, *args, **kwargs)
            if name.lower() != "user32":
                return library
            made = self.made
            send = library.SendMessageW

            def SendMessageW(hwnd, message, wparam, lparam):
                for window in made:
                    if window.hwnd == hwnd:
                        window.sync()
                send.argtypes = SendMessageW.argtypes
                answer = send(hwnd, message, wparam, lparam)
                for window in made:
                    if window.hwnd == hwnd:
                        window.sync()
                return answer
            SendMessageW.argtypes = None
            return types.SimpleNamespace(SendMessageW=SendMessageW)
        for target, name, value in ((original.tray_popup, "Popup", _HostPopupClass(self.made)),
                                    (original, "ctypes", types.SimpleNamespace(WinDLL=windll, c_void_p=ctypes.c_void_p,
                                                                               c_uint=ctypes.c_uint, c_size_t=ctypes.c_size_t,
                                                                               c_ssize_t=ctypes.c_ssize_t))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pump(self, seconds):
        for window in self.made:
            window.pump(seconds)


del BASE


if __name__ == "__main__":
    unittest.main()
