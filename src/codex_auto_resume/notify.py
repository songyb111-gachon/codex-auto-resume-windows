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

import base64
import os
import subprocess
import time
from xml.sax.saxutils import quoteattr, escape

from . import messages

SCHEME = "codex-auto-resume"
# Toasts from a process without its own registered AppUserModelID are not shown. This is
# Windows PowerShell's own, which always exists, so notifications appear attributed to it.
AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
TIMEOUT_SECONDS = 20
INTERRUPTION_ID_LENGTH = 64

_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml(%(xml)s)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier(%(aumid)s).Show($toast)
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


def _powershell() -> str | None:
    root = os.environ.get("SystemRoot")
    if os.name != "nt" or not root:
        return None
    path = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.isfile(path) else None


def _toast_xml(title: str, body: str, button: str | None, uri: str | None) -> str:
    actions = ""
    if button and uri:
        actions = '<actions><action content=%s activationType="protocol" arguments=%s/></actions>' % (
            quoteattr(button), quoteattr(uri))
    return ('<toast duration="long"><visual><binding template="ToastGeneric">'
            '<text>%s</text><text>%s</text></binding></visual>%s</toast>'
            % (escape(title), escape(body), actions))


def show(title: str, body: str, *, button: str | None = None, uri: str | None = None) -> bool:
    """Best effort. Returns True only when PowerShell reported success."""
    shell = _powershell()
    if shell is None:
        return False
    script = _SCRIPT % {"xml": quoteattr(_toast_xml(title, body, button, uri)),
                        "aumid": quoteattr(AUMID)}
    # -EncodedCommand takes UTF-16LE base64: no quoting rules apply to the payload at all,
    # so no string built here can be reinterpreted as PowerShell syntax.
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def _local_time(when: float) -> str:
    return time.strftime("%H:%M", time.localtime(when))


def scheduled(thread_id: str, interruption_id: str, reset_at: float | None) -> bool:
    """Announce that this conversation will be resumed, and offer to opt out."""
    short = str(thread_id)[:8]
    if reset_at:
        body = messages.text("toast_body_at").format(time=_local_time(reset_at), short=short)
    else:
        body = messages.text("toast_body_soon").format(short=short)
    return show(messages.text("toast_title"), body,
                button=messages.text("toast_button_cancel"), uri=cancel_uri(interruption_id))


def cancelled(thread_id: str) -> bool:
    return show(messages.text("toast_cancelled_title"),
                messages.text("toast_cancelled_body").format(short=str(thread_id)[:8]))
