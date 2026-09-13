"""The notification-area mini-dashboard: one click on the icon, a small window beside it.

It answers the three questions somebody has when they glance at the icon - is it working,
is anything waiting, and when does it look again - and it offers the two decisions that
are safe to make from there: pause everything, or switch automatic recovery off or on for
one exact task. Everything else is one button away, in the Dashboard.

Four rules shape this file, and the tests hold it to each of them.

* **It is a front end, not a recoverer.** Like the Dashboard and the Codex panel it asks
  `control.Control` for exactly four things - the pending list, the status, the global
  switch and the per-task switch (`CONTROL_CALLS`) - and it imports nothing that can put a
  continuation into Codex. The watcher remains the only thing that does that.
* **A switch belongs to the row it was drawn in.** A click carries the interruption id and
  the conversation id captured when that row was painted, never a title, a position or
  "the newest one". The control layer re-reads the record and refuses a click that no
  longer matches it; a refused click changes nothing, says so for a few seconds, and the
  list is read again.
* **It never stalls the icon.** Every control call runs on a short worker thread and its
  answer comes back as a posted message, so a store that is busy for a second leaves the
  window responsive. Timers run only while the window is on screen.
* **It never stops the watcher.** It lives on the icon's own thread inside the watcher,
  and every message is handled inside a `try` that logs the exception's class name and
  carries on, exactly as `tray.py` does.

The file is in two halves. The top half is pure - wording, ordering, placement, hit
testing, focus order, motion, the icon badge's pixels - and is tested on any platform.
The bottom half is the Win32 window and its GDI+ renderer, and only runs on Windows.
"""
from __future__ import annotations

import ctypes as C
import itertools
import math
import os
import threading
import time

from . import brand, l10n, machine, reasons
from .tray import countdown

# ---------------------------------------------------------------------------- the pure half
WIDTH = 360                  # device-independent pixels at 96 DPI
MAX_TASKS = 3
REFRESH_TICKS = 3            # re-read the list every third one-second tick while visible
NOTICE_SECONDS = 4.0
FRAME_MS = 33                # about thirty frames a second, and only while something moves
FIRST_READ_WAIT_MS = 300     # the first opening waits this long for real numbers at most
CLICK_AWAY_SECONDS = 0.5     # a click on the icon that closed the window does not reopen it
DOUBLE_CLICK_SECONDS = 0.6
KEY_REPEAT_SECONDS = 0.3     # Enter on the icon arrives twice

# The whole of what this window may ask of the control layer.
CONTROL_CALLS = ("list_pending", "get_status", "set_enabled", "set_interruption_recovery")
# The refusals that mean "the row you clicked is no longer the record it was drawn from".
STALE_CODES = frozenset({"no_such_interruption", "thread_mismatch", "already_finished"})

STATES = ("monitoring", "waiting", "checking", "recovering", "paused", "attention")
# Circumstances under which nothing will recover until a person does something.
ATTENTION_OVERLAYS = frozenset({"compatibility_blocked", "engine_unavailable", "watcher_not_ticking"})

# What each state is drawn with. Fill tokens for the dot, text tokens for its word: `active`
# is fill-only and never carries text, which is why the two tables are separate.
DOT_FILL = {"monitoring": "active", "waiting": "waiting", "checking": "accent",
            "recovering": "active", "paused": "paused", "attention": "attention"}
STATE_INK = {"monitoring": "accent", "waiting": "waiting", "checking": "accent",
             "recovering": "accent", "paused": "paused", "attention": "warning"}
# The icon's badge. Plain monitoring has none: an icon that always wears a dot says nothing.
BADGE = {"monitoring": None, "waiting": "waiting", "checking": "waiting", "recovering": "active",
         "paused": "paused", "attention": "attention"}
# A reason chip's text colour; its ground is the same colour at CHIP_ALPHA.
CHIP_ALPHA = 0.12


def say(strings, key, **fields) -> str:
    """One string from the catalog the icon was given, English underneath it.

    The icon can be built with an empty vocabulary (some watcher paths do), and a window
    that shows a key name, or raises, in front of a person is worse than one in English.
    """
    value = (strings or {}).get(key)
    if not isinstance(value, str) or not value:
        value = l10n.catalog(l10n.DEFAULT).get(key, key)
    for name, supplied in fields.items():
        value = value.replace("{%s}" % name, str(supplied))
    return value


def one_line(text, limit=120) -> str:
    """A conversation name as a single, bounded line."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 1] + "…"


_LOCALE_PROBES = ("activity.monitoring", "popup.nothing", "action.pause", "popup.open_dashboard")


def locale_of(strings) -> str:
    """Which shipped catalog a vocabulary is, so the window can pick a typeface for it."""
    if not strings:
        return l10n.DEFAULT
    best, score = l10n.DEFAULT, -1
    for locale in l10n.LOCALES:
        table = l10n.catalog(locale)
        found = sum(1 for key in _LOCALE_PROBES
                    if strings.get(key) is not None and strings.get(key) == table.get(key))
        if found > score:
            best, score = locale, found
    return best


_SCRIPT_FACES = {"ko": "Malgun Gothic", "ja": "Yu Gothic UI", "zh-CN": "Microsoft YaHei UI",
                 "zh-TW": "Microsoft JhengHei UI"}


def font_faces(locale) -> tuple:
    """The typefaces to try for a locale, best first. The last one is on every Windows."""
    return (_SCRIPT_FACES.get(locale, "Segoe UI Variable Text"), "Segoe UI")


def font_candidates(locale, weight) -> tuple:
    """(face, weight) pairs to try for one font role, best first.

    GDI has no semibold inside a family it lists as regular: Segoe UI Variable Text asked
    for weight 600 answers with its bold. The semibold instances are families of their
    own and are asked for at their regular weight. Malgun Gothic and the Chinese UI faces
    have no semibold at all, so their emphasis is their bold.
    """
    faces = font_faces(locale)
    if weight < 600:
        return tuple((face, 400) for face in faces)
    if locale == "ja":
        return (("Yu Gothic UI Semibold", 400), ("Yu Gothic UI", 600), ("Segoe UI Semibold", 400),
                ("Segoe UI", 600))
    if locale in _SCRIPT_FACES:
        return ((faces[0], 700), ("Segoe UI Semibold", 400), ("Segoe UI", 600))
    return (("Segoe UI Variable Text Semibold", 400), ("Segoe UI Semibold", 400), ("Segoe UI", 600))


def is_waiting(row) -> bool:
    return row.get("state") in machine.WAITING


def urgency(row):
    """Most urgent first: work already in Codex, then the soonest check, then the oldest."""
    at = row.get("eligible_at")
    return (1 if is_waiting(row) else 0, at if at is not None else float("inf"),
            row.get("detected_at") or 0, str(row.get("interruption_id") or ""))


def activity(status, rows, now) -> str:
    """The one word the header says. A pure function of what the control layer returned."""
    status = status or {}
    rows = rows or []
    watcher = status.get("watcher") or {}
    if (status.get("watcher_running") is False or watcher.get("ticking") is False
            or watcher.get("engine_state") == "incompatible"
            or any(ATTENTION_OVERLAYS & set(row.get("overlays") or ()) for row in rows)):
        return "attention"
    if status and not status.get("enabled", True):
        return "paused"
    if any(not is_waiting(row) for row in rows):
        return "recovering"
    waiting = [row for row in rows if is_waiting(row)]
    if any(row.get("eligible_at") is not None and row["eligible_at"] <= now for row in waiting):
        return "checking"
    return "waiting" if waiting else "monitoring"


def snapshot_activity(snapshot, now, *, attention=False) -> str:
    """The same word from the icon's own tick snapshot, for the badge."""
    snapshot = snapshot or {}
    if attention:
        return "attention"
    if snapshot and not snapshot.get("enabled", True):
        return "paused"
    if snapshot.get("running"):
        return "recovering"
    if snapshot.get("waiting"):
        due = snapshot.get("next_at")
        return "checking" if due is not None and due <= now else "waiting"
    return "monitoring"


def task_item(row, strings, now) -> dict:
    """One pending recovery as the window shows it, with the identities its switch acts on."""
    category = row.get("category") or "unknown"
    usage = reasons.has_reset_time(category)
    at = row.get("eligible_at")
    seconds = None
    if not is_waiting(row):
        status = say(strings, "activity.recovering")
    elif at is None:
        status = say(strings, "activity.waiting")
    else:
        seconds = max(0.0, at - now)
        key = "popup.until_reset" if usage and row.get("reset_at") else "popup.until_retry"
        status = say(strings, key, time=countdown(seconds))
    overlays = set(row.get("overlays") or ())
    enabled = bool(row.get("thread_enabled", True))
    if overlays & ATTENTION_OVERLAYS or not reasons.is_recoverable(category):
        tone = "warning"
    elif not enabled or overlays & {"paused", "thread_disabled"}:
        tone = "paused"
    else:
        tone = "waiting"
    name = row.get("name")
    return {
        "interruption_id": row.get("interruption_id"),
        "thread_id": row.get("thread_id"),
        "name": one_line(name) if isinstance(name, str) and name.strip() else say(strings, "msg.toast_unnamed"),
        "reason": say(strings, reasons.label_key(category)),
        "tone": tone,
        "status": status,
        "at_zero": seconds is not None and seconds <= 0,
        "check_label": say(strings, "popup.resume_usage" if usage else "popup.resume_transient"),
        "checked": enabled,
        "busy": False,
    }


def view_model(rows, status, strings, now, *, notice=None, error=None) -> dict:
    """Everything the window says, as plain values. `rows` is None until the first read."""
    known = rows is not None
    ordered = sorted(rows or [], key=urgency)
    waiting = [row for row in ordered if is_waiting(row)]
    due = [row["eligible_at"] for row in waiting if row.get("eligible_at") is not None]
    dash = "—"
    state = activity(status, ordered, now)
    tasks = [task_item(row, strings, now) for row in ordered[:MAX_TASKS]]
    more = len(ordered) - len(tasks)
    paused = None if status is None else not status.get("enabled", True)
    return {
        "title": say(strings, "tray.title"),
        "state": state,
        "state_text": say(strings, "activity." + state),
        "counts": [
            (say(strings, "popup.count_waiting"), str(len(waiting)) if known else dash),
            (say(strings, "popup.count_recovering"), str(len(ordered) - len(waiting)) if known else dash),
            (say(strings, "popup.next_check"), countdown(max(0.0, min(due) - now)) if due else dash),
        ],
        "tasks": tasks,
        "more": say(strings, "popup.more", n=more) if more > 0 else None,
        "empty": say(strings, "popup.nothing") if known and not ordered else None,
        "zero_note": say(strings, "popup.zero_note") if any(task["at_zero"] for task in tasks) else None,
        "notice": notice,
        "error": error,
        "paused": paused,
        "toggle_text": say(strings, "action.resume" if paused else "action.pause"),
        "toggle_busy": False,
        "dashboard_text": say(strings, "popup.open_dashboard"),
    }


def busy_key(action):
    if not action:
        return None
    if action[0] == "recovery":
        return ("recovery", action[1])
    if action[0] == "enabled":
        return ("enabled",)
    return None


def perform(action, control, *, source=None, dashboard=None):
    """Run one action against the control layer. Called on a worker thread.

    Returns ("ok", payload), ("refused", code) for a coded refusal, or ("failed", name).
    """
    kind = action[0] if action else None
    try:
        if kind == "read":
            rows = control.list_pending(source=source) if source is not None else control.list_pending()
            return ("ok", {"rows": [dict(row) for row in rows], "status": dict(control.get_status())})
        if kind == "recovery":
            _, interruption_id, thread_id, enabled = action
            return ("ok", dict(control.set_interruption_recovery(interruption_id, thread_id, bool(enabled))))
        if kind == "enabled":
            return ("ok", dict(control.set_enabled(bool(action[1]))))
        if kind == "dashboard":
            return ("ok", {"opened": bool(dashboard()) if dashboard else False})
    except Exception as exc:                  # a front end reports; it never raises into the loop
        code = getattr(exc, "code", None)
        if isinstance(code, str) and code:
            return ("refused", code)
        return ("failed", type(exc).__name__)
    return ("failed", "unknown_action")


class PopupModel:
    """What the window knows, and what a click on what it drew means. No Win32 here."""

    def __init__(self, strings=None):
        self.strings = dict(strings or {})
        self.rows = None
        self.status = None
        self.read_failed = False
        self.notice_key = None
        self.notice_until = 0.0
        self.busy = set()
        # What the last view drew: interruption id -> (thread id, checked). A click is
        # resolved against this and nothing else.
        self.drawn = {}
        self.drawn_paused = None
        self.wants_read = False

    def view(self, now) -> dict:
        notice = (say(self.strings, self.notice_key)
                  if self.notice_key and now < self.notice_until else None)
        error = say(self.strings, "pending.unavailable") if self.read_failed and self.rows is None else None
        vm = view_model(self.rows, self.status, self.strings, now, notice=notice, error=error)
        for task in vm["tasks"]:
            task["busy"] = ("recovery", task["interruption_id"]) in self.busy
        vm["toggle_busy"] = ("enabled",) in self.busy or vm["paused"] is None
        self.drawn = {task["interruption_id"]: (task["thread_id"], task["checked"]) for task in vm["tasks"]}
        self.drawn_paused = vm["paused"]
        return vm

    def action_for(self, target):
        """The action a click on `target` asks for, from what was drawn - or None."""
        if not target:
            return None
        kind = target[0]
        if kind == "check" and len(target) == 2 and target[1] in self.drawn:
            thread_id, checked = self.drawn[target[1]]
            return ("recovery", target[1], thread_id, not checked)
        if kind == "toggle" and self.drawn_paused is not None:
            return ("enabled", bool(self.drawn_paused))     # paused -> resume, running -> pause
        if kind == "dashboard":
            return ("dashboard",)
        return None

    def begin(self, action) -> bool:
        """Mark an action as under way. False if the same one already is."""
        key = busy_key(action)
        if key is None:
            return True
        if key in self.busy:
            return False
        self.busy.add(key)
        return True

    def apply_outcome(self, action, outcome, now) -> None:
        kind = action[0]
        verdict = outcome[0]
        payload = outcome[1] if len(outcome) > 1 else None
        key = busy_key(action)
        if key is not None:
            self.busy.discard(key)
        if kind == "read":
            if verdict == "ok":
                self.rows = [dict(row) for row in payload["rows"]]
                self.status = dict(payload["status"])
                self.read_failed = False
            else:
                self.read_failed = True
            return
        if kind == "dashboard":
            return
        if verdict == "ok":
            # The control layer's own answer, for the conversation the click named.
            if kind == "recovery" and self.rows is not None:
                for row in self.rows:
                    if row.get("thread_id") == action[2]:
                        row["thread_enabled"] = bool(payload.get("enabled"))
            elif kind == "enabled" and self.status is not None:
                self.status["enabled"] = bool(payload.get("enabled"))
        else:
            # Refused or failed: nothing local changes. Say so, and look again.
            self.notice_key = "popup.stale" if kind == "recovery" and verdict == "refused" else "action.failed"
            self.notice_until = now + NOTICE_SECONDS
        self.wants_read = True

    def attention(self) -> bool:
        return self.status is not None and activity(self.status, self.rows, time.time()) == "attention"


def select_action(visible, now, *, hidden_at=None, double_click_at=None, previous_key_at=None,
                  keyboard=False) -> str:
    """What a select on the icon does: "show", "hide" or "none".

    Clicking the icon while the window is open first takes activation away from the window,
    which hides it, and only then reports the click. That click must not reopen it.
    """
    if keyboard and previous_key_at is not None and 0 <= now - previous_key_at < KEY_REPEAT_SECONDS:
        return "none"
    if double_click_at is not None and 0 <= now - double_click_at < DOUBLE_CLICK_SECONDS:
        return "none" if visible else "show"
    if visible:
        return "hide"
    if hidden_at is not None and 0 <= now - hidden_at < CLICK_AWAY_SECONDS:
        return "none"
    return "show"


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


# ------------------------------------------------------------------------------- motion
def _wave(elapsed_ms, period_ms) -> float:
    """0 at the start of a period, 1 halfway, back to 0: a breath."""
    phase = (elapsed_ms % period_ms) / float(period_ms)
    return 0.5 - 0.5 * math.cos(2 * math.pi * phase)


def halo(state, elapsed_ms, since_entered_ms=None, *, reduced=False):
    """The halo behind the state dot for one frame, or None when there is none.

    `opacity` is the halo's alpha, `scale` multiplies `HALO["radius"]`, and `arc` is the
    start angle of the checking arc in degrees (None when there is no arc).
    """
    low, high = brand.HALO["min_opacity"], brand.HALO["max_opacity"]
    middle = (low + high) / 2
    breathe, attention = brand.MOTION["breathe_ms"], brand.MOTION["attention_ms"]
    if state == "paused":
        return None
    if reduced:
        return {"opacity": middle, "scale": 1.0, "arc": None}
    if state == "monitoring":
        wave = _wave(elapsed_ms, breathe)
        return {"opacity": low + (high - low) * wave, "scale": 0.86 + 0.14 * wave, "arc": None}
    if state == "checking":
        return {"opacity": middle, "scale": 1.0,
                "arc": (elapsed_ms % attention) / float(attention) * 360.0}
    if state == "recovering":
        wave = _wave(elapsed_ms, attention)
        strong = min(1.0, high * 1.8)
        return {"opacity": high * 0.6 + (strong - high * 0.6) * wave, "scale": 0.9 + 0.3 * wave,
                "arc": None}
    if state == "attention":
        since = since_entered_ms if since_entered_ms is not None else attention
        if 0 <= since < attention:
            wave = math.sin(math.pi * since / float(attention))
            strong = min(1.0, high * 1.8)
            return {"opacity": middle + (strong - middle) * wave, "scale": 1.0 + 0.2 * wave, "arc": None}
        return {"opacity": middle, "scale": 1.0, "arc": None}
    return {"opacity": middle, "scale": 1.0, "arc": None}      # waiting: a still, soft halo


def animates(state, since_entered_ms=0, *, reduced=False) -> bool:
    """Whether the frame timer should run at all."""
    if reduced:
        return False
    if state in ("monitoring", "checking", "recovering"):
        return True
    if state == "attention":
        return since_entered_ms is not None and 0 <= since_entered_ms < brand.MOTION["attention_ms"]
    return False


# ---------------------------------------------------------------------------- the badge
def composite_badge(pixels, width, height, colour) -> None:
    """Draw a state dot into an icon's pixels, in place.

    `pixels` is top-down BGRA with straight alpha, as icon bitmaps are. The dot sits in the
    bottom-right corner inside a transparent cut-out, so it reads on a light taskbar and a
    dark one without a coloured ring of its own.
    """
    red, green, blue = colour
    cut = max(2.5, width * 0.25)
    ring = max(1.0, width / 16.0)
    dot = cut - ring
    cx, cy = width - cut, height - cut
    for y in range(max(0, int(cy - cut - 1)), height):
        for x in range(max(0, int(cx - cut - 1)), width):
            distance = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            cover_cut = max(0.0, min(1.0, cut - distance + 0.5))
            if cover_cut <= 0:
                continue
            cover_dot = max(0.0, min(1.0, dot - distance + 0.5))
            index = (y * width + x) * 4
            alpha = pixels[index + 3] / 255.0 * (1.0 - cover_cut)
            out = cover_dot + alpha * (1.0 - cover_dot)
            if out <= 0:
                pixels[index:index + 4] = bytes(4)
                continue
            for offset, value in ((0, blue), (1, green), (2, red)):
                mixed = (value * cover_dot + pixels[index + offset] * alpha * (1.0 - cover_dot)) / out
                pixels[index + offset] = int(round(mixed))
            pixels[index + 3] = int(round(out * 255))


# ------------------------------------------------------------------------------- layout
def layout(vm, scale, measure, width=WIDTH) -> dict:
    """Every rectangle the window draws, in device pixels, and the height it needs.

    `measure(role, text, width, wrap)` returns the (width, height) the text takes in that
    font role - wrapped to `width` when `wrap`, on one line otherwise. Nothing is clipped:
    what does not fit on a line wraps and makes its block taller, and the only text that is
    shortened with an ellipsis is a conversation name and a reason chip.
    """
    space = brand.SPACING

    def px(value):
        return int(round(value * scale))

    total = px(width)
    margin, pad = px(space["m"]), px(space["l"])
    left, right = margin + pad, total - margin - pad
    inner = right - left
    items, targets = [], []
    y = margin + pad

    def text(rect, role, value, colour, *, wrap=False, align="left", target=None):
        items.append({"kind": "text", "rect": rect, "role": role, "text": value, "colour": colour,
                      "wrap": wrap, "align": align, "target": target})

    # Header: the state dot, the product, the state in words.
    mark = px(2 * brand.HALO["radius"] + 4)
    text_left = left + mark + px(space["s"] + 2)
    text_width = right - text_left
    _, title_h = measure("title", vm["title"], text_width, False)
    _, state_h = measure("state", vm["state_text"], text_width, True)
    stack = title_h + state_h
    header_h = max(mark, stack)
    top = y + (header_h - stack) // 2
    items.append({"kind": "halo", "cx": left + mark / 2.0, "cy": y + header_h / 2.0, "state": vm["state"],
                  "radius": brand.HALO["radius"] * scale})
    text((text_left, top, right, top + title_h), "title", vm["title"], "ink")
    text((text_left, top + title_h, right, top + stack), "state", vm["state_text"],
         STATE_INK.get(vm["state"], "ink"), wrap=True)
    y += header_h + px(space["m"])

    # Summary: waiting, recovering, next check.
    items.append({"kind": "rule", "rect": (left, y, right, y + max(1, px(1)))})
    y += px(space["m"])
    gutter = px(space["m"])
    column = (inner - 2 * gutter) // 3
    label_h = max(measure("label", label, column, True)[1] for label, _ in vm["counts"])
    value_h = max(measure("value", value, column, False)[1] for _, value in vm["counts"])
    for index, (label, value) in enumerate(vm["counts"]):
        x = left + index * (column + gutter)
        if index:
            rule_x = x - gutter // 2
            items.append({"kind": "rule", "rect": (rule_x, y + px(2), rule_x + max(1, px(1)),
                                                   y + label_h + value_h)})
        text((x, y, x + column, y + label_h), "label", label, "muted", wrap=True)
        text((x, y + label_h + px(2), x + column, y + label_h + px(2) + value_h), "value", value, "ink")
    y += label_h + px(2) + value_h + px(space["m"])
    items.append({"kind": "rule", "rect": (left, y, right, y + max(1, px(1)))})
    y += px(space["m"])

    # The tasks, most urgent first.
    row_pad = px(space["m"])
    for task in vm["tasks"]:
        target = ("check", task["interruption_id"])
        row_top = y
        x0, x1 = left + row_pad, right - row_pad
        content = x1 - x0
        contents = []
        chip_text_w, chip_text_h = measure("chip", task["reason"], content, False)
        chip_pad = px(space["s"])
        chip_w = min(chip_text_w + 2 * chip_pad, content // 2)
        chip_h = chip_text_h + px(4)
        name_w = content - chip_w - px(space["s"])
        _, name_h = measure("name", task["name"], name_w, False)
        line_h = max(name_h, chip_h)
        line_top = row_top + row_pad
        contents.append({"kind": "text", "rect": (x0, line_top + (line_h - name_h) // 2, x0 + name_w,
                                                  line_top + (line_h - name_h) // 2 + name_h),
                         "role": "name", "text": task["name"], "colour": "ink", "wrap": False,
                         "align": "left", "target": None})
        chip = (x1 - chip_w, line_top + (line_h - chip_h) // 2, x1, line_top + (line_h - chip_h) // 2 + chip_h)
        contents.append({"kind": "chip", "rect": chip, "tone": task["tone"]})
        contents.append({"kind": "text", "rect": (chip[0] + chip_pad, chip[1], chip[2] - chip_pad, chip[3]),
                         "role": "chip", "text": task["reason"], "colour": task["tone"], "wrap": False,
                         "align": "center", "target": None})
        line = line_top + line_h + px(2)
        _, status_h = measure("small", task["status"], content, True)
        contents.append({"kind": "text", "rect": (x0, line, x1, line + status_h), "role": "small",
                         "text": task["status"], "colour": "muted", "wrap": True, "align": "left",
                         "target": None})
        line += status_h + px(space["s"]) + px(2)
        box = px(16)
        label_left = x0 + box + px(space["s"])
        _, label_h = measure("body", task["check_label"], x1 - label_left, True)
        _, first_line = measure("body", "Ag", content, False)
        check_h = max(box, label_h)
        box_top = line + max(0, (min(first_line, check_h) - box) // 2)
        contents.append({"kind": "check", "rect": (x0, box_top, x0 + box, box_top + box),
                         "checked": task["checked"], "busy": task["busy"], "target": target})
        contents.append({"kind": "text", "rect": (label_left, line, x1, line + label_h), "role": "body",
                         "text": task["check_label"], "colour": "ink", "wrap": True, "align": "left",
                         "target": target})
        hit = (x0 - px(4), line - px(4), x1 + px(4), line + check_h + px(4))
        targets.append((target, hit))
        row_bottom = line + check_h + row_pad
        items.append({"kind": "panel", "rect": (left, row_top, right, row_bottom)})
        items.extend(contents)
        items.append({"kind": "focusable", "rect": hit, "target": target, "radius": px(brand.RADII["small"])})
        y = row_bottom + px(space["s"])

    if vm["more"]:
        _, more_h = measure("small", vm["more"], inner, True)
        text((left, y, right, y + more_h), "small", vm["more"], "muted", wrap=True, align="center")
        y += more_h + px(space["s"])

    quiet = vm["error"] or vm["empty"]
    if quiet:
        _, quiet_h = measure("body", quiet, inner - 2 * pad, True)
        block = quiet_h + 2 * pad
        items.append({"kind": "panel", "rect": (left, y, right, y + block)})
        text((left + pad, y + pad, right - pad, y + pad + quiet_h), "body", quiet, "muted",
             wrap=True, align="center")
        y += block + px(space["s"])

    if vm["zero_note"]:
        _, note_h = measure("small", vm["zero_note"], inner, True)
        text((left, y, right, y + note_h), "small", vm["zero_note"], "muted", wrap=True)
        y += note_h + px(space["s"])

    if vm["notice"]:
        inset = px(space["s"])
        _, notice_h = measure("small", vm["notice"], inner - 2 * inset, True)
        block = notice_h + 2 * inset
        items.append({"kind": "note", "rect": (left, y, right, y + block), "tone": "warning"})
        text((left + inset, y + inset, right - inset, y + inset + notice_h), "small", vm["notice"],
             "warning", wrap=True)
        y += block + px(space["s"])

    # Footer: Pause/Resume and Open Dashboard. Side by side when both fit on one line,
    # stacked when either would not - a German button label is not cut in half.
    y += px(space["xs"])
    button_h = px(32)
    button_pad = px(space["m"])
    buttons = (("toggle", vm["toggle_text"], False, vm["toggle_busy"]),
               ("dashboard", vm["dashboard_text"], True, False))
    half = (inner - px(space["s"])) // 2
    widths = [measure("button", label, inner, False)[0] for _, label, _, _ in buttons]
    if max(widths) + 2 * button_pad <= half:
        placed = [((left, y, left + half, y + button_h), False), ((right - half, y, right, y + button_h), False)]
        y += button_h
    else:
        placed = []
        for index, (_, label, _, _) in enumerate(buttons):
            _, label_h = measure("button", label, inner - 2 * button_pad, True)
            height = max(button_h, label_h + 2 * px(space["s"]))
            placed.append(((left, y, right, y + height), True))
            y += height + (px(space["s"]) if index == 0 else 0)
    for (name, label, primary, busy), (rect, wrapped) in zip(buttons, placed):
        target = (name,)
        items.append({"kind": "button", "rect": rect, "primary": primary, "busy": busy, "target": target})
        if wrapped:
            _, label_h = measure("button", label, rect[2] - rect[0] - 2 * button_pad, True)
            top = rect[1] + (rect[3] - rect[1] - label_h) // 2
            label_rect = (rect[0] + button_pad, top, rect[2] - button_pad, top + label_h)
        else:
            label_rect = (rect[0] + button_pad, rect[1], rect[2] - button_pad, rect[3])
        items.append({"kind": "text", "rect": label_rect, "role": "button", "text": label,
                      "colour": "on_accent" if primary else "ink", "wrap": wrapped, "align": "center",
                      "target": target})
        targets.append((target, rect))
        items.append({"kind": "focusable", "rect": rect, "target": target, "radius": px(brand.RADII["control"])})
    y += pad
    card = (margin, margin, total - margin, y)
    items.insert(0, {"kind": "card", "rect": card, "radius": px(brand.RADII["card"])})
    return {"size": (total, y + margin), "card": card, "items": items, "targets": targets, "scale": scale}


# ============================================================================ the Win32 half
if os.name == "nt":
    from ctypes import wintypes as W
    from .tray import GUID, LRESULT, WNDCLASSW, WNDPROC
else:                                              # pragma: no cover - the pure half only
    W = None

WM_ACTIVATE, WM_PAINT, WM_CLOSE, WM_ERASEBKGND = 0x0006, 0x000F, 0x0010, 0x0014
WM_SETTINGCHANGE, WM_KEYDOWN, WM_TIMER = 0x001A, 0x0100, 0x0113
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSELEAVE = 0x0200, 0x0201, 0x0202, 0x02A3
WM_DPICHANGED = 0x02E0
WM_APP = 0x8000
WM_POPUP_RESULT = WM_APP + 2
WM_POPUP_STRINGS = WM_APP + 3
WA_INACTIVE = 0
VK_TAB, VK_RETURN, VK_SHIFT, VK_ESCAPE, VK_SPACE = 0x09, 0x0D, 0x10, 0x1B, 0x20
VK_UP, VK_DOWN = 0x26, 0x28
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080
CS_DROPSHADOW = 0x00020000
SW_HIDE, SW_SHOWNOACTIVATE, SW_SHOW = 0, 4, 5
SWP_NOACTIVATE = 0x0010
HWND_TOPMOST = -1
IDC_ARROW = 32512
MONITOR_DEFAULTTONEAREST = 2
TME_LEAVE = 0x2
SPI_GETCLIENTAREAANIMATION = 0x1042
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DT_CENTER, DT_VCENTER, DT_WORDBREAK, DT_SINGLELINE = 0x1, 0x4, 0x10, 0x20
DT_CALCRECT, DT_NOPREFIX, DT_EDITCONTROL, DT_END_ELLIPSIS = 0x400, 0x800, 0x2000, 0x8000
TIMER_TICK, TIMER_FRAME, TIMER_FIRST = 1, 2, 3
GR_GDIOBJECTS, GR_USEROBJECTS = 0, 1

# Font roles: size in px at 96 DPI and weight. The product line is smaller than TYPE's
# title because this is a flyout, not a window.
ROLES = {
    "title": (15, 600),
    "state": (brand.TYPE["body"], 400),
    "label": (brand.TYPE["small"], 400),
    "value": (brand.TYPE["heading"], 600),
    "name": (brand.TYPE["body"], 600),
    "chip": (brand.TYPE["small"], 600),
    "body": (brand.TYPE["body"], 400),
    "small": (brand.TYPE["small"], 400),
    "button": (brand.TYPE["body"], 600),
}
# Ideographic and Hangul text at 11-12 px loses strokes; these scripts get one pixel more.
_DENSE_SCRIPTS = frozenset({"ko", "ja", "zh-CN", "zh-TW"})
# Languages whose lines break between words only, where GDI would break inside a word.
_BREAK_AT_SPACES = frozenset({"ko"})


def role_size(role, locale) -> int:
    size, _ = ROLES[role]
    return size + 1 if locale in _DENSE_SCRIPTS and size <= 12 else size


def argb(token, alpha=1.0) -> int:
    red, green, blue = brand.rgb(brand.LIGHT[token])
    return (max(0, min(255, int(round(alpha * 255)))) << 24) | (red << 16) | (green << 8) | blue


def colorref(token) -> int:
    red, green, blue = brand.rgb(brand.LIGHT[token])
    return red | (green << 8) | (blue << 16)


_DLLS = {}
_DECLARED = False
_DECLARE_LOCK = threading.Lock()


def _dll(name):
    """This module's own handles, so its argument types never change another module's."""
    if name not in _DLLS:
        _DLLS[name] = C.WinDLL(name, use_last_error=True)
    return _DLLS[name]


if os.name == "nt":
    class MONITORINFO(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("rcMonitor", W.RECT), ("rcWork", W.RECT), ("dwFlags", W.DWORD)]

    class PAINTSTRUCT(C.Structure):
        _fields_ = [("hdc", W.HDC), ("fErase", W.BOOL), ("rcPaint", W.RECT), ("fRestore", W.BOOL),
                    ("fIncUpdate", W.BOOL), ("rgbReserved", C.c_ubyte * 32)]

    class TRACKMOUSEEVENT(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("dwFlags", W.DWORD), ("hwndTrack", W.HWND), ("dwHoverTime", W.DWORD)]

    class BITMAPINFOHEADER(C.Structure):
        _fields_ = [("biSize", W.DWORD), ("biWidth", W.LONG), ("biHeight", W.LONG), ("biPlanes", W.WORD),
                    ("biBitCount", W.WORD), ("biCompression", W.DWORD), ("biSizeImage", W.DWORD),
                    ("biXPelsPerMeter", W.LONG), ("biYPelsPerMeter", W.LONG), ("biClrUsed", W.DWORD),
                    ("biClrImportant", W.DWORD)]

    class BITMAPINFO(C.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", W.DWORD * 3)]

    class BITMAP(C.Structure):
        _fields_ = [("bmType", W.LONG), ("bmWidth", W.LONG), ("bmHeight", W.LONG), ("bmWidthBytes", W.LONG),
                    ("bmPlanes", W.WORD), ("bmBitsPixel", W.WORD), ("bmBits", C.c_void_p)]

    class ICONINFO(C.Structure):
        _fields_ = [("fIcon", W.BOOL), ("xHotspot", W.DWORD), ("yHotspot", W.DWORD),
                    ("hbmMask", W.HBITMAP), ("hbmColor", W.HBITMAP)]

    class NOTIFYICONIDENTIFIER(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("hWnd", W.HWND), ("uID", W.UINT), ("guidItem", GUID)]

    class GdiplusStartupInput(C.Structure):
        _fields_ = [("GdiplusVersion", C.c_uint32), ("DebugEventCallback", C.c_void_p),
                    ("SuppressBackgroundThread", W.BOOL), ("SuppressExternalCodecs", W.BOOL)]

    class PointF(C.Structure):
        _fields_ = [("X", C.c_float), ("Y", C.c_float)]


def _signature(function, result, *arguments):
    function.restype = result
    function.argtypes = list(arguments)


def _declare():
    """Argument and result types for every call below, once. Handles are pointers: a
    64-bit handle returned through ctypes' default `int` would be silently cut in half."""
    global _DECLARED
    with _DECLARE_LOCK:
        if _DECLARED:
            return
        H, F, I, U, D = C.c_void_p, C.c_float, C.c_int, W.UINT, W.DWORD
        user32, gdi32, kernel32, gdiplus = _dll("user32"), _dll("gdi32"), _dll("kernel32"), _dll("gdiplus")
        _signature(user32.CreateWindowExW, H, D, W.LPCWSTR, W.LPCWSTR, D, I, I, I, I, H, H, H, H)
        _signature(user32.DefWindowProcW, LRESULT, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.RegisterClassW, W.ATOM, C.POINTER(WNDCLASSW))
        _signature(user32.UnregisterClassW, W.BOOL, W.LPCWSTR, H)
        _signature(user32.DestroyWindow, W.BOOL, H)
        _signature(user32.ShowWindow, W.BOOL, H, I)
        _signature(user32.SetWindowPos, W.BOOL, H, H, I, I, I, I, U)
        _signature(user32.SetForegroundWindow, W.BOOL, H)
        _signature(user32.SetFocus, H, H)
        _signature(user32.InvalidateRect, W.BOOL, H, H, W.BOOL)
        _signature(user32.UpdateWindow, W.BOOL, H)
        _signature(user32.BeginPaint, H, H, C.POINTER(PAINTSTRUCT))
        _signature(user32.EndPaint, W.BOOL, H, C.POINTER(PAINTSTRUCT))
        _signature(user32.SetTimer, C.c_size_t, H, C.c_size_t, U, H)
        _signature(user32.KillTimer, W.BOOL, H, C.c_size_t)
        _signature(user32.PostMessageW, W.BOOL, H, U, W.WPARAM, W.LPARAM)
        _signature(user32.GetCursorPos, W.BOOL, C.POINTER(W.POINT))
        _signature(user32.MonitorFromRect, H, C.POINTER(W.RECT), D)
        _signature(user32.GetMonitorInfoW, W.BOOL, H, C.POINTER(MONITORINFO))
        _signature(user32.SystemParametersInfoW, W.BOOL, U, U, H, U)
        _signature(user32.GetKeyState, C.c_short, I)
        _signature(user32.TrackMouseEvent, W.BOOL, C.POINTER(TRACKMOUSEEVENT))
        _signature(user32.LoadCursorW, H, H, H)
        _signature(user32.SetWindowRgn, I, H, H, W.BOOL)
        _signature(user32.DrawTextW, I, H, W.LPCWSTR, I, C.POINTER(W.RECT), U)
        _signature(user32.GetIconInfo, W.BOOL, H, C.POINTER(ICONINFO))
        _signature(user32.CreateIconIndirect, H, C.POINTER(ICONINFO))
        _signature(user32.DestroyIcon, W.BOOL, H)
        _signature(user32.GetGuiResources, D, H, D)
        for name, result, arguments in (("GetDpiForWindow", U, (H,)),
                                        ("SetThreadDpiAwarenessContext", H, (H,))):
            function = getattr(user32, name, None)
            if function is not None:
                _signature(function, result, *arguments)
        _signature(gdi32.CreateCompatibleDC, H, H)
        _signature(gdi32.DeleteDC, W.BOOL, H)
        _signature(gdi32.CreateDIBSection, H, H, C.POINTER(BITMAPINFO), U, C.POINTER(C.c_void_p), H, D)
        _signature(gdi32.SelectObject, H, H, H)
        _signature(gdi32.DeleteObject, W.BOOL, H)
        _signature(gdi32.GetObjectW, I, H, I, H)
        _signature(gdi32.CreateFontW, H, I, I, I, I, I, D, D, D, D, D, D, D, D, W.LPCWSTR)
        _signature(gdi32.GetTextFaceW, I, H, I, W.LPWSTR)
        _signature(gdi32.SetTextColor, D, H, D)
        _signature(gdi32.SetBkMode, I, H, I)
        _signature(gdi32.SetDIBitsToDevice, I, H, I, I, D, D, I, I, U, U, H, C.POINTER(BITMAPINFO), U)
        _signature(gdi32.CreateRoundRectRgn, H, I, I, I, I, I, I)
        _signature(gdi32.GetDIBits, I, H, H, U, U, H, C.POINTER(BITMAPINFO), U)
        _signature(gdi32.CreateBitmap, H, I, I, U, U, H)
        _signature(kernel32.GetModuleHandleW, H, W.LPCWSTR)
        _signature(kernel32.GetCurrentProcess, H)
        _signature(gdiplus.GdiplusStartup, I, C.POINTER(C.c_size_t), C.POINTER(GdiplusStartupInput), H)
        _signature(gdiplus.GdiplusShutdown, None, C.c_size_t)
        _signature(gdi32.GdiFlush, W.BOOL)
        _signature(gdiplus.GdipCreateBitmapFromScan0, I, I, I, I, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipGetImageGraphicsContext, I, H, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDisposeImage, I, H)
        _signature(gdiplus.GdipDeleteGraphics, I, H)
        _signature(gdiplus.GdipSetSmoothingMode, I, H, I)
        _signature(gdiplus.GdipSetPixelOffsetMode, I, H, I)
        _signature(gdiplus.GdipCreateSolidFill, I, D, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeleteBrush, I, H)
        _signature(gdiplus.GdipCreatePen1, I, D, F, I, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeletePen, I, H)
        _signature(gdiplus.GdipSetPenStartCap, I, H, I)
        _signature(gdiplus.GdipSetPenEndCap, I, H, I)
        _signature(gdiplus.GdipSetPenLineJoin, I, H, I)
        _signature(gdiplus.GdipCreatePath, I, I, C.POINTER(C.c_void_p))
        _signature(gdiplus.GdipDeletePath, I, H)
        _signature(gdiplus.GdipAddPathArc, I, H, F, F, F, F, F, F)
        _signature(gdiplus.GdipAddPathRectangle, I, H, F, F, F, F)
        _signature(gdiplus.GdipClosePathFigure, I, H)
        _signature(gdiplus.GdipFillPath, I, H, H, H)
        _signature(gdiplus.GdipDrawPath, I, H, H, H)
        _signature(gdiplus.GdipFillEllipse, I, H, H, F, F, F, F)
        _signature(gdiplus.GdipDrawArc, I, H, H, F, F, F, F, F, F)
        _signature(gdiplus.GdipDrawLines, I, H, H, C.POINTER(PointF), I)
        _DECLARED = True


class _PerMonitorDpi:
    """Per-monitor-v2 coordinates for this thread while inside, restored afterwards."""

    def __enter__(self):
        self.previous = None
        function = getattr(_dll("user32"), "SetThreadDpiAwarenessContext", None)
        if function is not None:
            self.previous = function(C.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
        return self

    def __exit__(self, *unused):
        function = getattr(_dll("user32"), "SetThreadDpiAwarenessContext", None)
        if function is not None and self.previous:
            function(C.c_void_p(self.previous))


# The product's own Reduce motion setting, adopted by the watcher whenever it reads its
# settings. Windows' own switch is honoured as well; either one stops all motion.
_reduce_motion_setting = False


def set_reduce_motion(value) -> None:
    global _reduce_motion_setting
    _reduce_motion_setting = value is True


def reduced_motion() -> bool:
    """True when Windows, or this product's Reduce motion setting, asks for fewer animations."""
    if _reduce_motion_setting:
        return True
    try:
        _declare()
        value = W.BOOL(1)
        if not _dll("user32").SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, C.byref(value), 0):
            return False
        return not value.value
    except Exception:
        return False


def gui_resources() -> tuple:
    """(GDI objects, USER objects) this process holds, for the leak tests."""
    _declare()
    user32, process = _dll("user32"), _dll("kernel32").GetCurrentProcess()
    return (user32.GetGuiResources(process, GR_GDIOBJECTS), user32.GetGuiResources(process, GR_USEROBJECTS))


def icon_rect(hwnd, uid=1):
    """The icon's rectangle on screen, or None (in the overflow flyout, or not yet placed)."""
    try:
        _declare()
        shell32 = _dll("shell32")
        _signature(shell32.Shell_NotifyIconGetRect, C.c_long, C.POINTER(NOTIFYICONIDENTIFIER), C.POINTER(W.RECT))
        identifier = NOTIFYICONIDENTIFIER()
        identifier.cbSize = C.sizeof(NOTIFYICONIDENTIFIER)
        identifier.hWnd = hwnd
        identifier.uID = uid
        rect = W.RECT()
        if shell32.Shell_NotifyIconGetRect(C.byref(identifier), C.byref(rect)) != 0:
            return None
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


# ------------------------------------------------------------------------------ GDI+
_GDIPLUS = {"token": 0, "users": 0}
_GDIPLUS_LOCK = threading.Lock()


def _gdiplus_acquire():
    _declare()
    with _GDIPLUS_LOCK:
        if _GDIPLUS["users"] == 0:
            token = C.c_size_t(0)
            startup = GdiplusStartupInput(1, None, False, False)
            status = _dll("gdiplus").GdiplusStartup(C.byref(token), C.byref(startup), None)
            if status != 0:
                raise OSError("GdiplusStartup failed (%d)" % status)
            _GDIPLUS["token"] = token.value
        _GDIPLUS["users"] += 1


def _gdiplus_release():
    with _GDIPLUS_LOCK:
        if _GDIPLUS["users"] <= 0:
            return
        _GDIPLUS["users"] -= 1
        if _GDIPLUS["users"] == 0:
            _dll("gdiplus").GdiplusShutdown(_GDIPLUS["token"])
            _GDIPLUS["token"] = 0


PIXEL_FORMAT_32BPP_RGB = 0x00022009


class _Painter:
    """Antialiased shapes straight into a canvas's pixels, through the GDI+ flat API.

    GDI+ is pointed at the DIB's own memory rather than at its DC: drawing through a DC
    makes GDI+ compose every shape in a buffer of its own and copy it back, which at this
    window's size cost about a tenth of a second a frame. Every object is released.
    """

    def __init__(self, canvas):
        self.gp = _dll("gdiplus")
        self.bitmap = C.c_void_p()
        self.graphics = C.c_void_p()
        _dll("gdi32").GdiFlush()                               # GDI may still owe us text
        status = self.gp.GdipCreateBitmapFromScan0(canvas.width, canvas.height, canvas.width * 4,
                                                   PIXEL_FORMAT_32BPP_RGB, canvas.bits, C.byref(self.bitmap))
        if status != 0:
            raise OSError("GdipCreateBitmapFromScan0 failed (%d)" % status)
        status = self.gp.GdipGetImageGraphicsContext(self.bitmap, C.byref(self.graphics))
        if status != 0:
            self.gp.GdipDisposeImage(self.bitmap)
            raise OSError("GdipGetImageGraphicsContext failed (%d)" % status)
        self.gp.GdipSetSmoothingMode(self.graphics, 4)         # antialias
        self.gp.GdipSetPixelOffsetMode(self.graphics, 4)       # half: edges land on pixel edges

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        self.gp.GdipDeleteGraphics(self.graphics)
        self.gp.GdipDisposeImage(self.bitmap)

    def _path(self, rect, radius):
        left, top, right, bottom = (float(value) for value in rect)
        path = C.c_void_p()
        self.gp.GdipCreatePath(0, C.byref(path))
        radius = max(0.0, min(float(radius), (right - left) / 2.0, (bottom - top) / 2.0))
        if radius <= 0.0:
            self.gp.GdipAddPathRectangle(path, left, top, right - left, bottom - top)
            return path
        d = radius * 2.0
        self.gp.GdipAddPathArc(path, left, top, d, d, 180.0, 90.0)
        self.gp.GdipAddPathArc(path, right - d, top, d, d, 270.0, 90.0)
        self.gp.GdipAddPathArc(path, right - d, bottom - d, d, d, 0.0, 90.0)
        self.gp.GdipAddPathArc(path, left, bottom - d, d, d, 90.0, 90.0)
        self.gp.GdipClosePathFigure(path)
        return path

    def _pen(self, colour, width):
        pen = C.c_void_p()
        self.gp.GdipCreatePen1(colour, float(width), 2, C.byref(pen))      # unit: pixel
        self.gp.GdipSetPenStartCap(pen, 2)                                 # round
        self.gp.GdipSetPenEndCap(pen, 2)
        self.gp.GdipSetPenLineJoin(pen, 2)
        return pen

    def fill_round(self, rect, radius, colour):
        path, brush = self._path(rect, radius), C.c_void_p()
        self.gp.GdipCreateSolidFill(colour, C.byref(brush))
        try:
            self.gp.GdipFillPath(self.graphics, brush, path)
        finally:
            self.gp.GdipDeleteBrush(brush)
            self.gp.GdipDeletePath(path)

    def stroke_round(self, rect, radius, colour, width):
        half = width / 2.0
        inner = (rect[0] + half, rect[1] + half, rect[2] - half, rect[3] - half)
        path, pen = self._path(inner, max(0.0, radius - half)), self._pen(colour, width)
        try:
            self.gp.GdipDrawPath(self.graphics, pen, path)
        finally:
            self.gp.GdipDeletePen(pen)
            self.gp.GdipDeletePath(path)

    def fill_circle(self, cx, cy, radius, colour):
        brush = C.c_void_p()
        self.gp.GdipCreateSolidFill(colour, C.byref(brush))
        try:
            self.gp.GdipFillEllipse(self.graphics, brush, float(cx - radius), float(cy - radius),
                                    float(radius * 2), float(radius * 2))
        finally:
            self.gp.GdipDeleteBrush(brush)

    def arc(self, cx, cy, radius, start, sweep, colour, width):
        pen = self._pen(colour, width)
        try:
            self.gp.GdipDrawArc(self.graphics, pen, float(cx - radius), float(cy - radius),
                                float(radius * 2), float(radius * 2), float(start), float(sweep))
        finally:
            self.gp.GdipDeletePen(pen)

    def lines(self, points, colour, width):
        array = (PointF * len(points))(*[PointF(float(x), float(y)) for x, y in points])
        pen = self._pen(colour, width)
        try:
            self.gp.GdipDrawLines(self.graphics, pen, array, len(points))
        finally:
            self.gp.GdipDeletePen(pen)


class _Canvas:
    """A top-down 32-bpp DIB selected into a memory DC: the frame is built here, whole,
    and handed to the window in one call."""

    def __init__(self):
        self.dc = _dll("gdi32").CreateCompatibleDC(None)
        if not self.dc:
            raise OSError("CreateCompatibleDC")
        self.bitmap = None
        self.original = None
        self.bits = C.c_void_p()
        self.info = BITMAPINFO()
        self.width = self.height = 0

    def ensure(self, width, height):
        if self.bitmap and (width, height) == (self.width, self.height):
            return
        gdi32 = _dll("gdi32")
        info = BITMAPINFO()
        info.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = C.c_void_p()
        bitmap = gdi32.CreateDIBSection(self.dc, C.byref(info), 0, C.byref(bits), None, 0)
        if not bitmap:
            raise OSError("CreateDIBSection")
        previous = gdi32.SelectObject(self.dc, bitmap)
        if self.bitmap:
            gdi32.DeleteObject(self.bitmap)
        else:
            self.original = previous
        self.bitmap, self.bits, self.info, self.width, self.height = bitmap, bits, info, width, height

    def pixels(self) -> bytes:
        return C.string_at(self.bits, self.width * self.height * 4)

    def close(self):
        gdi32 = _dll("gdi32")
        if self.bitmap:
            gdi32.SelectObject(self.dc, self.original)
            gdi32.DeleteObject(self.bitmap)
            self.bitmap = None
        if self.dc:
            gdi32.DeleteDC(self.dc)
            self.dc = None


_FACE_CACHE = {}
_SUBSTITUTE = {}
_NO_SUCH_FACE = "CodexAutoResume No Such Face"


def _realized_face(dc, face) -> str:
    gdi32 = _dll("gdi32")
    font = gdi32.CreateFontW(-12, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, face)
    if not font:
        return ""
    previous = gdi32.SelectObject(dc, font)
    try:
        buffer = C.create_unicode_buffer(64)
        gdi32.GetTextFaceW(dc, 64, buffer)
        return buffer.value
    finally:
        gdi32.SelectObject(dc, previous)
        gdi32.DeleteObject(font)


def _face_exists(dc, face) -> bool:
    """Whether GDI has this face itself rather than a substitute for it.

    `GetTextFaceW` answers with a family's localized name - Malgun Gothic is reported as
    its Korean name on a Korean system - so a face counts as present when the answer is its
    own name, or is anything other than what a face that does not exist is mapped to.
    """
    if face not in _FACE_CACHE:
        if "name" not in _SUBSTITUTE:
            _SUBSTITUTE["name"] = _realized_face(dc, _NO_SUCH_FACE)
        realized = _realized_face(dc, face)
        _FACE_CACHE[face] = bool(realized) and (realized.lower() == face.lower()
                                                or realized != _SUBSTITUTE["name"])
    return _FACE_CACHE[face]


class _Fonts:
    def __init__(self, dc, locale, scale):
        gdi32 = _dll("gdi32")
        self.key = (locale, scale)
        self.handles = {}
        self.faces = {}
        try:
            for role, (_, weight) in ROLES.items():
                candidates = font_candidates(locale, weight)
                face, actual = next(((name, value) for name, value in candidates if _face_exists(dc, name)),
                                    candidates[-1])
                height = -max(1, int(round(role_size(role, locale) * scale)))
                handle = gdi32.CreateFontW(height, 0, 0, 0, actual, 0, 0, 0, 1, 0, 0, 5, 0, face)
                if not handle:
                    raise OSError("CreateFontW")
                self.handles[role] = handle
                self.faces[role] = face
        except Exception:
            self.close()
            raise

    def close(self):
        gdi32 = _dll("gdi32")
        for handle in self.handles.values():
            gdi32.DeleteObject(handle)
        self.handles = {}


class Renderer:
    """Draws a view model into its own canvas. Owns every GDI and GDI+ object it makes."""

    def __init__(self):
        _declare()
        _gdiplus_acquire()
        try:
            self.canvas = _Canvas()
        except Exception:
            _gdiplus_release()
            raise
        self.fonts = None
        self._background_key = None
        self._background_pixels = None
        self._halo_band = None
        self._halo_plan = None

    def close(self):
        if self.fonts is not None:
            self.fonts.close()
            self.fonts = None
        if self.canvas is not None:
            self.canvas.close()
            self.canvas = None
            _gdiplus_release()

    def use(self, locale, scale):
        if self.fonts is None or self.fonts.key != (locale, scale):
            if self.fonts is not None:
                self.fonts.close()
                self.fonts = None
            self.fonts = _Fonts(self.canvas.dc, locale, scale)

    def lines(self, role, text, width):
        """Text as it will wrap, with the breaks made explicit where GDI's would be wrong.

        GDI breaks Korean between any two syllables, and Korean is set with breaks between
        words only. So Korean is broken here, at spaces, measured by GDI itself; a single
        word wider than the whole line is the one case left to GDI.
        """
        if not text or self.fonts is None or self.fonts.key[0] not in _BREAK_AT_SPACES:
            return text
        lines, line = [], ""
        for word in text.split(" "):
            candidate = word if not line else line + " " + word
            if not line or self.measure(role, candidate, width, False)[0] <= width:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if any(self.measure(role, entry, width, False)[0] > width for entry in lines):
            return text
        return "\n".join(lines)

    def measure(self, role, text, width, wrap):
        if wrap:
            text = self.lines(role, text, width)
        gdi32, user32 = _dll("gdi32"), _dll("user32")
        dc = self.canvas.dc
        previous = gdi32.SelectObject(dc, self.fonts.handles[role])
        try:
            rect = W.RECT(0, 0, max(1, int(width)), 0)
            flags = DT_CALCRECT | DT_NOPREFIX | ((DT_WORDBREAK | DT_EDITCONTROL) if wrap else DT_SINGLELINE)
            user32.DrawTextW(dc, text or " ", -1, C.byref(rect), flags)
            return rect.right - rect.left, rect.bottom - rect.top
        finally:
            gdi32.SelectObject(dc, previous)

    def layout(self, vm, scale, locale):
        self.use(locale, scale)
        return layout(vm, scale, self.measure)

    def draw(self, vm, plan, *, frame=None, hover=None, pressed=None, focus=None):
        """One whole frame into the canvas. Returns the canvas."""
        width, height = plan["size"]
        scale = plan["scale"]
        canvas = self.canvas
        canvas.ensure(width, height)
        self._background(plan)
        busy = {item["target"] for item in plan["items"] if item.get("busy")}
        with _Painter(canvas) as paint:
            for item in plan["items"]:
                if item["kind"] not in ("card", "halo"):
                    self._shape(paint, item, scale, hover, pressed)
        self._text(canvas.dc, plan, busy)
        with _Painter(canvas) as paint:
            for item in plan["items"]:
                if item["kind"] == "check" and item["checked"]:
                    self._tick(paint, item, scale)
                if item["kind"] == "focusable" and focus is not None and item["target"] == focus:
                    ring = max(2.0, 2.0 * scale)
                    grow = ring + max(1.0, scale)
                    rect = item["rect"]
                    paint.stroke_round((rect[0] - grow, rect[1] - grow, rect[2] + grow, rect[3] + grow),
                                       item["radius"] + grow, argb("focus"), ring)
        self._keep_halo_band(plan)
        return self.draw_halo(plan, frame, restore=False)

    def draw_halo(self, plan, frame, *, restore=True):
        """Only the halo, for an animation frame; everything else in the canvas is kept.

        The band of rows behind the halo was saved when the whole frame was drawn, so a
        frame is one memory copy and two antialiased circles rather than the whole window.
        """
        item = next((entry for entry in plan["items"] if entry["kind"] == "halo"), None)
        if item is None:
            return self.canvas
        if restore:
            if self._halo_plan is not plan or self._halo_band is None:
                raise ValueError("the whole frame has to be drawn before its halo")
            offset, band = self._halo_band
            C.memmove(self.canvas.bits.value + offset, band, len(band))
        with _Painter(self.canvas) as paint:
            self._halo(paint, item, plan["scale"], frame)
        return self.canvas

    @property
    def halo_plan(self):
        return self._halo_plan

    def _background(self, plan):
        """The ground, the card's shadow and the card: drawn once per size, then copied."""
        canvas = self.canvas
        card = plan["items"][0]
        key = (plan["size"], plan["card"], card["radius"], plan["scale"])
        if self._background_key == key and self._background_pixels is not None:
            C.memmove(canvas.bits, self._background_pixels, len(self._background_pixels))
            return
        with _Painter(canvas) as paint:
            paint.fill_round((0, 0, canvas.width, canvas.height), 0, argb("canvas"))
            self._card(paint, card["rect"], card["radius"], plan["scale"])
        self._background_pixels = canvas.pixels()
        self._background_key = key

    def _keep_halo_band(self, plan):
        canvas = self.canvas
        item = next((entry for entry in plan["items"] if entry["kind"] == "halo"), None)
        self._halo_plan = plan
        if item is None:
            self._halo_band = None
            return
        _dll("gdi32").GdiFlush()
        # The largest halo any state draws is 1.2 times its radius; leave room for the edge.
        reach = item["radius"] * 1.35 + 2 * plan["scale"] + 2
        top = max(0, int(item["cy"] - reach))
        bottom = min(canvas.height, int(math.ceil(item["cy"] + reach)))
        offset = top * canvas.width * 4
        self._halo_band = (offset, C.string_at(canvas.bits.value + offset, (bottom - top) * canvas.width * 4))

    def _shape(self, paint, item, scale, hover, pressed):
        kind = item["kind"]
        if kind == "panel":
            radius = brand.RADII["control"] * scale
            paint.fill_round(item["rect"], radius, argb("raised"))
            paint.stroke_round(item["rect"], radius, argb("line"), max(1.0, round(scale)))
        elif kind == "rule":
            paint.fill_round(item["rect"], 0, argb("line"))
        elif kind == "chip":
            rect = item["rect"]
            paint.fill_round(rect, (rect[3] - rect[1]) / 2.0, argb(item["tone"], CHIP_ALPHA))
        elif kind == "note":
            paint.fill_round(item["rect"], brand.RADII["small"] * scale, argb(item["tone"], CHIP_ALPHA))
        elif kind == "check":
            rect = item["rect"]
            radius = min(brand.RADII["small"], 16 / 4.0) * scale
            alpha = 0.5 if item["busy"] else 1.0
            if item["checked"]:
                paint.fill_round(rect, radius, argb("accent", alpha))
            else:
                paint.fill_round(rect, radius, argb("inset", alpha))
                edge = "accent" if hover == item["target"] else "line"
                paint.stroke_round(rect, radius, argb(edge, alpha), max(1.0, round(scale)))
        elif kind == "button":
            rect = item["rect"]
            radius = brand.RADII["control"] * scale
            alpha = 0.55 if item["busy"] else 1.0
            if item["primary"]:
                paint.fill_round(rect, radius, argb("accent", alpha))
            else:
                paint.fill_round(rect, radius, argb("inset" if hover == item["target"] else "raised", alpha))
                paint.stroke_round(rect, radius, argb("line", alpha), max(1.0, round(scale)))
            if not item["busy"] and item["target"] in (hover, pressed):
                shade = 0.16 if pressed == item["target"] else (0.08 if item["primary"] else 0.0)
                if shade:
                    paint.fill_round(rect, radius, argb("ink", shade))

    def _card(self, paint, rect, radius, scale):
        elevation = brand.ELEVATION
        offset = elevation["raised_offset"] * scale
        blur = elevation["raised_blur"] * scale
        steps = 7
        # A soft shadow as a stack of widening, fading rounded rectangles: GDI+ has no blur,
        # and at this size seven layers are indistinguishable from one.
        for step in range(steps, 0, -1):
            spread = blur * step / (2.0 * steps)
            alpha = elevation["shadow_opacity"] * 0.22 * (1.0 - step / (steps + 1.0)) ** 1.6
            grown = (rect[0] - spread + offset * 0.25, rect[1] - spread + offset,
                     rect[2] + spread + offset * 0.25, rect[3] + spread + offset)
            paint.fill_round(grown, radius + spread, argb("shadow_dark", alpha))
        # The highlight is a hint of light up and left, one step wide: any more reads as embossed.
        lift = max(1.0, offset / 4.0)
        lifted = (rect[0] - lift, rect[1] - lift, rect[2] - lift, rect[3] - lift)
        paint.fill_round(lifted, radius, argb("shadow_light", 0.45))
        paint.fill_round(rect, radius, argb("surface"))
        paint.stroke_round(rect, radius, argb("line"), max(1.0, round(scale)))

    def _halo(self, paint, item, scale, frame):
        colour = DOT_FILL.get(item["state"], "idle")
        cx, cy = item["cx"], item["cy"]
        if frame is not None:
            paint.fill_circle(cx, cy, item["radius"] * frame["scale"], argb(colour, frame["opacity"]))
        paint.fill_circle(cx, cy, 4.5 * scale, argb(colour))
        if frame is not None and frame.get("arc") is not None:
            paint.arc(cx, cy, item["radius"] - 1.5 * scale, frame["arc"], 100.0, argb("accent"),
                      max(1.5, 1.75 * scale))

    def _tick(self, paint, item, scale):
        left, top, right, bottom = item["rect"]
        size = right - left
        points = [(left + size * 0.27, top + size * 0.52), (left + size * 0.44, top + size * 0.69),
                  (left + size * 0.74, top + size * 0.34)]
        paint.lines(points, argb("on_accent", 0.5 if item["busy"] else 1.0), max(1.5, 1.8 * scale))

    def _text(self, dc, plan, busy):
        gdi32, user32 = _dll("gdi32"), _dll("user32")
        gdi32.SetBkMode(dc, 1)                                             # transparent
        original = None
        try:
            for item in plan["items"]:
                if item["kind"] != "text":
                    continue
                previous = gdi32.SelectObject(dc, self.fonts.handles[item["role"]])
                if original is None:
                    original = previous
                colour = item["colour"]
                if item.get("target") in busy and colour != "on_accent":
                    colour = "muted"
                gdi32.SetTextColor(dc, colorref(colour))
                flags = DT_NOPREFIX
                if item["wrap"]:
                    flags |= DT_WORDBREAK | DT_EDITCONTROL
                else:
                    flags |= DT_SINGLELINE | DT_VCENTER | DT_END_ELLIPSIS
                if item["align"] == "center":
                    flags |= DT_CENTER
                left, top, right, bottom = item["rect"]
                value = self.lines(item["role"], item["text"], right - left) if item["wrap"] else item["text"]
                rect = W.RECT(int(left), int(top), int(right), int(bottom))
                user32.DrawTextW(dc, value, -1, C.byref(rect), flags)
        finally:
            if original is not None:
                gdi32.SelectObject(dc, original)
            gdi32.GdiFlush()


# ------------------------------------------------------------------------ the icon badge
def badge_icon(base_icon, token):
    """A new HICON: `base_icon` with a dot in the colour `token`. The caller destroys it.

    Returns None when the base icon has no colour bitmap to draw on.
    """
    _declare()
    user32, gdi32 = _dll("user32"), _dll("gdi32")
    info = ICONINFO()
    if not base_icon or not user32.GetIconInfo(base_icon, C.byref(info)):
        return None
    colour_bitmap, mask_bitmap = info.hbmColor, info.hbmMask
    try:
        if not colour_bitmap:
            return None
        shape = BITMAP()
        if not gdi32.GetObjectW(colour_bitmap, C.sizeof(BITMAP), C.byref(shape)):
            return None
        width, height = shape.bmWidth, abs(shape.bmHeight)
        pixels = _read_pixels(colour_bitmap, width, height)
        if pixels is None:
            return None
        if not any(pixels[3::4]):
            # An icon without an alpha channel: its mask says what is transparent.
            mask = _read_pixels(mask_bitmap, width, height) if mask_bitmap else None
            for index in range(3, len(pixels), 4):
                pixels[index] = 0 if mask is not None and mask[index - 3] else 255
        composite_badge(pixels, width, height, brand.rgb(brand.LIGHT[token]))
        return _icon_from_pixels(pixels, width, height)
    finally:
        if colour_bitmap:
            gdi32.DeleteObject(colour_bitmap)
        if mask_bitmap:
            gdi32.DeleteObject(mask_bitmap)


def _bitmap_info(width, height):
    info = BITMAPINFO()
    info.bmiHeader.biSize = C.sizeof(BITMAPINFOHEADER)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    return info


def _read_pixels(bitmap, width, height):
    gdi32 = _dll("gdi32")
    dc = gdi32.CreateCompatibleDC(None)
    try:
        buffer = (C.c_ubyte * (width * height * 4))()
        info = _bitmap_info(width, height)
        if gdi32.GetDIBits(dc, bitmap, 0, height, buffer, C.byref(info), 0) != height:
            return None
        return bytearray(buffer)
    finally:
        gdi32.DeleteDC(dc)


def _icon_from_pixels(pixels, width, height):
    user32, gdi32 = _dll("user32"), _dll("gdi32")
    bits = C.c_void_p()
    info = _bitmap_info(width, height)
    colour = gdi32.CreateDIBSection(None, C.byref(info), 0, C.byref(bits), None, 0)
    if not colour:
        return None
    rows = ((width + 15) // 16) * 2
    zeros = (C.c_ubyte * (rows * height))()
    mask = gdi32.CreateBitmap(width, height, 1, 1, zeros)
    try:
        if not mask:
            return None
        C.memmove(bits, bytes(pixels), len(pixels))
        icon_info = ICONINFO()
        icon_info.fIcon = True
        icon_info.hbmMask = mask
        icon_info.hbmColor = colour
        return user32.CreateIconIndirect(C.byref(icon_info)) or None
    finally:
        gdi32.DeleteObject(colour)
        if mask:
            gdi32.DeleteObject(mask)


# ------------------------------------------------------------------------------ the window
class Popup:
    """The window itself. Created, shown, hidden and destroyed on the icon's thread only;
    `set_strings` is the one method another thread may call."""

    def __init__(self, *, control=None, source=None, strings=None, on_dashboard=None, log=None,
                 anchor=None):
        self.model = PopupModel(strings)
        self.locale = locale_of(strings)
        self.control = control
        self.source = source
        self.on_dashboard = on_dashboard
        self.log = log or (lambda *unused: None)
        self.anchor = anchor
        self.hwnd = None
        self.visible = False
        self._proc = None
        self._class = None
        self._renderer = None
        self._rounded = False
        self._pending_show = None
        self.hidden_at = None
        self._double_click_at = None
        self._key_at = None
        self.hover = self.pressed = self.focus = None
        self.keyboard = False
        self.dpi = 96
        self._vm = None
        self._plan = None
        self._screen = None
        self._lock = threading.Lock()
        self._results = {}
        self._sequence = itertools.count(1)
        self._reading = False
        self._read_again = False
        self._ticks = 0
        self._frame_running = False
        self._state = None
        self._state_since = time.monotonic()
        self._epoch = time.monotonic()
        self._reduced = False
        self._tracking = False
        self._strings = None
        self._static_dirty = True        # anything but the halo changed since the last frame
        self._origin = None

    # ------------------------------------------------------------------ lifecycle
    def create(self):
        _declare()
        user32, kernel32 = _dll("user32"), _dll("kernel32")
        instance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._wndproc)
        klass = WNDCLASSW()
        klass.style = CS_DROPSHADOW
        klass.lpfnWndProc = self._proc
        klass.hInstance = instance
        klass.hCursor = user32.LoadCursorW(None, C.c_void_p(IDC_ARROW))
        self._class = "CodexAutoResumePopup-%d-%d" % (os.getpid(), id(self))
        klass.lpszClassName = self._class
        if not user32.RegisterClassW(C.byref(klass)):
            self._class = None
            raise OSError("RegisterClassW")
        try:
            with _PerMonitorDpi():
                self.hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW | WS_EX_TOPMOST, self._class,
                                                   say(self.model.strings, "tray.title"), WS_POPUP,
                                                   0, 0, WIDTH, 120, None, None, instance, None)
            if not self.hwnd:
                raise OSError("CreateWindowExW")
            self._renderer = Renderer()
            self._round_corners()
            getter = getattr(user32, "GetDpiForWindow", None)
            self.dpi = (getter(self.hwnd) if getter is not None else 0) or 96
        except Exception:
            self.destroy()
            raise

    def destroy(self):
        user32 = _dll("user32")
        hwnd, self.hwnd = self.hwnd, None
        self.visible = False
        if hwnd:
            for timer in (TIMER_TICK, TIMER_FRAME, TIMER_FIRST):
                user32.KillTimer(hwnd, timer)
            user32.DestroyWindow(hwnd)
        self._frame_running = False
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._plan = self._vm = None
        self._static_dirty = True
        if self._class:
            user32.UnregisterClassW(self._class, _dll("kernel32").GetModuleHandleW(None))
            self._class = None

    def set_strings(self, strings):
        """Adopt a new vocabulary. Safe from any thread: applied on the next frame."""
        with self._lock:
            self._strings = dict(strings or {})
        hwnd = self.hwnd
        if hwnd:
            _dll("user32").PostMessageW(hwnd, WM_POPUP_STRINGS, 0, 0)

    def attention(self) -> bool:
        return self.model.attention()

    # ---------------------------------------------------------------- the icon asks
    def on_select(self, keyboard=False):
        now = time.monotonic()
        choice = select_action(self.visible or self._pending_show is not None, now,
                               hidden_at=self.hidden_at, double_click_at=self._double_click_at,
                               previous_key_at=self._key_at, keyboard=keyboard)
        if keyboard:
            self._key_at = now
        if choice == "show":
            self.show(keyboard=keyboard)
        elif choice == "hide":
            self.hide()

    def on_double_click(self):
        self._double_click_at = time.monotonic()
        if not self.visible and self._pending_show is None:
            self.show()

    def show(self, keyboard=False, activate=True, origin=None):
        if self.hwnd is None:
            self.create()
        self.keyboard = keyboard
        self.hover = self.pressed = None
        self.focus = None
        self._reduced = reduced_motion()
        self._request_read()
        if self.model.rows is None and self.model.status is None and self.control is not None:
            self._pending_show = (activate, origin)
            _dll("user32").SetTimer(self.hwnd, TIMER_FIRST, FIRST_READ_WAIT_MS, None)
            return
        self._present(activate, origin)

    def hide(self):
        self._pending_show = None
        hwnd = self.hwnd
        if not hwnd:
            return
        user32 = _dll("user32")
        for timer in (TIMER_TICK, TIMER_FRAME, TIMER_FIRST):
            user32.KillTimer(hwnd, timer)
        self._frame_running = False
        if self.visible:
            self.visible = False
            user32.ShowWindow(hwnd, SW_HIDE)
            self.hidden_at = time.monotonic()
        self.hover = self.pressed = self.focus = None

    # ------------------------------------------------------------------- presenting
    def _round_corners(self):
        try:
            value = C.c_int(DWMWCP_ROUND)
            dwm = _dll("dwmapi")
            _signature(dwm.DwmSetWindowAttribute, C.c_long, C.c_void_p, W.DWORD, C.c_void_p, W.DWORD)
            self._rounded = dwm.DwmSetWindowAttribute(self.hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                                      C.byref(value), C.sizeof(value)) == 0
        except Exception:
            self._rounded = False

    def _shape(self, width, height):
        if self._rounded:
            return
        radius = int(round(8 * self.dpi / 96.0)) * 2
        region = _dll("gdi32").CreateRoundRectRgn(0, 0, width + 1, height + 1, radius, radius)
        if region and not _dll("user32").SetWindowRgn(self.hwnd, region, True):
            _dll("gdi32").DeleteObject(region)            # only a region the system took is its own

    def _screen_now(self):
        user32 = _dll("user32")
        with _PerMonitorDpi():
            icon = self.anchor() if self.anchor else None
            point = W.POINT()
            user32.GetCursorPos(C.byref(point))
            cursor = (point.x, point.y)
            probe = W.RECT(*(icon or (cursor[0], cursor[1], cursor[0] + 1, cursor[1] + 1)))
            monitor = user32.MonitorFromRect(C.byref(probe), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = C.sizeof(MONITORINFO)
            user32.GetMonitorInfoW(monitor, C.byref(info))
            dpi = 0
            try:
                shcore = _dll("shcore")
                x, y = W.UINT(0), W.UINT(0)
                if shcore.GetDpiForMonitor(C.c_void_p(monitor), 0, C.byref(x), C.byref(y)) == 0:
                    dpi = x.value
            except Exception:
                dpi = 0
        work, whole = info.rcWork, info.rcMonitor
        return {"icon": icon, "cursor": cursor, "dpi": dpi or self.dpi or 96,
                "work": (work.left, work.top, work.right, work.bottom),
                "monitor": (whole.left, whole.top, whole.right, whole.bottom)}

    def _present(self, activate=True, origin=None):
        user32 = _dll("user32")
        self._pending_show = None
        user32.KillTimer(self.hwnd, TIMER_FIRST)
        self._screen = self._screen_now()
        self.dpi = self._screen["dpi"]
        plan = self._rebuild(time.time())
        if self.keyboard and self.focus is None:
            order = focus_order(plan["targets"])
            self.focus = order[0] if order else None
        self._move(plan, origin)
        self.visible = True
        user32.InvalidateRect(self.hwnd, None, False)
        user32.ShowWindow(self.hwnd, SW_SHOW if activate else SW_SHOWNOACTIVATE)
        if activate:
            user32.SetForegroundWindow(self.hwnd)
            user32.SetFocus(self.hwnd)
        user32.SetTimer(self.hwnd, TIMER_TICK, 1000, None)
        self._sync_frames()
        user32.UpdateWindow(self.hwnd)

    def _move(self, plan, origin=None):
        width, height = plan["size"]
        screen = self._screen
        if origin is not None:
            x, y = origin
        else:
            gap = int(round(brand.SPACING["m"] * self.dpi / 96.0))
            x, y, _ = place((width, height), screen["work"], screen["monitor"], screen["icon"],
                            screen["cursor"], gap=gap)
        self._origin = origin
        with _PerMonitorDpi():
            _dll("user32").SetWindowPos(self.hwnd, C.c_void_p(HWND_TOPMOST), x, y, width, height, SWP_NOACTIVATE)
        self._shape(width, height)

    def _rebuild(self, now):
        with self._lock:
            strings, self._strings = self._strings, None
        if strings is not None:
            self.model.strings = strings
            self.locale = locale_of(strings)
        vm = self.model.view(now)
        if vm["state"] != self._state:
            self._state = vm["state"]
            self._state_since = time.monotonic()
        plan = self._renderer.layout(vm, self.dpi / 96.0, self.locale)
        self._vm, self._plan = vm, plan
        self._static_dirty = True
        return plan

    def _update(self, now=None):
        if self.hwnd is None or self._renderer is None:
            return
        previous = self._plan["size"] if self._plan else None
        plan = self._rebuild(time.time() if now is None else now)
        if self.visible and plan["size"] != previous and self._screen is not None:
            self._move(plan, getattr(self, "_origin", None))
        order = focus_order(plan["targets"])
        if self.focus is not None and self.focus not in order:
            self.focus = order[0] if order and self.keyboard else None
        self._sync_frames()
        _dll("user32").InvalidateRect(self.hwnd, None, False)

    def _since_state_ms(self):
        return (time.monotonic() - self._state_since) * 1000.0

    def _sync_frames(self):
        user32 = _dll("user32")
        wanted = (self.visible and self._vm is not None
                  and animates(self._vm["state"], self._since_state_ms(), reduced=self._reduced))
        if wanted and not self._frame_running:
            user32.SetTimer(self.hwnd, TIMER_FRAME, FRAME_MS, None)
            self._frame_running = True
        elif not wanted and self._frame_running:
            user32.KillTimer(self.hwnd, TIMER_FRAME)
            self._frame_running = False

    def frame(self):
        """The halo for this instant."""
        if self._vm is None:
            return None
        return halo(self._vm["state"], (time.monotonic() - self._epoch) * 1000.0,
                    self._since_state_ms(), reduced=self._reduced)

    def render(self):
        """Draw the current view into the canvas and return it (the tests read it back)."""
        if self._plan is None:
            self._rebuild(time.time())
        if self._static_dirty or self._renderer.halo_plan is not self._plan:
            self._static_dirty = False
            return self._renderer.draw(self._vm, self._plan, frame=self.frame(), hover=self.hover,
                                       pressed=self.pressed, focus=self.focus if self.keyboard else None)
        return self._renderer.draw_halo(self._plan, self.frame())

    def _invalidate(self):
        """Something other than the halo changed: the next frame is drawn whole."""
        self._static_dirty = True
        if self.hwnd:
            _dll("user32").InvalidateRect(self.hwnd, None, False)

    # ---------------------------------------------------------------------- work
    def _request_read(self):
        if self.control is None:
            return
        if self._reading:
            self._read_again = True
            return
        self._reading = True
        self._run(("read",))

    def _run(self, action):
        number = next(self._sequence)
        control, source, dashboard = self.control, self.source, self.on_dashboard

        def work():
            outcome = perform(action, control, source=source, dashboard=dashboard)
            with self._lock:
                self._results[number] = (action, outcome)
            hwnd = self.hwnd
            if hwnd:
                _dll("user32").PostMessageW(hwnd, WM_POPUP_RESULT, number, 0)

        threading.Thread(target=work, name="tray-popup-call", daemon=True).start()

    def _finished(self, number):
        with self._lock:
            action, outcome = self._results.pop(number, (None, None))
        if action is None:
            return
        if outcome[0] == "failed":
            self.log("tray popup %s failed (%s)" % (action[0], outcome[1]))
        self.model.apply_outcome(action, outcome, time.time())
        showing = self.visible or self._pending_show is not None
        if action[0] == "read":
            self._reading = False
            if self._read_again:
                self._read_again = False
                self.model.wants_read = True
        if self.model.wants_read:
            self.model.wants_read = False
            # A hidden window reads nothing; the next opening reads anyway.
            if showing:
                self._request_read()
        if self._pending_show is not None and action[0] == "read":
            self._present(*self._pending_show)
        elif self.visible:
            self._update()

    def _activate(self, target):
        action = self.model.action_for(target)
        if action is None:
            return
        if action[0] == "dashboard":
            self.hide()
            self._run(action)
            return
        if not self.model.begin(action):
            return
        self._run(action)
        self._update()

    # --------------------------------------------------------------------- messages
    def _wndproc(self, hwnd, message, wparam, lparam):
        try:
            handled = self._handle(hwnd, message, wparam, lparam)
            if handled is not None:
                return handled
        except Exception as exc:              # the popup must never take the watcher down
            self.log("tray popup message failed (%s)" % type(exc).__name__)
        return _dll("user32").DefWindowProcW(hwnd, message, wparam, lparam)

    def _handle(self, hwnd, message, wparam, lparam):
        user32 = _dll("user32")
        if message == WM_PAINT:
            self._paint(hwnd)
            return 0
        if message == WM_ERASEBKGND:
            return 1
        if message == WM_TIMER:
            if wparam == TIMER_FRAME:
                self._sync_frames()
                user32.InvalidateRect(hwnd, None, False)
            elif wparam == TIMER_TICK:
                self._ticks += 1
                if self._ticks % REFRESH_TICKS == 0:
                    self._request_read()
                self._update()
            elif wparam == TIMER_FIRST and self._pending_show is not None:
                self._present(*self._pending_show)
            return 0
        if message == WM_POPUP_RESULT:
            self._finished(wparam)
            return 0
        if message == WM_POPUP_STRINGS:
            if self.visible:
                self._update()
            return 0
        if message == WM_ACTIVATE:
            if (wparam & 0xFFFF) == WA_INACTIVE:
                if self.visible:
                    self.hide()                  # a click anywhere else closes it
                return 0
            return None                          # activated: let Windows give it the keyboard
        if message == WM_CLOSE:
            self.hide()
            return 0
        if message == WM_KEYDOWN:
            return self._key(wparam)
        if message == WM_MOUSEMOVE:
            self._mouse_move(hwnd, lparam)
            return 0
        if message == WM_MOUSELEAVE:
            self._tracking = False
            if self.hover is not None:
                self.hover = None
                self._invalidate()
            return 0
        if message == WM_LBUTTONDOWN:
            self.keyboard = False
            self.pressed = self._hit(lparam)
            self._invalidate()
            return 0
        if message == WM_LBUTTONUP:
            target, pressed = self._hit(lparam), self.pressed
            self.pressed = None
            if target is not None and target == pressed:
                self._activate(target)
            self._invalidate()
            return 0
        if message == WM_DPICHANGED:
            dpi = wparam & 0xFFFF
            if dpi and dpi != self.dpi:
                self.dpi = dpi
                if self.visible:
                    # The scale changed under an open window: measure the screen again and
                    # put it back beside the icon at its new size, not where Windows guessed.
                    self._screen = self._screen_now()
                    self._screen["dpi"] = dpi
                    self._move(self._rebuild(time.time()), self._origin)
                    self._invalidate()
            return 0
        if message == WM_SETTINGCHANGE:
            self._reduced = reduced_motion()
            self._sync_frames()
            return None
        return None

    def _paint(self, hwnd):
        user32 = _dll("user32")
        paint = PAINTSTRUCT()
        dc = user32.BeginPaint(hwnd, C.byref(paint))
        try:
            if dc and self._renderer is not None and (self._plan is not None or self.visible):
                canvas = self.render()
                _dll("gdi32").SetDIBitsToDevice(dc, 0, 0, canvas.width, canvas.height, 0, 0, 0,
                                                canvas.height, canvas.bits, C.byref(canvas.info), 0)
        finally:
            user32.EndPaint(hwnd, C.byref(paint))

    def _hit(self, lparam):
        if self._plan is None:
            return None
        x = C.c_short(lparam & 0xFFFF).value
        y = C.c_short((lparam >> 16) & 0xFFFF).value
        return hit_test(self._plan["targets"], x, y)

    def _mouse_move(self, hwnd, lparam):
        user32 = _dll("user32")
        target = self._hit(lparam)
        if target != self.hover:
            self.hover = target
            self._invalidate()
        if not self._tracking:
            track = TRACKMOUSEEVENT()
            track.cbSize = C.sizeof(TRACKMOUSEEVENT)
            track.dwFlags = TME_LEAVE
            track.hwndTrack = hwnd
            self._tracking = bool(user32.TrackMouseEvent(C.byref(track)))

    def _key(self, key):
        user32 = _dll("user32")
        if key == VK_ESCAPE:
            self.hide()
            return 0
        if key in (VK_TAB, VK_UP, VK_DOWN) and self._plan is not None:
            backwards = key == VK_UP or (key == VK_TAB and user32.GetKeyState(VK_SHIFT) < 0)
            self.keyboard = True
            self.focus = next_focus(focus_order(self._plan["targets"]), self.focus, backwards)
            self._invalidate()
            return 0
        if key in (VK_SPACE, VK_RETURN) and self.focus is not None:
            self._activate(self.focus)
            return 0
        return None
