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


def quote_argument(value) -> str:
    """Quote one argument for a Windows command line, always.

    `subprocess.list2cmdline` quotes only what it must - a token with a space - so an
    installation under a path without spaces produced an entirely unquoted Run value.
    That is a real defect and not a cosmetic one: the same command under
    `C:\\Users\\John Smith\\...` is parsed as the program `C:\\Users\\John` with
    arguments, and the watcher never starts at sign-in. Nothing about whether it works
    should depend on what the user is called.

    The backslash rule is the documented CommandLineToArgvW one: a run of backslashes
    matters only immediately before a quote, where it must be doubled. Wrapping in
    quotes without that - the obvious version - turns `--home D:\\` into `"D:\\"`, whose
    trailing backslash escapes the closing quote and swallows the next argument.
    """
    text = str(value)
    quoted = ['"']
    slashes = 0
    for character in text:
        if character == "\\":
            slashes += 1
            continue
        if character == '"':
            quoted.append("\\" * (slashes * 2 + 1))
            quoted.append('"')
        else:
            quoted.append("\\" * slashes)
            quoted.append(character)
        slashes = 0
    quoted.append("\\" * (slashes * 2))
    quoted.append('"')
    return "".join(quoted)


def command_line(entry_script: Path, home: Path | None = None, launcher: Path | None = None) -> str:
    launcher = launcher or python_launcher()
    argv = [str(launcher), str(Path(entry_script).resolve())]
    if home is not None:
        argv += ["--home", str(Path(home).resolve())]
    argv.append("run")
    return " ".join(quote_argument(argument) for argument in argv)


PROTOCOL_KEY = r"Software\Classes\%s" % PROTOCOL_SCHEME
PROTOCOL_COMMAND_KEY = PROTOCOL_KEY + r"\shell\open\command"

# Windows shows a toast under the sender's AppUserModelID. Without one of our own, the
# notification is attributed to whatever process raised it - PowerShell - which is not
# something a finished product should show a user. An unpackaged application may claim
# an AUMID by registering it per-user; measured on Windows 11, delivery works even
# unregistered, and this registration is what supplies the display name and icon.
AUMID = "CodexAutoResume.Watcher"
AUMID_KEY = r"Software\Classes\AppUserModelId\%s" % AUMID
AUMID_DISPLAY_NAME = "Codex Auto Resume"


def aumid_registration() -> dict | None:
    """The current display name and icon for our AUMID, or None if unregistered."""
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUMID_KEY, 0, winreg.KEY_READ) as key:
            values = {}
            for name in ("DisplayName", "IconUri"):
                try:
                    value, kind = winreg.QueryValueEx(key, name)
                except FileNotFoundError:
                    continue
                if kind == winreg.REG_SZ and isinstance(value, str):
                    values[name] = value
            return values or None
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StartupError("Cannot read the notification identity registration") from exc


def register_aumid(icon_path=None) -> bool:
    """Claim our AUMID for the current user. Idempotent; needs no administrator rights."""
    winreg = _winreg()
    icon = str(Path(icon_path).resolve()) if icon_path else None
    current = aumid_registration() or {}
    if current.get("DisplayName") == AUMID_DISPLAY_NAME and current.get("IconUri") == icon:
        return False
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, AUMID_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, AUMID_DISPLAY_NAME)
            if icon:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, icon)
    except OSError as exc:
        raise StartupError("Cannot register the notification identity") from exc
    return True


def unregister_aumid() -> bool:
    """Remove only our own AUMID key. Idempotent."""
    winreg = _winreg()
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, AUMID_KEY)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def protocol_command_line(entry_script: Path, home: Path, launcher: Path | None = None) -> str:
    """Command Windows runs when a toast button activates our URI."""
    launcher = launcher or python_launcher()
    argv = [str(launcher), str(Path(entry_script).resolve()), "--home", str(Path(home).resolve()),
            "--quiet", "activate"]
    # Quoted the same way as the autostart value, and for the same reason: under a path
    # with a space, an unquoted handler makes the notification's button do nothing.
    return " ".join(quote_argument(argument) for argument in argv) + ' "%1"'


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


def _canonical(value) -> str:
    """One spelling for one location, so two of them can be compared.

    Windows can hand out the same directory under more than one name: an 8.3 short
    name (``RUNNER~1`` for ``runneradmin``), a different case, a junction. A registry
    value written when ``%TEMP%`` or ``%USERPROFILE%`` was in short form would then
    never match a home resolved to its long form, and setup would report the
    installation's own autostart entry as a conflicting second installation - refusing
    to set itself up, with no way for the user to see why.

    ``resolve()`` expands all of that, but only for a path that exists; for one that
    does not, an absolute normalised path is the best available answer and is still
    stable for comparison against another of the same kind.
    """
    try:
        text = os.fspath(value)
    except TypeError:
        text = str(value)
    try:
        return os.path.normcase(str(Path(text).resolve()))
    except (OSError, ValueError, RuntimeError):
        try:
            return os.path.normcase(os.path.abspath(text))
        except (OSError, ValueError):
            return os.path.normcase(text)


def _same_path(left, right) -> bool:
    return _canonical(left) == _canonical(right)


def _inside(child, parent) -> bool:
    """True when ``child`` is ``parent`` or lives under it, both canonicalised."""
    child_text, parent_text = _canonical(child), _canonical(parent)
    if child_text == parent_text:
        return True
    return child_text.startswith(parent_text.rstrip("\\/") + os.sep)


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
        return _inside(argv[1], home)
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
