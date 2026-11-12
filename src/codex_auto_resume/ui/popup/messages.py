"""The window's messages: everything Windows says to the popup, and what each one decides.

Moved out of window.py (v0.6.10) by line range, as a mixin the window is made of - so no call site
changed and the window keeps the life of one popup to itself; in v0.6.23 the calls it makes too (`work`: each runs on a
thread of its own and comes back as WM_POPUP_RESULT), to give the window room for its opening. Each handler reads and changes the
window's own state and calls the window's own methods; nothing here keeps state of its own.
"""
from __future__ import annotations

import ctypes as C
import threading
import time
from ... import brand
from .model import perform
from .motion import face_amount, face_length, face_state, mixed, opening
from .placement import focus_order, hit_test, next_focus
from . import access
from .hidden import PopupHidden
from .win32 import (GWL_EXSTYLE,
                    KEY_WAS_DOWN,
                    LWA_ALPHA,
                    SWP_NOACTIVATE,
                    SWP_NOSIZE,
                    SWP_NOZORDER,
                    WS_EX_LAYERED,
                    _PerMonitorDpi,
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
                    WM_CONTEXTMENU,
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


class PopupMessages(PopupHidden):
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
                if self._opening is not None:
                    self._opening_step()
                self._sync_frames()
                user32.InvalidateRect(hwnd, None, False)
            elif wparam == TIMER_TICK:
                self._ticks += 1
                self._still = self._ask_still()      # battery saver or a lock, within a second of it (_sync_frames)
                if self._ticks % REFRESH_TICKS == 0:
                    self._request_read()
                self._update()
            elif wparam == TIMER_FIRST and self._pending_show is not None:
                self._present(*self._pending_show)
            return 0
        if message == WM_POPUP_RESULT:
            self._finished(wparam)
            return 0
        if message == access.WM_GETOBJECT:
            # v0.6.11: a screen reader asking what is in the window (access.py); anything else it asks,
            # Windows answers for the window itself.
            return access.answer(self, wparam, lparam)
        if message == WM_POPUP_STRINGS:
            if self.visible:
                self._update()
            return 0
        if message == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                if self.visible and not self._menu_has(lparam):
                    self.hide()                  # a click anywhere else closes it; its own row menu does not
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
            self.title_pressed(lparam, time.monotonic() * 1000.0)
            self._invalidate()
            return 0
        if message == WM_LBUTTONUP:
            target, pressed = self._hit(lparam), self.pressed
            self.pressed = None
            if target is not None and target == pressed:
                self._activate(target)
            self._invalidate()
            return 0
        if message == WM_CONTEXTMENU:
            self._context_menu(lparam)
            return 0
        if message == WM_DPICHANGED:
            dpi = wparam & 0xFFFF
            if dpi and dpi != self.dpi:
                self.dpi = dpi
                self._fit = None
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
            self._speak()
            return 0
        if key in (VK_SPACE, VK_RETURN) and self.focus is not None:
            self._activate(self.focus)
            return 0
        return None

    # ------------------------------------------------------------------- the opening (v0.6.23)
    def _start_opening(self):
        """The popup fades in and rises into place from SPACING xs below it (motion.opening), as the window's menu
        does: a layered window for as long as that takes, an ordinary one again on arrival. Simply there while held."""
        self._end_opening()
        if self._holds() or not self.hwnd or self._home is None:
            return
        user32 = _dll("user32")
        try:
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) | WS_EX_LAYERED)
            self._layered = True
            if not user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, LWA_ALPHA):
                raise OSError("SetLayeredWindowAttributes")
        except Exception as exc:                  # then it is simply there, as before
            self.log("tray popup opening motion unavailable (%s)" % type(exc).__name__)
            self._end_opening()
            return
        rise = max(1, int(round(brand.SPACING["xs"] * self.dpi / 96.0)))
        self._opening = (None, rise)             # its clock starts at its first frame, once the first picture is up
        self._stand(rise)

    def _opening_step(self):
        """A frame of the opening: how opaque, and how far below its place; at the end, whole and in place."""
        started, rise = self._opening
        if started is None:
            started = time.monotonic() * 1000.0
            self._opening = (started, rise)
        alpha, below, done = opening(time.monotonic() * 1000.0 - started, rise)
        if done:
            self._end_opening()
            return
        _dll("user32").SetLayeredWindowAttributes(self.hwnd, 0, alpha, LWA_ALPHA)
        self._stand(below)

    def _end_opening(self):
        """Nothing left of an opening: in its place, and no longer layered - drawn again at once, so no frame is empty."""
        self._opening = None
        if self._below:
            self._stand(0)
        if self._layered and self.hwnd:
            user32 = _dll("user32")
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE) & ~WS_EX_LAYERED)
            user32.InvalidateRect(self.hwnd, None, False)
            user32.UpdateWindow(self.hwnd)
        self._layered = False

    def _stand(self, below):
        """Where it opens to, `below` px lower: moved, never sized."""
        self._below = below
        if self._home is not None and self.hwnd:
            with _PerMonitorDpi():
                _dll("user32").SetWindowPos(self.hwnd, None, self._home[0], self._home[1] + below, 0, 0,
                                            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    # ------------------------------------------------------------------- a button's face (v0.6.23)
    def _face_glides(self):
        """{target: ((fill, edge) it left from, how far on)} for the buttons part way to a new face (renderer.draw's
        `faces`): one starts for each button whose state changed since the last frame, from what it showed, in the time
        motion.face_length gives, and a finished one is let go. Nothing glides while held, hidden or on its first frame."""
        now, faces = time.monotonic() * 1000.0, self._faces if self._faces is not None else {}
        states = {item["target"]: (item, face_state(item, self.hover, self.pressed))
                  for item in self._plan["items"] if item["kind"] == "button"}
        before = (self._face_states or {}) if self.visible else {}
        self._face_states = {target: state for target, (_, state) in states.items()} if self.visible else None
        shown, started = {}, False
        for target, (item, state) in states.items():
            face, was = faces.get(target), before.get(target, state)
            if was != state:
                face = None if self._holds() else (now, self._showing(item, was, face, now), face_length(was, state))
                started = started or face is not None
            amount, done = face_amount(face, now) if face is not None else (1.0, True)
            if done:
                faces.pop(target, None)
            else:
                faces[target], shown[target] = face, (face[1], amount)
        for gone in set(faces) - set(states):
            del faces[gone]
        self._faces = faces
        if started:
            self._sync_frames()
        return shown

    def _showing(self, item, state, face, now):
        """The (fill, edge) a button shows this instant: its `state`'s colours, or part way to them from where `face` left."""
        colours = self._renderer.face_colours(item, state)
        if face is None:
            return colours
        amount = face_amount(face, now)[0]
        return tuple(mixed(one, other, amount) for one, other in zip(face[1], colours))

    # ---------------------------------------------------------------------- work
    def _request_read(self):
        if self.control is None:
            return
        if self._reading:
            self._read_again = True
            return
        self._reading = True
        self._run(("read",))

    def _run(self, action):
        number = next(self._sequence)
        control, source, dashboard = self.control, self.source, self.on_dashboard

        def work():
            outcome = perform(action, control, source=source, dashboard=dashboard)
            with self._lock:
                self._results[number] = (action, outcome)
            hwnd = self.hwnd
            if hwnd:
                _dll("user32").PostMessageW(hwnd, WM_POPUP_RESULT, number, 0)

        threading.Thread(target=work, name="tray-popup-call", daemon=True).start()

    def _finished(self, number):
        with self._lock:
            action, outcome = self._results.pop(number, (None, None))
        if action is None:
            return
        if outcome[0] == "failed":
            self.log("tray popup %s failed (%s)" % (action[0], outcome[1]))
        self.model.apply_outcome(action, outcome, time.time())
        if action[0] == "read" and outcome[0] == "ok":
            # get_status carries the stored settings; nothing more is asked of the control layer.
            self.follow_settings((outcome[1].get("status") or {}).get("settings"))
        showing = self.visible or self._pending_show is not None
        if action[0] == "read":
            self._reading = False
            if self._read_again:
                self._read_again = False
                self.model.wants_read = True
        if self.model.wants_read:
            self.model.wants_read = False
            # A hidden window reads nothing; the next opening reads anyway.
            if showing:
                self._request_read()
        if self._pending_show is not None and action[0] == "read":
            self._present(*self._pending_show)
        elif self.visible:
            self._update()
