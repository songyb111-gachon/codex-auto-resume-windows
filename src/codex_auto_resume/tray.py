"""The watcher's notification-area icon.

Owned by the watcher process and by nothing else: it appears when a watcher starts and
disappears when it stops, so it can never show a watcher that is not there - which a
separate tray process could. It runs its own message loop on its own thread, and every
action it offers goes through the same control layer as every other interface.

It decides nothing. It shows what the last tick found - paused or not, how many
recoveries are waiting, when the next one is due - and counts that time down locally.
Reaching zero only means the watcher looks again; nothing is sent because of it.

Since v0.6.3 a single click opens the mini-dashboard beside the icon (`tray_popup.py`),
the right-click menu is what it always was, and the icon wears a small badge for the
state it is in. The popup lives on this thread too, so it is gone when the icon is.

Since v0.6.4 the popup and the menu open in the Interface language and the Theme stored at
the moment they open (`_adopt_settings`), rather than waiting for the watcher's next tick.

Since v0.6.5 the icon itself moves, in its own simpler language than the windows' status light
(see "the icon's motion" below): while it watches, the mark's head breathes and now and then
travels once round the ring; while a continuation is being sent it keeps travelling; paused, it
is grey and still; a problem is its colour, pulses once and holds. Frames are composed from a
table built off this thread, swapped with NIM_MODIFY a few times a second, and nothing moves
under Reduce motion, Windows' animation setting, High Contrast or battery saver, while the session
is locked or while the icon sits in the overflow flyout.

Since v0.6.5 this thread also hosts the notification card (`notice_window.CardStack`), as it hosts
the popup: given the notifier's inbox, the icon attaches it once its window exists, so a notice
from the watcher's notifications thread becomes the product's card beside the notification area;
with no icon, or a card that cannot be made here, every notification is today's toast.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from . import brand

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_NULL = 0x0000
WM_WTSSESSION_CHANGE = 0x02B1
WTS_CONSOLE_CONNECT, WTS_CONSOLE_DISCONNECT, WTS_REMOTE_CONNECT, WTS_REMOTE_DISCONNECT = 1, 2, 3, 4
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 7, 8
NOTIFY_FOR_THIS_SESSION = 0
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_CONTEXTMENU = 0x007B
WM_USER = 0x0400
WM_APP = 0x8000
CALLBACK = WM_APP + 1
WM_TRAY_FRAMES = WM_APP + 2         # the frame table's building thread has finished
# The icon window's timers: the one-second tick (tooltip, badge, what may move) and, only while
# the icon moves, the frame timer.
TIMER_TICK, TIMER_FRAME = 1, 2
# With NOTIFYICON_VERSION_4 the shell reports a click or Enter on the icon as a select,
# and a right click or the menu key as WM_CONTEXTMENU, instead of raw mouse messages.
NIN_SELECT = WM_USER + 0
NIN_KEYSELECT = WM_USER + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NOTIFYICON_VERSION_4 = 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x80
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512
TIP_CHARS = 128

# The menu's command ids. Deliberately not one per pending recovery: a context menu
# built from a list that the watcher is still changing would act on whichever row the id
# happened to mean when the menu was drawn, and there is no room beside a menu item to
# name the conversation an action is about - which is how the window's confirmations stop
# somebody cancelling the wrong task. The safe half of the same need is a route: Pending
# opens the window on the page where those actions live, with their identities and their
# confirmations intact. (The popup's per-task switch is the other half: it names the
# conversation beside the switch, and it is bound to that row's exact identities.)
MENU_OPEN, MENU_TOGGLE, MENU_STOP, MENU_PENDING = 1, 2, 3, 4

# How the menu looks. Windows draws a popup menu itself, and draws it light unless the process has
# asked for dark through uxtheme's preferred app mode - a call Windows exports by ordinal only, with
# no documented name, stable since Windows 10 1903 (build 18362). On an older build that ordinal is
# a different function, so nothing is asked there and the menu stays light. It is asked for
# ForceDark exactly when the popup beside it is dark, and back to Default otherwise; High Contrast
# needs no request, because Windows draws every menu in the contrast theme's colours.
APP_MODE_DEFAULT, APP_MODE_FORCE_DARK = 0, 2
UXTHEME_SET_PREFERRED_APP_MODE, UXTHEME_FLUSH_MENU_THEMES = 135, 136
DARK_MENU_BUILD = 18362
_DLLS = {}


def _dll(name):
    """This module's own handle on a system DLL.

    `ctypes.windll` is shared by the whole process, and the argument types set here
    would silently change how every other module's calls into the same DLL convert
    their arguments. A private handle keeps these declarations to this file.
    """
    if name not in _DLLS:
        _DLLS[name] = C.WinDLL(name, use_last_error=True)
    return _DLLS[name]

LRESULT = C.c_ssize_t
WNDPROC = C.WINFUNCTYPE(LRESULT, W.HWND, W.UINT, W.WPARAM, W.LPARAM)


class WNDCLASSW(C.Structure):
    _fields_ = [("style", W.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", C.c_int),
                ("cbWndExtra", C.c_int), ("hInstance", W.HINSTANCE), ("hIcon", W.HICON),
                ("hCursor", W.HANDLE), ("hbrBackground", W.HBRUSH), ("lpszMenuName", W.LPCWSTR),
                ("lpszClassName", W.LPCWSTR)]


class GUID(C.Structure):
    _fields_ = [("Data1", W.DWORD), ("Data2", W.WORD), ("Data3", W.WORD), ("Data4", C.c_ubyte * 8)]


class NOTIFYICONDATAW(C.Structure):
    _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("uFlags", W.UINT),
                ("uCallbackMessage", W.UINT), ("hIcon", W.HICON), ("szTip", W.WCHAR * TIP_CHARS),
                ("dwState", W.DWORD), ("dwStateMask", W.DWORD), ("szInfo", W.WCHAR * 256),
                ("uVersion", W.UINT), ("szInfoTitle", W.WCHAR * 64), ("dwInfoFlags", W.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", W.HICON)]


class MSG(C.Structure):
    _fields_ = [("hwnd", W.HWND), ("message", W.UINT), ("wParam", W.WPARAM), ("lParam", W.LPARAM),
                ("time", W.DWORD), ("pt", W.POINT)]


def countdown(seconds: float) -> str:
    """A short, locale-neutral duration: 45s, 12:04, 3:05:00."""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, secs)
    if minutes:
        return "%d:%02d" % (minutes, secs)
    return "%ds" % secs


def tooltip(snapshot: dict, strings: dict, now: float) -> str:
    """What hovering over the icon says. Built from the last tick; counted down locally."""
    title = strings.get("tray.title", "Codex Auto Resume")
    if not snapshot:
        return title
    if not snapshot.get("enabled", True):
        line = strings.get("tray.paused", "Paused")
    else:
        waiting, running = snapshot.get("waiting", 0), snapshot.get("running", 0)
        parts = []
        if running:
            parts.append(strings.get("tray.running", "{n} running in Codex").replace("{n}", str(running)))
        if waiting:
            parts.append(strings.get("tray.waiting", "{n} waiting").replace("{n}", str(waiting)))
            due = snapshot.get("next_at")
            if due:
                parts.append(strings.get("tray.next", "next check in {time}")
                             .replace("{time}", countdown(due - now)))
        line = " · ".join(parts) if parts else strings.get("tray.idle", "Nothing waiting")
    return (title + "\n" + line)[:TIP_CHARS - 1]


def popup_attention(popup) -> bool:
    """Whether the open popup says nothing can recover until a person acts.

    Only while it is open. A closed popup reads nothing, so what it last read is a moment ago,
    not now, and a problem that has since cleared would otherwise keep the icon on "needs
    attention" until somebody opened it again.
    """
    return bool(popup is not None and popup.visible and popup.attention())


def badge_token(snapshot, now, attention=False):
    """The palette token of the icon's badge for a snapshot, or None for no badge."""
    from . import tray_popup
    return tray_popup.BADGE.get(tray_popup.snapshot_activity(snapshot, now, attention=attention))


def menu_app_mode(look) -> int:
    """The app mode the menu is asked for, by what the popup draws with: dark only in dark."""
    return APP_MODE_FORCE_DARK if look == "dark" else APP_MODE_DEFAULT


def prefer_app_mode(mode) -> bool:
    """Ask Windows to draw this process's menus in `mode`. False where Windows cannot be asked."""
    if os.name != "nt" or sys.getwindowsversion().build < DARK_MENU_BUILD:
        return False
    uxtheme = _dll("uxtheme")
    # By ordinal each time: an export looked up this way is a fresh function object, so the types
    # declared on it reach no other caller.
    prefer = uxtheme[UXTHEME_SET_PREFERRED_APP_MODE]
    prefer.argtypes, prefer.restype = (C.c_int,), C.c_int
    flush = uxtheme[UXTHEME_FLUSH_MENU_THEMES]
    flush.argtypes, flush.restype = (), None
    prefer(mode)
    flush()                                     # menus already themed in this process take it up
    return True


# ------------------------------------------------------------------------ the icon's motion
# The icon does not copy the windows' six-state status light. It is sixteen pixels across and a
# person glances at it, so it speaks a smaller language - the distinctions it drops (waiting,
# checking, monitoring) are the ones nobody has to act on:
#
#   watching    the watcher runs with recovery on: the head breathes on brand's monitoring
#               rhythm, and about every half minute it travels once, slowly, round the ring;
#   recovering  a continuation is being sent or is running in Codex: the head keeps travelling
#               round, at brand's arc rhythm, on the quicker recovering breath;
#   idle        paused: the head is grey (brand's `idle` fill) and still;
#   attention   needs a person: amber, one pulse when it arrives, then it holds;
#   failed      a failure: the danger colour, one pulse, then it holds.
#
# The turning mark is the mark's own head going round its own ring - "the ring is the wait, the
# gap is the interruption, the head is the moment it resumes" - so the motion adds no shape and
# no colour. Breathing is the head's brightness: at this size there is no room for a halo. The
# badge in the corner, the mark's shape and the light and dark taskbar handling are unchanged.
#
# Of brand.GLOW the icon reads four rhythms and nothing else: monitoring_ms (watching's breath),
# recovering_ms (recovering's breath), arc_ms (recovering's turn) and attention_ms (the one
# pulse). The glow's reach, stops, opacities, scales and the arc's look are the windows' and are
# ignored here. Its own numbers are ICON_MOTION's, deliberately not in brand.GLOW: every GLOW key
# is the windows' status light's; the window's taskbar button reads these from Brand.Mark instead.
ICON_STATES = ("watching", "recovering", "idle", "attention", "failed")
# The icon's state as a brand status-light state: its colour and its rhythm. Every value is a
# key of brand.STATUS_FILL; anything unknown is idle grey, as brand.status_fill is.
ICON_BRAND_STATE = {"watching": "monitoring", "recovering": "recovering", "idle": "idle",
                    "attention": "attention", "failed": "failed"}
# The icon's state for each status-light word: the popup's for a snapshot (icon_state), and the window's
# header light's, for its taskbar button (Brand.Mark.IconState, build/make_brand.py). Anything else is idle.
ICON_FOR_LIGHT = {"monitoring": "watching", "waiting": "watching", "checking": "watching",
                  "recovering": "recovering", "paused": "idle", "idle": "idle",
                  "attention": "attention", "failed": "failed"}
ICON_MOTION = {
    "turn_every_ms": 30000,   # watching: one slow turn about this often...
    "turn_ms": 2400,          # ...taking this long, eased in and out; recovering turns on arc_ms
    "breathe_frame_ms": 300,  # a frame about three times a second while only breathing
    "turn_frame_ms": 200,     # five a second while the head travels
    "positions": 24,          # head positions round the ring, fifteen degrees apart
    "levels": 9,              # the breath's brightness steps, a raised cosine sampled nine times
    "dim": 0.6,               # at the breath's low the head is this far from its colour toward the badge
    "build_budget_ms": 2000,  # a frame table that takes longer than this is not used
    "cache": 256,             # composed frames kept, per table
}
# The badge's own deep blue the breath dims the head toward.
ICON_DIM_TOWARD = brand.ICON_BOTTOM
# The head's colour in the states that recolour it. The head sits on the icon's deep-blue badge,
# never on the taskbar, so it is the colour the dark palette gives the state - made to read on a
# dark ground - except idle's, whose dark value is a grey that all but vanishes into the badge:
# idle takes the light palette's grey. (Looked at, side by side, at 16 to 32 px.)
ICON_HEAD_PALETTE = {"idle": "light", "attention": "dark", "danger": "dark"}


def icon_state(snapshot, *, attention=False, failed=False) -> str:
    """The icon's state from the tick's snapshot: one of ICON_STATES, ICON_FOR_LIGHT of the popup's word.

    `attention` is what the badge already uses (the open popup says nothing can recover until a
    person acts); `failed` is a failure the watcher reports. Neither is ever inferred here.
    """
    if failed:
        return "failed"
    from . import tray_popup
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
    turned round, so a breath that starts or stops lands on the icon as it always looked."""
    top = ICON_MOTION["levels"] - 1
    return int(round(top * (1.0 - brand._breath(elapsed_ms, cycle_ms))))


def icon_turn(state, elapsed_ms) -> float:
    """How far round the ring the head has travelled, in degrees from its place, or None at rest.

    Watching: one turn in the last `turn_ms` of every `turn_every_ms`, eased in and out, so the
    first comes about half a minute after motion starts rather than every time it starts again.
    Recovering: continuously, one turn per brand arc_ms, at an even speed.
    """
    if state == "recovering":
        cycle = brand.GLOW["arc_ms"]
        return 360.0 * (elapsed_ms % cycle) / cycle
    if state == "watching":
        every, length = ICON_MOTION["turn_every_ms"], ICON_MOTION["turn_ms"]
        into = elapsed_ms % every - (every - length)
        if into < 0:
            return None
        return 360.0 * (0.5 - 0.5 * math.cos(math.pi * min(1.0, into / float(length))))
    return None


def icon_frame(state, elapsed_ms, since_entered_ms=None, *, reduced=False) -> tuple:
    """(head position, breathing level) for one frame: a pure function of the state and the clock.

    Position 0 is the head in its place, positions counting on round the ring the way the mark
    leads; the top level is the head's full colour. With motion reduced every state is its rest:
    the head in its place at full colour, so the states differ by colour only. `since_entered_ms`
    is how long the state has been shown (None: long enough that its one pulse is over).
    """
    positions, top = ICON_MOTION["positions"], ICON_MOTION["levels"] - 1
    if reduced:
        return (0, top)
    brand_state = icon_brand_state(state)
    position = 0
    turn = icon_turn(state, elapsed_ms)
    if turn is not None:
        position = int(round(turn / (360.0 / positions))) % positions
    if brand_state in brand.GLOW_BREATHES:
        return (position, _breath_level(elapsed_ms, brand.GLOW[brand_state + "_ms"]))
    if brand_state in brand.GLOW_PULSES and since_entered_ms is not None \
            and 0 <= since_entered_ms < brand.GLOW["attention_ms"]:
        return (0, _breath_level(since_entered_ms, brand.GLOW["attention_ms"]))
    return (0, top)


def icon_frame_ms(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """How soon the next frame is due, in ms, or None when nothing moves (no timer at all)."""
    if reduced:
        return None
    if state == "recovering":
        return ICON_MOTION["turn_frame_ms"]
    if state == "watching":
        return ICON_MOTION["turn_frame_ms"] if icon_turn(state, elapsed_ms) is not None \
            else ICON_MOTION["breathe_frame_ms"]
    if icon_brand_state(state) in brand.GLOW_PULSES and since_entered_ms is not None \
            and 0 <= since_entered_ms < brand.GLOW["attention_ms"]:
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
    own image at that size, byte for byte. A frame is that, the head's colour at a breathing level,
    and the badge composited last exactly as tray_popup.badge_icon does it. Top-down BGRA with
    straight alpha, as icon bitmaps are. `ground` and `heads` go into the window's Brand.Mark as they are.
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
            angle = brand.ICON_SHAPE["arc_end"] + 360.0 * position / positions
            box = brand.icon_head_box(size, angle)
            self.heads.append((box, brand.icon_samples(size, head_angle=angle, box=box)))
        self._cache = {}

    def compose(self, position, head, badge=None) -> bytes:
        """One frame: the head at `position` in `head` (red, green, blue), and the badge's dot in
        `badge` (red, green, blue) or none."""
        key = (int(position) % len(self.heads), tuple(head), tuple(badge) if badge else None)
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
        if badge:
            from . import tray_popup
            tray_popup.composite_badge(pixels, size, size, key[2])
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


class SYSTEM_POWER_STATUS(C.Structure):
    _fields_ = [("ACLineStatus", C.c_ubyte), ("BatteryFlag", C.c_ubyte), ("BatteryLifePercent", C.c_ubyte),
                ("SystemStatusFlag", C.c_ubyte), ("BatteryLifeTime", W.DWORD), ("BatteryFullLifeTime", W.DWORD)]


def battery_saver() -> bool:
    """True while Windows' battery saver (energy saver) is on; False where Windows cannot say."""
    if os.name != "nt":
        return False
    try:
        status = SYSTEM_POWER_STATUS()
        get = _dll("kernel32").GetSystemPowerStatus
        get.argtypes, get.restype = (C.POINTER(SYSTEM_POWER_STATUS),), W.BOOL
        if not get(C.byref(status)):
            return False
        return bool(status.SystemStatusFlag & 1)
    except Exception:
        return False


class Tray:
    """One icon, one hidden window, one thread - and, once clicked, one popup on it."""

    def __init__(self, *, icon_path=None, strings=None, on_open=None, on_toggle=None, on_stop=None,
                 on_pending=None, log=None, control=None, pending_source=None, on_dashboard=None,
                 inbox=None, on_notice_action=None, on_notice_complete=None):
        self.icon_path = Path(icon_path) if icon_path else None
        self.strings = strings or {}
        self.on_open, self.on_toggle, self.on_stop = on_open, on_toggle, on_stop
        self.on_pending = on_pending
        self.log = log or (lambda *args: None)
        # The popup's only way to act: the shared control layer, plus the read-only source
        # `list_pending` uses to attach conversation names. Without a control there is no
        # popup, and a double click opens the Dashboard as it did before v0.6.3.
        self.control = control
        self.pending_source = pending_source
        self.on_dashboard = on_dashboard
        self._snapshot = {}
        self._lock = threading.Lock()
        self._thread = None
        self._hwnd = None
        self._ready = threading.Event()
        self._proc = None           # keeps the callback alive for the window's life
        self._icon = None
        self._icon_owned = False
        self._badge = None          # the badged copy currently shown, if any
        self._badge_token = None
        self._shown_icon = None
        self._last_tip = None
        self._taskbar_created = None
        self._class_name = None
        self._version4 = False
        self._popup = None
        self._popup_failed = False
        self._settings_stamp = None   # the settings file as last read: (mtime, size), or None
        self._settings_values = None
        self._menu_mode = APP_MODE_DEFAULT   # what this process's menus were last asked to be
        self._menu_theming = True            # False once Windows could not be asked
        # v0.6.5: the icon's motion. Until its frame table is built (off this thread) the icon is
        # drawn exactly as before - the .ico, and a badged copy of it - and if the table cannot be
        # built it stays that way. Once it is, every icon shown is one composed frame, made into
        # an HICON as it is shown and destroyed once the shell holds the next: two at most.
        self._frames = None           # IconFrames once built; False when it could not be
        self._frames_result = None    # what the building thread left: (frames, reason)
        self._frame_icon = None       # the composed frame on show, if any
        self._frame_key = None
        self._icon_state = None
        self._state_since = time.monotonic()
        self._epoch = time.monotonic()      # the motion's clock: breaths and turns count from here
        self._motion_allowed = False
        self._motion_ms = None              # the frame timer's interval while it runs
        self._session_locked = False
        self._session_away = False
        self._session_watch = False
        self._motion_read_failed = False    # said once until the settings file can be read again
        # v0.6.5: the notification card. With an inbox, this thread hosts the cards once its window
        # exists (notice_window.CardStack attaches itself to the inbox); a card's button calls
        # `on_notice_action(uri)` and each notice the stack took is ended by
        # `on_notice_complete(notice, shown)`, both on worker threads. No inbox, or a stack that
        # could not be made: no card, and every notification stays today's toast.
        self.inbox = inbox
        self.on_notice_action = on_notice_action
        self.on_notice_complete = on_notice_complete
        self._cards = None

    # ----------------------------------------------------------------- public
    def start(self) -> bool:
        if os.name != "nt":
            return False
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        return self._ready.wait(5) and self._hwnd is not None

    def update(self, snapshot: dict) -> None:
        with self._lock:
            self._snapshot = dict(snapshot)

    def set_strings(self, strings: dict) -> None:
        """Adopt a new vocabulary, after the Interface language changed."""
        with self._lock:
            self.strings = dict(strings or {})
            # Forget the last tooltip so the next tick rewrites it even if the numbers in
            # it have not moved.
            self._last_tip = None
        popup = self._popup
        if popup is not None:
            popup.set_strings(strings)

    def stop(self) -> None:
        if self._hwnd:
            _dll("user32").PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
        if self._thread is not None:
            self._thread.join(5)

    # ---------------------------------------------------------------- window
    def _run(self):
        try:
            self._create()
        except Exception as exc:          # a missing tray must never stop the watcher
            self.log("tray unavailable (%s)" % type(exc).__name__)
            self._ready.set()
            return
        self._ready.set()
        user32 = _dll("user32")
        message = MSG()
        while user32.GetMessageW(C.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(C.byref(message))
            user32.DispatchMessageW(C.byref(message))
        # The class name is this icon's own; free it so the next icon can register.
        user32.UnregisterClassW.argtypes = [W.LPCWSTR, W.HINSTANCE]
        user32.UnregisterClassW(self._class_name, _dll("kernel32").GetModuleHandleW(None))

    def _create(self):
        user32, kernel32 = _dll("user32"), _dll("kernel32")
        user32.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user32.DefWindowProcW.restype = LRESULT
        user32.CreateWindowExW.restype = W.HWND
        user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int,
                                           C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID]
        user32.LoadImageW.restype = W.HANDLE
        user32.LoadImageW.argtypes = [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT]
        user32.LoadIconW.restype = W.HICON
        user32.LoadIconW.argtypes = [W.HINSTANCE, W.LPVOID]
        user32.DestroyIcon.argtypes = [W.HICON]
        user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        user32.TrackPopupMenu.argtypes = [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, W.LPVOID]
        user32.AppendMenuW.argtypes = [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR]
        user32.CreatePopupMenu.restype = W.HMENU
        user32.DestroyMenu.argtypes = [W.HMENU]
        user32.SetTimer.argtypes = [W.HWND, C.c_size_t, W.UINT, W.LPVOID]
        user32.KillTimer.argtypes = [W.HWND, C.c_size_t]
        user32.RegisterWindowMessageW.restype = W.UINT
        _dll("shell32").Shell_NotifyIconW.argtypes = [W.DWORD, C.POINTER(NOTIFYICONDATAW)]
        kernel32.GetModuleHandleW.restype = W.HMODULE
        instance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        # Unique per icon, not per process: an icon started after another one in the
        # same process must not collide with a class the first one registered.
        self._class_name = "CodexAutoResumeTray-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self._class_name
        if not user32.RegisterClassW(C.byref(klass)):
            raise OSError("RegisterClassW")
        # A hidden top-level window, not a message-only one: only a real top-level
        # window hears "TaskbarCreated", which is how the icon comes back after Explorer
        # restarts.
        self._hwnd = user32.CreateWindowExW(0, klass.lpszClassName, "Codex Auto Resume", 0,
                                            0, 0, 0, 0, None, None, instance, None)
        if not self._hwnd:
            raise OSError("CreateWindowExW")
        self._taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
        self._icon = self._load_icon()
        self._shown_icon = self._icon
        self._notify(NIM_ADD)
        self._set_version()
        self._host_cards()
        user32.SetTimer(self._hwnd, TIMER_TICK, 1000, None)
        self._watch_session()
        if self._icon_owned:
            # Only for our own mark: a missing .ico keeps Windows' generic icon, unmoved.
            self._build_frames_later(user32.GetSystemMetrics(SM_CXSMICON))

    # ------------------------------------------------------------- the notification card
    def _host_cards(self):
        """Host the notification card on this thread, if this icon was given an inbox.

        A stack that cannot be made costs the card only: the inbox stays detached, and the
        notifier raises today's toast for everything, as it does with no icon at all.
        """
        if self.inbox is None:
            return
        try:
            from . import notice_window, tray_popup
            self._cards = notice_window.CardStack(on_action=self.on_notice_action,
                                                  on_complete=self.on_notice_complete, log=self.log,
                                                  anchor=lambda: tray_popup.icon_rect(self._hwnd, 1),
                                                  inbox=self.inbox, appearance=self._card_look).create()
        except Exception as exc:
            self._cards = None
            self.log("notification card unavailable (%s)" % type(exc).__name__)

    def _card_look(self):
        """How the next card is drawn: the Theme and Reduce motion stored now, as the popup and the
        menu take them up when they open (`_adopt_settings`), then Windows' own answers."""
        from . import notice_window
        self._adopt_settings()
        return notice_window.look()

    def _drop_cards(self):
        """Take the cards down with the icon. The stack lets go of the inbox first, so a notice
        from now on is today's toast, and ends every notice it held (notice_window.CardStack)."""
        cards, self._cards = self._cards, None
        if cards is not None:
            try:
                cards.destroy()
            except Exception as exc:
                self.log("notification card cleanup failed (%s)" % type(exc).__name__)

    def _load_icon(self):
        user32 = _dll("user32")
        width, height = user32.GetSystemMetrics(SM_CXSMICON), user32.GetSystemMetrics(SM_CYSMICON)
        if self.icon_path and self.icon_path.is_file():
            handle = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, width, height, LR_LOADFROMFILE)
            if handle:
                self._icon_owned = True
                return handle
        self._icon_owned = False            # a shared system icon is never destroyed
        return user32.LoadIconW(None, C.c_void_p(IDI_APPLICATION))

    def _data(self, flags):
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = CALLBACK
        data.hIcon = self._shown_icon or self._icon
        with self._lock:
            snapshot = dict(self._snapshot)
        data.szTip = tooltip(snapshot, self.strings, time.time())
        return data

    def _notify(self, action):
        # NIF_SHOWTIP: under version 4 the shell hides the standard tooltip unless asked.
        data = self._data(NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP)
        self._last_tip = data.szTip
        return _dll("shell32").Shell_NotifyIconW(action, C.byref(data))

    def _set_version(self):
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uVersion = NOTIFYICON_VERSION_4
        self._version4 = bool(_dll("shell32").Shell_NotifyIconW(NIM_SETVERSION, C.byref(data)))

    def _refresh(self):
        with self._lock:
            snapshot = dict(self._snapshot)
        text = tooltip(snapshot, self.strings, time.time())
        if self._frames:
            self._observe(snapshot)
            changed, replaced = self._frame_for(time.monotonic())
        else:
            changed, replaced = self._badge_for(snapshot)
            replaced = [replaced]
        if text != self._last_tip or changed:
            self._notify(NIM_MODIFY)
        for handle in replaced:
            if handle:
                _dll("user32").DestroyIcon(handle)      # only after the shell holds the new one
        self._sync_motion()

    def _badge_for(self, snapshot):
        """Swap the badge when the state it shows changed. Returns (changed, icon to destroy)."""
        if not self._icon:
            return False, None
        try:
            from . import tray_popup
            token = badge_token(snapshot, time.time(), popup_attention(self._popup))
            if token == self._badge_token:
                return False, None
            badge = tray_popup.badge_icon(self._icon, token) if token else None
            replaced, self._badge = self._badge, badge
            self._badge_token = token
            self._shown_icon = badge or self._icon
            return True, replaced
        except Exception as exc:
            self.log("tray badge failed (%s)" % type(exc).__name__)
            return False, None

    # --------------------------------------------------------------- the icon's motion
    def _build_frames_later(self, size):
        """Build the frame table on a thread of its own; the icon's thread hears when it is done."""
        def build():
            try:
                frames = build_icon_frames(size)
                result = (frames, None if frames else "over its time budget")
            except Exception as exc:
                result = (None, type(exc).__name__)
            with self._lock:
                self._frames_result = result
            hwnd = self._hwnd
            if hwnd:
                _dll("user32").PostMessageW(hwnd, WM_TRAY_FRAMES, 0, 0)

        threading.Thread(target=build, name="tray-frames", daemon=True).start()

    def _frames_built(self):
        with self._lock:
            result, self._frames_result = self._frames_result, None
        if result is None or not self._icon:
            return
        frames, reason = result
        if frames is None:
            self._frames = False
            self.log("tray motion unavailable (%s)" % reason)   # once: the table is never built again
            return
        self._frames = frames
        self._refresh()

    def _observe(self, snapshot):
        """What the one-second tick decides for the motion: the badge, the state, whether it may move.

        Windows is asked what may move only when the state has something to move, and whether
        the icon is in the overflow flyout only when nothing else already holds it still. The
        product's own Reduce motion is taken from the stored settings on the same tick
        (`_adopt_reduce_motion`), so a Save in the window holds the icon within a second.
        """
        attention = popup_attention(self._popup)
        self._badge_token = badge_token(snapshot, time.time(), attention)
        state = icon_state(snapshot, attention=attention, failed=snapshot.get("failed") is True)
        now = time.monotonic()
        if state != self._icon_state:
            self._icon_state, self._state_since = state, now
        since = (now - self._state_since) * 1000.0
        allowed = False
        if icon_frame_ms(state, (now - self._epoch) * 1000.0, since) is not None:
            from . import tray_popup
            self._adopt_reduce_motion(tray_popup)
            allowed = icon_motion_allowed(reduced=tray_popup.reduced_motion(), contrast=tray_popup.high_contrast(),
                                          battery_saver=battery_saver(),
                                          locked=self._session_locked or self._session_away,
                                          frames=bool(self._frames))
            if allowed:
                allowed = tray_popup.icon_rect(self._hwnd, 1) is not None
        self._motion_allowed = allowed

    def _frame_for(self, now):
        """Show the frame this moment wants. Returns (changed, [icons to destroy once shown])."""
        frames = self._frames
        if not frames:
            return False, []
        state = self._icon_state or "watching"
        elapsed = (now - self._epoch) * 1000.0
        since = (now - self._state_since) * 1000.0
        position, level = icon_frame(state, elapsed, since, reduced=not self._motion_allowed)
        head = icon_level_colour(icon_head_colour(state), level)
        token = self._badge_token
        key = (position, head, token)
        if key == self._frame_key and self._frame_icon:
            return False, []
        try:
            from . import tray_popup
            pixels = frames.compose(position, head, brand.rgb(brand.LIGHT[token]) if token else None)
            tray_popup._declare()                  # the GDI calls' types, as badge_icon declares them
            made = tray_popup._icon_from_pixels(pixels, frames.size, frames.size)
            if not made:
                raise OSError("CreateIconIndirect")
        except Exception as exc:
            # Back to the icon as it was before v0.6.5, for the rest of this icon's life.
            self.log("tray motion failed (%s)" % type(exc).__name__)
            self._frames, self._frame_key = False, None
            replaced, self._frame_icon = self._frame_icon, None
            self._badge_token = None
            self._shown_icon = self._badge or self._icon
            return True, [replaced]
        # The badged copy of the old path is not shown once frames are; it goes with the swap.
        replaced = [self._frame_icon, self._badge]
        self._frame_icon, self._badge, self._frame_key = made, None, key
        self._shown_icon = made
        return True, replaced

    def _animate(self):
        """One frame-timer tick: only the icon, only when its frame changed."""
        changed, replaced = self._frame_for(time.monotonic())
        if changed:
            self._notify_icon()
        for handle in replaced:
            if handle:
                _dll("user32").DestroyIcon(handle)
        self._sync_motion()

    def _notify_icon(self):
        """NIM_MODIFY with the icon alone: a frame changes nothing else the shell holds."""
        data = NOTIFYICONDATAW()
        data.cbSize = C.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = NIF_ICON
        data.hIcon = self._shown_icon or self._icon
        return _dll("shell32").Shell_NotifyIconW(NIM_MODIFY, C.byref(data))

    def _sync_motion(self):
        """Run the frame timer at the interval this moment wants, and not at all when nothing moves."""
        interval = None
        if self._frames and self._motion_allowed and self._icon_state is not None:
            now = time.monotonic()
            interval = icon_frame_ms(self._icon_state, (now - self._epoch) * 1000.0,
                                     (now - self._state_since) * 1000.0)
        if interval == self._motion_ms:
            return
        user32 = _dll("user32")
        if interval is None:
            user32.KillTimer(self._hwnd, TIMER_FRAME)
        else:
            user32.SetTimer(self._hwnd, TIMER_FRAME, interval, None)   # the same id replaces it
        self._motion_ms = interval

    def _watch_session(self):
        """Hear when the session is locked or disconnected: nobody sees the icon move then."""
        try:
            wts = _dll("wtsapi32")
            wts.WTSRegisterSessionNotification.argtypes = [W.HWND, W.DWORD]
            wts.WTSRegisterSessionNotification.restype = W.BOOL
            self._session_watch = bool(wts.WTSRegisterSessionNotification(self._hwnd, NOTIFY_FOR_THIS_SESSION))
        except Exception:
            self._session_watch = False           # then the lock is simply not known; nothing else changes

    def _session_changed(self, event):
        if event == WTS_SESSION_LOCK:
            self._session_locked = True
        elif event == WTS_SESSION_UNLOCK:
            self._session_locked = False
        elif event in (WTS_CONSOLE_DISCONNECT, WTS_REMOTE_DISCONNECT):
            self._session_away = True
        elif event in (WTS_CONSOLE_CONNECT, WTS_REMOTE_CONNECT):
            self._session_away = False
        else:
            return
        self._refresh()

    def _menu(self):
        user32 = _dll("user32")
        self._adopt_settings()                  # the menu speaks the language stored now
        self._theme_menu()                      # and is drawn in the theme the popup is
        with self._lock:
            snapshot = dict(self._snapshot)
        menu = user32.CreatePopupMenu()
        try:
            status = tooltip(snapshot, self.strings, time.time()).split("\n", 1)[-1]
            user32.AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, status)
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_OPEN,
                               self.strings.get("menu.open", "Open Codex Auto Resume"))
            # Only while there is something to look at. An item that opens a page saying
            # nothing is waiting is an item that teaches people not to use the menu.
            waiting = int(snapshot.get("waiting", 0) or 0) + int(snapshot.get("running", 0) or 0)
            if waiting and self.on_pending:
                user32.AppendMenuW(menu, MF_STRING, MENU_PENDING,
                                   self.strings.get("menu.pending", "Show what is waiting")
                                   .replace("{n}", str(waiting)))
            paused = not snapshot.get("enabled", True)
            user32.AppendMenuW(menu, MF_STRING, MENU_TOGGLE,
                               self.strings.get("menu.resume", "Resume recovery") if paused
                               else self.strings.get("menu.pause", "Pause recovery"))
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_STOP, self.strings.get("menu.stop", "Stop the watcher"))
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            # Without this the menu does not close when the user clicks elsewhere.
            user32.SetForegroundWindow(self._hwnd)
            chosen = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                           point.x, point.y, 0, self._hwnd, None)
            user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)
        self._act(chosen, paused)

    def _act(self, chosen, paused):
        action = {MENU_OPEN: self.on_open, MENU_STOP: self.on_stop,
                  MENU_PENDING: self.on_pending}.get(chosen)
        try:
            if chosen == MENU_TOGGLE and self.on_toggle:
                self.on_toggle(paused)          # paused -> resume; running -> pause
            elif action:
                action()
        except Exception as exc:
            self.log("tray action failed (%s)" % type(exc).__name__)

    # ------------------------------------------------------ what was stored since
    def _stored_settings(self):
        """The stored settings through the control layer, read again only when the file changed.

        None when this icon has no control layer that can say. A look at the file's stamp is all
        an unchanged file costs, so it is taken each time somebody opens the popup or the menu.
        """
        read = getattr(self.control, "get_settings", None)
        if read is None:
            return None
        where = getattr(self.control, "settings_path", None)
        stamp = None
        if where is not None:
            try:
                status = os.stat(where())
                stamp = (status.st_mtime_ns, status.st_size)
            except OSError:
                stamp = None
        if stamp is None or stamp != self._settings_stamp or self._settings_values is None:
            self._settings_values = dict(read())
            self._settings_stamp = stamp
        return self._settings_values

    def _adopt_settings(self):
        """Speak the stored Interface language and draw in the stored Theme from this opening on.

        The watcher adopts a changed settings file at its next tick, which can be an hour away,
        and somebody who has just chosen a language or a theme and clicks the icon expects the
        popup and the menu to have it already. So the icon looks for itself before it opens
        either - the same settings, resolved the way the watcher resolves them - and the watcher
        restarts for none of it. The icon and its badge do not change with the theme.
        """
        try:
            values = self._stored_settings()
            if values is None:
                return
            from . import tray_popup
            tray_popup.adopt_settings(values)
            strings = tray_popup.vocabulary(values.get("interface_language"))
            with self._lock:
                changed = strings != self.strings
            if changed:
                self.set_strings(strings)
        except Exception as exc:                # an unreadable file costs the new words, nothing else
            self.log("tray settings read failed (%s)" % type(exc).__name__)

    def _adopt_reduce_motion(self, tray_popup):
        """Take up the stored Reduce motion on the tick that decides whether the icon may move.

        The watcher adopts a changed settings file at its own next tick, poll_seconds away - 30 s
        by default and up to an hour - and a Save in the window wakes nothing, so an icon that
        waited for it kept moving all that time after somebody asked for stillness. It looks for
        itself instead: a look at the file's stamp a second while there is something to move, and
        a read only when the file changed (`_stored_settings`). What it read is set again on every
        such tick, so a watcher tick that read the file just before the save is overruled a second
        later. An unreadable file keeps the setting there is, and is said once until it reads again.
        """
        try:
            values = self._stored_settings()
        except Exception as exc:
            if not self._motion_read_failed:
                self._motion_read_failed = True
                self.log("tray settings read failed (%s)" % type(exc).__name__)
            return
        self._motion_read_failed = False
        if values is not None:
            tray_popup.set_reduce_motion(values.get("reduce_motion"))

    def _theme_menu(self):
        """Ask for a dark menu when the popup beside it is dark, and for Windows' own look otherwise.

        Resolved when the menu opens, the way the popup resolves it: the stored Theme, Windows' app
        mode for Use system setting, and High Contrast over both. Asked only when that changes. If
        Windows cannot be asked, or the request fails, the menu keeps the look it always had and
        nothing is asked again; the failure is logged once.
        """
        if not self._menu_theming:
            return
        try:
            from . import tray_popup
            look = tray_popup.appearance(tray_popup.theme_setting(), tray_popup.apps_use_light_theme(),
                                         tray_popup.high_contrast())
            mode = menu_app_mode(look)
            if mode == self._menu_mode:
                return
            if prefer_app_mode(mode):
                self._menu_mode = mode
            else:
                self._menu_theming = False
        except Exception as exc:
            self._menu_theming = False
            self.log("tray menu theme failed (%s)" % type(exc).__name__)

    # ----------------------------------------------------------------- popup
    def _popup_for_click(self):
        if self.control is None or self._popup_failed:
            return None
        if self._popup is None:
            from . import tray_popup
            with self._lock:
                strings = dict(self.strings)
            self._popup = tray_popup.Popup(control=self.control, source=self.pending_source,
                                           strings=strings, on_dashboard=self.on_dashboard,
                                           log=self.log,
                                           anchor=lambda: tray_popup.icon_rect(self._hwnd, 1))
        return self._popup

    def _popup_broke(self, exc):
        self.log("tray popup unavailable (%s)" % type(exc).__name__)
        self._popup_failed = True
        popup, self._popup = self._popup, None
        if popup is not None:
            try:
                popup.destroy()
            except Exception:
                pass

    def _select(self, keyboard=False):
        self._adopt_settings()
        popup = self._popup_for_click()
        if popup is None:
            return
        try:
            popup.on_select(keyboard=keyboard)
        except Exception as exc:
            self._popup_broke(exc)

    def _double_click(self):
        self._adopt_settings()
        popup = self._popup_for_click()
        if popup is None:
            if self.on_open:
                self._act(MENU_OPEN, False)
            return
        try:
            popup.on_double_click()
        except Exception as exc:
            self._popup_broke(exc)

    def _hide_popup(self):
        if self._popup is not None:
            try:
                self._popup.hide()
            except Exception as exc:
                self._popup_broke(exc)

    def _wndproc(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        try:
            if message == CALLBACK:
                event = lparam & 0xFFFF
                if self._version4:
                    if event in (NIN_SELECT, NIN_KEYSELECT):
                        self._select(keyboard=event == NIN_KEYSELECT)
                    elif event == WM_LBUTTONDBLCLK:
                        self._double_click()
                    elif event == WM_CONTEXTMENU:
                        self._hide_popup()
                        self._menu()
                else:
                    if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        self._hide_popup()
                        self._menu()
                    elif event == WM_LBUTTONUP:
                        self._select()
                    elif event == WM_LBUTTONDBLCLK:
                        self._double_click()
                return 0
            if message == WM_TIMER:
                if wparam == TIMER_FRAME:
                    self._animate()
                else:
                    self._refresh()
                return 0
            if message == WM_TRAY_FRAMES:
                self._frames_built()
                return 0
            if message == WM_WTSSESSION_CHANGE:
                self._session_changed(wparam)
                return 0
            if self._taskbar_created and message == self._taskbar_created:
                self._hide_popup()
                self._notify(NIM_ADD)
                self._set_version()
                return 0
            if message == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if message == WM_DESTROY:
                user32.KillTimer(hwnd, TIMER_TICK)
                user32.KillTimer(hwnd, TIMER_FRAME)
                self._motion_ms = None
                if self._session_watch:
                    try:
                        wts = _dll("wtsapi32")
                        wts.WTSUnRegisterSessionNotification.argtypes = [W.HWND]
                        wts.WTSUnRegisterSessionNotification(hwnd)
                    except Exception:
                        pass
                    self._session_watch = False
                self._drop_cards()
                popup, self._popup = self._popup, None
                if popup is not None:
                    try:
                        popup.destroy()
                    except Exception as exc:
                        self.log("tray popup cleanup failed (%s)" % type(exc).__name__)
                data = NOTIFYICONDATAW()
                data.cbSize = C.sizeof(NOTIFYICONDATAW)
                data.hWnd = hwnd
                data.uID = 1
                _dll("shell32").Shell_NotifyIconW(NIM_DELETE, C.byref(data))
                if self._badge:
                    user32.DestroyIcon(self._badge)
                    self._badge = None
                if self._frame_icon:
                    user32.DestroyIcon(self._frame_icon)
                    self._frame_icon = self._frame_key = None
                if self._icon and self._icon_owned:
                    user32.DestroyIcon(self._icon)
                self._icon = self._shown_icon = None
                user32.PostQuitMessage(0)
                return 0
        except Exception as exc:
            self.log("tray message failed (%s)" % type(exc).__name__)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


def snapshot_from(store, now: float) -> dict:
    """What the icon shows, from our own store only: no Codex read, no content."""
    from . import machine
    waiting, running, due = 0, 0, []
    for row in store.pending():
        if row["state"] in machine.WAITING:
            waiting += 1
            at = machine.eligible_at(row)
            if at:
                due.append(at)
        else:
            running += 1
    return {"enabled": store.settings()["enabled"], "waiting": waiting, "running": running,
            "next_at": min(due) if due else None}


# The pages the window will open on. A closed list, because the value is spliced into a
# command line: nothing else may ever reach it, whatever a caller passes.
PAGES = ("overview", "pending", "history", "statistics", "diagnostics", "settings")


def open_dashboard(home: Path, page: str = None) -> bool:
    """Start the settings window, if it is installed beside the watcher."""
    # The page is checked before anything else, including whether there is a window to
    # open: a value that is not one of ours is a mistake in this file, and a mistake that
    # only shows up on machines where the window happens to be installed is a worse one.
    if page is not None and page not in PAGES:
        raise ValueError("not a page of the window")
    exe = Path(home) / "CodexAutoResumeSettings.exe"
    if not exe.is_file():
        return False
    arguments = [str(exe)]
    if page is not None:
        arguments.append("--page=" + page)
    subprocess.Popen(arguments, cwd=str(home), close_fds=True)
    return True
