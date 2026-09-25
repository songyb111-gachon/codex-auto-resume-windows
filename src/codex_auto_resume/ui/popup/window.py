"""The window itself: its class, its messages, and the life of one popup.

Everything Windows says arrives here and leaves as a decision made in the modules beside this
one. This is the only part of the popup that could be called stateful.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
import itertools
import os
import threading
import time
from ... import brand
from ...win.dll import WNDCLASSW, WNDPROC
from .layout import WIDTH
from .model import PopupModel, perform, select_action
from .motion import MotionGates, animates, glide_amount, halo, next_glides
from .placement import focus_order, hit_test, next_focus, place
from .renderer import Renderer
from . import theme as look                # the three questions below are asked through it
from .theme import adopt_settings, appearance, design_setting, effective_theme, theme_setting
from .win32 import (CS_DROPSHADOW,
                    DWMWA_USE_IMMERSIVE_DARK_MODE,
                    DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1,
                    DWMWA_WINDOW_CORNER_PREFERENCE,
                    DWMWCP_ROUND,
                    HWND_TOPMOST,
                    IDC_ARROW,
                    KEY_WAS_DOWN,
                    MONITORINFO,
                    MONITOR_DEFAULTTONEAREST,
                    PAINTSTRUCT,
                    SWP_NOACTIVATE,
                    SW_HIDE,
                    SW_SHOW,
                    SW_SHOWNOACTIVATE,
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
                    WS_EX_TOOLWINDOW,
                    WS_EX_TOPMOST,
                    WS_POPUP,
                    _PerMonitorDpi,
                    _declare,
                    _dll,
                    _signature)
from .words import locale_of, say, vocabulary


REFRESH_TICKS = 3            # re-read the list every third one-second tick while visible


FRAME_MS = 33                # about thirty frames a second, and only while something moves


FIRST_READ_WAIT_MS = 300     # the first opening waits this long for real numbers at most


# ------------------------------------------------------------------------------ the window
class Popup(MotionGates):
    """The window itself. Created, shown, hidden and destroyed on the icon's thread only;
    `set_strings` is the one method another thread may call."""

    def __init__(self, *, control=None, source=None, strings=None, on_dashboard=None, log=None,
                 anchor=None):
        self.model = PopupModel(strings)
        self.locale = locale_of(strings)
        self.control = control
        self.source = source
        self.on_dashboard = on_dashboard
        self.log = log or (lambda *unused: None)
        self.anchor = anchor
        self.hwnd = None
        self.visible = False
        self._proc = None
        self._class = None
        self._renderer = None
        self._rounded = False
        self._pending_show = None
        self.hidden_at = None
        self._double_click_at = None
        self._key_at = None
        self._painted_plan = None
        self.hover = self.pressed = self.focus = None
        self.keyboard = False
        self.dpi = 96
        self._vm = None
        self._plan = None
        self._screen = None
        self._lock = threading.Lock()
        self._results = {}
        self._sequence = itertools.count(1)
        self._reading = False
        self._read_again = False
        self._ticks = 0
        self._frame_running = False
        self._state = None
        self._state_since = time.monotonic()
        self._reduced = False            # a stopper: Reduce motion, Windows' animation setting, High Contrast
        self._contrast = False
        self._apps_light = None          # Windows' app mode when last asked: True, False or None
        self._theme = "light"            # the theme in effect: the setting, resolved against that mode
        self._framed_dark = None         # what DWM was last told about the window's frame
        self._tracking = False
        self._strings = None
        self._static_dirty = True        # anything but the halo changed since the last frame
        self._origin = None
        self._switches = None            # {target: checked} as last laid out while on screen
        self._glides = {}                # {target: (started_ms, from, to)}: switches on the move

    # ------------------------------------------------------------------ lifecycle
    def create(self):
        _declare()
        user32, kernel32 = _dll("user32"), _dll("kernel32")
        instance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.style = CS_DROPSHADOW
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.hCursor = user32.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        self._class = "CodexAutoResumePopup-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self._class
        if not user32.RegisterClassW(C.byref(klass)):
            self._class = None
            raise OSError("RegisterClassW")
        try:
            with _PerMonitorDpi():
                self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, self._class,
                                                   say(self.model.strings, "tray.title"), WS_POPUP,
                                                   0, 0, WIDTH, 120, None, None, instance, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW")
            self._renderer = Renderer()
            self._round_corners()
            getter = getattr(user32, "GetDpiForWindow", None)
            self.dpi = (getter(self.hwnd) if getter is not None else 0) or 96
        except Exception:
            self.destroy()
            raise

    def destroy(self):
        user32 = _dll("user32")
        hwnd, self.hwnd = self.hwnd, None
        self.visible = False
        if hwnd:
            for timer in (TIMER_TICK, TIMER_FRAME, TIMER_FIRST):
                user32.KillTimer(hwnd, timer)
            user32.DestroyWindow(hwnd)
        self._frame_running = False
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._plan = self._vm = None
        self._static_dirty = True
        self._framed_dark = None
        self._switches, self._glides = None, {}
        if self._class:
            user32.UnregisterClassW(self._class, _dll("kernel32").GetModuleHandleW(None))
            self._class = None

    def set_strings(self, strings):
        """Adopt a new vocabulary. Safe from any thread: applied on the next frame."""
        with self._lock:
            self._strings = dict(strings or {})
        hwnd = self.hwnd
        if hwnd:
            _dll("user32").PostMessageW(hwnd, WM_POPUP_STRINGS, 0, 0)

    def attention(self) -> bool:
        return self.model.attention()

    # ---------------------------------------------------------------- the icon asks
    def on_select(self, keyboard=False):
        now = time.monotonic()
        choice = select_action(self.visible or self._pending_show is not None, now,
                               hidden_at=self.hidden_at, double_click_at=self._double_click_at,
                               previous_key_at=self._key_at, keyboard=keyboard)
        if keyboard:
            self._key_at = now
        if choice == "show":
            self.show(keyboard=keyboard)
        elif choice == "hide":
            self.hide()

    def on_double_click(self):
        self._double_click_at = time.monotonic()
        if not self.visible and self._pending_show is None:
            self.show()

    def show(self, keyboard=False, activate=True, origin=None):
        if self.hwnd is None:
            self.create()
        self.keyboard = keyboard
        self.hover = self.pressed = None
        self.focus = None
        self._read_look()
        self._request_read()
        if self.model.rows is None and self.model.status is None and self.control is not None:
            self._pending_show = (activate, origin)
            _dll("user32").SetTimer(self.hwnd, TIMER_FIRST, FIRST_READ_WAIT_MS, None)
            return
        self._present(activate, origin)

    def hide(self):
        self._pending_show = None
        hwnd = self.hwnd
        if not hwnd:
            return
        user32 = _dll("user32")
        for timer in (TIMER_TICK, TIMER_FRAME, TIMER_FIRST):
            user32.KillTimer(hwnd, timer)
        self._frame_running = False
        if self.visible:
            self.visible = False
            user32.ShowWindow(hwnd, SW_HIDE)
            self.hidden_at = time.monotonic()
        self.hover = self.pressed = self.focus = None
        self._painted_plan = None
        # A change made while it is closed is simply there when it opens again.
        self._switches, self._glides = None, {}

    # ------------------------------------------------------------------- appearance
    def _read_look(self):
        """Ask Windows again how to draw: High Contrast, its app mode and its motion setting - on every
        opening and whenever Windows says a setting changed, never per frame. High Contrast moves nothing
        either, and outranks the theme and the design (the product's own, adopted with the theme).

        These three are the only questions this window asks Windows about how to look, and they
        go through `look` rather than by name: a test that draws without a screen replaces them,
        and through the module there is one place to do it whichever file is asking.
        """
        self._contrast = look.high_contrast()
        self._apps_light = look.apps_use_light_theme()
        self._reduced = look.reduced_motion() or self._contrast
        self._theme = effective_theme(theme_setting(), self._apps_light)
        self._design = design_setting()

    def _follow_theme(self):
        """The theme (the setting, the app mode last read) and the stored design; a change redraws it all."""
        theme, design = effective_theme(theme_setting(), self._apps_light), design_setting()
        if (theme, design) != (self._theme, self._design):
            self._theme, self._design = theme, design
            self._static_dirty = True

    def _frame_theme(self):
        """Tell DWM whether the window is dark, so the hairline Windows 11 draws round it matches."""
        dark = appearance(self._theme, contrast=self._contrast) == "dark"
        if not self.hwnd or dark == self._framed_dark:
            return
        self._framed_dark = dark
        try:
            value = C.c_int(1 if dark else 0)
            dwm = _dll("dwmapi")
            _signature(dwm.DwmSetWindowAttribute, C.c_long, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD)
            for attribute in (DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1):
                if dwm.DwmSetWindowAttribute(self.hwnd, attribute, C.byref(value), C.sizeof(value)) == 0:
                    break
        except Exception:
            pass                                   # a frame that stays light is not worth a failure

    def follow_settings(self, values):
        """Take up what a read of the stored settings says: the language, the theme, the design, Reduce motion.

        The icon hands over the same things before each opening; this is for a change made while
        the popup is open, which then shows within one read.
        """
        if not isinstance(values, dict):
            return
        adopt_settings(values)
        strings = vocabulary(values.get("interface_language"))
        with self._lock:
            if strings != (self._strings if self._strings is not None else self.model.strings):
                self._strings = strings                    # applied by the next rebuild, as set_strings is
        self._reduced = look.reduced_motion() or self._contrast

    # ------------------------------------------------------------------- presenting
    def _round_corners(self):
        try:
            value = C.c_int(DWMWCP_ROUND)
            dwm = _dll("dwmapi")
            _signature(dwm.DwmSetWindowAttribute, C.c_long, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD)
            self._rounded = dwm.DwmSetWindowAttribute(self.hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                                      C.byref(value), C.sizeof(value)) == 0
        except Exception:
            self._rounded = False

    def _shape(self, width, height):
        if self._rounded:
            return
        radius = int(round(8 * self.dpi / 96.0)) * 2
        region = _dll("gdi32").CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        if region and not _dll("user32").SetWindowRgn(self.hwnd, region, True):
            _dll("gdi32").DeleteObject(region)            # only a region the system took is its own

    def _screen_now(self):
        user32 = _dll("user32")
        with _PerMonitorDpi():
            icon = self.anchor() if self.anchor else None
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            cursor = (point.x, point.y)
            probe = W.RECT(*(icon or (cursor[0], cursor[1], cursor[0] + 1, cursor[1] + 1)))
            monitor = user32.MonitorFromRect(C.byref(probe), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = C.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, C.byref(info))
            dpi = 0
            try:
                shcore = _dll("shcore")
                x, y = W.UINT(0), W.UINT(0)
                if shcore.GetDpiForMonitor(C.c_void_p(monitor), 0, C.byref(x), C.byref(y)) == 0:
                    dpi = x.value
            except Exception:
                dpi = 0
        work, whole = info.rcWork, info.rcMonitor
        return {"icon": icon, "cursor": cursor, "dpi": dpi or self.dpi or 96,
                "work": (work.left, work.top, work.right, work.bottom),
                "monitor": (whole.left, whole.top, whole.right, whole.bottom)}

    def _present(self, activate=True, origin=None):
        user32 = _dll("user32")
        self._pending_show = None
        user32.KillTimer(self.hwnd, TIMER_FIRST)
        self._screen = self._screen_now()
        self.dpi = self._screen["dpi"]
        plan = self._rebuild(time.time())
        if self.keyboard and self.focus is None:
            order = focus_order(plan["targets"])
            self.focus = order[0] if order else None
        self._move(plan, origin)
        self._frame_theme()
        self.visible = True
        user32.InvalidateRect(self.hwnd, None, False)
        user32.ShowWindow(self.hwnd, SW_SHOW if activate else SW_SHOWNOACTIVATE)
        if activate:
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.hwnd)
        user32.SetTimer(self.hwnd, TIMER_TICK, 1000, None)
        self._sync_frames()
        user32.UpdateWindow(self.hwnd)

    def _move(self, plan, origin=None):
        width, height = plan["size"]
        screen = self._screen
        if origin is not None:
            x, y = origin
        else:
            gap = int(round(brand.SPACING["m"] * self.dpi / 96.0))
            x, y, _ = place((width, height), screen["work"], screen["monitor"], screen["icon"],
                            screen["cursor"], gap=gap)
        self._origin = origin
        with _PerMonitorDpi():
            _dll("user32").SetWindowPos(self.hwnd, C.c_void_p(HWND_TOPMOST), x, y, width, height, SWP_NOACTIVATE)
        self._shape(width, height)

    def _rebuild(self, now):
        with self._lock:
            strings, self._strings = self._strings, None
        if strings is not None:
            self.model.strings = strings
            self.locale = locale_of(strings)
        self._follow_theme()
        vm = self.model.view(now)
        # The light's cycle starts with the light, not the word: "attention" is a grey dot that does not
        # move for a watcher not known to be running and an amber one that breathes for one that is.
        if vm["light"] != self._state:
            self._state = vm["light"]
            self._state_since = time.monotonic()
        plan = self._renderer.layout(vm, self.dpi / 96.0, self.locale)
        self._vm, self._plan = vm, plan
        self._static_dirty = True
        self._follow_switches(plan)
        return plan

    def _follow_switches(self, plan):
        """Start a glide for each switch now drawn the other way from the last layout on screen."""
        seen = {item["target"]: bool(item["checked"]) for item in plan["items"] if item["kind"] == "switch"}
        previous = self._switches if self.visible else None
        self._glides = next_glides(seen, previous, self._glides, time.monotonic() * 1000.0,
                                   animate=self.visible and not self._controls_still)
        self._switches = seen if self.visible else None

    def _glide_amounts(self):
        """{target: how far on} for the switches still gliding; finished glides are let go."""
        now = time.monotonic() * 1000.0
        amounts = {}
        for target, glide in list(self._glides.items()):
            amount, done = glide_amount(glide, now)
            if done:
                del self._glides[target]
            else:
                amounts[target] = amount
        return amounts

    def _update(self, now=None):
        if self.hwnd is None or self._renderer is None:
            return
        previous = self._plan["size"] if self._plan else None
        plan = self._rebuild(time.time() if now is None else now)
        if self.visible and plan["size"] != previous and self._screen is not None:
            self._move(plan, getattr(self, "_origin", None))
        order = focus_order(plan["targets"])
        if self.focus is not None and self.focus not in order:
            self.focus = order[0] if order and self.keyboard else None
        if self.visible:
            self._frame_theme()
        self._sync_frames()
        _dll("user32").InvalidateRect(self.hwnd, None, False)

    def _since_state_ms(self):
        return (time.monotonic() - self._state_since) * 1000.0

    def _sync_frames(self):
        user32 = _dll("user32")
        wanted = (self.visible and self._vm is not None
                  and (bool(self._glides)
                       or animates(self._vm["light"], self._since_state_ms(), reduced=self._light_still,
                                   design=self._design)))
        if wanted and not self._frame_running:
            user32.SetTimer(self.hwnd, TIMER_FRAME, FRAME_MS, None)
            self._frame_running = True
        elif not wanted and self._frame_running:
            user32.KillTimer(self.hwnd, TIMER_FRAME)
            self._frame_running = False

    def frame(self):
        """The halo for this instant, its cycle starting with its state, as the window's does."""
        if self._vm is None:
            return None
        since = self._since_state_ms()
        return halo(self._vm["light"], since, since, reduced=self._light_still, design=self._design)

    def render(self):
        """Draw the current view into the canvas and return it (the tests read it back)."""
        if self._plan is None:
            self._rebuild(time.time())
        look = (self._theme, self._design, self._contrast)
        if (self._renderer.theme, self._renderer.design, self._renderer.contrast) != look:
            # The halo band saved with the last whole frame is in the old colours.
            self._renderer.theme, self._renderer.design, self._renderer.contrast = look
            self._static_dirty = True
        if self._glides:
            # A switch on the move is drawn over the ground every frame, and the frame after its
            # glide ends draws it back into the ground where it has come to rest.
            self._static_dirty = True
        if self._static_dirty or self._renderer.halo_plan is not self._plan:
            self._static_dirty = False
            return self._renderer.draw(self._vm, self._plan, frame=self.frame(), hover=self.hover,
                                       pressed=self.pressed, focus=self.focus if self.keyboard else None,
                                       glides=self._glide_amounts())
        return self._renderer.draw_halo(self._plan, self.frame())

    def _invalidate(self):
        """Something other than the halo changed: the next frame is drawn whole."""
        self._static_dirty = True
        if self.hwnd:
            _dll("user32").InvalidateRect(self.hwnd, None, False)

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

    def _activate(self, target):
        action = self.model.action_for(target)
        if action is None:
            return
        if action[0] == "dashboard":
            self.hide()
            self._run(action)
            return
        if not self.model.begin(action):
            return
        self._run(action)
        self._update()

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
