"""The window's stand-in core (v0.6.27-alpha, P6 S6.2a): what the window tests that run its bridges share.

Since the Rust core the window starts one program, the installation's `app\\bin\\codex-auto-resume.exe` (gui/CoreExe.cs),
as `bridge <command> [-]` and `bridge serve`. The tests' stand-ins were written for the interpreter's command line,
`python.exe [-X OPTION ...] -c CODE APP_SRC <command> [-]`, and read the command at args[3]. `shimmed` puts one statement at
the top of a stand-in's Main that takes the core's words, refuses any other (exit 64, so a window that started it the old
way fails its test), and hands the rest of the stand-in the shape it reads. `place` compiles a stand-in to the core's path
in a scratch home, with extra copies beside it where a stand-in starts one (a watcher's pythonw.exe, a grandchild).

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

NO_WINDOW = 0x08000000
CORE = "codex-auto-resume.exe"
# The process names a test's clean-up ends inside its own scratch home: the core and what a stand-in starts beside it.
NAMES = "codex-auto-resume,python,pythonw,CodexAutoResume"

SHIM = (
    "if (args.Length == 0 || args[0] != \"bridge\") { System.Console.Error.Write(\"not the core's bridge: \" + "
    "string.Join(\" \", args)); return 64; } "
    "{ var core = new string[args.Length + 2]; core[0] = \"-c\"; core[1] = \"CODE\"; core[2] = \"APP_SRC\"; "
    "System.Array.Copy(args, 1, core, 3, args.Length - 1); args = core; }"
)
MAIN = "static int Main(string[] args) {"


def shimmed(source: str, after: str = MAIN) -> str:
    """`source` with SHIM as the first thing after `after` (Main's opening, or a line of it that must run first)."""
    if source.count(after) != 1:
        raise ValueError("the stand-in has no single %r to put the core's words after" % after)
    return source.replace(after, after + "\n        " + SHIM, 1)


def core_of(home: Path) -> Path:
    return Path(home) / "app" / "bin" / CORE


def place(csc: Path, source: Path, home: Path, extra: tuple = ()) -> Path:
    """The stand-in compiled at the core's path in `home` (and as each of `extra` beside it); the core's path."""
    folder = core_of(home).parent
    folder.mkdir(parents=True, exist_ok=True)
    (Path(home) / "app" / "src").mkdir(parents=True, exist_ok=True)
    for name in (CORE,) + tuple(extra):
        subprocess.run([str(csc), "/nologo", "/target:exe", "/out:" + str(folder / name), str(source)],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)
    return core_of(home)
