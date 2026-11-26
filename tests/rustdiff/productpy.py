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
    interpreter()                 the bundled python.exe (refpython's: the zip of this tree or of a sibling worktree, checked
                                  by SHA-256, unpacked into a scratch folder of the run and removed at its end)
    run(argv)                     `-c script args` or a script file on it, through refpython's command / script_command

Follow-3.14 (D): this module no longer unpacks a runtime of its own. The embeddable runtime ignores PYTHONPATH (its `._pth`
makes it isolated), so `refpython.command` puts the folders on sys.path by a three-line boot, as for the reference. The
generators are pinned to the bundled runtime whatever `--reference-python` says: a table of Python's Unicode is the
product's Python's, not the reference's choice (under `system` the diffs that read the reference differ by design; these
do not).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MAKE_RELEASE = ROOT / "build" / "make_release.py"
# The Unicode version of each CPython the product may ship (docs.python.org, "unicodedata.unidata_version"): 3.13 is 15.1.0,
# 3.14 is 16.0.0. A generator refuses a runtime whose own unicodedata says otherwise.
UNICODE_OF = {"3.13": "15.1.0", "3.14": "16.0.0"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GUARD = "CAR_UNICODE_REEXEC"
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


def _refpython():
    """refpython.py (the reference's Python: one unpacking of the bundled runtime for the whole run), whether this module is
    loaded as `rustdiff.productpy` or, by a generator, as the top-level `productpy`."""
    try:
        from rustdiff import refpython
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import refpython
    return refpython


def interpreter() -> Path:
    """python.exe of the bundled runtime: refpython's, pinned to `bundled` whatever `--reference-python` says (the product's
    Unicode tables are the product's Python's, not the reference's choice)."""
    return _refpython().interpreter("bundled")


def run(argv, *, env=None, cwd=None, capture=False) -> subprocess.CompletedProcess:
    """`python.exe -X utf8 *argv` of the bundled runtime (`-c script args`, or a script file and its arguments), no console
    window, through refpython's own command (`command` / `script_command`): an embeddable runtime ignores PYTHONPATH, so the
    folders the environment names go onto sys.path by the boot."""
    environment = dict(os.environ if env is None else env)
    paths = [entry for entry in environment.get("PYTHONPATH", "").split(os.pathsep) if entry]
    words = [str(each) for each in argv]
    refpython = _refpython()
    if words[0] == "-c":
        command = refpython.command(words[1], *words[2:], paths=paths, which="bundled")
    else:
        command = refpython.script_command(words[0], *words[1:], paths=paths, which="bundled")
    return subprocess.run(command, env=environment, cwd=cwd, creationflags=NO_WINDOW, capture_output=capture)


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
