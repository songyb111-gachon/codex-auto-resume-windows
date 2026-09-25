"""Drawing the popup into memory.

One pass over the layout, into a bitmap that the window below hands to Windows. The renderer
asks Windows nothing, which is why the same drawing makes the documentation's pictures with no
screen at all.
"""
from __future__ import annotations

from ctypes import wintypes as W
import ctypes as C
import math
from ... import brand
from .elevation import lift_coverage, recipe_shadows, shadow_step, tile_ground, well_coverage
from .fonts import _Fonts
from .gdiplus import _Canvas, _Painter, _ShadowImage, _gdiplus_acquire, _gdiplus_release
from .layout import layout as plan            # the method below shares its name
from .theme import SYSTEM_COLOURS, contrast_colour, system_rgb
from .win32 import (DT_CALCRECT,
                    DT_CENTER,
                    DT_EDITCONTROL,
                    DT_END_ELLIPSIS,
                    DT_NOPREFIX,
                    DT_SINGLELINE,
                    DT_VCENTER,
                    DT_WORDBREAK,
                    _declare,
                    _dll,
                    _pack)


# What each state is drawn with. Fill tokens for the dot, text tokens for its word: `active`
# is fill-only and never carries text, which is why the two tables are separate. The dot is
# brand's status light, as in the window and the panel: every state in which the watcher runs
# with recovery on is the `active` cyan it had before v0.6.3, a pause keeps its grey, and a
# problem is amber. The word beside it, and its glow, tell the running states apart. Keyed by
# light, not by word: brand's own table, so a watcher not known to be running is `idle` grey
# (v0.6.10), which no word is.
DOT_FILL = dict(brand.STATUS_FILL)


# A reason chip's text colour; its ground is that colour mixed CHIP_ALPHA of the way into the
# card's surface, as the panel mixes it, whatever the chip sits on.
CHIP_ALPHA = 0.12


# Languages whose lines break between words only, where GDI would break inside a word.
_BREAK_AT_SPACES = frozenset({"ko"})


class Renderer:
    """Draws a view model into its own canvas. Owns every GDI and GDI+ object it makes."""

    def __init__(self):
        _declare()
        _gdiplus_acquire()
        try:
            self.canvas = _Canvas()
        except Exception:
            _gdiplus_release()
            raise
        self.fonts = None
        self.contrast = False            # High Contrast: system colours, and no shadow, tint or glow
        self.theme = "light"             # v0.6.4: "light" or "dark", as the window resolved it
        self._images = {}                # this scale and theme's shadow images, by shape, theme, colour, strength
        self._images_look = None
        self._ground_key = None
        self._ground_pixels = None
        self._halo_band = None
        self._halo_plan = None

    def close(self):
        self._drop_images()
        if self.fonts is not None:
            self.fonts.close()
            self.fonts = None
        if self.canvas is not None:
            self.canvas.close()
            self.canvas = None
            _gdiplus_release()

    def use(self, locale, scale):
        if self.fonts is None or self.fonts.key != (locale, scale):
            if self.fonts is not None:
                self.fonts.close()
                self.fonts = None
            self.fonts = _Fonts(self.canvas.dc, locale, scale)

    def lines(self, role, text, width):
        """Text as it will wrap, with the breaks made explicit where GDI's would be wrong.

        GDI breaks Korean between any two syllables, and Korean is set with breaks between
        words only. So Korean is broken here, at spaces, measured by GDI itself; a single
        word wider than the whole line is the one case left to GDI.
        """
        if not text or self.fonts is None or self.fonts.key[0] not in _BREAK_AT_SPACES:
            return text
        lines, line = [], ""
        for word in text.split(" "):
            candidate = word if not line else line + " " + word
            if not line or self.measure(role, candidate, width, False)[0] <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if any(self.measure(role, entry, width, False)[0] > width for entry in lines):
            return text
        return "\n".join(lines)

    def measure(self, role, text, width, wrap):
        if wrap:
            text = self.lines(role, text, width)
        gdi32, user32 = _dll("gdi32"), _dll("user32")
        dc = self.canvas.dc
        previous = gdi32.SelectObject(dc, self.fonts.handles[role])
        try:
            rect = W.RECT(0, 0, max(1, int(width)), 0)
            flags = DT_CALCRECT | DT_NOPREFIX | ((DT_WORDBREAK | DT_EDITCONTROL) if wrap else DT_SINGLELINE)
            user32.DrawTextW(dc, text or " ", -1, C.byref(rect), flags)
            return rect.right - rect.left, rect.bottom - rect.top
        finally:
            gdi32.SelectObject(dc, previous)

    def layout(self, vm, scale, locale):
        self.use(locale, scale)
        return plan(vm, scale, self.measure)

    def draw(self, vm, plan, *, frame=None, hover=None, pressed=None, focus=None, glides=None):
        """One whole frame into the canvas. Returns the canvas.

        `glides` is {switch target: how far on, 0 to 1} for the switches part way through a
        glide: those are left out of the cached ground and drawn over it where they are now.
        """
        width, height = plan["size"]
        scale = plan["scale"]
        canvas = self.canvas
        canvas.ensure(width, height)
        glides = glides or {}
        self._ground(plan, pressed, glides)
        busy = {item["target"] for item in plan["items"] if item.get("busy")}
        with _Painter(canvas) as paint:
            for item in plan["items"]:
                if item["kind"] == "button":
                    self._button(paint, item, scale, hover, pressed)
                elif item["kind"] == "switch" and item["target"] in glides:
                    self._switch(paint, item, scale, on=glides[item["target"]])
        self._text(canvas.dc, plan, busy)
        if focus is not None:
            with _Painter(canvas) as paint:
                for item in plan["items"]:
                    if item["kind"] == "focusable" and item["target"] == focus:
                        ring = max(2.0, 2.0 * scale)
                        grow = ring + max(1.0, scale)
                        rect = item["rect"]
                        paint.stroke_round((rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow),
                                           item["radius"] + grow, self._argb("focus"), ring)
        self._keep_halo_band(plan)
        return self.draw_halo(plan, frame, restore=False)

    def draw_halo(self, plan, frame, *, restore=True):
        """Only the halo, for an animation frame; everything else in the canvas is kept.

        The band of rows behind the halo was saved when the whole frame was drawn, so a
        frame is one memory copy and two antialiased circles rather than the whole window.
        """
        item = next((entry for entry in plan["items"] if entry["kind"] == "halo"), None)
        if item is None:
            return self.canvas
        if restore:
            if self._halo_plan is not plan or self._halo_band is None:
                raise ValueError("the whole frame has to be drawn before its halo")
            offset, band = self._halo_band
            C.memmove(self.canvas.bits.value + offset, band, len(band))
        with _Painter(self.canvas) as paint:
            self._halo(paint, item, plan["scale"], frame)
        return self.canvas

    @property
    def halo_plan(self):
        return self._halo_plan

    # ------------------------------------------------------------------ colours
    def _theme(self):
        """The theme the colours come from: brand's name for it, and light for anything unknown."""
        return self.theme if self.theme in brand.THEMES else "light"

    def _tokens(self):
        return brand.palette(self._theme())

    def _rgb(self, token):
        if self.contrast:
            return system_rgb(contrast_colour(token))
        return brand.rgb(self._tokens()[token])

    def _argb(self, token, alpha=1.0):
        return _pack(self._rgb(token), alpha)

    def _colorref(self, token):
        red, green, blue = self._rgb(token)
        return red | (green << 8) | (blue << 16)

    def _system_key(self):
        """What the ground's colours depend on besides the tokens: the system colours, in High Contrast."""
        return tuple(system_rgb(name) for name in sorted(SYSTEM_COLOURS)) if self.contrast else None

    # ------------------------------------------------------------------ the ground
    @staticmethod
    def _lifted(item, pressed):
        """A button stands on the card unless it is pressed or busy."""
        return not item["busy"] and pressed != item["target"]

    def _ground(self, plan, pressed, glides=()):
        """Everything but the text, the buttons' faces and the halo: drawn once, then copied.

        The canvas, the card and its lift, the task rows, rules, chips, notes and switches, and
        the lift under each button. None of it changes on a one-second tick, so a tick costs a
        memory copy; hovering changes only a face. A press takes a button's lift away, so a
        press is part of the key, and so is the theme every colour in it comes from. A switch in
        the middle of a glide is left out - its row's tile shows there - and drawn over the copy.
        """
        canvas, scale = self.canvas, plan["scale"]
        self._use_scale(scale)
        parts = []
        for item in plan["items"]:
            kind = item["kind"]
            if kind == "button":
                parts.append((kind, item["rect"], item["primary"], self._lifted(item, pressed)))
            elif kind not in ("text", "focusable", "halo"):
                parts.append((kind, item["rect"], item.get("radius"), item.get("tone"), item.get("checked"),
                              item.get("busy"), kind == "switch" and item["target"] in glides))
        key = (plan["size"], scale, self._theme(), self._system_key(), tuple(parts))
        if self._ground_key == key and self._ground_pixels is not None:
            C.memmove(canvas.bits, self._ground_pixels, len(self._ground_pixels))
            return
        drawn = [item for item in plan["items"] if not (item["kind"] == "switch" and item["target"] in glides)]
        with _Painter(canvas) as paint:
            paint.fill_round((0, 0, canvas.width, canvas.height), 0, self._argb("canvas"))
            # The card, then every tile's lift, then everything that stands on the card: a tile's
            # shadow falls on the card, and never over a tile drawn before it - the highlight above
            # the second tile would otherwise lie across the bottom edge of the first.
            for item in drawn:
                if item["kind"] == "card":
                    self._ground_item(paint, item, scale, pressed)
            for item in drawn:
                if item["kind"] == "panel":
                    self._lift(paint, "tile", item["rect"], brand.RADII["control"] * scale, scale)
            for item in drawn:
                if item["kind"] != "card":
                    self._ground_item(paint, item, scale, pressed)
        self._ground_pixels = canvas.pixels()
        self._ground_key = key

    def _ground_item(self, paint, item, scale, pressed):
        kind = item["kind"]
        hairline = max(1.0, round(scale))
        if kind == "card":
            # The panel's card: its lift, its ground (dark lifts it a step toward `raised`), dark's
            # one-pixel top light inside the border, and the hairline.
            rect, radius = item["rect"], item["radius"]
            self._lift(paint, "card", rect, radius, scale)
            ground = (self._argb("surface") if self.contrast
                      else _pack(brand.rgb(brand.card_ground(self._theme()))))
            paint.fill_round(rect, radius, ground)
            self._inner(paint, "card", rect, radius, scale)
            paint.stroke_round(rect, radius, self._argb("line"), hairline)
        elif kind == "panel":
            # A task row is a tile, raised off the card (DEPTH): its lift is already under it (see
            # _ground), then its ground - `raised`, a step brighter than the card's in dark - its top
            # light and the hairline, which stays because a shadow alone is not an edge for everybody.
            rect, radius = item["rect"], brand.RADII["control"] * scale
            ground = self._argb("raised") if self.contrast else _pack(brand.rgb(tile_ground(self._theme())))
            paint.fill_round(rect, radius, ground)
            self._inner(paint, "tile", rect, radius, scale)
            paint.stroke_round(rect, radius, self._argb("line"), hairline)
        elif kind == "well":
            # A value's field, sunken as the panel's are: the inset fill, the inset recipe inside the
            # border, and the hairline.
            rect, radius = item["rect"], brand.RADII["control"] * scale
            paint.fill_round(rect, radius, self._argb("inset"))
            self._well(paint, rect, radius, scale)
            paint.stroke_round(rect, radius, self._argb("line"), hairline)
        elif kind == "rule":
            paint.fill_round(item["rect"], 0, self._argb("line"))
        elif kind in ("chip", "note"):
            rect = item["rect"]
            radius = (rect[3] - rect[1]) / 2.0 if kind == "chip" else brand.RADII["control"] * scale
            if self.contrast:
                if kind == "note":                       # no tint to hold it together: an edge instead
                    paint.stroke_round(rect, radius, self._argb("line"), hairline)
            else:
                # Its tone mixed into the card's colour, whatever it sits on, and no edge: the same
                # ground on a raised row as on the card.
                tokens = self._tokens()
                ground = brand.mix(tokens["surface"], tokens[item["tone"]], CHIP_ALPHA)
                paint.fill_round(rect, radius, _pack(brand.rgb(ground)))
        elif kind == "switch":
            self._switch(paint, item, scale)
        elif kind == "button" and self._lifted(item, pressed):
            self._lift(paint, "control", item["rect"], brand.RADII["control"] * scale, scale)

    # ------------------------------------------------------------------ materials
    def _use_scale(self, scale):
        """Shadow images are kept for one scale and one theme only, so neither a change of display nor
        a flip of the theme can grow them."""
        look = (scale, self._theme())
        if self._images_look != look:
            self._drop_images()
            self._images_look = look

    def _drop_images(self):
        for image in self._images.values():
            image.close()
        self._images = {}

    def _image(self, mask, shadow):
        # The theme is part of the key as well as the reason the images are dropped: a shadow's
        # token is a different colour in each theme, and an image is that colour baked in.
        theme = self._theme()
        key = (mask["key"], theme, shadow.token, shadow.alpha)
        image = self._images.get(key)
        if image is None:
            image = self._images[key] = _ShadowImage(mask, brand.rgb(brand.palette(theme)[shadow.token]),
                                                     shadow.alpha)
        return image

    def _lift(self, paint, recipe, rect, radius, scale):
        """A raised body's outer shadows, the last listed first as CSS paints them; the body goes on top.

        Read from the theme's recipe shadow by shadow: dark's card mixes two drops with an inset top
        light, which `_inner` draws once the body is filled.
        """
        if self.contrast:
            return
        left, top, right, bottom = (int(value) for value in rect)
        for shadow in reversed(recipe_shadows(recipe, self._theme())):
            if shadow.inset:
                continue
            image = self._image(lift_coverage(right - left, bottom - top, radius, shadow.blur * scale), shadow)
            extent = image.extent
            image.stamp(paint, left - extent + shadow_step(shadow.dx * scale),
                        top - extent + shadow_step(shadow.dy * scale),
                        right - left + 2 * extent, bottom - top + 2 * extent, middle=False)

    def _inner(self, paint, recipe, rect, radius, scale):
        """A recipe's inset shadows inside a body's border, over its fill, as CSS paints them."""
        if self.contrast:
            return
        inset = [shadow for shadow in reversed(recipe_shadows(recipe, self._theme())) if shadow.inset]
        if not inset:
            return
        border = int(max(1.0, round(scale)))
        left, top, right, bottom = (int(value) for value in rect)
        width, height = right - left - 2 * border, bottom - top - 2 * border
        if width <= 0 or height <= 0:
            return
        inner = max(0.0, radius - border)
        for shadow in inset:
            mask = well_coverage(width, height, inner, shadow.blur * scale, shadow.dx * scale, shadow.dy * scale)
            self._image(mask, shadow).stamp(paint, left + border, top + border, width, height)

    def _well(self, paint, rect, radius, scale):
        """The inset recipe inside a body's border: in light, shade in from the top left and light from
        the bottom right; in dark, one soft shade along the inside of the top."""
        self._inner(paint, "inset", rect, radius, scale)

    def _switch(self, paint, item, scale, on=None):
        """The panel's switch: a well with a quiet knob when off, the accent with a white knob when on.

        `on` is how far on it is drawn, for a glide: the knob that far along its travel, the accent
        faded in over the well by as much, and the knob's colour that far from off's to on's. None
        draws it where it stands.
        """
        left, top, right, bottom = rect = item["rect"]
        radius = (bottom - top) / 2.0
        faded = 0.5 if item["busy"] else 1.0              # busy: halfway into the row it sits on
        knob = int(round(brand.LAYOUT["knob"] * scale))
        knob_left = left + int(round(brand.LAYOUT["knob_inset"] * scale))
        amount = (1.0 if item["checked"] else 0.0) if on is None else max(0.0, min(1.0, float(on)))
        off_knob = "ink" if self.contrast else "muted"
        if amount < 1.0:
            paint.fill_round(rect, radius, self._argb("inset", faded))
            if not item["busy"]:
                self._well(paint, rect, radius, scale)
            paint.stroke_round(rect, radius, self._argb("line", faded), max(1.0, round(scale)))
        if amount > 0.0:
            paint.fill_round(rect, radius, self._argb("accent", faded * amount))
        knob_left += int(round(brand.LAYOUT["knob_travel"] * scale)) * amount
        if amount in (0.0, 1.0):
            colour = self._argb("on_accent" if amount else off_knob, faded)
        else:
            start, end = self._rgb(off_knob), self._rgb("on_accent")
            colour = _pack(tuple(int(round(a + (b - a) * amount)) for a, b in zip(start, end)), faded)
        paint.fill_circle(knob_left + knob / 2.0, (top + bottom) / 2.0, knob / 2.0, colour)

    def _button(self, paint, item, scale, hover, pressed):
        """A button's face. Its lift is in the ground; pressed, it sinks into a well instead."""
        rect, target, primary = item["rect"], item["target"], item["primary"]
        radius = brand.RADII["control"] * scale
        sunk = not item["busy"] and pressed == target
        if item["busy"]:
            fill, edge = "surface", "line"
        elif sunk:
            fill, edge = ("accent_pressed", "accent") if primary else ("inset", "line")
        elif hover == target:
            fill, edge = ("accent_hover", "accent_hover") if primary else ("surface", "line")
        else:
            fill, edge = ("accent", "accent") if primary else ("raised", "line")
        paint.fill_round(rect, radius, self._argb(fill))
        if sunk:
            self._well(paint, rect, radius, scale)
        paint.stroke_round(rect, radius, self._argb(edge), max(1.0, round(scale)))

    # ------------------------------------------------------------------ the status light
    def _keep_halo_band(self, plan):
        canvas = self.canvas
        item = next((entry for entry in plan["items"] if entry["kind"] == "halo"), None)
        self._halo_plan = plan
        if item is None:
            self._halo_band = None
            return
        _dll("gdi32").GdiFlush()
        # The item's radius is the largest glow any frame draws; leave room for its soft edge.
        reach = item["radius"] + 2 * plan["scale"] + 2
        top = max(0, int(item["cy"] - reach))
        bottom = min(canvas.height, int(math.ceil(item["cy"] + reach)))
        offset = top * canvas.width * 4
        self._halo_band = (offset, C.string_at(canvas.bits.value + offset, (bottom - top) * canvas.width * 4))

    def _halo(self, paint, item, scale, frame):
        """The state dot, flat and the size it always was, with its glow and the checking arc."""
        state, cx, cy = item["state"], item["cx"], item["cy"]
        dot, light = brand.STATUS_DOT["popup"], brand.GLOW
        arc = frame.get("arc") if frame is not None else None
        arc_radius, arc_width = (dot + light["arc_gap"]) * scale, light["arc_width"] * scale
        if self.contrast:
            # A solid dot in a system colour, and the arc, if any, in the same colour.
            colour = _pack(system_rgb(brand.status_system(state)))
            paint.fill_circle(cx, cy, dot * scale, colour)
            if arc is not None:
                paint.arc(cx, cy, arc_radius, arc, light["arc_sweep"], colour, arc_width)
            return
        self._light(paint, cx, cy, dot, scale, DOT_FILL.get(state, "idle"), frame)
        if arc is not None:
            paint.arc(cx, cy, arc_radius, arc, light["arc_sweep"], self._argb("active", light["arc_alpha"]),
                      arc_width)

    def _light(self, paint, cx, cy, dot, scale, fill, frame):
        """The dot and its glow for a brand.glow frame (None: off). Dimmed, the dot is its colour over the card."""
        dim, opacity = (frame["dim"], frame["opacity"]) if frame is not None else (0.0, 0.0)
        if opacity > 0:
            paint.glow(cx, cy, brand.glow_radius(dot, frame["spread"]) * scale, brand.glow_stops(dot), self._rgb(fill),
                       opacity)
        paint.fill_circle(cx, cy, dot * scale, self._argb(fill, 1.0 - dim))

    def _text(self, dc, plan, busy):
        gdi32, user32 = _dll("gdi32"), _dll("user32")
        gdi32.SetBkMode(dc, 1)                                             # transparent
        original = None
        try:
            for item in plan["items"]:
                if item["kind"] != "text":
                    continue
                previous = gdi32.SelectObject(dc, self.fonts.handles[item["role"]])
                if original is None:
                    original = previous
                # Anything under way reads as waiting: a busy button's face is no longer the accent.
                colour = "muted" if item.get("target") in busy else item["colour"]
                gdi32.SetTextColor(dc, self._colorref(colour))
                flags = DT_NOPREFIX
                if item["wrap"]:
                    flags |= DT_WORDBREAK | DT_EDITCONTROL
                else:
                    flags |= DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS
                if item["align"] == "center":
                    flags |= DT_CENTER
                left, top, right, bottom = item["rect"]
                value = self.lines(item["role"], item["text"], right - left) if item["wrap"] else item["text"]
                rect = W.RECT(int(left), int(top), int(right), int(bottom))
                user32.DrawTextW(dc, value, -1, C.byref(rect), flags)
        finally:
            if original is not None:
                gdi32.SelectObject(dc, original)
            gdi32.GdiFlush()
