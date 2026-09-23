"""Where the popup goes, and what is under the pointer.

Beside the notification area, on the monitor the icon is on, cut to the work area - and never
over the taskbar, whichever edge it is on.
"""
from __future__ import annotations




# ------------------------------------------------------------------------------ placement
def taskbar_edge(work, monitor, anchor=None) -> str:
    """Which edge of the monitor the taskbar is on, from how the work area is inset."""
    if work[3] < monitor[3]:
        return "bottom"
    if work[1] > monitor[1]:
        return "top"
    if work[0] > monitor[0]:
        return "left"
    if work[2] < monitor[2]:
        return "right"
    if anchor is not None:
        # An auto-hidden taskbar takes no work area; the icon is on the nearest edge.
        cx, cy = (anchor[0] + anchor[2]) / 2, (anchor[1] + anchor[3]) / 2
        distance = {"bottom": monitor[3] - cy, "top": cy - monitor[1],
                    "left": cx - monitor[0], "right": monitor[2] - cx}
        return min(distance, key=lambda edge: distance[edge])
    return "bottom"


def _clamp(value, low, high):
    if high < low:
        return low
    return max(low, min(value, high))


def place(size, work, monitor, icon=None, cursor=None, gap=12):
    """Where the window goes: beside the icon, on the taskbar's side, inside the work area.

    Rectangles are (left, top, right, bottom) in physical pixels and may be negative on a
    monitor left of or above the primary one. Without an icon rectangle (the icon is in
    the overflow flyout) the cursor stands in for it. Returns (x, y, edge).
    """
    width, height = size
    anchor = icon
    if anchor is None and cursor is not None:
        anchor = (cursor[0], cursor[1], cursor[0] + 1, cursor[1] + 1)
    edge = taskbar_edge(work, monitor, anchor)
    left, top, right, bottom = work
    if anchor is None:
        anchor = (right - 1, bottom - 1, right, bottom)
    cx, cy = (anchor[0] + anchor[2]) // 2, (anchor[1] + anchor[3]) // 2
    if edge == "bottom":
        x, y = cx - width // 2, min(anchor[1], bottom) - gap - height
    elif edge == "top":
        x, y = cx - width // 2, max(anchor[3], top) + gap
    elif edge == "left":
        x, y = max(anchor[2], left) + gap, cy - height // 2
    else:
        x, y = min(anchor[0], right) - gap - width, cy - height // 2
    x = _clamp(x, left + gap, right - gap - width)
    y = _clamp(y, top + gap, bottom - gap - height)
    return x, y, edge


# --------------------------------------------------------------------- hit testing, focus
def hit_test(targets, x, y):
    for target, (left, top, right, bottom) in targets:
        if left <= x < right and top <= y < bottom:
            return target
    return None


def focus_order(targets) -> list:
    """Reading order: each task's switch, then Pause/Resume, then Open Dashboard."""
    return [target for target, _ in targets]


def next_focus(order, current, backwards=False):
    if not order:
        return None
    if current not in order:
        return order[-1] if backwards else order[0]
    index = order.index(current) + (-1 if backwards else 1)
    return order[index % len(order)]
