"""The advanced edition, put together for a test without touching the repository.

In the repository the advanced package lives in `advanced/src/`, outside every tree the
standard build copies, and core takes it only from beside itself - from the same `src`
directory as `codex_auto_resume` (src/codex_auto_resume/edition.py). So a test that wants core
to see an advanced installation builds one: `overlay()` copies `src/` into a temporary
directory and puts the package beside the copy, where the advanced archive puts it under
payload/app/src, and `run()` starts a Python on that copy and nothing else.

Never into `src/` itself. A package copied there is an untracked file under `src/`, which
tests/test_srcscan.py refuses; and a standard run that could import it would no longer be
testing the standard edition, which tests/test_edition.py's StandardRunGuard refuses.

The advanced package's own tests need no copy: they put `advanced/src` on the path as a
directory of its own, which is enough to import the package and, on purpose, not enough for
core to take it. Run them from the repository root as

    PYTHONPATH=src python -m unittest discover -s advanced/tests

Not a test module (no `test_` prefix), so discovery does not collect it.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ADVANCED = ROOT / "advanced"
ADVANCED_SRC = ADVANCED / "src"
# The package's name. The suite may spell it; in src/ only edition.py does (tests/test_edition.py).
PACKAGE = "codex_auto_resume_advanced"
# What every shipped file under advanced/ says in its first lines, so that an audit of the
# standard archive has one string to look for. Nothing the standard build copies may spell it.
SENTINEL = "ADVANCED-EDITION-CODE"
# The trees under advanced/ whose files ship in the advanced edition; its tests do not.
SHIPPED = ("src", "gui", "skills")
# How a run says which edition it is testing. Unset is the standard edition.
LEG = "CODEX_AR_EDITION"

_SKIP = shutil.ignore_patterns("__pycache__", "*.pyc")


def overlay(where, *, package=True, replace=None) -> Path:
    """`<where>/src`: a copy of src/ with the advanced package beside it, as an advanced
    installation has it.

    `package=False` leaves the package out. `replace` maps a file of the package to the text it
    holds instead, which is how a test builds one that is damaged in a known way."""
    src = Path(where) / "src"
    shutil.copytree(ROOT / "src", src, ignore=_SKIP)
    if package:
        shutil.copytree(ADVANCED_SRC / PACKAGE, src / PACKAGE, ignore=_SKIP)
        for name, text in (replace or {}).items():
            (src / PACKAGE / name).write_text(text, encoding="utf-8")
    return src


def run(code: str, *path, cwd) -> subprocess.CompletedProcess:
    """`code` in a fresh Python whose import path is `path`, in that order.

    PYTHONPATH is replaced rather than added to, the user's site-packages are left out, and the
    edition this run was told it tests is not passed on: the child sees what it is given."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(entry) for entry in path)
    env.pop(LEG, None)
    return subprocess.run([sys.executable, "-s", "-c", code], capture_output=True, text=True,
                          encoding="utf-8", env=env, cwd=str(cwd), timeout=120)


def tracked(*trees: str) -> list[str]:
    """Every tracked path under `advanced/<tree>`, as git spells it. Loud, like srcscan's
    listing: a scan over nothing proves nothing."""
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--",
                              *("advanced/" + tree for tree in trees)],
                             capture_output=True, timeout=120)
    if listing.returncode != 0:
        raise RuntimeError("git ls-files failed: %s"
                           % listing.stderr.decode("utf-8", "replace").strip())
    names = sorted(name for name in listing.stdout.decode("utf-8").split("\0") if name)
    if not names:
        raise RuntimeError("git lists nothing under advanced/ for %s" % ", ".join(trees))
    return names
