"""No reference run reaches this PC's Codex or its processes (Integration 10; the main session's rule of 2026-11-27).

The reference is the real Python product. Twice on 2026-11-27 a seat's reference run, given no stand-in, fell into core's
real engine discovery and started this PC's installed codex.exe to read its version. So every process the harness starts
on a tag's package (refpython.command / script_command, and so reference.run, advref.run and popen; tests/released.py's
run) runs `PROGRAM` first, before the script:

* core's process lookups refuse: `win.kernel.processes_named` and `process_identity`, `win.inventory.resource_users`, and
  every module's own binding of them (pairing's engine lookups, transport, the loop, the CLI, `windows`, ...) - a module
  of either package that defines or imports one of these names gets the refusal as it finishes loading, so a later
  `from ... import processes_named` binds the refusal too;
* the advanced edition's `codex.inuse.backend` (core's discovery and check of the engine) refuses;
* `CODEX_AUTO_RESUME_CODEX_EXE` names a path where no codex.exe is (`NO_CODEX`): `environment()` sets it in every
  environment the harness builds (reference.scratch_environment, released.run), over whatever the runner inherited, unless
  the test hands its own (a stand-in's path, or None for discovery on its scratch homes); the program sets it too where
  the environment names none.

A test that hands its own stand-in replaces the name after this (`pairing.processes_named = fake`, `mock.patch`), which
wins. A test whose subject is the live process table of this PC (platform_live_diffs' `LIVE_SCRIPT`: explorer.exe, its own
sleepers) asks for it by name with `CODEX_AR_REFGUARD=live-processes` in the process's environment; the inuse refusal and
the missing engine path stay. tests/test_rustdiff_refguard.py holds all of it, and the list of files that may ask.

The refusal raises the tag's `AdapterError` (what core's discovery raises when a lookup fails), or RuntimeError in a tree
that has none.
"""
from __future__ import annotations

# A path where no codex.exe is (the same as advturnsworld's), for the engine of every reference run.
NO_CODEX = r"C:\nonexistent-codex-auto-resume-reference\codex.exe"
ENGINE_VARIABLE = "CODEX_AUTO_RESUME_CODEX_EXE"
# The one way to let a reference process read this PC's process table (never its Codex's engine): the variable's value.
VARIABLE = "CODEX_AR_REFGUARD"
LIVE = "live-processes"
LOOKUPS = ("processes_named", "process_identity", "resource_users")
REFUSAL = "refused: a reference run never looks up this PC's processes or its Codex (tests/rustdiff/refguard.py)"

PROGRAM = r'''
def _car_refguard():
    import importlib.abc
    import os
    import sys

    os.environ.setdefault(%(engine)r, %(missing)r)
    live = os.environ.get(%(variable)r) == %(live)r
    lookups = () if live else %(lookups)r
    packages = ("codex_auto_resume", "codex_auto_resume_advanced")

    def refusal(name):
        def refuse(*arguments, **keywords):
            try:
                from codex_auto_resume.domain.errors import AdapterError
            except Exception:
                raise RuntimeError(%(refusal)r + ": " + name) from None
            raise AdapterError(%(refusal)r + ": " + name)
        refuse.__car_refguard__ = name
        return refuse

    refusals = {name: refusal(name) for name in lookups}
    backend = refusal("inuse.backend")
    originals = []  # the real lookups, by identity: a stand-in a script set before a later import is left alone

    def guard(module):
        for name, refuse in refusals.items():
            found = module.__dict__.get(name)
            if not callable(found) or getattr(found, "__car_refguard__", None) is not None:
                continue
            if getattr(found, "__module__", None) == module.__name__:
                originals.append(found)  # defined here: the real one (kernel, inventory, an older tag's windows)
            elif not any(found is each for each in originals):
                continue
            module.__dict__[name] = refuse
        if module.__name__ == "codex_auto_resume_advanced.codex.inuse" and "backend" in module.__dict__:
            module.__dict__["backend"] = backend

    class Loader(importlib.abc.Loader):
        def __init__(self, inner):
            self.inner = inner

        def create_module(self, spec):
            return self.inner.create_module(spec)

        def exec_module(self, module):
            # the module's own loader again, before its code runs (importlib.resources, inspect and the like see the
            # loader they always saw); the guard once its code has run
            module.__loader__ = self.inner
            if getattr(module, "__spec__", None) is not None:
                module.__spec__.loader = self.inner
            self.inner.exec_module(module)
            guard(module)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    asking = set()  # the names this finder is asking the others about: another finder that asks round finds none here

    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            if fullname.split(".")[0] not in packages or fullname in asking:
                return None
            asking.add(fullname)
            try:
                for finder in sys.meta_path:
                    if finder is self or not hasattr(finder, "find_spec"):
                        continue
                    spec = finder.find_spec(fullname, path, target)
                    if spec is not None:
                        if spec.loader is not None and hasattr(spec.loader, "exec_module"):
                            spec.loader = Loader(spec.loader)
                        return spec
                return None
            finally:
                asking.discard(fullname)

    sys.meta_path.insert(0, Finder())
    for module in list(sys.modules.values()):
        if getattr(module, "__name__", "").split(".")[0] in packages:
            guard(module)


_car_refguard()
del _car_refguard
''' % {"engine": ENGINE_VARIABLE, "missing": NO_CODEX, "variable": VARIABLE, "live": LIVE, "lookups": LOOKUPS,
       "refusal": REFUSAL}


def boot(paths=(), guard: bool = True) -> str:
    """The program a reference process runs before its script (argv[1], popped): the guard, `paths` first on sys.path,
    and the script compiled as `<string>` in __main__, as `-c` runs it. The recursion limit is raised by the one frame
    this boot adds (refpython.boot's rule: a recursion stops at the depth it stops at under a plain `-c`).
    `guard=False` is for a process that is not a reference but a test lane (the advanced proxy's two lanes run
    advanced/tests, which bring tests/no_real_codex.py and their own stand-ins); TheSource test names the one file."""
    return ((PROGRAM if guard else "") + "import sys\nsys.path[0:0] = %r\nsys.setrecursionlimit(sys.getrecursionlimit() + 1)\n"
            "exec(compile(sys.argv.pop(1), '<string>', 'exec'))\n" % ([str(each) for each in paths],))


def environment(base: dict, **handed) -> dict:
    """`base` (os.environ, as a run inherits it) with the engine's path pointing nowhere - whatever the runner's own
    environment said - and then `handed`: a test's own stand-in for the engine (`CODEX_AUTO_RESUME_CODEX_EXE=path`, or
    `None` to leave it unset and ask core's discovery on the run's scratch homes, whose process lookups still refuse)."""
    out = dict(base)
    out[ENGINE_VARIABLE] = NO_CODEX
    for name, value in handed.items():
        if value is None:
            out.pop(name, None)
        else:
            out[name] = value
    return out


def guarded(argv) -> bool:
    """True when `argv` (a reference process's) runs `PROGRAM` before anything else."""
    return any(isinstance(each, str) and "_car_refguard()" in each for each in argv[:5])


__all__ = ["NO_CODEX", "ENGINE_VARIABLE", "VARIABLE", "LIVE", "LOOKUPS", "PROGRAM", "boot", "environment", "guarded"]
