"""The shadow model: the recipes as data, and what a shadow does to a pixel.

Two kinds of answer live here on purpose. A surface that can ask the system for a shadow gets
the recipe; a surface that draws its own - the popup, the card, the icon - gets the arithmetic,
from the same numbers, so depth is one decision rather than three.
"""
from __future__ import annotations

from collections import namedtuple
import math

from .colour import mix, rgb
from .tokens import palette, theme_name



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
