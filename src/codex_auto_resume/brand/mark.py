"""The mark: its own colours, its geometry, and the rasteriser everything is drawn from.

The mark's colours are deliberately not theme tokens - it is the same mark on a dark taskbar
and a light one - and the rasteriser is deterministic, because the `.ico`, the logos, the
vector master and the icon's motion frames are all drawn from it and have to agree.
"""
from __future__ import annotations

import math

from .colour import rgb


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
