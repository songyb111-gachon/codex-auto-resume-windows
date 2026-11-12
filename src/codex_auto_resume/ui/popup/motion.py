"""What moves, and how far along it is.

The status light's breath and the glide a row makes when it changes, both read from `brand`, so
the popup, the window and the panel move alike.
"""
from __future__ import annotations

import time

from ... import brand


# ------------------------------------------------------------------------------- motion
def halo(state, elapsed_ms, since_entered_ms=None, *, reduced=False, design="soft"):
    """The state dot's light for one frame, or None when it is off: brand's status light, which the window and the
    panel draw too. `dim` is how far the dot is drawn toward the card, `opacity` multiplies the glow's soft falloff,
    `spread` is how far out the glow is and `arc` the checking arc's start angle in degrees, or None. In the design
    (v0.6.10): Plain dims it with no glow."""
    return brand.glow(state, elapsed_ms, since_entered_ms, reduced=reduced, design=design)


def scene_ms(reduced, since) -> float:
    """How far on the day's scene is: at its first instant, and still, with motion reduced."""
    return 0.0 if reduced else (time.monotonic() - since) * 1000.0


def animates(state, since_entered_ms=0, *, reduced=False) -> bool:
    """Whether the frame timer should run at all. The design has no say: every design moves, and only a
    stopper holds it."""
    return brand.glow_moves(state, since_entered_ms, reduced=reduced)


# v0.6.5: a task's switch glides when it changes - the knob slides end to end and the track
# cross-fades between the grey well and the accent - in brand's one transition time, on brand's
# one curve, as the window's and the panel's switches do. A glide is (started_ms, from, to), the
# ends being how far on the switch is: 0 off, 1 on. It starts only when a switch the window has
# already drawn is drawn the other way - which, for a change somebody asked for here, is when the
# control layer has confirmed it: the press only fades the switch while the answer is awaited, so
# it never moves and snaps back. With motion reduced, in High Contrast, while the window is hidden
# and on the frame that opens it, a change is simply drawn in its new place.
# v0.6.23 (second round): what opens - the popup, the icon's menu, a row's menu - fades in over brand's transition and rises
# into place from SPACING xs below it, on brand's curve, as the window's menu does (gui/SoftMenu.cs SoftMenuLayer.Tick); a menu
# closed fades out from where it was in brand's press time (SoftLayerFade). With motion held each is simply there and gone.
GLIDE_FRAME_MS = 16          # a one-shot glide's frames (an opening, a button's face): the card's own (notice_card.FRAME_MS)


def opening(elapsed_ms, rise) -> tuple:
    """(alpha 0 to 255, how far below its place, whether it has arrived) `elapsed_ms` into an opening `rise` px below."""
    progress = max(0.0, float(elapsed_ms)) / float(brand.MOTION["transition_ms"])
    if progress >= 1.0:
        return 255, 0, True
    eased = brand.ease(progress)
    return int(round(255 * eased)), int(round(rise * (1.0 - eased))), False


def closing(elapsed_ms, alpha) -> tuple:
    """(alpha, whether it has gone) `elapsed_ms` into a fade-out from `alpha`, in brand's press time."""
    progress = max(0.0, float(elapsed_ms)) / float(brand.MOTION["press_ms"])
    if progress >= 1.0:
        return 0, True
    return int(round(alpha * (1.0 - brand.ease(progress)))), False


# v0.6.23 (second round): a button's face glides between what its states look like - at rest, under the pointer, pressed, busy -
# as the window's buttons do (gui/SoftFields.cs, SoftSurfaceGlide): a press and its release in brand's press time, the rest in
# its transition, from whatever it showed, so a change that turns back half way leaves from where it is. A face is
# (started_ms, (fill, edge) it left from, length_ms); its shadow swaps at once, as the window's does.
def face_state(item, hover, pressed) -> str:
    """What a laid-out button shows now: the renderer draws each state's colours (Renderer.face_colours)."""
    target = item["target"]
    return "busy" if item.get("busy") else "pressed" if pressed == target else "hover" if hover == target else "rest"


def face_length(before, after) -> int:
    """How long a face takes from `before` to `after`: a press or its release is brand's press, the rest its transition."""
    return brand.MOTION["press_ms" if "pressed" in (before, after) else "transition_ms"]


def face_amount(face, now_ms) -> tuple:
    """(how far from the face it left toward the state's, eased, whether it is over) at `now_ms`."""
    started, _, length = face
    progress = (now_ms - started) / float(max(1, length))
    if progress >= 1.0:
        return 1.0, True
    return brand.ease(max(0.0, progress)), False


def mixed(one, other, amount) -> tuple:
    """(red, green, blue) `amount` of the way from `one` to `other`."""
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(one, other))


def glide_amount(glide, now_ms) -> tuple:
    """(how far on the switch is, whether the glide is over) at `now_ms`, eased."""
    started, begin, end = glide
    progress = (now_ms - started) / float(brand.MOTION["transition_ms"])
    if progress >= 1.0:
        return end, True
    return begin + (end - begin) * brand.ease(progress), False


def next_glides(seen, previous, glides, now_ms, *, animate=True) -> dict:
    """The glides running after a switch table `seen` ({target: checked}) replaced `previous`.

    A glide still heading where its switch is drawn keeps going; a switch drawn the other way
    from before starts one from wherever it is now - its end, or partway through a glide it is
    turning back from. `animate` False stops every glide where it would have ended; no `previous`
    (the window has just opened) starts none; a switch no longer drawn loses its glide.
    """
    if not animate:
        return {}
    running = {}
    for target, checked in seen.items():
        end = 1.0 if checked else 0.0
        glide = glides.get(target)
        if glide is not None and glide[2] == end:
            running[target] = glide
            continue
        if previous is None or target not in previous or bool(previous[target]) == bool(checked):
            continue
        begin = glide_amount(glide, now_ms)[0] if glide is not None else 1.0 - end
        running[target] = (now_ms, begin, end)
    return running
