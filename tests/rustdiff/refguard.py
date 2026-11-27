"""No reference run reaches this PC's Codex or its processes (Integration 10; the main session's rule of 2026-11-27).

The reference is the real Python product. Twice on 2026-11-27 a seat's reference run, given no stand-in, fell into core's
real engine discovery and started this PC's installed codex.exe to read its version. So every process the harness starts
on a tag's package (refpython.command / script_command, and so reference.run, advref.run and popen; tests/released.py's
run) runs `PROGRAM` first, before the script:

* core's lookups refuse: `win.kernel.processes_named`, `process_identity` and `package_roots` (the installed app
  packages, where the Codex app keeps its engine), `win.inventory.resource_users`, and every module's own binding of them
  (pairing's engine lookups, transport, the loop, the CLI, `windows`, ...) - a module of either package that defines or
  imports one of these names gets the refusal as it finishes loading, so a later `from ... import X` binds it too;
* the advanced edition's `codex.inuse.backend` (core's discovery and check of the engine) refuses;
* `CODEX_AUTO_RESUME_CODEX_EXE` names a path where no codex.exe is (`NO_CODEX`): `environment()` sets it in every
  environment the harness builds (reference.scratch_environment, released.run), over whatever the runner inherited; the
  program sets it too where the environment names none;
* no program called codex (codex.exe, codex.cmd, codex.ps1, codex) starts from outside the system's temporary folder,
  where every scratch tree lives - the last door, whatever a script did before it (`subprocess.Popen` refuses it with
  PermissionError).

A test that hands its own stand-in replaces the name after this (`pairing.processes_named = fake`, `mock.patch`), which
wins. Two ways out, each asked by name in the process's environment (`CODEX_AR_REFGUARD`) and held by
tests/test_rustdiff_refguard.py:

* `live-processes` - the live process table of this PC is the subject (platform_live_diffs' `LIVE_SCRIPT`: explorer.exe,
  the test's own sleepers): the lookups are the tag's own; inuse, the engine path and the door stay.
* `discovery` - core's discovery itself is the subject (the files in `DISCOVERY_SUBJECTS` alone, through
  `discovery_environment`): the real `inuse.backend` stays and the engine path is unset, so discovery runs - on a scratch
  tree only. The program first checks that LOCALAPPDATA, APPDATA, USERPROFILE, HOME, CODEX_HOME and every program-files
  root lie inside `CODEX_AR_REFGUARD_SCRATCH` and that no folder on PATH holds a codex program, and exits 97 otherwise;
  the lookups stay refused (the script stands in for them); whatever `config.discover_codex_exe` finds must lie inside the
  scratch tree (else it raises), and a codex program starts only from inside it.

The refusal raises the tag's `AdapterError` (what core's discovery raises when a lookup fails), or RuntimeError in a tree
that has none; each refusal keeps the tag's own function as `__car_refguard_original__`.
"""
from __future__ import annotations

import os
from pathlib import Path

# A path where no codex.exe is (the same as advturnsworld's), for the engine of every reference run.
NO_CODEX = r"C:\nonexistent-codex-auto-resume-reference\codex.exe"
ENGINE_VARIABLE = "CODEX_AUTO_RESUME_CODEX_EXE"
VARIABLE = "CODEX_AR_REFGUARD"
SCRATCH_VARIABLE = "CODEX_AR_REFGUARD_SCRATCH"
LIVE = "live-processes"
DISCOVERY = "discovery"
LOOKUPS = ("processes_named", "process_identity", "package_roots", "resource_users")
REFUSAL = "refused: a reference run never looks up this PC's processes or its Codex (tests/rustdiff/refguard.py)"
# The only files whose subject is core's discovery: they alone may run a reference with `DISCOVERY` (the main session's
# word of 2026-11-27, Integration 10). tests/test_rustdiff_refguard.py holds the list against the source.
DISCOVERY_SUBJECTS = ("tests/rustdiff/advcodex.py",)
# Every variable a home or an installation root is read from: in `DISCOVERY` all of them lie inside the scratch tree.
HOMES = ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "CODEX_HOME", "ProgramW6432", "ProgramFiles",
         "ProgramFiles(x86)", "ProgramData", "CommonProgramFiles", "CommonProgramW6432", "CommonProgramFiles(x86)")
CODEX_NAMES = ("codex.exe", "codex.cmd", "codex.ps1", "codex.bat", "codex")

PROGRAM = r'''
def _car_refguard():
    import importlib.abc
    import os
    import subprocess
    import sys
    import tempfile

    mode = os.environ.get(%(variable)r)
    live, discovery = mode == %(live)r, mode == %(discovery)r
    names = %(names)r

    def inside(path, root):
        try:
            path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
        except (OSError, ValueError):
            return False
        return path == root or path.startswith(root.rstrip("\\/") + os.sep)

    if discovery:
        root = os.environ.get(%(scratch)r) or ""
        wrong = [name for name in %(homes)r if os.environ.get(name) and not inside(os.environ[name], root)]
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            if folder and any(os.path.exists(os.path.join(folder, each)) for each in names):
                wrong.append("PATH " + folder)
        if not root or not os.path.isdir(root) or wrong:
            sys.stderr.write("refguard: a discovery run off its scratch tree %%r: %%s\n" %% (root, ", ".join(wrong)))
            sys.stderr.flush()
            os._exit(97)
        allowed = root
    else:
        os.environ.setdefault(%(engine)r, %(missing)r)
        allowed = tempfile.gettempdir()
    lookups = () if live else %(lookups)r
    packages = ("codex_auto_resume", "codex_auto_resume_advanced")

    def refusal(name, original=None):
        def refuse(*arguments, **keywords):
            try:
                from codex_auto_resume.domain.errors import AdapterError
            except Exception:
                raise RuntimeError(%(refusal)r + ": " + name) from None
            raise AdapterError(%(refusal)r + ": " + name)
        refuse.__car_refguard__ = name
        refuse.__car_refguard_original__ = original
        return refuse

    originals = []  # the real lookups, by identity: a stand-in a script set before a later import is left alone

    def guard(module):
        for name in lookups:
            found = module.__dict__.get(name)
            if not callable(found) or getattr(found, "__car_refguard__", None) is not None:
                continue
            if getattr(found, "__module__", None) == module.__name__:
                originals.append(found)  # defined here: the real one (kernel, inventory, an older tag's windows)
            elif not any(found is each for each in originals):
                continue
            module.__dict__[name] = refusal(name, found)
        if module.__name__ == "codex_auto_resume_advanced.codex.inuse" and "backend" in module.__dict__ \
                and not discovery:
            module.__dict__["backend"] = refusal("inuse.backend", module.__dict__["backend"])
        if discovery and module.__name__ == "codex_auto_resume.config" and "discover_codex_exe" in module.__dict__:
            found = module.__dict__["discover_codex_exe"]

            def discover_codex_exe(*arguments, **keywords):
                path = found(*arguments, **keywords)
                if not inside(str(path), allowed):
                    raise RuntimeError(%(refusal)r + ": discovery found %%s, outside the scratch tree %%s" %% (path, allowed))
                return path
            discover_codex_exe.__car_refguard_original__ = found
            module.__dict__["discover_codex_exe"] = discover_codex_exe

    started = subprocess.Popen._execute_child

    def program(args, executable):
        if executable:
            return str(executable)
        if isinstance(args, (list, tuple)):
            return str(args[0]) if args else ""
        text = os.fsdecode(args) if isinstance(args, bytes) else str(args)
        text = text.lstrip()
        if text.startswith('"'):
            return text[1:].split('"', 1)[0]
        return text.split(None, 1)[0] if text else ""

    def execute_child(self, args, executable, *rest, **keywords):
        exe = program(args, executable)
        if os.path.basename(exe.replace("/", "\\")).lower() in names and not inside(exe, allowed):
            raise PermissionError(%(refusal)r + ": starting " + exe)
        return started(self, args, executable, *rest, **keywords)

    subprocess.Popen._execute_child = execute_child

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
       "refusal": REFUSAL, "discovery": DISCOVERY, "scratch": SCRATCH_VARIABLE, "homes": HOMES, "names": CODEX_NAMES}


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
    environment said - and then `handed`: a test's own stand-in for the engine (`CODEX_AUTO_RESUME_CODEX_EXE=path`)."""
    out = dict(base)
    out[ENGINE_VARIABLE] = NO_CODEX
    for name, value in handed.items():
        if value is None:
            out.pop(name, None)
        else:
            out[name] = value
    return out


def system_path() -> str:
    """The folders of Windows itself, and nothing that could hold a codex program (checked)."""
    windows = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    folders = [os.path.join(windows, "System32"), windows, os.path.join(windows, "System32", "Wbem"),
               os.path.join(windows, "System32", "WindowsPowerShell", "v1.0")]
    for folder in folders:
        for name in CODEX_NAMES:
            if os.path.exists(os.path.join(folder, name)):
                raise RuntimeError("refguard: %s holds %s; no discovery run can be made here" % (folder, name))
    return os.pathsep.join(folders)


def discovery_environment(base: dict, scratch) -> dict:
    """For a file of `DISCOVERY_SUBJECTS` only: `base` (a scratch environment) made a discovery run on the scratch tree
    `scratch` - every home and program-files root inside it (each one `base` already put inside is kept), PATH Windows' own
    folders alone, the engine's path unset, `CODEX_AR_REFGUARD=discovery`. Both sides of a diff get it."""
    root = Path(scratch).resolve()
    out = dict(base)
    for name in HOMES:
        value = out.get(name)
        if not value or not _inside(value, root):
            out[name] = str(root / "_refguard" / name.replace("(", "").replace(")", ""))
    out["PATH"] = system_path()
    out.pop(ENGINE_VARIABLE, None)
    out[VARIABLE] = DISCOVERY
    out[SCRATCH_VARIABLE] = str(root)
    return out


def _inside(path, root) -> bool:
    try:
        path, root = os.path.normcase(os.path.realpath(path)), os.path.normcase(os.path.realpath(root))
    except (OSError, ValueError):
        return False
    return path == root or path.startswith(root.rstrip("\\/") + os.sep)


def guarded(argv) -> bool:
    """True when `argv` (a reference process's) runs `PROGRAM` before anything else."""
    return any(isinstance(each, str) and "_car_refguard()" in each for each in argv[:5])


__all__ = ["NO_CODEX", "ENGINE_VARIABLE", "VARIABLE", "SCRATCH_VARIABLE", "LIVE", "DISCOVERY", "LOOKUPS",
           "DISCOVERY_SUBJECTS", "HOMES", "CODEX_NAMES", "PROGRAM", "boot", "environment", "system_path",
           "discovery_environment", "guarded"]
