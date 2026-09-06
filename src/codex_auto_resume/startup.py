"""Optional per-user Windows login autostart via HKCU Run. No administrator rights.

Only the single value ``CodexAutoResume`` under the current user's Run key is
ever written or removed. Nothing system-wide, no services, no scheduled tasks.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "CodexAutoResume"


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
