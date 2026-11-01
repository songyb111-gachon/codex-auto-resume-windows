"""The icon's right-click menu, drawn (v0.6.20): its window, its picture, its keys and what a screen reader hears.

menuplan.py says where everything goes; this puts it on the screen. The menu lives on the icon's thread inside the
watcher, as the popup does, and is one layered window - an alpha for every pixel (UpdateLayeredWindow) - so the card
is opaque, its lift falls translucent over whatever is behind it, and past the shadow the window is not there at all:
a click on nothing goes through. It is drawn by the popup's own renderer, in the popup's palette, fonts, radii, depth
and lights, at the scale of the monitor it opens on, and in High Contrast in the system's colours with no shadow, the
item in hand in Highlight as Windows draws a menu's.

It behaves as Windows' menu did. It opens at the pointer, the card's corner there, turned to fit and kept inside the
work area; it takes the keyboard, and closes on Esc, Alt or F10, a click anywhere else, or anything that takes the
focus from it. Up and Down move the item in hand round the usable items, Home and End go to the first and last, Enter
chooses, a letter chooses the one item it starts or steps through several; the pointer puts an item in hand and a
release of either button on it chooses it. A screen reader is told it is a menu and each item's name, role and state,
and hears the item in hand move. Choosing hands the item's id to the icon (`on_choose`) after the menu has closed, which
is all it can do: nothing here acts, starts a process, or has any way to reach a conversation.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
import os
import threading

from ... import brand, l10n
from ...win import textsize
from ...win.dll import WNDCLASSW, WNDPROC
from . import access
from . import theme as look                # the questions below are asked through it, as the popup asks them
from .gdiplus import PIXEL_FORMAT_32BPP_PARGB, _Painter
from .menuplan import (menu_accessible_items,
                       menu_end,
                       menu_layout,
                       menu_letter,
                       menu_mirror,
                       menu_place,
                       menu_step)
from .placement import hit_test
from .renderer import Renderer
from .theme import design_setting, effective_theme, theme_setting
from .win32 import (DT_END_ELLIPSIS,
                    DT_NOPREFIX,
                    DT_RIGHT,
                    DT_RTLREADING,
                    DT_SINGLELINE,
                    DT_VCENTER,
                    HWND_TOPMOST,
                    IDC_ARROW,
                    MONITORINFO,
                    MONITOR_DEFAULTTONEAREST,
                    SWP_NOACTIVATE,
                    SW_HIDE,
                    SW_SHOW,
                    TME_LEAVE,
                    TRACKMOUSEEVENT,
                    VK_DOWN,
                    VK_ESCAPE,
                    VK_RETURN,
                    VK_UP,
                    WA_INACTIVE,
                    WM_ACTIVATE,
                    WM_CLOSE,
                    WM_KEYDOWN,
                    WM_LBUTTONDOWN,
                    WM_LBUTTONUP,
                    WM_MOUSELEAVE,
                    WM_MOUSEMOVE,
                    WM_SETTINGCHANGE,
                    WM_SYSCOLORCHANGE,
                    WS_EX_TOOLWINDOW,
                    WS_EX_TOPMOST,
                    WS_POPUP,
                    _PerMonitorDpi,
                    _declare,
                    _dll,
                    _pack,
                    _signature)
from .words import locale_of, say


WS_EX_LAYERED, ULW_ALPHA, AC_SRC_ALPHA = 0x00080000, 0x2, 0x1
WM_CANCELMODE, WM_ACTIVATEAPP, WM_CHAR = 0x001F, 0x001C, 0x0102
WM_SYSKEYDOWN, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0104, 0x0204, 0x0205
VK_MENU, VK_END, VK_HOME, VK_F10 = 0x12, 0x23, 0x24, 0x79
# What Windows tells whoever listens as a menu opens and closes, as its own menus do.
EVENT_SYSTEM_MENUPOPUPSTART, EVENT_SYSTEM_MENUPOPUPEND = 0x0006, 0x0007


class MENU_SIZE(C.Structure):
    _fields_ = [("cx", C.c_long), ("cy", C.c_long)]


class MENU_BLEND(C.Structure):
    _fields_ = [("BlendOp", C.c_ubyte), ("BlendFlags", C.c_ubyte), ("SourceConstantAlpha", C.c_ubyte),
                ("AlphaFormat", C.c_ubyte)]


_menu_lock = threading.Lock()
_menu_declared = []


def _declare_menu():
    """The few calls the popup itself never makes, declared once on the popup's handles."""
    _declare()
    with _menu_lock:
        if _menu_declared:
            return
        user32 = _dll("user32")
        _signature(user32.UpdateLayeredWindow, W.BOOL, C.c_void_p, C.c_void_p, C.POINTER(W.POINT),
                   C.POINTER(MENU_SIZE), C.c_void_p, C.POINTER(W.POINT), W.DWORD, C.POINTER(MENU_BLEND), W.DWORD)
        _signature(user32.GetForegroundWindow, C.c_void_p)
        _menu_declared.append(True)


# ------------------------------------------------------------------------------ the picture
class MenuRenderer(Renderer):
    """The popup's renderer, drawing the menu: its card and lift over nothing, its items, their words."""

    def menu_layout(self, entries, scale, locale, max_width=None):
        """The menu's plan in `locale` at `scale`: mirrored when the language is written right to left."""
        self.use(locale, scale)
        laid = menu_layout(entries, scale, self.measure, max_width)
        return menu_mirror(laid) if l10n.right_to_left(locale) else laid

    def draw_menu(self, plan, selected=None):
        """The whole window into the canvas, premultiplied, its alpha kept: transparent but for the card's lift and
        the card. Returns the canvas."""
        width, height = plan["size"]
        scale, card = plan["scale"], plan["card"]
        canvas = self.canvas
        canvas.ensure(width, height)
        _dll("gdi32").GdiFlush()
        C.memset(canvas.bits, 0, width * height * 4)
        self._use_scale(scale)
        radii = self._radii()
        radius = int(round(radii["card"] * scale))
        pill = radii["small"] * scale
        hairline = max(1.0, round(scale))
        with _Painter(canvas, PIXEL_FORMAT_32BPP_PARGB) as paint:
            # The card as the popup's card is drawn - its drop shadow, its ground, its hairline - but with no bright edge: not
            # light's highlight glowing round it, not dark's one-pixel top light inside it (the owner, 2026-11-01: the
            # raised look's lit edge does not belong round a menu).
            self._lift(paint, "card", card, radius, scale, lights=False)
            ground = (self._argb("surface") if self.contrast
                      else _pack(brand.rgb(brand.card_ground(self._theme(), self._design()))))
            paint.fill_round(card, radius, ground)
            paint.stroke_round(card, radius, self._argb("line"), hairline)
            for item in plan["items"]:
                if item["kind"] == "rule":
                    paint.fill_round(item["rect"], 0, self._argb("line"))
                    continue
                held = item["enabled"] and item["index"] == selected
                if held and self.contrast:
                    paint.fill_round(item["rect"], pill, self._argb("accent"))      # Highlight, as Windows' menus
                elif held:
                    # The item in hand rises: a raised pill with the control's lift, as the window's menus have it.
                    self._lift(paint, "control", item["rect"], pill, scale)
                    paint.fill_round(item["rect"], pill, self._argb("raised"))
                    paint.stroke_round(item["rect"], pill, self._argb("line"), hairline)
                if item["checked"]:
                    left, top, right, bottom = item["dot"]
                    dot = "on_accent" if held and self.contrast else ("accent" if item["enabled"] else "muted")
                    paint.fill_circle((left + right) / 2.0, (top + bottom) / 2.0, (right - left) / 2.0,
                                      self._argb(dot))
        self._menu_words(canvas, plan, selected)
        return canvas

    def _menu_words(self, canvas, plan, selected):
        """Each item's words, one line each, in the body role, through GDI as the popup's are - and then each line's
        alpha put back, which GDI's text clears: the words lie on the opaque card, so every pixel there is whole."""
        gdi32, user32 = _dll("gdi32"), _dll("user32")
        dc = canvas.dc
        gdi32.SetBkMode(dc, 1)                                             # transparent
        previous = gdi32.SelectObject(dc, self.fonts.handles["body"])
        drawn = []
        try:
            for item in plan["items"]:
                if item["kind"] != "item":
                    continue
                held = item["enabled"] and item["index"] == selected
                colour = "muted" if not item["enabled"] else ("on_accent" if held and self.contrast else "ink")
                gdi32.SetTextColor(dc, self._colorref(colour))
                flags = DT_NOPREFIX | DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS
                if plan.get("rtl"):
                    flags |= DT_RIGHT | DT_RTLREADING
                left, top, right, bottom = (int(value) for value in item["text_rect"])
                user32.DrawTextW(dc, item["text"], -1, C.byref(W.RECT(left, top, right, bottom)), flags)
                drawn.append((left, top, right, bottom))
        finally:
            gdi32.SelectObject(dc, previous)
            gdi32.GdiFlush()
        width, height = canvas.width, canvas.height
        memory = memoryview((C.c_ubyte * (width * height * 4)).from_address(canvas.bits.value)).cast("B")
        for left, top, right, bottom in drawn:
            left, right = max(0, left), min(width, right)
            for row in range(max(0, top), min(height, bottom)):
                start = (row * width + left) * 4 + 3
                memory[start:(row * width + right) * 4:4] = b"\xff" * (right - left)


# ------------------------------------------------------------------------------ the window
class Menu:
    """The menu's window: made the first time the icon is right-clicked, shown and hidden after that, and destroyed
    with the icon. On the icon's thread only."""

    def __init__(self, *, log=None):
        self.log = log or (lambda *unused: None)
        self.hwnd = None
        self.visible = False
        self.entries, self.strings, self.locale = [], {}, l10n.DEFAULT
        self.on_choose = None
        self.selected = None
        self.contrast, self._theme, self._design = False, "light", brand.DEFAULT_DESIGN
        self._renderer = None
        self._plan = None
        self._origin = (0, 0)
        self._proc = None
        self._class = None
        self._tracking = False
        self._access = None                      # what a screen reader is handed, made when one first asks
        self._spoken = []

    # ------------------------------------------------------------------ life
    def create(self):
        _declare_menu()
        user32, kernel32 = _dll("user32"), _dll("kernel32")
        instance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.hCursor = user32.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        self._class = "CodexAutoResumeMenu-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self._class
        if not user32.RegisterClassW(C.byref(klass)):
            self._class = None
            raise OSError("RegisterClassW")
        try:
            with _PerMonitorDpi():
                self.hwnd = user32.CreateWindowExW(WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST, self._class,
                                                   say(self.strings, "tray.title"), WS_POPUP, 0, 0, 1, 1,
                                                   None, None, instance, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW")
            self._renderer = MenuRenderer()
        except Exception:
            self.destroy()
            raise

    def destroy(self):
        user32 = _dll("user32")
        access.disconnect(self)
        hwnd, self.hwnd = self.hwnd, None
        self.visible = False
        if hwnd:
            user32.DestroyWindow(hwnd)
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._plan = None
        if self._class:
            user32.UnregisterClassW(self._class, _dll("kernel32").GetModuleHandleW(None))
            self._class = None

    # ------------------------------------------------------------------ the icon asks
    def open(self, entries, strings, on_choose) -> bool:
        """Show `entries` at the pointer and take the keyboard; `on_choose(id)` once one is chosen. False when it
        could not take the foreground - Windows refused it the focus - and it is hidden again: the icon shows
        Windows' own menu for that opening, which has the same need and its own ways round it."""
        if self.hwnd is None:
            self.create()
        self.entries, self.strings, self.on_choose = list(entries), dict(strings or {}), on_choose
        self.locale = locale_of(self.strings)
        self.selected = None
        self._read_look()
        screen = self._screen_now()
        scale = screen["dpi"] / 96.0
        work = screen["work"]
        plan = self._renderer.menu_layout(self.entries, scale, self.locale, work[2] - work[0])
        size = (plan["card"][2] - plan["card"][0], plan["card"][3] - plan["card"][1])
        fit = textsize.fitting(look.text_scale(), size, (work[2] - work[0], work[3] - work[1]))
        if fit > 1.0:
            # Windows' text size draws the whole menu that much larger, as it does the popup, as far as the screen holds.
            plan = self._renderer.menu_layout(self.entries, scale * fit, self.locale, work[2] - work[0])
        self._plan = plan
        self._origin = menu_place(plan, screen["cursor"], work)
        self._push()
        user32 = _dll("user32")
        width, height = plan["size"]
        with _PerMonitorDpi():
            user32.SetWindowPos(self.hwnd, C.c_void_p(HWND_TOPMOST), self._origin[0], self._origin[1], width, height,
                                SWP_NOACTIVATE)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        self.visible = True
        user32.SetForegroundWindow(self.hwnd)
        user32.SetFocus(self.hwnd)
        if user32.GetForegroundWindow() != self.hwnd:
            self.close(quietly=True)
            return False
        self._spoken = self.accessible_items()
        self._tell(EVENT_SYSTEM_MENUPOPUPSTART)
        return True

    def close(self, quietly=False):
        """Hidden, with nothing chosen."""
        if not self.visible:
            return
        self.visible = False
        self.selected = None
        self._tracking = False
        if self.hwnd:
            _dll("user32").ShowWindow(self.hwnd, SW_HIDE)
        if not quietly:
            self._tell(EVENT_SYSTEM_MENUPOPUPEND)
        self._spoken = []

    def _activate(self, index):
        """Choose the item at `index` - by a click, Enter, its letter, or a screen reader's default action: the menu
        closes, then the icon is handed the item's id. An item that cannot be used does nothing, as in Windows'."""
        if not self.visible or not (0 <= index < len(self.entries)):
            return
        entry = self.entries[index]
        if entry is None or not entry.get("enabled"):
            return
        chosen = self.on_choose
        self.close()
        if chosen is not None:
            chosen(entry["id"])

    # ------------------------------------------------------------------ what it looks like
    def _read_look(self):
        """High Contrast, the theme and the design, asked as the popup asks them, each time the menu opens or Windows
        says a setting changed."""
        self.contrast = look.high_contrast()
        self._theme = effective_theme(theme_setting(), look.apps_use_light_theme())
        self._design = design_setting()

    def _screen_now(self):
        """The pointer, the work area of the monitor it is on, and that monitor's scale, in physical pixels."""
        user32 = _dll("user32")
        with _PerMonitorDpi():
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            probe = W.RECT(point.x, point.y, point.x + 1, point.y + 1)
            monitor = user32.MonitorFromRect(C.byref(probe), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = C.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, C.byref(info))
            dpi = 0
            try:
                x, y = W.UINT(0), W.UINT(0)
                if _dll("shcore").GetDpiForMonitor(C.c_void_p(monitor), 0, C.byref(x), C.byref(y)) == 0:
                    dpi = x.value
            except Exception:
                dpi = 0
        work = info.rcWork
        return {"cursor": (point.x, point.y), "dpi": dpi or 96,
                "work": (work.left, work.top, work.right, work.bottom)}

    def render(self):
        """The window's picture as it is now (the tests read it back)."""
        renderer = self._renderer
        renderer.theme, renderer.design, renderer.contrast = self._theme, self._design, self.contrast
        return renderer.draw_menu(self._plan, self.selected)

    def _push(self):
        canvas = self.render()
        width, height = self._plan["size"]
        blend = MENU_BLEND(0, 0, 255, AC_SRC_ALPHA)
        with _PerMonitorDpi():
            ok = _dll("user32").UpdateLayeredWindow(self.hwnd, None, C.byref(W.POINT(*self._origin)),
                                                    C.byref(MENU_SIZE(width, height)), canvas.dc,
                                                    C.byref(W.POINT(0, 0)), 0, C.byref(blend), ULW_ALPHA)
        if not ok:
            raise OSError("UpdateLayeredWindow")

    def _select(self, index):
        """Put `index` in hand (None: nothing), draw it, and tell a screen reader."""
        if index == self.selected:
            return
        self.selected = index
        if self.visible:
            self._push()
            self._speak()

    # ------------------------------------------------------------------ a screen reader
    def accessible_items(self):
        return menu_accessible_items(self._plan, self.selected, self.strings) if self.visible else []

    def _speak(self):
        items = self.accessible_items()
        before, self._spoken = self._spoken, items
        if before:
            access.announce(self, before, items)

    def _tell(self, event):
        if not self.hwnd:
            return
        try:
            access._declare_msaa()
            access._com("user32").NotifyWinEvent(event, self.hwnd, access.OBJID_CLIENT, access.CHILDID_SELF)
        except Exception:
            pass

    # ------------------------------------------------------------------ messages
    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            handled = self._handle(message, wparam, lparam)
            if handled is not None:
                return handled
        except Exception as exc:                 # the menu must never take the watcher down
            self.log("tray menu message failed (%s)" % type(exc).__name__)
            try:
                self.close()
            except Exception:
                pass
        return _dll("user32").DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle(self, message, wparam, lparam):
        if message == access.WM_GETOBJECT:
            return access.answer(self, wparam, lparam, MenuAccessible)
        if message == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                self.close()                     # a click anywhere else, or anything that takes the focus
                return 0
            return None
        if message in (WM_CANCELMODE, WM_CLOSE):
            self.close()
            return 0
        if message == WM_ACTIVATEAPP:
            if not wparam:
                self.close()                     # another program took the foreground
            return None
        if message == WM_KEYDOWN:
            return self._key(wparam)
        if message == WM_SYSKEYDOWN:
            if wparam in (VK_MENU, VK_F10):
                self.close()                     # Alt or F10 leaves a menu, as Windows' does
                return 0
            return None
        if message == WM_CHAR:
            if not self.visible or (wparam & 0xFFFF) < 0x20:
                return 0                         # Enter's and Esc's own characters, after their keys
            index, choose = menu_letter(self.entries, self.selected, chr(wparam & 0xFFFF))
            if choose:
                self._activate(index)
            else:
                self._select(index)
            return 0
        if message == WM_MOUSEMOVE:
            self._mouse_move(lparam)
            return 0
        if message == WM_MOUSELEAVE:
            self._tracking = False
            self._select(None)
            return 0
        if message in (WM_LBUTTONDOWN, WM_RBUTTONDOWN):
            if not self._on_card(lparam):
                self.close()                     # its shadow is not the menu
            return 0
        if message in (WM_LBUTTONUP, WM_RBUTTONUP):
            target = self._hit(lparam)
            if target is not None:
                self._activate(target)
            return 0
        if message in (WM_SETTINGCHANGE, WM_SYSCOLORCHANGE):
            if self.visible:
                self._read_look()
                self._push()
            return None
        return None

    @staticmethod
    def _point(lparam):
        return C.c_short(lparam & 0xFFFF).value, C.c_short((lparam >> 16) & 0xFFFF).value

    def _hit(self, lparam):
        if self._plan is None:
            return None
        return hit_test(self._plan["targets"], *self._point(lparam))

    def _on_card(self, lparam):
        if self._plan is None:
            return False
        x, y = self._point(lparam)
        left, top, right, bottom = self._plan["card"]
        return left <= x < right and top <= y < bottom

    def _mouse_move(self, lparam):
        self._select(self._hit(lparam))
        if not self._tracking and self.hwnd:
            track = TRACKMOUSEEVENT()
            track.cbSize = C.sizeof(TRACKMOUSEEVENT)
            track.dwFlags = TME_LEAVE
            track.hwndTrack = self.hwnd
            self._tracking = bool(_dll("user32").TrackMouseEvent(C.byref(track)))

    def _key(self, key):
        if key == VK_ESCAPE:
            self.close()
        elif key in (VK_UP, VK_DOWN):
            self._select(menu_step(self.entries, self.selected, backwards=key == VK_UP))
        elif key in (VK_HOME, VK_END):
            self._select(menu_end(self.entries, last=key == VK_END))
        elif key == VK_RETURN:
            if self.selected is not None:
                self._activate(self.selected)
        else:
            return None
        return 0


class MenuAccessible(access.PopupAccessible):
    """The menu's client object for MSAA: the popup's, answering for a menu - a menu popup whose children are its items
    and lines, by menuplan's menu_accessible_items, named with the product's name."""

    def items(self):
        return self.popup.accessible_items()

    def _name(self, this, *arguments):
        return self._string(arguments, lambda item: say(self.popup.strings, "tray.title") if item is None
                            else item["name"])

    def _description(self, this, *arguments):
        return self._string(arguments, lambda item: None if item is None else item["description"])

    def _role(self, this, *arguments):
        *variant, out = arguments
        child, item = self._item(variant)
        if child is None:
            return access.E_INVALIDARG
        return self._number(out, access.A11Y_ROLES["menu" if item is None else item["role"]])
