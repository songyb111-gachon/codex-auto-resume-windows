"""Optional Windows toast shown when an interruption is recorded.

This is the only moment a control can be offered at the time it matters: the watcher
is running when the interruption is detected, whereas the Codex turn has already failed
by then, so nothing can be added to the app's own usage-limit notice.

The toast carries one button that opts this conversation out. Doing nothing resumes,
which is the default. Delivery is best effort: a notification that cannot be shown must
never change whether a resume happens.

Nothing about the interrupted work is disclosed. The toast contains only a shortened
conversation id and a local time - never prompt text, error text or account data.
"""
from __future__ import annotations

import subprocess
import time
from xml.sax.saxutils import quoteattr, escape

from . import messages, pwsh

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
INTERRUPTION_ID_LENGTH = 64

_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($env:CODEX_AUTO_RESUME_ARG_XML)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
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
    candidate = values[0].strip().lower()
    if len(candidate) != INTERRUPTION_ID_LENGTH or any(c not in "0123456789abcdef" for c in candidate):
        return None
    return candidate


def _toast_xml(title, body, button=None, uri=None, extra=()) -> str:
    actions = ""
    if button and uri:
        actions = '<actions><action content=%s activationType="protocol" arguments=%s/></actions>' % (
            quoteattr(button), quoteattr(uri))
    # Trimmed here rather than at the call sites, so no future caller can silently
    # lose a line to the platform limit.
    lines = [line for line in ([title] + list(extra) + [body]) if line][:MAX_TOAST_LINES]
    text = "".join("<text>%s</text>" % escape(line) for line in lines)
    return ('<toast duration="long"><visual><binding template="ToastGeneric">'
            '%s</binding></visual>%s</toast>' % (text, actions))


def show(title: str, body: str, *, button: str | None = None, uri: str | None = None,
         extra=()) -> bool:
    """Best effort. Returns True only when PowerShell reported success.

    The toast document travels as an environment variable into a constant script, never
    as script text: a title is whatever Codex named the conversation and a project is a
    folder name, and neither may be able to change what PowerShell runs. See pwsh.py.
    """
    if pwsh.executable() is None:
        return False
    try:
        code = pwsh.run(_SCRIPT, {"XML": _toast_xml(title, body, button, uri, extra),
                                  "AUMID": aumid()}, timeout=TIMEOUT_SECONDS)
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
    return messages.text("toast_unnamed")


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
    thread = messages.text("toast_thread").format(uuid=thread_id)
    secondary = _second_line(identity, used)
    return (secondary + "  ·  " + thread) if secondary else thread


def scheduled(thread_id: str, interruption_id: str, reset_at: float | None,
              category: str = "usage_limit", identity=None) -> bool:
    """Announce that this conversation will be recovered, and offer to opt out.

    Wording follows the failure category: a usage limit waits for a reset, everything
    else is simply retried. Both carry the same single cancel button.
    """
    usage = category == "usage_limit"
    title = headline(identity)
    if usage:
        body = (messages.text("toast_usage_at").format(time=_local_time(reset_at)) if reset_at
                else messages.text("toast_usage_soon"))
        button = messages.text("toast_button_cancel")
    else:
        body = messages.text("toast_transient")
        button = messages.text("toast_button_no_retry")
    # Order matters: the reason must come before the identifiers, because a line that
    # does not fit is lost and losing the reason makes the notification pointless.
    return show(title, _origin_line(identity, title, thread_id),
                button=button, uri=cancel_uri(interruption_id), extra=[body])


def cancelled(thread_id: str) -> bool:
    return show(messages.text("toast_cancelled_title"),
                messages.text("toast_thread").format(uuid=thread_id),
                extra=[messages.text("toast_cancelled_body")])


# --------------------------------------------------------------- lifecycle toasts
# Everything below announces something the watcher has already decided. A toast is
# never a prompt for permission and never gates recovery: `show` returning False costs
# a message, never an attempt. Only the detection toast carries a button, because
# cancelling is the one action that fails in the safe direction.

def starting(thread_id: str, identity=None) -> bool:
    """The moment a continuation is actually being sent."""
    return show(headline(identity),
                _origin_line(identity, headline(identity), thread_id),
                extra=[messages.text("toast_starting_body")])


def resumed(thread_id: str, identity=None) -> bool:
    """Delivery was proven, not assumed: the engine only reaches this after a receipt."""
    return show(messages.text("toast_resumed_title"),
                _origin_line(identity, messages.text("toast_resumed_title"), thread_id),
                extra=[messages.text("toast_resumed_body")])


def attempt_failed(thread_id: str, identity=None, *, certain: bool = True) -> bool:
    """A failed attempt, told apart from an uncertain one.

    Both are final - a stored failure is never retried, and an uncertain submission is
    never resent - but they mean different things to the person reading them: one did
    not arrive, the other may have. Telling them the wrong one is worse than silence.
    """
    title = messages.text("toast_failed_title") if certain else messages.text("toast_unknown_title")
    body = messages.text("toast_failed_body") if certain else messages.text("toast_unknown_body")
    return show(title, _origin_line(identity, title, thread_id), extra=[body])


def stopped(thread_id: str, identity=None, *, reason: str | None = None) -> bool:
    """Recovery has stopped for good, and why in one line."""
    title = messages.text("toast_exhausted_title")
    body = (messages.text("toast_no_progress_body") if reason == "no_progress"
            else messages.text("toast_exhausted_body") if reason == "attempts"
            else messages.text("toast_stopped_body"))
    return show(title, _origin_line(identity, title, thread_id), extra=[body])
