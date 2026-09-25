"""The palette: the identity ramp, the one brand colour, the two themes, and each design's colours.

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


# ------------------------------------------------------------------- v0.6.10: the designs
# The Design setting draws the same product three ways (brand/design.py says what else each
# draws). Soft is LIGHT and DARK above. Classic and Plain have their own, with LIGHT's key set
# exactly, so a surface swaps a design's colours the way it swaps a theme's. Nothing in them is
# read from Windows.
#
# Classic is what v0.6.2 shipped, read from the tag: `git show v0.6.2:src/codex_auto_resume/brand.py`
# (LIGHT and DARK, ten keys each). tests/test_brand.py holds the ten to that release's values, so no
# later change to Soft can move them. v0.6.2 filled a button with `surface` and a field with
# `canvas` and ringed the keyboard's focus in the accent, so `raised`, `inset` and `focus` are those.
# v0.6.2 had no quiet accent ground: Soft's carries v0.6.2's `muted` at 4.4:1, under the 4.5 every
# ground is held to, so Classic's is the accent a tenth of the way from white. The hover and pressed
# accents and the five state colours are Soft's. v0.6.2's dark was today's on the same ten keys.
CLASSIC_LIGHT = dict(LIGHT, **{
    "ink": "#0F1B2D", "muted": "#5A6B7F", "line": "#DCE3EC", "surface": "#FFFFFF", "canvas": "#F2F5F9",
    "raised": "#FFFFFF", "inset": "#F2F5F9", "accent": "#1257B8", "accent_soft": "#E7EEF8",
    "on_accent": "#FFFFFF", "focus": "#1257B8", "active": "#06B6D4", "idle": "#94A3B8",
    "attention": "#B45309",
})
CLASSIC_DARK = dict(DARK, **{"raised": "#191F29", "inset": "#0C1118", "focus": "#5CA2EE"})

# Plain: system-like neutral greys - fixed values, never Windows' own - with the product's accent,
# its state colours and its words, which are what make it this product rather than any window.
# The keyboard's focus is ringed in the ink.
PLAIN_LIGHT = dict(LIGHT, **{
    "ink": "#1B1B1B", "muted": "#5E5E5E", "line": "#E0E0E0", "surface": "#FFFFFF", "canvas": "#F3F3F3",
    "raised": "#FFFFFF", "inset": "#F3F3F3", "focus": "#1B1B1B",
})
PLAIN_DARK = dict(DARK, **{
    "ink": "#F3F3F3", "muted": "#ABABAB", "line": "#3D3D3D", "surface": "#2B2B2B", "canvas": "#202020",
    "raised": "#2B2B2B", "inset": "#1C1C1C", "focus": "#F3F3F3",
})
# Nothing draws a shadow in Classic or Plain; shadow_dark and shadow_light keep Soft's values there so
# every set has the same keys.

# Every design's colours, light first, by design name. The order is the setting's.
DESIGN_TOKENS = {"soft": (LIGHT, DARK),
                 "classic": (CLASSIC_LIGHT, CLASSIC_DARK), "plain": (PLAIN_LIGHT, PLAIN_DARK)}
DESIGNS = tuple(DESIGN_TOKENS)



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


def design_name(design) -> str:
    """One of DESIGNS, as given; anything else raises.

    A stored value that is not a design is the settings layer's to read as "soft" (settings.coerce)
    and a surface's to normalise before it asks; here a wrong name is a mistake in the code.
    """
    if isinstance(design, str) and design in DESIGN_TOKENS:
        return design
    raise ValueError("expected one of %s, got %r" % (", ".join(DESIGNS), design))


def palette(theme, design="soft") -> dict:
    """A design's colours in a theme: LIGHT or DARK for Soft, by theme name."""
    light, dark = DESIGN_TOKENS[design_name(design)]
    return dark if theme_name(theme) == "dark" else light
