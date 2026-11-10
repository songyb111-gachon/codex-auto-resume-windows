"""Which Python an installation's programs run under: the bundled one, unless a record says otherwise (v0.6.23).

Every program of an installation runs `<home>\\runtime\\python.exe` or `pythonw.exe`, the runtime it was installed with.
The advanced edition can put another official Python beside it, in `<home>\\runtimes\\<version>\\`, and name it in one small
record, `<home>\\runtimes\\chosen.json`. This module and gui/RuntimeChoice.cs are the two readers of that record; only the
advanced edition's package writes one, so on a standard installation there is none and everything here answers None.

A record that is missing, unreadable, not of a version's shape, or whose runtime is incomplete is no record: whoever asks
falls back to the bundled runtime. Reading never raises and never writes. The folder is worked out from the version - the
record names no path - so no record can send a launcher anywhere else.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

BUNDLED = "runtime"
FOLDER = "runtimes"
RECORD = "chosen.json"
# Far more than the record ever holds: anything longer is not one.
RECORD_MOST = 4096
VERSION = re.compile(r"3\.([1-9][0-9])\.(0|[1-9][0-9]{0,2})", re.ASCII)


def shaped(version) -> bool:
    return isinstance(version, str) and VERSION.fullmatch(version) is not None


def line_of(version) -> str:
    """"3.15" of "3.15.2"."""
    return ".".join(version.split(".")[:2])


def required(version) -> tuple:
    """What a runtime of `version` cannot run without, each in its folder: the two interpreters, the library, and the
    embeddable's own ._pth and standard library."""
    stem = "python3" + version.split(".")[1]
    return ("python.exe", "pythonw.exe", stem + ".dll", stem + "._pth", stem + ".zip")


def root(home) -> Path:
    return Path(home) / FOLDER


def folder(home, version) -> Path:
    return root(home) / version


def _real_folder(path) -> bool:
    return path.is_dir() and not path.is_symlink() and not path.is_junction()


def complete(home, version) -> bool:
    """Whether the runtime of `version` is all there: a real folder - no link, no junction - with every required file."""
    try:
        where = folder(home, version)
        return (_real_folder(root(home)) and _real_folder(where)
                and all((where / name).is_file() for name in required(version)))
    except (OSError, ValueError):
        return False


def recorded(home) -> str | None:
    """The version the record names, of a version's shape, or None. Its runtime may be gone: `chosen` asks that too."""
    try:
        with (root(home) / RECORD).open("rb") as stream:
            raw = stream.read(RECORD_MOST + 1)
        if len(raw) > RECORD_MOST:
            return None
        found = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    version = found.get("version") if isinstance(found, dict) else None
    return version if shaped(version) else None


def chosen(home) -> str | None:
    """The version every launcher is to use, or None for the bundled runtime."""
    version = recorded(home)
    return version if version is not None and complete(home, version) else None


def interpreter(home, *, windowless=False) -> Path | None:
    """The chosen runtime's python.exe, or its pythonw.exe with `windowless`; None for the bundled runtime."""
    version = chosen(home)
    return None if version is None else folder(home, version) / ("pythonw.exe" if windowless else "python.exe")
