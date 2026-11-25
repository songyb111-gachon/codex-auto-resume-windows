"""The Python the product ships, 3.14.10 (Unicode 16.0.0), as the Unicode generators and their checks use it.

`build/make_release.py` bundles the embeddable CPython `PYTHON_VERSION` (3.14.10), whose `unicodedata` is Unicode 16.0.0.
Every Unicode table the Rust crates read (`str.isspace`, `int()`'s decimal digits, `unicodedata.bidirectional`,
`str.isprintable`, `str.lower`/`casefold`, `\\w`, `str.isalnum`) has to be the product's, not this PC's system Python's
(3.13.15 is Unicode 15.1.0: 80 digits `int()` reads in the product and Rust refused, REVIEW-surface S1).

This module is where the three generators (gen_tables, gen_codex, gen_policy) learn which runtime that is, find it,
and run themselves under it:

    version(), unicode()          the pin, read from build/make_release.py (PYTHON_VERSION, and the Unicode of it below)
    stamp(), made_by(text)        the words a generated file carries, and the (python, unicode) a file's line says
    stale(text, what)             why a generated file is refused (made by another Python or Unicode), or None
    ensure(script, argv)          run `script` again under the bundled interpreter when this one is not it (returns the
                                  exit code), or None when this process already is it
    interpreter()                 the bundled python.exe, unpacked into a scratch folder of its own

The runtime is the zip `build/cache/python-<version>-embed-amd64.zip` of this tree or of a sibling worktree (CI downloads
it the way `make_release.py` does, by SHA-256), unpacked beside the system temp folder, never into the repository's
build/ and never over a Python someone installed. The embeddable runtime ignores PYTHONPATH (its `._pth` makes it
isolated), so the copy's `._pth` turns `site` on and a `sitecustomize.py` there gives PYTHONPATH back and then runs the
tree's own tests/sitecustomize.py (the guards that keep a test off the real toast and the real Codex): a runner started
by it (`run.py`, with `PYTHONPATH="src;tests"`) runs the reference on it too.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MAKE_RELEASE = ROOT / "build" / "make_release.py"
# The Unicode version of each CPython the product may ship (docs.python.org, "unicodedata.unidata_version"): 3.13 is 15.1.0,
# 3.14 is 16.0.0. A generator refuses a runtime whose own unicodedata says otherwise.
UNICODE_OF = {"3.13": "15.1.0", "3.14": "16.0.0"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GUARD = "CAR_UNICODE_REEXEC"
SITECUSTOMIZE = '''"""PYTHONPATH for the embeddable runtime (its ._pth ignores it), then the tree's own sitecustomize, if any.
Made by tests/rustdiff/productpy.py; nothing here is the product's."""
import os as _os
import sys as _sys

_extra = [entry for entry in _os.environ.get("PYTHONPATH", "").split(_os.pathsep) if entry]
_sys.path[1:1] = [entry for entry in _extra if entry not in _sys.path]
for _entry in _extra:
    _file = _os.path.join(_entry, "sitecustomize.py")
    if _os.path.isfile(_file) and _os.path.abspath(_file) != _os.path.abspath(__file__):
        try:
            import importlib.util as _util
            _spec = _util.spec_from_file_location("sitecustomize_of_the_tree", _file)
            _module = _util.module_from_spec(_spec)
            _spec.loader.exec_module(_module)
        except Exception as _error:   # never in the way of the interpreter
            _sys.stderr.write("the tree's sitecustomize did not load (%r)\\n" % (_error,))
        break
'''


def _pin(name: str) -> str:
    found = re.search(r'^%s\s*=\s*"([^"]+)"' % name, MAKE_RELEASE.read_text(encoding="utf-8"), re.M)
    if found is None:
        raise SystemExit("build/make_release.py has no %s: productpy.py reads the product's Python from it" % name)
    return found.group(1)


def version() -> str:
    """The bundled Python's version, `PYTHON_VERSION` of build/make_release.py (3.14.10)."""
    return _pin("PYTHON_VERSION")


def unicode() -> str:
    """The Unicode version that Python has (16.0.0)."""
    return UNICODE_OF[".".join(version().split(".")[:2])]


def stamp() -> str:
    """What a generated file says made it: this process's own runtime and its `unicodedata`, as they are (the generators
    run under the product's Python, `ensure`, so it is that one)."""
    import unicodedata
    return "Python %s (unicodedata %s, the product's bundled runtime)" % (
        ".".join(map(str, sys.version_info[:3])), unicodedata.unidata_version)


MADE_BY = re.compile(r"Python (\d+\.\d+\.\d+) \(unicodedata (\d+\.\d+\.\d+)")


def made_by(text: str):
    """(python, unicode) the generated file `text` says it was made by, or None when it says nothing."""
    found = MADE_BY.search(chr(10).join(text.splitlines()[:6]))
    if found is not None:
        return found.group(1), found.group(2)
    head = chr(10).join(text.splitlines()[:6])  # a table the first generators made: "Python 3.13.15's ... (`unicodedata` 15.1.0)"
    python, unicode_ = re.search(r"Python (\d+\.\d+\.\d+)", head), re.search(r"(?:unicodedata`?|Unicode) (\d+\.\d+\.\d+)", head)
    return None if python is None or unicode_ is None else (python.group(1), unicode_.group(1))


def is_product() -> bool:
    """Whether this process is the product's Python and its unicodedata is the Unicode that Python has."""
    import unicodedata
    return ".".join(map(str, sys.version_info[:3])) == version() and unicodedata.unidata_version == unicode()


def stale(text: str, what: str) -> str | None:
    """None when the generated file `text` says it was made by the product's Python and Unicode; else why it is refused."""
    said = made_by(text)
    if said is None:
        return "%s says which Python and Unicode made it nowhere: regenerate it with the product's Python" % what
    if said != (version(), unicode()):
        return ("%s was made by Python %s (Unicode %s); the product ships Python %s (Unicode %s): regenerate it "
                "(--write)" % (what, said[0], said[1], version(), unicode()))
    return None


def _archive() -> Path:
    name = "python-%s-embed-amd64.zip" % version()
    wanted = _pin("PYTHON_SHA256")
    named = os.environ.get("CAR_PRODUCT_PYTHON_ZIP")
    here = [Path(named)] if named else []
    here += [ROOT / "build" / "cache" / name]
    here += sorted(ROOT.parent.glob("*/build/cache/" + name))
    for candidate in here:
        if candidate.is_file() and hashlib.sha256(candidate.read_bytes()).hexdigest() == wanted:
            return candidate
    raise SystemExit("the product's Python %s (%s) is not at build/cache here or in a sibling worktree: run build/make_release.py "
                     "once, or name the zip in CAR_PRODUCT_PYTHON_ZIP" % (version(), name))


def interpreter() -> Path:
    """python.exe of the bundled runtime, unpacked (once) into a folder of its own under the system temp folder."""
    folder = Path(tempfile.gettempdir()) / ("car-product-python-%s-%s" % (version(), _pin("PYTHON_SHA256")[:8]))
    exe = folder / "python.exe"
    marker = folder / "car-product-python.ok"
    if not (exe.is_file() and marker.is_file()):
        part = folder.with_name(folder.name + ".part-%d" % os.getpid())
        part.mkdir(parents=True, exist_ok=False)
        try:
            with zipfile.ZipFile(_archive()) as archive:
                archive.extractall(part)
            pth = next(part.glob("python3*._pth"))
            pth.write_text("\n".join([pth.stem + ".zip", ".", "import site", ""]), encoding="utf-8", newline="\n")
            (part / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8", newline="\n")
            (part / "car-product-python.ok").write_text(version() + "\n", encoding="utf-8")
            if not folder.exists():
                part.rename(folder)
        finally:
            if part.exists():
                import shutil
                shutil.rmtree(part, ignore_errors=True)
    return exe


def run(argv, *, env=None, cwd=None, capture=False) -> subprocess.CompletedProcess:
    """`python.exe -X utf8 *argv` of the bundled runtime, no console window."""
    environment = dict(os.environ if env is None else env)
    return subprocess.run([str(interpreter()), "-X", "utf8", *map(str, argv)], env=environment, cwd=cwd,
                          creationflags=NO_WINDOW, capture_output=capture)


def ensure(script, argv) -> int | None:
    """None when this process is the product's Python; else `script argv` run under it, and its exit code (a generator
    returns that from main). A process the product's Python itself started never starts a third one."""
    if is_product():
        return None
    if os.environ.get(GUARD):
        raise SystemExit("this is Python %s, not the product's %s, and the product's Python started it" % (
            ".".join(map(str, sys.version_info[:3])), version()))
    environment = dict(os.environ)
    environment[GUARD] = "1"
    paths = [str(ROOT / "src"), str(ROOT / "tests")]
    environment["PYTHONPATH"] = os.pathsep.join(paths + [environment["PYTHONPATH"]] if environment.get("PYTHONPATH") else paths)
    done = run([str(script), *argv], env=environment, cwd=str(ROOT), capture=True)  # no console: the child's words are relayed
    for stream, data in ((sys.stdout, done.stdout), (sys.stderr, done.stderr)):
        stream.write(data.decode("utf-8", "replace"))
        stream.flush()
    return done.returncode
