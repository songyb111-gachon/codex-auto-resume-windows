"""The Win32 the card calls: its declarations, a handle cache of its own, and where the
taskbar and the screen are.
"""
from __future__ import annotations

import ctypes as C
import os
import threading

from ... import brand
from ... import notice_presence
from ... import win
from .. import popup

if os.name == "nt":
    from ctypes import wintypes as W
    from ...win.dll import LRESULT, WNDCLASSW, WNDPROC
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
# Compositing is GDI+'s high-speed blend, as the popup's painter blends: its high-quality one is
# gamma-corrected, and at 200% it made one entrance frame cost 35 ms instead of 9 - on the real
# screen the card sat faint for a tenth of a second and then jumped to full strength.
INTERPOLATION_HIGH_QUALITY_BILINEAR, PIXEL_OFFSET_HALF, COMPOSITING_HIGH_SPEED = 6, 4, 1
UNIT_PIXEL = 2

_DECLARED = False
_DECLARE_LOCK = threading.Lock()
# GDI+ objects this module makes itself (the popup's renderer and shadow images count their own
# in popup.gdiplus_objects): the leak tests read both.


_dll = win.library()      # handles of this module's own


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
    with popup._PerMonitorDpi():
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
    """How cards are drawn now: theme, design, High Contrast and what may move.

    `reduced` is every stopper - Reduce motion, Windows' animation setting, High Contrast, battery saver.
    Since v0.6.10 the design splits what they stop in two (brand.light_moves, brand.controls_move): the
    light, held by `light_still`, and the card's own entrance, exit and slide, held by `controls_still`.
    """
    contrast = popup.high_contrast()
    theme = popup.effective_theme(popup.theme_setting(), popup.apps_use_light_theme())
    design = popup.design_setting()
    reduced = bool(popup.reduced_motion() or contrast or notice_presence.battery_saver())
    return {"theme": theme, "design": design, "contrast": contrast, "reduced": reduced,
            "light_still": not brand.light_moves(design, stopped=reduced),
            "controls_still": not brand.controls_move(design, stopped=reduced)}


# ------------------------------------------------------------------------ one layered window
