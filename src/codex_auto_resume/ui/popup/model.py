"""What the popup is showing, worked out from what the watcher said.

The rows, their order, the word for what is happening, and what a click on each does. All of it
is a pure function of the snapshot: the same snapshot makes the same view, which is what lets
the documentation's pictures be taken without a running watcher.
"""
from __future__ import annotations

import time
from ... import machine
from ... import reasons
from ..words import countdown
from .words import one_line, say


MAX_TASKS = 3


NOTICE_SECONDS = 4.0


CLICK_AWAY_SECONDS = 0.5     # a click on the icon that closed the window does not reopen it


DOUBLE_CLICK_SECONDS = 0.6


KEY_REPEAT_SECONDS = 0.3     # Enter on the icon arrives twice


# The whole of what this window may ask of the control layer.
CONTROL_CALLS = ("list_pending", "get_status", "set_enabled", "set_interruption_recovery")


# The refusals that mean "the row you clicked is no longer the record it was drawn from".
STALE_CODES = frozenset({"no_such_interruption", "thread_mismatch", "already_finished"})


STATES = ("monitoring", "waiting", "checking", "recovering", "paused", "attention")


# Circumstances under which nothing will recover until a person does something.
ATTENTION_OVERLAYS = frozenset({"compatibility_blocked", "compatibility_failed_here", "engine_unavailable", "watcher_not_ticking"})


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
            or watcher.get("engine_state") in ("incompatible", "failed_here")
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
    """The same word from the icon's own tick snapshot, for the icon's state (tray.icon_state)."""
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
