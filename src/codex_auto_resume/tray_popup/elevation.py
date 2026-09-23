"""The soft depth: how far a shadow reaches, and how much of each pixel it covers.

The masks are expensive and every one is remembered, because a popup that recomputed its own
shadows each frame would cost more than it draws.
"""
from __future__ import annotations

import math
from .. import brand


# v0.6.5: depth inside the card (requirement 11). Until then everything on the popup's card was
# flat - a tile was a lighter fill and a hairline - so the card looked neumorphic and its inside
# did not. Now what stands on the card is raised and what holds a value is sunken:
#
#   a task tile    lifts off the card: a soft drop under it and a light top edge;
#   the counts     sit in a well, as the panel's fields do (brand's `inset` fill and recipe);
#   an empty list  says so from a well too, and so does a failed read;
#   a button       sinks into a well while it is pressed (brand's `control` and `inset`), and a
#                  switch's track is a well - both as they were, now on a surface that has depth.
#
# The panel is the reference, so a tile is made of brand's own recipes and grounds only - no
# number of the popup's own. The card's recipe does not transfer (at its 14 px blur a tile eight
# pixels from the next would share one grey smear with it); the control recipe does, at a tile's
# scale, and it is the lift the panel already puts on what stands on its cards (buttons, segments):
#
#   light  brand's control lift: a short drop down and right, the white highlight up and left;
#   dark   a drop alone is invisible on a dark card at this size, so dark is the panel's dark
#          recipe: brand's control drop, the one-pixel top light of brand's dark card inside the
#          hairline, and `raised` for a ground - a step brighter than the card's own, the step the
#          panel's rows stand on.
#
# A tile's ground is `raised` in both themes, as the panel's rows and every resting button are: a
# ground of the tile's own put the tiles a step above 'Pause recovery' in dark, so the button looked
# sunk below them. When the panel's rows take the same lift, this belongs in brand.SHADOWS.
# High Contrast draws none of it: system colours, hairlines, no shadow. Nothing here moves.
DEPTH = {
    "light": {"tile": brand.shadows("control", "light")},
    "dark": {"tile": brand.shadows("control", "dark")
             + tuple(shadow for shadow in brand.shadows("card", "dark") if shadow.inset)},
}


def recipe_shadows(recipe, theme="light") -> tuple:
    """A recipe's shadows in `theme`: the tile's (DEPTH, made of brand's) or brand's own (brand.SHADOWS)."""
    theme = brand.theme_name(theme)
    own = DEPTH.get(theme, {}).get(recipe)
    return own if own is not None else brand.shadows(recipe, theme)


def tile_ground(theme="light") -> str:
    """A task tile's ground: brand's `raised`, as the panel's rows and a resting button stand on."""
    return brand.palette(theme)["raised"]


# ---------------------------------------------------------------------------- elevation
# The panel's raised and inset surfaces, as images GDI+ can stamp. A CSS blur B is a Gaussian
# with sigma B/2, and across a straight edge its coverage is Phi(-d / sigma) - what
# brand.shadow_alpha says - so every edge matches the panel to within a level. Round a corner
# the distance is taken to the rounded rectangle; against a true blur that is at most two and a
# half levels out at the card's corner, at a point the card itself covers. One byte of coverage
# a pixel, worked out once for a size and a scale.
_MASKS = {}


_MASK_LIMIT = 64


def _rounded_distance(x, y, half_width, half_height, radius) -> float:
    """Signed distance from a point to a rounded rectangle centred on the origin; inside is negative."""
    qx = abs(x) - (half_width - radius)
    qy = abs(y) - (half_height - radius)
    if qx > 0 and qy > 0:
        return math.hypot(qx, qy) - radius
    return max(qx, qy) - radius


def _blurred(distance, sigma) -> float:
    """How much of an edge blurred by `sigma` covers a point `distance` outside it."""
    if sigma <= 0:
        return max(0.0, min(1.0, 0.5 - distance))
    return 0.5 * math.erfc(distance / (sigma * math.sqrt(2.0)))


def _remember(key, mask):
    if len(_MASKS) >= _MASK_LIMIT:
        _MASKS.clear()
    _MASKS[key] = mask
    return mask


def lift_coverage(width, height, radius, blur) -> dict:
    """An outer shadow's shape: a rounded rectangle blurred by `blur`, in device pixels.

    The image is the body - never wider or taller than its two corners and one straight pixel
    between them - with `extent` pixels of blur on every side, so its middle row and column
    stand for a straight edge of any length and one image serves every body of its kind. It is
    symmetric: a quarter is worked out and the rest is its mirror. It is kept by the box it is
    made from, not the body, so a taller card or a wider button finds the image already made.
    """
    core = 2 * int(math.ceil(radius)) + 1
    box_w, box_h = min(width, core), min(height, core)
    radius = max(0.0, min(radius, box_w / 2.0, box_h / 2.0))
    key = ("lift", box_w, box_h, round(radius, 3), round(blur, 3))
    if key in _MASKS:
        return _MASKS[key]
    sigma = blur / 2.0
    extent = int(math.ceil(3 * sigma)) + 1
    image_w, image_h = box_w + 2 * extent, box_h + 2 * extent
    rows = [b""] * image_h
    for j in range((image_h + 1) // 2):
        y = j + 0.5 - image_h / 2.0
        row = bytearray(image_w)
        for i in range((image_w + 1) // 2):
            distance = _rounded_distance(i + 0.5 - image_w / 2.0, y, box_w / 2.0, box_h / 2.0, radius)
            row[i] = row[image_w - 1 - i] = int(_blurred(distance, sigma) * 255 + 0.5)
        rows[j] = rows[image_h - 1 - j] = bytes(row)
    return _remember(key, {"key": key, "width": image_w, "height": image_h,
                           "centre": (image_w // 2, image_h // 2), "extent": extent,
                           "coverage": b"".join(rows)})


def well_coverage(width, height, radius, blur, dx, dy) -> dict:
    """An inset shadow inside a box of `width` x `height`: how much of it shows at each pixel.

    CSS draws an inset shadow as everything outside the box, moved by (dx, dy) and blurred, cut
    to the box. The cut is in the coverage here, antialiased, so nothing has to be clipped. The
    middle row and column stand for a straight edge as in `lift_coverage`, with room for the
    offset and the blur; a well's light and dark shadows are one image turned round. Like a
    lift, it is kept by the box it is made from, which is the same box turned round.
    """
    sigma = blur / 2.0
    reach = int(math.ceil(radius)) + int(math.ceil(3 * sigma))
    box_w = min(width, 2 * (reach + int(math.ceil(abs(dx)))) + 1)
    box_h = min(height, 2 * (reach + int(math.ceil(abs(dy)))) + 1)
    radius = max(0.0, min(radius, box_w / 2.0, box_h / 2.0))
    key = ("well", box_w, box_h, round(radius, 3), round(blur, 3), round(dx, 3), round(dy, 3))
    if key in _MASKS:
        return _MASKS[key]
    turned = _MASKS.get(key[:5] + (round(-dx, 3), round(-dy, 3)))
    if turned is not None:
        return _remember(key, dict(turned, key=key, coverage=turned["coverage"][::-1]))
    half_w, half_h = box_w / 2.0, box_h / 2.0
    data = bytearray(box_w * box_h)
    for j in range(box_h):
        y = j + 0.5 - half_h
        for i in range(box_w):
            x = i + 0.5 - half_w
            inside = max(0.0, min(1.0, 0.5 - _rounded_distance(x, y, half_w, half_h, radius)))
            if inside > 0:
                hole = _blurred(_rounded_distance(x - dx, y - dy, half_w, half_h, radius), sigma)
                data[j * box_w + i] = int((1.0 - hole) * inside * 255 + 0.5)
    return _remember(key, {"key": key, "width": box_w, "height": box_h, "centre": (box_w // 2, box_h // 2),
                           "extent": 0, "coverage": bytes(data)})


def shadow_step(value) -> int:
    """A shadow's offset in whole device pixels, rounded away from zero so light and dark stay opposite."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))
