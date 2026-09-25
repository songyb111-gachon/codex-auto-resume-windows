"""The three designs: what each draws, as data.

v0.6.10. The Design setting draws the same product three ways, and every surface reads the
difference from here rather than deciding it: the colours are tokens.py's (DESIGN_TOKENS), and
everything else a design changes is a yes or no below, or a radius.
"""
from __future__ import annotations

from .scale import RADII
from .tokens import design_name


# ------------------------------------------------------------------- the designs
# Three things a design decides, each yes or no:
#
#   depth       shadows, sunken wells and a card lifted a step off the canvas (dark); without it
#               a surface is its fill and its hairline
#   glow        the soft falloff round the status light while it breathes
#   accent_bar  v0.6.2's marks: a 3 px accent bar inside each card's left hairline, and the current
#               page's tab underlined in the accent
#
# Soft is the design every surface drew until this existed, and the default. Classic is v0.6.2's
# flat cards with their accent bar and today's status light, and Plain is flat and grey.
#
# What moves is not a design's to decide. Every design moves as Soft does - the light breathes, the
# switches and lists glide and the notification card rises in - except that Plain's light dims
# without a glow: the only gradient on any surface is the glow, so Plain has none. Since v0.6.11 the
# stoppers alone hold motion. v0.6.10's fourth design, Still, was Soft with nothing moving - exactly
# what Soft draws under Reduce motion - and two ways to one picture only confused, so a stored Still
# now reads as Soft with Reduce motion on (settings._migrate) and Reduce motion is the one switch.
#
# A design changes paint and never layout: every size, padding, dot and reserved shadow margin is
# the same in all three, and a radius is only ever smaller than Soft's, so nothing measured for Soft
# can overflow in another design. High Contrast replaces every design, and Reduce motion, Windows'
# animation setting and every other stopper stop motion in each.
DESIGN = {
    "soft":    {"depth": True,  "glow": True,  "accent_bar": False},
    "classic": {"depth": False, "glow": True,  "accent_bar": True},
    "plain":   {"depth": False, "glow": False, "accent_bar": False},
}
# Corner radii, by RADII's roles. Classic's are v0.6.2's: an 8 px card and 7 px buttons, the small
# radius its 6 px fields' (v0.6.2:mcpui.py), and pills stay pills. Plain's are Windows 11's: 8 px for
# what stands alone and 4 px for a control.
DESIGN_RADII = {
    "soft": dict(RADII),
    "classic": {"card": 8, "control": 7, "chip": 999, "small": 6, "check": 4},
    "plain": {"card": 8, "control": 4, "chip": 999, "small": 4, "check": 4},
}
ACCENT_BAR = 3              # CSS px: Classic's bar inside a card's left hairline, and its tab's underline

DEFAULT_DESIGN = "soft"


def _rule(design, axis) -> bool:
    return DESIGN[design_name(design)][axis]


def design_depth(design="soft") -> bool:
    """Whether a design draws shadows, wells and a lifted card. High Contrast draws none, whatever this says."""
    return _rule(design, "depth")


def design_glow(design="soft") -> bool:
    """Whether a design draws the glow round the status light while the light moves."""
    return _rule(design, "glow")


def design_accent_bar(design="soft") -> bool:
    """Whether a design draws v0.6.2's accent bar on each card and underlines the current tab."""
    return _rule(design, "accent_bar")


def design_radii(design="soft") -> dict:
    """A design's corner radii, by RADII's roles, in CSS px."""
    return DESIGN_RADII[design_name(design)]
