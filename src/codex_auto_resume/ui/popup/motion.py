"""What moves, and how far along it is.

The status light's breath and the glide a row makes when it changes, both read from `brand`, so
the popup, the window and the panel move alike.
"""
from __future__ import annotations

from ... import brand


# ------------------------------------------------------------------------------- motion
def halo(state, elapsed_ms, since_entered_ms=None, *, reduced=False, design="soft"):
    """The state dot's light for one frame, or None when it is off: brand's status light, which the window and the
    panel draw too. `dim` is how far the dot is drawn toward the card, `opacity` multiplies the glow's soft falloff,
    `spread` is how far out the glow is and `arc` the checking arc's start angle in degrees, or None. In the design
    (v0.6.10): Still holds it, and Plain dims it with no glow."""
    return brand.glow(state, elapsed_ms, since_entered_ms, reduced=reduced, design=design)


def animates(state, since_entered_ms=0, *, reduced=False, design="soft") -> bool:
    """Whether the frame timer should run at all."""
    return brand.glow_moves(state, since_entered_ms, reduced=reduced, design=design)


# v0.6.5: a task's switch glides when it changes - the knob slides end to end and the track
# cross-fades between the grey well and the accent - in brand's one transition time, on brand's
# one curve, as the window's and the panel's switches do. A glide is (started_ms, from, to), the
# ends being how far on the switch is: 0 off, 1 on. It starts only when a switch the window has
# already drawn is drawn the other way - which, for a change somebody asked for here, is when the
# control layer has confirmed it: the press only fades the switch while the answer is awaited, so
# it never moves and snaps back. With motion reduced, in High Contrast, in a design that does not
# glide (v0.6.10: Still, Classic, Plain), while the window is hidden and on the frame that opens it,
# a change is simply drawn in its new place.
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
