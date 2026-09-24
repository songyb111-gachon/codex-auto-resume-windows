"""GDI+: the surfaces drawn on, and the counting that proves nothing leaks.

Every object made here is counted in and out, and `tests/test_tray_popup.py` reads the count: a
popup that leaked one handle a frame would take the session down in an afternoon.
"""
from __future__ import annotations

import ctypes as C
import threading
from .win32 import (BITMAPINFO,
                    BITMAPINFOHEADER,
                    GdiplusStartupInput,
                    INTERPOLATION_NEAREST,
                    PointF,
                    UNIT_PIXEL,
                    _declare,
                    _dll,
                    _pack)


# GetGuiResources cannot see GDI+ objects, so this module counts its own: every image,
# graphics, brush, pen and path it makes, less every one it lets go. The leak tests read it.
_GDIPLUS_LIVE = {"objects": 0}


_GDIPLUS_LIVE_LOCK = threading.Lock()


def _gdiplus_made(count):
    with _GDIPLUS_LIVE_LOCK:
        _GDIPLUS_LIVE["objects"] += count


def gdiplus_objects() -> int:
    """How many GDI+ objects this module holds at this moment."""
    return _GDIPLUS_LIVE["objects"]


# ------------------------------------------------------------------------------ GDI+
_GDIPLUS = {"token": 0, "users": 0}


_GDIPLUS_LOCK = threading.Lock()


def _gdiplus_acquire():
    _declare()
    with _GDIPLUS_LOCK:
        if _GDIPLUS["users"] == 0:
            token = C.c_size_t(0)
            startup = GdiplusStartupInput(1, None, False, False)
            status = _dll("gdiplus").GdiplusStartup(C.byref(token), C.byref(startup), None)
            if status != 0:
                raise OSError("GdiplusStartup failed (%d)" % status)
            _GDIPLUS["token"] = token.value
        _GDIPLUS["users"] += 1


def _gdiplus_release():
    with _GDIPLUS_LOCK:
        if _GDIPLUS["users"] <= 0:
            return
        _GDIPLUS["users"] -= 1
        if _GDIPLUS["users"] == 0:
            _dll("gdiplus").GdiplusShutdown(_GDIPLUS["token"])
            _GDIPLUS["token"] = 0


PIXEL_FORMAT_32BPP_RGB = 0x00022009


PIXEL_FORMAT_32BPP_PARGB = 0x000E200B


class _Painter:
    """Antialiased shapes straight into a canvas's pixels, through the GDI+ flat API.

    GDI+ is pointed at the DIB's own memory rather than at its DC: drawing through a DC
    makes GDI+ compose every shape in a buffer of its own and copy it back, which at this
    window's size cost about a tenth of a second a frame. Every object is released, and
    counted in and out (`gdiplus_objects`).
    """

    def __init__(self, canvas):
        self.gp = _dll("gdiplus")
        self.bitmap = C.c_void_p()
        self.graphics = C.c_void_p()
        _dll("gdi32").GdiFlush()                               # GDI may still owe us text
        status = self.gp.GdipCreateBitmapFromScan0(canvas.width, canvas.height, canvas.width * 4,
                                                   PIXEL_FORMAT_32BPP_RGB, canvas.bits, C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        _gdiplus_made(1)
        status = self.gp.GdipGetImageGraphicsContext(self.bitmap, C.byref(self.graphics))
        if status != 0:
            self.gp.GdipDisposeImage(self.bitmap)
            _gdiplus_made(-1)
            raise OSError("GdipGetImageGraphicsContext failed (%d)" % status)
        _gdiplus_made(1)
        self.gp.GdipSetSmoothingMode(self.graphics, 4)         # antialias
        self.gp.GdipSetPixelOffsetMode(self.graphics, 4)       # half: edges land on pixel edges
        # A shadow image's one-pixel middle is stretched; nearest neighbour keeps it exact.
        self.gp.GdipSetInterpolationMode(self.graphics, INTERPOLATION_NEAREST)

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.gp.GdipDeleteGraphics(self.graphics)
        self.gp.GdipDisposeImage(self.bitmap)
        _gdiplus_made(-2)

    def _made(self, status, what):
        if status != 0:
            raise OSError("%s failed (%d)" % (what, status))
        _gdiplus_made(1)

    def _delete_path(self, path):
        self.gp.GdipDeletePath(path)
        _gdiplus_made(-1)

    def _delete_brush(self, brush):
        self.gp.GdipDeleteBrush(brush)
        _gdiplus_made(-1)

    def _delete_pen(self, pen):
        self.gp.GdipDeletePen(pen)
        _gdiplus_made(-1)

    def _brush(self, colour):
        brush = C.c_void_p()
        self._made(self.gp.GdipCreateSolidFill(colour, C.byref(brush)), "GdipCreateSolidFill")
        return brush

    def _path(self, rect, radius):
        left, top, right, bottom = (float(value) for value in rect)
        path = C.c_void_p()
        self._made(self.gp.GdipCreatePath(0, C.byref(path)), "GdipCreatePath")
        radius = max(0.0, min(float(radius), (right - left) / 2.0, (bottom - top) / 2.0))
        if radius <= 0.0:
            self.gp.GdipAddPathRectangle(path, left, top, right - left, bottom - top)
            return path
        d = radius * 2.0
        self.gp.GdipAddPathArc(path, left, top, d, d, 180.0, 90.0)
        self.gp.GdipAddPathArc(path, right - d, top, d, d, 270.0, 90.0)
        self.gp.GdipAddPathArc(path, right - d, bottom - d, d, d, 0.0, 90.0)
        self.gp.GdipAddPathArc(path, left, bottom - d, d, d, 90.0, 90.0)
        self.gp.GdipClosePathFigure(path)
        return path

    def _pen(self, colour, width):
        pen = C.c_void_p()
        self._made(self.gp.GdipCreatePen1(colour, float(width), 2, C.byref(pen)), "GdipCreatePen1")  # pixels
        self.gp.GdipSetPenStartCap(pen, 2)                                 # round
        self.gp.GdipSetPenEndCap(pen, 2)
        self.gp.GdipSetPenLineJoin(pen, 2)
        return pen

    def fill_round(self, rect, radius, colour):
        path = self._path(rect, radius)
        try:
            brush = self._brush(colour)
            try:
                self.gp.GdipFillPath(self.graphics, brush, path)
            finally:
                self._delete_brush(brush)
        finally:
            self._delete_path(path)

    def stroke_round(self, rect, radius, colour, width):
        half = width / 2.0
        inner = (rect[0] + half, rect[1] + half, rect[2] - half, rect[3] - half)
        path = self._path(inner, max(0.0, radius - half))
        try:
            pen = self._pen(colour, width)
            try:
                self.gp.GdipDrawPath(self.graphics, pen, path)
            finally:
                self._delete_pen(pen)
        finally:
            self._delete_path(path)

    def fill_circle(self, cx, cy, radius, colour):
        brush = self._brush(colour)
        try:
            self.gp.GdipFillEllipse(self.graphics, brush, float(cx - radius), float(cy - radius),
                                    float(radius * 2), float(radius * 2))
        finally:
            self._delete_brush(brush)

    def arc(self, cx, cy, radius, start, sweep, colour, width):
        pen = self._pen(colour, width)
        try:
            self.gp.GdipDrawArc(self.graphics, pen, float(cx - radius), float(cy - radius),
                                float(radius * 2), float(radius * 2), float(start), float(sweep))
        finally:
            self._delete_pen(pen)

    def glow(self, cx, cy, radius, stops, rgb, opacity):
        """A soft round light of `radius`: `rgb` at `opacity` times each stop's factor.

        `stops` are (fraction of the radius from the centre, factor) pairs, as brand.glow_stops
        gives them; between two stops the alpha runs in a straight line, and at the edge it is
        nothing, so the glow has no rim. A GDI+ path gradient counts its positions from the edge
        inward, so the stops are turned round.
        """
        if radius <= 0 or opacity <= 0:
            return
        path = C.c_void_p()
        self._made(self.gp.GdipCreatePath(0, C.byref(path)), "GdipCreatePath")
        try:
            self.gp.GdipAddPathEllipse(path, float(cx - radius), float(cy - radius),
                                       float(radius * 2), float(radius * 2))
            brush = C.c_void_p()
            self._made(self.gp.GdipCreatePathGradientFromPath(path, C.byref(brush)),
                       "GdipCreatePathGradientFromPath")
            try:
                centre = PointF(float(cx), float(cy))
                self.gp.GdipSetPathGradientCenterPoint(brush, C.byref(centre))
                turned = list(reversed(stops))
                colours = (C.c_uint32 * len(turned))(*[_pack(rgb, opacity * factor) for _, factor in turned])
                positions = (C.c_float * len(turned))(*[1.0 - fraction for fraction, _ in turned])
                self.gp.GdipSetPathGradientPresetBlend(brush, colours, positions, len(turned))
                self.gp.GdipFillPath(self.graphics, brush, path)
            finally:
                self._delete_brush(brush)
        finally:
            self._delete_path(path)


class _ShadowImage:
    """One shadow in its colour: a coverage mask as a premultiplied GDI+ image.

    The pixels are made with four table look-ups over the mask rather than a loop, and GDI+
    draws straight from that memory, so the memory lives exactly as long as the image.
    """

    def __init__(self, mask, rgb, strength):
        self.width, self.height = mask["width"], mask["height"]
        self.centre, self.extent = mask["centre"], mask["extent"]
        coverage = mask["coverage"]
        alpha = bytes(min(255, int(strength * level + 0.5)) for level in range(256))
        pixels = bytearray(4 * self.width * self.height)
        for offset, channel in enumerate((rgb[2], rgb[1], rgb[0])):
            pixels[offset::4] = coverage.translate(bytes(int(channel * value / 255.0 + 0.5) for value in alpha))
        pixels[3::4] = coverage.translate(alpha)
        self._pixels = pixels
        self._memory = (C.c_ubyte * len(pixels)).from_buffer(pixels)
        self.bitmap = C.c_void_p()
        status = _dll("gdiplus").GdipCreateBitmapFromScan0(self.width, self.height, self.width * 4,
                                                           PIXEL_FORMAT_32BPP_PARGB,
                                                           C.cast(self._memory, C.c_void_p), C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        _gdiplus_made(1)

    def close(self):
        if self.bitmap:
            _dll("gdiplus").GdipDisposeImage(self.bitmap)
            _gdiplus_made(-1)
            self.bitmap = C.c_void_p()

    def stamp(self, paint, left, top, width, height, middle=True):
        """Into (left, top, width, height): the corners as they are, the middle row and column stretched."""
        cx, cy = self.centre
        right, bottom = self.width - cx - 1, self.height - cy - 1
        columns = ((left, cx, 0), (left + cx, width - cx - right, cx), (left + width - right, right, cx + 1))
        rows = ((top, cy, 0), (top + cy, height - cy - bottom, cy), (top + height - bottom, bottom, cy + 1))
        for row, (y, tall, source_y) in enumerate(rows):
            for column, (x, wide, source_x) in enumerate(columns):
                if wide <= 0 or tall <= 0 or (row == column == 1 and not middle):
                    continue
                paint.gp.GdipDrawImageRectRectI(paint.graphics, self.bitmap, x, y, wide, tall, source_x, source_y,
                                                1 if column == 1 else wide, 1 if row == 1 else tall,
                                                UNIT_PIXEL, None, None, None)


class _Canvas:
    """A top-down 32-bpp DIB selected into a memory DC: the frame is built here, whole,
    and handed to the window in one call."""

    def __init__(self):
        self.dc = _dll("gdi32").CreateCompatibleDC(None)
        if not self.dc:
            raise OSError("CreateCompatibleDC")
        self.bitmap = None
        self.original = None
        self.bits = C.c_void_p()
        self.info = BITMAPINFO()
        self.width = self.height = 0

    def ensure(self, width, height):
        if self.bitmap and (width, height) == (self.width, self.height):
            return
        gdi32 = _dll("gdi32")
        info = BITMAPINFO()
        info.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = C.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.dc, C.byref(info), 0, C.byref(bits), None, 0)
        if not bitmap:
            raise OSError("CreateDIBSection")
        previous = gdi32.SelectObject(self.dc, bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        else:
            self.original = previous
        self.bitmap, self.bits, self.info, self.width, self.height = bitmap, bits, info, width, height

    def pixels(self) -> bytes:
        return C.string_at(self.bits, self.width * self.height * 4)

    def close(self):
        gdi32 = _dll("gdi32")
        if self.bitmap:
            gdi32.SelectObject(self.dc, self.original)
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None
