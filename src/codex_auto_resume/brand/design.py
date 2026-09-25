"""The four designs: what each draws, and what moves in it, as data.

v0.6.10. The Design setting draws the same product four ways, and every surface reads the
difference from here rather than deciding it: the colours are tokens.py's (DESIGN_TOKENS), and
everything else a design changes is a yes or no below, or a radius.
"""
from __future__ import annotations

from .scale import RADII
from .tokens import design_name


# ------------------------------------------------------------------- the designs
# Five things a design decides, each yes or no:
#
#   depth       shadows, sunken wells and a card lifted a step off the canvas (dark); without it
#               a surface is its fill and its hairline
#   glow        the soft falloff round the status light while it breathes
#   breathes    the status light moves at all - its breath, and checking's turning arc
#   glides      the controls move when they change: a switch or a check box, a list rising open,
#               the scroll glide, and the notification card's entrance, exit and slide
#   accent_bar  v0.6.2's marks: a 3 px accent bar inside each card's left hairline, and the current
#               page's tab underlined in the accent
#
# Soft is the design every surface drew until this existed, and the default. Still is Soft with
# nothing moving - exactly what Reduce motion draws, as a look rather than an accessibility
# setting, and the only design that takes motion away. Classic is v0.6.2's flat cards with their
# accent bar and today's status light, and Plain is flat and grey; both move as Soft does - the
# light breathes, the switches and lists glide and the notification card rises in - except that
# Plain's light dims without a glow: the only gradient on any surface is the glow, so Plain has none.
#
# A design changes paint and never layout: every size, padding, dot and reserved shadow margin is
# the same in all four, and a radius is only ever smaller than Soft's, so nothing measured for Soft
# can overflow in another design. High Contrast replaces every design, and Reduce motion, Windows'
# animation setting and every other stopper stop motion in each: a design can only have less motion
# than they allow, never more.
DESIGN = {
    "soft":    {"depth": True,  "glow": True,  "breathes": True,  "glides": True,  "accent_bar": False},
    "still":   {"depth": True,  "glow": False, "breathes": False, "glides": False, "accent_bar": False},
    "classic": {"depth": False, "glow": True,  "breathes": True,  "glides": True,  "accent_bar": True},
    "plain":   {"depth": False, "glow": False, "breathes": True,  "glides": True,  "accent_bar": False},
}
# Corner radii, by RADII's roles. Classic's are v0.6.2's: an 8 px card and 7 px buttons, the small
# radius its 6 px fields' (v0.6.2:mcpui.py), and pills stay pills. Plain's are Windows 11's: 8 px for
# what stands alone and 4 px for a control.
DESIGN_RADII = {
    "soft": dict(RADII),
    "still": dict(RADII),
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


def design_breathes(design="soft") -> bool:
    """Whether the status light moves in a design, when nothing else holds it still."""
    return _rule(design, "breathes")


def design_glides(design="soft") -> bool:
    """Whether the controls and the card move when they change in a design, when nothing else holds them still."""
    return _rule(design, "glides")


def design_accent_bar(design="soft") -> bool:
    """Whether a design draws v0.6.2's accent bar on each card and underlines the current tab."""
    return _rule(design, "accent_bar")


def design_radii(design="soft") -> dict:
    """A design's corner radii, by RADII's roles, in CSS px."""
    return DESIGN_RADII[design_name(design)]


def light_moves(design="soft", *, stopped=False) -> bool:
    """Whether the status light moves: the design breathes, and nothing stops it (`stopped` is every
    stopper a surface knows of - Reduce motion, Windows' animation setting, High Contrast and the rest)."""
    return design_breathes(design) and not stopped


def controls_move(design="soft", *, stopped=False) -> bool:
    """Whether the controls and the card move when they change: the design glides, and nothing stops it."""
    return design_glides(design) and not stopped
