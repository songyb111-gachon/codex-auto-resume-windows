"""Render the Codex Auto Resume mark: a vector master, PNGs, and a Windows .ico.

Deterministic and standard-library only, so a release build needs no image toolchain and
draws identical pixels on any machine. The compressed PNG bytes are identical only between
Pythons built with the same zlib - zlib-ng, for one, deflates the same scanlines differently -
so `tests/test_brand.py` compares decoded content rather than bytes.

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

## Where the geometry lives (v0.6.5)

The nine numbers and the rasteriser moved into `codex_auto_resume.brand` (`ICON_SHAPE`,
`icon_render`), because the notification-area icon now draws its motion frames from them
inside the watcher. This script imports them under the names it always used, and writes
exactly the bytes it wrote before. `--frames <dir>` renders the icon's motion as a contact
sheet - every head position and breathing level at 16/20/24/32 px on a light and a dark
taskbar, with nothing drawn on the mark since v0.6.8 - which is the desk check for that motion.
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
SUPERSAMPLE = brand.ICON_SUPERSAMPLE

BADGE_TOP = brand.rgb(brand.ICON_TOP)
BADGE_BOTTOM = brand.rgb(brand.ICON_BOTTOM)
MARK = brand.rgb(brand.ICON_MARK)
HEAD = brand.rgb(brand.ICON_ACCENT)

# The mark's geometry, in a square whose half-size is 1: brand.ICON_SHAPE, under the names
# this script has always given it. These nine numbers are the entire design; the SVG master,
# every PNG and the notification-area icon's frames are computed from them.
RING_INNER = brand.ICON_SHAPE["ring_inner"]
RING_OUTER = brand.ICON_SHAPE["ring_outer"]
ARC_START = brand.ICON_SHAPE["arc_start"]
ARC_END = brand.ICON_SHAPE["arc_end"]
HEAD_RADIUS = brand.ICON_SHAPE["head_radius"]
CORNER_LARGE = brand.ICON_SHAPE["corner_large"]
CORNER_SMALL = brand.ICON_SHAPE["corner_small"]
CORNER_THRESHOLD = brand.ICON_SHAPE["corner_threshold"]
# The plugin card's logo pair, and how wide the dark one's rim is as a fraction of the
# badge's half-size: about three pixels at this size, which reads as an edge and not as
# a border.
LOGO_SIZE = 512
LOGO_RIM = 0.012

HEAD_CENTRE = brand.icon_head_centre()


def render(size: int, rim: float = 0.0) -> bytes:
    """Return raw RGBA bytes for one square icon of the given size (brand.icon_render).

    `rim` draws a hairline of the badge's own top colour just inside the edge, as a
    fraction of the half-size, for the dark logo.
    """
    return brand.icon_render(size, rim)


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


# --- the icon's motion, as a contact sheet ----------------------------------------------

FRAME_SIZES = (16, 20, 24, 32)
# Windows 11's taskbar in its light and its dark mode, near enough to judge an icon against.
TASKBARS = {"light": "#EEF0F3", "dark": "#1F1F1F"}


def frame_rows(frames):
    """The frames a person should look at, as (what, [BGRA frames]): watching's breath and a turn, one
    sweep each of recovering and a failure as the frame timer steps them, attention's breath, and
    paused at rest. Nothing is drawn on the mark since v0.6.8."""
    from codex_auto_resume import tray
    top = tray.ICON_MOTION["levels"] - 1
    accent = tray.icon_head_colour("watching")
    breath = list(range(top, -1, -1)) + list(range(1, top + 1))
    rows = [("watching: the breath", [frames.compose(0, tray.icon_level_colour(accent, level))
                                      for level in breath]),
            ("watching: one turn", [frames.compose(position, accent)
                                    for position in range(tray.ICON_MOTION["positions"])])]
    motion, step = tray.ICON_MOTION, tray.ICON_MOTION["turn_frame_ms"]
    for state in ("recovering", "failed"):
        slot = brand.GLOW["monitoring_ms"] * (motion["failed_slot"] if state == "failed" else 1)
        cycle = slot * (2 * motion["sweep_out"] + motion["sweep_hold"] + motion["recover_rest"])
        rows.append(("%s: one sweep" % state,
                     [frames.compose(*_frame(tray, state, elapsed)) for elapsed in range(0, int(cycle), step)]))
    amber = tray.icon_head_colour("attention")
    rows.append(("attention: the breath", [frames.compose(0, tray.icon_level_colour(amber, level))
                                           for level in breath]))
    rows.append(("idle", [frames.compose(0, tray.icon_head_colour("idle"))]))
    return rows


def _frame(tray, state, elapsed):
    position, level = tray.icon_frame(state, elapsed)
    return position, tray.icon_level_colour(tray.icon_head_colour(state), level)


def contact_sheet(out: Path) -> Path:
    """Every frame at FRAME_SIZES on a light and a dark taskbar, as one PNG in `out`."""
    from codex_auto_resume import tray
    pad = 4
    blocks = []
    for size in FRAME_SIZES:
        frames = tray.IconFrames(size)
        rows = frame_rows(frames)
        for ground in TASKBARS.values():
            blocks.append((size, brand.rgb(ground), rows))
    cell = max(FRAME_SIZES) + 2 * pad
    columns = max(len(row) for _, _, rows in blocks for _, row in rows)
    width = columns * cell
    height = sum(len(rows) * cell for _, _, rows in blocks)
    canvas = bytearray(b"\xff" * (width * height * 4))
    top = 0
    for size, ground, rows in blocks:
        for _, row in rows:
            for column, pixels in enumerate(row):
                left = column * cell
                for y in range(cell):
                    for x in range(cell):
                        colour = ground
                        fx, fy = x - pad, y - pad
                        if 0 <= fx < size and 0 <= fy < size:
                            index = (fy * size + fx) * 4
                            alpha = pixels[index + 3] / 255.0
                            source = (pixels[index + 2], pixels[index + 1], pixels[index])
                            colour = tuple(int(round(g + (s - g) * alpha)) for g, s in zip(ground, source))
                        at = ((top + y) * width + left + x) * 4
                        canvas[at:at + 4] = bytes(colour) + b"\xff"
            top += cell
    out.mkdir(parents=True, exist_ok=True)
    target = out / "icon-motion-frames.png"
    target.write_bytes(png_rgba(width, height, bytes(canvas)))
    return target


def main(argv=None) -> int:
    argv = list(argv or [])
    if argv[:1] == ["--frames"]:
        if len(argv) < 2:
            print("usage: make_icon.py --frames <dir>")
            return 2
        print("wrote %s" % contact_sheet(Path(argv[1])))
        return 0
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
