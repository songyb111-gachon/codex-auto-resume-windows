"""Per-user Windows registration: login autostart, and the toast button's URL protocol.

Both are optional, both are HKCU only, and both need no administrator rights. The only
things ever written are the single ``CodexAutoResume`` value under the current user's Run
key and the ``codex-auto-resume:`` protocol keys under the user's own class registrations.
Nothing system-wide, no services, no scheduled tasks.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CodexAutoResume"
PROTOCOL_SCHEME = "codex-auto-resume"


class StartupError(RuntimeError):
    pass


def _winreg():
    if os.name != "nt":
        raise StartupError("Windows registry autostart is only available on Windows")
    import winreg  # noqa: WPS433 - Windows-only module
    return winreg


def python_launcher() -> Path:
    """pythonw.exe (no console window) from the interpreter running this code."""
    executable = Path(sys.executable).resolve()
    windowless = executable.with_name("pythonw.exe")
    return windowless if windowless.is_file() else executable


def command_line(entry_script: Path, home: Path | None = None, launcher: Path | None = None) -> str:
    launcher = launcher or python_launcher()
    argv = [str(launcher), str(Path(entry_script).resolve())]
    if home is not None:
        # list2cmdline escapes a trailing backslash (e.g. --home D:\), which naive
        # quoting would turn into an escaped quote, swallowing the `run` subcommand.
        argv += ["--home", str(Path(home).resolve())]
    argv.append("run")
    return subprocess.list2cmdline(argv)


PROTOCOL_KEY = r"Software\Classes\%s" % PROTOCOL_SCHEME
PROTOCOL_COMMAND_KEY = PROTOCOL_KEY + r"\shell\open\command"


def protocol_command_line(entry_script: Path, home: Path, launcher: Path | None = None) -> str:
    """Command Windows runs when a toast button activates our URI."""
    launcher = launcher or python_launcher()
    argv = [str(launcher), str(Path(entry_script).resolve()), "--home", str(Path(home).resolve()),
            "--quiet", "activate"]
    return subprocess.list2cmdline(argv) + ' "%1"'


def protocol_value() -> str | None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROTOCOL_COMMAND_KEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, "")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StartupError("Cannot read the current user's URL protocol registration") from exc
    return value if kind == winreg.REG_SZ and isinstance(value, str) else None


def install_protocol(command: str) -> bool:
    """Register the per-user URL protocol. Idempotent; needs no administrator rights."""
    winreg = _winreg()
    if protocol_value() == command:
        return False
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PROTOCOL_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Codex Auto Resume")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, PROTOCOL_COMMAND_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
    except OSError as exc:
        raise StartupError("Cannot register the URL protocol for the current user") from exc
    return True


def uninstall_protocol() -> bool:
    """Remove only the keys this tool creates, deepest first. Idempotent."""
    winreg = _winreg()
    removed = False
    for key_path in (PROTOCOL_COMMAND_KEY, PROTOCOL_KEY + r"\shell\open",
                     PROTOCOL_KEY + r"\shell", PROTOCOL_KEY):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            removed = True
        except FileNotFoundError:
            continue
        except OSError:
            # A subkey added by something else must not be force-deleted.
            break
    return removed


def parse_command(command: str) -> list[str]:
    """Split a registered Run value the way Windows itself would.

    Naive splitting would mis-handle the quoted paths ``list2cmdline`` writes, and a
    wrong split here decides whether uninstall deletes someone else's registration.
    """
    if os.name != "nt":
        raise StartupError("Windows registry autostart is only available on Windows")
    import ctypes
    from ctypes import wintypes

    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    count = ctypes.c_int(0)
    pointer = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not pointer:
        return []
    try:
        return [pointer[index] for index in range(count.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(pointer)


def _same_path(left: str, right: Path) -> bool:
    try:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(str(right)))
    except (OSError, ValueError):
        return False


def belongs_to(command: str, home: Path) -> bool:
    """True when this Run value starts the installation rooted at ``home``.

    Uninstall must never remove an autostart entry belonging to a *different* copy of
    this tool: the two installations have separate state, and silently unregistering
    the other one leaves that watcher dead with no notice at the next sign-in.
    """
    try:
        argv = parse_command(command)
    except StartupError:
        return False
    for index, argument in enumerate(argv):
        if argument == "--home" and index + 1 < len(argv) and _same_path(argv[index + 1], home):
            return True
    if len(argv) >= 2:
        # A launcher living inside the home identifies the installation on its own.
        try:
            script = Path(os.path.abspath(argv[1]))
            resolved_home = Path(os.path.abspath(str(home)))
            if script == resolved_home or script.is_relative_to(resolved_home):
                return True
        except (OSError, ValueError):
            return False
    return False


def current_value() -> str | None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StartupError("Cannot read the current user's Run key") from exc
    return value if kind == winreg.REG_SZ and isinstance(value, str) else None


def install(command: str) -> bool:
    """Idempotent: returns True when the value was created or changed."""
    winreg = _winreg()
    if current_value() == command:
        return False
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    except OSError as exc:
        raise StartupError("Cannot write the current user's Run key") from exc
    return True


def uninstall() -> bool:
    """Idempotent: returns True when a value was removed."""
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StartupError("Cannot remove the current user's Run value") from exc
    return True
