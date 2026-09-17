"""The one place a colour is decided.

Five surfaces used to carry their own copies of the palette - the plugin manifest, the
Codex panel's stylesheet, the settings window's C# literals, the icon renderer and the
documentation. Five copies is five chances to drift, and they had already drifted: the
manifest's brand colour and the panel's accent agreed, and neither agreed with the icon.

So the palette lives here, in the package, and everything else is generated from it or
tested against it. The C# window cannot import Python, so its colours are *generated*
into `gui/Brand.cs` and a test regenerates and compares. Everything else imports.

## The idea

The product waits, and then it acts. That is the whole behaviour, so it is the whole
palette: deep blue at rest, cyan at the moment it does something. The ramp is not
decoration, it is the state model - a reader who learns that bright means active has
learned what the tool does.

## Reading the tokens

`LIGHT` and `DARK` hold the same key set, so any surface can theme by swapping one for
the other. `RAMP` is the four identity blues, darkest first, and is what the icon and
any promotional surface draw from; it does not change with the theme, because a brand
mark that changes colour with the operating system is not a brand mark.

`active` is a **fill-only** token. Measured against white it reaches 2.4:1, which is fine
for a status dot or a bar and is not enough for text. `accent` is the token for anything
a person has to read; it reaches 6.8:1 on white and 6.7:1 on the dark surface. Text drawn
*on* the accent takes `on_accent`, which is not the same colour in the two themes.
"""
from __future__ import annotations

from collections import namedtuple
import math

# The identity ramp: deep blue -> blue -> sky -> cyan. Darkest first.
RAMP = ("#0B2545", "#14417E", "#1257B8", "#3B9BEA", "#06B6D4")

# The single colour a host asks for when it has room for exactly one.
BRAND = "#1257B8"

LIGHT = {
    "ink":     "#0F1B2D",   # text, a near-black carrying the same blue bias
    "muted":   "#536477",   # secondary text; readable on the canvas, not only on a card
    "line":    "#D3DCE7",   # hairlines and card edges
    # v0.6.3: the surfaces moved toward each other. A raised card in a soft interface is
    # the same material as the window lifted by light and shadow, not a white sheet laid
    # on a grey one - so the canvas warmed up a step and the card came down from pure
    # white. The hairline stays: a shadow alone is not an edge for everybody, and nothing
    # in this product may depend on seeing a shadow.
    "surface": "#F6F8FB",   # cards
    "canvas":  "#E9EEF4",   # the window behind them
    "raised":  "#FBFCFE",   # a control resting on a card: a button, a chip, a toggle
    "inset":   "#E2E8F0",   # pressed, selected, or a well a value sits in
    "shadow_dark":  "#B7C4D4",  # the shadow below and right of a raised surface
    "shadow_light": "#FFFFFF",  # the highlight above and left of it
    "accent":  "#1257B8",   # anything to read or to click
    # v0.6.4: the primary button under the pointer and under a press. Written out rather than
    # mixed where they are drawn, because C#'s Math.Round, CSS color-mix and Python round a
    # half differently and three surfaces would land one level apart. The tests hold each to
    # its formula: hover is the accent at brightness 1.07 (the panel's old `filter`), pressed
    # is the accent 12% of the way to ink.
    "accent_hover": "#135DC5",
    "accent_pressed": "#1250A7",
    "accent_soft": "#DCE8F8",  # a quiet accent ground: a selected row, the active tab
    "on_accent": "#FFFFFF",  # text drawn *on* the accent, never on a page ground
    "focus":   "#2F7DE1",   # the keyboard focus ring
    "active":  "#06B6D4",   # fill only: the watcher is running, work is in flight
    "idle":    "#94A3B8",   # fill only: stopped, nothing pending
    "attention": "#B45309",  # fill only: needs a person
    # State colours that carry text. Each one is readable on a card - the tests hold them
    # to 4.5:1 - because a state is never shown by colour alone: it always has a word.
    "success": "#157045",   # recovered
    "waiting": "#1A5FA8",   # waiting for a reset or a retry
    "warning": "#9A4A06",   # needs a decision soon
    "danger":  "#B42318",   # stopped, failed
    "paused":  "#55657A",   # deliberately quiet
}

# Dark is not light inverted. Three things were wrong with the first attempt, and all
# three were visible the moment the two themes were put side by side:
#
#   * the canvas and the surface were four points of lightness apart, so a card did not
#     read as a card - the panel looked like one dark sheet with hairlines drawn on it;
#   * the hairline was darker than the surface it sat on, which is the wrong direction.
#     On a dark ground an edge is lighter than what it encloses, not darker;
#   * the cyan was at full saturation. It is a fill for "the watcher is running", it
#     appears as an 11px dot, and at #22D3EE that dot was the brightest thing on screen -
#     the product read as fluorescent rather than technical.
#
# So the surface is lifted away from the canvas, the line is lifted above the surface,
# and the cyan is brought down in chroma while staying unmistakably cyan. The blues keep
# the brand; there is simply less of the loudest one visible at once.
DARK = {
    "ink":     "#E8EEF6",
    "muted":   "#9AACBF",
    "line":    "#2E3A4B",
    "surface": "#191F29",
    "canvas":  "#0C1118",
    "raised":  "#212835",
    "inset":   "#121820",
    "shadow_dark":  "#05080C",
    "shadow_light": "#27303D",
    "accent":  "#5CA2EE",
    # Pressed goes 12% toward shadow_dark, not toward ink: dark ink is near-white, and a
    # button that brightens when pressed reads as released.
    "accent_hover": "#62ADFF",
    "accent_pressed": "#5290D3",
    "accent_soft": "#1B2D45",
    "focus":   "#7DB6F5",
    # Dark themes need a bright accent to stand off the surface, and a bright accent
    # cannot then carry white text: white on #5AA5F5 measures 2.6:1. So the text on the
    # accent is a token, not a literal, and it goes dark exactly when the accent goes
    # light. This was caught by the contrast test rather than by looking at it.
    "on_accent": "#08111C",
    "active":  "#35B5CC",
    "idle":    "#5F6E80",
    "attention": "#E09B57",
    "success": "#5CC98E",
    "waiting": "#7DB6F5",
    "warning": "#E8A765",
    "danger":  "#F2877C",
    "paused":  "#9AACBF",
}

# The icon's own colours, which are deliberately not theme tokens: a Windows icon is
# drawn once and shown against whatever the shell feels like today.
ICON_TOP = "#1B62C4"
ICON_BOTTOM = "#0B2545"
ICON_MARK = "#F2F9FF"
ICON_ACCENT = "#4FE0F5"


# ------------------------------------------------------------------- scale
# Everything that is not a colour, in device-independent pixels at 96 DPI. The window
# multiplies by its own scale factor; the panel writes these as CSS pixels. One table,
# so a card in the window and a card in Codex round their corners by the same amount.
RADII = {"card": 16, "control": 11, "chip": 999, "small": 7}
SPACING = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
# The notification-area popup's type sizes. The panel sets its own (TYPE_SCALE, below) and
# the settings window keeps the system message font, so this table is the popup's alone.
TYPE = {"title": 20, "heading": 14, "body": 12, "small": 11}
# Motion is a state, not decoration: the state light's glow is GLOW (below), and every
# recurring motion stops when a person has asked Windows to reduce motion. What is left here
# is the panel's control transitions. The shadows that were scalars here until v0.6.4 are
# SHADOWS, the panel's exact recipes.
MOTION = {"transition_ms": 160}


# ------------------------------------------------------------ v0.6.4: the panel, as data
# The Codex panel is the design the other two surfaces follow, and until v0.6.4 most of its
# numbers lived only in its stylesheet. The window and the popup could not read them, so each
# drew its own approximation of the same card - three surfaces that looked alike and were
# made of different stuff. These tables are the stylesheet's numbers, so they can be one.

# Type, in CSS px, as the panel sets it. The panel's only: the window keeps the system message
# font at its own sizes and the popup keeps TYPE, and both of those were decisions.
TYPE_SCALE = {"display": 21, "display_narrow": 20, "title": 15, "body": 14, "small": 12.5,
              "mono": 13, "badge": 12}
LINE_HEIGHT = {"display": 1.25, "title": 1.35, "body": 1.5, "small": 1.45, "bubble": 1.55}
# What each kind of text is set in: (TYPE_SCALE key, CSS weight).
TYPE_ROLES = {
    "display": ("display", 600), "title": ("title", 600), "heading": ("body", 600),
    "label": ("body", 500), "body": ("body", 400), "button": ("body", 500),
    "name": ("body", 600), "chip": ("small", 500), "help": ("small", 400),
    "count": ("small", 400), "mono": ("mono", 400),
}

# Sizes, in CSS px. A tuple is a padding in CSS shorthand order - top, right, bottom, left,
# a missing value repeating the one CSS would repeat - so the panel writes it as it stands and
# the window expands it with `padding()`.
LAYOUT = {
    "page_pad": (16, 14, 20),       # around the page of cards
    "page_gap": 14,                 # between cards
    "card_pad": (16, 18),
    "card_head_gap": 12,            # a card's heading and what sits beside it
    "card_first_gap": 6,            # the heading and the first thing under it
    "hero_pad": (16, 20),           # the state card at the top
    "hero_gap": 4,
    "savebar_pad": (10, 12),        # the save card at the bottom
    "row_pad": (11, 0),             # a setting: its name on the left, its control on the right
    "row_gap": 16,
    "tile_pad": (10, 12, 10, 14),   # a row tile: a pending task, the master switch
    "tile_gap": 8,
    "button_height": 34,
    "button_pad": (6, 16),
    "field_height": 35,             # a select or a number: a well
    "select_pad": (6, 34, 6, 12),
    "chevron_width": 10,            # the select's wedge, `muted`
    "chevron_height": 5,
    "chevron_right": 13,            # from the inside of the well's right border to the wedge
    "number_width": 88,
    "segment_height": 36,
    "segment_pad": (7, 8),
    "segment_gap": 6,
    "switch_width": 40,
    "switch_height": 22,
    "knob": 16,
    "knob_inset": 3,                # from the track's outer edge
    "knob_travel": 18,
    "chip_height": 22,
    "chip_pad_x": 9,
    "count_height": 20,
    "count_min_width": 24,
    "count_pad_x": 8,
    "well_pad": (12, 14),           # text in a well: the preview bubble, a text area
    "stored_pad": (9, 12),          # stored text: a well with no inner shadow
    "callout_pad": (10, 12),
    "callout_gap": 10,
    "callout_badge": 18,
    "nav_pad": (7, 14),             # a page tab or a section item (derived from the segment)
    "fold_chevron": 8,              # a fold's chevron arms, drawn 2px in `muted`
    "skeleton_height": 9,
    "skeleton_radius": 6,
    "focus_width": 2,
    "focus_offset": 2,
    "hairline": 1,
}

# Elevation, per theme and recipe: the panel's box-shadow lists as data. A Shadow is
# (dx, dy, blur, token, alpha, inset) in CSS px, listed front to back as CSS lists them, so
# the last is painted first. Light is the soft interface: a shadow down and right at a little
# over half strength and a highlight up and left. Dark is mostly the hairline - a shadow on a
# near-black ground is invisible at best and muddy at worst - so it keeps a faint drop and a
# one-pixel top light.
Shadow = namedtuple("Shadow", "dx dy blur token alpha inset")
SHADOWS = {
    "light": {
        "card": (Shadow(4, 4, 14, "shadow_dark", 0.55, False),
                 Shadow(-4, -4, 14, "shadow_light", 0.90, False)),
        "control": (Shadow(2, 2, 6, "shadow_dark", 0.45, False),
                    Shadow(-2, -2, 6, "shadow_light", 0.90, False)),
        "inset": (Shadow(2, 2, 6, "shadow_dark", 0.38, True),
                  Shadow(-2, -2, 6, "shadow_light", 0.50, True)),
    },
    "dark": {
        "card": (Shadow(0, 1, 2, "shadow_dark", 0.70, False),
                 Shadow(0, 6, 18, "shadow_dark", 0.35, False),
                 Shadow(0, 1, 0, "shadow_light", 0.45, True)),
        "control": (Shadow(0, 1, 2, "shadow_dark", 0.60, False),),
        "inset": (Shadow(0, 1, 2, "shadow_dark", 0.55, True),),
    },
}
# The card's own ground in CSS. Dark lifts a card a step toward `raised`; it is a stylesheet
# detail, because only the panel has a dark theme.
_CARD_GROUND = {"light": "var(--surface)",
                "dark": "color-mix(in srgb, var(--raised) 22%, var(--surface))"}

# ------------------------------------------------------------------- the status light
# A flat dot whose colour says what the watcher is doing, with a soft glow that says it is
# alive. The dot keeps the size each surface has always drawn; only its colour rule and its
# glow are decided here, once, for the window, the popup and the panel.
#
# Every state in which the watcher runs with recovery on is the brand's `active` cyan - the
# colour the dot had until v0.6.3 drew waiting and checking in blue. The word beside the dot
# and the motion tell those four apart. A stopped or unknown watcher and a pause keep the
# greys they have always had, with no glow at all; amber is for a watcher that runs and is not
# well, and red for a failure.
STATUS_DOT = {"window": 5, "popup": 4.5, "panel": 6, "mini": 4}   # radius, CSS px
STATUS_FILL = {"monitoring": "active", "waiting": "active", "checking": "active",
               "recovering": "active", "attention": "attention", "failed": "danger",
               "paused": "paused", "idle": "idle"}
# High Contrast: a solid dot in a system colour, never a glow.
STATUS_SYSTEM = {"monitoring": "Highlight", "waiting": "Highlight", "checking": "Highlight",
                 "recovering": "Highlight", "attention": "WindowText", "failed": "WindowText",
                 "paused": "GrayText", "idle": "GrayText"}
# The glow. It is a radial falloff around the dot, never a disc with an edge: its alpha is the
# frame's opacity times 1 at the dot's edge, NEAR_ALPHA at NEAR_AT of the way out, FAR_ALPHA
# at FAR_AT, and 0 at `reach` CSS px past the edge (times the display scale, and times the
# frame's scale). Breathing is a raised cosine - a sine with no corner at either end - with a
# low amplitude and a slow cycle, so it reads as a light that is on rather than one that blinks.
#
# The numbers were checked by eye before they were kept: monitoring at four phases, waiting,
# checking, recovering and attention, beside the v0.6.3 halo, at 100% and 200% on the light
# surface and canvas. The falloff shows no edge at either scale; monitoring's trough leaves the
# dot nearly bare and its peak is a soft ring about as wide as the dot; recovering and the one
# attention pulse read stronger without flashing. The flat v0.6.3 disc beside them looked like
# a sticker, which is what this replaces.
GLOW = {
    "reach": 7,
    "near_at": 0.35, "near_alpha": 0.55,
    "far_at": 0.70, "far_alpha": 0.20,
    "monitoring_ms": 3600, "monitoring_low": 0.14, "monitoring_high": 0.30,
    "monitoring_scale_low": 0.94, "monitoring_scale_high": 1.00,
    "recovering_ms": 2200, "recovering_low": 0.18, "recovering_high": 0.38,
    "recovering_scale_low": 0.96, "recovering_scale_high": 1.04,
    "still": 0.20,                  # waiting and checking, and attention once it has pulsed
    "attention_ms": 1400, "attention_peak": 0.42,
    # Checking also turns the arc every surface already drew: `arc_gap` past the dot's edge,
    # `arc_width` wide, `arc_sweep` degrees long, in `active` at `arc_alpha`. With motion
    # reduced it holds at `arc_still_at` degrees.
    "arc_ms": 1600, "arc_alpha": 0.55, "arc_gap": 3, "arc_width": 1.6, "arc_sweep": 100,
    "arc_still_at": 300,
}
GLOW_BREATHES = ("monitoring", "recovering")
GLOW_PULSES = ("attention", "failed")


def _number(value) -> str:
    """A number as a stylesheet or a C# literal writes it: 14, 12.5, 0.3."""
    value = round(float(value), 4)
    return "%d" % value if value.is_integer() else repr(value)


def _css_length(value) -> str:
    return "0" if value == 0 else "%spx" % _number(value)


def padding(key: str) -> tuple:
    """A LAYOUT padding as (top, right, bottom, left), expanded the way CSS expands it."""
    value = LAYOUT[key]
    if not isinstance(value, tuple):
        value = (value,)
    if len(value) == 1:
        return value * 4
    if len(value) == 2:
        return (value[0], value[1], value[0], value[1])
    if len(value) == 3:
        return (value[0], value[1], value[2], value[1])
    return tuple(value)


def css_scale() -> str:
    """The scale as CSS custom properties, for the panel's stylesheet.

    The glow's properties are all `--glow-*`, so the attention pulse's duration is
    `--glow-attention-ms` and never `--attention`: the palette already emits `--attention` as
    a colour on the same `:root`, and two custom properties with one name do not raise
    anything - the later declaration wins, the dark theme re-declares the colour, and an
    animation handed a colour for its duration simply does not run.

    `--type-*` is the panel's own type scale (TYPE_SCALE); the popup's TYPE is not a
    stylesheet's business. The glow's stops are written for the panel's dot, as lengths along
    the gradient's ray from the centre.
    """
    parts = []
    for prefix, table in (("radius", RADII), ("space", SPACING), ("type", TYPE_SCALE)):
        for name, value in table.items():
            parts.append("--%s-%s: %spx;" % (prefix, name.replace("_", "-"), _number(value)))
    for name, value in LINE_HEIGHT.items():
        parts.append("--lh-%s: %s;" % (name.replace("_", "-"), _number(value)))
    for name, value in LAYOUT.items():
        values = value if isinstance(value, tuple) else (value,)
        parts.append("--size-%s: %s;" % (name.replace("_", "-"),
                                          " ".join(_css_length(part) for part in values)))
    parts.append("--transition: %dms;" % MOTION["transition_ms"])
    dot = STATUS_DOT["panel"]
    parts.append("--glow-reach: %s;" % _css_length(GLOW["reach"]))
    for name, fraction in (("edge", 0.0), ("near", GLOW["near_at"]), ("far", GLOW["far_at"]),
                           ("outer", 1.0)):
        parts.append("--glow-%s: %s;" % (name, _css_length(dot + GLOW["reach"] * fraction)))
    parts.append("--glow-near-mix: %s%%;" % _number(GLOW["near_alpha"] * 100))
    parts.append("--glow-far-mix: %s%%;" % _number(GLOW["far_alpha"] * 100))
    for state in GLOW_BREATHES:
        parts.append("--glow-%s-ms: %dms;" % (state, GLOW[state + "_ms"]))
        for part in ("low", "high", "scale_low", "scale_high"):
            parts.append("--glow-%s-%s: %s;" % (state, part.replace("_", "-"),
                                                _number(GLOW["%s_%s" % (state, part)])))
        parts.append("--glow-%s-rest: %s;" % (state, _number(glow_rest(state))))
    parts.append("--glow-still: %s;" % _number(GLOW["still"]))
    parts.append("--glow-attention-ms: %dms;" % GLOW["attention_ms"])
    parts.append("--glow-attention-peak: %s;" % _number(GLOW["attention_peak"]))
    parts.append("--glow-arc-ms: %dms;" % GLOW["arc_ms"])
    parts.append("--glow-arc-mix: %s%%;" % _number(GLOW["arc_alpha"] * 100))
    return " ".join(parts)


def _theme_name(theme) -> str:
    if theme is LIGHT or theme == "light":
        return "light"
    if theme is DARK or theme == "dark":
        return "dark"
    raise ValueError("expected 'light' or 'dark', got %r" % (theme,))


def css_elevation(theme) -> str:
    """`--elev-card`, `--elev-control`, `--elev-inset` and `--card-ground` for one theme.

    `color-mix(in srgb, X p%, transparent)` is X at alpha p, which is what keeps the shadow's
    colour a token in the stylesheet rather than a number baked into it.
    """
    name = _theme_name(theme)
    parts = []
    for recipe, shadows in SHADOWS[name].items():
        parts.append("--elev-%s: %s;" % (recipe, ", ".join(
            "%s%s %s %s color-mix(in srgb, var(--%s) %d%%, transparent)" % (
                "inset " if shadow.inset else "", _css_length(shadow.dx), _css_length(shadow.dy),
                _css_length(shadow.blur), shadow.token.replace("_", "-"),
                int(round(shadow.alpha * 100)))
            for shadow in shadows)))
    parts.append("--card-ground: %s;" % _CARD_GROUND[name])
    return " ".join(parts)


_SIDES = ("left", "top", "right", "bottom")


def shadow_offset(shadow: Shadow, side: str) -> float:
    """How far a shadow is moved toward one side of its box, in CSS px.

    An outer shadow at (4, 4) lies 4px further out on the right and the bottom and 4px less
    far out on the left and the top. An inset shadow is the other way round: (2, 2) darkens
    the inside of the top and left edges.
    """
    if side not in _SIDES:
        raise ValueError("expected one of %s, got %r" % (", ".join(_SIDES), side))
    toward = {"left": -shadow.dx, "top": -shadow.dy, "right": shadow.dx, "bottom": shadow.dy}[side]
    return -toward if shadow.inset else toward


def shadow_alpha(shadow: Shadow, d: float, side: str, scale: float = 1.0) -> float:
    """One shadow's alpha `d` device px from a straight edge of its box.

    For an outer shadow `d` runs outward from the border's outer edge; for an inset one, inward
    from just inside the border. A CSS blur B is a Gaussian with sigma B/2, so the alpha is
    `alpha * Phi((offset - d) / sigma)`. Measured against the panel's own screenshot this is
    exact to about one colour level on straight edges; corners need the 2D version.
    """
    offset = shadow_offset(shadow, side) * scale
    sigma = shadow.blur * scale / 2.0
    if sigma <= 0:
        return shadow.alpha * (1.0 if offset > d else 0.5 if offset == d else 0.0)
    return shadow.alpha * 0.5 * math.erfc(-((offset - d) / sigma) / math.sqrt(2.0))


def elevation_colour(recipe: str, side: str, d: float, ground: str, theme="light",
                     scale: float = 1.0) -> tuple:
    """The colour `d` device px from one edge of a box with `recipe`, as unrounded (r, g, b).

    `ground` is a token or `#RRGGBB`: for an outer recipe, what the box stands on; for the
    inset recipe, the well's own fill. The list is painted back to front, as CSS paints it.
    """
    palette = LIGHT if _theme_name(theme) == "light" else DARK
    colour = [float(part) for part in rgb(palette.get(ground, ground))]
    for shadow in reversed(SHADOWS[_theme_name(theme)][recipe]):
        alpha = shadow_alpha(shadow, d, side, scale)
        colour = [part + (tone - part) * alpha for part, tone in zip(colour, rgb(palette[shadow.token]))]
    return tuple(colour)


def reach(recipe: str, theme="light", scale: float = 1.0) -> tuple:
    """How far a recipe's outer shadows reach past its box, as (left, top, right, bottom).

    Offset plus 1.5 blur, three sigmas, where a shadow is below a fifth of a percent of its
    strength; in device px at `scale`, rounded up. A container that clips its children closer
    than this cuts their shadow off. Inset shadows stay inside the box and reach nothing.
    """
    sides = []
    for side in _SIDES:
        far = 0.0
        for shadow in SHADOWS[_theme_name(theme)][recipe]:
            if not shadow.inset:
                far = max(far, shadow_offset(shadow, side) + 1.5 * shadow.blur)
        sides.append(int(math.ceil(far * scale - 1e-9)))
    return tuple(sides)


def status_fill(state) -> str:
    """The colour token a state's dot is filled with. Anything unknown is idle grey."""
    return STATUS_FILL.get(state, "idle")


def status_system(state) -> str:
    """The High Contrast system colour a state's dot is filled with."""
    return STATUS_SYSTEM.get(state, "GrayText")


def _breath(elapsed_ms, cycle_ms) -> float:
    """0 at the start of a cycle, 1 halfway, 0 again: a raised cosine."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * (elapsed_ms % cycle_ms) / cycle_ms)


def glow_rest(state) -> float:
    """The glow's still opacity, which is what reduced motion shows; 0 for no glow."""
    if state in GLOW_BREATHES:
        return (GLOW[state + "_low"] + GLOW[state + "_high"]) / 2
    if state in ("waiting", "checking") or state in GLOW_PULSES:
        return GLOW["still"]
    return 0.0


def glow(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """The glow around the status dot for one frame, or None when the state has none.

    `opacity` multiplies the falloff (see GLOW), `scale` multiplies the glow's outer radius,
    and `arc` is the checking arc's start angle in degrees, or None. `elapsed_ms` is any clock
    that does not run backwards; `since_entered_ms` is how long the state has been shown, and
    None means long enough that its one pulse is over. Paused, idle and unknown states have no
    glow; High Contrast draws none either, which is the caller's check.
    """
    if state in GLOW_BREATHES:
        if reduced:
            return {"opacity": glow_rest(state), "scale": 1.0, "arc": None}
        wave = _breath(elapsed_ms, GLOW[state + "_ms"])
        low, high = GLOW[state + "_low"], GLOW[state + "_high"]
        small, large = GLOW[state + "_scale_low"], GLOW[state + "_scale_high"]
        return {"opacity": low + (high - low) * wave, "scale": small + (large - small) * wave,
                "arc": None}
    if state == "waiting":
        return {"opacity": GLOW["still"], "scale": 1.0, "arc": None}
    if state == "checking":
        arc = (GLOW["arc_still_at"] if reduced
               else (elapsed_ms % GLOW["arc_ms"]) / GLOW["arc_ms"] * 360.0)
        return {"opacity": GLOW["still"], "scale": 1.0, "arc": arc}
    if state in GLOW_PULSES:
        opacity = GLOW["still"]
        if not reduced and since_entered_ms is not None and 0 <= since_entered_ms < GLOW["attention_ms"]:
            wave = _breath(since_entered_ms, GLOW["attention_ms"])
            opacity = GLOW["still"] + (GLOW["attention_peak"] - GLOW["still"]) * wave
        return {"opacity": opacity, "scale": 1.0, "arc": None}
    return None


def glow_moves(state, since_entered_ms=None, *, reduced=False) -> bool:
    """Whether a frame timer has anything to draw for this state."""
    if reduced:
        return False
    if state in GLOW_BREATHES or state == "checking":
        return True
    if state in GLOW_PULSES:
        return since_entered_ms is not None and 0 <= since_entered_ms < GLOW["attention_ms"]
    return False


def glow_stops(dot_radius: float) -> tuple:
    """The falloff as (fraction of the outer radius from the centre, alpha factor) stops.

    For a gradient filling the glow's whole disc; the first stop lies under the dot. GDI+
    path gradients count their positions from the edge inward, so the window reverses these.
    """
    outer = float(dot_radius + GLOW["reach"])
    return ((0.0, 1.0), (dot_radius / outer, 1.0),
            ((dot_radius + GLOW["reach"] * GLOW["near_at"]) / outer, GLOW["near_alpha"]),
            ((dot_radius + GLOW["reach"] * GLOW["far_at"]) / outer, GLOW["far_alpha"]),
            (1.0, 0.0))


def glow_radius(dot_radius: float, glow_scale: float = 1.0) -> float:
    """The glow's outer radius in CSS px for a frame's `scale`; times the display scale to draw."""
    return (dot_radius + GLOW["reach"]) * glow_scale


def glow_extent(dot_radius: float) -> float:
    """The largest outer radius any frame draws: the band a surface keeps free for the glow."""
    largest = max(1.0, *(GLOW[state + "_scale_high"] for state in GLOW_BREATHES))
    return glow_radius(dot_radius, largest)


def rgb(value: str) -> tuple[int, int, int]:
    """`#RRGGBB` to a byte triple."""
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError("expected #RRGGBB, got %r" % value)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def mix(one: str, other: str, amount: float) -> str:
    """`one` moved `amount` of the way toward `other`, per channel, rounded half up."""
    return "#%02X%02X%02X" % tuple(int(math.floor(a + (b - a) * amount + 0.5))
                                   for a, b in zip(rgb(one), rgb(other)))


def brighten(value: str, factor: float) -> str:
    """Every channel times `factor`, rounded half up and held at 255: CSS `brightness()`."""
    return "#%02X%02X%02X" % tuple(min(255, int(math.floor(channel * factor + 0.5)))
                                   for channel in rgb(value))


def _channel(byte: int) -> float:
    part = byte / 255.0
    return part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4


def luminance(value: str) -> float:
    red, green, blue = (_channel(channel) for channel in rgb(value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one: str, other: str) -> float:
    """WCAG contrast ratio, so the tests can assert readability rather than taste."""
    first, second = luminance(one), luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def css_variables(theme: dict) -> str:
    """`--name: #value;` pairs, in declaration order, for a stylesheet block.

    Token names are hyphenated on the way out, because that is what CSS custom
    properties look like everywhere else. Emitting `--on_accent` and then writing
    `var(--on-accent)` in the stylesheet is a mistake that produces no error at all:
    the property is simply unset and the text falls back to whatever it inherited.
    """
    return " ".join("--%s: %s;" % (name.replace("_", "-"), value)
                    for name, value in theme.items())
