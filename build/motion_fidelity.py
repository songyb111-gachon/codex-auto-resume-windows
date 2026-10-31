"""Whether the window the motion picture is drawn from is the window the captured pictures show (TOOLING section 4).

Each page drawn at rest by the render mode - no hover, no pointer, its lights at the still's moment - is held to that
page's committed still (assets/screenshot-<page>[-<locale>].png), client area only:

- at least MIN_EXACT of its pixels exactly the still's;
- every pixel that is not within TEXT_LEVELS levels a channel and within TEXT_REACH px of glyph ink in the still - a
  ClearType edge drawn into a memory bitmap instead of on the screen - and none in a fill, a border or a shadow.

The dialog the window opens over itself (Timeline, v0.6.20) has no still of its own - nothing of the screen is ever
captured here - so it is held to the stills of what it is made of (`compare_dialog`): its ground is the window's
ground, its Close button the face of the window's own primary button, its title bar the still's title bar, each read
at the same control in the committed still, exactly.

Two kinds of pixel are left out, and why is recorded with the result: the corners Windows rounds, which the capture
leaves clear (the motion lays them from the still, motion_compose.WindowChrome); and the status light, which the
pictures' `--breathe` step paints again over every capture with the generator's own drawing (make_screenshots.
paint_light), where the motion shows the window's own light at each moment - its difference is measured and recorded,
not held. The card's resting frame is held byte for byte to the README card (tests/test_motion_card.py does that).
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _path in (str(ROOT / "src"), str(ROOT / "build")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

MIN_EXACT = 0.99
TEXT_LEVELS = 24
TEXT_REACH = 2
INK = 160                            # a still pixel this dark or darker, on its darkest channel, is glyph ink
# The page's still and the Settings section it was captured on (make_screenshots.render_window).
PAGES = (("overview", None), ("pending", None), ("history", None), ("statistics", None), ("diagnostics", None),
         ("settings", "continuation"))


def still_path(page: str, locale: str) -> Path:
    import make_screenshots
    return make_screenshots.window_targets(locale)[page]


def compare(rendered: bytes, still: tuple, client: tuple, light=None) -> dict:
    """The comparison of a rendered client area (RGB) with a still (width, height, RGB, alpha): `exact` (the share of
    pixels compared that are the same), `worst` (levels), `outside` (differing pixels that are not a text edge),
    `light` (differing pixels of the light's own), `passed`."""
    import make_screenshots
    width, height, rgb, alpha = still
    client_w, client_h = client
    top = height - client_h
    if width != client_w or top < 0:
        return {"exact": 0.0, "worst": 255, "outside": client_w * client_h, "light": 0, "passed": False,
                "why": "the still is %dx%d, the client area %dx%d" % (width, height, client_w, client_h)}
    owned = set()
    if light is not None:
        owned = {(x, y - top) for x, y, _samples in make_screenshots.light_pixels(light)}
    compared = same = worst = outside = light_differs = 0
    for y in range(client_h):
        row = rendered[y * client_w * 3:(y + 1) * client_w * 3]
        base = ((top + y) * width) * 3
        other = rgb[base:base + client_w * 3]
        clear = alpha is not None and min(alpha[(top + y) * width:(top + y + 1) * width]) < 255
        if row == other and not clear:
            compared += client_w
            same += client_w
            continue
        for x in range(client_w):
            if clear and alpha[(top + y) * width + x] < 255:
                continue
            if (x, y) in owned:
                light_differs += row[x * 3:x * 3 + 3] != other[x * 3:x * 3 + 3]
                continue
            compared += 1
            a, b = row[x * 3:x * 3 + 3], other[x * 3:x * 3 + 3]
            if a == b:
                same += 1
                continue
            level = max(abs(a[c] - b[c]) for c in range(3))
            worst = max(worst, level)
            if level > TEXT_LEVELS or not _near_ink(rgb, width, height, x, top + y):
                outside += 1
    exact = same / float(compared) if compared else 0.0
    return {"exact": round(exact, 6), "worst": worst, "outside": outside, "light": light_differs,
            "passed": exact >= MIN_EXACT and outside == 0}


def _near_ink(rgb: bytes, width: int, height: int, x: int, y: int) -> bool:
    for yy in range(max(0, y - TEXT_REACH), min(height, y + TEXT_REACH + 1)):
        for xx in range(max(0, x - TEXT_REACH), min(width, x + TEXT_REACH + 1)):
            if min(rgb[(yy * width + xx) * 3:(yy * width + xx) * 3 + 3]) <= INK:
                return True
    return False


def pages_at_rest(locale: str) -> list:
    """The render job's frames for every page at rest, its light at the still's moment (0)."""
    frames = []
    for index, (page, section) in enumerate(PAGES):
        frame = {"index": index, "locale": locale, "page": page, "light": 0}
        if section:
            frame["section"] = section
        frames.append(frame)
    return frames


def dialog_frame(locale: str) -> dict:
    """The render job's frame for the Timeline dialog over Pending, its first task chosen as the window chooses it."""
    return {"index": len(PAGES), "locale": locale, "page": "pending", "light": 0, "dialog": {"kind": "timeline"}}


def compare_dialog(picture: bytes, bounds: dict, client: tuple, still: tuple) -> dict:
    """The dialog drawn over the window (RGB client area `picture`, its parts' `bounds`) held to the pending still:
    three probes - the dialog's ground, the face of its Close button and its title bar - each exactly the colour the
    still has at the control it is made of. `exact` is the share that match, `worst` the largest difference in levels,
    `outside` how many do not."""
    width, height, rgb, _alpha = still
    client_w, client_h = client
    top = height - client_h

    def colour(data, x, y, wide):
        at = (int(y) * wide + int(x)) * 3
        return tuple(data[at:at + 3])

    window = bounds["dialog.window"]
    close = bounds["dialog.close"]
    retry = bounds["pending.retry"]
    probes = (
        ("ground", colour(picture, window[0] + 1 + 4, window[1] + top + 4, client_w), colour(rgb, 8, top + 200, width)),
        ("close", colour(picture, close[0] + 10, close[1] + close[3] // 2, client_w),
         colour(rgb, retry[0] + 10, top + retry[1] + retry[3] // 2, width)),
        ("title bar", colour(picture, window[0] + window[2] // 2, window[1] + 6, client_w),
         colour(rgb, width // 2, 8, width)),
    )
    worst = 0
    wrong = []
    for name, drawn, wanted in probes:
        level = max(abs(a - b) for a, b in zip(drawn, wanted))
        worst = max(worst, level)
        if level:
            wrong.append(name)
    return {"exact": round((len(probes) - len(wrong)) / float(len(probes)), 6), "worst": worst, "outside": len(wrong),
            "light": 0, "passed": not wrong, "probes": [name for name, _a, _b in probes], "wrong": wrong}


def check(exe: Path, work: Path, locales=("en", "ko"), forms=None) -> dict:
    """{"<locale>/<page>": comparison} for each page in each locale, drawn now by the render mode at `exe`, and
    {"<locale>/dialog": comparison} for the Timeline dialog over Pending (compare_dialog)."""
    import make_screenshots
    import motion_window
    manifest = json.loads(make_screenshots.MANIFEST.read_text(encoding="utf-8"))
    results = {}
    for locale in locales:
        answers = (forms or {}).get(locale) or {"answers": motion_window.answers(locale)}
        out = Path(work) / ("fidelity-" + locale)
        overview = still_path("overview", locale)
        frame = make_screenshots.read_png(overview)
        job = {"out": str(out / "frames"), "theme": "light", "design": "soft", "forms": {locale: answers},
               "scale": make_screenshots.PINNED_SCALE,
               "targets": ["dialog.window", "dialog.close", "pending.retry"], "outer": [frame[0], frame[1]],
               "chrome": motion_window.chrome({"window": {"still": str(overview.relative_to(make_screenshots.ROOT))}}),
               "frames": pages_at_rest(locale) + [dialog_frame(locale)]}
        result = motion_window.render(exe, job, out)
        pictures = list(motion_window.pictures(result, out / "frames"))
        _index, picture, bounds = pictures[-1]
        results["%s/dialog" % locale] = compare_dialog(picture, bounds, tuple(result["client"]),
                                                       make_screenshots.read_png(still_path("pending", locale)))
        for (_index, picture, _bounds), (page, _section) in zip(pictures, PAGES):
            path = still_path(page, locale)
            key = str(path.relative_to(make_screenshots.ROOT)).replace("\\", "/")
            lights = (manifest.get("lights", {}).get(key) or {}).get("lights") or [None]
            results["%s/%s" % (locale, page)] = compare(picture, make_screenshots.read_png(path),
                                                        tuple(result["client"]), lights[0])
    return results
