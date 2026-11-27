"""CODEX_AR_CORE=rust: the product's entry points, started as the Rust binary instead of run in Python.

With the variable set, `install()` puts one finder first on sys.meta_path. When a test (or a child Python the
test starts with tests/ on its path) imports one of ENTRY_POINTS, the module loads as always and then its
`main` is replaced by a function that runs car-core-stub (core.py; codex-auto-resume.exe once car-bin
exists) with the entry point's name and the same argv, hands it the test's stdin when the command reads it
(`serve`, an argument given as `-`, the MCP server), writes what it printed to the test's stdout and stderr,
and returns its exit code. The module itself, its other names and its loader are left as they are, so a test
that reads them reads Python's; a test that fails on Rust only for that goes in LEDGER, with its reason.

Installed by tests/sitecustomize.py (runs with tests/ on PYTHONPATH, and their child Pythons) and by
scripts/test_parts.py's lanes (PYTHONPATH=src: sitecustomize is not on their path). Without the variable
neither imports this file: a strict no-op.

S4.2: `codex_auto_resume.engine` passes the same finder, and as it loads its `Engine` becomes engineproxy.py's
(loaded by path, beside this file): car-engine in a `car-harness serve` of its own, whose store, source and backend
are the test's own Python objects, asked back over the pipe. The Store and LocalSource stay Python's: what the
engine decides is Rust's, what it reads and writes is the test's.

S7.2a3 (owner Q3 (c)): every `codex_auto_resume_advanced.*` module passes the same finder too, and as it loads the
advanced proxy (tests/rustdiff/advproxy/, loaded by path as `rustdiff_advproxy`) replaces the names its table forwards
to car-adv's `advserve`; a module the table does not forward is the reference's own.

Not yet here (later seats, PLAN 4.2): a `serve` that streams a live pipe line by line (the whole input is read first, which a test's StringIO
allows); `python -m codex_auto_resume.<entry>`, which runs the module as __main__ and so never passes the
finder (no test starts the product that way today). Self-contained: stdlib only, nothing else of rustdiff,
so it loads by path before anything is on sys.path.
"""
from __future__ import annotations

import importlib.abc
import os
from pathlib import Path
import subprocess
import sys

VARIABLE, VALUE = "CODEX_AR_CORE", "rust"
# Module -> the stub's entry point. mcpserver re-exports mcp.server's main; both are replaced.
ENTRY_POINTS = {"codex_auto_resume.controlcli": "bridge", "codex_auto_resume.mcpserver": "mcp",
                "codex_auto_resume.mcp.server": "mcp", "codex_auto_resume.cli": "cli"}
# S4.2: the package whose `Engine` becomes the proxy (engineproxy.py).
ENGINE = "codex_auto_resume.engine"
# S7.2a3: the advanced package, each of whose modules the advanced proxy patches as it loads (advproxy/table.py).
ADVANCED = "codex_auto_resume_advanced"
# S6.4: the popup's pure half (words and view model), as car-surface (surfaceproxy.py).
SURFACE = ("codex_auto_resume.ui.popup.words", "codex_auto_resume.ui.popup.model", "codex_auto_resume.ui.words",
           "codex_auto_resume.ui.tray.model", "codex_auto_resume.ui.tray.words", "codex_auto_resume.ui.tray.menu", "codex_auto_resume.ui.tray.motion")
# S6.4f: the drawing half's plans and motion, as the C# host's (planproxy.py, loaded by path); patched after SURFACE's.
PLAN = ("codex_auto_resume.ui.tray.motion", "codex_auto_resume.ui.popup.motion", "codex_auto_resume.ui.popup.placement",
        "codex_auto_resume.ui.popup.elevation", "codex_auto_resume.ui.popup.layout", "codex_auto_resume.ui.popup.renderer", "codex_auto_resume.notice_card",
        "codex_auto_resume.ui.popup.fonts", "codex_auto_resume.ui.popup.theme")
STDIN_ARGUMENT = "-"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CRATE = Path(__file__).resolve().parents[2] / "rust" / "crates" / "car-harness"


def wanted() -> bool:
    return os.environ.get(VARIABLE) == VALUE


def executable() -> Path:
    """The binary the entry points become: CODEX_AR_CORE_EXE, else the harness crate's release build."""
    named = os.environ.get("CODEX_AR_CORE_EXE")
    if named:
        return Path(named)
    target = Path(os.environ["CARGO_TARGET_DIR"]) if os.environ.get("CARGO_TARGET_DIR") else CRATE.parents[1] / "target"
    return target / "release" / "car-core-stub.exe"


def _stdin_bytes() -> bytes:
    stream = sys.stdin
    if stream is None:
        return b""
    buffer = getattr(stream, "buffer", None)
    data = buffer.read() if buffer is not None else stream.read()
    return data if isinstance(data, bytes) else data.encode("utf-8")


def _write(stream, data: bytes) -> None:
    """The child's bytes onto the test's stream: as bytes where it has a buffer (no newline translation, the
    wire's own "\\n"), else as UTF-8 text (a test's StringIO)."""
    if stream is None or not data:
        return
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        buffer.write(data)
        buffer.flush()
    else:
        stream.write(data.decode("utf-8", "replace"))


def rust_main(entry: str, python_main):
    """The `main` a module of ENTRY_POINTS gets: the same signature, run as the Rust binary."""
    def main(argv=None) -> int:
        arguments = [str(argument) for argument in (sys.argv[1:] if argv is None else argv)]
        reads_stdin = entry == "mcp" or "serve" in arguments or STDIN_ARGUMENT in arguments
        done = subprocess.run([str(executable()), entry, *arguments],
                              input=_stdin_bytes() if reads_stdin else b"", capture_output=True,
                              creationflags=NO_WINDOW)
        _write(sys.stdout, done.stdout)
        _write(sys.stderr, done.stderr)
        return done.returncode

    main.__wrapped__ = python_main
    main.rust_core = entry
    main.__doc__ = "CODEX_AR_CORE=rust: %s's main, run as %s %s" % (python_main.__module__, executable().name, entry)
    return main


def engine_proxy():
    """engineproxy.py, loaded by path once."""
    found = sys.modules.get("rustdiff_engineproxy")
    if found is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("rustdiff_engineproxy", Path(__file__).resolve().with_name(
            "engineproxy.py"))
        found = importlib.util.module_from_spec(spec)
        sys.modules["rustdiff_engineproxy"] = found
        spec.loader.exec_module(found)
    return found


def advanced_proxy():
    """advproxy/, loaded by path once as the package `rustdiff_advproxy`."""
    found = sys.modules.get("rustdiff_advproxy")
    if found is None:
        import importlib.util
        directory = Path(__file__).resolve().with_name("advproxy")
        spec = importlib.util.spec_from_file_location("rustdiff_advproxy", directory / "__init__.py",
                                                      submodule_search_locations=[str(directory)])
        found = importlib.util.module_from_spec(spec)
        sys.modules["rustdiff_advproxy"] = found
        spec.loader.exec_module(found)
    return found


def surface_proxy():
    """surfaceproxy.py, loaded by path once."""
    found = sys.modules.get("rustdiff_surfaceproxy")
    if found is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("rustdiff_surfaceproxy", Path(__file__).resolve().with_name(
            "surfaceproxy.py"))
        found = importlib.util.module_from_spec(spec)
        sys.modules["rustdiff_surfaceproxy"] = found
        spec.loader.exec_module(found)
    return found


def _by_path(name: str, file: str):
    """A module beside this file, loaded by path once."""
    found = sys.modules.get(name)
    if found is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().with_name(file))
        found = importlib.util.module_from_spec(spec)
        sys.modules[name] = found
        spec.loader.exec_module(found)
    return found


def advanced(name: str) -> bool:
    """A module of the advanced package, while the advanced proxy is wanted (CODEX_AR_ADVPROXY=0 leaves the advanced
    edition the reference's under CODEX_AR_CORE=rust: core's proxies alone, to tell which side a difference is on)."""
    if os.environ.get("CODEX_AR_ADVPROXY", "1") == "0":
        return False
    return name == ADVANCED or name.startswith(ADVANCED + ".")


def patch(module) -> None:
    if module.__name__ in PLAN:
        _by_path("rustdiff_planproxy", "planproxy.py").install(module)
    if module.__name__ in SURFACE:
        surface_proxy().install(module)
        return
    if module.__name__ in PLAN:
        return
    if advanced(module.__name__):
        advanced_proxy().patch(module)
        return
    if module.__name__ == ENGINE:
        engine_proxy().install(module)
        return
    entry = ENTRY_POINTS[module.__name__]
    current = getattr(module, "main", None)
    if current is not None and not getattr(current, "rust_core", None):
        module.main = rust_main(entry, current)


class _Loader(importlib.abc.Loader):
    """The module's own loader, and then `patch`. Everything else is asked of the real loader."""

    def __init__(self, real):
        self.real = real

    def create_module(self, spec):
        return self.real.create_module(spec)

    def exec_module(self, module):
        self.real.exec_module(module)
        patch(module)

    def __getattr__(self, name):
        return getattr(self.real, name)


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name not in ENTRY_POINTS and name != ENGINE and name not in SURFACE and name not in PLAN and not advanced(name):
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                if spec.loader is not None and not isinstance(spec.loader, _Loader):
                    spec.loader = _Loader(spec.loader)
                return spec
        return None


def install() -> bool:
    """Route the entry points to Rust when CODEX_AR_CORE=rust; True when that is now so. Idempotent."""
    if not wanted():
        return False
    if not any(isinstance(finder, Finder) for finder in sys.meta_path):
        sys.meta_path.insert(0, Finder())
    for name in (*ENTRY_POINTS, ENGINE, *SURFACE, *PLAN):
        if name in sys.modules:
            patch(sys.modules[name])
    for name in [loaded for loaded in sys.modules if advanced(loaded)]:
        patch(sys.modules[name])
    return True

