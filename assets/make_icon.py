"""Render the Codex Auto Resume icon to PNG and Windows .ico.

Deterministic and standard-library only, so a release build needs no image toolchain
and produces byte-identical output on any machine.

The mark is an original design: a rounded square badge carrying an open ring with an
arrowhead - a resume/retry motion - and a small gap at the top left where the ring is
"interrupted". Nothing here derives from the OpenAI or Codex marks.
"""
from __future__ import annotations

import math
from pathlib import Path
import struct
import sys
import zlib

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
SUPERSAMPLE = 4

# Deep green badge, near-white mark. Matches the plugin manifest brandColor.
BADGE_TOP = (0x35, 0x7D, 0x58)
BADGE_BOTTOM = (0x24, 0x5A, 0x3F)
MARK = (0xF4, 0xFA, 0xF6)


def _mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _rounded_square(x, y, radius):
    """Signed coverage test for a rounded square centred on (0,0) with half-size 1."""
    half = 1.0 - radius
    dx = max(abs(x) - half, 0.0)
    dy = max(abs(y) - half, 0.0)
    return math.hypot(dx, dy) <= radius and abs(x) <= 1.0 and abs(y) <= 1.0


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


def _triangle(px, py, a, b, c):
    def side(p, q, r):
        return (p[0] - r[0]) * (q[1] - r[1]) - (q[0] - r[0]) * (p[1] - r[1])

    point = (px, py)
    d1, d2, d3 = side(point, a, b), side(point, b, c), side(point, c, a)
    negative = min(d1, d2, d3) < 0
    positive = max(d1, d2, d3) > 0
    return not (negative and positive)


RING_INNER, RING_OUTER = 0.34, 0.54
ARC_START, ARC_END = math.radians(118), math.radians(62)


def _arrow_triangle():
    """Head at the end of the sweep: base across the stroke, tip along the motion.

    The base is a radial cut that overhangs the stroke on both sides, so it merges with
    the arc's own radial terminus instead of leaving a notch. The tip continues counter-
    clockwise into the ring's gap.
    """
    radial = (math.cos(ARC_END), math.sin(ARC_END))
    tangent = (-math.sin(ARC_END), math.cos(ARC_END))     # counter-clockwise motion
    centre = ((RING_INNER + RING_OUTER) / 2.0 * radial[0],
              (RING_INNER + RING_OUTER) / 2.0 * radial[1])
    overhang, reach = 0.09, 0.19
    inner = (RING_INNER - overhang, RING_OUTER + overhang)
    return (
        (inner[0] * radial[0], inner[0] * radial[1]),
        (inner[1] * radial[0], inner[1] * radial[1]),
        (centre[0] + tangent[0] * reach, centre[1] + tangent[1] * reach),
    )


ARROW = _arrow_triangle()


def _arrow_hit(x, y):
    return _triangle(x, y, *ARROW)


def _mark_hit(x, y):
    """The arrow: an open ring closed by a solid arrowhead at the end of its sweep."""
    if _ring_arc(x, y, RING_INNER, RING_OUTER, ARC_START, ARC_END):
        return True
    return _arrow_hit(x, y)


def render(size: int) -> bytes:
    """Return raw RGBA bytes for one square icon of the given size."""
    scale = size * SUPERSAMPLE
    rows = []
    radius = 0.30 if size >= 32 else 0.24
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
                    badge = _mix(BADGE_TOP, BADGE_BOTTOM, (fy + 1.0) / 2.0)
                    colour = MARK if _mark_hit(fx, -fy) else badge
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


def png(size: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + pixels[y * size * 4:(y + 1) * size * 4] for y in range(size))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    # mtime-free and level-pinned so the bytes are reproducible.
    body = zlib.compress(raw, 9)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", body) + chunk(b"IEND", b""))


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


def main(argv=None) -> int:
    out = Path(argv[0]) if argv else Path(__file__).resolve().parent
    out.mkdir(parents=True, exist_ok=True)
    images = []
    for size in SIZES:
        data = png(size, render(size))
        images.append((size, data))
        if size == 256:
            (out / "codex-auto-resume-256.png").write_bytes(data)
    (out / "codex-auto-resume.ico").write_bytes(ico(images))
    print("wrote %s (%d sizes) and codex-auto-resume-256.png"
          % (out / "codex-auto-resume.ico", len(images)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
