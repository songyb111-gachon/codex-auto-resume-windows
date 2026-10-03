"""Optional Windows toast shown when an interruption is recorded.

This is the only moment a control can be offered at the time it matters: the watcher
is running when the interruption is detected, whereas the Codex turn has already failed
by then, so nothing can be added to the app's own usage-limit notice.

The toast carries one button that opts this conversation out. Doing nothing resumes,
which is the default. Delivery is best effort: a notification that cannot be shown must
never change whether a resume happens.

Nothing about the interrupted work is disclosed. The toast contains only a shortened
conversation id and a local time - never prompt text, error text or account data.

Since v0.6.5 every toast's content is built by a pure function (`*_content`), so the same
lines can also be drawn as the product's own notification card (`notifier.py`,
`notice_card.py`). When the card is shown the toast is still raised, `silent=True`, so
Windows keeps it in its notification center for history, without a banner or a sound.
"""
from __future__ import annotations

import subprocess
import time

from . import l10n, machine, needsyou, pwsh
from .domain import ids

SCHEME = "codex-auto-resume"
# The toast is sent under our own AppUserModelID, so Windows attributes it to
# "Codex Auto Resume" instead of to whatever process raised it. Measured on Windows 11:
# an unpackaged application may claim an AUMID, and delivery succeeds even before the
# identity is registered - registration supplies the display name and icon, not the
# ability to notify. A missing registration therefore degrades to an unnamed sender,
# never to a lost notification.
LEGACY_POWERSHELL_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def aumid() -> str:
    # Imported lazily: startup.py owns every per-user registration, and importing it at
    # module load would drag the registry into processes that only format a message.
    from .startup import AUMID
    return AUMID
TIMEOUT_SECONDS = 20

_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($env:CODEX_AUTO_RESUME_ARG_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
if ($env:CODEX_AUTO_RESUME_ARG_SILENT -eq '1') { $toast.SuppressPopup = $true }
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:CODEX_AUTO_RESUME_ARG_AUMID).Show($toast)
"""


def cancel_uri(interruption_id: str) -> str:
    """Capability URI for one interruption.

    The interruption id is an unguessable local identifier, so a page that merely knows
    the scheme cannot target a real record. The only action it can ever perform is
    *cancelling* a resume, which fails in the safe direction.
    """
    return "%s:cancel?i=%s" % (SCHEME, interruption_id)


def parse_cancel_uri(uri: str) -> str | None:
    """Return the interruption id, or None when the URI is not a valid cancel request."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    # Windows may hand the URI over as "codex-auto-resume:cancel?..." (opaque path).
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "cancel":
        return None
    values = parse_qs(parts.query).get("i") or []
    if len(values) != 1:
        return None
    return ids.read_interruption_id(values[0])


def open_uri(page: str = "pending") -> str:
    """Capability URI that opens one page of the Dashboard.

    Like cancelling, it cannot make anything happen that should not: it names a page
    from a closed list, it changes no state, and a hostile page that knows the scheme can
    at worst open a window.
    """
    return "%s:open?page=%s" % (SCHEME, page)


def parse_open_uri(uri: str) -> str | None:
    """Return the page, or None when the URI is not a valid open request."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "open":
        return None
    values = parse_qs(parts.query).get("page") or []
    if len(values) != 1:
        return None
    page = values[0].strip().lower()
    # The same closed list the icon uses, from where both can read it without importing the
    # other's window code.
    return page if page in machine.PAGES else None


def power_stop_uri(nonce: str) -> str:
    """Capability URI that stops the power action for one batch (v0.6.12, the A28 amendment).

    The nonce names the batch: 16 hex digits, new at every arming and at every batch's end, so a page
    that merely knows the scheme cannot name one, and a notice of a batch that is over - still in the
    notification center - stops nothing. Like cancelling, it can only take automation away: the PC
    stays on this time.
    """
    return "%s:power-stop?n=%s" % (SCHEME, nonce)


def parse_power_stop_uri(uri: str) -> str | None:
    """Return the batch's nonce, or None when the URI is not a valid power-stop request: exactly one
    `n` of 16 lowercase hex digits."""
    from urllib.parse import parse_qs, urlsplit

    try:
        parts = urlsplit(str(uri))
    except (ValueError, TypeError):
        return None
    if parts.scheme.lower() != SCHEME:
        return None
    action = (parts.path or parts.netloc or "").strip("/").lower()
    if action != "power-stop":
        return None
    values = parse_qs(parts.query, keep_blank_values=True).get("n") or []
    if len(values) != 1 or set(parse_qs(parts.query, keep_blank_values=True)) != {"n"}:
        return None
    return values[0] if ids.is_power_nonce(values[0]) else None


# Windows shows at most five buttons on a toast. This product never needs more than two.
MAX_TOAST_ACTIONS = 5


# v0.6.11: a needs-you notice's sound, only when a person chose one: Windows' own reminder sound, named
# by the toast's own audio element - so it is Windows that plays it, and Windows' Do not disturb and
# Focus that hold it back with the toast. Otherwise a needs-you toast is silent; no other toast changes.
NEEDS_YOU_SOUND = "ms-winsoundevent:Notification.Reminder"


def _audio(silent, sound) -> str:
    """The toast's audio element: none (Windows' default, every toast but the two below), silent (the
    history copy, and a needs-you notice without a sound), or the needs-you sound a person chose."""
    if silent or sound is False:
        return '<audio silent="true"/>'
    return '<audio src="%s"/>' % NEEDS_YOU_SOUND if sound is True else ""


def _toast_xml(title, body, button=None, uri=None, extra=(), more=(), silent=False, sound=None) -> str:
    # Imported when a toast is built, not when this module is: `xml.sax` brings about
    # ninety modules with it, `urllib.request`, `http.client`, `email` and `ssl` among
    # them, and every process that imports the watcher paid for them whether or not it
    # ever showed a notification.
    from xml.sax.saxutils import escape, quoteattr

    pairs = ([(button, uri)] if button and uri else []) + [
        (label, target) for label, target in more if label and target]
    actions = ""
    if pairs:
        actions = "<actions>%s</actions>" % "".join(
            '<action content=%s activationType="protocol" arguments=%s/>' % (
                quoteattr(label), quoteattr(target))
            for label, target in pairs[:MAX_TOAST_ACTIONS])
    # Trimmed here rather than at the call sites, so no future caller can silently
    # lose a line to the platform limit.
    lines = [line for line in ([title] + list(extra) + [body]) if line][:MAX_TOAST_LINES]
    text = "".join("<text>%s</text>" % escape(line) for line in lines)
    # The history copy (`silent`) makes no sound. Without it the document is byte for byte
    # what it was before v0.6.5; tests/test_notice_card.py holds every toast to a golden.
    audio = _audio(silent, sound)
    return ('<toast duration="long"><visual><binding template="ToastGeneric">'
            '%s</binding></visual>%s%s</toast>' % (text, audio, actions))


def show(title: str, body: str, *, button: str | None = None, uri: str | None = None,
         extra=(), more=(), silent: bool = False, sound: bool | None = None) -> bool:
    """Best effort. Returns True only when PowerShell reported success.

    The toast document travels as an environment variable into a constant script, never
    as script text: a title is whatever Codex named the conversation and a project is a
    folder name, and neither may be able to change what PowerShell runs. See pwsh.py.

    `silent=True` is the copy kept for history while the notification card is on screen:
    Windows files it straight into its notification center (`SuppressPopup`) and it plays
    no sound (`<audio silent="true"/>`). Checked on Windows 11 build 26200: a toast with
    SuppressPopup set is in `ToastNotificationManager.History` a moment after `Show`. The
    default is exactly the toast this function always raised.
    """
    if pwsh.executable() is None:
        return False
    values = {"XML": _toast_xml(title, body, button, uri, extra, more, silent=silent is True,
                                sound=sound if isinstance(sound, bool) else None),
              "AUMID": aumid()}
    if silent is True:
        values["SILENT"] = "1"
    try:
        code = pwsh.run(_SCRIPT, values, timeout=TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError, pwsh.PowerShellError):
        return False
    return code == 0


def _local_time(when: float) -> str:
    return time.strftime("%H:%M", time.localtime(when))


def headline(identity) -> str:
    """The first line: what a person would call this task.

    Priority is title, then project, then the working directory's name. These are
    display labels only. Recovery never looks a thread up by any of them; the exact
    UUID stays the sole identity, and it is shown on its own line as well.
    """
    identity = identity if isinstance(identity, dict) else {}
    for key in ("name", "project", "cwd_basename"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return l10n.message("toast_unnamed")


# Windows renders at most three <text> elements in a ToastGeneric binding; a fourth is
# silently dropped. Measured on Windows 11 with a four-line toast, where the body line
# - the whole reason for the notification - never appeared. Everything therefore has to
# fit in exactly three: name, reason, then origin and the exact thread id.
MAX_TOAST_LINES = 3


def _second_line(identity, used: str):
    identity = identity if isinstance(identity, dict) else {}
    for key in ("project", "cwd_basename"):
        value = identity.get(key)
        if isinstance(value, str) and value.strip() and value.strip() != used:
            return value.strip()
    return None


def _origin_line(identity, used: str, thread_id: str) -> str:
    """The last line: where this task lives, and which conversation it is exactly.

    The thread id shares a line with the project because a separate line for it would
    be a fourth, and Windows would drop one. It is never omitted.
    """
    thread = _thread_line(thread_id)
    secondary = _second_line(identity, used)
    return (_run(secondary) + "  ·  " + thread) if secondary else thread


def _run(value) -> str:
    """A name or an id kept one run in a line of a right-to-left language (l10n.embedded, v0.6.11): an id's
    groups and a project named in another direction stay in their own order. Itself in any other language."""
    return l10n.embedded(value, l10n.current())


def _thread_line(thread_id: str) -> str:
    return l10n.message("toast_thread").format(uuid=_run(thread_id))


def _content(title, body, *, button=None, uri=None, extra=(), more=(), sound=None) -> dict:
    """What one toast says, as the arguments `show` takes. Only what was given is kept, so
    `show_content` passes `show` exactly the keywords each toast always passed. `sound` (v0.6.11) is a
    needs-you notice's alone, and every other toast leaves it out."""
    content = {"title": title, "body": body}
    for name, value in (("button", button), ("uri", uri), ("extra", list(extra)), ("more", list(more))):
        if value:
            content[name] = value
    if isinstance(sound, bool):
        content["sound"] = sound
    return content


def show_content(content: dict, *, silent: bool = False) -> bool:
    """Raise the toast one of the `*_content` functions describes."""
    options = {name: content[name] for name in ("button", "uri", "extra", "more", "sound") if name in content}
    if silent is True:
        options["silent"] = True
    return show(content["title"], content["body"], **options)


# v0.6.11: what the detection notice says of an interruption its conversation holds for a person
# (machine.hold_for_tier) - never that it will resume - and what the objection window's says.
HELD_MESSAGES = {"ask": "toast_held", "notify_only": "toast_notify_only",
                 # v0.6.11: the two guards' holds (guards.py), said as what changed or grew.
                 "workspace_changed": "toast_workspace_changed", "context_cost": "toast_context_cost"}


def held_message(hold) -> str:
    """The sentence for an interruption that waits for a person, by the kind of hold it has."""
    return l10n.message(HELD_MESSAGES.get(hold, "toast_held"))


def _reason_label(category) -> str:
    from . import reasons
    return l10n.text(reasons.label_key(category), l10n.current())


def _cancel_button(category) -> str:
    return l10n.message("toast_button_cancel" if category == "usage_limit" else "toast_button_no_retry")


def scheduled_content(thread_id: str, interruption_id: str, reset_at: float | None,
                      category: str = "usage_limit", identity=None, hold=None) -> dict:
    """The detection toast's content. See `scheduled`.

    `hold` (v0.6.11) is the hold the conversation's tier put on it, or None - at the defaults,
    always. A held interruption is said to wait for the person, under its reason, and keeps the
    same two buttons: Don't resume, and the Dashboard, where it is let continue."""
    usage = category == "usage_limit"
    title = headline(identity)
    if hold is not None:
        return _content(title, _origin_line(identity, title, thread_id),
                        button=_cancel_button(category), uri=cancel_uri(interruption_id),
                        extra=[_reason_label(category) + " · " + held_message(hold)],
                        more=[(l10n.message("toast_button_open"), open_uri("pending"))])
    if usage:
        body = (l10n.message("toast_usage_at").format(time=_local_time(reset_at)) if reset_at
                else l10n.message("toast_usage_soon"))
        button = l10n.message("toast_button_cancel")
    else:
        # The reason, named. "Temporary rate limit" and "server error" are different things
        # to the person reading, and the classifier already knows which one this was. The
        # label is the normalised one from the reason registry - never the error text.
        from . import reasons
        label = l10n.text(reasons.label_key(category), l10n.current())
        body = label + " · " + l10n.message("toast_transient")
        button = l10n.message("toast_button_no_retry")
    # Order matters: the reason must come before the identifiers, because a line that
    # does not fit is lost and losing the reason makes the notification pointless.
    return _content(title, _origin_line(identity, title, thread_id),
                    button=button, uri=cancel_uri(interruption_id), extra=[body],
                    more=[(l10n.message("toast_button_open"), open_uri("pending"))])


def scheduled(thread_id: str, interruption_id: str, reset_at: float | None,
              category: str = "usage_limit", identity=None) -> bool:
    """Announce that this conversation will be recovered, and offer to opt out.

    Wording follows the failure category: a usage limit waits for a reset, everything
    else is simply retried. Both carry the same single cancel button.
    """
    return show_content(scheduled_content(thread_id, interruption_id, reset_at, category, identity))


def objection_message(until) -> str:
    """The objection window's sentence: when the continuation goes, unless it is stopped."""
    return l10n.message("toast_objection").format(time=_local_time(until))


def objection_content(thread_id: str, interruption_id: str, until: float,
                      category: str = "usage_limit", identity=None) -> dict:
    """The objection window's content (v0.6.11): the continuation is sent at `until` unless the
    person stops it. The detection notice's two buttons and no other - Don't resume, and the
    Dashboard - so a button still cannot make anything be sent (A28)."""
    title = headline(identity)
    return _content(title, _origin_line(identity, title, thread_id),
                    button=_cancel_button(category), uri=cancel_uri(interruption_id),
                    extra=[_reason_label(category) + " · " + objection_message(until)],
                    more=[(l10n.message("toast_button_open"), open_uri("pending"))])


def cancelled_content(thread_id: str) -> dict:
    return _content(l10n.message("toast_cancelled_title"),
                    _thread_line(thread_id),
                    extra=[l10n.message("toast_cancelled_body")])


def cancelled(thread_id: str) -> bool:
    return show_content(cancelled_content(thread_id))


# --------------------------------------------------------------- lifecycle toasts
# Everything below announces something the watcher has already decided. A toast is
# never a prompt for permission and never gates recovery: `show` returning False costs
# a message, never an attempt. Only the detection toast carries a button, because
# cancelling is the one action that fails in the safe direction.

def starting_content(thread_id: str, identity=None, *, task_changed: bool = False) -> dict:
    """A continuation being sent now. `task_changed` (v0.6.11, the task-changed guard's Tell) adds to
    its one line that the task's workspace changed since it stopped - the same three lines (D6)."""
    body = l10n.message("toast_starting_body")
    if task_changed is True:
        body += " · " + l10n.message("toast_task_changed")
    return _content(headline(identity),
                    _origin_line(identity, headline(identity), thread_id),
                    extra=[body])


def starting(thread_id: str, identity=None) -> bool:
    """The moment a continuation is actually being sent."""
    return show_content(starting_content(thread_id, identity))


def resumed_content(thread_id: str, identity=None) -> dict:
    return _content(l10n.message("toast_resumed_title"),
                    _origin_line(identity, l10n.message("toast_resumed_title"), thread_id),
                    extra=[l10n.message("toast_resumed_body")])


def resumed(thread_id: str, identity=None) -> bool:
    """Delivery was proven, not assumed: the engine only reaches this after a receipt."""
    return show_content(resumed_content(thread_id, identity))


def attempt_failed_content(thread_id: str, identity=None, *, certain: bool = True) -> dict:
    title = l10n.message("toast_failed_title") if certain else l10n.message("toast_unknown_title")
    body = l10n.message("toast_failed_body") if certain else l10n.message("toast_unknown_body")
    return _content(title, _origin_line(identity, title, thread_id), extra=[body])


def attempt_failed(thread_id: str, identity=None, *, certain: bool = True) -> bool:
    """A failed attempt, told apart from an uncertain one.

    Both are final - a stored failure is never retried, and an uncertain submission is
    never resent - but they mean different things to the person reading them: one did
    not arrive, the other may have. Telling them the wrong one is worse than silence.
    """
    return show_content(attempt_failed_content(thread_id, identity, certain=certain))


def stopped_content(thread_id: str, identity=None, *, reason: str | None = None) -> dict:
    title = l10n.message("toast_exhausted_title")
    body = (l10n.message("toast_no_progress_body") if reason == "no_progress"
            else l10n.message("toast_exhausted_body") if reason == "attempts"
            # v0.6.11: the time ceiling, which a task reaches with attempts to spare.
            else l10n.message("toast_time_cap_body") if reason == "time"
            else l10n.message("toast_stopped_body"))
    return _content(title, _origin_line(identity, title, thread_id), extra=[body])


def stopped(thread_id: str, identity=None, *, reason: str | None = None) -> bool:
    """Recovery has stopped for good, and why in one line."""
    return show_content(stopped_content(thread_id, identity, reason=reason))


# ------------------------------------------------------------ needs-you notices (v0.6.11)
# A conversation that needs a person (needsyou.py): a failure this product will never resume, or a
# turn that has recorded nothing new for a while. Said once, with one next step from the catalog, and
# one button - Open Dashboard, at Settings, which is where a kind of notice is switched off. Nothing
# on it cancels, sends or writes anything (A28), and it names no error: the category's catalog words
# only (D6).
def needs_you_label(kind) -> str:
    """What kind of need it is, in the catalog's words: the reason's label, or "Not moving"."""
    if kind == needsyou.STALLED:
        return l10n.message("needs_you_stalled_label")
    return _reason_label(kind)


def needs_you_message(kind, minutes=None) -> str:
    """The one next step for this kind, from the catalog."""
    key = needsyou.NEXT_STEPS.get(kind, needsyou.NEXT_STEPS["terminal_failure"])
    count = minutes if type(minutes) is int and minutes > 0 else 10
    return l10n.message(key[len("msg."):]).replace("{minutes}", str(count))


def needs_you_content(thread_id: str, kind: str, identity=None, *, minutes=None, sound: bool = False) -> dict:
    """The needs-you notice's content: its conversation, what it needs and what to do next, and Open
    Dashboard. `sound` is the person's choice (needs_you_sound): Windows' reminder sound, or none."""
    title = headline(identity)
    return _content(title, _origin_line(identity, title, thread_id),
                    extra=[needs_you_label(kind) + " · " + needs_you_message(kind, minutes)],
                    more=[(l10n.message("toast_button_open"), open_uri("settings"))],
                    sound=sound is True)



# ---------------------------------------------------------- after a long sleep (v0.6.11)
# What fell due while this PC slept for longer than Ask after a long sleep allows waits for a person
# (power.py). One notice for the sleep - how long it lasted and how many wait - and one button, Open
# Dashboard at Pending, where each is let continue or cancelled. No cancel on the notice: a notification
# button cancels one exact interruption (A28), and this one is about several; nothing on it sends.
def slept_for(seconds) -> str:
    """How long this PC slept, in the hours and minutes every surface writes a wait in."""
    try:
        minutes = max(1, int(seconds) // 60)
    except (TypeError, ValueError, OverflowError):
        minutes = 1
    hours, minutes = divmod(minutes, 60)
    locale = l10n.current()
    parts = [l10n.text("time.hours", locale, n=hours)] if hours else []
    if minutes or not hours:
        parts.append(l10n.text("time.minutes", locale, n=minutes))
    return " ".join(parts)


def after_sleep_content(slept, count) -> dict:
    """A long sleep's notice: how long this PC slept, how many tasks that fell due meanwhile wait for a
    person, what to do next, and Open Dashboard at Pending."""
    try:
        waiting = max(1, int(count))
    except (TypeError, ValueError, OverflowError):
        waiting = 1
    return _content(l10n.message("toast_after_sleep").replace("{time}", slept_for(slept)),
                    l10n.message("toast_after_sleep_next"),
                    extra=[l10n.message("toast_after_sleep_count").replace("{n}", str(waiting))],
                    more=[(l10n.message("toast_button_open"), open_uri("pending"))])


# ------------------------------------------------------------ the memory guard (v0.6.11)
# The watcher uses more memory than the memory guard allows (memguard.py). Warn: said once, and the
# watcher goes on; its button opens Diagnostics, where the peak is. Stop: the watcher stopped between
# two ticks, and its button opens the Overview, where Start watcher is. Neither is about a conversation,
# and neither has a cancel: nothing on either sends or cancels anything (A28).
def memory_content(event, used, limit) -> dict:
    """A memory guard's notice: what the watcher uses against the limit, what happens now, and one
    button that opens a page of the Dashboard."""
    def whole(value):
        try:
            return str(max(0, int(value)))
        except (TypeError, ValueError, OverflowError):
            return "?"
    stopped = event == "memory_stopped"
    body = l10n.message("toast_memory_body").replace("{used}", whole(used)).replace("{limit}", whole(limit))
    return _content(l10n.message("toast_memory_stopped" if stopped else "toast_memory_warning"), body,
                    extra=[l10n.message("toast_memory_stopped_next" if stopped else "toast_memory_warning_next")],
                    more=[(l10n.message("toast_button_open"), open_uri("overview" if stopped else "diagnostics"))])


# ------------------------------------------------- the power action after recoveries (v0.6.12)
# Every usage-limit recovery of a batch has ended and nothing else runs in Codex, so this PC is about to
# go to sleep, hibernate or shut down (runtime/afterwork.py). The countdown's notice says when, and has
# two buttons: Don't sleep (or hibernate, or shut down), which stops it for this batch and sends
# nothing, and Open Dashboard at Settings, where it is turned off. The others say what happened, and
# offer at most Open Dashboard. None names a conversation.
POWER_ACTIONS = ("sleep", "hibernate", "shut_down")


def _power_word(action) -> str:
    return action if action in POWER_ACTIONS else "sleep"


def power_grace_content(action, until, nonce) -> dict:
    """The countdown's notice: what happens at `until`, why, what puts it off, and its two buttons."""
    word = _power_word(action)
    return _content(l10n.message("toast_power_grace." + word).replace("{time}", _local_time(until)),
                    l10n.message("toast_power_grace_body"),
                    button=l10n.message("toast_power_stop." + word), uri=power_stop_uri(nonce),
                    extra=[l10n.message("toast_power_grace_next")],
                    more=[(l10n.message("toast_button_open"), open_uri("settings"))])


def power_content(event, detail) -> dict:
    """The power action's notice for `event`, from the closed `detail` the watcher gives it."""
    detail = detail if isinstance(detail, dict) else {}
    action = _power_word(detail.get("action"))
    if event == "power_grace":
        return power_grace_content(action, detail.get("until"), detail.get("nonce"))
    if event == "power_now":
        return _content(l10n.message("toast_power_now." + action), "")
    if event == "power_failed":
        return _content(l10n.message("toast_power_failed"), l10n.message("toast_power_failed_body"),
                        more=[(l10n.message("toast_button_open"), open_uri("settings"))])
    if event == "power_not_met":
        return _content(l10n.message("toast_power_not_met"), "",
                        more=[(l10n.message("toast_button_open"), open_uri("settings"))])
    return _content(l10n.message("toast_power_stopped"), "")
