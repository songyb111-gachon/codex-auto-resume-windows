"""One card: its shadow, its body, its breathing light, and where a click lands on it.
"""
from __future__ import annotations

import ctypes as C

from ... import brand
from ... import notice_card
from .. import popup
from . import win32
from .win32 import INTERPOLATION_HIGH_QUALITY_BILINEAR, UNIT_PIXEL, WS_EX_LAYERED, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP, _declare  # noqa: F401
from .surfaces import _CardRenderer, _Image, _Layer, _Surface  # noqa: F401

class Card:
    """One notice on screen: its view, its drawn image, its two windows and its motion."""

    def __init__(self, stack, notice, *, now_ms, where, drawn, windows=True):
        _declare()
        self.stack = stack
        self.notice = notice
        self.vm = notice_card.view(notice)
        self.edge, self.born, self._breathed = "bottom", now_ms, now_ms
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
    def _glow(self, now_ms):
        """The light for `now_ms`: its own moment, counted from when the card came."""
        age = 0.0 if now_ms is None else now_ms - self.born
        return None if self.contrast else brand.glow(self.vm["status"], age, age, reduced=self.motion.reduced)

    def _draw_card(self, now_ms=None):
        if self.renderer is None:
            self.renderer = _CardRenderer()
            self.renderer.theme, self.renderer.contrast = self.theme, self.contrast
        self.renderer.use(self.vm["locale"], self.scale)
        self.plan = notice_card.layout(self.vm, self.scale, self.renderer.measure)
        canvas = self.renderer.draw(self.vm, self.plan, frame=self._glow(now_ms), hover=self.hover,
                                    pressed=self.pressed)
        width, height = self.plan["size"]
        pixels = notice_card.premultiply(canvas.pixels(), width, height,
                                         brand.RADII["card"] * self.scale)
        if self.image is not None:
            self.image.close()
        self.image = _Image(pixels, width, height)
        self._drawn_scale = None

    def _draw_light(self, now_ms):
        """Only the status light, for a breath (v0.6.10), as the popup draws its own: the renderer draws
        the light's band again over the face as it was last drawn, and the band alone is cut and copied
        into the card's image - and into its layer too, when the card is settled and the layer already
        holds the rest. Until v0.6.10 every breath drew the whole card and cut all of it."""
        canvas = self.renderer.draw_halo(self.plan, self._glow(now_ms))
        top, bottom = self.renderer.halo_rows
        width, height = self.plan["size"]
        row = width * 4
        win32._dll("gdi32").GdiFlush()
        band = notice_card.premultiply(C.string_at(canvas.bits.value + top * row, (bottom - top) * row),
                                       width, height, brand.RADII["card"] * self.scale, top)
        self.image._pixels[top * row:bottom * row] = band
        layer = self.body
        if (self._drawn_scale is not None and self._drawn_scale >= 0.9999 and layer is not None
                and layer.bits and (layer.width, layer.height) == (width, height)):
            C.memmove(layer.bits.value + top * row, C.addressof(self.image._memory) + top * row, len(band))
        else:
            self._drawn_scale = None

    @property
    def size(self):
        return self.plan["size"]

    def _create_windows(self):
        user32, stack = win32._dll("user32"), self.stack
        width, height = self.size
        with popup._PerMonitorDpi():
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
        """The pointer moved onto or off a button, or pressed one: draw the face again, with the light
        where its breath last was rather than back at the top of it."""
        self._draw_card(self._breathed)
        self._pushed = None

    def breathe(self, now_ms) -> bool:
        """Whether the status light moves now. Its band alone is drawn again for it (_draw_light), once
        a breath's frame has passed: on every tick of the stack's timer while only lights move, which
        runs at the popup's rate then, and on every other one while another card moves. Less one motion
        frame, so a tick that lands a little early is not left for the next. The stack asks only while
        this card stands still."""
        if self.contrast or not brand.glow_moves(self.vm["status"], now_ms - self.born, reduced=self.motion.reduced):
            return False
        if now_ms - self._breathed >= notice_card.BREATH_FRAME_MS - notice_card.FRAME_MS:
            self._draw_light(now_ms)
            self._pushed, self._breathed = None, now_ms
        return True

    # ---- a frame
    def _paint_body(self, scale):
        if self._drawn_scale == scale:
            return
        layer, image = self.body, self.image
        if scale >= 0.9999:
            win32._dll("gdi32").GdiFlush()
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
                mask = popup.lift_coverage(width, height, radius, shadow.blur * self.scale)
                images.append(popup._ShadowImage(mask, brand.rgb(shadow.colour), shadow.alpha))
            self._shadow_images[level] = images
        with _Surface(layer) as surface:
            surface.gp.GdipSetInterpolationMode(surface.graphics, 5)        # nearest: stretched middles stay exact
            for shadow, image in zip(reversed(placed), reversed(images)):
                extent = image.extent
                image.stamp(surface, self.margin - extent + popup.shadow_step(shadow.dx * self.scale),
                            self.margin - extent + popup.shadow_step(shadow.dy * self.scale),
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
        return popup.hit_test(self.plan["targets"], x, y) if self.plan else None

    def close(self):
        user32 = win32._dll("user32")
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
