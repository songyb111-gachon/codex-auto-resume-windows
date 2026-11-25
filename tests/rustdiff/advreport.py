"""What the compatibility report's and the Stop hook's diffs share (seat S7.3c): the reference runner, the Rust example, a family.

A family is a script run under the reference tag's own advanced edition (`advref.run`, the lane `advanced/tests` runs in:
the tag's core and advanced trees, CODEX_AR_EDITION=advanced, every home a scratch folder). It makes the homes a case
needs through the tag's own fixtures (`advanced/tests/reportfixtures.py`, `ghfake.py`, taken out of git beside the
package), asks the tag's code the question of each case, and prints
`{"cases": [[op, arg, ...], ...], "results": [{"ok": value} | {"error": "Class", "code": word?}, ...]}`. The same cases go to
car-adv's example `advreport` (advanced/rust/crates/car-adv/examples/advreport), which reads the same homes - the script
leaves them on disk until the test ends - and every answer must equal the tag's, as the wire writes it (`diffs.encode`).

The Rust side never writes a home it was given to read, and starts no process: gh is a recorded script, never found,
never started (github ops), the watcher's report and the Codex home are data or scratch folders, and the clock is a case's.

Not loaded by run.py on its own (no `diffs_` prefix): diffs_advreport_*.py and diffs_advhook_*.py are.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from rustdiff import advdiff, advref, diffs

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "advanced" / "rust"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GOLDEN = ROOT / "advanced" / "tests" / "golden" / "report"
_TESTS: dict = {}


def tests_folder(tag: str | None = None) -> Path:
    """`advanced/tests` of the tag (the fixtures and the gh stand-in), taken out of git beside its package, once."""
    root = advref.package(tag)
    if (tag or advref.reference.TAG) in _TESTS:
        return _TESTS[tag or advref.reference.TAG]
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", tag or advref.reference.TAG,
                              "advanced/tests/reportfixtures.py", "advanced/tests/ghfake.py",
                              "advanced/tests/advancedcase.py", "advanced/tests/golden/report"],
                             capture_output=True, creationflags=NO_WINDOW)
    if archive.returncode != 0:
        raise unittest.SkipTest("%s's advanced tests are not in this checkout" % (tag or advref.reference.TAG))
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(root, filter="data")
    _TESTS[tag or advref.reference.TAG] = root / "advanced" / "tests"
    return _TESTS[tag or advref.reference.TAG]


def binary() -> Path:
    named = os.environ.get("CODEX_AR_ADVREPORT_EXE")
    if named:
        return Path(named)
    return advref.target_dir() / "release" / "examples" / "advreport.exe"


def build() -> None:
    """`cargo build --release --locked -p car-adv --example advreport` in the advanced workspace."""
    environment = dict(os.environ)
    environment.setdefault("CARGO_BUILD_JOBS", "2")
    subprocess.run(["cargo", "build", "--release", "--locked", "-p", "car-adv", "--example", "advreport"],
                   cwd=str(WORKSPACE), env=environment, check=True, creationflags=NO_WINDOW, timeout=3600)


# What every reference script starts with. `case(op, *args, ref=lambda: ...)` records one case and what the tag answers;
# the homes a fixtures.Home makes stay where `SCRATCH` is, so that the Rust side reads them after this process ends.
PRELUDE = diffs.TAGGING + r'''
import enum, json, os, sys, tempfile
from pathlib import Path
SCRATCH, TESTS = sys.argv[1], sys.argv[2]
tempfile.tempdir = SCRATCH
tempfile.TemporaryDirectory.cleanup = lambda self, *a, **k: None
tempfile.TemporaryDirectory._cleanup = classmethod(lambda cls, *a, **k: None)
sys.path.insert(0, TESTS)
CASES, RESULTS = [], []

def jsonable(value):
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted(jsonable(each) for each in value)
    if isinstance(value, (list, tuple)):
        return [jsonable(each) for each in value]
    if isinstance(value, dict):
        return {str(key): jsonable(each) for key, each in value.items()}
    return value

def failed(error):
    found = {"error": type(error).__name__}
    code = getattr(error, "code", None)
    if code is not None and not isinstance(code, int):
        found["code"] = str(code)
    return found

def case(op, *args, ref):
    CASES.append([op, *args])
    try:
        RESULTS.append({"ok": jsonable(ref())})
    except Exception as error:
        RESULTS.append(failed(error))

def finish():
    sys.stdout.write(json.dumps({"cases": tagged(CASES), "results": tagged(RESULTS)}, ensure_ascii=False, allow_nan=False))
'''


def untag(value):
    """`value` with every {"$float": ...} tag (rustdiff.diffs.FLOAT_TAG) turned back into its float, the way `diffs.encode`
    wants a value: it tags a NaN or an infinity itself, and refuses a value that already is one."""
    if isinstance(value, list):
        return [untag(each) for each in value]
    if isinstance(value, dict):
        if list(value) == ["$float"]:
            return float(value["$float"])
        return {key: untag(each) for key, each in value.items()}
    return value


def snapshot(folder: Path) -> dict:
    """Every file and folder under `folder` but the profile: its size, modification time and the SHA-256 of its bytes."""
    import hashlib
    found = {}
    for path in sorted(folder.rglob("*")):
        name = path.relative_to(folder).as_posix()
        if name == "profile" or name.startswith("profile/"):
            continue
        if path.is_dir():
            found[name] = "folder"
        else:
            status = path.stat()
            found[name] = (status.st_size, status.st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
    return found


class ReportDiff(unittest.TestCase):
    """A diff of car-adv's report or hook: `family(script)` runs the script in the tag and the same cases in `advreport`."""

    @classmethod
    def setUpClass(cls):
        # cargo's own check says whether it is current: a stale example (a merge since it was built) never answers.
        if not os.environ.get("CODEX_AR_ADVREPORT_EXE"):
            build()
        cls.scratch = tempfile.mkdtemp(prefix="advreport-")
        cls.addClassCleanup(shutil.rmtree, cls.scratch, True)

    def reference(self, script: str, *, label: str, arguments=()) -> tuple:
        """(folder, cases, the tag's answers): the script run under the tag's advanced edition, its homes left on disk."""
        folder = Path(tempfile.mkdtemp(prefix="%s-" % label, dir=self.scratch))
        profile = folder / "profile"
        profile.mkdir()
        made = advref.run(PRELUDE + script, str(folder), str(tests_folder()), *map(str, arguments), profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-3000:].decode("utf-8", "replace"))
        done = json.loads(made.stdout.decode("utf-8"))
        return folder, done["cases"], done["results"]

    def rust(self, folder: Path, cases: list, *, chunk: int = 400) -> list:
        """car-adv's answers to `cases`, `advreport` run on the scratch environment of the folder's profile."""
        actual = []
        environment = advref.environment(folder / "profile")
        for start in range(0, len(cases), chunk):
            request = json.dumps({"cases": cases[start:start + chunk]}, ensure_ascii=False).encode("utf-8")
            ran = subprocess.run([str(binary())], input=request, capture_output=True, env=environment,
                                 cwd=str(folder / "profile"), creationflags=NO_WINDOW, timeout=900)
            if ran.returncode != 0:
                raise AssertionError("advreport failed (%d): %s" % (ran.returncode,
                                                                    ran.stderr[-3000:].decode("utf-8", "replace")))
            actual += json.loads(ran.stdout.decode("utf-8"))["results"]
        return actual

    def same(self, label: str, cases: list, expected: list, actual: list) -> None:
        self.assertEqual(len(actual), len(expected), label)
        for index, (want, got) in enumerate(zip(expected, actual)):
            want, got = untag(want), untag(got)
            if diffs.encode(want) != diffs.encode(got):
                self.fail("%s: case %d differs at %s\n  case      %s\n  reference %s\n  rust      %s" % (
                    label, index, advdiff.first_difference(want, got),
                    json.dumps(cases[index], ensure_ascii=False)[:300],
                    json.dumps(want, ensure_ascii=False)[:600], json.dumps(got, ensure_ascii=False)[:600]))

    def family(self, script: str, *, label: str, expect_cases: int = 1, chunk: int = 400, compare=None,
               readonly: bool = False) -> dict:
        folder, cases, expected = self.reference(script, label=label)
        self.assertGreaterEqual(len(cases), expect_cases, label)
        before = snapshot(folder) if readonly else None
        actual = self.rust(folder, cases, chunk=chunk)
        if readonly:
            self.assertEqual(snapshot(folder), before, "%s: the Rust side wrote, made or left something in a home" % label)
        self.same(label, cases, expected, actual)
        if compare is not None:
            compare(cases, expected, actual)
        return {"cases": cases, "results": expected, "folder": folder}
