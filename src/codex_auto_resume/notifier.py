"""One notification, built once, shown one way: the product's card or today's Windows toast.

v0.6.5 adds a second way to *show* a notification the watcher already raises - the product's
own card beside the notification area (`notice_card.py`, `notice_window.py`). It changes no
wording, no privacy claim, no notification policy and nothing about recovery. This module is
the half that runs off the icon's thread:

    build(event, detail, identity)  the one builder: an engine event -> a Notice
    deliver(notice, ...)            hand it to the card, or raise today's toast
    complete(notice, shown)         how a notice the card took ends: its silent history copy
                                    once the card was seen, else today's toast after all
    Inbox                           hands a Notice from any thread to the icon's thread
    activate(uri, ...)              a card button, done in process: cancel one, or open a page

**One builder, one set of words.** A `Notice` carries the toast's own content - the exact
arguments `notify.show` has always been given, built by `notify.*_content` - and the card's
view of the same lines. The card's buttons *are* the toast's buttons, as data: (label, URI)
pairs, so "the card offers exactly what the toast offers" is an equality, not a promise. The
card shows the toast's three lines and nothing else, plus the product's name, a status light
and - for a detected interruption - the reason's label, which is a catalog word.

**Exactly one route.** `deliver` either hands the notice to the card, or raises today's toast
exactly as before. The card is chosen only when `notice_presence.card_allowed` says so and the
icon's thread accepted the notice; anything else - the setting off, no icon, Do not disturb,
this app's notifications switched off in Windows, full screen, a locked or remote session, a
screen reader, an icon thread that did not answer - is the toast, byte for byte.

A notice the card took is then ended by its host exactly once, through `complete`: when the
card has been on screen whole, the same toast is raised silently (`SuppressPopup`, no sound: it
goes straight to Windows' notification center, so the history is the same either way); when the
card could not be drawn, or its host went away before it was seen, today's toast is raised
instead. The history copy waits for the card on purpose - raised any earlier, a card that then
failed would leave two copies in the notification center, or none on the screen.

**Nothing here can recover anything.** A card button reaches `activate`, which does in process
what `cli.cmd_activate` does for a toast button: the URI is parsed by the same two parsers, a
page must be one of the window's own, and the only change it can make is to *cancel* one exact
interruption through the control layer, with the actor the toast has always used ("toast").
"""
from __future__ import annotations

import collections
from dataclasses import dataclass
import threading

from . import l10n, messages, notice_presence, notify, reasons

# The setting that turns the card off (settings.py, the "windows" group, default on).
CARD_SETTING = "notification_card"

# What each kind of notice is called and which brand status light it wears. The light is the
# brand's own vocabulary (brand.STATUS_FILL); only the card draws it, the toast has none.
STATUS = {
    "interruption": "waiting",      # detected, and it will be recovered
    "starting": "recovering",       # a continuation is being sent now
    "resumed": "monitoring",        # delivery proven: running again
    "failed": "failed",             # the attempt did not go through
    "unknown": "attention",         # it may have gone through; nothing is resent
    "stopped": "attention",         # recovery stopped for good
    "cancelled": "paused",          # a person switched it off
}
PROBES = ("notification_state", "notification_mode", "app_notifications", "screen_reader",
          "remote_session", "session_locked")


@dataclass(frozen=True)
class Notice:
    """One notification as data. Built by `build` or `build_cancelled`, never by a surface.

    `title`, `line` and `origin` are the toast's three lines in the order Windows draws them;
    `chip` is the reason's catalog label (a detected interruption only) and `chip_tone` its
    colour token; `actions` are the toast's buttons, (label, URI) pairs; `content` is the toast
    itself - the arguments `notify.show` receives - as sorted (name, value) pairs; `key` is the
    exact conversation id, so a newer card for the same conversation replaces the older one.
    """
    kind: str
    status: str
    title: str
    line: str
    origin: str
    chip: str | None
    chip_tone: str | None
    actions: tuple
    content: tuple
    locale: str
    key: str | None = None

    def toast_content(self) -> dict:
        """The toast, as `notify.show_content` takes it."""
        content = {}
        for name, value in self.content:
            if name == "extra":
                value = list(value)
            elif name == "more":
                value = [tuple(pair) for pair in value]
            content[name] = value
        return content


def _frozen(content: dict) -> tuple:
    frozen = []
    for name in sorted(content):
        value = content[name]
        if name == "extra":
            value = tuple(value)
        elif name == "more":
            value = tuple(tuple(pair) for pair in value)
        frozen.append((name, value))
    return tuple(frozen)


def toast_actions(content: dict) -> tuple:
    """The buttons a toast with this content shows, as `notify._toast_xml` lays them out."""
    button, uri = content.get("button"), content.get("uri")
    pairs = ([(button, uri)] if button and uri else []) + [
        (label, target) for label, target in content.get("more") or () if label and target]
    return tuple(tuple(pair) for pair in pairs[:notify.MAX_TOAST_ACTIONS])


def _notice(kind, content, *, key, chip=None, chip_tone=None, line=None) -> Notice:
    extra = list(content.get("extra") or ())
    return Notice(kind=kind, status=STATUS[kind], title=content["title"],
                  line=line if line is not None else (extra[0] if extra else ""),
                  origin=content["body"], chip=chip, chip_tone=chip_tone,
                  actions=toast_actions(content), content=_frozen(content),
                  locale=messages.language(), key=key)


def build(event, detail, identity=None):
    """The Notice for one engine event, or None for an event that is never announced.

    The same mapping `app.App._notifier` has made since v0.6.0, event for event, now in one
    place: an interruption, a continuation starting, a result (proven, failed or uncertain)
    and a stop. `identity` is the display labels the source found for the conversation, or
    None; the exact thread id is always the one in `detail`.
    """
    detail = detail if isinstance(detail, dict) else {}
    thread_id = detail.get("thread_id")
    state = detail.get("state")
    if event == "interruption":
        category = detail.get("category") or "usage_limit"
        content = notify.scheduled_content(thread_id, detail.get("interruption_id"),
                                           detail.get("reset_at"), category, identity)
        # The card names the reason in its chip, so its line is the sentence without the label
        # the toast has to put in front of it. Both are words the toast already says.
        line = None if category == "usage_limit" else messages.text("toast_transient")
        chip = l10n.text(reasons.label_key(category), messages.language())
        return _notice("interruption", content, key=thread_id, chip=chip, chip_tone="waiting", line=line)
    if event == "starting":
        return _notice("starting", notify.starting_content(thread_id, identity), key=thread_id)
    if event == "result":
        if state in ("turn_started", "resumed"):
            return _notice("resumed", notify.resumed_content(thread_id, identity), key=thread_id)
        # A failed attempt is final, and an uncertain submission is never resent: neither is
        # ever described as something that will be retried.
        certain = state != "submission_unknown"
        return _notice("failed" if certain else "unknown",
                       notify.attempt_failed_content(thread_id, identity, certain=certain), key=thread_id)
    if event == "stopped":
        reason = ("no_progress" if state == "no_progress_exhausted"
                  else "attempts" if state == "retry_budget_exhausted" else None)
        return _notice("stopped", notify.stopped_content(thread_id, identity, reason=reason), key=thread_id)
    return None


def build_cancelled(thread_id) -> Notice:
    """What a cancel from a notification button says afterwards, as `notify.cancelled` does."""
    return _notice("cancelled", notify.cancelled_content(thread_id), key=thread_id)


# --------------------------------------------------------------------------- the handover
class Inbox:
    """Notices on their way from any thread to the card host on the icon's thread.

    The icon's thread owns every window it draws, so nothing else may touch the card. A
    notice is put here and the host is woken - `wake` posts one message to a window on the
    icon's thread, which then calls `take`. `post` says whether the host has it: False when
    no host is attached, when it has fallen `LIMIT` notices behind, or when it could not be
    woken, and the caller then raises the toast instead. Nothing waits on the icon's thread.
    A notice `post` accepted is the host's to end (`complete`), including when the host goes
    away before taking it: `detach` hands those back rather than dropping them.
    """

    LIMIT = 8

    def __init__(self):
        self._lock = threading.Lock()
        self._waiting = collections.deque()
        self._wake = None

    def attach(self, wake) -> None:
        """Called on the icon's thread once its host window exists. `wake()` returns a bool."""
        with self._lock:
            self._wake = wake

    def detach(self) -> list:
        """The host is going away: nothing more is accepted, and what was waiting - accepted,
        never taken - is handed back, oldest first, for the host to end as today's toast."""
        with self._lock:
            self._wake = None
            left = list(self._waiting)
            self._waiting.clear()
        return left

    @property
    def attached(self) -> bool:
        return self._wake is not None

    def post(self, notice) -> bool:
        with self._lock:
            wake = self._wake
            if wake is None or len(self._waiting) >= self.LIMIT:
                return False
            self._waiting.append(notice)
        try:
            woken = bool(wake())
        except Exception:
            woken = False
        if woken:
            return True
        with self._lock:
            try:
                self._waiting.remove(notice)
            except ValueError:
                return True            # the host took it anyway, woken by an earlier message
        return False

    def take(self) -> list:
        """Everything posted since the last call, oldest first. Called on the icon's thread."""
        with self._lock:
            taken = list(self._waiting)
            self._waiting.clear()
        return taken


def _presence() -> dict:
    """What Windows says now, asked about the identity the toast is raised under."""
    return notice_presence.snapshot(notify.aumid())


def deliver(notice, *, inbox=None, setting=True, probe=None, show=notify.show_content):
    """Show one notice by exactly one route. Returns (route, shown): route "card" or "toast".

    Card: the host accepted it (`shown` is True) and will end it with `complete` - the silent
    history copy once the card has been seen, or today's toast if it never could be. Toast:
    today's toast, exactly as `notify` has always raised it. The presence probes are only read
    when the card is possible at all. Called on the notifications thread, never on the tick path
    and never on the icon's thread (raising a toast runs PowerShell).
    """
    allowed = False
    if setting is True and inbox is not None and inbox.attached:
        try:
            answers = dict((probe or _presence)() or {})
        except Exception:
            answers = {}
        allowed = notice_presence.card_allowed(setting=True, tray_present=True,
                                               **{name: answers.get(name) for name in PROBES})
    if allowed and inbox.post(notice):
        return "card", True
    return "toast", bool(show(notice.toast_content()))


def complete(notice, card_shown, *, show=notify.show_content) -> bool:
    """End a notice the card took, once its host knows how it went. Called once per notice.

    `card_shown` True: the card was on screen whole (or was clicked, or a newer card about the
    same conversation took its place) - the same toast is raised silently, for Windows'
    notification center only. Anything else: the card could not be drawn, had no room, or its
    host went away before it was seen - today's toast is raised instead, exactly as the toast
    route raises it. Either way the notification center ends up with the notice once. Runs
    PowerShell: a worker thread's job.
    """
    content = notice.toast_content()
    if card_shown is True:
        return bool(show(content, silent=True))
    return bool(show(content))


# ------------------------------------------------------------------------- the buttons
def activate(uri, *, control=None, open_dashboard=None, announce=None) -> str:
    """Do what a card button's URI asks, in process. Returns what happened, as one word.

    "opened" / "not_installed"  an open URI: `open_dashboard(page)` for one of the window's pages
    "cancelled"                  a cancel URI: that one interruption, through the control layer
    "refused" / "failed"         the control layer said no (a coded refusal) or broke
    "ignored"                    anything else, including every malformed URI

    Called on a worker thread by the card's host: cancelling may wait for a busy store. After a
    cancel, `announce(notice)` is given the notice `notify.cancelled` would have raised.
    """
    page = notify.parse_open_uri(uri)
    if page is not None:
        if open_dashboard is None:
            return "not_installed"
        try:
            return "opened" if open_dashboard(page) else "not_installed"
        except Exception:
            return "failed"
    interruption_id = notify.parse_cancel_uri(uri)
    if interruption_id is None or control is None:
        return "ignored"
    try:
        result = control.cancel_interruption(interruption_id, actor="toast")
    except Exception as exc:
        code = getattr(exc, "code", None)
        return "refused" if isinstance(code, str) and code else "failed"
    thread_id = (result or {}).get("thread_id")
    if announce is not None and thread_id:
        try:
            announce(build_cancelled(thread_id))
        except Exception:
            pass
    return "cancelled"
