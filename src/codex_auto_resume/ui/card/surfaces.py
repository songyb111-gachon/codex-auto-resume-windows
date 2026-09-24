"""What the card is drawn into: the layered bitmap, the GDI+ surfaces and images, and the
count of GDI+ objects alive, which the leak tests read.
"""
from __future__ import annotations

import ctypes as C
import os
import threading

from ... import brand
from .. import popup
from . import win32
from .win32 import AC_SRC_ALPHA, AC_SRC_OVER, BITMAPINFO, BITMAPINFOHEADER, BLENDFUNCTION, COMPOSITING_HIGH_SPEED, HWND_TOPMOST, PIXEL_FORMAT_32BPP_PARGB, PIXEL_OFFSET_HALF, SIZE, SWP_NOACTIVATE, SWP_NOMOVE, SWP_NOSIZE, SW_SHOWNOACTIVATE, ULW_ALPHA, W  # noqa: F401

_LIVE = {"objects": 0}
_LIVE_LOCK = threading.Lock()


def _made(count):
    with _LIVE_LOCK:
        _LIVE["objects"] += count


def gdiplus_objects() -> int:
    return _LIVE["objects"]


class _Layer:
    """A layered window and the premultiplied 32-bit DIB it is updated from."""

    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.dc = win32._dll("gdi32").CreateCompatibleDC(None)
        if not self.dc:
            raise OSError("CreateCompatibleDC")
        self.bitmap = self.original = None
        self.bits = C.c_void_p()
        self.width = self.height = 0
        self.shown = False

    def ensure(self, width, height):
        if self.bitmap and (width, height) == (self.width, self.height):
            return
        gdi32 = win32._dll("gdi32")
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
        win32._dll("gdi32").GdiFlush()
        C.memset(self.bits, 0, self.width * self.height * 4)

    def pixels(self) -> bytes:
        win32._dll("gdi32").GdiFlush()
        return C.string_at(self.bits, self.width * self.height * 4)

    def push(self, x, y, alpha):
        """Put the DIB on screen at (x, y) with the whole window at `alpha` (0-1)."""
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(round(alpha * 255)))), AC_SRC_ALPHA)
        with popup._PerMonitorDpi():
            ok = win32._dll("user32").UpdateLayeredWindow(self.hwnd, None, C.byref(W.POINT(int(x), int(y))),
                                                    C.byref(SIZE(self.width, self.height)), self.dc,
                                                    C.byref(W.POINT(0, 0)), 0, C.byref(blend), ULW_ALPHA)
            if ok and not self.shown:
                win32._dll("user32").SetWindowPos(self.hwnd, C.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                            SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE)
                win32._dll("user32").ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
                self.shown = True
        return bool(ok)

    def close(self):
        gdi32 = win32._dll("gdi32")
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
        self.gp = win32._dll("gdiplus")
        self.bitmap, self.graphics = C.c_void_p(), C.c_void_p()
        win32._dll("gdi32").GdiFlush()
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
        self.gp.GdipSetCompositingQuality(self.graphics, COMPOSITING_HIGH_SPEED)

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
        status = win32._dll("gdiplus").GdipCreateBitmapFromScan0(width, height, width * 4, PIXEL_FORMAT_32BPP_PARGB,
                                                           C.cast(self._memory, C.c_void_p), C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        _made(1)

    def close(self):
        if self.bitmap:
            win32._dll("gdiplus").GdipDisposeImage(self.bitmap)
            _made(-1)
            self.bitmap = C.c_void_p()


# ------------------------------------------------------------------------------ one card
class _CardRenderer(popup.Renderer if os.name == "nt" else object):
    """The popup's renderer, and brand's own fill for a light the popup never shows.

    The popup's six states have their fills in `popup.DOT_FILL`; a card can also say that
    an attempt failed, which brand draws in `danger` (brand.STATUS_FILL). Everything else - the
    dot's dimming, the glow's falloff and its size, High Contrast's system colour - is the
    popup's own drawing.
    """

    def _halo(self, paint, item, scale, frame):
        state = item["state"]
        if self.contrast or state in popup.DOT_FILL:
            return super()._halo(paint, item, scale, frame)
        self._light(paint, item["cx"], item["cy"], brand.STATUS_DOT["popup"], scale,
                    brand.status_fill(state), frame)
        return None
