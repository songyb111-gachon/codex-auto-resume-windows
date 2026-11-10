"""Local Windows Codex auto-resume, limited to desktop-owned loaded threads.

`__version__` is read from the plugin manifest rather than written here. There used to be a
literal in this file, and it sat at the first release's number through four more of them
while everything else - the manifest, the settings window, the release archive - moved on.
One number that everything reads cannot go stale the way two numbers do.
"""
import os as _os
import sys as _sys

# PEP 810, Python 3.15: every import of this package and of what it uses waits for the name's first use, on the bundled
# runtime. The one switch: off in this version, which bundles 3.14 (docs/DEVELOPMENT.md, "The day the bundled Python
# moves", has what was measured). Set here and not on the command lines, because the product's interpreters are started
# from three languages in eight places (-X disable-remote-debug in each), and every one of them imports this package first.
LAZY_IMPORTS = False


def _lazy_imports(wanted, interpreter=_sys) -> None:
    """All imports lazy from here on where that is wanted and this is the bundled interpreter (<home>\\runtime\\python.exe);
    a source run stays as it is. Before 3.15 there is nothing to set."""
    start = getattr(interpreter, "set_lazy_imports", None)
    if wanted and start is not None and _os.path.basename(_os.path.dirname(interpreter.executable)).lower() == "runtime":
        start("all")


_lazy_imports(LAZY_IMPORTS)


def __getattr__(name):
    # Resolved on demand: importing this package should not read a file, and most callers
    # never ask for the version at all.
    if name == "__version__":
        from .config import version
        return version()
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
