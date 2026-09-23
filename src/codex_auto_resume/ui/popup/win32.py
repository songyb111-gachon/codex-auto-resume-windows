"""The Win32 this popup calls: the numbers, the structures, and one declaration pass.

`_declare()` sets the argument types for every function used here, under a lock, once per
process. The handles come from `win.library()`, so nothing declared here reaches another
module - which is the whole reason that helper hands back a cache of its own.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
import os
import threading
from ... import win
from ...win.dll import GUID, LRESULT, WNDCLASSW


WM_ACTIVATE, WM_PAINT, WM_CLOSE, WM_ERASEBKGND = 0x0006, 0x000F, 0x0010, 0x0014


WM_SYSCOLORCHANGE, WM_SETTINGCHANGE, WM_KEYDOWN, WM_TIMER = 0x0015, 0x001A, 0x0100, 0x0113


WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSELEAVE = 0x0200, 0x0201, 0x0202, 0x02A3


WM_DPICHANGED = 0x02E0


WM_APP = 0x8000


WM_POPUP_RESULT = WM_APP + 2


WM_POPUP_STRINGS = WM_APP + 3


WA_INACTIVE = 0


VK_TAB, VK_RETURN, VK_SHIFT, VK_ESCAPE, VK_SPACE = 0x09, 0x0D, 0x10, 0x1B, 0x20


VK_UP, VK_DOWN = 0x26, 0x28


KEY_WAS_DOWN = 1 << 30                  # WM_KEYDOWN lParam: the key was already down (auto-repeat)


WS_POPUP = 0x80000000


WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080


CS_DROPSHADOW = 0x00020000


SW_HIDE, SW_SHOWNOACTIVATE, SW_SHOW = 0, 4, 5


SWP_NOACTIVATE = 0x0010


HWND_TOPMOST = -1


IDC_ARROW = 32512


MONITOR_DEFAULTTONEAREST = 2


TME_LEAVE = 0x2


SPI_GETCLIENTAREAANIMATION = 0x1042


SPI_GETHIGHCONTRAST, HCF_HIGHCONTRASTON = 0x0042, 0x1


SPI_GETNONCLIENTMETRICS = 0x0029


DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2


# Windows 11 draws a hairline round a rounded popup in the app mode's colour unless told the
# window is dark; 20 since Windows 10 20H1, 19 on the builds before it.
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 20, 19


HKEY_CURRENT_USER, RRF_RT_REG_DWORD = 0x80000001, 0x00000010


DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4


DT_CENTER, DT_VCENTER, DT_WORDBREAK, DT_SINGLELINE = 0x1, 0x4, 0x10, 0x20


DT_CALCRECT, DT_NOPREFIX, DT_EDITCONTROL, DT_END_ELLIPSIS = 0x400, 0x800, 0x2000, 0x8000


TIMER_TICK, TIMER_FRAME, TIMER_FIRST = 1, 2, 3


GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1


def _pack(rgb, alpha=1.0) -> int:
    """(red, green, blue) and an alpha as the ARGB number GDI+ takes."""
    red, green, blue = rgb
    return (max(0, min(255, int(round(alpha * 255)))) << 24) | (red << 16) | (green << 8) | blue


_DECLARED = False


_DECLARE_LOCK = threading.Lock()


_dll = win.library()      # handles of this module's own


if os.name == "nt":
    class MONITORINFO(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]

    class PAINTSTRUCT(C.Structure):
        _fields_ = [("hdc", W.HDC), ("fErase", W.BOOL), ("rcPaint", W.RECT), ("fRestore", W.BOOL),
                    ("fIncUpdate", W.BOOL), ("rgbReserved", C.c_ubyte * 32)]

    class TRACKMOUSEEVENT(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("dwFlags", W.DWORD), ("hwndTrack", W.HWND), ("dwHoverTime", W.DWORD)]

    class BITMAPINFOHEADER(C.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                    ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                    ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]

    class BITMAPINFO(C.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]

    class BITMAP(C.Structure):
        _fields_ = [("bmType", W.LONG), ("bmWidth", W.LONG), ("bmHeight", W.LONG), ("bmWidthBytes", W.LONG),
                    ("bmPlanes", W.WORD), ("bmBitsPixel", W.WORD), ("bmBits", C.c_void_p)]

    class ICONINFO(C.Structure):
        _fields_ = [("fIcon", W.BOOL), ("xHotspot", W.DWORD), ("yHotspot", W.DWORD),
                    ("hbmMask", W.HBITMAP), ("hbmColor", W.HBITMAP)]

    class NOTIFYICONIDENTIFIER(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("guidItem", GUID)]

    class GdiplusStartupInput(C.Structure):
        _fields_ = [("GdiplusVersion", C.c_uint32), ("DebugEventCallback", C.c_void_p),
                    ("SuppressBackgroundThread", W.BOOL), ("SuppressExternalCodecs", W.BOOL)]

    class PointF(C.Structure):
        _fields_ = [("X", C.c_float), ("Y", C.c_float)]

    class HIGHCONTRASTW(C.Structure):
        _fields_ = [("cbSize", W.UINT), ("dwFlags", W.DWORD), ("lpszDefaultScheme", W.LPWSTR)]

    class LOGFONTW(C.Structure):
        _fields_ = [("lfHeight", W.LONG), ("lfWidth", W.LONG), ("lfEscapement", W.LONG),
                    ("lfOrientation", W.LONG), ("lfWeight", W.LONG), ("lfItalic", W.BYTE),
                    ("lfUnderline", W.BYTE), ("lfStrikeOut", W.BYTE), ("lfCharSet", W.BYTE),
                    ("lfOutPrecision", W.BYTE), ("lfClipPrecision", W.BYTE), ("lfQuality", W.BYTE),
                    ("lfPitchAndFamily", W.BYTE), ("lfFaceName", W.WCHAR * 32)]

    class NONCLIENTMETRICSW(C.Structure):
        _fields_ = [("cbSize", W.UINT), ("iBorderWidth", C.c_int), ("iScrollWidth", C.c_int),
                    ("iScrollHeight", C.c_int), ("iCaptionWidth", C.c_int), ("iCaptionHeight", C.c_int),
                    ("lfCaptionFont", LOGFONTW), ("iSmCaptionWidth", C.c_int), ("iSmCaptionHeight", C.c_int),
                    ("lfSmCaptionFont", LOGFONTW), ("iMenuWidth", C.c_int), ("iMenuHeight", C.c_int),
                    ("lfMenuFont", LOGFONTW), ("lfStatusFont", LOGFONTW), ("lfMessageFont", LOGFONTW),
                    ("iPaddedBorderWidth", C.c_int)]


def _signature(function, result, *arguments):
    function.restype = result
    function.argtypes = list(arguments)


def _declare():
    """Argument and result types for every call below, once. Handles are pointers: a
    64-bit handle returned through ctypes' default `int` would be silently cut in half."""
    global _DECLARED
    with _DECLARE_LOCK:
        if _DECLARED:
            return
        H, F, I, U, D = C.c_void_p, C.c_float, C.c_int, W.UINT, W.DWORD
        user32, gdi32, kernel32, gdiplus = _dll("user32"), _dll("gdi32"), _dll("kernel32"), _dll("gdiplus")
        _signature(user32.CreateWindowExW, H, D, W.LPCWSTR, W.LPCWSTR, D, I, I, I, I, H, H, H, H)
        _signature(user32.DefWindowProcW, LRESULT, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.RegisterClassW, W.ATOM, C.POINTER(WNDCLASSW))
        _signature(user32.UnregisterClassW, W.BOOL, W.LPCWSTR, H)
        _signature(user32.DestroyWindow, W.BOOL, H)
        _signature(user32.ShowWindow, W.BOOL, H, I)
        _signature(user32.SetWindowPos, W.BOOL, H, H, I, I, I, I, U)
        _signature(user32.SetForegroundWindow, W.BOOL, H)
        _signature(user32.SetFocus, H, H)
        _signature(user32.InvalidateRect, W.BOOL, H, H, W.BOOL)
        _signature(user32.UpdateWindow, W.BOOL, H)
        _signature(user32.BeginPaint, H, H, C.POINTER(PAINTSTRUCT))
        _signature(user32.EndPaint, W.BOOL, H, C.POINTER(PAINTSTRUCT))
        _signature(user32.SetTimer, C.c_size_t, H, C.c_size_t, U, H)
        _signature(user32.KillTimer, W.BOOL, H, C.c_size_t)
        _signature(user32.PostMessageW, W.BOOL, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.GetCursorPos, W.BOOL, C.POINTER(W.POINT))
        _signature(user32.MonitorFromRect, H, C.POINTER(W.RECT), D)
        _signature(user32.GetMonitorInfoW, W.BOOL, H, C.POINTER(MONITORINFO))
        _signature(user32.SystemParametersInfoW, W.BOOL, U, U, H, U)
        _signature(user32.GetKeyState, C.c_short, I)
        _signature(user32.TrackMouseEvent, W.BOOL, C.POINTER(TRACKMOUSEEVENT))
        _signature(user32.LoadCursorW, H, H, H)
        _signature(user32.SetWindowRgn, I, H, H, W.BOOL)
        _signature(user32.DrawTextW, I, H, W.LPCWSTR, I, C.POINTER(W.RECT), U)
        _signature(user32.GetIconInfo, W.BOOL, H, C.POINTER(ICONINFO))
        _signature(user32.CreateIconIndirect, H, C.POINTER(ICONINFO))
        _signature(user32.DestroyIcon, W.BOOL, H)
        _signature(user32.GetGuiResources, D, H, D)
        _signature(user32.GetSysColor, D, I)
        for name, result, arguments in (("GetDpiForWindow", U, (H,)),
                                        ("SetThreadDpiAwarenessContext", H, (H,))):
            function = getattr(user32, name, None)
            if function is not None:
                _signature(function, result, *arguments)
        _signature(gdi32.CreateCompatibleDC, H, H)
        _signature(gdi32.DeleteDC, W.BOOL, H)
        _signature(gdi32.CreateDIBSection, H, H, C.POINTER(BITMAPINFO), U, C.POINTER(C.c_void_p), H, D)
        _signature(gdi32.SelectObject, H, H, H)
        _signature(gdi32.DeleteObject, W.BOOL, H)
        _signature(gdi32.GetObjectW, I, H, I, H)
        _signature(gdi32.CreateFontW, H, I, I, I, I, I, D, D, D, D, D, D, D, D, W.LPCWSTR)
        _signature(gdi32.GetTextFaceW, I, H, I, W.LPWSTR)
        _signature(gdi32.SetTextColor, D, H, D)
        _signature(gdi32.SetBkMode, I, H, I)
        _signature(gdi32.SetDIBitsToDevice, I, H, I, I, D, D, I, I, U, U, H, C.POINTER(BITMAPINFO), U)
        _signature(gdi32.CreateRoundRectRgn, H, I, I, I, I, I, I)
        _signature(gdi32.GetDIBits, I, H, H, U, U, H, C.POINTER(BITMAPINFO), U)
        _signature(gdi32.CreateBitmap, H, I, I, U, U, H)
        _signature(_dll("advapi32").RegGetValueW, C.c_long, H, W.LPCWSTR, W.LPCWSTR, D, H,
                   C.POINTER(W.DWORD), C.POINTER(W.DWORD))
        _signature(kernel32.GetModuleHandleW, H, W.LPCWSTR)
        _signature(kernel32.GetCurrentProcess, H)
        _signature(gdiplus.GdiplusStartup, I, C.POINTER(C.c_size_t), C.POINTER(GdiplusStartupInput), H)
        _signature(gdiplus.GdiplusShutdown, None, C.c_size_t)
        _signature(gdi32.GdiFlush, W.BOOL)
        _signature(gdiplus.GdipCreateBitmapFromScan0, I, I, I, I, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipGetImageGraphicsContext, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDisposeImage, I, H)
        _signature(gdiplus.GdipDeleteGraphics, I, H)
        _signature(gdiplus.GdipSetSmoothingMode, I, H, I)
        _signature(gdiplus.GdipSetPixelOffsetMode, I, H, I)
        _signature(gdiplus.GdipCreateSolidFill, I, D, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeleteBrush, I, H)
        _signature(gdiplus.GdipCreatePen1, I, D, F, I, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeletePen, I, H)
        _signature(gdiplus.GdipSetPenStartCap, I, H, I)
        _signature(gdiplus.GdipSetPenEndCap, I, H, I)
        _signature(gdiplus.GdipSetPenLineJoin, I, H, I)
        _signature(gdiplus.GdipCreatePath, I, I, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeletePath, I, H)
        _signature(gdiplus.GdipAddPathArc, I, H, F, F, F, F, F, F)
        _signature(gdiplus.GdipAddPathRectangle, I, H, F, F, F, F)
        _signature(gdiplus.GdipClosePathFigure, I, H)
        _signature(gdiplus.GdipFillPath, I, H, H, H)
        _signature(gdiplus.GdipDrawPath, I, H, H, H)
        _signature(gdiplus.GdipFillEllipse, I, H, H, F, F, F, F)
        _signature(gdiplus.GdipDrawArc, I, H, H, F, F, F, F, F, F)
        _signature(gdiplus.GdipDrawLines, I, H, H, C.POINTER(PointF), I)
        _signature(gdiplus.GdipAddPathEllipse, I, H, F, F, F, F)
        _signature(gdiplus.GdipCreatePathGradientFromPath, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipSetPathGradientCenterPoint, I, H, C.POINTER(PointF))
        _signature(gdiplus.GdipSetPathGradientPresetBlend, I, H, C.POINTER(C.c_uint32), C.POINTER(F), I)
        _signature(gdiplus.GdipSetInterpolationMode, I, H, I)
        _signature(gdiplus.GdipDrawImageRectRectI, I, H, H, I, I, I, I, I, I, I, I, I, H, H, H)
        _DECLARED = True


class _PerMonitorDpi:
    """Per-monitor-v2 coordinates for this thread while inside, restored afterwards."""

    def __enter__(self):
        self.previous = None
        function = getattr(_dll("user32"), "SetThreadDpiAwarenessContext", None)
        if function is not None:
            self.previous = function(C.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        return self

    def __exit__(self, *unused):
        function = getattr(_dll("user32"), "SetThreadDpiAwarenessContext", None)
        if function is not None and self.previous:
            function(C.c_void_p(self.previous))


def gui_resources() -> tuple:
    """(GDI objects, USER objects) this process holds, for the leak tests."""
    _declare()
    user32, process = _dll("user32"), _dll("kernel32").GetCurrentProcess()
    return (user32.GetGuiResources(process, GR_GDIOBJECTS), user32.GetGuiResources(process, GR_USEROBJECTS))


def icon_rect(hwnd, uid=1):
    """The icon's rectangle on screen, or None (in the overflow flyout, or not yet placed)."""
    try:
        _declare()
        shell32 = _dll("shell32")
        _signature(shell32.Shell_NotifyIconGetRect, C.c_long, C.POINTER(NOTIFYICONIDENTIFIER), C.POINTER(W.RECT))
        identifier = NOTIFYICONIDENTIFIER()
        identifier.cbSize = C.sizeof(NOTIFYICONIDENTIFIER)
        identifier.hWnd = hwnd
        identifier.uID = uid
        rect = W.RECT()
        if shell32.Shell_NotifyIconGetRect(C.byref(identifier), C.byref(rect)) != 0:
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


UNIT_PIXEL, INTERPOLATION_NEAREST = 2, 5


def _bitmap_info(width, height):
    info = BITMAPINFO()
    info.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    return info


def _icon_from_pixels(pixels, width, height):
    user32, gdi32 = _dll("user32"), _dll("gdi32")
    bits = C.c_void_p()
    info = _bitmap_info(width, height)
    colour = gdi32.CreateDIBSection(None, C.byref(info), 0, C.byref(bits), None, 0)
    if not colour:
        return None
    rows = ((width + 15) // 16) * 2
    zeros = (C.c_ubyte * (rows * height))()
    mask = gdi32.CreateBitmap(width, height, 1, 1, zeros)
    try:
        if not mask:
            return None
        C.memmove(bits, bytes(pixels), len(pixels))
        icon_info = ICONINFO()
        icon_info.fIcon = True
        icon_info.hbmMask = mask
        icon_info.hbmColor = colour
        return user32.CreateIconIndirect(C.byref(icon_info)) or None
    finally:
        gdi32.DeleteObject(colour)
        if mask:
            gdi32.DeleteObject(mask)
