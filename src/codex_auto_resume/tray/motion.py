"""What the icon does while it is watched: the states it moves in, and every frame of them.

The arithmetic and the pixels both, because the documentation's picture builder treats them
as one thing - `build/make_screenshots.py` hashes this group by name to decide whether the
icon's GIF has to be drawn again, and parting the table from the composition would part that
key from what it is a key for.

Pure but for one question put to the popup: whether it is asking for attention.
"""
from __future__ import annotations

import math
import time

from .. import brand



# ------------------------------------------------------------------------ the icon's motion
# The icon does not copy the windows' six-state status light: sixteen pixels across and glanced at, it speaks
# a smaller language, and the distinctions it drops - waiting, checking, monitoring - are ones nobody acts on:
#
#   watching    the watcher runs with recovery on: a loop of five of brand's monitoring breaths (22 s) - three
#               breaths of the head, then a sweep out and back in the last two, at full brightness;
#   recovering  a continuation is being sent or is running in Codex: the head sweeps out and back
#               over and over, at twice the speed, at full brightness and never breathing;
#   idle        paused: the head is grey (brand's `idle` fill) and still;
#   attention   needs a person: amber, breathing in its place on brand's attention rhythm (5.6 s), the slowest
#               breath there is, for as long as it lasts;
#   failed      a failure: the danger colour, sweeping out and back like recovering but twice as quickly - a sweep
#               every 1.98 s - and blinking as it goes, on the red light's own 1.2 s breath, for as long as it lasts:
#               the one state whose head breathes while it travels (the user: "실패시에는 깜빡이면서 움직이면
#               좋겠는데"); watching and recovering keep v0.6.5's rule below. The two keep different time, neither
#               a whole number of the other ("달라야해 / 같으면 안 예뻐"): they meet again only every 39.6 s.
#
# Until v0.6.8 attention and a failure pulsed once and held. The user: "빨간 상태등일 때도 상태등이 움직이게
# 해줘", then "확인필요는 천천히 계속 부드럽게 깜빡이고, 실패는 빠르게 움직이는거도 필요해" - and, asked which,
# that a failure's head moves quickly too, not only its light.
#
# The user, on a first cut that breathed under a turn every thirty seconds: "회전할 땐 안 깜빡이게 해 / 회전하는
# 시간도 깜빡임 시간의 배수에 맞춰서 둘이 안 겹치게", and "시계가 나을거 같아서". So the head never breathes while it
# travels, its slot is a whole number of breaths and both its ends are at full brightness - every hand-over is
# there, with no jump - and it leaves its place clockwise, along the white stroke only, never crossing the gap.
#
# The sweeping mark is the mark's own head running along its own ring - "the ring is the wait, the gap is the
# interruption, the head is the moment it resumes" - so the motion adds no shape and no colour, and breathing is the
# head's brightness: no room for a halo here. The shape and the taskbar handling are as ever, and since v0.6.8 no
# badge sits on top: the head is the only thing that says the state, on the tray as on the taskbar button.
#
# Of brand.GLOW the icon reads three rhythms and nothing else: monitoring_ms (watching's breath, and so every slot
# of its loop and of recovering's and a failure's sweeps), attention_ms (attention's breath) and failed_ms (the blink
# a failure's head keeps as it sweeps). Its own numbers are
# ICON_MOTION's, not in brand.GLOW, every key of which is the windows' status light's; the taskbar button reads them from Brand.Mark.
ICON_STATES = ("watching", "recovering", "idle", "attention", "failed")
# The icon's state as a brand status-light state: its colour and its rhythm. Every value is a
# key of brand.STATUS_FILL; anything unknown is idle grey, as brand.status_fill is.
ICON_BRAND_STATE = {"watching": "monitoring", "recovering": "recovering", "idle": "idle",
                    "attention": "attention", "failed": "failed"}
# The icon's state for each status-light word: the popup's for a snapshot (icon_state), and the same word for what
# the settings window read, for its taskbar button (SettingsForm.TrayActivity, Brand.Mark.IconState). Else idle.
ICON_FOR_LIGHT = {"monitoring": "watching", "waiting": "watching", "checking": "watching", "recovering": "recovering",
                  "paused": "idle", "idle": "idle", "attention": "attention", "failed": "failed"}
# The states whose head breathes in its place, and the brand.GLOW rhythm each breathes on.
ICON_BREATHS = {"watching": "monitoring_ms", "attention": "attention_ms"}
# The states whose head sweeps: watching between its breaths, recovering and a failure all the time.
ICON_SWEEPS = ("watching", "recovering", "failed")
# The one state whose head breathes as it sweeps, and the rhythm: a failure blinks on the red light's own breath.
ICON_TRAVEL_BREATHS = {"failed": "failed_ms"}
ICON_MOTION = {
    # watching: `breaths` breaths of the head, then a sweep in a slot of `sweep_breaths` of them - `sweep_out` of
    # that slot going out, as much coming back, `sweep_hold` of it held at the far end and the rest of it at home.
    # Recovering sweeps the same shape in one breath, then rests `recover_rest` of one at home: a sweep every 3.96 s.
    # A failure sweeps recovering's shape in `failed_slot` of a breath: twice as quickly, a sweep every 1.98 s.
    "breaths": 3, "sweep_breaths": 2, "sweep_out": 0.4, "sweep_hold": 0.025, "recover_rest": 0.075,
    "failed_slot": 0.5,
    # Every frame shown costs explorer.exe a redraw: the rates that looked smooth for the least of it (measured),
    # each just inside a whole number of Windows' 15.625 ms timer ticks, which a timer waits for at the least.
    "breathe_frame_ms": 156,  # ten ticks: about six frames a second while it breathes...
    "turn_frame_ms": 62,      # ...four, sixteen, while it travels: about one frame a position at that speed
    "positions": 24,          # head positions round the ring, fifteen degrees apart
    "levels": 24,             # the breath's brightness steps: a tint of the head, never a stored frame
    "dim": 0.6,               # the breath's low, toward the badge: deeper than the light since v0.6.6 softened it
    "build_budget_ms": 2000,  # a frame table that takes longer than this is not used
    "cache": 256,             # composed frames kept, per table
}
ICON_SWEEP = (brand.ICON_SHAPE["arc_end"] - brand.ICON_SHAPE["arc_start"]) % 360.0   # the stroke, in degrees
# The badge's own deep blue the breath dims the head toward.
ICON_DIM_TOWARD = brand.ICON_BOTTOM
# The head's colour in the states that recolour it. The head sits on the icon's deep-blue badge,
# never on the taskbar, so it is the colour the dark palette gives the state - made to read on a
# dark ground - except idle's, whose dark value is a grey that all but vanishes into the badge:
# idle takes the light palette's grey. (Looked at, side by side, at 16 to 32 px.)
ICON_HEAD_PALETTE = {"idle": "light", "attention": "dark", "danger": "dark"}


def icon_state(snapshot, *, attention=False, failed=False) -> str:
    """The icon's state from the tick's snapshot: one of ICON_STATES, ICON_FOR_LIGHT of the popup's word.

    `attention` is the open popup's word (it says nothing can recover until a person acts);
    `failed` is a failure the watcher reports. Neither is ever inferred here.
    """
    if failed:
        return "failed"
    from .. import tray_popup
    word = tray_popup.snapshot_activity(snapshot, time.time(), attention=attention)
    return ICON_FOR_LIGHT.get(word, "idle")


def icon_brand_state(state) -> str:
    """The brand status-light state an icon state is drawn as; anything unknown is idle."""
    return ICON_BRAND_STATE.get(state, "idle")


def icon_head_colour(state) -> tuple:
    """The head's full colour in a state, as (red, green, blue).

    Running states keep the mark's own accent, so the icon at rest is exactly the icon it has
    always been; the others take their status colour (ICON_HEAD_PALETTE says which palette).
    """
    token = brand.status_fill(icon_brand_state(state))
    if token == "active":
        return brand.rgb(brand.ICON_ACCENT)
    return brand.rgb(brand.palette(ICON_HEAD_PALETTE.get(token, "light"))[token])


def icon_level_colour(colour, level) -> tuple:
    """The head's colour at breathing `level`: the top level is `colour`, the lowest is dimmed
    ICON_MOTION dim of the way toward the badge's deep blue."""
    top = ICON_MOTION["levels"] - 1
    level = max(0, min(top, int(level)))
    amount = ICON_MOTION["dim"] * (top - level) / float(top)
    target = brand.rgb(ICON_DIM_TOWARD)
    return tuple(int(math.floor(one + (other - one) * amount + 0.5)) for one, other in zip(colour, target))


def _breath_level(elapsed_ms, cycle_ms) -> int:
    """Full brightness at the start of a cycle, dimmest halfway, full again: brand's raised cosine
    turned round, so every breath starts and ends on the icon as it always looked."""
    top = ICON_MOTION["levels"] - 1
    return int(round(top * (1.0 - brand._breath(elapsed_ms, cycle_ms))))


def icon_turn(state, elapsed_ms) -> float:
    """How far along the stroke the head has swept from its place, clockwise, in degrees, or None when the state is
    not sweeping at all: ICON_SWEEP at the stroke's other end, brand's raised cosine over a sweep out and back with
    that cosine's top held at the far end, and 0 - not None - for whatever is left of the cycle once it is home,
    where it rests lit and still. ICON_MOTION says how long each part of a sweep takes; a failure's is recovering's
    in `failed_slot` of the time."""
    if state not in ICON_SWEEPS:
        return None
    breath, motion = float(brand.GLOW["monitoring_ms"]), ICON_MOTION
    if state == "failed":
        breath *= motion["failed_slot"]
    sweeps = motion["sweep_breaths"] if state == "watching" else 1
    out, hold = breath * sweeps * motion["sweep_out"], breath * sweeps * motion["sweep_hold"]
    start = breath * motion["breaths"] if state == "watching" else 0.0
    cycle = start + breath * sweeps if state == "watching" else 2 * out + hold + breath * motion["recover_rest"]
    into = elapsed_ms % cycle - start
    if into < 0 or into >= 2 * out + hold:
        return None if into < 0 else 0.0
    return ICON_SWEEP * brand._breath(min(into, max(out, into - hold)), 2 * out)


def icon_frame(state, elapsed_ms, since_entered_ms=None, *, reduced=False) -> tuple:
    """(head position, breathing level) for one frame: a pure function of the state and the clock.

    Position 0 is the head in its place, positions counting on clockwise round the ring, and a sweep reaches the
    one nearest ICON_SWEEP; the top level is the head's full colour, which it has for a sweep's whole cycle - but a
    failure's, which blinks as it goes (ICON_TRAVEL_BREATHS). With
    motion reduced every state is its rest: the head in its place at full colour, so the states differ by colour
    only. `since_entered_ms`, how long the state has been shown, is what a problem's one pulse ran on until v0.6.8;
    nothing reads it now, and it is still taken so its callers are unchanged.
    """
    positions, top = ICON_MOTION["positions"], ICON_MOTION["levels"] - 1
    if reduced:
        return (0, top)
    turn = icon_turn(state, elapsed_ms)
    if turn is not None:
        level = (_breath_level(elapsed_ms, brand.GLOW[ICON_TRAVEL_BREATHS[state]]) if state in ICON_TRAVEL_BREATHS
                 else top)
        return (int(round(turn / (360.0 / positions))) % positions, level)
    if state in ICON_BREATHS:
        return (0, _breath_level(elapsed_ms, brand.GLOW[ICON_BREATHS[state]]))
    return (0, top)


def icon_frame_ms(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """How soon the next frame is due, in ms, or None when nothing moves (no timer at all)."""
    if reduced:
        return None
    if icon_turn(state, elapsed_ms) is not None:
        return ICON_MOTION["turn_frame_ms"]
    if state in ICON_BREATHS:
        return ICON_MOTION["breathe_frame_ms"]
    return None


def icon_motion_allowed(*, reduced=False, contrast=False, battery_saver=False, locked=False, hidden=False,
                        frames=True) -> bool:
    """Whether the icon may move at all. Any one reason holds it still: Reduce motion (the setting
    or Windows' animation effects), High Contrast (which holds every status light still), battery
    saver, a locked or disconnected session, an icon in the overflow flyout where nobody sees it,
    or a frame table that could not be built."""
    return bool(frames) and not (reduced or contrast or battery_saver or locked or hidden)


class IconFrames:
    """The icon's frames for one size, as pixels: pure, built on any thread, drawn on the icon's.

    The mark without its head is rendered once; for each of ICON_MOTION's head positions only the
    few pixels the head can touch are rendered again, with the head kept apart so it can take any
    colour with the arithmetic a whole render uses. Position 0 in the accent is therefore the .ico's
    own image at that size, byte for byte. A frame is that and the head's colour at a breathing
    level, and nothing on top of it since v0.6.8. Top-down BGRA with straight alpha, as icon
    bitmaps are. `ground` and `heads` go into the window's Brand.Mark as they are.
    """

    def __init__(self, size):
        self.size = size = int(size)
        if size <= 0:
            raise ValueError("an icon has a size")
        positions = ICON_MOTION["positions"]
        base = bytearray(size * size * 4)
        for y, row in enumerate(brand.icon_samples(size, head=False)):
            for x, sample in enumerate(row):
                red, green, blue, alpha = brand.icon_pixel(sample, (0, 0, 0))
                index = (y * size + x) * 4
                base[index:index + 4] = bytes((blue, green, red, alpha))
        self.ground = bytes(base)
        self.heads = []
        for position in range(positions):
            angle = brand.ICON_SHAPE["arc_end"] - 360.0 * position / positions   # clockwise
            box = brand.icon_head_box(size, angle)
            self.heads.append((box, brand.icon_samples(size, head_angle=angle, box=box)))
        self._cache = {}

    def compose(self, position, head) -> bytes:
        """One frame: the head at `position` in `head` (red, green, blue)."""
        key = (int(position) % len(self.heads), tuple(head))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        size = self.size
        pixels = bytearray(self.ground)
        (left, top, _, _), rows = self.heads[key[0]]
        for y, row in enumerate(rows):
            for x, sample in enumerate(row):
                red, green, blue, alpha = brand.icon_pixel(sample, key[1])
                index = ((top + y) * size + left + x) * 4
                pixels[index:index + 4] = bytes((blue, green, red, alpha))
        frame = bytes(pixels)
        if len(self._cache) >= ICON_MOTION["cache"]:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = frame
        return frame


def build_icon_frames(size, clock=time.perf_counter):
    """IconFrames for `size`, or None when it cannot be built inside ICON_MOTION's budget."""
    started = clock()
    frames = IconFrames(size)
    if (clock() - started) * 1000.0 > ICON_MOTION["build_budget_ms"]:
        return None
    return frames
