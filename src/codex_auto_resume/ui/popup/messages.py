"""The window's messages: everything Windows says to the popup, and what each one decides.

Moved out of window.py (v0.6.10) by line range, as a mixin the window is made of - so no call site
changed and the window keeps the life of one popup to itself. Each handler reads and changes the
window's own state and calls the window's own methods; nothing here keeps state of its own.
"""
from __future__ import annotations

import ctypes as C
import time
from .placement import focus_order, hit_test, next_focus
from .win32 import (KEY_WAS_DOWN,
                    PAINTSTRUCT,
                    TIMER_FIRST,
                    TIMER_FRAME,
                    TIMER_TICK,
                    TME_LEAVE,
                    TRACKMOUSEEVENT,
                    VK_DOWN,
                    VK_ESCAPE,
                    VK_RETURN,
                    VK_SHIFT,
                    VK_SPACE,
                    VK_TAB,
                    VK_UP,
                    WA_INACTIVE,
                    WM_ACTIVATE,
                    WM_CLOSE,
                    WM_DPICHANGED,
                    WM_ERASEBKGND,
                    WM_KEYDOWN,
                    WM_LBUTTONDOWN,
                    WM_LBUTTONUP,
                    WM_MOUSELEAVE,
                    WM_MOUSEMOVE,
                    WM_PAINT,
                    WM_POPUP_RESULT,
                    WM_POPUP_STRINGS,
                    WM_SETTINGCHANGE,
                    WM_SYSCOLORCHANGE,
                    WM_TIMER,
                    _dll)


REFRESH_TICKS = 3            # re-read the list every third one-second tick while visible


class PopupMessages:
    """The popup's window procedure and its handlers, for `Popup` (window.py) to be made of."""

    # --------------------------------------------------------------------- messages
    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            handled = self._handle(hwnd, message, wparam, lparam)
            if handled is not None:
                return handled
        except Exception as exc:              # the popup must never take the watcher down
            self.log("tray popup message failed (%s)" % type(exc).__name__)
        return _dll("user32").DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        if message == WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == WM_ERASEBKGND:
            return 1
        if message == WM_TIMER:
            if wparam == TIMER_FRAME:
                # A glide redraws the frame whole (render() sees it); the halo alone is a band.
                self._sync_frames()
                user32.InvalidateRect(hwnd, None, False)
            elif wparam == TIMER_TICK:
                self._ticks += 1
                if self._ticks % REFRESH_TICKS == 0:
                    self._request_read()
                self._update()
            elif wparam == TIMER_FIRST and self._pending_show is not None:
                self._present(*self._pending_show)
            return 0
        if message == WM_POPUP_RESULT:
            self._finished(wparam)
            return 0
        if message == WM_POPUP_STRINGS:
            if self.visible:
                self._update()
            return 0
        if message == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                if self.visible:
                    self.hide()                  # a click anywhere else closes it
                return 0
            return None                          # activated: let Windows give it the keyboard
        if message == WM_CLOSE:
            self.hide()
            return 0
        if message == WM_KEYDOWN:
            return self._key(wparam, lparam)
        if message == WM_MOUSEMOVE:
            self._mouse_move(hwnd, lparam)
            return 0
        if message == WM_MOUSELEAVE:
            self._tracking = False
            if self.hover is not None:
                self.hover = None
                self._invalidate()
            return 0
        if message == WM_LBUTTONDOWN:
            self.keyboard = False
            self.pressed = self._hit(lparam)
            self._invalidate()
            return 0
        if message == WM_LBUTTONUP:
            target, pressed = self._hit(lparam), self.pressed
            self.pressed = None
            if target is not None and target == pressed:
                self._activate(target)
            self._invalidate()
            return 0
        if message == WM_DPICHANGED:
            dpi = wparam & 0xFFFF
            if dpi and dpi != self.dpi:
                self.dpi = dpi
                if self.visible:
                    # The scale changed under an open window: measure the screen again and
                    # put it back beside the icon at its new size, not where Windows guessed.
                    self._screen = self._screen_now()
                    self._screen["dpi"] = dpi
                    self._move(self._rebuild(time.time()), self._origin)
                    self._invalidate()
            return 0
        if message in (WM_SETTINGCHANGE, WM_SYSCOLORCHANGE):
            # High Contrast, Windows' app mode ("ImmersiveColorSet") or its motion setting may have
            # changed. The registry is read again whatever the setting's name, which is cheap and
            # rare; an open window is repainted at once when what it draws with changed.
            before = (self._contrast, self._theme, self._design)
            self._read_look()
            if (self._contrast, self._theme, self._design) != before or message == WM_SYSCOLORCHANGE:
                self._invalidate()
            if self.visible:
                self._frame_theme()
            self._sync_frames()
            return None
        return None

    def _paint(self, hwnd):
        user32 = _dll("user32")
        paint = PAINTSTRUCT()
        dc = user32.BeginPaint(hwnd, C.byref(paint))
        try:
            if dc and self._renderer is not None and (self._plan is not None or self.visible):
                canvas = self.render()
                _dll("gdi32").SetDIBitsToDevice(dc, 0, 0, canvas.width, canvas.height, 0, 0, 0,
                                                canvas.height, canvas.bits, C.byref(canvas.info), 0)
                self._painted_plan = self._plan
        finally:
            user32.EndPaint(hwnd, C.byref(paint))

    def _hit(self, lparam):
        # Against the layout on screen. A read or a tick replaces `_plan` before Windows
        # gets round to painting it, and a click queued in between was aimed at the rows
        # the person could see, not at where they are about to move.
        plan = self._painted_plan
        if plan is None:
            return None
        x = C.c_short(lparam & 0xFFFF).value
        y = C.c_short((lparam >> 16) & 0xFFFF).value
        return hit_test(plan["targets"], x, y)

    def _mouse_move(self, hwnd, lparam):
        user32 = _dll("user32")
        target = self._hit(lparam)
        if target != self.hover:
            self.hover = target
            self._invalidate()
        if not self._tracking:
            track = TRACKMOUSEEVENT()
            track.cbSize = C.sizeof(TRACKMOUSEEVENT)
            track.dwFlags = TME_LEAVE
            track.hwndTrack = hwnd
            self._tracking = bool(user32.TrackMouseEvent(C.byref(track)))

    def _key(self, key, lparam=0):
        user32 = _dll("user32")
        if key in (VK_SPACE, VK_RETURN) and lparam & KEY_WAS_DOWN:
            # Auto-repeat. A held key is one press: repeating it would flip a switch back
            # and forth as each answer came in, and where it stopped would be chance.
            return 0
        if key == VK_ESCAPE:
            self.hide()
            return 0
        if key in (VK_TAB, VK_UP, VK_DOWN) and self._plan is not None:
            backwards = key == VK_UP or (key == VK_TAB and user32.GetKeyState(VK_SHIFT) < 0)
            self.keyboard = True
            self.focus = next_focus(focus_order(self._plan["targets"]), self.focus, backwards)
            self._invalidate()
            return 0
        if key in (VK_SPACE, VK_RETURN) and self.focus is not None:
            self._activate(self.focus)
            return 0
        return None
