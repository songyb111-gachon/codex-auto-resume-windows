"""Render every icon concept at every real size, light and dark, on one sheet.

Design provenance, kept in the repository so the choice can be argued with rather than
taken on trust. It lives under `build/` deliberately: it is a design tool, and `build/`
is the one tree the release payload excludes, so exploring three ideas does not add
three ideas' worth of bytes to what a user downloads.

An icon is not chosen by looking at a 256-pixel render. It is chosen by looking at 16
pixels on the two backgrounds Windows actually draws it on - the light taskbar and the
dark one - because that is where most of them stop being a shape and start being a
smudge. So the sheet renders every size the .ico carries, twice.

Run: python build/icon_concepts.py
"""
from __future__ import annotations

import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "assets"))

from codex_auto_resume import brand          # noqa: E402
import make_icon                              # noqa: E402

SIZES = (16, 20, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 4

MARK = brand.rgb(brand.ICON_MARK)
ACCENT = brand.rgb(brand.ICON_ACCENT)
TOP = brand.rgb(brand.ICON_TOP)
BOTTOM = brand.rgb(brand.ICON_BOTTOM)


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _rounded_square(x, y, radius):
    half = 1.0 - radius
    dx = max(abs(x) - half, 0.0)
    dy = max(abs(y) - half, 0.0)
    return math.hypot(dx, dy) <= radius and abs(x) <= 1.0 and abs(y) <= 1.0


def _arc(x, y, inner, outer, start, end):
    distance = math.hypot(x, y)
    if not (inner <= distance <= outer):
        return False
    angle = math.atan2(y, x) % (2 * math.pi)
    start %= 2 * math.pi
    end %= 2 * math.pi
    if start <= end:
        return start <= angle <= end
    return angle >= start or angle <= end


def _triangle(px, py, a, b, c):
    def side(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])
    point = (px, py)
    d1, d2, d3 = side(point, a, b), side(point, b, c), side(point, c, a)
    return not (min(d1, d2, d3) < 0 and max(d1, d2, d3) > 0)


def _bar(x, y, x0, x1, y0, y1):
    return x0 <= x <= x1 and y0 <= y <= y1


def _segment(px, py, a, b, thickness):
    """Distance to a capsule: a thick line segment with rounded ends."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t)) <= thickness


# --- A. Resume arc: the open ring closed by an arrowhead, recoloured -----------------
# This was the shipped mark up to v0.5.1. Its geometry is repeated here rather than
# imported, so the sheet keeps comparing the same four candidates no matter what the
# production renderer becomes.
A_INNER, A_OUTER = 0.34, 0.54
A_START, A_END = math.radians(118), math.radians(20)
A_HALF_BASE, A_REACH, A_TILT = 0.17, 0.42, math.radians(-24)


def _arrowhead():
    radial = (math.cos(A_END), math.sin(A_END))
    aim = A_END + math.pi / 2 + A_TILT
    middle = (A_INNER + A_OUTER) / 2.0
    centre = (middle * radial[0], middle * radial[1])
    return ((centre[0] - radial[0] * A_HALF_BASE, centre[1] - radial[1] * A_HALF_BASE),
            (centre[0] + radial[0] * A_HALF_BASE, centre[1] + radial[1] * A_HALF_BASE),
            (centre[0] + math.cos(aim) * A_REACH, centre[1] + math.sin(aim) * A_REACH))


A_HEAD = _arrowhead()


def concept_a(x, y):
    if _triangle(x, y, *A_HEAD):
        return ACCENT
    if _arc(x, y, A_INNER, A_OUTER, A_START, A_END):
        # The last stretch before the head brightens, so the mark reads as motion
        # arriving somewhere rather than as a circle with a bump on it.
        angle = math.atan2(y, x) % (2 * math.pi)
        if angle <= math.radians(70) or angle >= math.radians(330):
            return ACCENT
        return MARK
    return None


# --- B. Pause into play: two bars resolving into a forward chevron -------------------
def concept_b(x, y):
    if _bar(x, y, -0.62, -0.42, -0.46, 0.46):
        return MARK
    if _bar(x, y, -0.30, -0.10, -0.46, 0.46):
        return MARK
    if _triangle(x, y, (0.06, 0.50), (0.06, -0.50), (0.66, 0.0)):
        return ACCENT
    return None


# --- C. Orbit: a waiting ring with the moving end lit --------------------------------
C_INNER, C_OUTER = 0.36, 0.52
C_START, C_END = math.radians(70), math.radians(-15)


def concept_c(x, y):
    middle = (C_INNER + C_OUTER) / 2.0
    lead = (middle * math.cos(C_END), middle * math.sin(C_END))
    if math.hypot(x - lead[0], y - lead[1]) <= 0.17:
        return ACCENT
    if _arc(x, y, C_INNER, C_OUTER, C_START, C_END):
        return MARK
    return None


# --- D. Chevron in a ring: forward motion inside a closed boundary -------------------
def concept_d(x, y):
    if _arc(x, y, 0.62, 0.78, math.radians(300), math.radians(240)):
        return MARK
    if (_segment(x, y, (-0.14, 0.34), (0.20, 0.0), 0.105)
            or _segment(x, y, (-0.14, -0.34), (0.20, 0.0), 0.105)):
        return ACCENT
    return None


CONCEPTS = (("A resume arc", concept_a), ("B pause into play", concept_b),
            ("C orbit", concept_c), ("D chevron in ring", concept_d))


def render(size, mark):
    scale = size * SUPERSAMPLE
    radius = 0.30 if size >= 32 else 0.24
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    fx = (px * SUPERSAMPLE + sx + 0.5) / scale * 2.0 - 1.0
                    fy = (py * SUPERSAMPLE + sy + 0.5) / scale * 2.0 - 1.0
                    if not _rounded_square(fx, fy, radius):
                        continue
                    badge = _mix(TOP, BOTTOM, (fy + 1.0) / 2.0)
                    colour = mark(fx, -fy) or badge
                    r += colour[0]
                    g += colour[1]
                    b += colour[2]
                    a += 255
            samples = SUPERSAMPLE * SUPERSAMPLE
            if a == 0:
                row += b"\x00\x00\x00\x00"
            else:
                covered = a // 255
                row += bytes((r // covered, g // covered, b // covered, a // samples))
        rows.append(bytes(row))
    return b"".join(rows)


def sheet(path: Path) -> Path:
    """One RGBA canvas: a light strip and a dark strip per concept."""
    pad, gap = 12, 10
    width = pad * 2 + sum(size + gap for size in SIZES) - gap
    strip = max(SIZES) + pad
    height = pad + len(CONCEPTS) * 2 * strip
    canvas = bytearray(b"\x00" * (width * height * 4))

    def put(x0, y0, size, pixels):
        for y in range(size):
            start = ((y0 + y) * width + x0) * 4
            canvas[start:start + size * 4] = pixels[y * size * 4:(y + 1) * size * 4]

    def fill(y0, rows, colour):
        for y in range(y0, min(y0 + rows, height)):
            start = y * width * 4
            canvas[start:start + width * 4] = bytes(colour + (255,)) * width

    y = pad
    for _, mark in CONCEPTS:
        drawn = [(size, render(size, mark)) for size in SIZES]
        for ground in ((0xF2, 0xF5, 0xF9), (0x0E, 0x14, 0x1C)):
            fill(y - 6, strip, ground)
            x = pad
            for size, pixels in drawn:
                put(x, y + (max(SIZES) - size) // 2, size, pixels)
                x += size + gap
            y += strip

    path.write_bytes(make_icon.png_rgba(width, height, bytes(canvas)))
    return path


def main() -> int:
    out = ROOT / "build" / "dist"
    out.mkdir(parents=True, exist_ok=True)
    target = sheet(out / "icon-concepts.png")
    print("wrote %s" % target)
    for name, _ in CONCEPTS:
        print("  row pair: %s" % name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
