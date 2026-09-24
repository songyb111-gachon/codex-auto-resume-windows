"""The palette: the identity ramp, the one brand colour, and the two themes.

Every colour this product draws in either is one of these or is mixed from one. A surface that
invents a colour of its own has left the product, which is what makes this file worth reading
before any of the others.
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

# Dark is not light inverted. Three things were wrong the moment the themes were put side by
# side: the canvas and the surface were four points of lightness apart, so a card did not read
# as one; the hairline was darker than what it enclosed, which is the wrong direction on a dark
# ground; and the cyan at full saturation made an 11 px dot the brightest thing on screen -
# fluorescent rather than technical. So the surface is lifted away from the canvas, the line
# above the surface, and the cyan brought down in chroma while staying unmistakably cyan.
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
