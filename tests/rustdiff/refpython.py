"""Which Python runs the reference.

The product ships CPython 3.14.10 as its bundled embeddable runtime (build/make_release.py PYTHON_VERSION,
build/runtime_keep.json), and a person may choose python.org's newer one; a diff whose reference runs on whatever
`sys.executable` happens to be (3.13.15 on the PC that wrote them) hides every place the versions differ: json's nesting
depth, `ntpath.realpath`, junction handling, Unicode tables. So the reference runs on the bundled runtime by default.

    CODEX_AR_REFERENCE_PYTHON = bundled   the embeddable 3.14.10 zip, unpacked once per run into a scratch folder (default)
                                system    this interpreter (`sys.executable`), as the harness ran before
                                <path>    a python.exe, a folder holding one, or an embeddable runtime's .zip
                                          (python-3.15.2-embed-amd64.zip, say), also unpacked into a scratch folder

`run.py --reference-python VALUE` sets the variable; the variable is what child processes (rediff_*.py, which start
run.py) inherit. `interpreter()` is the one place that resolves it.

The zip is build/make_release.py's: `make_release.PYTHON_ZIP`, checked against `make_release.PYTHON_SHA256`. It is looked
for, in order, at CODEX_AR_RUNTIME_ZIP, in this checkout's build/cache, and in the build/cache of the repository's other
worktrees (the cache is not tracked, so a worktree made for one task has none); on CI and nowhere else, a zip that is
nowhere is fetched by `make_release.fetch_runtime()` - there is no fetch of this module's own. Nothing is copied into the
repository: the zip is read where it lies and unpacked in a temporary folder that goes when the run ends.

An embeddable runtime ignores PYTHONPATH and the working folder (its python314._pth file makes it isolated), so the
reference's source reaches it through `boot()`, a few lines in front of the script that put the folders on sys.path -
what the product's own entry points do (make_release.collect_runtime), and nothing in the person's environment.

Stdlib only, and the tag's own code: if a diff's script ever needs a package the embeddable runtime lacks, `check()`
(run once, when the runtime is first resolved) names the import that failed.

Every reference process runs refguard.py's program first, on any runtime (Integration 10): core's process lookups and the
advanced edition's engine discovery refuse, and CODEX_AUTO_RESUME_CODEX_EXE points where no codex.exe is, unless the
caller's environment names one. So `command` and `script_command` always start through the boot, an installed
interpreter too (its PYTHONPATH then names the same folders the boot puts first).
"""
from __future__ import annotations

import atexit
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

try:
    from rustdiff import refguard
except ImportError:  # loaded by path, without tests/ on sys.path
    _spec = importlib.util.spec_from_file_location("rustdiff_refguard", Path(__file__).resolve().parent / "refguard.py")
    refguard = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(refguard)

ROOT =Path(__file__).resolve().parents[2]
VARIABLE = "CODEX_AR_REFERENCE_PYTHON"
ZIP_VARIABLE = "CODEX_AR_RUNTIME_ZIP"
# What `interpreter()` has resolved in this process, and the variable a child process finds it again by (so a run.py
# that started `rediff_*.py` that started run.py unpacks one runtime, not three).
RESOLVED_VARIABLE = "CODEX_AR_REFERENCE_PYTHON_EXE"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DEFAULT = "bundled"
_CACHE: dict = {}
# The imports the reference's own code makes of the standard library that an embeddable runtime might lack (the product
# trims its copy to runtime_keep.json's list; the untrimmed zip has them all, and this names a missing one early).
CHECK = ("import json, sqlite3, ctypes, ctypes.wintypes, winreg, unicodedata, hashlib, ssl, uuid, zipfile, "
         "urllib.request, logging.handlers, tomllib, zoneinfo, decimal, queue, socket, select, "
         "sys; print(sys.version.split()[0])")


def choice() -> str:
    """The value asked for: the variable, else `bundled`."""
    return os.environ.get(VARIABLE) or DEFAULT


def select(value: str) -> None:
    """Make `value` the choice of this process and of every child it starts."""
    os.environ[VARIABLE] = value
    os.environ.pop(RESOLVED_VARIABLE, None)
    _CACHE.clear()


def _make_release():
    """build/make_release.py, loaded by path under its own name (the build's tests import it the same way)."""
    loaded = sys.modules.get("make_release")
    if loaded is not None:
        return loaded
    path = ROOT / "build" / "make_release.py"
    spec = importlib.util.spec_from_file_location("make_release", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_release"] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop("make_release", None)
        raise
    return module


def _worktrees() -> list:
    """Every worktree of this repository (the first is the main one); empty where git cannot say."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True,
                              text=True, encoding="utf-8", creationflags=NO_WINDOW, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [Path(line[len("worktree "):]) for line in done.stdout.splitlines() if line.startswith("worktree ")]


def bundled_zip() -> Path:
    """The bundled runtime's zip, with its digest checked against build/make_release.py's pin."""
    make_release = _make_release()
    name = make_release.PYTHON_ZIP
    candidates = []
    if os.environ.get(ZIP_VARIABLE):
        candidates.append(Path(os.environ[ZIP_VARIABLE]))
    candidates.append(ROOT / "build" / "cache" / name)
    candidates.extend(each / "build" / "cache" / name for each in _worktrees())
    for each in candidates:
        if each.is_file():
            archive = each
            break
    else:
        if not os.environ.get("CI"):
            raise RuntimeError(
                "the bundled runtime %s is not in any build/cache here (looked in %s). Put it there by running "
                "build/make_release.py (its fetch_runtime), or name it with %s, or run with --reference-python system"
                % (name, ", ".join(str(each.parent) for each in candidates), ZIP_VARIABLE))
        archive = make_release.fetch_runtime()  # CI: the build's own fetch, which checks the digest too
    import hashlib

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != make_release.PYTHON_SHA256:
        raise RuntimeError("%s is not the pinned runtime: sha256 %s, build/make_release.py pins %s"
                           % (archive, digest, make_release.PYTHON_SHA256))
    return archive


def _unpack(archive: Path) -> Path:
    """The runtime's .zip unpacked into a new scratch folder (removed when this process ends); its python.exe."""
    folder = Path(tempfile.mkdtemp(prefix="rustdiff-refpython-"))
    atexit.register(shutil.rmtree, folder, True)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            target = (folder / name).resolve()
            if folder.resolve() not in target.parents and target != folder.resolve():
                raise RuntimeError("%s holds a member outside its folder: %s" % (archive, name))
        bundle.extractall(folder)
    exe = folder / "python.exe"
    if not exe.is_file():
        raise RuntimeError("%s holds no python.exe" % archive)
    return exe


def _resolve(value: str) -> Path:
    if value == "system":
        return Path(sys.executable)
    if value == "bundled":
        return _unpack(bundled_zip())
    path = Path(value)
    if path.is_dir():
        path = path / "python.exe"
    if path.suffix.lower() == ".zip" and path.is_file():
        return _unpack(path)
    if not path.is_file():
        raise RuntimeError("--reference-python %r is none of bundled, system, a python.exe, a folder with one or a "
                           "runtime .zip" % value)
    return path


def interpreter(value: str | None = None) -> Path:
    """The python.exe the reference runs on, resolved (and unpacked) once per process, once per run across children.
    `value` names another runtime (the twin of reftwin.py: `system`, a path); the choice itself when it is None."""
    if value is not None and value != choice():
        if ("exe", value) not in _CACHE:
            exe = _resolve(value)
            check(exe)
            _CACHE[("exe", value)] = exe
        return _CACHE[("exe", value)]
    if "exe" in _CACHE:
        return _CACHE["exe"]
    handed = os.environ.get(RESOLVED_VARIABLE)
    if handed and os.environ.get(VARIABLE) and Path(handed).is_file():
        _CACHE["exe"] = Path(handed)
        return _CACHE["exe"]
    exe = _resolve(choice())
    ready = check(exe)
    _CACHE["exe"], _CACHE["version"] = exe, ready
    os.environ[RESOLVED_VARIABLE] = str(exe)
    if not os.environ.get(VARIABLE):
        os.environ[VARIABLE] = DEFAULT
    return exe


def check(exe: Path) -> str:
    """The runtime's version, after one start that imports what the reference's code imports; names what is missing."""
    done = subprocess.run([str(exe), "-X", "utf8", "-c", CHECK], capture_output=True, text=True, encoding="utf-8",
                          creationflags=NO_WINDOW, timeout=120)
    if done.returncode != 0:
        raise RuntimeError("the reference Python %s lacks what the reference imports:\n%s" % (exe, done.stderr[-1500:]))
    return done.stdout.strip()


def version() -> str:
    """`3.14.10`, say: the reference interpreter's own."""
    interpreter()
    if "version" not in _CACHE:
        _CACHE["version"] = check(_CACHE["exe"])
    return _CACHE["version"]


def ignores_environment(exe: Path) -> bool:
    """True for an embeddable runtime: a python3XX._pth beside it makes it ignore PYTHONPATH and the working folder."""
    return any(Path(exe).parent.glob("python*._pth"))


def boot(paths, guard: bool = True) -> str:
    """The program text that runs `script` (argv[1]) with `paths` on sys.path, for a runtime that ignores PYTHONPATH.
    `sys.argv` is what `-c script args` would have given: ['-c', *args]. It runs in __main__, as -c does. The script runs
    one Python frame deeper than under -c (this boot's own module frame), so the recursion limit is raised by that one
    frame: a recursion the product's entry points (`-c`, no exec) stop at depth N stops at N here too (Integration 8:
    the MCP server's batch depth, RecursionError at 995 under -c, came at 994 under this boot)."""
    return refguard.boot(paths, guard)  # the guard first (refguard.py), then the path and the frame's recursion room


def command(script: str, *arguments, paths=(), which: str | None = None) -> list:
    """The argv that runs `script` with `arguments` as sys.argv[1:] on the reference Python, `paths` first on sys.path
    (also given as PYTHONPATH by the caller, which a runtime that honours it needs and one that does not ignores).
    `which` names another runtime than the chosen one (reftwin.py)."""
    exe = interpreter(which)
    return [str(exe), "-X", "utf8", "-c", boot(paths), script, *map(str, arguments)]


# A script FILE under a runtime that ignores PYTHONPATH: `boot` has run, `sys.argv` is ['-c', path, *arguments]; the file runs
# as `__main__` with the argv `python path arguments` gives it (and sys.exit's code is the process's).
FILE_RUNNER = ("import runpy, sys\npath = sys.argv[1]\nsys.argv[:] = sys.argv[1:]\n"
               "runpy.run_path(path, run_name='__main__')")


def script_command(path, *arguments, paths=(), which: str | None = None, guard: bool = True) -> list:
    """The argv that runs the script FILE `path` with `arguments` on the reference Python, `paths` first on its sys.path: what
    `command` is for a script's text (the generators, and a long script the command line cannot hold). `guard=False`
    only for a test lane that is no reference (refguard.boot)."""
    exe = interpreter(which)
    if ignores_environment(exe):
        return [str(exe), "-X", "utf8", "-c", boot(paths, guard), FILE_RUNNER, str(path), *map(str, arguments)]
    # an installed interpreter put the script's own folder first, as `python path` does
    return [str(exe), "-X", "utf8", "-c", boot([Path(path).resolve().parent, *paths], guard), FILE_RUNNER, str(path),
            *map(str, arguments)]


def describe() -> str:
    """One line for run.py's header and the README's runs: the choice, the version and the exe's kind."""
    exe = interpreter()
    return "python %s (%s: %s)" % (version(), choice(), "embeddable" if ignores_environment(exe) else "installed")
