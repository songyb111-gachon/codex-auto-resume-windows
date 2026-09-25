"""The status light: which colour a state is drawn in, and how it breathes.

Frame by frame, from one table, so the window's light, the panel's, the icon's and the popup's
are the same light at the same moment in the same cycle.
"""
from __future__ import annotations

import math

from .tokens import palette



# ------------------------------------------------------------------- the status light
# A flat dot whose colour says what the watcher is doing, with a soft glow that says it is
# alive. The dot keeps the size each surface has always drawn; only its colour rule and its
# glow are decided here, once, for the window, the popup and the panel.
#
# Every state in which the watcher runs with recovery on is the brand's `active` cyan - the
# colour the dot had until v0.6.3 drew waiting and checking in blue. The word beside the dot
# and the motion tell those four apart - waiting and monitoring by the word alone since v0.6.9, as the icon always did. A stopped or unknown watcher and a pause keep the
# greys they have always had, with no glow at all; amber is for a watcher that runs and is not
# well, and red for a failure.
STATUS_DOT = {"window": 5, "popup": 4.5, "panel": 6, "mini": 4}   # radius, CSS px
STATUS_FILL = {"monitoring": "active", "waiting": "active", "checking": "active",
               "recovering": "active", "attention": "attention", "failed": "danger",
               "paused": "paused", "idle": "idle"}
# High Contrast: a solid dot in a system colour, never a glow.
STATUS_SYSTEM = {"monitoring": "Highlight", "waiting": "Highlight", "checking": "Highlight",
                 "recovering": "Highlight", "attention": "WindowText", "failed": "WindowText",
                 "paused": "GrayText", "idle": "GrayText"}
# The light. Three cuts were wrong in three directions, and the user named each: a glow 7 px round a dot that never
# changed - "너무 많이 커지는거 같아"; a dot that blinked, deep and quick - "너무 빠르게 깜빡이는거 같아 / 은은한
# 느낌이 있어야해 부드럽고"; and an answer that shrank the swing, which is the wrong lever - "지금은 너무 안 보여".
# Then: "이번에는 상태등의 정석대로 해줘". So the shape is the ordinary one for a light this size and nothing of
# ours - one symmetric cosine a cycle near a resting breath, a deep swing taken in light and drawn through the
# screen's gamma, a glow that rides the brightness, and a reach that is a share of the dot rather than a count of
# pixels. docs/BRAND.md sets out why each of those is what it is.
#
# Monitoring runs it every monitoring_ms, recovering every recovering_ms, attention every attention_ms and a failure
# every failed_ms, each for as long as it lasts. Until v0.6.8 a problem ran it once and then held still; the user:
# "빨간 상태등일 때도 상태등이 움직이게 해줘", then "확인필요는 천천히 계속 부드럽게 깜빡이고, 실패는 빠르게
# 움직이는거도 필요해". So attention is the slowest breath of all and a failure the quickest, and nothing pulses
# once. A cycle begins and ends at the top, where a still light also sits, so a light
# that starts moving does not jump in brightness; the glow is the one thing that arrives with the motion. Waiting
# breathes on monitoring's rhythm (waiting_ms is monitoring_ms): it is the watcher watching, with something to watch for, and until
# v0.6.9 it held lit and still while the notification-area icon, which draws it as watching, kept moving - the user,
# of the panel: "상태등이 맨위에 있는건 안 깜빡이네?". Checking holds lit with no glow and turns its arc. Every light
# holds still under Reduce motion or Windows' animation setting; High Contrast is a solid dot. The glow is a falloff, never a disc: at its peak, `peak` times
# `edge_alpha` at the dot's edge, `near_alpha` at `near_at` of the reach, `far_alpha` at `far_at`, nothing at the
# reach, straight between; a smaller spread is that falloff drawn smaller about the centre, so it grows out from
# under the dot, and at most it reaches 8 CSS px from the window's dot centre, inside the 28 px box kept for it.
GLOW = {
    # The breath. `low` is how much light is left at the bottom of it, `gamma` turns light into what
    # an eye on a screen sees, `peak` is the glow's opacity at full brightness and `reach` how far it
    # gets past the dot's edge.
    "low": 0.35, "gamma": 2.2, "peak": 0.50, "reach_of_radius": 0.6,
    "edge_alpha": 0.67, "near_at": 0.14, "near_alpha": 0.58, "far_at": 0.66, "far_alpha": 0.50,
    "monitoring_ms": 4400, "waiting_ms": 4400, "recovering_ms": 2800, "attention_ms": 5600, "failed_ms": 1200,
    # Checking also turns the arc every surface already drew: `arc_gap` past the dot's edge,
    # `arc_width` wide, `arc_sweep` degrees long, in `active` at `arc_alpha`. With motion
    # reduced it holds at `arc_still_at` degrees.
    "arc_ms": 1600, "arc_alpha": 0.55, "arc_gap": 3, "arc_width": 1.6, "arc_sweep": 100,
    "arc_still_at": 300,
}
GLOW_BREATHES = ("monitoring", "waiting", "recovering", "attention", "failed")



def status_colour(state, theme="light") -> str:
    """The `#RRGGBB` a state's dot and glow are drawn in, in a theme (status_fill's token)."""
    return palette(theme)[status_fill(state)]



def status_fill(state) -> str:
    """The colour token a state's dot is filled with. Anything unknown is idle grey."""
    return STATUS_FILL.get(state, "idle")


def status_system(state) -> str:
    """The High Contrast system colour a state's dot is filled with."""
    return STATUS_SYSTEM.get(state, "GrayText")


def _breath(elapsed_ms, cycle_ms) -> float:
    """0 at the start of a cycle, 1 halfway, 0 again: a raised cosine."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * (elapsed_ms % cycle_ms) / cycle_ms)


def glow_floor() -> float:
    """What the dot is drawn at when the breath is at its lowest: `low` of the light, as it is seen."""
    return GLOW["low"] ** (1.0 / GLOW["gamma"])


def glow_phase(fraction):
    """The light at `fraction` of one breath, 0 to 1, as (dim, spread): how far the dot is drawn toward the ground it
    sits on (0 at rest) and how far out the glow is (0 none, 1 its peak). One symmetric cosine, taken in light and
    raised to 1/gamma to be drawn; the glow rides the brightness, squared so it keeps to the top of the breath."""
    breath = 0.5 + 0.5 * math.cos(2.0 * math.pi * (fraction % 1.0))            # 1 at rest, 0 at the low
    lit = (GLOW["low"] + (1.0 - GLOW["low"]) * breath) ** (1.0 / GLOW["gamma"])
    floor = glow_floor()
    risen = (lit - floor) / (1.0 - floor)
    return 1.0 - lit, risen * risen


def glow(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """The status light for one frame, or None when it is off (paused, idle, unknown: a grey dot and nothing else).

    `dim` is how far the dot is drawn from its colour toward the ground under it, `opacity` multiplies the glow's
    falloff (glow_stops), `spread` is how far out it is (glow_radius) and `arc` is the checking arc's start angle in
    degrees, or None. `elapsed_ms` is any clock that does not run backwards. `since_entered_ms`, how long the state
    has been shown, is what a problem's one pulse ran on until v0.6.8; every light that moves now loops on
    `elapsed_ms`, and the argument is still taken so the surfaces that pass it are unchanged. High Contrast neither
    dims the dot nor draws a glow, which is the caller's check.
    """
    fraction = arc = None
    if state in GLOW_BREATHES:
        fraction = None if reduced else (elapsed_ms % GLOW[state + "_ms"]) / GLOW[state + "_ms"]
    elif state == "checking":
        arc = GLOW["arc_still_at"] if reduced else (elapsed_ms % GLOW["arc_ms"]) / GLOW["arc_ms"] * 360.0
    else:
        return None
    dim, spread = (0.0, 0.0) if fraction is None else glow_phase(fraction)
    return {"dim": dim, "opacity": GLOW["peak"] * spread, "spread": spread, "arc": arc}


def glow_moves(state, since_entered_ms=None, *, reduced=False) -> bool:
    """Whether a frame timer has anything to draw for this state: every breathing state and checking's arc, for as
    long as the state lasts. `since_entered_ms` is taken and read by nothing since v0.6.8 (see glow)."""
    return not reduced and (state in GLOW_BREATHES or state == "checking")


def glow_reach(dot_radius: float) -> float:
    """How far past the dot's edge the glow gets at the top of the breath: a share of the dot, so the window's
    10 px light and the panel's 12 px one are the same light at two sizes."""
    return GLOW["reach_of_radius"] * dot_radius


def glow_stops(dot_radius: float) -> tuple:
    """The falloff as (fraction of the outer radius from the centre, alpha factor) stops, for a gradient filling the
    glow's disc at any spread; the first two lie under the dot. GDI+ path gradients count their positions from the
    edge inward, so the window and the popup reverse these."""
    outer, reach = float(glow_extent(dot_radius)), glow_reach(dot_radius)
    return ((0.0, GLOW["edge_alpha"]), (dot_radius / outer, GLOW["edge_alpha"]),
            ((dot_radius + reach * GLOW["near_at"]) / outer, GLOW["near_alpha"]),
            ((dot_radius + reach * GLOW["far_at"]) / outer, GLOW["far_alpha"]),
            (1.0, 0.0))


def glow_radius(dot_radius: float, spread: float = 1.0) -> float:
    """The glow's outer radius in CSS px for a frame's `spread`; times the display scale to draw."""
    return dot_radius + glow_reach(dot_radius) * spread


def glow_extent(dot_radius: float) -> float:
    """The largest outer radius any frame draws: the band a surface keeps free for the glow."""
    return glow_radius(dot_radius, 1.0)
