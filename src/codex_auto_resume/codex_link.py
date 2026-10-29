"""The Codex app's own link to one conversation, and opening it.

A notice about one conversation may offer Open Codex: a click goes to the Codex app, at that conversation, through
the link the app registers with Windows (`codex://threads/<id>`). That link is Codex's, not this product's - it can
only show a conversation, never change one - so this module is the one place that builds it, reads it back and hands
it to Windows. Only a UUID in its canonical text is ever put in a link, and only exactly such a link is ever read.

From v0.6.19 it also holds this product's own link to the advanced edition's chat at one conversation (`chat_uri`),
the other place a click on a notice may go. It was part of `notify.py` until v0.6.18, which re-exports these names,
so `notify.codex_thread_uri` and the rest still read as they always did.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

from .domain import ids

# v0.6.16: the Codex app's own link to one conversation. Measured on 2026-10-16 (Codex app 26.1007): opened through
# Windows' URL handler, it brings a running or minimized app to the front at that conversation, and starts a closed
# one there. Codex's link, not this product's: it can only show a conversation, never change one.
CODEX_THREAD_LINK = "codex://threads/"


def codex_thread_uri(thread_id) -> str | None:
    """The Codex app's link to one conversation, or None unless `thread_id` is a UUID in its canonical text - the
    only thing ever put in the link (ids.is_uuid)."""
    return CODEX_THREAD_LINK + thread_id if ids.is_uuid(thread_id) else None


def parse_codex_thread_uri(uri) -> str | None:
    """The conversation a Codex link names, or None when `uri` is anything but exactly CODEX_THREAD_LINK and a UUID
    in its canonical text: no query, no fragment, no second segment."""
    text = uri if isinstance(uri, str) else ""
    if not text.startswith(CODEX_THREAD_LINK):
        return None
    thread_id = text[len(CODEX_THREAD_LINK):]
    return thread_id if ids.is_uuid(thread_id) else None


# v0.6.19: this product's own link to the advanced edition's chat at one conversation, where a click on a notice may
# go while the chat is on (notifier.click_uri) - notify.SCHEME's `chat` action, with nothing but a canonical UUID in it.
CHAT_LINK = "codex-auto-resume:chat?thread="


def chat_uri(thread_id) -> str | None:
    """The link that opens the chat at `thread_id`, or None unless it is a UUID in its canonical text. Like an open
    URI it changes nothing: at worst it opens a window."""
    return CHAT_LINK + thread_id if ids.is_uuid(thread_id) else None


def parse_chat_uri(uri) -> str | None:
    """The conversation a chat link names, or None for anything but exactly CHAT_LINK and a canonical UUID."""
    text = uri if isinstance(uri, str) else ""
    thread_id = text[len(CHAT_LINK):] if text.startswith(CHAT_LINK) else None
    return thread_id if ids.is_uuid(thread_id) else None


def open_in_codex(link) -> bool:
    """Show one conversation in the Codex app, where a click on a notice may go: the app's own link to it, handed to
    Windows' URL handler - explorer.exe, given the link as its one argument, opens it with whatever Windows has
    registered for `codex:`, the Codex app, as a click on such a link would. No shell and no command string: the link
    is read again here, and only exactly a Codex conversation link - CODEX_THREAD_LINK and a UUID's canonical text -
    is ever put in the argument list. False when there is no explorer.exe."""
    thread_id = parse_codex_thread_uri(link)
    if thread_id is None:
        raise ValueError("not a Codex conversation link")
    explorer = Path(os.environ.get("SystemRoot") or r"C:\Windows") / "explorer.exe"
    if not explorer.is_file():
        return False
    # explorer.exe is a GUI program, so no console is made for it; the flag is the rule every start obeys
    # (tests/test_no_console_windows.py).
    subprocess.Popen([str(explorer), codex_thread_uri(thread_id)], close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True
