"""The twin check: every reference call, run on a second Python, and what differs between the two.

A diff stops at its first mismatch, and a mismatch between Rust and one Python says nothing of the other Python.
With CODEX_AR_REFERENCE_TWIN set (`system`, or a path, as refpython.py takes them) every `reference.run` also runs its
script on the twin Python and compares what the two did: exit code, stdout, stderr and the profile folder's files. The
run itself goes on with the chosen Python's answer alone, so a diff's verdict is unchanged. Each call that differs is
appended to CODEX_AR_REFERENCE_TWIN_LOG (a folder; `calls.jsonl` and the two answers as files) and, with the profile
restored, nothing of the twin's run is left behind.

    CODEX_AR_REFERENCE_TWIN=system CODEX_AR_REFERENCE_TWIN_LOG=<folder> python -X utf8 tests/rustdiff/run.py -k <diff>

The twin sees what the first run left outside the profile (a file a script writes elsewhere), so it is for the
readers - scripts that read what the case laid down - not for a store that writes where it reads.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from rustdiff import refpython

VARIABLE = "CODEX_AR_REFERENCE_TWIN"
LOG_VARIABLE = "CODEX_AR_REFERENCE_TWIN_LOG"
_COUNT = [0]


def twin() -> str | None:
    """The twin runtime asked for, or None."""
    return os.environ.get(VARIABLE) or None


def digest(folder: Path) -> dict:
    """Every file under `folder` by relative name: its size and sha256 (a folder is its name with None)."""
    found = {}
    for path in sorted(Path(folder).rglob("*")):
        name = path.relative_to(folder).as_posix()
        if path.is_file() and not path.is_symlink():
            found[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            found[name] = None
    return found


def restore(folder: Path, saved: Path) -> None:
    """`folder` made to hold exactly what `saved` holds."""
    for child in list(Path(folder).iterdir()):
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
    for child in Path(saved).iterdir():
        target = Path(folder) / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def log_folder() -> Path | None:
    named = os.environ.get(LOG_VARIABLE)
    if not named:
        return None
    folder = Path(named)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def twinned(start, home: Path, script: str, arguments):
    """Run `start(which)` - the reference's process on runtime `which` (None: the chosen one) - on both Pythons.
    Returns the chosen one's finished process, with `home` as that run left it."""
    other = twin()
    home = Path(home)
    with tempfile.TemporaryDirectory(prefix="rustdiff-twin-") as own:
        before, after = Path(own) / "before", Path(own) / "after"
        shutil.copytree(home, before)
        main = start(None)
        shutil.copytree(home, after)
        restore(home, before)
        second = start(other)
        left = digest(home)
        differs = [name for name, one, two in (("returncode", main.returncode, second.returncode),
                                               ("stdout", main.stdout, second.stdout),
                                               ("stderr", main.stderr, second.stderr),
                                               ("files", digest(after), left)) if one != two]
        restore(home, after)
    _COUNT[0] += 1
    folder = log_folder()
    if folder is not None and differs:
        number = _COUNT[0]
        (folder / ("%05d-chosen.out" % number)).write_bytes(main.stdout)
        (folder / ("%05d-twin.out" % number)).write_bytes(second.stdout)
        (folder / ("%05d-chosen.err" % number)).write_bytes(main.stderr)
        (folder / ("%05d-twin.err" % number)).write_bytes(second.stderr)
        entry = {"call": number, "differs": differs, "chosen": refpython.choice(), "twin": other,
                 "script": hashlib.sha256(script.encode("utf-8")).hexdigest()[:16], "head": script[:160],
                 "arguments": [str(each)[:200] for each in arguments][:6],
                 "returncodes": [main.returncode, second.returncode]}
        with (folder / "calls.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return main
