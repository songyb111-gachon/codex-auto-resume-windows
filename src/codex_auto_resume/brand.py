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

## Two themes, three surfaces (v0.6.4)

Until v0.6.4 only the Codex panel had a dark theme. Now the window and the notification-area
popup have one too, and the panel in dark is the reference they are held to: the same DARK
palette, the same dark elevation recipes, the same card ground. Every theme-dependent value is
reachable by theme name - `palette(theme)`, `shadows(recipe, theme)`, `card_ground(theme)`,
`status_colour(state, theme)`, `check_box(checked, enabled, theme)` - and the window gets the
dark half generated as `Brand.Dark`, a twin of `Brand` with the same names. Which theme is in
effect is the surfaces' business; High Contrast replaces both.
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

# The mark's shape, in a square whose half-size is 1, x to the right and y up: a rounded-square
# badge carrying an open ring with a round head at its leading end. Until v0.6.5 these numbers
# lived in assets/make_icon.py. The notification-area icon now draws its motion frames from them
# inside the watcher, so they live with the code that runs, and make_icon.py imports them: one
# geometry and one rasteriser for the .ico, the logos, the vector master and the icon's frames.
ICON_SHAPE = {
    "ring_inner": 0.34, "ring_outer": 0.53,
    # Counter-clockwise from the near end of the gap round to its far end: a 290 degree sweep
    # leaving a 70 degree opening at the top. The head sits at the far end, leading the ring.
    "arc_start": 125.0, "arc_end": 55.0,
    "head_radius": 0.155,
    "corner_large": 0.30, "corner_small": 0.24,
    # Below this size the corner radius drops: a 30% round on a 16 pixel square eats the mark.
    "corner_threshold": 32,
}
ICON_SUPERSAMPLE = 4


# ------------------------------------------------------------------- scale
# Everything that is not a colour, in device-independent pixels at 96 DPI. The window
# multiplies by its own scale factor; the panel writes these as CSS pixels. One table,
# so a card in the window and a card in Codex round their corners by the same amount.
RADII = {"card": 16, "control": 11, "chip": 999, "small": 7, "check": 5}
SPACING = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}
# The notification-area popup's type sizes. The panel sets its own (TYPE_SCALE, below) and
# the settings window keeps the system message font, so this table is the popup's alone.
TYPE = {"title": 20, "heading": 14, "body": 12, "small": 11}
# Motion is a state, not decoration: the state light's glow is GLOW (below), and every
# recurring motion stops when a person has asked Windows to reduce motion. What is left here
# is the controls' transitions. The shadows that were scalars here until v0.6.4 are
# SHADOWS, the panel's exact recipes.
#
# v0.6.5: a switch glides when it changes - its knob slides and its track cross-fades - on every
# surface, in `transition_ms`, on one curve: `ease`, a CSS cubic-bezier's four control numbers.
# It is an ease-out (easeOutCubic): the knob leaves at once and settles, so a switch answers the
# click the moment it is confirmed and still comes to rest softly. The panel writes it as
# `--transition-ease`, the window reads Brand.TransitionEase*, the popup calls ease(). A change
# that waits for a confirmation starts only once it is confirmed; nothing slides under Reduce
# motion, Windows' animation setting or High Contrast.
MOTION = {"transition_ms": 160, "ease": (0.33, 1.0, 0.68, 1.0)}


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
    # v0.6.4: the check box (CHECKBOX, below). The knob plus a hairline each side, so its inner
    # square is exactly the switch's knob; it fits inside the switch's height and inside one line
    # of body text, so a row of check boxes is never taller than a row with a switch.
    "check_size": 18,
    "check_gap": 10,                # from the box to its label, which is always on its right
    "check_stroke": 2,              # the check mark's line (CHECK_MARK)
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
# Dark's card recipe is not the same shape as light's: two drops in `shadow_dark` and an inset
# one-pixel top light in `shadow_light`, where light has one drop and one highlight. So a surface
# drawing dark reads each shadow's `inset` rather than inferring it from the recipe's name.

# The card's own ground: `surface` moved this fraction of the way toward `raised`. Dark lifts a
# card a step, because on a near-black canvas a surface that is only its own colour reads as a
# hole; light's card is its surface. The panel writes it as color-mix; the window and the popup
# fill with card_ground(theme), which is the same colour (no channel of it lands on a half, so
# CSS's rounding and brand.mix's agree).
CARD_LIFT = {"light": 0.0, "dark": 0.22}
_CARD_GROUND = {name: ("var(--surface)" if not lift else
                       "color-mix(in srgb, var(--raised) %d%%, var(--surface))" % int(round(lift * 100)))
                for name, lift in CARD_LIFT.items()}

# ------------------------------------------------------------------- the check box
# v0.6.4. A switch turns something that runs on or off; a check box picks which items of a list
# apply - which kinds of interruption may be recovered, which events notify. The same setting is
# the same kind on every surface, and a check box sits to the left of its label everywhere.
#
# It is the switch's material: unchecked it is the sunken well fields and switch tracks are (the
# `inset` fill with the inset elevation inside its border); checked it is the accent with an
# `on_accent` mark, as the switch's track and knob are. Its edge unchecked is `muted`, not `line`:
# the switch's off state is identified by its `muted` knob, and an empty box has nothing inside
# to do that - a `line` hairline on the card is 1.3:1, well under the 3:1 a control's boundary
# needs, so the box would all but vanish for some readers. Disabled, it is what a disabled field
# or button is here: a `surface` fill, a `line` hairline, no lift, and a `muted` mark if checked.
#
# Sizes are LAYOUT's check_size, check_gap and check_stroke and RADII's check. The keyboard focus
# ring is every control's: `focus`, LAYOUT focus_width, focus_offset outside the box, its corners
# following the box's. Each state's entries are palette tokens; `well` says whether the inset
# elevation is drawn inside the border.
CHECKBOX = {
    "off":          {"fill": "inset",   "edge": "muted",  "mark": None,        "well": True},
    "on":           {"fill": "accent",  "edge": "accent", "mark": "on_accent", "well": False},
    "off_disabled": {"fill": "surface", "edge": "line",   "mark": None,        "well": False},
    "on_disabled":  {"fill": "surface", "edge": "line",   "mark": "muted",     "well": False},
}
# High Contrast / forced colours: system colours by the names Windows Forms gives them (the popup
# and the window read these; the panel maps them through SYSTEM_CSS). Never a shadow.
CHECKBOX_SYSTEM = {
    "off":          {"fill": "Window",    "edge": "WindowText", "mark": None},
    "on":           {"fill": "Highlight", "edge": "Highlight",  "mark": "HighlightText"},
    "off_disabled": {"fill": "Window",    "edge": "GrayText",   "mark": None},
    "on_disabled":  {"fill": "Window",    "edge": "GrayText",   "mark": "GrayText"},
}
# The same system colours as CSS names them in `@media (forced-colors: active)`.
SYSTEM_CSS = {"Window": "Canvas", "WindowText": "CanvasText", "Highlight": "Highlight",
              "HighlightText": "HighlightText", "GrayText": "GrayText", "WindowFrame": "CanvasText",
              "Control": "Canvas"}
# The mark: a polyline's centre line - start, corner, end - in CSS px from the box's outer
# top-left corner (its border included), on the check_size box. Stroked check_stroke wide with
# flat ends and a mitred corner, which is exactly the outline check_mark_outline() returns and
# the panel clips with (`--check-mark-shape`). Both arms run at 45 degrees and meet at a right
# angle, the long arm twice the short one; the outline is centred across the box and sits a tenth
# of a pixel low, where the eye puts a tick's weight.
CHECK_MARK = ((4.5, 8.75), (7.5, 11.75), (13.5, 5.75))

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
# The light. Three cuts were wrong in three directions, and the user named each one: the first breathed a glow round
# a dot that never changed, 7 px of it - "너무 많이 커지는거 같아"; v0.6.5 made the dot itself blink, deep and quick -
# "너무 빠르게 깜빡이는거 같아 / 은은한 느낌이 있어야해 부드럽고"; v0.6.6 answered that by shrinking the swing, which
# is the wrong lever - "지금은 너무 안 보여". Then: "이번에는 상태등의 정석대로 해줘".
#
# So this is how a status light of this size is ordinarily built, and nothing of ours. The dot is 10 px across in the
# window, 12 in the panel, 9 in the popup, and at that size:
#
#   * colour says what the state is; motion only says the thing is alive. A state nobody waits on does not move;
#   * one cycle near a resting breath - `monitoring_ms`, four seconds, twelve to fifteen a minute. Quicker reads as a
#     blink, much slower as a light that has stopped;
#   * one symmetric cosine across the whole cycle, so the light is never not moving and has a corner nowhere;
#   * the dot dims and comes back: `low` of the light is left at the bottom, 62% of the colour as drawn, and the
#     glow carries the rest of the movement. Gentleness comes from the speed and the curve, not from a small swing,
#     which is what v0.6.6 got backwards - it shrank the swing and left nothing to see;
#   * the cosine is taken in light and raised to 1/`gamma` to be drawn, because a screen shows light unevenly and a
#     cosine walked straight along an alpha bunches at the top and rushes at the bottom;
#   * the glow rides the brightness rather than taking a turn of its own, and is a share of the dot rather than a
#     count of pixels: `reach_of_radius` of the radius at `peak` opacity at the top of the breath, gone at the
#     bottom. A flat 3 px, which is what this was until v0.6.6, is two thirds of the popup's radius and half of the
#     panel's - the same light in two strengths;
#   * the dot's size never changes. A 10 px disc that scales reads as jitter, not as breathing.
#
# Monitoring runs it every monitoring_ms, recovering every recovering_ms, and a problem once, in attention_ms, when
# it is first shown, then holds lit. A cycle begins and ends at rest - lit, no glow - so a light that starts moving
# leaves the still one with no jump. Waiting and checking hold lit with no glow (checking turns its arc), as does
# every light under Reduce motion or Windows' animation setting; High Contrast is a solid dot.
#
# The glow is a falloff, never a disc: at its peak, `peak` times `edge_alpha` at the dot's edge, `near_alpha` at
# `near_at` of the reach, `far_alpha` at `far_at`, nothing at the reach, straight between. A smaller spread is that
# falloff drawn smaller about the centre, so it grows out from under the dot; at most it reaches 8 CSS px from the
# window's dot centre, inside the 28 px column kept for it.
GLOW = {
    # The breath. `low` is how much light is left at the bottom of it, `gamma` turns light into what
    # an eye on a screen sees, `peak` is the glow's opacity at full brightness and `reach` how far it
    # gets past the dot's edge.
    "low": 0.35, "gamma": 2.2, "peak": 0.50, "reach_of_radius": 0.6,
    "edge_alpha": 0.67, "near_at": 0.14, "near_alpha": 0.58, "far_at": 0.66, "far_alpha": 0.50,
    "monitoring_ms": 4400, "recovering_ms": 2800, "attention_ms": 1400,
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
    stylesheet's business. The glow's stops, and `--glow-from` (its scale with no spread), are
    written for the panel's dot; `--glow-dot-low` is the dot's opacity at its darkest.
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
    parts.append("--transition-ease: %s;" % css_ease())
    dot, light = STATUS_DOT["panel"], GLOW
    parts.append("--glow-reach: %s;" % _css_length(glow_reach(dot)))
    for name, fraction in (("edge", 0.0), ("near", light["near_at"]), ("far", light["far_at"]),
                           ("outer", 1.0)):
        parts.append("--glow-%s: %s;" % (name, _css_length(dot + glow_reach(dot) * fraction)))
    for name in ("edge", "near", "far"):
        parts.append("--glow-%s-mix: %s%%;" % (name, _number(light[name + "_alpha"] * 100)))
    parts.append("--glow-from: %s;" % _number(dot / glow_extent(dot)))
    for state in GLOW_BREATHES:
        parts.append("--glow-%s-ms: %dms;" % (state, light[state + "_ms"]))
    parts.append("--glow-attention-ms: %dms;" % light["attention_ms"])
    parts.append("--glow-arc-ms: %dms;" % light["arc_ms"])
    parts.append("--glow-arc-mix: %s%%;" % _number(light["arc_alpha"] * 100))
    parts.append(css_check_box())
    return " ".join(parts)


GLOW_STOPS = 40             # keyframe stops a breath is written as: one every 2.5% of the cycle, which keeps the
                            # straight lines between them inside a thousandth of the curve


def css_glow_keyframes() -> str:
    """GLOW's breath as the panel's keyframes: `glow-dot`, the dot's opacity over the card, and `glow-spread`, the
    glow's opacity and scale.

    A keyframe selector cannot read a custom property and CSS has no cosine, so the curve is sampled here from
    glow_phase itself, every 5% of the cycle, and written out as stops. What the browser puts between two stops is a
    straight line across a twentieth of a four-second breath, which is below what an eye can see; sampling is what
    keeps the panel's light the same light as the window's rather than a hand-fitted lookalike.
    """
    dot, spread, extent = [], [], glow_extent(STATUS_DOT["panel"])
    for step in range(GLOW_STOPS + 1):
        fraction = step / float(GLOW_STOPS)
        dim, out = glow_phase(fraction)
        at = "%s%%" % _number(fraction * 100)
        dot.append("%s { opacity: %s; }" % (at, _number(1.0 - dim)))
        scale = glow_radius(STATUS_DOT["panel"], out) / extent
        spread.append("%s { opacity: %s; transform: scale(%s); }" % (at, _number(GLOW["peak"] * out), _number(scale)))
    return ("@keyframes glow-dot { %s }\n@keyframes glow-spread { %s }"
            % (" ".join(dot), " ".join(spread)))


def css_ease() -> str:
    """MOTION's curve as CSS writes it: cubic-bezier(0.33, 1, 0.68, 1)."""
    return "cubic-bezier(%s)" % ", ".join(_number(value) for value in MOTION["ease"])


def _bezier(a, b, t):
    """One coordinate of a CSS cubic-bezier from (0, 0) to (1, 1) through control values a and b."""
    return ((1.0 - 3.0 * b + 3.0 * a) * t + (3.0 * b - 6.0 * a)) * t * t + 3.0 * a * t


def _bezier_slope(a, b, t):
    return 3.0 * (1.0 - 3.0 * b + 3.0 * a) * t * t + 2.0 * (3.0 * b - 6.0 * a) * t + 3.0 * a


def ease(progress: float) -> float:
    """How far a transition has come, 0 to 1, after `progress` of its time: MOTION's curve.

    CSS's cubic-bezier, solved the way browsers solve it - a few Newton steps on the curve's x,
    then halving if they do not settle - so the window (Brand.Ease), the popup and the panel's
    stylesheet move a switch along the same path. Anything outside 0..1 is held at its end.
    """
    if not progress > 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    x1, y1, x2, y2 = MOTION["ease"]
    t = progress
    for _ in range(8):
        error = _bezier(x1, x2, t) - progress
        if abs(error) < 1e-7:
            return _bezier(y1, y2, t)
        slope = _bezier_slope(x1, x2, t)
        if abs(slope) < 1e-6:
            break
        t = min(1.0, max(0.0, t - error / slope))
    low, high, t = 0.0, 1.0, progress
    for _ in range(40):
        value = _bezier(x1, x2, t)
        if abs(value - progress) < 1e-7:
            break
        if value < progress:
            low = t
        else:
            high = t
        t = (low + high) / 2.0
    return _bezier(y1, y2, t)


def css_check_box() -> str:
    """The check box's custom properties, part of css_scale().

    `--check-<state>-<part>` for every CHECKBOX entry - `--check-off-fill: var(--inset);` - so a
    stylesheet that draws with them follows the table and the theme block that redefines the
    tokens. A custom property's var() is resolved on the element that declares it and inherited
    resolved, so these follow a theme only where the theme is stamped on that same element: the
    panel's `:root`, never a descendant.

    `--check-<state>-elev` is `var(--elev-inset)` where the well is drawn and `none` elsewhere.
    `--check-mark-shape` is the mark as a `clip-path` polygon on a box of `--size-check-size`,
    measured from its outer top-left corner - so the layer it clips covers the whole box, border
    included (an absolutely placed `::before` sits a hairline up and left of its padding box).
    The sizes themselves are the `--size-check-*` and `--radius-check` css_scale() writes.
    """
    parts = []
    for state, entry in CHECKBOX.items():
        name = state.replace("_", "-")
        for part in ("fill", "edge", "mark"):
            if entry[part] is not None:
                parts.append("--check-%s-%s: var(--%s);" % (name, part, entry[part].replace("_", "-")))
        parts.append("--check-%s-elev: %s;" % (name, "var(--elev-inset)" if entry["well"] else "none"))
    parts.append("--check-mark-shape: polygon(%s);" % ", ".join(
        "%spx %spx" % (_number(x), _number(y)) for x, y in check_mark_outline()))
    return " ".join(parts)


THEMES = ("light", "dark")


def theme_name(theme) -> str:
    """'light' or 'dark', from either name or from LIGHT or DARK themselves; anything else raises.

    'system' is not a theme here: a surface resolves it (Windows' app mode, or the host's colour
    scheme) before it asks for colours.
    """
    if theme is LIGHT or theme == "light":
        return "light"
    if theme is DARK or theme == "dark":
        return "dark"
    raise ValueError("expected 'light' or 'dark', got %r" % (theme,))


def palette(theme) -> dict:
    """LIGHT or DARK, by theme name."""
    return DARK if theme_name(theme) == "dark" else LIGHT


def shadows(recipe: str, theme="light") -> tuple:
    """A theme's elevation recipe - 'card', 'control' or 'inset' - front to back, as CSS lists it.

    Paint it back to front. Dark's card mixes outer shadows with an inset top light, so read each
    Shadow's `inset` rather than the recipe's name.
    """
    return SHADOWS[theme_name(theme)][recipe]


def card_ground(theme="light") -> str:
    """A card's own fill in a theme: `surface`, lifted CARD_LIFT of the way toward `raised`."""
    tokens = palette(theme)
    return mix(tokens["surface"], tokens["raised"], CARD_LIFT[theme_name(theme)])


def status_colour(state, theme="light") -> str:
    """The `#RRGGBB` a state's dot and glow are drawn in, in a theme (status_fill's token)."""
    return palette(theme)[status_fill(state)]


def check_box_state(checked, enabled=True) -> str:
    """The CHECKBOX key for a box: 'off', 'on', 'off_disabled' or 'on_disabled'."""
    return ("on" if checked else "off") + ("" if enabled else "_disabled")


def check_box(checked, enabled=True, theme="light") -> dict:
    """A check box's colours in a theme: `fill`, `edge` and `mark` as `#RRGGBB` (`mark` None when
    there is none) and `well`, whether the inset elevation is drawn inside the border."""
    entry, tokens = CHECKBOX[check_box_state(checked, enabled)], palette(theme)
    return {"fill": tokens[entry["fill"]], "edge": tokens[entry["edge"]],
            "mark": tokens[entry["mark"]] if entry["mark"] else None, "well": entry["well"]}


def check_box_system(checked, enabled=True) -> dict:
    """The same box in High Contrast: `fill`, `edge` and `mark` as Windows system colour names."""
    return dict(CHECKBOX_SYSTEM[check_box_state(checked, enabled)])


def css_system(name: str) -> str:
    """A Windows system colour name as CSS's forced-colors keyword (WindowText is CanvasText)."""
    return SYSTEM_CSS[name]


def check_mark(scale: float = 1.0, left: float = 0.0, top: float = 0.0) -> tuple:
    """The mark's centre line - start, corner, end - in device px for a box whose outer top-left
    corner is at (left, top); stroke it LAYOUT check_stroke * scale wide, flat ends, mitred."""
    return tuple((left + x * scale, top + y * scale) for x, y in CHECK_MARK)


def check_mark_outline(scale: float = 1.0, left: float = 0.0, top: float = 0.0) -> tuple:
    """The stroked mark as a filled polygon: six points, the outer side first from the start.

    Flat ends and a mitred corner, so filling this is exactly stroking check_mark(): the panel
    clips with it, and a surface without a pen that mitres can fill it instead.
    """
    (x0, y0), (x1, y1), (x2, y2) = CHECK_MARK
    half = LAYOUT["check_stroke"] / 2.0

    def normal(ax, ay, bx, by):
        length = math.hypot(bx - ax, by - ay)
        return (-(by - ay) / length, (bx - ax) / length)

    n1, n2 = normal(x0, y0, x1, y1), normal(x1, y1, x2, y2)
    joint = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
    mitre = (half * (n1[0] + n2[0]) / joint, half * (n1[1] + n2[1]) / joint)
    points = ((x0 + half * n1[0], y0 + half * n1[1]), (x1 + mitre[0], y1 + mitre[1]),
              (x2 + half * n2[0], y2 + half * n2[1]), (x2 - half * n2[0], y2 - half * n2[1]),
              (x1 - mitre[0], y1 - mitre[1]), (x0 - half * n1[0], y0 - half * n1[1]))
    return tuple((left + x * scale, top + y * scale) for x, y in points)


def css_elevation(theme) -> str:
    """`--elev-card`, `--elev-control`, `--elev-inset` and `--card-ground` for one theme.

    `color-mix(in srgb, X p%, transparent)` is X at alpha p, which is what keeps the shadow's
    colour a token in the stylesheet rather than a number baked into it.
    """
    name = theme_name(theme)
    parts = []
    for recipe, listed in SHADOWS[name].items():
        parts.append("--elev-%s: %s;" % (recipe, ", ".join(
            "%s%s %s %s color-mix(in srgb, var(--%s) %d%%, transparent)" % (
                "inset " if shadow.inset else "", _css_length(shadow.dx), _css_length(shadow.dy),
                _css_length(shadow.blur), shadow.token.replace("_", "-"),
                int(round(shadow.alpha * 100)))
            for shadow in listed)))
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
                     scale: float = 1.0, inside=None) -> tuple:
    """The colour `d` device px from one edge of a box with `recipe`, as unrounded (r, g, b).

    `ground` is a token or `#RRGGBB`: outside the box, what the box stands on; inside it, the
    box's own fill. `inside` says which side of the edge `d` runs: None means inside for a recipe
    whose every shadow is inset (the well) and outside for any other. Only the shadows on that
    side are applied - dark's card has an inset top light that never reaches outside it. The list
    is painted back to front, as CSS paints it.
    """
    tokens, recipe_shadows = palette(theme), shadows(recipe, theme)
    if inside is None:
        inside = all(shadow.inset for shadow in recipe_shadows)
    colour = [float(part) for part in rgb(tokens.get(ground, ground))]
    for shadow in reversed(recipe_shadows):
        if shadow.inset != bool(inside):
            continue
        alpha = shadow_alpha(shadow, d, side, scale)
        colour = [part + (tone - part) * alpha for part, tone in zip(colour, rgb(tokens[shadow.token]))]
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
        for shadow in SHADOWS[theme_name(theme)][recipe]:
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


def glow_floor() -> float:
    """What the dot is drawn at when the breath is at its lowest: `low` of the light, as it is seen."""
    return GLOW["low"] ** (1.0 / GLOW["gamma"])


def glow_phase(fraction):
    """The light at `fraction` of one breath, 0 to 1, as (dim, spread): how far the dot is drawn toward the ground it
    sits on (0 at rest) and how far out the glow is (0 none, 1 its peak).

    One cosine, symmetric, running the whole cycle: there is no moment the light is not moving, which is what a breath
    is and a blink is not. The cosine is taken in light and then raised to 1/gamma, because a screen shows light
    unevenly - fading a colour's alpha straight along a cosine bunches at the top and rushes at the bottom, and the
    same curve taken this way is even to look at. The glow rides the brightness rather than following it as its own
    phase: it is out when the dot is lit, gone when the dot is low, and squared so it stays near the top of the
    breath instead of hanging around the middle.
    """
    breath = 0.5 + 0.5 * math.cos(2.0 * math.pi * (fraction % 1.0))            # 1 at rest, 0 at the low
    lit = (GLOW["low"] + (1.0 - GLOW["low"]) * breath) ** (1.0 / GLOW["gamma"])
    floor = glow_floor()
    risen = (lit - floor) / (1.0 - floor)
    return 1.0 - lit, risen * risen


def glow(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """The status light for one frame, or None when it is off (paused, idle, unknown: a grey dot and nothing else).

    `dim` is how far the dot is drawn from its colour toward the ground under it, `opacity` multiplies the glow's
    falloff (glow_stops), `spread` is how far out it is (glow_radius) and `arc` is the checking arc's start angle in
    degrees, or None. `elapsed_ms` is any clock that does not run backwards; `since_entered_ms` is how long the state
    has been shown, None meaning long enough that its one pulse is over. High Contrast neither dims the dot nor draws
    a glow, which is the caller's check.
    """
    fraction = arc = None
    if state in GLOW_BREATHES:
        fraction = None if reduced else (elapsed_ms % GLOW[state + "_ms"]) / GLOW[state + "_ms"]
    elif state == "checking":
        arc = GLOW["arc_still_at"] if reduced else (elapsed_ms % GLOW["arc_ms"]) / GLOW["arc_ms"] * 360.0
    elif state in GLOW_PULSES:
        if not reduced and since_entered_ms is not None and 0 <= since_entered_ms < GLOW["attention_ms"]:
            fraction = since_entered_ms / GLOW["attention_ms"]
    elif state != "waiting":
        return None
    dim, spread = (0.0, 0.0) if fraction is None else glow_phase(fraction)
    return {"dim": dim, "opacity": GLOW["peak"] * spread, "spread": spread, "arc": arc}


def glow_moves(state, since_entered_ms=None, *, reduced=False) -> bool:
    """Whether a frame timer has anything to draw for this state."""
    if reduced:
        return False
    if state in GLOW_BREATHES or state == "checking":
        return True
    if state in GLOW_PULSES:
        return since_entered_ms is not None and 0 <= since_entered_ms < GLOW["attention_ms"]
    return False


def glow_reach(dot_radius: float) -> float:
    """How far past the dot's edge the glow gets at the top of the breath: a share of the dot, so the window's
    10 px light and the panel's 12 px one are the same light at two sizes."""
    return GLOW["reach_of_radius"] * dot_radius


def glow_stops(dot_radius: float) -> tuple:
    """The falloff as (fraction of the outer radius from the centre, alpha factor) stops, for a gradient filling the
    glow's disc at any spread; the first two lie under the dot. GDI+ path gradients count their positions from the
    edge inward, so the window and the popup reverse these."""
    outer, reach = float(glow_extent(dot_radius)), glow_reach(dot_radius)
    return ((0.0, GLOW["edge_alpha"]), (dot_radius / outer, GLOW["edge_alpha"]),
            ((dot_radius + reach * GLOW["near_at"]) / outer, GLOW["near_alpha"]),
            ((dot_radius + reach * GLOW["far_at"]) / outer, GLOW["far_alpha"]),
            (1.0, 0.0))


def glow_radius(dot_radius: float, spread: float = 1.0) -> float:
    """The glow's outer radius in CSS px for a frame's `spread`; times the display scale to draw."""
    return dot_radius + glow_reach(dot_radius) * spread


def glow_extent(dot_radius: float) -> float:
    """The largest outer radius any frame draws: the band a surface keeps free for the glow."""
    return glow_radius(dot_radius, 1.0)


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


# ------------------------------------------------------------------- the mark, rasterised
# Deterministic and standard-library only, so a release build and the watcher draw identical
# pixels on any machine. A pixel is ICON_SUPERSAMPLE squared samples; each sample is the head,
# the ring, or the badge's vertical gradient, and the pixel is their integer average with an
# alpha of how many fell on the badge. assets/make_icon.py writes the .ico, the logos and the
# vector master from here; tray.py composes the notification-area icon's motion frames from here.

def icon_rounded_square(x, y, radius):
    """Signed distance to a rounded square centred on (0, 0) with half-size 1; negative inside.

    A distance rather than a boolean because the dark logo needs to know how close to the edge
    it is, to draw a rim there.
    """
    half = 1.0 - radius
    dx = max(abs(x) - half, 0.0)
    dy = max(abs(y) - half, 0.0)
    if abs(x) > 1.0 or abs(y) > 1.0:
        return 1.0
    return math.hypot(dx, dy) - radius


def icon_ring_arc(x, y, inner, outer, start, end):
    """True inside an annulus sector, angles in radians measured counter-clockwise."""
    distance = math.hypot(x, y)
    if not (inner <= distance <= outer):
        return False
    angle = math.atan2(y, x) % (2 * math.pi)
    start %= 2 * math.pi
    end %= 2 * math.pi
    if start <= end:
        return start <= angle <= end
    return angle >= start or angle <= end


def icon_head_centre(angle=None):
    """The head's centre on the stroke's centre line, at `angle` degrees (the sweep's end by default)."""
    middle = (ICON_SHAPE["ring_inner"] + ICON_SHAPE["ring_outer"]) / 2.0
    radians = math.radians(ICON_SHAPE["arc_end"] if angle is None else angle)
    return (middle * math.cos(radians), middle * math.sin(radians))


def icon_head_box(size, angle=None):
    """The pixels (left, top, right, bottom) a head at `angle` can touch in a `size` icon."""
    x, y = icon_head_centre(angle)
    reach = ICON_SHAPE["head_radius"]
    return (max(0, int(math.floor((x - reach + 1.0) / 2.0 * size))),
            max(0, int(math.floor((1.0 - (y + reach)) / 2.0 * size))),
            min(size, int(math.ceil((x + reach + 1.0) / 2.0 * size))),
            min(size, int(math.ceil((1.0 - (y - reach)) / 2.0 * size))))


def icon_samples(size, rim=0.0, *, head_angle=None, head=True, box=None):
    """The mark's samples, pixel by pixel: rows of (covered, heads, red, green, blue).

    `covered` is how many of a pixel's samples fall on the badge, `heads` how many of those are
    the head, and red, green and blue the summed colour of the others - the ring, the badge's
    gradient, or the rim. Kept apart so the head can be given any colour afterwards
    (icon_pixel) with exactly the arithmetic a whole render uses. `head=False` leaves the head
    out altogether; `box` limits the work to (left, top, right, bottom).
    """
    shape = ICON_SHAPE
    steps = ICON_SUPERSAMPLE
    scale = size * steps
    radius = shape["corner_large"] if size >= shape["corner_threshold"] else shape["corner_small"]
    top_colour, bottom_colour, mark = rgb(ICON_TOP), rgb(ICON_BOTTOM), rgb(ICON_MARK)
    inner, outer = shape["ring_inner"], shape["ring_outer"]
    start, end = math.radians(shape["arc_start"]), math.radians(shape["arc_end"])
    head_x, head_y = icon_head_centre(head_angle)
    head_radius = shape["head_radius"]
    left, top, right, bottom = box if box is not None else (0, 0, size, size)
    rows = []
    for py in range(top, bottom):
        row = []
        for px in range(left, right):
            covered = heads = red = green = blue = 0
            for sy in range(steps):
                fy = (py * steps + sy + 0.5) / scale * 2.0 - 1.0
                for sx in range(steps):
                    fx = (px * steps + sx + 0.5) / scale * 2.0 - 1.0
                    distance = icon_rounded_square(fx, fy, radius)
                    if distance > 0.0:
                        continue
                    covered += 1
                    if head and math.hypot(fx - head_x, -fy - head_y) <= head_radius:
                        heads += 1
                        continue
                    if icon_ring_arc(fx, -fy, inner, outer, start, end):
                        colour = mark
                    elif rim and distance >= -rim:
                        colour = top_colour
                    else:
                        position = (fy + 1.0) / 2.0
                        colour = tuple(round(x + (y - x) * position) for x, y in zip(top_colour, bottom_colour))
                    red += colour[0]
                    green += colour[1]
                    blue += colour[2]
            row.append((covered, heads, red, green, blue))
        rows.append(row)
    return rows


def icon_pixel(sample, head_colour) -> tuple:
    """One (red, green, blue, alpha) pixel from icon_samples, with the head in `head_colour`."""
    covered, heads, red, green, blue = sample
    if covered == 0:
        return (0, 0, 0, 0)
    return ((red + heads * head_colour[0]) // covered, (green + heads * head_colour[1]) // covered,
            (blue + heads * head_colour[2]) // covered,
            covered * 255 // (ICON_SUPERSAMPLE * ICON_SUPERSAMPLE))


def icon_render(size: int, rim: float = 0.0) -> bytes:
    """Raw RGBA bytes for one square icon: the mark exactly as the .ico and the logos carry it.

    `rim` draws a hairline of the badge's own top colour just inside the edge, as a fraction of
    the half-size. The deep blue badge has plenty of contrast on a light page and almost none on
    a near-black one, so the dark logo lifts itself off the ground rather than relying on a
    ground it cannot see.
    """
    head = rgb(ICON_ACCENT)
    return b"".join(bytes(part for sample in row for part in icon_pixel(sample, head))
                    for row in icon_samples(size, rim))
