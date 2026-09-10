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
    "muted":   "#5A6B7F",   # secondary text; 5.4:1 on the canvas
    "line":    "#DCE3EC",   # hairlines and card edges
    "surface": "#FFFFFF",   # cards
    "canvas":  "#F2F5F9",   # the window behind them
    "accent":  "#1257B8",   # anything to read or to click
    "on_accent": "#FFFFFF",  # text drawn *on* the accent, never on a page ground
    "active":  "#06B6D4",   # fill only: the watcher is running, work is in flight
    "idle":    "#94A3B8",   # fill only: stopped, nothing pending
    "attention": "#B45309",  # fill only: needs a person
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
    "accent":  "#5CA2EE",
    # Dark themes need a bright accent to stand off the surface, and a bright accent
    # cannot then carry white text: white on #5AA5F5 measures 2.6:1. So the text on the
    # accent is a token, not a literal, and it goes dark exactly when the accent goes
    # light. This was caught by the contrast test rather than by looking at it.
    "on_accent": "#08111C",
    "active":  "#35B5CC",
    "idle":    "#5F6E80",
    "attention": "#E09B57",
}

# The icon's own colours, which are deliberately not theme tokens: a Windows icon is
# drawn once and shown against whatever the shell feels like today.
ICON_TOP = "#1B62C4"
ICON_BOTTOM = "#0B2545"
ICON_MARK = "#F2F9FF"
ICON_ACCENT = "#4FE0F5"


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
