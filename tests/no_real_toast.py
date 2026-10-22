"""No test raises a real Windows toast: the guard every test run loads.

On 2026-10-22 the owner kept seeing "automatic recovery cancelled" toasts that no watcher had raised. They
were test output: tests/test_downgrade.py patched notify.show_content, the notifier had bound the real one as
a default argument at import, and the command line's cancel went on to raise a real toast under the
product's own identity - on every run that included it, for twelve days, while the test passed
(plans/notif-check.md section 3). A test that reaches the real toast now fails, loudly, whichever way it
got there.

**The seam.** A toast is a PowerShell script that calls `CreateToastNotifier(...)`. It is raised only
through `subprocess.run` (codex_auto_resume/pwsh.py, of every version), so that is where the guard stands:
a real `subprocess.run` whose command carries that script raises AssertionError instead of starting
PowerShell, and the attempt is recorded. A test that patches subprocess.run, pwsh.run, notify.show or
notify.show_content puts its own stand-in in front of the guard, as it always did, and nothing changes for
it. Only Windows' notification center is guarded: the product's own card (notice_window) is a window that
the GUI tests draw on purpose.

**Loud.** The AssertionError may be swallowed - the engine's `announce` swallows every notifier failure, as
it must - so a recorded attempt also fails the test that was running when it was made (unittest's
`TestCase.run`, wrapped), and an attempt no test claimed (a worker thread after its test ended, a child
process) ends the process with exit status 1 and says why on stderr.

**Loaded by every run.** tests/sitecustomize.py installs it in any interpreter that has tests/ on its path
(PYTHONPATH="src;tests", as every local run is started), and scripts/test_parts.py installs it in the
process that runs a suite (CI's lanes put only src on the path). It imports nothing until the module it
guards is imported - an import hook, so a child process's own imports are what they were - and never
raises out of install().

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import sys

MESSAGE = "a test reached the real Windows toast"
# What every toast script of the product says (notify._SCRIPT), and nothing else it runs does.
TOAST_MARK = "CreateToastNotifier"
GUARDED = "_no_real_toast"

_hits: list = []           # each attempt: {"where": test id or None, "claimed": bool}
_state = {"installed": False}


def active() -> bool:
    """Whether the guard is installed in this interpreter."""
    return _state["installed"]


def attempts() -> int:
    """How many real toasts were attempted here (each refused)."""
    return len(_hits)


def _decoded(argument) -> str:
    import base64
    try:
        return base64.b64decode(argument).decode("utf-16-le", "replace")
    except Exception:
        return ""


def is_toast(command) -> bool:
    """Whether `command` (subprocess.run's first argument) runs a toast script, plainly or encoded."""
    try:
        if isinstance(command, (str, bytes)):
            parts = [command]
        else:
            parts = list(command)
        parts = [part.decode("utf-8", "replace") if isinstance(part, bytes) else str(part) for part in parts]
        for index, part in enumerate(parts):
            if TOAST_MARK in part:
                return True
            if part.lower() in ("-encodedcommand", "-enc", "-e", "-ec") and index + 1 < len(parts):
                if TOAST_MARK in _decoded(parts[index + 1]):
                    return True
    except Exception:
        return False
    return False


def _guard_subprocess(module) -> None:
    run = getattr(module, "run", None)
    if run is None or getattr(run, GUARDED, False):
        return
    import functools

    @functools.wraps(run)
    def guarded_run(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        if is_toast(command):
            _hits.append({"where": None, "claimed": False})
            raise AssertionError(MESSAGE + ": a test must patch notifier.deliver, notify.show_content or "
                                 "notify.show before anything raises a notice (tests/no_real_toast.py)")
        return run(*args, **kwargs)

    setattr(guarded_run, GUARDED, True)
    module.run = guarded_run


def _guard_unittest(module) -> None:
    case = getattr(module, "TestCase", None)
    if case is None or getattr(case.run, GUARDED, False):
        return
    original = case.run

    def run(self, result=None):
        before = len(_hits)
        try:
            return original(self, result)
        finally:
            fresh = [hit for hit in _hits[before:] if not hit["claimed"]]
            if fresh and result is not None:
                for hit in fresh:
                    hit["claimed"] = True
                    hit["where"] = self.id()
                error = AssertionError("%s (%d time(s)); patch notifier.deliver, notify.show_content or "
                                       "notify.show in this test (tests/no_real_toast.py)" % (MESSAGE, len(fresh)))
                result.addFailure(self, (AssertionError, error, None))

    setattr(run, GUARDED, True)
    run.__wrapped__ = original
    case.run = run


AFTER_IMPORT = {"subprocess": _guard_subprocess, "unittest.case": _guard_unittest}


class _Loader:
    """The loader a guarded module was found with, which guards the module once it has run."""

    def __init__(self, loader, after):
        self._loader, self._after = loader, after

    def create_module(self, spec):
        return self._loader.create_module(spec)

    def exec_module(self, module):
        self._loader.exec_module(module)
        try:
            self._after(module)
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._loader, name)


class _Finder:
    """Finds nothing itself: for the guarded modules only, the spec the other finders find, with a loader
    that guards the module after it runs."""

    def find_spec(self, name, path=None, target=None):
        after = AFTER_IMPORT.get(name)
        if after is None:
            return None
        for finder in sys.meta_path:
            if finder is self or not hasattr(finder, "find_spec"):
                continue
            spec = finder.find_spec(name, path, target)
            if spec is not None:
                if spec.loader is not None and hasattr(spec.loader, "exec_module"):
                    spec.loader = _Loader(spec.loader, after)
                return spec
        return None


def _at_exit() -> None:
    unclaimed = [hit for hit in _hits if not hit["claimed"]]
    if not unclaimed:
        return
    try:
        sys.stdout.flush()
        sys.stderr.write("\n%s: %d attempt(s) no test claimed - refused, and this run fails "
                         "(tests/no_real_toast.py)\n" % (MESSAGE, len(unclaimed)))
        sys.stderr.flush()
    finally:
        import os
        os._exit(1)


def install() -> bool:
    """Install the guard in this interpreter (again is nothing). True when it is installed."""
    if _state["installed"]:
        return True
    try:
        for name, after in AFTER_IMPORT.items():
            if name in sys.modules:
                after(sys.modules[name])
        if not any(isinstance(finder, _Finder) for finder in sys.meta_path):
            sys.meta_path.insert(0, _Finder())
        import atexit
        atexit.register(_at_exit)
        _state["installed"] = True
    except Exception:
        return False
    return True
