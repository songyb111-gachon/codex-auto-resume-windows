"""How long a change takes, and the one curve it takes it on.

CSS's `cubic-bezier` solved the way a browser solves it, so that a transition written here and
a transition written in the panel's stylesheet are the same movement rather than two that look
alike.
"""
from __future__ import annotations


# Motion is a state, not decoration: the state light's is GLOW (below), and every recurring motion
# stops when a person has asked Windows to reduce motion. What is left here is the controls' -
# since v0.6.5 a switch glides when it changes, its knob sliding and its track cross-fading on
# every surface, in `transition_ms` on one curve: `ease`, an ease-out (easeOutCubic) written as a
# CSS cubic-bezier's four control numbers, so a switch answers the click at once and settles. The
# panel writes it as `--transition-ease`, the window reads Brand.TransitionEase*, the popup calls
# ease(); a change that waits for confirmation starts only once confirmed, and nothing slides
# under Reduce motion, Windows' animation setting or High Contrast.
MOTION = {"transition_ms": 160, "ease": (0.33, 1.0, 0.68, 1.0)}



def _bezier(a, b, t):
    """One coordinate of a CSS cubic-bezier from (0, 0) to (1, 1) through control values a and b."""
    return ((1.0 - 3.0 * b + 3.0 * a) * t + (3.0 * b - 6.0 * a)) * t * t + 3.0 * a * t


def _bezier_slope(a, b, t):
    return 3.0 * (1.0 - 3.0 * b + 3.0 * a) * t * t + 2.0 * (3.0 * b - 6.0 * a) * t + 3.0 * a


def ease(progress: float) -> float:
    """How far a transition has come, 0 to 1, after `progress` of its time: MOTION's curve.

    CSS's cubic-bezier, solved the way browsers solve it - a few Newton steps on the curve's x,
    then halving if they do not settle - so the window (Brand.Ease), the popup and the panel's
    stylesheet move a switch along the same path. Anything outside 0..1 is held at its end.
    """
    if not progress > 0.0:
        return 0.0
    if progress >= 1.0:
        return 1.0
    x1, y1, x2, y2 = MOTION["ease"]
    t = progress
    for _ in range(8):
        error = _bezier(x1, x2, t) - progress
        if abs(error) < 1e-7:
            return _bezier(y1, y2, t)
        slope = _bezier_slope(x1, x2, t)
        if abs(slope) < 1e-6:
            break
        t = min(1.0, max(0.0, t - error / slope))
    low, high, t = 0.0, 1.0, progress
    for _ in range(40):
        value = _bezier(x1, x2, t)
        if abs(value - progress) < 1e-7:
            break
        if value < progress:
            low = t
        else:
            high = t
        t = (low + high) / 2.0
    return _bezier(y1, y2, t)
