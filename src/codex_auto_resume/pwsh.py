"""Run a fixed Windows PowerShell script, with values passed beside it rather than in it.

Two features need PowerShell because the platform offers them nowhere else from Python's
standard library: raising a toast under our own AppUserModelID, and writing a Start Menu
shortcut that carries one. Both used to build the script text with each value quoted as
a PowerShell single-quoted string, doubling any ASCII apostrophe.

That was not enough, and the failure was a code injection. PowerShell's tokenizer treats
four more characters as single quotes - U+2018, U+2019, U+201A and U+201B - so a project
folder or conversation title containing one of them ended the string early and the rest
of the value ran as PowerShell, in the watcher's context, under the user's account. A
folder called "Bob’s project" was enough to break a notification; a crafted name was
enough to run a command. Measured, not inferred: tests/test_pwsh.py raises the exact
payload through the real interpreter.

The fix is not a longer escape list. Values never become script text at all. Each one
travels as an environment variable of the child process, and the script - a constant,
reviewed in this repository - reads it with `$env:NAME`. PowerShell does not parse an
environment variable's value as code under any circumstances, so there is no character a
value could contain that changes what runs. The script itself is still sent with
-EncodedCommand, so no command-line quoting applies to it either.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess

# Namespaced so a value can never collide with, or be mistaken for, a real setting.
PREFIX = "CODEX_AUTO_RESUME_ARG_"
_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,40}\Z")
# Windows limits an environment variable to 32,767 characters. Everything passed here is
# short; a value near the limit is a bug, and refusing it beats truncating it.
MAX_VALUE = 16000


class PowerShellError(RuntimeError):
    """A static reason only - never a transcript, never a value."""


def executable() -> str | None:
    """The in-box Windows PowerShell, by absolute path. Never whatever is on PATH."""
    root = os.environ.get("SystemRoot")
    if os.name != "nt" or not root:
        return None
    path = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return path if os.path.isfile(path) else None


def environment(values: dict) -> dict:
    """The child's environment: ours, plus one variable per value.

    Every value is checked here rather than trusted: a NUL cannot be carried in an
    environment block at all, and an oversized value means something upstream is wrong.
    """
    child = dict(os.environ)
    # Never inherit a stale argument from a parent that happened to set one.
    for key in list(child):
        if key.upper().startswith(PREFIX):
            del child[key]
    for name, value in values.items():
        if not _NAME.match(name):
            raise PowerShellError("invalid argument name")
        text = "" if value is None else str(value)
        if "\0" in text:
            raise PowerShellError("an argument contains a NUL character")
        if len(text) > MAX_VALUE:
            raise PowerShellError("an argument is too long")
        child[PREFIX + name] = text
    return child


def reference(name: str) -> str:
    """How a fixed script refers to a value: `$env:CODEX_AUTO_RESUME_ARG_NAME`."""
    if not _NAME.match(name):
        raise PowerShellError("invalid argument name")
    return "$env:" + PREFIX + name


def run(script: str, values: dict, *, timeout: float) -> int:
    """Run `script` with `values` available as environment variables. Returns the exit code.

    `script` must be a constant. It is the caller's code, not data; nothing derived from
    a value may be formatted into it. tests/test_pwsh.py holds every caller to that.
    """
    shell = executable()
    if shell is None:
        raise PowerShellError("PowerShell is unavailable")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=environment(values), stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=timeout, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return completed.returncode
