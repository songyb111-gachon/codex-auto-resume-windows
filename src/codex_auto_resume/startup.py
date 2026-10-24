"""Per-user Windows registration: login autostart, and the toast button's URL protocol.

Both are optional, both are HKCU only, and both need no administrator rights. The only
things ever written are the single ``CodexAutoResume`` value under the current user's Run
key and the ``codex-auto-resume:`` protocol keys under the user's own class registrations -
and, through read_key/write_key/delete_key at the foot of this module, the one key of
addremove.py under the user's Uninstall key. Nothing system-wide, no services, no scheduled tasks.
"""
from __future__ import annotations

import os
from pathlib import Path
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
    """pythonw.exe beside the interpreter running this code - never python.exe.

    What this names is started by Windows itself (the Run value at sign-in, the notification
    button's protocol handler, the Start Menu entry) or detached, with no console to share.
    python.exe there is a console program with nothing to hide its console: Windows opens a
    console window for it, and for the watcher that window stays for the whole session. A Run
    value cannot carry CREATE_NO_WINDOW. This used to fall back to python.exe without a word
    when there was no pythonw.exe; it refuses instead, and every caller says so rather than
    registering or starting a watcher someone would see (tests/test_no_console_windows.py).
    """
    executable = Path(sys.executable).resolve()
    windowless = executable.with_name("pythonw.exe")
    if not windowless.is_file():
        raise StartupError("no pythonw.exe beside %s: nothing is registered or started with a "
                           "console interpreter, which would open a window" % executable.name)
    return windowless


# PEP 768, new in Python 3.14: an interpreter with remote debugging on can be made, by any process of the same
# user, to run a script of that process's choosing (sys.remote_exec) - and it is on unless the interpreter is told
# otherwise. Every process of the bundled Python this product starts is told so on its command line, right after
# the interpreter. The spelling is `disable-remote-debug`, with hyphens: an unknown -X option is kept without a
# word, and `-X disable_remote_debug`, as PEP 768 wrote it, leaves remote debugging on (measured on 3.14.7 and on
# the bundled 3.14.9). Before 3.14 the option is unknown and kept the same way, so one command line serves every
# supported line. Not the PYTHON_DISABLE_REMOTE_DEBUG variable: an environment is handed on to everything a
# process starts, Codex and other people's Python among it, and this is for the product's own processes alone.
NO_REMOTE_DEBUG = ("-X", "disable-remote-debug")
_NO_REMOTE_DEBUG_OPTION = NO_REMOTE_DEBUG[1]


def remote_debug_on() -> bool:
    """Whether another process could make this one run code (PEP 768). Always False before 3.14."""
    probe = getattr(sys, "is_remote_debug_enabled", None)
    try:
        return bool(probe is not None and probe())
    except Exception:                               # noqa: BLE001 - a question that cannot be asked is a no
        return False


def again_without_remote_debug(script) -> int | None:
    """Run this script again with remote debugging off, where it is on: the exit code to end with, or None to go on
    in this process.

    For a script's `__main__` alone, which passes its own `__file__` (src/auto_resume.py, scripts/plugin_setup.py;
    the stable launcher keeps a copy of its own, since it runs before any engine is found). What the product starts
    itself carries NO_REMOTE_DEBUG already; this is for what it does not start: a sign-in or notification-button
    value an older version wrote, or a published bootstrap that runs setup the way it always did. The script runs
    again with the same arguments and the option in front. Under pythonw.exe - started by Windows, with no streams
    and nobody waiting for an answer - the new process is detached and this one ends; under python.exe the new one
    runs windowless on this process's streams and its exit code is this one's. Once at most: a process given the
    option never starts another, and where the new one cannot be started this one goes on as it is."""
    if not remote_debug_on() or _NO_REMOTE_DEBUG_OPTION in getattr(sys, "_xoptions", {}):
        return None
    import subprocess
    try:
        if Path(sys.executable).name.lower() == "pythonw.exe":
            # A GUI program: Windows makes no console for it, so a detached one opens nothing (python_launcher).
            interpreter = Path(sys.executable).resolve().with_name("pythonw.exe")
            flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            subprocess.Popen([str(interpreter), *NO_REMOTE_DEBUG, str(script), *sys.argv[1:]], close_fds=True,
                             creationflags=flags, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return 0
        streams = [stream.fileno() if stream is not None else subprocess.DEVNULL
                   for stream in (sys.stdin, sys.stdout, sys.stderr)]
        for stream in (sys.stdout, sys.stderr):
            if stream is not None:
                stream.flush()
        return subprocess.run([sys.executable, *NO_REMOTE_DEBUG, str(script), *sys.argv[1:]],
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                              stdin=streams[0], stdout=streams[1], stderr=streams[2]).returncode
    except (OSError, ValueError, AttributeError):
        return None


def script_index(argv) -> int:
    """Where the script is in an interpreter's command line: after the interpreter and its options, `-X` and `-W`
    each with its value (NO_REMOTE_DEBUG, which a notification-button value carries)."""
    index = 1
    while index < len(argv) and argv[index].startswith("-") and argv[index] != "-":
        index += 2 if argv[index] in ("-X", "-W") else 1
    return index


def quote_argument(value) -> str:
    """Quote one argument for a Windows command line, always.

    `subprocess.list2cmdline` quotes only what it must - a token with a space - so an
    installation under a path without spaces produced an entirely unquoted Run value.
    That is a real defect and not a cosmetic one: the same command under
    `C:\\Users\\Example User\\...` is parsed as the program `C:\\Users\\Example` with
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


def command_line(entry_script: Path, home: Path | None = None, launcher: Path | None = None,
                 options=()) -> str:
    """The sign-in (Run) value's command line, or with `options` (NO_REMOTE_DEBUG) one the product starts itself.

    The Run value keeps the form every released version reads: their `belongs_to` takes the argument after the
    interpreter for the launcher, so an option there would make an older setup - a downgrade - refuse this
    installation's own value as another's. The launcher it names turns remote debugging off itself, before it does
    anything else (scripts/watcher_launcher.py, `_again_without_remote_debug`), and so does src/auto_resume.py."""
    launcher = launcher or python_launcher()
    argv = [str(launcher), *options, str(Path(entry_script).resolve())]
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


def notification_identity_owner(home) -> bool | None:
    """Whether the registered notification identity belongs to ``home``.

    ``None`` when nothing is registered, so a caller can tell "not ours" from "not
    there" - the first must be left alone, the second is simply nothing to do.

    The AUMID and the Start Menu shortcut are one registration in two places: Windows
    will not draw a toast from an unpackaged application unless a shortcut carries the
    same AppUserModelID, so they are installed together and point at the same
    installation. Both are per-user singletons at fixed locations, which means a second
    copy of this tool overwrites them rather than adding its own - and an uninstall that
    removed them without asking whose they were would silence the *other* copy's
    notifications while leaving it running. The icon path is the identifying part: it is
    written as an absolute path inside the installation that registered it.
    """
    registration = aumid_registration()
    if not registration:
        return None
    icon = registration.get("IconUri")
    if not icon:
        # Registered without an icon: nothing identifies it, so treat it as not ours
        # rather than guess. Leaving a stray key behind is the cheaper mistake.
        return False
    return _inside(icon, home)


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
    # With NO_REMOTE_DEBUG: only `doctor` reads this value back (script_index), and setup writes it whole each time.
    argv = [str(launcher), *NO_REMOTE_DEBUG, str(Path(entry_script).resolve()), "--home", str(Path(home).resolve()),
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
    script = script_index(argv)
    if len(argv) > script:
        # A launcher living inside the home identifies the installation on its own.
        return _inside(argv[script], home)
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


# ---------------------------------------------------------------------------------------- a key's own values
# addremove.py decides what its key says and whose it is; startup.py stays the one module that touches the
# registry, so these are the whole of what it is asked for. They carry no rule of their own.

def read_key(path: str, names) -> dict | None:
    """The values of `names` under the HKCU key `path` that exist, or None when the key does not."""
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
            found = {}
            for name in names:
                try:
                    found[name] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    continue
            return found
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise StartupError("Cannot read the current user's registry key") from exc


def write_key(path: str, values: dict) -> None:
    """Create the HKCU key `path` and set each value: a string as REG_SZ, an integer as REG_DWORD."""
    winreg = _winreg()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                kind = winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ
                winreg.SetValueEx(key, name, 0, kind, value)
    except OSError as exc:
        raise StartupError("Cannot write the current user's registry key") from exc


def delete_key(path: str) -> bool:
    """Idempotent: True when the HKCU key `path` was removed. A key with subkeys is refused by Windows, as it should be."""
    winreg = _winreg()
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise StartupError("Cannot remove the current user's registry key") from exc
    return True
