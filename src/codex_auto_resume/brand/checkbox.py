"""The check box and its tick: the state table, its High Contrast twin, and the geometry.

One control drawn three ways - by the window, by the panel and by the popup - from one table,
because a check box that means the same thing should not look like three controls.
"""
from __future__ import annotations

import math

from .scale import LAYOUT
from .tokens import palette


# ------------------------------------------------------------------- the check box
# v0.6.4. A switch turns something that runs on or off; a check box picks which items of a list
# apply - which kinds of interruption may be recovered, which events notify. The same setting is
# the same kind on every surface, and a check box sits to the left of its label everywhere.
#
# It is the switch's material: unchecked, the sunken well fields and switch tracks are (`inset`
# with the inset elevation inside its border); checked, the accent with an `on_accent` mark. Its
# edge unchecked is `muted`, not `line`, because an empty box has no knob to identify it and a
# `line` hairline on the card is 1.3:1 - under the 3:1 a control's boundary needs. Disabled, it is
# what a disabled field is: `surface`, a `line` hairline, no lift, a `muted` mark if checked.
# Sizes are LAYOUT's check_size, check_gap and check_stroke and RADII's check; the focus ring is
# every control's. Each state's entries are palette tokens; `well` says whether the inset
# elevation is drawn inside the border.
CHECKBOX = {
    "off":          {"fill": "inset",   "edge": "muted",  "mark": None,        "well": True},
    "on":           {"fill": "accent",  "edge": "accent", "mark": "on_accent", "well": False},
    "off_disabled": {"fill": "surface", "edge": "line",   "mark": None,        "well": False},
    "on_disabled":  {"fill": "surface", "edge": "line",   "mark": "muted",     "well": False},
}
# High Contrast / forced colours: system colours by the names Windows Forms gives them (the popup
# and the window read these; the panel maps them through SYSTEM_CSS). Never a shadow.
CHECKBOX_SYSTEM = {
    "off":          {"fill": "Window",    "edge": "WindowText", "mark": None},
    "on":           {"fill": "Highlight", "edge": "Highlight",  "mark": "HighlightText"},
    "off_disabled": {"fill": "Window",    "edge": "GrayText",   "mark": None},
    "on_disabled":  {"fill": "Window",    "edge": "GrayText",   "mark": "GrayText"},
}
# The same system colours as CSS names them in `@media (forced-colors: active)`.
SYSTEM_CSS = {"Window": "Canvas", "WindowText": "CanvasText", "Highlight": "Highlight",
              "HighlightText": "HighlightText", "GrayText": "GrayText", "WindowFrame": "CanvasText",
              "Control": "Canvas"}
# The mark: a polyline's centre line - start, corner, end - in CSS px from the box's outer
# top-left corner (its border included), on the check_size box. Stroked check_stroke wide with
# flat ends and a mitred corner, which is exactly the outline check_mark_outline() returns and
# the panel clips with (`--check-mark-shape`). Both arms run at 45 degrees and meet at a right
# angle, the long arm twice the short one; the outline is centred across the box and sits a tenth
# of a pixel low, where the eye puts a tick's weight.
CHECK_MARK = ((4.5, 8.75), (7.5, 11.75), (13.5, 5.75))



def check_box_state(checked, enabled=True) -> str:
    """The CHECKBOX key for a box: 'off', 'on', 'off_disabled' or 'on_disabled'."""
    return ("on" if checked else "off") + ("" if enabled else "_disabled")


def check_box(checked, enabled=True, theme="light") -> dict:
    """A check box's colours in a theme: `fill`, `edge` and `mark` as `#RRGGBB` (`mark` None when
    there is none) and `well`, whether the inset elevation is drawn inside the border."""
    entry, tokens = CHECKBOX[check_box_state(checked, enabled)], palette(theme)
    return {"fill": tokens[entry["fill"]], "edge": tokens[entry["edge"]],
            "mark": tokens[entry["mark"]] if entry["mark"] else None, "well": entry["well"]}


def check_box_system(checked, enabled=True) -> dict:
    """The same box in High Contrast: `fill`, `edge` and `mark` as Windows system colour names."""
    return dict(CHECKBOX_SYSTEM[check_box_state(checked, enabled)])


def css_system(name: str) -> str:
    """A Windows system colour name as CSS's forced-colors keyword (WindowText is CanvasText)."""
    return SYSTEM_CSS[name]


def check_mark(scale: float = 1.0, left: float = 0.0, top: float = 0.0) -> tuple:
    """The mark's centre line - start, corner, end - in device px for a box whose outer top-left
    corner is at (left, top); stroke it LAYOUT check_stroke * scale wide, flat ends, mitred."""
    return tuple((left + x * scale, top + y * scale) for x, y in CHECK_MARK)


def check_mark_outline(scale: float = 1.0, left: float = 0.0, top: float = 0.0) -> tuple:
    """The stroked mark as a filled polygon: six points, the outer side first from the start.

    Flat ends and a mitred corner, so filling this is exactly stroking check_mark(): the panel
    clips with it, and a surface without a pen that mitres can fill it instead.
    """
    (x0, y0), (x1, y1), (x2, y2) = CHECK_MARK
    half = LAYOUT["check_stroke"] / 2.0

    def normal(ax, ay, bx, by):
        length = math.hypot(bx - ax, by - ay)
        return (-(by - ay) / length, (bx - ax) / length)

    n1, n2 = normal(x0, y0, x1, y1), normal(x1, y1, x2, y2)
    joint = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
    mitre = (half * (n1[0] + n2[0]) / joint, half * (n1[1] + n2[1]) / joint)
    points = ((x0 + half * n1[0], y0 + half * n1[1]), (x1 + mitre[0], y1 + mitre[1]),
              (x2 + half * n2[0], y2 + half * n2[1]), (x2 - half * n2[0], y2 - half * n2[1]),
              (x1 - mitre[0], y1 - mitre[1]), (x0 - half * n1[0], y0 - half * n1[1]))
    return tuple((left + x * scale, top + y * scale) for x, y in points)
