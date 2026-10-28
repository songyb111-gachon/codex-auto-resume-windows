# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""Open Codex on a notice (v0.6.18; v0.6.20: the notice itself, no button): a click on a notice shows its
conversation in the Codex app.

The standard edition's notices offer two kinds of button and no others (A28): one that cancels one exact
interruption, and one that opens one page of the Dashboard, and a click on the notice opens a Dashboard page. With
this capability on, a click on a notice about one conversation - its key that conversation's id
(notifier.Notice.key) - opens Codex instead, and the buttons are the standard edition's (the owner, 2026-10-28:
a button of its own looked out of place). The link is the Codex app's own link to that conversation (core's notify.codex_thread_uri, measured on Codex
app 26.1007: a running, minimized or closed app opens at that conversation). The card opens it through
notify.open_in_codex (core's notifier.activate already reads exactly that link, and nothing else of its shape);
Windows' own toast hands it to whatever is registered for `codex:`. The link only shows a conversation: nothing
is sent, nothing is changed, and the card still has no send path (A1).

An action: core never asks it anything. While it stands on and Windows has a handler for `codex:` - read, never
written, from the registry's Software\\Classes\\codex under HKEY_CURRENT_USER, then HKEY_LOCAL_MACHINE, a key
marked "URL Protocol" as every registered URL scheme is - the icon's surface says so (surfaces.notice_view), and
the watcher sends the click of each notice it builds about one conversation to it (core's notifier.with_open_codex).
Where Windows has none, the click is not sent there: a link nothing can open is not offered.
"""
from __future__ import annotations

CAPABILITY = "open_codex_button"
# The registry key every registered URL scheme has (Windows' "Registering an Application to a URI Scheme"), under
# Software\Classes of the user and of the machine, the user's first - as Windows reads HKEY_CLASSES_ROOT.
PROTOCOL_KEY = r"Software\Classes\codex"
PROTOCOL_VALUE = "URL Protocol"
# How long one answer of the registry is reused, in seconds: the icon asks its surface every tick.
REUSE = 60


def _registered(read) -> bool:
    """Whether `read(root, path, value)` finds the `codex:` scheme registered under either root."""
    for root in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        try:
            if read(root, PROTOCOL_KEY, PROTOCOL_VALUE) is True:
                return True
        except Exception:
            continue
    return False


def _read_registry(root, path, value) -> bool:
    """True where the key `path` under `root` holds the value `value` (of any type, empty included): a read, opened
    for KEY_READ alone, and closed again."""
    import winreg
    with winreg.OpenKey(getattr(winreg, root), path, 0, winreg.KEY_READ) as key:
        winreg.QueryValueEx(key, value)
    return True


def handler_registered(read=None) -> bool:
    """Whether Windows has a handler for `codex:` links. Off Windows, or where nothing can be read, False."""
    import os
    if read is None:
        if os.name != "nt":
            return False
        read = _read_registry
    return _registered(read)


class OpenCodexButton:
    """open_codex_button's code: an action, so nothing of it runs at a plug point. It answers one question for the
    icon's surface - whether a notice may offer the button now - reading the registry at most once a REUSE. `read`
    and `clock` are seams a test fills."""
    __slots__ = ("paths", "_read", "_clock", "_known")

    def __init__(self, paths, *, read=None, clock=None):
        self.paths = paths
        self._read = read
        self._clock = clock
        self._known = None                    # (when it was read, the answer)

    def available(self) -> bool:
        """Whether Windows can open a `codex:` link here now (handler_registered), reused for REUSE seconds."""
        import time
        now = (self._clock or time.monotonic)()
        if self._known is not None and 0 <= now - self._known[0] < REUSE:
            return self._known[1]
        try:
            answer = handler_registered(self._read)
        except Exception:
            answer = False
        self._known = (now, answer)
        return answer


def make(paths) -> OpenCodexButton:
    return OpenCodexButton(paths)
