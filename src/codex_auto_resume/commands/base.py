"""What every command has: the error it refuses with, the App it is given, the state it opens.

`PROG` is the name the parser prints and the name the shortcut runs, and is written here once.
"""
from __future__ import annotations

import time

from .. import config
from ..app import App
from ..domain import ids
from ..openstate import open_state


PROG = "auto_resume"


class CliError(RuntimeError):
    pass


def canonical_thread_id(value: str) -> str:
    problem = ids.uuid_problem(value, as_text=True)
    if problem == ids.MALFORMED:
        raise CliError("thread id must be a canonical UUID (never --last or a name)")
    if problem is not None or str(value) != value:
        raise CliError("thread id must be lowercase canonical UUID text")
    return value


def _now() -> float:
    return time.time()


def _print(text: str = "") -> None:
    print(text)


def _app(args) -> App:
    paths = config.Paths(args.home)
    return App(paths, codex_exe=args.codex_exe, codex_home=args.codex_home, console=not args.quiet)


def _open_state(app):
    """The state for a command that only switches things on or off, or cancels.

    While an older watcher still owns an unmigrated state, these keep working through
    the schema that watcher understands; nothing else does until it stops.
    """
    return open_state(app.paths.state_dir, legacy="always")
