"""The advanced edition's reference: a tag's own core AND advanced package, in a process of its own.

`reference.py` takes a tag's `src/codex_auto_resume` alone; the advanced store (seat S7.1a) needs the tag's
`advanced/src/codex_auto_resume_advanced` beside it, on the path the advanced lane puts it on
(`src;advanced/src`), with CODEX_AR_EDITION=advanced, as the brief says the advanced lane's reference runs. Both
trees come out of git together (`git archive`, once per tag, into a temporary folder), so the core and the
edition are always the same release; every home a release could look for points into a scratch folder, and the
process gets no console window.

`older(tag)` is the same for an older release, which the schema fixtures are made by: a v0.6.12 file is made by
v0.6.12's own code. Not a test module; run.py loads only `diffs*.py` and `*_diffs.py`.
"""
from __future__ import annotations

import atexit
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

import reference

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_TREES: dict = {}


def trees(tag: str) -> tuple:
    """(core src, advanced src) of `tag`, taken out of git once."""
    if tag in _TREES:
        return _TREES[tag]
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", tag, "src/codex_auto_resume",
                              "advanced/src/codex_auto_resume_advanced", ".codex-plugin/plugin.json"],
                             capture_output=True, creationflags=NO_WINDOW)
    if archive.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    folder = Path(tempfile.mkdtemp(prefix="advreference-%s-" % tag))
    atexit.register(shutil.rmtree, folder, True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter="data")
    _TREES[tag] = (folder / "src", folder / "advanced" / "src")
    return _TREES[tag]


def run(script: str, *arguments, profile: Path | None = None, tag: str | None = None,
        stdin: bytes | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run `script` under `tag`'s core and advanced packages (the reference tag by default), every home in a
    scratch folder (`profile`, or one of its own). stdout and stderr are bytes."""
    core, advanced = trees(tag or reference.TAG)
    with tempfile.TemporaryDirectory(prefix="advreference-home-") as own:
        home = Path(profile) if profile is not None else Path(own)
        environment = reference.scratch_environment(home, PYTHONPATH="%s;%s" % (core, advanced),
                                                    CODEX_AR_EDITION="advanced")
        return subprocess.run([sys.executable, "-X", "utf8", "-c", script, *map(str, arguments)],
                              input=stdin, capture_output=True, env=environment, cwd=str(home),
                              creationflags=NO_WINDOW, timeout=timeout)


def popen(script: str, *arguments, profile: Path, tag: str | None = None) -> subprocess.Popen:
    """`run`, started and not waited for: the cross-process claim runs two at once."""
    core, advanced = trees(tag or reference.TAG)
    environment = reference.scratch_environment(Path(profile), PYTHONPATH="%s;%s" % (core, advanced),
                                                CODEX_AR_EDITION="advanced")
    return subprocess.Popen([sys.executable, "-X", "utf8", "-c", script, *map(str, arguments)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
                            cwd=str(profile), creationflags=NO_WINDOW)
