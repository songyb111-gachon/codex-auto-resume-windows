"""The days of the year with a look of their own: one table, and the small marks they carry."""
from __future__ import annotations

import time

from .colour import rgb


# (month, day, the icon's body, its mark), every year.
FIXED_DAYS = (
    (1, 1, "#A67C1A", "sparkle"),
    (9, 6, "#C2553B", "confetti"),
    (12, 24, "#1F6B4A", "snow"),
    (12, 25, "#1F6B4A", "snow"),
)

# Lunar 1/1 and 8/15, as solar dates: KASI's calendar converter. Past the last year there is no look.
LUNAR_NEW_YEAR = ("#A32D2D", "sparkle", (
    (2026, 2, 17), (2027, 2, 7), (2028, 1, 27), (2029, 2, 13), (2030, 2, 3), (2031, 1, 23), (2032, 2, 11), (2033, 1, 31),
    (2034, 2, 19), (2035, 2, 8), (2036, 1, 28), (2037, 2, 15), (2038, 2, 4), (2039, 1, 24), (2040, 2, 12)))
HARVEST_MOON = ("#26215C", "moon", (
    (2026, 9, 25), (2027, 9, 15), (2028, 10, 3), (2029, 9, 22), (2030, 9, 12), (2031, 10, 1), (2032, 9, 19), (2033, 9, 8),
    (2034, 9, 27), (2035, 9, 16), (2036, 10, 4), (2037, 9, 24), (2038, 9, 13), (2039, 10, 2), (2040, 9, 21)))
LUNAR_DAYS = (LUNAR_NEW_YEAR, HARVEST_MOON)

# The marks in a square from -1 to 1, x to the right and y up: round dots (x, y, radius, colour), or a four-point star.
MOTIF_DOTS = {
    "confetti": ((-0.52, 0.42, 0.26, "#FFD76A"), (0.46, 0.56, 0.24, "#FFFFFF"), (0.14, -0.46, 0.28, "#FFB3C0")),
    "snow": ((-0.5, 0.36, 0.26, "#FFFFFF"), (0.42, 0.6, 0.22, "#FFFFFF"), (0.18, -0.42, 0.3, "#FFFFFF")),
    "moon": ((0.0, 0.0, 0.82, "#F6EBC9"),),
}
SPARKLE_COLOUR = "#FFE9A8"
SPARKLE_WAIST = 0.24
SPARKLE_POINTS = ((0.0, 1.0), (SPARKLE_WAIST, SPARKLE_WAIST), (1.0, 0.0), (SPARKLE_WAIST, -SPARKLE_WAIST),
                  (0.0, -1.0), (-SPARKLE_WAIST, -SPARKLE_WAIST), (-1.0, 0.0), (-SPARKLE_WAIST, SPARKLE_WAIST))

# Where the mark stands on the icon, in the icon's own square, and the smallest icon it can be told apart on.
MOTIF_ON_ICON = {"x": 0.66, "y": 0.66, "half": 0.3, "least": 24}


def day_look(year, month, day):
    """(the icon's body, its mark) for that date, or None for an ordinary day."""
    for fixed_month, fixed_day, body, motif in FIXED_DAYS:
        if (month, day) == (fixed_month, fixed_day):
            return (body, motif)
    for body, motif, dates in LUNAR_DAYS:
        if (year, month, day) in dates:
            return (body, motif)
    return None


def day_look_at(moment):
    """day_look for the local date at `moment`, seconds since the epoch."""
    local = time.localtime(moment)
    return day_look(local.tm_year, local.tm_mon, local.tm_mday)


def _in_star(x, y):
    inside = False
    points = SPARKLE_POINTS
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[index - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def motif_colour(motif, x, y):
    """The (red, green, blue) of `motif` at (x, y) in its square, or None where it is not."""
    if motif == "sparkle":
        return rgb(SPARKLE_COLOUR) if _in_star(x, y) else None
    for cx, cy, radius, colour in MOTIF_DOTS.get(motif, ()):
        if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2:
            return rgb(colour)
    return None
