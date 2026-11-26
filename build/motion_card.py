"""The notification card in a motion picture: its own paint at a pinned moment, laid on the canvas offscreen.

The card already draws itself offscreen: `Card(..., windows=False)` keeps its body and its floating shadow as two
premultiplied bitmaps (`_Layer(None)`) and `paint(now_ms)` fills them for any moment of its entrance - alpha, the
rise toward the taskbar, the scale and the shadow's depth all from notice_card's own motion. What a layered window
does with them on a real desktop - UpdateLayeredWindow, each layer at the frame's alpha over whatever is beneath - is
`lay` here, in integers, so that at full alpha it is exactly make_screenshots' `_over`: the settled card on the
canvas is the README card's own picture (`_SettledCard.at(0)`), byte for byte. On a clear canvas (RGBA, straight
alpha: the owner, 2026-11-16 - on a desktop the card floats with only its own shadow) the two layers are laid over
nothing in premultiplied BGRA, as the still does, and that is what is put on the canvas (`lay_clear`).

The card is placed as the stack places it (`notice_card.stack_positions`): above the taskbar strip, beside the tray
icon, the gap the stack keeps. Its light breathes on the picture's clock as it does on a desktop: held at the moment
the card came while it enters, the card's own `_draw_light` at the frame's moment once it stands still, and still
again from the moment it begins to leave. Its hover and pressed faces are the card's own (`hover`, `pressed`,
`redraw`), and the button a plan points at is named by what its link does (`card.open` is "Open Dashboard").
"""
from __future__ import annotations

from pathlib import Path
import sys
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# A card that is never told to leave holds for as long as a picture can be.
FOREVER_MS = 10.0 ** 12


class Layer(NamedTuple):
    """A premultiplied BGRA bitmap and where its top-left goes on the canvas."""
    pixels: bytes
    width: int
    height: int
    left: int
    top: int


class Drawn(NamedTuple):
    """The card at one moment: its shadow and its body, and the alpha the whole card is shown at."""
    alpha: float
    shadow: Layer
    body: Layer
    frame: tuple


def lay(canvas: bytearray, canvas_width: int, canvas_height: int, layer: Layer, alpha: float = 1.0) -> None:
    """`layer` over the opaque RGB `canvas` at the layer's place, as a layered window at `alpha` is shown over what
    is beneath it: each premultiplied channel and its coverage scaled by alpha, then source-over. At alpha 1 this is
    make_screenshots._over to the byte. What falls outside the canvas is cut off."""
    level = max(0, min(255, int(round(alpha * 255))))
    if level == 0:
        return
    pixels, width = layer.pixels, layer.width
    for y in range(layer.height):
        row_y = layer.top + y
        if row_y < 0 or row_y >= canvas_height:
            continue
        start = max(0, -layer.left)
        stop = min(width, canvas_width - layer.left)
        if start >= stop:
            continue
        source = (y * width) * 4
        base = (row_y * canvas_width + layer.left) * 3
        for x in range(start, stop):
            at = source + x * 4
            cover = pixels[at + 3]
            if cover == 0:
                continue
            blue, green, red = pixels[at], pixels[at + 1], pixels[at + 2]
            if level != 255:
                cover = (cover * level + 127) // 255
                blue, green, red = ((blue * level + 127) // 255, (green * level + 127) // 255,
                                    (red * level + 127) // 255)
            target = base + x * 3
            if cover == 255:
                canvas[target] = red
                canvas[target + 1] = green
                canvas[target + 2] = blue
                continue
            keep = 255 - cover
            canvas[target] = min(255, red + (canvas[target] * keep + 127) // 255)
            canvas[target + 1] = min(255, green + (canvas[target + 1] * keep + 127) // 255)
            canvas[target + 2] = min(255, blue + (canvas[target + 2] * keep + 127) // 255)


def lay_clear(canvas: bytearray, canvas_width: int, canvas_height: int, layers, alpha: float = 1.0) -> None:
    """`layers` (shadow first, then body) laid over the RGBA `canvas` with straight alpha, each at `alpha`.

    They are laid on each other first, in premultiplied BGRA over nothing, exactly as make_screenshots' `_over` lays
    the still's - so the settled card on a clear canvas is the clear still's pixels to the byte - and the result is
    then laid over the canvas: wholly clear where the canvas is, the straight colour of the card and of the shadow's
    soft edge where it is."""
    import make_screenshots
    level = max(0, min(255, int(round(alpha * 255))))
    if level == 0:
        return
    stack = bytearray(canvas_width * canvas_height * 4)
    left, top, right, bottom = canvas_width, canvas_height, 0, 0
    for layer in layers:
        pixels, width = layer.pixels, layer.width
        if level != 255:
            pixels = pixels.translate(bytes((value * level + 127) // 255 for value in range(256)))
        x0, y0 = max(0, layer.left), max(0, layer.top)
        x1, y1 = min(canvas_width, layer.left + width), min(canvas_height, layer.top + layer.height)
        if x0 >= x1 or y0 >= y1:
            continue
        cut = pixels
        if (x0, y0, x1, y1) != (layer.left, layer.top, layer.left + width, layer.top + layer.height):
            cut = b"".join(pixels[((y - layer.top) * width + x0 - layer.left) * 4:
                                  ((y - layer.top) * width + x1 - layer.left) * 4] for y in range(y0, y1))
        make_screenshots._over(stack, canvas_width, cut, x1 - x0, y1 - y0, x0, y0)
        left, top, right, bottom = min(left, x0), min(top, y0), max(right, x1), max(bottom, y1)
    for y in range(top, bottom):
        start = (y * canvas_width + left) * 4
        source = stack[start:start + (right - left) * 4]
        if source[3::4].count(0) == right - left:
            continue
        under = canvas[start:start + (right - left) * 4]
        if under[3::4].count(0) == right - left:
            rgb, cover = make_screenshots.unpremultiply(bytes(source))
            row = bytearray(len(source))
            row[0::4], row[1::4], row[2::4], row[3::4] = rgb[0::3], rgb[1::3], rgb[2::3], cover
            canvas[start:start + len(row)] = row
            continue
        for x in range(right - left):
            at = x * 4
            blue, green, red, cover = source[at:at + 4]
            if cover == 0:
                continue
            keep = 255 - cover
            held = under[at + 3]
            total = cover + (held * keep + 127) // 255
            for channel, colour in enumerate((red, green, blue)):
                laid = colour + ((under[at + channel] * held + 127) // 255 * keep + 127) // 255
                canvas[start + at + channel] = min(255, (laid * 255 + total // 2) // total)
            canvas[start + at + 3] = total


class CardFrames:
    """One card, for one picture: `drawn(t, born, ...)` is the card at moment `t` of a life that began at `born`.

    `work` and `monitor` are the canvas's work area and whole area, (left, top, right, bottom) in its pixels, and
    `anchor` the tray icon's rectangle the card stands beside; `scale` its size (1.5 beside a window pictured at
    150 %). `render`, a build/surface_render.py session, draws it through the host's render mode instead of the
    reference's Card, with the same calls. Close it when done: the card holds GDI+ objects."""

    def __init__(self, locale: str, *, scale: float, work, monitor, anchor=None, theme: str = "light",
                 design: str | None = None, render=None):
        import make_screenshots
        from codex_auto_resume import brand, notice_window
        from codex_auto_resume.ui import popup as tray_popup
        self._release = tray_popup._gdiplus_release
        tray_popup._gdiplus_acquire()
        self.card = None
        self.scale = scale
        where = {"dpi": int(round(96 * scale)), "work": (0, 0, 0, 0), "monitor": (0, 0, 0, 0), "anchor": None}
        drawn = {"theme": theme, "design": design or brand.DEFAULT_DESIGN, "contrast": False, "reduced": False}
        self._pinned = make_screenshots.pinned_face      # the stills' face (F1)
        try:
            with self._pinned():
                if render is not None:
                    self.card = render.card(make_screenshots.card_notice(locale), now_ms=0, where=where, drawn=drawn,
                                            hold=make_screenshots._NoStack().hold())
                else:
                    self.card = notice_window.Card(make_screenshots._NoStack(), make_screenshots.card_notice(locale),
                                                   now_ms=0, where=where, drawn=drawn, windows=False)
        except BaseException:
            self.close()
            raise
        self.place = self.position(work, monitor, anchor)
        self._face = (None, None)
        self._light = None

    def position(self, work, monitor, anchor) -> tuple:
        """Where the settled card's top-left stands: the newest card's place in the stack."""
        from codex_auto_resume import brand, notice_card
        gap = int(round(brand.SPACING["m"] * self.scale))
        positions, edge = notice_card.stack_positions([self.card.size], tuple(work), tuple(monitor),
                                                      tuple(anchor) if anchor else None, gap=gap, spacing=gap)
        if not positions:
            raise ValueError("the canvas's work area has no room for the card")
        self.card.edge = edge
        return positions[0]

    def target(self, verb: str):
        """The card's button whose link does `verb` (`open` for Open Dashboard): its target as the card names it."""
        for action in self.card.vm["actions"]:
            name = action["uri"].split(":", 1)[-1].split("?", 1)[0]
            if name == verb:
                return action["target"]
        raise KeyError("the card has no button that does %r" % verb)

    def button(self, verb: str) -> tuple:
        """(left, top, right, bottom) of that button on the canvas, the card at rest."""
        wanted = self.target(verb)
        for target, rect in self.card.plan["targets"]:
            if target == wanted:
                x, y = self.place
                return rect[0] + x, rect[1] + y, rect[2] + x, rect[3] + y
        raise KeyError("the card's layout has no button %r" % (wanted,))

    def drawn(self, t: float, born: float, *, hover=None, pressed=None, leave=None, light=None) -> Drawn | None:
        """The card at `t`, born at `born`, leaving from `leave` (or not), with `hover` / `pressed` naming a button by
        its verb; None once it has gone. `light` pins the moment its light is drawn at, for a test."""
        with self._pinned():
            return self._drawn(t, born, hover=hover, pressed=pressed, leave=leave, light=light)

    def _drawn(self, t, born, *, hover, pressed, leave, light):
        from codex_auto_resume import notice_card
        card = self.card
        motion = notice_card.CardMotion(born, hold_ms=FOREVER_MS)
        motion.move_to(born, self.place)
        if leave is not None:
            motion.retire(leave)
        if hasattr(card, "follow"):                 # the render mode's card: the same motion, said to it
            card.follow(motion, born, FOREVER_MS, self.place, leave)
        else:
            card.motion = motion
            card.born = born
        entering = t - born < notice_card.ENTRANCE_MS
        if light is None:
            light = born if entering else (t if leave is None else max(born + notice_card.ENTRANCE_MS,
                                                                        min(t, leave)))
        face = (self.target(hover) if hover else None, self.target(pressed) if pressed else None)
        if face != self._face:
            # The pointer came onto a button or pressed it: the card draws its face again, with its light where
            # the breath is (Card.redraw).
            card.hover, card.pressed = face
            card._breathed = light
            card.redraw()
            self._face, self._light = face, light - born
        elif light - born != self._light:
            card._draw_light(light)
            self._light = light - born
        painted = card.paint(t)
        frame = painted["frame"]
        if motion.gone:
            return None
        width, height = card.size
        margin = card.margin
        body = Layer(card.body.pixels(), width, height, painted["x"], painted["y"])
        shadow = Layer(card.shadow.pixels(), width + 2 * margin, height + 2 * margin,
                       painted["x"] - margin, painted["y"] - margin)
        return Drawn(frame.alpha, shadow, body, tuple(frame))

    def lay_on(self, canvas: bytearray, width: int, height: int, drawn: Drawn) -> None:
        """The card's two layers over `canvas`, as the stack shows them: the shadow, then the body, each at the
        frame's alpha. A canvas of four bytes a pixel is a clear one (`lay_clear`)."""
        if drawn is None:
            return
        if len(canvas) == width * height * 4:
            lay_clear(canvas, width, height, (drawn.shadow, drawn.body) if self.card.margin else (drawn.body,),
                      drawn.alpha)
            return
        if self.card.margin:
            lay(canvas, width, height, drawn.shadow, drawn.alpha)
        lay(canvas, width, height, drawn.body, drawn.alpha)

    def close(self) -> None:
        if self.card is not None:
            self.card.close()
            self.card = None
        if self._release is not None:
            self._release()
            self._release = None
