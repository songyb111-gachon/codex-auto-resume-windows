"""Windows' title bar round the window stills, which are drawn offscreen (v0.6.20).

The window's stills are drawn by the window itself, offscreen, at a pinned scale (build/make_screenshots.py, PINNED_DPI:
150 %), so a picture is the same on a laptop at 200 % and on a monitor at 150 % (the owner, 2026-10-30: "모니터 연결을
안 하고 가상모니터 느낌으로 항상 일정하게 생성"). Everything inside the window is the window's own drawing and comes out
the same pixels as a capture on a 150 % monitor. The title bar is not the window's: Windows (its desktop window manager)
draws it, on the monitor the window is on and at that monitor's DPI, and nothing in Windows draws it for a window that
is on no monitor or at a DPI no monitor has. So the title bar is taken ONCE from a real capture at the pinned scale and
kept here, beside the generator: build/frame/<kind>-caption.png, the caption rows of that capture with its rounded top
corners filled back in as the capture had them before build/capture_window.ps1 cut them (Windows' plain bar colour), and
build/frame/frame.json, what it is a picture of - the window's title, the icon's digest, the DPI, the theme - so a
change to any of them stops the generator rather than frame a picture with a title bar that is no longer the window's.

The render mode puts it round each still (gui/WindowRender.cs, FramedStill): its first `left` px and last `right` px as
they are - the icon and title, and the caption buttons - and its plain bar between, so one title bar frames a window of
any width (zh-CN opens wider); then the corners are cut round exactly as build/capture_window.ps1 cuts them.

To take it again - after the title, the icon or Windows' title bar changed - capture one still on a monitor at the
pinned scale (`python -X utf8 build/make_screenshots.py --capture ...`, the main session) and run

    python -X utf8 build/window_frame.py take window assets/screenshot-dashboard.png
    python -X utf8 build/window_frame.py take setup assets/screenshot-setup-ko.png --client-height 716
    python -X utf8 build/window_frame.py check          # whether the title bars are this tree's window's

`take` reads the client height from the window's opening size at the pinned scale for `window`; give it for `setup`.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

FOLDER = ROOT / "build" / "frame"
KEY = FOLDER / "frame.json"
ICON = ROOT / "assets" / "codex-auto-resume.ico"
# The title each window's caption shows (gui/SettingsApp.cs and gui/InstallerWindow.cs: Text).
TITLE = "Codex Auto Resume"
# How much of a caption is kept at each end: the icon and the title, and the caption buttons. Between them a caption is
# its plain bar, at every width.
LEFT = 240
RIGHT = 200
# The corners Windows rounds for a window at 96 DPI (build/capture_window.ps1: 8 px, at the window's DPI).
CORNER = 8
KINDS = ("window", "setup")


class FrameError(RuntimeError):
    """A title bar that is missing, or a picture of another window than this tree's."""


def caption_path(kind: str) -> Path:
    return FOLDER / ("%s-caption.png" % kind)


def icon_digest() -> str:
    return hashlib.sha256(ICON.read_bytes()).hexdigest()


def radius(dpi: int) -> int:
    """The corners' radius at `dpi`, as build/capture_window.ps1 rounds it."""
    return int(round(CORNER * dpi / 96.0))


def read_key() -> dict:
    if not KEY.is_file():
        return {}
    return json.loads(KEY.read_text(encoding="utf-8"))


def problems(kind: str, dpi: int, theme: str = "light") -> list:
    """Why the kept title bar of `kind` cannot frame a still of this tree's window at `dpi` in `theme`: [] when it can."""
    entry = read_key().get(kind)
    if not entry or not caption_path(kind).is_file():
        return ["no title bar of the %s is kept (build/frame/%s-caption.png)" % (kind, kind)]
    wrong = []
    if entry.get("dpi") != dpi:
        wrong.append("it was taken at %s DPI, the stills are drawn at %s" % (entry.get("dpi"), dpi))
    if entry.get("theme") != theme:
        wrong.append("it is the %s theme's, the stills are %s" % (entry.get("theme"), theme))
    if entry.get("title") != TITLE:
        wrong.append("it says %r, the window says %r" % (entry.get("title"), TITLE))
    if entry.get("icon") != icon_digest():
        wrong.append("it shows another icon than assets/codex-auto-resume.ico")
    if entry.get("caption") != hashlib.sha256(caption_path(kind).read_bytes()).hexdigest():
        wrong.append("build/frame/%s-caption.png is not the picture frame.json records" % kind)
    return wrong


def still_job(kind: str, dpi: int, theme: str = "light") -> dict:
    """The render job's `still` for `kind` (gui/WindowRender.cs FramedStill), or FrameError saying why there is none."""
    wrong = problems(kind, dpi, theme)
    if wrong:
        raise FrameError("the %s's title bar cannot frame its stills: %s - take it again from a capture at %d DPI "
                         "(build/window_frame.py)" % (kind, "; ".join(wrong), dpi))
    entry = read_key()[kind]
    return {"caption": str(caption_path(kind)), "left": entry["left"], "right": entry["right"], "radius": radius(dpi),
            "dpi": dpi}


def caption_rows(width: int, height: int, rgb: bytes, alpha, client_height: int) -> tuple:
    """(rows, RGBA bytes) of a captured still's title bar: the rows above its client area, with every pixel the rounding
    cleared or thinned - a corner - given back the bar's own colour, opaque, as the capture had it before it was cut."""
    rows = height - client_height
    if rows <= 0:
        raise FrameError("the still is %d px tall and its client area %d: it has no title bar" % (height, client_height))
    bar = tuple(rgb[(2 * width + width // 2) * 3:(2 * width + width // 2) * 3 + 3])
    out = bytearray()
    for y in range(rows):
        for x in range(width):
            at = y * width + x
            if alpha is not None and alpha[at] < 255:
                out += bytes(bar) + b"\xff"
            else:
                out += bytes(rgb[at * 3:at * 3 + 3]) + b"\xff"
    return rows, bytes(out)


def take(kind: str, still: Path, client_height: int | None = None, dpi: int | None = None) -> dict:
    """Keeps the title bar of a captured still of `kind` (its first frame) as build/frame/<kind>-caption.png, and what
    it is a picture of in build/frame/frame.json."""
    import make_screenshots as shots
    if kind not in KINDS:
        raise FrameError("a title bar is kept for %s, not %r" % (", ".join(KINDS), kind))
    dpi = dpi or shots.PINNED_DPI
    if client_height is None:
        if kind != "window":
            raise FrameError("give the %s's client height (--client-height)" % kind)
        client_height = int(round(shots.OPENING_HEIGHT * dpi / 96.0))
    width, height, rgb, alpha = shots.read_png(Path(still))
    rows, rgba = caption_rows(width, height, rgb, alpha, client_height)
    FOLDER.mkdir(parents=True, exist_ok=True)
    bgra = bytearray(len(rgba))
    bgra[0::4], bgra[1::4], bgra[2::4], bgra[3::4] = rgba[2::4], rgba[1::4], rgba[0::4], rgba[3::4]
    shots.write_png(caption_path(kind), width, rows, bytes(bgra))
    key = read_key()
    key[kind] = {"title": TITLE, "icon": icon_digest(), "dpi": dpi, "theme": "light", "rows": rows, "width": width,
                 "left": LEFT, "right": RIGHT,
                 "caption": hashlib.sha256(caption_path(kind).read_bytes()).hexdigest()}
    KEY.write_text(json.dumps(key, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return key[kind]


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="window_frame.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    taking = sub.add_parser("take", help="keep a captured still's title bar")
    taking.add_argument("kind", choices=KINDS)
    taking.add_argument("still")
    taking.add_argument("--client-height", type=int, default=None)
    sub.add_parser("check", help="whether the kept title bars are this tree's window's")
    options = parser.parse_args(argv)
    if options.command == "take":
        print(json.dumps(take(options.kind, Path(options.still), options.client_height), indent=2, sort_keys=True))
        return 0
    import make_screenshots as shots
    failed = 0
    for kind in KINDS:
        wrong = problems(kind, shots.PINNED_DPI)
        print("%-7s %s" % (kind, "; ".join(wrong) if wrong else "ok"))
        failed += bool(wrong)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
