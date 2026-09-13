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
TYPE = {"title": 20, "heading": 14, "body": 12, "small": 11}
# A raised surface: a soft shadow offset down and right, a highlight up and left. Small
# on purpose - exaggerated embossing is the thing that makes soft interfaces unreadable.
ELEVATION = {"raised_blur": 14, "raised_offset": 4, "inset_blur": 6, "inset_offset": 2,
             "shadow_opacity": 0.55}
# Motion is a state, not decoration. Monitoring breathes slowly; a single attention pulse
# is quicker and happens once; nothing blinks. Every recurring motion stops when a
# person has asked Windows to reduce motion.
MOTION = {"breathe_ms": 2400, "attention_ms": 1200, "transition_ms": 160}
HALO = {"min_opacity": 0.12, "max_opacity": 0.34, "radius": 9}


def css_scale() -> str:
    """The scale as CSS custom properties, for the panel's stylesheet.

    The attention pulse is `--pulse`, not `--attention`: the palette already emits
    `--attention` as a colour on the same `:root`, and two custom properties with one name
    do not raise anything - the later declaration wins, the dark theme re-declares the
    colour, and an animation handed a colour for its duration simply does not run.
    """
    parts = []
    for prefix, table in (("radius", RADII), ("space", SPACING), ("type", TYPE)):
        for name, value in table.items():
            parts.append("--%s-%s: %spx;" % (prefix, name, value))
    parts.append("--breathe: %dms;" % MOTION["breathe_ms"])
    parts.append("--pulse: %dms;" % MOTION["attention_ms"])
    parts.append("--transition: %dms;" % MOTION["transition_ms"])
    parts.append("--halo-min: %s;" % HALO["min_opacity"])
    parts.append("--halo-max: %s;" % HALO["max_opacity"])
    return " ".join(parts)


def rgb(value: str) -> tuple[int, int, int]:
    """`#RRGGBB` to a byte triple."""
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError("expected #RRGGBB, got %r" % value)
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


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
