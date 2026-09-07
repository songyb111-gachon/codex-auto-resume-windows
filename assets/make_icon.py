"""Render the Codex Auto Resume mark: a vector master, PNGs, and a Windows .ico.

Deterministic and standard-library only, so a release build needs no image toolchain and
produces byte-identical output on any machine.

## The mark

A rounded-square badge in the brand's deep blue, carrying an open ring with a bright head
at its leading end. The ring is the wait; the gap at the top is the interruption; the
cyan head is the moment it resumes. Every colour comes from `codex_auto_resume.brand`,
so the icon cannot drift away from the panel, the window and the plugin card.

Nothing here derives from the OpenAI or Codex marks.

## Why this shape and not the other three

Four concepts were built and rendered at all nine icon sizes on both a light and a dark
ground - `build/icon_concepts.py` still renders the sheet, so the comparison can be
repeated rather than believed. What the sheet showed:

* A **pause-then-play** pair was the most legible at 16px and the least distinctive
  anywhere: it is the most common glyph pair in software, and it says "media player".
* A **chevron inside a ring** was handsome at 256 and gone by 24: the chevron and the
  ring merged into one blob.
* An **arrowhead on an open arc** - the previous mark - reads as a flag at large sizes,
  because a triangle joined to a curve at an angle stops looking joined.
* A **ring with a round head** survived 16px *and* stayed specific. A circle is the one
  shape that cannot lose its silhouette when it is four pixels across.

The head is a disc rather than an arrowhead for that last reason, and it sits at the end
of the sweep rather than inside the gap so it reads as leading the ring rather than
floating beside it.

## The vector master

`assets/brand/icon.svg` is generated here from the same constants the rasteriser uses,
so there is one geometry, not a drawing and a copy of it. `tests/test_brand.py`
regenerates it and compares, which is what makes that claim checkable.
"""
from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from codex_auto_resume import brand      # noqa: E402

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 4

BADGE_TOP = brand.rgb(brand.ICON_TOP)
BADGE_BOTTOM = brand.rgb(brand.ICON_BOTTOM)
MARK = brand.rgb(brand.ICON_MARK)
HEAD = brand.rgb(brand.ICON_ACCENT)

# The mark's geometry, in a square whose half-size is 1. These nine numbers are the
# entire design; the SVG master and every PNG are computed from them.
RING_INNER = 0.34
RING_OUTER = 0.53
# Counter-clockwise from the near end of the gap round to its far end: a 290 degree
# sweep leaving a 70 degree opening at the top.
ARC_START = 125.0
ARC_END = 55.0
HEAD_RADIUS = 0.155
CORNER_LARGE = 0.30
CORNER_SMALL = 0.24
# Below this the corner radius drops: a 30% round on a 16 pixel square eats the mark.
CORNER_THRESHOLD = 32
# The plugin card's logo pair, and how wide the dark one's rim is as a fraction of the
# badge's half-size: about three pixels at this size, which reads as an edge and not as
# a border.
LOGO_SIZE = 512
LOGO_RIM = 0.012


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _rounded_square(x, y, radius):
    """Signed distance to a rounded square centred on (0,0) with half-size 1.

    Negative inside, zero on the edge. A distance rather than a boolean because the
    dark logo needs to know how close to the edge it is, to draw a rim there.
    """
    half = 1.0 - radius
    dx = max(abs(x) - half, 0.0)
    dy = max(abs(y) - half, 0.0)
    if abs(x) > 1.0 or abs(y) > 1.0:
        return 1.0
    return math.hypot(dx, dy) - radius


def _ring_arc(x, y, inner, outer, start, end):
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


def _head_centre():
    """On the stroke's centre line, at the leading end of the sweep."""
    middle = (RING_INNER + RING_OUTER) / 2.0
    angle = math.radians(ARC_END)
    return (middle * math.cos(angle), middle * math.sin(angle))


HEAD_CENTRE = _head_centre()


def _mark_hit(x, y):
    """Returns the mark colour at a point, or None for the badge behind it."""
    if math.hypot(x - HEAD_CENTRE[0], y - HEAD_CENTRE[1]) <= HEAD_RADIUS:
        return HEAD
    if _ring_arc(x, y, RING_INNER, RING_OUTER, math.radians(ARC_START), math.radians(ARC_END)):
        return MARK
    return None


def render(size: int, rim: float = 0.0) -> bytes:
    """Return raw RGBA bytes for one square icon of the given size.

    `rim` draws a hairline of the badge's own top colour just inside the edge, as a
    fraction of the half-size. The deep blue badge has plenty of contrast on a light
    page and almost none on a near-black one, so the dark logo lifts itself off the
    ground rather than relying on a ground it cannot see.
    """
    scale = size * SUPERSAMPLE
    radius = CORNER_LARGE if size >= CORNER_THRESHOLD else CORNER_SMALL
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    fx = (px * SUPERSAMPLE + sx + 0.5) / scale * 2.0 - 1.0
                    fy = (py * SUPERSAMPLE + sy + 0.5) / scale * 2.0 - 1.0
                    distance = _rounded_square(fx, fy, radius)
                    if distance > 0.0:
                        continue
                    badge = _mix(BADGE_TOP, BADGE_BOTTOM, (fy + 1.0) / 2.0)
                    if rim and distance >= -rim:
                        badge = BADGE_TOP
                    colour = _mark_hit(fx, -fy) or badge
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


def png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    """A minimal 8-bit RGBA PNG. No metadata, so the bytes depend only on the pixels."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    stride = width * 4
    raw = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    # mtime-free and level-pinned so the bytes are reproducible.
    body = zlib.compress(raw, 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


def png(size: int, pixels: bytes) -> bytes:
    return png_rgba(size, size, pixels)


def ico(images: list[tuple[int, bytes]]) -> bytes:
    """A Vista+ .ico holding PNG-compressed entries."""
    count = len(images)
    directory = b""
    payload = b""
    offset = 6 + 16 * count
    for size, data in images:
        directory += struct.pack("<BBBBHHII", size if size < 256 else 0,
                                 size if size < 256 else 0, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return struct.pack("<HHH", 0, 1, count) + directory + payload


# --- the vector master ---------------------------------------------------------------

SVG_BOX = 512
_CENTRE = SVG_BOX / 2.0


def _point(angle_degrees: float, radius: float) -> str:
    """Unit-circle polar to SVG user units. SVG's y axis points down, so it is negated."""
    angle = math.radians(angle_degrees)
    x = _CENTRE + radius * _CENTRE * math.cos(angle)
    y = _CENTRE - radius * _CENTRE * math.sin(angle)
    return "%.3f %.3f" % (x, y)


def svg() -> str:
    """The mark as scalable vector, generated from the constants above.

    The sweep is 290 degrees, so both arcs take the large-arc flag.

    The sweep flags are worth stating rather than guessing at, because the obvious guess
    is wrong and it fails quietly: it still draws a shape, just the *other* one - the
    70 degree gap, filled, spilling outside the badge. The band runs 125 -> 180 -> 270
    -> 0 -> 55 degrees, and on a screen, where y points down, that path reads
    up-left -> left -> down -> right -> up-right, which is **counter-clockwise**. So the
    outer edge takes sweep 0 and the inner edge back takes sweep 1.
    """
    outer = RING_OUTER * _CENTRE
    inner = RING_INNER * _CENTRE
    head_radius = HEAD_RADIUS * _CENTRE
    head_x = _CENTRE + HEAD_CENTRE[0] * _CENTRE
    head_y = _CENTRE - HEAD_CENTRE[1] * _CENTRE
    corner = CORNER_LARGE * _CENTRE
    path = " ".join((
        "M %s" % _point(ARC_START, RING_OUTER),
        "A %.3f %.3f 0 1 0 %s" % (outer, outer, _point(ARC_END, RING_OUTER)),
        "L %s" % _point(ARC_END, RING_INNER),
        "A %.3f %.3f 0 1 1 %s" % (inner, inner, _point(ARC_START, RING_INNER)),
        "Z",
    ))
    return "\n".join((
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'width="%d" height="%d" role="img" aria-label="Codex Auto Resume">'
        % (SVG_BOX, SVG_BOX, SVG_BOX, SVG_BOX),
        '  <title>Codex Auto Resume</title>',
        '  <defs>',
        '    <linearGradient id="badge" x1="0" y1="0" x2="0" y2="1">',
        '      <stop offset="0" stop-color="%s"/>' % brand.ICON_TOP,
        '      <stop offset="1" stop-color="%s"/>' % brand.ICON_BOTTOM,
        '    </linearGradient>',
        '  </defs>',
        '  <rect width="%d" height="%d" rx="%.3f" ry="%.3f" fill="url(#badge)"/>'
        % (SVG_BOX, SVG_BOX, corner, corner),
        '  <path d="%s" fill="%s"/>' % (path, brand.ICON_MARK),
        '  <circle cx="%.3f" cy="%.3f" r="%.3f" fill="%s"/>'
        % (head_x, head_y, head_radius, brand.ICON_ACCENT),
        '</svg>',
        '',
    ))


def main(argv=None) -> int:
    out = Path(argv[0]) if argv else Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    images = []
    for size in SIZES:
        data = png(size, render(size))
        images.append((size, data))
        if size == 256:
            # Two names for one image: the historical one, and the one the Codex plugin
            # manifest points `interface.composerIcon` at.
            (out / "codex-auto-resume-256.png").write_bytes(data)
            (out / "icon.png").write_bytes(data)
    (out / "codex-auto-resume.ico").write_bytes(ico(images))
    # The plugin card's logo pair. Same mark, and the dark one carries a rim so the
    # badge does not dissolve into a near-black panel.
    (out / "logo.png").write_bytes(png(LOGO_SIZE, render(LOGO_SIZE)))
    (out / "logo-dark.png").write_bytes(png(LOGO_SIZE, render(LOGO_SIZE, rim=LOGO_RIM)))
    vector = out / "brand" / "icon.svg"
    vector.parent.mkdir(parents=True, exist_ok=True)
    vector.write_text(svg(), encoding="utf-8")
    print("wrote %s (%d sizes), icon.png, codex-auto-resume-256.png, "
          "logo.png, logo-dark.png and brand/icon.svg"
          % (out / "codex-auto-resume.ico", len(images)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
