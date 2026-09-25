"""The notification card, the pure half: what it says, where it goes and how it moves.

Since v0.6.5 a notification can appear as the product's own card beside the notification area
instead of as a Windows toast (`notifier.py` decides which, `notice_presence.py` says when the
card may not). It is the popup's card - the same width, radius, shadow family, padding, type
roles, chip and status light, every one of them read from `brand` and drawn by the popup's own
renderer - laid out like one of the popup's task cards:

    ( light ) Codex Auto Resume                      ( reason )
    +-------------------------------------------------------+
    | The conversation's name                                |
    | Why the card appeared, in the toast's own sentence     |
    | project  -  Conversation: <the exact id>               |
    +-------------------------------------------------------+
    [ Don't resume ]                        [ Open Dashboard ]

It shows the toast's three lines and nothing else, and the toast's buttons (for a detected
interruption; every other notice has none, as its toast has none).

**The moment it appears** is part of the design (requirement 6): it rises out of the corner the
notification area is in, fading in and growing from 98% to full size while its shadow deepens,
on the brand's one curve (`brand.ease`, the ease-out every surface moves on), so it settles rather
than lands. It holds for a few seconds - longer if
Windows is set to keep notifications longer - pauses while the pointer is over any card, and
fades out. Up to three stack, the newest nearest the corner; a fourth retires the oldest early,
and so does any card the work area has no room for (a short screen holds two, or one).
With Reduce motion, Windows' animation setting, battery saver or High Contrast it appears and
disappears in place, with no movement and no fade at either end (B-D10).

**Over the wallpaper.** The popup draws its own canvas behind its card, so its neumorphic light
(a white glow up and left) has something to be lighter than. A card floating over somebody's
wallpaper has no canvas: a white glow on a dark photo is a halo, and light's pale blue-grey drop
is a *lighter* smudge on a dark desktop. So the floating card keeps the recipe's geometry and
drops only, drawn in the one near-black shadow token, at the strength that darkens a white ground
as much as the recipe's drop does (`float_shadows`). Dark's recipe is already near-black and is
kept as it is. The card itself, its hairline and dark's inner top light are the popup's.

Everything here is pure and tested on any platform; `notice_window.py` is the Win32 half.
"""
from __future__ import annotations

from collections import namedtuple
import math

from . import brand, l10n
from .ui import popup

WIDTH = popup.WIDTH                       # the popup's width, so the two are one product
CARD_WIDTH = WIDTH - 2 * brand.SPACING["m"]    # the card itself: exactly the popup's card
MAX_CARDS = 3
FRAME_MS = 16                                  # frames only while something moves
# The status light alone breathes at the popup's frame rate, and only its band is drawn (v0.6.10):
# until then the whole card was drawn again for it at most every 80 ms (about 11 frames a second on
# Windows' default 15.6 ms timer tick), on a timer running at FRAME_MS for as long as the card was up.
BREATH_FRAME_MS = popup.FRAME_MS
# The entrance, as tuned on a real screen (2880x1800 at 200%, light and dark, over a busy dark
# desktop): the card is solid within about a third of the entrance and then keeps rising softly
# to rest. With the fade spread over most of it (280 ms, 16 dip, fade done at 60%), a light card
# crossing a dark desktop read as a grey slab with the text beneath showing through for several
# frames, and the rise was over before the eye found the card.
ENTRANCE_MS = 340
EXIT_MS = 220
SLIDE_MS = 280
SWAP_MS = 130                                  # a card replaced by a newer one about the same task
STACK_DELAY_MS = 120                           # a newcomer waits this long for the stack to make room
HOLD_MS = 6000                                 # at least; Windows' own duration if it is longer
HOVER_GRACE_MS = 1500                          # after the pointer leaves, at least this is left
RISE = 20                                      # dip the card rises through as it enters
SCALE_FROM = 0.98
ALPHA_SHARE = 0.35                             # the fade is complete this far into the entrance
# The shadow at the start of the entrance, as a fraction of the settled one: nearer and fainter,
# so the card seems to lift off the desktop as it arrives.
DEPTH_START = {"offset": 0.35, "blur": 0.55, "alpha": 0.30}
DEPTH_LEVELS = 6                               # shadow images kept per card, from start to settled
# A shadow drawn over the wallpaper must darken whatever is under it. Tokens lighter than this
# (relative luminance) are redrawn in FLOAT_SHADOW_TOKEN, and a white highlight is dropped.
FLOAT_SHADOW_TOKEN = "shadow_dark"
FLOAT_SHADOW_THEME = "dark"                    # dark's shadow_dark: near-black with the brand's blue
DARK_ENOUGH = 0.05
HEADER_KEY = "tray.title"                      # "Codex Auto Resume": a name, never translated

FloatShadow = namedtuple("FloatShadow", "dx dy blur colour alpha")


# -------------------------------------------------------------------------------- words
def view(notice) -> dict:
    """What one card says, as plain values, from a notifier.Notice (or anything shaped like one)."""
    strings = l10n.catalog(notice.locale if notice.locale in l10n.LOCALES else l10n.DEFAULT)
    actions = []
    for index, (label, uri) in enumerate(notice.actions):
        # Opening the Dashboard is the accent, as it is in the popup; cancelling is the quiet one.
        actions.append({"label": label, "uri": uri, "primary": str(uri).split("?", 1)[0].endswith(":open"),
                        "target": ("action", index)})
    return {
        "product": strings.get(HEADER_KEY) or l10n.catalog(l10n.DEFAULT)[HEADER_KEY],
        "status": notice.status,
        "chip": notice.chip,
        "chip_tone": notice.chip_tone or "waiting",
        "title": popup.one_line(notice.title),
        "line": notice.line,
        "origin": popup.one_line(notice.origin, 200),
        "actions": actions,
        "locale": notice.locale if notice.locale in l10n.LOCALES else l10n.DEFAULT,
    }


def texts(vm) -> list:
    """Every string a card with this view draws, for the privacy test."""
    found = [vm["product"], vm["title"], vm["line"], vm["origin"]]
    if vm["chip"]:
        found.append(vm["chip"])
    found.extend(action["label"] for action in vm["actions"])
    return [text for text in found if text]


# ------------------------------------------------------------------------------- layout
def layout(vm, scale, measure) -> dict:
    """Every rectangle the card draws, in device pixels, with the card at (0, 0).

    The items are the kinds `popup.Renderer` draws (card, halo, chip, panel, text,
    button), so the card is painted by the popup's own renderer and materials. `measure` is
    the renderer's: (role, text, width, wrap) -> (width, height). The title and the chip end in
    an ellipsis rather than wrap; the reason line wraps, because it is the reason the card
    appeared, and so does the origin line, because it ends in the exact conversation id.
    `targets` are the buttons, for hit testing. Every gap is a step of brand.SPACING.
    """
    space = brand.SPACING

    def px(value):
        return int(round(value * scale))

    width = px(CARD_WIDTH)
    pad = px(space["l"])
    left, right = pad, width - pad
    inner = right - left
    items, targets = [], []
    y = pad

    def text(rect, role, value, colour, *, wrap=False, align="left", target=None):
        items.append({"kind": "text", "rect": tuple(int(v) for v in rect), "role": role, "text": value,
                      "colour": colour, "wrap": wrap, "align": align, "target": target})

    # The header: the status light, the product beside it in the popup's eyebrow (muted, `label`), and
    # the reason's chip. The light and the word stand as they do in every header (popup.light_row):
    # `light_inset` from the edge to the dot and `light_gap` from the dot to the word, since v0.6.10.
    mark = px(popup.MARK)
    cx, text_left = popup.light_row(left, brand.STATUS_DOT["popup"], scale)
    _, product_h = measure("label", vm["product"], inner, False)
    chip_rect = None
    chip_w = chip_h = 0
    # A chip as the window and the panel size one (v0.6.10): LAYOUT's height and padding.
    chip_pad = px(brand.LAYOUT["chip_pad_x"])
    if vm["chip"]:
        chip_text_w, chip_text_h = measure("chip", vm["chip"], inner, False)
        product_w, _ = measure("label", vm["product"], inner, False)
        room = right - (text_left + product_w + px(space["m"]))
        chip_w = max(min(chip_text_w + 2 * chip_pad, room), min(chip_text_w + 2 * chip_pad, inner // 3))
        chip_h = max(px(brand.LAYOUT["chip_height"]), chip_text_h)
    header_h = max(mark, product_h, chip_h)
    items.append({"kind": "halo", "cx": cx, "cy": y + header_h / 2.0, "state": vm["status"],
                  "radius": brand.glow_extent(brand.STATUS_DOT["popup"]) * scale})
    product_right = right - (chip_w + px(space["s"]) if chip_w else 0)
    top = y + (header_h - product_h) // 2
    text((text_left, top, product_right, top + product_h), "label", vm["product"], "muted")
    if vm["chip"]:
        chip_top = y + (header_h - chip_h) // 2
        chip_rect = (right - chip_w, chip_top, right, chip_top + chip_h)
        items.append({"kind": "chip", "rect": chip_rect, "tone": vm["chip_tone"]})
        text((chip_rect[0] + chip_pad, chip_rect[1], chip_rect[2] - chip_pad, chip_rect[3]), "chip",
             vm["chip"], vm["chip_tone"], align="center")
    y += header_h + px(space["s"])

    # The notice itself, as a task tile: its name, why, and exactly which conversation.
    tile_pad = px(space["m"])
    tile_top = y
    x0, x1 = left + tile_pad, right - tile_pad
    content = x1 - x0
    line_y = tile_top + tile_pad
    _, title_h = measure("name", vm["title"], content, False)
    text((x0, line_y, x1, line_y + title_h), "name", vm["title"], "ink")
    line_y += title_h + px(space["xs"])
    if vm["line"]:
        _, line_h = measure("body", vm["line"], content, True)
        text((x0, line_y, x1, line_y + line_h), "body", vm["line"], "ink", wrap=True)
        line_y += line_h + px(space["xs"])
    if vm["origin"]:
        # Wrapped, never cut: its end is the exact conversation id, which half an id is not.
        _, origin_h = measure("small", vm["origin"], content, True)
        text((x0, line_y, x1, line_y + origin_h), "small", vm["origin"], "muted", wrap=True)
        line_y += origin_h
    tile_bottom = line_y + tile_pad
    items.append({"kind": "panel", "rect": (left, tile_top, right, tile_bottom)})
    y = tile_bottom

    # The toast's buttons, as the popup lays out its own: side by side when both labels fit on
    # one line, stacked when either would not - a German label is never cut in half.
    if vm["actions"]:
        y += px(space["m"])
        button_h = px(brand.LAYOUT["button_height"])     # the window's and the panel's, since v0.6.10
        button_pad = px(space["m"])
        half = (inner - px(space["s"])) // 2
        widths = [measure("button", action["label"], inner, False)[0] for action in vm["actions"]]
        placed = []
        if len(vm["actions"]) == 1:
            placed.append(((right - half, y, right, y + button_h), False))
            y += button_h
        elif len(vm["actions"]) == 2 and max(widths) + 2 * button_pad <= half:
            placed = [((left, y, left + half, y + button_h), False),
                      ((right - half, y, right, y + button_h), False)]
            y += button_h
        else:
            for index, action in enumerate(vm["actions"]):
                _, label_h = measure("button", action["label"], inner - 2 * button_pad, True)
                height = max(button_h, label_h + 2 * px(space["s"]))
                placed.append(((left, y, right, y + height), True))
                y += height + (px(space["s"]) if index < len(vm["actions"]) - 1 else 0)
        for action, (rect, wrapped) in zip(vm["actions"], placed):
            target = action["target"]
            items.append({"kind": "button", "rect": rect, "primary": action["primary"], "busy": False,
                          "target": target})
            if wrapped:
                _, label_h = measure("button", action["label"], rect[2] - rect[0] - 2 * button_pad, True)
                top = rect[1] + (rect[3] - rect[1] - label_h) // 2
                label_rect = (rect[0] + button_pad, top, rect[2] - button_pad, top + label_h)
            else:
                label_rect = (rect[0] + button_pad, rect[1], rect[2] - button_pad, rect[3])
            text(label_rect, "button", action["label"], "on_accent" if action["primary"] else "ink",
                 wrap=wrapped, align="center", target=target)
            targets.append((target, rect))
    y += pad
    card = (0, 0, width, y)
    items.insert(0, {"kind": "card", "rect": card, "radius": px(brand.RADII["card"])})
    return {"size": (width, y), "card": card, "items": items, "targets": targets, "scale": scale}


# ------------------------------------------------------------------------------- motion
# The card rises, comes back and slides on brand.ease, the one curve a switch glides on in every
# surface (brand.MOTION). Until v0.6.10 it had its own easeOutCubic, the curve brand.ease is written
# as a CSS cubic-bezier of - near it, and not it.
def ease_in(progress: float) -> float:
    """easeInQuad, for leaving: it lingers a moment, then goes."""
    t = min(1.0, max(0.0, progress))
    return t * t


Frame = namedtuple("Frame", "alpha offset scale depth")
SETTLED = Frame(1.0, 0.0, 1.0, 1.0)


def entrance(elapsed_ms, *, reduced=False) -> Frame:
    """The card `elapsed_ms` into its entrance: alpha 0-1, offset in dip toward the taskbar
    edge (RISE to 0), scale (SCALE_FROM to 1) and the shadow's depth (0 to 1)."""
    if reduced or elapsed_ms >= ENTRANCE_MS:
        return SETTLED
    t = max(0.0, elapsed_ms) / float(ENTRANCE_MS)
    settle = brand.ease(t)
    return Frame(alpha=brand.ease(t / ALPHA_SHARE), offset=RISE * (1.0 - settle),
                 scale=SCALE_FROM + (1.0 - SCALE_FROM) * settle, depth=settle)


def leaving(elapsed_ms, start_alpha=1.0, *, reduced=False, duration=EXIT_MS) -> float:
    """The card's alpha `elapsed_ms` into its exit, from `start_alpha`. No movement of its own."""
    if reduced or elapsed_ms >= duration:
        return 0.0
    return start_alpha * (1.0 - ease_in(max(0.0, elapsed_ms) / float(duration)))


def rise_vector(edge) -> tuple:
    """Which way the entrance offset points: toward the taskbar, so the card rises out of it."""
    return {"bottom": (0, 1), "top": (0, -1), "left": (-1, 0), "right": (1, 0)}.get(edge, (0, 1))


class CardMotion:
    """One card's life on a clock it is given: enter, hold, exit, gone. No Win32 here.

    Holding counts down only while nobody points at a card (`pause`); leaving is ease-in with
    no movement of its own; a pointer arriving while it leaves on its own brings it back.
    `retire` sends it out early and for good - a fourth card arrived, a newer notice about the
    same task replaced it (`quick`), or it was clicked. `delay` holds an entrance back while
    the stack makes room. Its place in the stack glides to a new target over SLIDE_MS.
    With `reduced`, every change is immediate and nothing fades.
    """

    def __init__(self, now_ms, *, hold_ms=HOLD_MS, reduced=False, position=None):
        self.reduced = bool(reduced)
        self.phase = "hold" if self.reduced else "enter"
        self.since = now_ms
        self.hold_ms = max(0.0, float(hold_ms))
        self.hold_left = self.hold_ms
        self.paused = False
        self.from_alpha = 1.0
        self.exit_ms = EXIT_MS
        self.final = False
        self.position = position
        self._slide = None

    def restart(self, now_ms) -> None:
        """Begin the card's life at `now_ms` - the entrance, or the hold when reduced - rather than
        when its motion was made. Its host calls it once the card is drawn and ready to show, so
        the time spent drawing it (tens of milliseconds at 200%) never eats into the entrance."""
        if self.phase in ("enter", "hold") and not self.final:
            self.phase = "hold" if self.reduced else "enter"
            self.since = now_ms
            self.hold_left = self.hold_ms

    def delay(self, ms) -> None:
        """Start the entrance `ms` later (it stays invisible until then)."""
        if self.phase == "enter" and ms > 0:
            self.since += ms

    # ---- the clock
    def _advance(self, now_ms):
        if self.phase == "enter" and now_ms - self.since >= ENTRANCE_MS:
            self.phase, self.since = "hold", self.since + ENTRANCE_MS
        if self.phase == "return" and now_ms - self.since >= EXIT_MS:
            self.phase, self.since = "hold", self.since + EXIT_MS
        if self.phase == "hold" and not self.paused and now_ms - self.since >= self.hold_left:
            self.phase, self.since, self.from_alpha = "exit", self.since + self.hold_left, 1.0
            self.hold_left = 0.0
        if self.phase == "exit" and (self.reduced or now_ms - self.since >= self.exit_ms):
            self.phase = "gone"

    def frame(self, now_ms) -> Frame:
        self._advance(now_ms)
        elapsed = now_ms - self.since
        if self.phase == "enter":
            return entrance(elapsed, reduced=self.reduced)
        if self.phase == "return":
            t = brand.ease(elapsed / float(EXIT_MS))
            return SETTLED._replace(alpha=self.from_alpha + (1.0 - self.from_alpha) * t)
        if self.phase == "exit":
            return SETTLED._replace(alpha=leaving(elapsed, self.from_alpha, reduced=self.reduced,
                                                  duration=self.exit_ms))
        if self.phase == "gone":
            return SETTLED._replace(alpha=0.0)
        return SETTLED

    @property
    def gone(self) -> bool:
        return self.phase == "gone"

    def pause(self, now_ms, paused) -> None:
        """Hold still while somebody points at the stack; count down again when they stop."""
        self._advance(now_ms)
        paused = bool(paused)
        if paused == self.paused:
            return
        if paused:
            if self.phase == "hold":
                self.hold_left = max(0.0, self.hold_left - (now_ms - self.since))
                self.since = now_ms
            elif self.phase == "exit" and not self.reduced and not self.final:
                # Brought back: from wherever the fade had got to, up to full again.
                self.from_alpha = self.frame(now_ms).alpha
                self.phase, self.since = "return", now_ms
                self.hold_left = 0.0
        else:
            if self.phase in ("hold", "return"):
                if self.phase == "hold":
                    self.since = now_ms
                self.hold_left = max(self.hold_left, float(HOVER_GRACE_MS))
        self.paused = paused

    def retire(self, now_ms, *, quick=False) -> None:
        """Leave now and for good: a newer card needs the place, or it was clicked."""
        self._advance(now_ms)
        self.final = True
        if self.phase == "gone":
            return
        if self.phase == "exit":
            if quick and self.exit_ms > SWAP_MS:
                self.from_alpha = self.frame(now_ms).alpha
                self.since, self.exit_ms = now_ms, SWAP_MS
            return
        self.from_alpha = 0.0 if self.phase == "enter" and now_ms < self.since else self.frame(now_ms).alpha
        self.phase, self.since, self.paused = "exit", now_ms, False
        self.exit_ms = SWAP_MS if quick else EXIT_MS
        if self.reduced:
            self.phase = "gone"

    # ---- where it is
    def move_to(self, now_ms, target, delay=0) -> None:
        """Glide to a new place in the stack, starting `delay` ms from now (or jump there, reduced,
        or on its first place)."""
        target = tuple(target)
        if self.position is None or self.reduced:
            self.position, self._slide = target, None
            return
        current = self.place(now_ms)
        if current == target:
            self._slide = None
            self.position = target
            return
        self._slide = (current, target, now_ms + max(0, delay))
        self.position = target

    def place(self, now_ms) -> tuple:
        if self._slide is None:
            return self.position
        start, target, began = self._slide
        t = (now_ms - began) / float(SLIDE_MS)
        if t >= 1.0:
            self._slide = None
            return target
        settle = brand.ease(t)
        return tuple(int(round(a + (b - a) * settle)) for a, b in zip(start, target))

    def moving(self, now_ms) -> bool:
        """Whether a frame timer has anything to draw for this card now."""
        self._advance(now_ms)
        if self._slide is not None and now_ms - self._slide[2] < SLIDE_MS:
            return True
        return self.phase in ("enter", "exit", "return") and not self.reduced

    def wait_ms(self, now_ms):
        """How long nothing will change, when nothing is moving: the rest of the hold, or None."""
        self._advance(now_ms)
        if self.phase == "hold" and not self.paused:
            return max(0.0, self.hold_left - (now_ms - self.since))
        return None


def hold_ms(message_duration_ms=None) -> float:
    """HOLD_MS, or Windows' own "dismiss notifications after" time when that is longer."""
    if isinstance(message_duration_ms, (int, float)) and not isinstance(message_duration_ms, bool):
        return float(max(HOLD_MS, message_duration_ms))
    return float(HOLD_MS)


# -------------------------------------------------------------------------- the stack
def _clamp(value, low, high):
    return low if high < low else max(low, min(value, high))


def stack_direction(edge, y, height, work) -> int:
    """-1 when older cards stand above the newest one, +1 when below: away from the corner."""
    if edge == "top":
        return 1
    if edge in ("left", "right") and (y + height / 2.0) < (work[1] + work[3]) / 2.0:
        return 1                                         # an icon high on a vertical taskbar
    return -1


def stack_positions(sizes, work, monitor, anchor=None, *, gap, spacing) -> tuple:
    """Where the cards go, newest first: ([(x, y), ...], edge). Physical pixels.

    The newest card is where the popup would open beside the anchor (`popup.place`): on the
    taskbar's side of the monitor that has the notification area, inside the work area. Each
    older one stands `spacing` further from the corner - upward from a taskbar at the bottom,
    left or right (the notification area is at the bottom end of a vertical taskbar), downward
    from one at the top.

    Only the cards that fit are placed: the list stops at the first older card that would reach
    past the work area, and the caller retires that one and every older one. An older card is
    never pushed back inside instead - that would lay it over a newer card, whose window stands
    above it and would cover its buttons. So on a short screen (a 1080p laptop at 150%, a 768p
    one at 100%) the stack is two cards, or one; the newest always has its place.
    """
    if not sizes:
        return [], popup.taskbar_edge(work, monitor, anchor)
    first_w, first_h = sizes[0]
    x0, y0, edge = popup.place((first_w, first_h), work, monitor, anchor, None, gap=gap)
    upward = stack_direction(edge, y0, first_h, work) < 0
    positions = [(x0, y0)]
    edge_x = x0 + first_w                                # cards line up on the corner's side
    y = y0
    previous_h = first_h
    for width, height in sizes[1:]:
        x = x0 if edge == "left" else edge_x - width
        y = y - spacing - height if upward else y + previous_h + spacing
        if y < work[1] + gap or y + height > work[3] - gap:
            break                                        # it would not fit: it and the older ones go
        x = _clamp(x, work[0] + gap, work[2] - gap - width)
        positions.append((x, y))
        previous_h = height
    return positions, edge


# --------------------------------------------------------------------- the floating shadow
def _luminance_of(colour) -> float:
    return brand.luminance(colour)


def float_shadows(theme) -> tuple:
    """The card recipe's outer shadows as they may be drawn over a wallpaper (see the docstring).

    A shadow in a light colour is redrawn in FLOAT_SHADOW_TOKEN at the alpha that darkens a white
    ground by as much; a shadow lighter than the ground it was designed for (light's highlight)
    has nothing to be lighter than here and is dropped. Inset shadows belong to the card and are
    drawn by the renderer inside it.
    """
    tokens = brand.palette(theme)
    ink = brand.palette(FLOAT_SHADOW_THEME)[FLOAT_SHADOW_TOKEN]
    ground = tokens["canvas"]
    found = []
    for shadow in brand.shadows("card", theme):
        if shadow.inset:
            continue
        colour = tokens[shadow.token]
        if _luminance_of(colour) >= _luminance_of(ground):
            continue                                     # a highlight: it lifts nothing here
        if _luminance_of(colour) <= DARK_ENOUGH:
            found.append(FloatShadow(shadow.dx, shadow.dy, shadow.blur, colour, shadow.alpha))
            continue
        darkening = shadow.alpha * (1.0 - _luminance_of(colour)) / (1.0 - _luminance_of(ink))
        found.append(FloatShadow(shadow.dx, shadow.dy, shadow.blur, ink, round(darkening, 4)))
    return tuple(found)


def shadow_at(shadows, depth) -> tuple:
    """The floating shadows at `depth` (0 = the start of the entrance, 1 = settled)."""
    depth = min(1.0, max(0.0, depth))

    def toward(start):
        return start + (1.0 - start) * depth

    offset, blur, alpha = (toward(DEPTH_START[name]) for name in ("offset", "blur", "alpha"))
    return tuple(FloatShadow(s.dx * offset, s.dy * offset, s.blur * blur, s.colour, s.alpha * alpha)
                 for s in shadows)


def depth_level(depth) -> int:
    """Which of DEPTH_LEVELS pre-drawn shadow images stands for `depth`."""
    return int(round(min(1.0, max(0.0, depth)) * (DEPTH_LEVELS - 1)))


def shadow_margin(shadows, scale) -> int:
    """How far the settled shadows reach past the card, in device pixels (three sigmas)."""
    reach = 0.0
    for shadow in shadows:
        reach = max(reach, max(abs(shadow.dx), abs(shadow.dy)) + 1.5 * shadow.blur)
    return int(math.ceil(reach * scale)) + 2


# ---------------------------------------------------------------------- the card's edge
_CORNERS = {}                                  # radius -> corner_coverage(radius), a few at most


def corner_coverage(radius) -> tuple:
    """How much of each pixel of a card's top-left corner square the card covers, 0-255.

    The rounded rectangle's own antialiasing, done once per radius: rows of `radius` bytes.
    The other three corners are this square turned round. Kept for the next call, since the
    status light's band is cut by it with every breath.
    """
    if radius in _CORNERS:
        return _CORNERS[radius]
    size = int(math.ceil(radius))
    rows = []
    for j in range(size):
        row = bytearray(size)
        for i in range(size):
            distance = math.hypot(radius - (i + 0.5), radius - (j + 0.5)) - radius
            if i + 0.5 >= radius or j + 0.5 >= radius:
                distance = -1.0
            row[i] = int(round(min(1.0, max(0.0, 0.5 - distance)) * 255))
        rows.append(bytes(row))
    if len(_CORNERS) >= 8:                     # a card per scale; nothing grows without end
        _CORNERS.clear()
    _CORNERS[radius] = tuple(rows)
    return _CORNERS[radius]


def premultiply(pixels, width, height, radius, top=0) -> bytearray:
    """A card's opaque BGRX pixels as premultiplied BGRA with its rounded corners cut out.

    Every pixel is opaque but those in the four corner squares, which take the rounded
    rectangle's coverage; those are scaled by it, as `UpdateLayeredWindow` requires. `pixels`
    may be a band of whole rows starting at row `top` of a card `height` high - the status
    light's, drawn again for a breath - and the band is cut exactly as the whole card is there.
    """
    data = bytearray(pixels)
    band = len(data) // (4 * width) if width else 0
    data[3::4] = b"\xff" * (width * band)
    rows = corner_coverage(radius)
    size = len(rows)
    for j in range(min(size, height)):
        for i in range(min(size, width)):
            cover = rows[j][i]
            if cover == 255:
                continue
            for x, y in ((i, j), (width - 1 - i, j), (i, height - 1 - j), (width - 1 - i, height - 1 - j)):
                y -= top
                if not 0 <= y < band:
                    continue
                index = (y * width + x) * 4
                if cover == 0:
                    data[index:index + 4] = b"\x00\x00\x00\x00"
                else:
                    for channel in range(3):
                        data[index + channel] = (data[index + channel] * cover + 127) // 255
                    data[index + 3] = cover
    return data
