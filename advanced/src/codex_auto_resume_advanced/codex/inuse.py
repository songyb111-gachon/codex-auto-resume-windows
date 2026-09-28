# ADVANCED-EDITION-CODE: in the advanced edition's archive, never the standard one's.
"""The Codex an installation drives, for the capabilities' own sessions and reads.

The marker-free continuation's channel and the goal continuation's route and channel each open a
session of their own with Codex's app server, and the goal continuation reads Codex's goals
database. Each has to be of the Codex the watcher drives - the one its `codex queue` goes to, whose
home core reads. A Codex found here by discovery alone would not be: with two engines installed
and the watcher pinned to one (the `codex_exe` setting, `--codex-exe`), discovery is ambiguous and
nothing is ever sent; and with `--codex-home`, the session and the reads would be of another home.
So the watcher tells its plug the Codex it found and checked (core's Plug.codex, runtime/app.py),
and that is the one used here.

A process that holds no watcher - the Dashboard's bridge, where a person runs a measurement - has
been told nothing, and finds Codex as the watcher does when it is given no arguments: the
`codex_exe` setting (or CODEX_AR_CODEX_EXE) where one is set, discovery otherwise, and CODEX_HOME's
home. Nothing here starts a process: `backend` runs core's engine check, which a test replaces.
"""
from __future__ import annotations

from pathlib import Path

from codex_auto_resume import config

# {an installation's home: (codex.exe, Codex home)}, as its watcher told them, for the life of the
# process - as core keeps one plug for each home (edition.plug).
_TOLD = {}


def _key(paths) -> Path:
    return Path(paths.home)


def tell(paths, codex_exe, codex_home) -> None:
    """What the watcher of the installation at `paths` drives (AdvancedPlug.codex)."""
    _TOLD[_key(paths)] = (Path(codex_exe).resolve(), Path(codex_home).resolve())


def told(paths):
    """(codex.exe, Codex home) as the watcher told them for `paths`, or None."""
    return _TOLD.get(_key(paths)) if paths is not None else None


def forget(paths) -> None:
    """What was told for `paths` forgotten: a test's cleanup."""
    _TOLD.pop(_key(paths), None)


def home(paths=None) -> Path:
    """The Codex home: the watcher's, as told; else CODEX_HOME's, as the watcher finds it."""
    found = told(paths)
    return found[1] if found is not None else config.codex_home()


def _pinned(paths):
    """The codex.exe the `codex_exe` setting pins, or None - what the watcher drives when it was
    given no `--codex-exe` (runtime/app.py)."""
    if paths is None:
        return None
    try:
        value = config.load_settings(paths).get("codex_exe")
    except Exception:
        return None
    return value if isinstance(value, str) and value else None


def backend(paths=None):
    """Core's Backend for the Codex the installation at `paths` drives, checked, so that its
    `engine_version` is that Codex's: the one its watcher told, else the one the watcher would
    find. Raises as core's discovery and check do."""
    from codex_auto_resume.codex.transport import Backend
    found = told(paths)
    if found is not None:
        exe, where = found
    else:
        where = config.codex_home()
        exe = config.discover_codex_exe(_pinned(paths), lambda path: Backend(where, path)._compatible())
    made = Backend(where, exe)
    made._compatible()
    return made
