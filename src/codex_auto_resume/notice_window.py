"""The notification card, the Win32 half: layered windows beside the notification area.

`notice_card.py` decides what a card says, where it goes and how it moves; this file puts it on
the screen. It lives on the icon's thread inside the watcher, as the popup does (B-D1): the
icon's thread creates `CardStack`, attaches it to the notifier's `Inbox`, and from then on a
notice posted from any thread arrives here as one message and is shown by this thread alone.

Each card is two layered windows, both `WS_EX_NOACTIVATE`, so a card never takes the focus
from whatever somebody is doing, whatever they click:

* the **shadow**, `WS_EX_TRANSPARENT` as well: the soft floating shadow, painted with per-pixel
  alpha (`UpdateLayeredWindow`) so it spills over the wallpaper. It lets every click through -
  it reaches past the card and over the taskbar, and a shadow must never eat a click on a tray
  icon or the clock;
* the **card**, owned by its shadow so it always stands above it: the popup's card, drawn by the
  popup's own renderer (`tray_popup.Renderer`) at the monitor's scale and then given its rounded
  corners in alpha. Its two buttons are the toast's two buttons.

A frame is one scaled blit of the card drawn once, one stamp of the shadow at the frame's depth,
and one `UpdateLayeredWindow` each with the frame's alpha - no layout, no text. The frame timer
runs only while something moves; a card that is only holding costs one one-shot timer.

Nothing here can act: a button click calls `on_action(uri)` on a short worker thread and the
card goes away; what the URI may do is decided in `notifier.activate`. No control layer, no
notification module, no automation of anybody else's window.

**Every notice ends once.** Each notice this stack takes from the inbox is ended by exactly one
`on_complete(notice, shown)` call, on a worker thread (the host passes `notifier.complete`):
`shown` True once the card has been on screen whole - its first frame at full strength went
through `UpdateLayeredWindow` - or was clicked, or was replaced by a newer card about the same
conversation (which then speaks for it); False when it broke, was pushed out of the stack or
the stack went away before it was ever seen whole, and for every notice still waiting in the
inbox when the stack goes. A card that breaks after it was seen is only taken down: it has
been shown, and its history copy is already on its way.
"""
from __future__ import annotations

import ctypes as C
import os
import threading
import time

from . import brand, notice_card, notice_presence, tray_popup

if os.name == "nt":
    from ctypes import wintypes as W
    from .tray import LRESULT, WNDCLASSW, WNDPROC
else:                                              # pragma: no cover - the pure half only
    W = None

WM_DESTROY, WM_TIMER, WM_SETTINGCHANGE = 0x0002, 0x0113, 0x001A
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONUP = 0x0200, 0x0201, 0x0202, 0x0205
WM_MOUSEACTIVATE, WM_MOUSELEAVE, WM_NCDESTROY = 0x0021, 0x02A3, 0x0082
WM_APP = 0x8000
WM_NOTICE = WM_APP + 7                     # the notifier's Inbox has something for this thread
MA_NOACTIVATE = 3
WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE = 0x00080000, 0x00000020, 0x08000000
WS_EX_TOOLWINDOW, WS_EX_TOPMOST = 0x00000080, 0x00000008
HWND_MESSAGE, HWND_TOPMOST = -3, -1
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE = 0x0010, 0x0002, 0x0001
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 0x2, 0x0, 0x1
IDC_ARROW = 32512
TME_LEAVE = 0x2
MONITOR_DEFAULTTONEAREST, MONITOR_DEFAULTTOPRIMARY = 2, 1
ABM_GETTASKBARPOS = 5
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
TIMER_FRAME, TIMER_WAIT = 1, 2
PIXEL_FORMAT_32BPP_PARGB = 0x000E200B
INTERPOLATION_HIGH_QUALITY_BILINEAR, PIXEL_OFFSET_HALF, COMPOSITING_HIGH_QUALITY = 6, 4, 2
UNIT_PIXEL = 2

_DLLS = {}
_DECLARED = False
_DECLARE_LOCK = threading.Lock()
# GDI+ objects this module makes itself (the popup's renderer and shadow images count their own
# in tray_popup.gdiplus_objects): the leak tests read both.
_LIVE = {"objects": 0}
_LIVE_LOCK = threading.Lock()


def _made(count):
    with _LIVE_LOCK:
        _LIVE["objects"] += count


def gdiplus_objects() -> int:
    return _LIVE["objects"]


def _dll(name):
    """This module's own handles, so its argument types never change another module's."""
    if name not in _DLLS:
        _DLLS[name] = C.WinDLL(name, use_last_error=True)
    return _DLLS[name]


def _on_a_worker_thread(target, *args):
    """Run `target(*args)` on a short daemon thread, never on the icon's thread, which draws:
    what a callback does (raise a toast, cancel through the control layer) may take seconds."""
    threading.Thread(target=target, args=args, name="notice-callback", daemon=True).start()


if os.name == "nt":
    class BLENDFUNCTION(C.Structure):
        _fields_ = [("BlendOp", C.c_ubyte), ("BlendFlags", C.c_ubyte), ("SourceConstantAlpha", C.c_ubyte),
                    ("AlphaFormat", C.c_ubyte)]

    class SIZE(C.Structure):
        _fields_ = [("cx", W.LONG), ("cy", W.LONG)]

    class APPBARDATA(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uCallbackMessage", W.UINT), ("uEdge", W.UINT),
                    ("rc", W.RECT), ("lParam", W.LPARAM)]

    class TRACKMOUSEEVENT(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("dwFlags", W.DWORD), ("hwndTrack", W.HWND), ("dwHoverTime", W.DWORD)]

    class MONITORINFO(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]

    class BITMAPINFOHEADER(C.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                    ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                    ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]

    class BITMAPINFO(C.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]


def _signature(function, result, *arguments):
    function.restype = result
    function.argtypes = list(arguments)


def _declare():
    global _DECLARED
    with _DECLARE_LOCK:
        if _DECLARED:
            return
        H, I, U, D, F = C.c_void_p, C.c_int, W.UINT, W.DWORD, C.c_float
        user32, gdi32, gdiplus = _dll("user32"), _dll("gdi32"), _dll("gdiplus")
        _signature(user32.CreateWindowExW, H, D, W.LPCWSTR, W.LPCWSTR, D, I, I, I, I, H, H, H, H)
        _signature(user32.DefWindowProcW, LRESULT, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.RegisterClassW, W.ATOM, C.POINTER(WNDCLASSW))
        _signature(user32.UnregisterClassW, W.BOOL, W.LPCWSTR, H)
        _signature(user32.DestroyWindow, W.BOOL, H)
        _signature(user32.ShowWindow, W.BOOL, H, I)
        _signature(user32.SetWindowPos, W.BOOL, H, H, I, I, I, I, U)
        _signature(user32.UpdateLayeredWindow, W.BOOL, H, H, C.POINTER(W.POINT), C.POINTER(SIZE), H,
                   C.POINTER(W.POINT), D, C.POINTER(BLENDFUNCTION), D)
        _signature(user32.PostMessageW, W.BOOL, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.SetTimer, C.c_size_t, H, C.c_size_t, U, H)
        _signature(user32.KillTimer, W.BOOL, H, C.c_size_t)
        _signature(user32.TrackMouseEvent, W.BOOL, C.POINTER(TRACKMOUSEEVENT))
        _signature(user32.MonitorFromRect, H, C.POINTER(W.RECT), D)
        _signature(user32.MonitorFromPoint, H, W.POINT, D)
        _signature(user32.GetMonitorInfoW, W.BOOL, H, C.POINTER(MONITORINFO))
        _signature(user32.LoadCursorW, H, H, H)
        _signature(_dll("shell32").SHAppBarMessage, C.c_size_t, D, C.POINTER(APPBARDATA))
        _signature(_dll("kernel32").GetModuleHandleW, H, W.LPCWSTR)
        _signature(gdi32.CreateCompatibleDC, H, H)
        _signature(gdi32.DeleteDC, W.BOOL, H)
        _signature(gdi32.CreateDIBSection, H, H, C.POINTER(BITMAPINFO), U, C.POINTER(C.c_void_p), H, D)
        _signature(gdi32.SelectObject, H, H, H)
        _signature(gdi32.DeleteObject, W.BOOL, H)
        _signature(gdi32.GdiFlush, W.BOOL)
        _signature(gdiplus.GdipCreateBitmapFromScan0, I, I, I, I, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipGetImageGraphicsContext, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDisposeImage, I, H)
        _signature(gdiplus.GdipDeleteGraphics, I, H)
        _signature(gdiplus.GdipSetInterpolationMode, I, H, I)
        _signature(gdiplus.GdipSetPixelOffsetMode, I, H, I)
        _signature(gdiplus.GdipSetCompositingQuality, I, H, I)
        _signature(gdiplus.GdipDrawImageRectRect, I, H, H, F, F, F, F, F, F, F, F, I, H, H, H)
        _signature(gdiplus.GdipDrawImageRectRectI, I, H, H, I, I, I, I, I, I, I, I, I, H, H, H)
        _signature(_dll("shcore").GetDpiForMonitor, C.c_long, H, I, C.POINTER(W.UINT), C.POINTER(W.UINT))
        _DECLARED = True


# ------------------------------------------------------------------------------ the screen
def taskbar_corner():
    """The primary taskbar's notification-area end as a thin rectangle, and its edge; or None.

    SHAppBarMessage is the documented question "where is the taskbar": it names no other
    window and reads nothing but a rectangle. The notification area sits at the far end of a
    horizontal taskbar and at the bottom of a vertical one.
    """
    try:
        _declare()
        data = APPBARDATA()
        data.cbSize = C.sizeof(APPBARDATA)
        if not _dll("shell32").SHAppBarMessage(ABM_GETTASKBARPOS, C.byref(data)):
            return None
        rc = data.rc
        if rc.right <= rc.left or rc.bottom <= rc.top:
            return None
        if data.uEdge in (ABE_LEFT, ABE_RIGHT):
            return (rc.left, rc.bottom - 2, rc.right, rc.bottom - 1)
        return (rc.right - 2, rc.top, rc.right - 1, rc.bottom)
    except Exception:
        return None


def screen(anchor=None) -> dict:
    """The monitor a card goes on: the one with the icon, else the notification area, else the
    primary. Work area and monitor rectangles in physical pixels, and that monitor's DPI."""
    _declare()
    user32 = _dll("user32")
    with tray_popup._PerMonitorDpi():
        icon = None
        try:
            icon = anchor() if anchor else None
        except Exception:
            icon = None
        corner = icon or taskbar_corner()
        if corner is not None:
            probe = W.RECT(*corner)
            monitor = user32.MonitorFromRect(C.byref(probe), MONITOR_DEFAULTTONEAREST)
        else:
            monitor = user32.MonitorFromPoint(W.POINT(0, 0), MONITOR_DEFAULTTOPRIMARY)
        info = MONITORINFO()
        info.cbSize = C.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(monitor, C.byref(info))
        dpi = 0
        try:
            x, y = W.UINT(0), W.UINT(0)
            if _dll("shcore").GetDpiForMonitor(monitor, 0, C.byref(x), C.byref(y)) == 0:
                dpi = x.value
        except Exception:
            dpi = 0
    work, whole = info.rcWork, info.rcMonitor
    return {"anchor": corner, "dpi": dpi or 96,
            "work": (work.left, work.top, work.right, work.bottom),
            "monitor": (whole.left, whole.top, whole.right, whole.bottom)}


def look() -> dict:
    """How cards are drawn now: theme, High Contrast and whether anything may move."""
    contrast = tray_popup.high_contrast()
    theme = tray_popup.effective_theme(tray_popup.theme_setting(), tray_popup.apps_use_light_theme())
    reduced = bool(tray_popup.reduced_motion() or contrast or notice_presence.battery_saver())
    return {"theme": theme, "contrast": contrast, "reduced": reduced}


# ------------------------------------------------------------------------ one layered window
class _Layer:
    """A layered window and the premultiplied 32-bit DIB it is updated from."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.dc = _dll("gdi32").CreateCompatibleDC(None)
        if not self.dc:
            raise OSError("CreateCompatibleDC")
        self.bitmap = self.original = None
        self.bits = C.c_void_p()
        self.width = self.height = 0
        self.shown = False

    def ensure(self, width, height):
        if self.bitmap and (width, height) == (self.width, self.height):
            return
        gdi32 = _dll("gdi32")
        info = BITMAPINFO()
        info.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth, info.bmiHeader.biHeight = width, -height
        info.bmiHeader.biPlanes, info.bmiHeader.biBitCount = 1, 32
        bits = C.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.dc, C.byref(info), 0, C.byref(bits), None, 0)
        if not bitmap:
            raise OSError("CreateDIBSection")
        previous = gdi32.SelectObject(self.dc, bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        else:
            self.original = previous
        self.bitmap, self.bits, self.width, self.height = bitmap, bits, width, height

    def clear(self):
        _dll("gdi32").GdiFlush()
        C.memset(self.bits, 0, self.width * self.height * 4)

    def pixels(self) -> bytes:
        _dll("gdi32").GdiFlush()
        return C.string_at(self.bits, self.width * self.height * 4)

    def push(self, x, y, alpha):
        """Put the DIB on screen at (x, y) with the whole window at `alpha` (0-1)."""
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(round(alpha * 255)))), AC_SRC_ALPHA)
        with tray_popup._PerMonitorDpi():
            ok = _dll("user32").UpdateLayeredWindow(self.hwnd, None, C.byref(W.POINT(int(x), int(y))),
                                                    C.byref(SIZE(self.width, self.height)), self.dc,
                                                    C.byref(W.POINT(0, 0)), 0, C.byref(blend), ULW_ALPHA)
            if ok and not self.shown:
                _dll("user32").SetWindowPos(self.hwnd, C.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE)
                _dll("user32").ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
                self.shown = True
        return bool(ok)

    def close(self):
        gdi32 = _dll("gdi32")
        if self.bitmap:
            gdi32.SelectObject(self.dc, self.original)
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None


class _Surface:
    """GDI+ drawing straight into a layer's premultiplied pixels (as the popup's painter does
    into its canvas). Shaped like the popup's painter where `_ShadowImage.stamp` reads it."""

    def __init__(self, layer):
        self.gp = _dll("gdiplus")
        self.bitmap, self.graphics = C.c_void_p(), C.c_void_p()
        _dll("gdi32").GdiFlush()
        status = self.gp.GdipCreateBitmapFromScan0(layer.width, layer.height, layer.width * 4,
                                                   PIXEL_FORMAT_32BPP_PARGB, layer.bits, C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        _made(1)
        status = self.gp.GdipGetImageGraphicsContext(self.bitmap, C.byref(self.graphics))
        if status != 0:
            self.gp.GdipDisposeImage(self.bitmap)
            _made(-1)
            raise OSError("GdipGetImageGraphicsContext failed (%d)" % status)
        _made(1)
        self.gp.GdipSetPixelOffsetMode(self.graphics, PIXEL_OFFSET_HALF)
        self.gp.GdipSetCompositingQuality(self.graphics, COMPOSITING_HIGH_QUALITY)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.gp.GdipDeleteGraphics(self.graphics)
        self.gp.GdipDisposeImage(self.bitmap)
        _made(-2)


class _Image:
    """Premultiplied pixels as a GDI+ image, kept alive for exactly as long as the image."""

    def __init__(self, pixels, width, height):
        self.width, self.height = width, height
        self._pixels = bytearray(pixels)
        self._memory = (C.c_ubyte * len(self._pixels)).from_buffer(self._pixels)
        self.bitmap = C.c_void_p()
        status = _dll("gdiplus").GdipCreateBitmapFromScan0(width, height, width * 4, PIXEL_FORMAT_32BPP_PARGB,
                                                           C.cast(self._memory, C.c_void_p), C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        _made(1)

    def close(self):
        if self.bitmap:
            _dll("gdiplus").GdipDisposeImage(self.bitmap)
            _made(-1)
            self.bitmap = C.c_void_p()


# ------------------------------------------------------------------------------ one card
class _CardRenderer(tray_popup.Renderer if os.name == "nt" else object):
    """The popup's renderer, and brand's own fill for a light the popup never shows.

    The popup's six states have their fills in `tray_popup.DOT_FILL`; a card can also say that
    an attempt failed, which brand draws in `danger` (brand.STATUS_FILL). Everything else - the
    glow's falloff, its size, High Contrast's system colour - is the popup's own drawing.
    """

    def _halo(self, paint, item, scale, frame):
        state = item["state"]
        if self.contrast or state in tray_popup.DOT_FILL:
            return super()._halo(paint, item, scale, frame)
        dot, fill = brand.STATUS_DOT["popup"], brand.status_fill(state)
        cx, cy = item["cx"], item["cy"]
        if frame is not None:
            paint.glow(cx, cy, brand.glow_radius(dot, frame["scale"]) * scale, brand.glow_stops(dot),
                       self._rgb(fill), frame["opacity"])
        paint.fill_circle(cx, cy, dot * scale, self._argb(fill))
        return None


class Card:
    """One notice on screen: its view, its drawn image, its two windows and its motion."""

    def __init__(self, stack, notice, *, now_ms, where, drawn, windows=True):
        _declare()
        self.stack = stack
        self.notice = notice
        self.vm = notice_card.view(notice)
        self.edge = "bottom"
        self.scale = where["dpi"] / 96.0
        self.theme, self.contrast = drawn["theme"], drawn["contrast"]
        self.motion = notice_card.CardMotion(now_ms, hold_ms=stack.hold(), reduced=drawn["reduced"])
        self.hover = self.pressed = None
        self.tracking = False
        self.pushed_out = False
        self.moved_out = False
        self.seen = False               # a frame at full strength has been put on screen, or clicked
        self.superseded = False         # a newer notice about the same conversation took its place
        self.ended = False              # on_complete has been called for this notice
        self.renderer = None
        self.plan = None
        self.image = None
        self.shadows = () if self.contrast else notice_card.float_shadows(self.theme)
        self.margin = notice_card.shadow_margin(self.shadows, self.scale) if self.shadows else 0
        self._shadow_images = {}
        self._drawn_level = None
        self._drawn_scale = None
        self._pushed = None
        self.shadow = self.body = None
        try:
            self._draw_card()
            if windows:
                self._create_windows()
            else:                                   # offscreen: the tests and the eye check
                self.shadow, self.body = _Layer(None), _Layer(None)
            width, height = self.size
            self.body.ensure(width, height)
            self.shadow.ensure(width + 2 * self.margin, height + 2 * self.margin)
        except Exception:
            self.close()
            raise

    # ---- drawing the card once
    def _draw_card(self):
        if self.renderer is None:
            self.renderer = _CardRenderer()
            self.renderer.theme, self.renderer.contrast = self.theme, self.contrast
        self.renderer.use(self.vm["locale"], self.scale)
        self.plan = notice_card.layout(self.vm, self.scale, self.renderer.measure)
        glow = None if self.contrast else brand.glow(self.vm["status"], 0.0, None, reduced=True)
        canvas = self.renderer.draw(self.vm, self.plan, frame=glow, hover=self.hover, pressed=self.pressed)
        width, height = self.plan["size"]
        pixels = notice_card.premultiply(canvas.pixels(), width, height,
                                         brand.RADII["card"] * self.scale)
        if self.image is not None:
            self.image.close()
        self.image = _Image(pixels, width, height)
        self._drawn_scale = None

    @property
    def size(self):
        return self.plan["size"]

    def _create_windows(self):
        user32, stack = _dll("user32"), self.stack
        width, height = self.size
        with tray_popup._PerMonitorDpi():
            base = WS_EX_LAYERED | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            shadow = user32.CreateWindowExW(base | WS_EX_TRANSPARENT, stack.class_name, "", WS_POPUP,
                                            0, 0, width + 2 * self.margin, height + 2 * self.margin,
                                            None, None, stack.instance, None)
            if not shadow:
                raise OSError("CreateWindowExW")
            self.shadow = _Layer(shadow)
            stack.windows[shadow] = self
            body = user32.CreateWindowExW(base, stack.class_name, self.notice.title, WS_POPUP,
                                          0, 0, width, height, shadow, None, stack.instance, None)
            if not body:
                raise OSError("CreateWindowExW")
            self.body = _Layer(body)
            stack.windows[body] = self

    def redraw(self):
        """The pointer moved onto or off a button, or pressed one: draw the face again."""
        self._draw_card()
        self._pushed = None

    # ---- a frame
    def _paint_body(self, scale):
        if self._drawn_scale == scale:
            return
        layer, image = self.body, self.image
        if scale >= 0.9999:
            _dll("gdi32").GdiFlush()
            C.memmove(layer.bits, image._memory, len(image._pixels))
        else:
            layer.clear()
            width, height = image.width * scale, image.height * scale
            left, top = (image.width - width) / 2.0, (image.height - height) / 2.0
            with _Surface(layer) as surface:
                surface.gp.GdipSetInterpolationMode(surface.graphics, INTERPOLATION_HIGH_QUALITY_BILINEAR)
                surface.gp.GdipDrawImageRectRect(surface.graphics, image.bitmap, left, top, width, height,
                                                 0.0, 0.0, float(image.width), float(image.height),
                                                 UNIT_PIXEL, None, None, None)
        self._drawn_scale = scale

    def _paint_shadow(self, level):
        if self._drawn_level == level or not self.shadows:
            return
        layer = self.shadow
        layer.clear()
        images = self._shadow_images.get(level)
        width, height = self.size
        radius = brand.RADII["card"] * self.scale
        depth = level / float(notice_card.DEPTH_LEVELS - 1)
        placed = notice_card.shadow_at(self.shadows, depth)
        if images is None:
            images = []
            for shadow in placed:
                mask = tray_popup.lift_coverage(width, height, radius, shadow.blur * self.scale)
                images.append(tray_popup._ShadowImage(mask, brand.rgb(shadow.colour), shadow.alpha))
            self._shadow_images[level] = images
        with _Surface(layer) as surface:
            surface.gp.GdipSetInterpolationMode(surface.graphics, 5)        # nearest: stretched middles stay exact
            for shadow, image in zip(reversed(placed), reversed(images)):
                extent = image.extent
                image.stamp(surface, self.margin - extent + tray_popup.shadow_step(shadow.dx * self.scale),
                            self.margin - extent + tray_popup.shadow_step(shadow.dy * self.scale),
                            width + 2 * extent, height + 2 * extent, middle=False)
        self._drawn_level = level

    def paint(self, now_ms) -> dict:
        """Draw both layers for `now_ms`: the frame, where the card goes, and a key for the frame."""
        frame = self.motion.frame(now_ms)
        x, y = self.motion.place(now_ms) or (0, 0)
        vector = notice_card.rise_vector(self.edge)
        push = int(round(frame.offset * self.scale))
        x, y = x + vector[0] * push, y + vector[1] * push
        level = notice_card.depth_level(frame.depth)
        self._paint_body(round(frame.scale, 4))
        if self.shadows:
            self._paint_shadow(level)
        return {"frame": frame, "x": x, "y": y, "margin": self.margin,
                "key": (x, y, round(frame.alpha, 3), round(frame.scale, 4), level)}

    def present(self, now_ms):
        """Draw this card for `now_ms` and put both windows where the frame says.

        Raises when Windows refuses either layer: a card that is not on the screen must not live
        out its motion unseen, it has to be handed back (see CardStack._tick)."""
        drawn = self.paint(now_ms)
        if drawn["key"] == self._pushed:
            return
        x, y, alpha = drawn["x"], drawn["y"], drawn["frame"].alpha
        if self.shadows and not self.shadow.push(x - self.margin, y - self.margin, alpha):
            raise OSError("UpdateLayeredWindow refused the shadow")
        if not self.body.push(x, y, alpha):
            raise OSError("UpdateLayeredWindow refused the card")
        self._pushed = drawn["key"]
        if alpha >= 1.0:
            self.seen = True

    def hit(self, lparam):
        x = C.c_short(lparam & 0xFFFF).value
        y = C.c_short((lparam >> 16) & 0xFFFF).value
        return tray_popup.hit_test(self.plan["targets"], x, y) if self.plan else None

    def close(self):
        user32 = _dll("user32")
        for layer in (self.body, self.shadow):
            if layer is not None:
                if layer.hwnd:
                    self.stack.windows.pop(layer.hwnd, None)
                    user32.DestroyWindow(layer.hwnd)
                layer.close()
        self.body = self.shadow = None
        for images in self._shadow_images.values():
            for image in images:
                image.close()
        self._shadow_images = {}
        if self.image is not None:
            self.image.close()
            self.image = None
        if self.renderer is not None:
            self.renderer.close()
            self.renderer = None


# ----------------------------------------------------------------------------- the stack
class CardStack:
    """Every card on screen, on the icon's thread. `wake` is the one method another thread calls.

    `on_action(uri)` is called on a worker thread when a card's button is clicked; `anchor()`
    returns the icon's rectangle or None (`tray_popup.icon_rect`); `inbox` is the notifier's
    Inbox, which this stack attaches itself to once its window exists; `on_complete(notice,
    shown)` ends each notice it took, once, on a worker thread (see the module's docstring).
    `worker(target, *args)` runs a callback off the icon's thread (a short daemon thread unless
    given). `locate()` and `appearance()` stand in for `screen` and `look` (the tests put cards
    somewhere no screen shows them).
    """

    def __init__(self, *, on_action=None, log=None, anchor=None, inbox=None, on_complete=None,
                 clock=None, locate=None, appearance=None, worker=None):
        self.on_action = on_action
        self.log = log or (lambda *unused: None)
        self.anchor = anchor
        self.inbox = inbox
        self.on_complete = on_complete
        self.worker = worker or _on_a_worker_thread
        self.clock = clock or (lambda: time.monotonic() * 1000.0)
        self.locate = locate or (lambda: screen(self.anchor))
        self.appearance = appearance or look
        self.hwnd = None
        self.class_name = None
        self.instance = None
        self.cards = []                 # newest first
        self.windows = {}               # hwnd -> Card
        self._proc = None
        self._frame_running = False
        self._hovered = False
        self._gdiplus = False

    # ---- lifecycle
    def create(self):
        _declare()
        user32 = _dll("user32")
        self.instance = _dll("kernel32").GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = self.instance
        klass.hCursor = user32.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        self.class_name = "CodexAutoResumeCard-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self.class_name
        if not user32.RegisterClassW(C.byref(klass)):
            self.class_name = None
            raise OSError("RegisterClassW")
        self.hwnd = user32.CreateWindowExW(0, self.class_name, "", 0, 0, 0, 0, 0,
                                           C.c_void_p(HWND_MESSAGE), None, self.instance, None)
        if not self.hwnd:
            self.destroy()
            raise OSError("CreateWindowExW")
        if self.inbox is not None:
            self.inbox.attach(self.wake)
        return self

    def wake(self) -> bool:
        """Any thread: ask this stack's thread to take what the inbox holds."""
        hwnd = self.hwnd
        return bool(hwnd) and bool(_dll("user32").PostMessageW(hwnd, WM_NOTICE, 0, 0))

    def destroy(self):
        """Take every card down and let go of the inbox. Every notice this stack was given and
        has not ended yet ends now: shown if it was seen (or had already left by design),
        today's toast if it was still arriving or never taken from the inbox."""
        waiting = self.inbox.detach() if self.inbox is not None else []
        user32 = _dll("user32")
        for card in list(self.cards):
            self._end(card, card.seen or card.superseded)
            self._drop(card)
        for notice in waiting:
            self._complete(notice, False)
        hwnd, self.hwnd = self.hwnd, None
        if hwnd:
            for timer in (TIMER_FRAME, TIMER_WAIT):
                user32.KillTimer(hwnd, timer)
            user32.DestroyWindow(hwnd)
        self._frame_running = False
        if self.class_name:
            user32.UnregisterClassW(self.class_name, self.instance)
            self.class_name = None
        self._release_gdiplus()

    def hold(self) -> float:
        return notice_card.hold_ms(notice_presence.message_duration_ms())

    def _acquire_gdiplus(self):
        if not self._gdiplus:
            tray_popup._gdiplus_acquire()
            self._gdiplus = True

    def _release_gdiplus(self):
        if self._gdiplus:
            tray_popup._gdiplus_release()
            self._gdiplus = False

    # ---- showing
    def show(self, notice, *, where=None, drawn=None):
        """Put one notice on screen as the newest card. Returns the Card, or None if it failed."""
        now = self.clock()
        try:
            self._acquire_gdiplus()
            where = where or self.locate()
            drawn = drawn or self.appearance()
            card = Card(self, notice, now_ms=now, where=where, drawn=drawn)
        except Exception as exc:
            self.log("notification card unavailable (%s)" % type(exc).__name__)
            if not self.cards:
                self._release_gdiplus()
            self._complete(notice, False)
            return None
        try:
            self.admit(card, now, where)
        except Exception as exc:
            self.log("notification card unavailable (%s)" % type(exc).__name__)
            self._end(card, False)
            self._drop(card)
            return None
        self._tick()
        return card

    def admit(self, card, now, where):
        """A new card joins the stack: what it replaces or pushes out leaves.

        A newer notice about a conversation that already has a card takes that card's place: the
        old one fades out quickly where it is and the new one rises into the same slot as it goes,
        so a task's card reads as one card moving through its states. Anything else arrives as
        the newest, nearest the corner, once the stack has begun to make room for it.
        """
        key = getattr(card.notice, "key", None)
        living = [entry for entry in self.cards if entry.motion.phase not in ("exit", "gone")]
        replaced = next((entry for entry in living if key and getattr(entry.notice, "key", None) == key), None)
        if replaced is not None:
            replaced.motion.retire(now, quick=True)
            replaced.superseded = True
            self.cards.insert(self.cards.index(replaced), card)
            card.motion.delay(notice_card.SWAP_MS)
            settle = notice_card.SWAP_MS               # the others make room once it has gone
        else:
            self.cards.insert(0, card)
            settle = 0
            if living:
                card.motion.delay(notice_card.STACK_DELAY_MS)
        living = [entry for entry in self.cards if entry.motion.phase not in ("exit", "gone")]
        for extra in living[notice_card.MAX_CARDS:]:
            extra.motion.retire(now)                     # the oldest leaves early,
            extra.pushed_out = True                      # moving on with the stack as it fades
        self._restack(now, where, settle)
        if self._hovered:
            card.motion.pause(now, True)

    def _restack(self, now, where, delay=0):
        """Give every card its place, newest nearest the corner. A card the work area has no room
        for retires, as a fourth one does. A card leaving because a new one came moves away from
        the corner by the new card's height while it fades, as the stack does, so a leaving card
        and an arriving one never cross."""
        living = [card for card in self.cards if card.motion.phase not in ("exit", "gone")]
        scale = where["dpi"] / 96.0
        gap = int(round(brand.SPACING["m"] * scale))
        spacing = int(round(brand.SPACING["m"] * scale))
        positions, edge = notice_card.stack_positions([card.size for card in living], where["work"],
                                                      where["monitor"], where["anchor"], gap=gap,
                                                      spacing=spacing)
        for extra in living[len(positions):]:
            extra.motion.retire(now)                     # no room: it leaves with the older ones,
            extra.pushed_out = True                      # never laid over a newer card
        living = living[:len(positions)]
        for card, position in zip(living, positions):
            if card.motion.position is None:
                card.edge = edge
            card.motion.move_to(now, position, delay)
        if not living or not positions:
            return
        newest = living[0]
        away = notice_card.stack_direction(edge, positions[0][1], newest.size[1], where["work"])
        step = away * (newest.size[1] + spacing)
        for card in self.cards:
            if (card.pushed_out and not card.moved_out and card.motion.phase == "exit"
                    and card.motion.position is not None):
                x, y = card.motion.position
                card.motion.move_to(now, (x, y + step))
                card.moved_out = True

    def _complete(self, notice, shown):
        """End one notice, off this thread: the host raises its history copy or its toast."""
        callback = self.on_complete
        if callback is None:
            return
        self.worker(self._quietly, callback, notice, shown is True)

    def _end(self, card, shown):
        """End a card's notice, the first time only: whatever happens to the card afterwards,
        its notice has gone out by one route."""
        if card.ended:
            return
        card.ended = True
        self._complete(card.notice, shown)

    def _quietly(self, callback, *values):
        try:
            callback(*values)
        except Exception as exc:
            self.log("notification card callback failed (%s)" % type(exc).__name__)

    def _drop(self, card):
        if card in self.cards:
            self.cards.remove(card)
        card.close()
        if not self.cards:
            self._release_gdiplus()

    # ---- time
    def _tick(self):
        now = self.clock()
        for card in list(self.cards):
            card.motion.frame(now)
            if card.motion.gone:
                # Seen, or replaced by a newer card about the same conversation: its silent copy.
                # Pushed out of the stack before it was ever seen whole: today's toast instead.
                self._end(card, card.seen or card.superseded)
                self._drop(card)
                continue
            try:
                card.present(now)
            except Exception as exc:
                self.log("notification card frame failed (%s)" % type(exc).__name__)
                self._end(card, False)               # never seen whole: today's toast instead
                self._drop(card)
                continue
            if card.seen:
                self._end(card, True)                # seen: now its silent copy for the history
        self._sync_hover(now)
        self._schedule(now)

    def _sync_hover(self, now):
        """Hold every card while the pointer is over any of them, and only then. A card that
        goes away under the pointer (it was clicked) never hears the pointer leave, so this is
        asked again whenever the stack changes, not only when a card says so."""
        hovered = any(card.tracking for card in self.cards)
        if hovered != self._hovered:
            self._hovered = hovered
            for card in self.cards:
                card.motion.pause(now, hovered)

    def _schedule(self, now):
        if not self.hwnd:
            return
        user32 = _dll("user32")
        moving = any(card.motion.moving(now) for card in self.cards)
        if moving and not self._frame_running:
            user32.SetTimer(self.hwnd, TIMER_FRAME, notice_card.FRAME_MS, None)
            self._frame_running = True
        elif not moving and self._frame_running:
            user32.KillTimer(self.hwnd, TIMER_FRAME)
            self._frame_running = False
        user32.KillTimer(self.hwnd, TIMER_WAIT)
        if not moving:
            waits = [wait for wait in (card.motion.wait_ms(now) for card in self.cards) if wait is not None]
            if waits:
                user32.SetTimer(self.hwnd, TIMER_WAIT, max(1, int(min(waits)) + 1), None)

    # ---- the pointer
    def _hover(self, card, target):
        if target != card.hover:
            card.hover = target
            card.redraw()
        self._sync_hover(self.clock())
        self._tick()

    def _click(self, card, target):
        now = self.clock()
        if target is not None:
            index = target[1]
            actions = card.vm["actions"]
            if 0 <= index < len(actions) and self.on_action is not None:
                self.worker(self._quietly, self.on_action, actions[index]["uri"])
        card.seen = True                                 # somebody pointed at it and clicked
        card.motion.retire(now)
        self._tick()

    # ---- messages
    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            handled = self._handle(hwnd, message, wparam, lparam)
            if handled is not None:
                return handled
        except Exception as exc:                  # a card must never take the watcher down
            self.log("notification card message failed (%s)" % type(exc).__name__)
        return _dll("user32").DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        if hwnd == self.hwnd:
            if message == WM_NOTICE:
                for notice in (self.inbox.take() if self.inbox is not None else []):
                    try:
                        self.show(notice)               # ends the notice itself if it cannot draw it
                    except Exception as exc:            # admitted by then: its card ends it later
                        self.log("notification card failed (%s)" % type(exc).__name__)
                return 0
            if message == WM_TIMER:
                if wparam == TIMER_WAIT:
                    user32.KillTimer(hwnd, TIMER_WAIT)
                self._tick()
                return 0
            return None
        card = self.windows.get(hwnd)
        if card is None or hwnd != (card.body.hwnd if card.body else None):
            if message == WM_MOUSEACTIVATE:
                return MA_NOACTIVATE
            return None
        if message == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE                  # clicking a card never activates it
        if message == WM_MOUSEMOVE:
            if not card.tracking:
                track = TRACKMOUSEEVENT()
                track.cbSize = C.sizeof(TRACKMOUSEEVENT)
                track.dwFlags = TME_LEAVE
                track.hwndTrack = hwnd
                card.tracking = bool(user32.TrackMouseEvent(C.byref(track)))
            self._hover(card, card.hit(lparam))
            return 0
        if message == WM_MOUSELEAVE:
            card.tracking = False
            card.pressed = None
            self._hover(card, None)
            return 0
        if message == WM_LBUTTONDOWN:
            card.pressed = card.hit(lparam)
            if card.pressed is not None:
                card.redraw()
                self._tick()
            return 0
        if message == WM_LBUTTONUP:
            target, pressed = card.hit(lparam), card.pressed
            card.pressed = None
            if target is not None and target == pressed:
                self._click(card, target)
            elif target is None and pressed is None:
                self._click(card, None)           # a click on the card itself puts it away
            else:
                card.redraw()
                self._tick()
            return 0
        if message == WM_RBUTTONUP:
            self._click(card, None)
            return 0
        return None
