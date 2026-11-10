"""The days of the year with a look of their own: one table, the icon's mark and the popup's scene, as plain shapes."""
from __future__ import annotations

import math
import re
import time

from .colour import rgb


# The icon's body, top to bottom, and the scene's ground.
DAY_LOOKS = {
    "birthday": ("#EE8468", "#9E3A4B", "#FFEADF"),
    "new_year": ("#2F3D8F", "#C9942B", "#1B2559"),
    "christmas": ("#2E8B5E", "#0F4A36", "#12442F"),
    "seollal": ("#D2453E", "#7A1F2B", "#FFF4E2"),
    "chuseok": ("#2B2F77", "#12143F", "#1C1F55"),
}

# (month, day, look), every year.
FIXED_DAYS = (
    (1, 1, "new_year"),
    (9, 6, "birthday"),
    (12, 24, "christmas"),
    (12, 25, "christmas"),
)

# Lunar 1/1 and 8/15, as solar dates: KASI's calendar converter. Past the last year there is no look.
LUNAR_DAYS = (
    ("seollal", ((2026, 2, 17), (2027, 2, 7), (2028, 1, 27), (2029, 2, 13), (2030, 2, 3), (2031, 1, 23), (2032, 2, 11),
                 (2033, 1, 31), (2034, 2, 19), (2035, 2, 8), (2036, 1, 28), (2037, 2, 15), (2038, 2, 4), (2039, 1, 24),
                 (2040, 2, 12))),
    ("chuseok", ((2026, 9, 25), (2027, 9, 15), (2028, 10, 3), (2029, 9, 22), (2030, 9, 12), (2031, 10, 1), (2032, 9, 19),
                 (2033, 9, 8), (2034, 9, 27), (2035, 9, 16), (2036, 10, 4), (2037, 9, 24), (2038, 9, 13), (2039, 10, 2),
                 (2040, 9, 21))),
)

# The icon's mark shows from this size up; below it the body alone.
MOTIF_LEAST = 24
SCENE_WIDTH, SCENE_HEIGHT = 190.0, 66.0
# Where each scene's main piece begins, in its 190: all from there rightward is shown whole, or the scene is not shown at all.
SCENE_FOCUS = {"birthday": 142.0, "new_year": 122.0, "christmas": 117.0, "seollal": 127.0, "chuseok": 126.0}
# A scene narrowed to fit stands on its ground; the one that hangs from the top hangs from it.
SCENE_FROM_TOP = ("seollal",)


def day_look(year, month, day):
    """The look of that date, a key of DAY_LOOKS, or None for an ordinary day."""
    for fixed_month, fixed_day, look in FIXED_DAYS:
        if (month, day) == (fixed_month, fixed_day):
            return look
    for look, dates in LUNAR_DAYS:
        if (year, month, day) in dates:
            return look
    return None


def day_look_at(moment):
    """day_look for the local date at `moment`, seconds since the epoch."""
    local = time.localtime(moment)
    return day_look(local.tm_year, local.tm_mon, local.tm_mday)


# ------------------------------------------------------------------ a path, as points
_TOKEN = re.compile(r"[MmLlHhVvQqTtZz]|-?(?:\d+\.?\d*|\.\d+)")
_ARGUMENTS = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "T": 2, "Z": 0}


def path_points(path, steps=8):
    """An SVG path of M, L, H, V, Q, T and Z, flattened: a list of subpaths, each a list of (x, y)."""
    tokens = _TOKEN.findall(path)
    subpaths, points = [], []
    x = y = start_x = start_y = 0.0
    control = None
    at, command = 0, None
    while at < len(tokens):
        if tokens[at].isalpha():
            command = tokens[at]
            at += 1
            if command in "Zz":
                points.append((start_x, start_y))
                x, y = start_x, start_y
                control = None
                continue
        upper, relative = command.upper(), command.islower()
        values = [float(value) for value in tokens[at:at + _ARGUMENTS[upper]]]
        at += _ARGUMENTS[upper]
        base_x, base_y = (x, y) if relative else (0.0, 0.0)
        if upper == "M":
            if points:
                subpaths.append(points)
            x, y = base_x + values[0], base_y + values[1]
            start_x, start_y = x, y
            points = [(x, y)]
            command = "l" if relative else "L"
            control = None
        elif upper in "LHV":
            if upper == "H":
                x = base_x + values[0]
            elif upper == "V":
                y = base_y + values[0]
            else:
                x, y = base_x + values[0], base_y + values[1]
            points.append((x, y))
            control = None
        else:
            if upper == "Q":
                cx, cy, end_x, end_y = base_x + values[0], base_y + values[1], base_x + values[2], base_y + values[3]
            else:
                cx, cy = (2 * x - control[0], 2 * y - control[1]) if control else (x, y)
                end_x, end_y = base_x + values[0], base_y + values[1]
            for step in range(1, steps + 1):
                t = step / float(steps)
                points.append(((1 - t) ** 2 * x + 2 * (1 - t) * t * cx + t * t * end_x,
                               (1 - t) ** 2 * y + 2 * (1 - t) * t * cy + t * t * end_y))
            x, y, control = end_x, end_y, (cx, cy)
    if points:
        subpaths.append(points)
    return subpaths


def _rotated(points, degrees, px, py):
    radians = math.radians(degrees)
    c, s = math.cos(radians), math.sin(radians)
    return [(px + (x - px) * c - (y - py) * s, py + (x - px) * s + (y - py) * c) for x, y in points]


def _box(x, y, w, h):
    return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]


# ------------------------------------------------------------------ the icon's mark, in the icon's 32 by 32
def _mark_star():
    return path_points("M25.5 2l1 3.5 3.5 1-3.5 1-1 3.5-1-3.5-3.5-1 3.5-1z", 1)[0]


MARKS = {
    "birthday": (("poly", _rotated(_box(21, 3, 3.4, 6), 25, 22, 6), "#FFD76A"), ("circle", 27, 9.5, 1.7, "#FFFFFF"),
                 ("poly", _rotated(_box(25, 2.5, 3, 5), -30, 26, 5), "#FFB3C0")),
    "new_year": (("poly", _mark_star(), "#FFE9A8"),),
    "christmas": (("line", 25.5, 2.5, 25.5, 10.5, 1.1, "#FFFFFF"), ("line", 21.8, 4.5, 29.2, 8.5, 1.1, "#FFFFFF"),
                  ("line", 21.8, 8.5, 29.2, 4.5, 1.1, "#FFFFFF")),
    "seollal": tuple(("poly", _box(2, 23.5 + index * 1.5, 28, 1.5), colour)
                     for index, colour in enumerate(("#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0"))),
    "chuseok": (("circle", 25.5, 6.5, 4.0, "#F6E7B4"), ("circle", 24.2, 5.6, 0.8, "#E2CF96")),
}


def _inside(points, x, y):
    inside = False
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[index - 1]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _on_line(x, y, x1, y1, x2, y2, width):
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return (x - x1 - t * dx) ** 2 + (y - y1 - t * dy) ** 2 <= width * width / 4.0


def mark_colour(look, x, y):
    """The (red, green, blue) of `look`'s mark at (x, y) in the icon's 32 by 32, or None where it is not."""
    found = None
    for shape in MARKS[look]:
        kind = shape[0]
        if kind == "poly":
            hit = _inside(shape[1], x, y)
        elif kind == "circle":
            hit = (x - shape[1]) ** 2 + (y - shape[2]) ** 2 <= shape[3] ** 2
        else:
            hit = _on_line(x, y, shape[1], shape[2], shape[3], shape[4], shape[5])
        if hit:
            found = shape[-1]
    return rgb(found) if found else None


# ------------------------------------------------------------------ the scene, in its 190 by 66
class _Seeded:
    """The same numbers every time: a scene is the same scene every time it is drawn."""

    def __init__(self, seed):
        self.value = seed

    def __call__(self, low, high):
        self.value = (self.value * 1103515245 + 12345) & 0x7FFFFFFF
        return low + (high - low) * self.value / 0x7FFFFFFF


def _star_points(x, y, size):
    w = size * 0.24
    return [(x, y - size), (x + w, y - w), (x + size, y), (x + w, y + w), (x, y + size), (x - w, y + w), (x - size, y), (x - w, y - w)]


def _pulse(seconds, duration, delay=0.0):
    """0 to 1 and back to 0 over `duration`, eased in and out (the mock's 0%, 50%, 100% keyframes)."""
    phase = ((seconds - delay) / duration) % 1.0
    return (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0


def _drift(seconds, duration):
    """-10 to 14 and back, a whole `duration` each way."""
    turn = seconds / duration
    part = turn % 1.0
    if int(turn) % 2:
        part = 1.0 - part
    return -10.0 + 24.0 * (1.0 - math.cos(math.pi * part)) / 2.0


def _fall(seconds, duration, delay):
    return ((seconds - delay) / duration) % 1.0


def _twinkling(stars, seconds):
    shapes = []
    for x, y, size, colour, duration, delay in stars:
        level = _pulse(seconds, duration, delay)
        shapes.append(("poly", _star_points(x, y, size * (0.7 + 0.4 * level)), colour, 0.25 + 0.75 * level))
    return shapes


def _light(cx, cy, radius, whole_to, colour, opacity):
    """A soft round light: as bright as `opacity` out to `whole_to` of its radius, then falling away to nothing."""
    return ("glow", cx, cy, radius, whole_to, colour, opacity)


def _stars(seeded, count, xs, ys, sizes, colour):
    return [(seeded(*xs), seeded(*ys), seeded(*sizes), colour, seeded(2.0, 4.0), seeded(0.0, 2.0)) for _ in range(count)]


def _poly(path, colour):
    return ("poly", path_points(path)[0], colour, 1.0)


_CONFETTI_COLOURS = ("#F2A33A", "#E8735A", "#5BB8C4", "#F6C945", "#B98AD9")
_SEEDS = {"birthday": 906, "new_year": 101, "christmas": 1225, "seollal": 11, "chuseok": 815}
_kept = {}


def _birthday():
    seeded = _Seeded(_SEEDS["birthday"])
    confetti = [(seeded(50, 186), seeded(3, 5), seeded(5, 8), _CONFETTI_COLOURS[index % 5], seeded(3.2, 6.0), seeded(-6.0, 0.0))
                for index in range(16)]
    cake = [("round", 142, 42, 38, 20, 4, "#FFFFFF", 1.0), _poly("M142 48q4.7 7 9.5 0t9.5 0 9.5 0 9.5 0v-3q0-3-3-3h-32q-3 0-3 3z", "#F4A7B5"),
            ("round", 159.5, 30, 3, 12, 1, "#5BB8C4", 1.0)]

    def frame(seconds):
        shapes = []
        for x, width, height, colour, duration, delay in confetti:
            part = _fall(seconds, duration, delay)
            top = -4.0 - 14.0 + 96.0 * part
            shapes.append(("poly", _rotated(_box(x, top, width, height), 320.0 * part, x + width / 2.0, top + height / 2.0), colour, 1.0))
        shapes += cake
        stretched = 4.4 * (1.0 + 0.35 * _pulse(seconds, 1.1))
        shapes.append(("ellipse", 161.0, 30.4 - stretched, 2.6, stretched, "#F6B73C", 1.0))
        return shapes
    return frame


def _new_year():
    seeded = _Seeded(_SEEDS["new_year"])
    stars = _stars(seeded, 9, (58, 186), (7, 36), (2.5, 5.2), "#FFE9A8")
    still = [("circle", 150, 72, 28, "#FAC65A", 1.0), _poly("M60 66q24-14 48-5t44-5 44 4v8z", "#141B45")]

    def frame(seconds):
        return [_light(150, 72, 62, 0.45, "#FFC766", 0.34 + 0.3 * _pulse(seconds, 4.0))] + still + _twinkling(stars, seconds)
    return frame


def _tree(x, height, colour):
    return ("poly", [(x, 66.0 - height), (x + height * 0.42, 66.0), (x - height * 0.42, 66.0)], colour, 1.0)


def _christmas():
    seeded = _Seeded(_SEEDS["christmas"])
    trees = [_tree(132, 34, "#1F6B4A"), _tree(172, 28, "#1F6B4A"), _tree(152, 48, "#2B8660")]
    gold = [(152.0, 16.0, 4.6, "#FFD76A", 3.0, 0.5)]
    snow = [(seeded(50, 190), seeded(0.9, 2.0), seeded(4.0, 8.0), seeded(-8.0, 0.0)) for _ in range(22)]

    def frame(seconds):
        shapes = trees + _twinkling(gold, seconds)
        for x, radius, duration, delay in snow:
            shapes.append(("circle", x, -4.0 - 14.0 + 96.0 * _fall(seconds, duration, delay), radius, "#FFFFFF", 1.0))
        return shapes
    return frame


def _seollal():
    bands = [("round", 0, index * 3.4, 190, 3.4, 0, colour, 1.0)
             for index, colour in enumerate(("#D9463E", "#F2C230", "#3FA86B", "#3B6FC9", "#E88BB0"))]
    cloud = path_points("M60 42q4-6 11-3 5-6 12-1 6-2 8 4z")[0]
    bag = path_points("M138 26q-13 12-11 24 2 12 22 12t22-12q2-12-11-24z")[0]
    neck = path_points("M139 26q10 5 20 0l2-5q-12-4-24 0z")[0]
    tie = _box(138, 24.5, 22, 3.6)
    across = [path_points("M149 39v12")[0], path_points("M143 45h12")[0]]
    pivot = (149.0, 21.0)

    def frame(seconds):
        dx = _drift(seconds, 7.0)
        shapes = list(bands)
        shapes.append(("stroke", [(x + dx, y) for x, y in cloud], 1.4, "#E2C9A0", 1.0))
        angle = -5.0 + 10.0 * _pulse(seconds, 3.4)

        def turn(points):
            return _rotated(points, angle, pivot[0], pivot[1])

        shapes.append(("poly", turn(bag), "#C93B3B", 1.0))
        shapes.append(("poly", turn(neck), "#E25B4F", 1.0))
        shapes.append(("poly", turn(tie), "#F2C230", 1.0))
        knot = turn([(149.0, 26.0)])[0]
        shapes.append(("circle", knot[0], knot[1], 3.2, "#F6D76B", 1.0))
        ring = turn([(149.0, 45.0)])[0]
        shapes.append(("ring", ring[0], ring[1], 8.5, 1.5, "#F2C230", 1.0))
        for line in across:
            shapes.append(("stroke", turn(line), 1.3, "#F2C230", 1.0))
        return shapes
    return frame


def _chuseok():
    seeded = _Seeded(_SEEDS["chuseok"])
    stars = _stars(seeded, 7, (60, 120), (8, 38), (1.8, 3.2), "#FFF4D0")
    moon = [("circle", 146, 30, 20, "#F6E7B4", 1.0), ("circle", 139, 25, 3.6, "#E6D39B", 1.0), ("circle", 152, 35, 4.6, "#E6D39B", 1.0),
            ("circle", 151, 22, 2, "#E6D39B", 1.0)]

    def cloud(x, y, duration, seconds):
        dx = _drift(seconds, duration)
        return [("round", x + dx, y, 46, 7, 3.5, "#3A3F86", 1.0), ("round", x + 10 + dx, y - 5, 24, 8, 4, "#3A3F86", 1.0)]

    def frame(seconds):
        return ([_light(146, 30, 43, 0.47, "#FFEBB8", 0.3 + 0.3 * _pulse(seconds, 4.5))] + moon
                + cloud(100, 50, 8.0, seconds) + cloud(146, 56, 6.0, seconds) + _twinkling(stars, seconds))
    return frame


_SCENES = {"birthday": _birthday, "new_year": _new_year, "christmas": _christmas, "seollal": _seollal, "chuseok": _chuseok}


def scene_frame(look, milliseconds):
    """`look`'s scene `milliseconds` in, as the shapes to draw in order, in its 190 by 66: pure, and the same every time."""
    frame = _kept.get(look)
    if frame is None:
        frame = _kept[look] = _SCENES[look]()
    return frame(milliseconds / 1000.0)
