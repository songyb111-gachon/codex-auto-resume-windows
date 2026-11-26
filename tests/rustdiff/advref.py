"""The advanced reference (S7.1b): a tag's own advanced edition, in a process of its own, on scratch homes only.

`reference.py` takes `src/codex_auto_resume` out of the tag and nothing of `advanced/`. The advanced seats need the
advanced package as well: `package(tag)` extracts `src/codex_auto_resume`, `advanced/src/codex_auto_resume_advanced`
and the plugin manifest into one scratch folder (once per tag, as `released.package` does), and `run(script, ...)`
starts the reference's Python with PYTHONPATH `<folder>/src;<folder>/advanced/src` and CODEX_AR_EDITION=advanced - the
lane `advanced/tests` runs in. Every home is a scratch folder, there is no console window, and neither the shim's
variables nor this checkout's tests/ reach the process.

`PROBE` / `build()` are the Rust side's: car-adv's example `advprobe`, built in the advanced workspace on demand.
"""
from __future__ import annotations

import atexit
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from rustdiff import reference

ROOT = Path(__file__).resolve().parents[2]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ADVANCED = ROOT / "advanced" / "rust"
MANIFEST = ADVANCED / "crates" / "car-adv" / "Cargo.toml"
_EXTRACTED: dict = {}


def package(tag: str | None = None) -> Path:
    """The folder holding `src/` and `advanced/src/` of `tag` (default: the reference's), taken out of git once."""
    tag = tag or reference.TAG
    if tag in _EXTRACTED:
        return _EXTRACTED[tag]
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", tag, "src/codex_auto_resume",
                              "advanced/src/codex_auto_resume_advanced", ".codex-plugin/plugin.json"],
                             capture_output=True, creationflags=NO_WINDOW)
    if archive.returncode != 0:
        if os.environ.get("CI"):
            raise AssertionError("%s is not in this checkout; CI must fetch the tags" % tag)
        raise unittest.SkipTest("%s is not in this checkout" % tag)
    folder = Path(tempfile.mkdtemp(prefix="advref-%s-" % tag))
    atexit.register(shutil.rmtree, folder, True)
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(folder, filter="data")
    _EXTRACTED[tag] = folder
    return folder


def trees(tag: str | None = None) -> tuple:
    """(core src, advanced src) of `tag`: the two folders the advanced lane puts on the path (`src;advanced/src`)."""
    root = package(tag)
    return root / "src", root / "advanced" / "src"


def locales(tag: str | None = None) -> Path:
    """The tag's own advanced catalogs (advanced/src/codex_auto_resume_advanced/locales)."""
    return package(tag) / "advanced" / "src" / "codex_auto_resume_advanced" / "locales"


def environment(profile: Path, tag: str | None = None) -> dict:
    root = package(tag)
    return reference.scratch_environment(profile, PYTHONPATH=os.pathsep.join(
        [str(root / "src"), str(root / "advanced" / "src")]), CODEX_AR_EDITION="advanced")


def run(script: str, *arguments, profile: Path | None = None, tag: str | None = None,
        stdin: bytes | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    """Run `script` under the tag's advanced edition with `arguments` as sys.argv[1:]; stdout and stderr as bytes."""
    with tempfile.TemporaryDirectory(prefix="advref-run-") as own:
        home = Path(profile) if profile is not None else Path(own)
        # A long script (the arming scenarios') does not fit a command line: it goes in a file of the scratch folder.
        # (the reference's Python, `--reference-python`: reference.command / script_command, not sys.executable)
        if len(script) > 8000:
            path = Path(own) / "advref-script.py"
            path.write_text(script, encoding="utf-8")
            command = reference.script_command(path, *arguments, paths=trees(tag))
        else:
            command = reference.command(script, *arguments, paths=trees(tag))
        return subprocess.run(command, input=stdin,
                              capture_output=True, env=environment(home, tag), cwd=str(home),
                              creationflags=NO_WINDOW, timeout=timeout)


def popen(script: str, *arguments, profile: Path, tag: str | None = None) -> subprocess.Popen:
    """`run`, started and not waited for: the cross-process claim runs two at once."""
    return subprocess.Popen(reference.command(script, *arguments, paths=trees(tag)),
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=environment(Path(profile), tag), cwd=str(profile), creationflags=NO_WINDOW)


# ------------------------------------------------------------------------------------------------ the Rust side
def target_dir() -> Path:
    named = os.environ.get("CARGO_TARGET_DIR_ADVANCED")
    return Path(named) if named else ADVANCED / "target"


def probe_path() -> Path:
    named = os.environ.get("CODEX_AR_ADV_PROBE_EXE")
    return Path(named) if named else target_dir() / "release" / "examples" / "advprobe.exe"


def build() -> None:
    """`cargo build --release --locked --example advprobe` in the advanced workspace (CARGO_BUILD_JOBS 4 unless set)."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "4")
    subprocess.run(["cargo", "build", "--release", "--locked", "--example", "advprobe", "--manifest-path",
                    str(MANIFEST)], env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


def ensure() -> Path:
    """The probe, built when it is not there (and no CODEX_AR_ADV_PROBE_EXE names one)."""
    if not probe_path().is_file():
        build()
    return probe_path()


def ask(request: dict) -> dict:
    """One request to the probe (JSON on stdin, JSON on stdout); the parsed answer. The probe never reads a home."""
    done = subprocess.run([str(ensure())], input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, creationflags=NO_WINDOW, timeout=900)
    if done.returncode != 0:
        raise AssertionError("advprobe failed (%d): %s" % (done.returncode, done.stderr[-3000:].decode("utf-8", "replace")))
    return json.loads(done.stdout.decode("utf-8"))


def ask_raw(request: dict) -> bytes:
    """The probe's answer as the bytes it wrote."""
    done = subprocess.run([str(ensure())], input=json.dumps(request, ensure_ascii=False).encode("utf-8"),
                          capture_output=True, creationflags=NO_WINDOW, timeout=900)
    if done.returncode != 0:
        raise AssertionError("advprobe failed (%d): %s" % (done.returncode, done.stderr[-3000:].decode("utf-8", "replace")))
    return done.stdout
