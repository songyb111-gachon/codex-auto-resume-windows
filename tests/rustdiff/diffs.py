"""The diffs: each runs one input through the reference (reference.py) and through Rust (core.py) and holds
the outputs equal byte for byte (D12). Run by run.py, never by the lanes' discovery: tests/rustdiff has no
__init__.py, which unittest's discovery needs to enter a folder (README.md says what each file is).

S0.4's proof, end to end:
* DefaultsDiff - the bridge's `defaults` on a fresh scratch home: the reply line and settings.json from the
  tag's controlcli and from car-core-stub, and the reply against tests/golden/bridge/defaults.json.
* StateFixtureDiff - a state.sqlite the tag's own store writes (one record in each state it knows, as
  tests/released.py writes v0.6.10's), opened by the tag's store and read by car-harness with rusqlite.
* ShimRoutes - CODEX_AR_CORE=rust sends controlcli.main to the Rust binary through both seams, and without
  the variable nothing of the shim loads.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import released
from rustdiff import core, reference

ROOT = core.ROOT
GOLDEN = ROOT / "tests" / "golden" / "bridge"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# What each diff saw, for run.py to print and README.md to record.
RECORD: list[str] = []


def canonical(data: bytes, *homes: Path) -> bytes:
    """The wire's bytes with each scratch home written as <scratch>, as tests/wiregolden.py writes its
    pinned directories - in the JSON-escaped form a reply carries a path in, and as it is."""
    for home in homes:
        for form in (json.dumps(str(home))[1:-1], str(home)):
            data = data.replace(form.encode("utf-8"), b"<scratch>")
    return data


def golden_line(command: str, case: int = 0) -> bytes:
    """A bridge golden's reply as the wire writes it: json.dumps(reply, ensure_ascii=False) and "\\n"."""
    document = json.loads((GOLDEN / (command + ".json")).read_text(encoding="utf-8"))
    return (json.dumps(document["cases"][case]["reply"], ensure_ascii=False) + "\n").encode("utf-8")


# The channel's floats (REVIEW-int5 S3). The wire writes JSON with allow_nan=False and car-harness reads requests with
# serde, so a NaN or an infinity cannot cross as itself: each goes as a one-key object, {"$float": "nan"}, {"$float":
# "inf"} or {"$float": "-inf"}, both ways - the reference's family scripts tag their cases and answers (`TAGGING` is in
# leaves.PRELUDE and codexdiff.SCRIPT), car-harness turns a tag into the float before a case runs and its own NaN and
# infinities into tags in the answer (`leaves::untag`, `leaves::tag`). Every finite value goes as before, so a diff that
# never meets a non-finite float writes the same bytes. A dict whose only key is "$float" is the tag's, never a case's.
FLOAT_TAG = "$float"
TAGGING = r'''
def tagged(value):
    """`value` with every NaN and infinity as its {"$float": ...} tag (rustdiff.diffs.FLOAT_TAG)."""
    if isinstance(value, float):
        if value != value:
            return {"$float": "nan"}
        if value in (float("inf"), float("-inf")):
            return {"$float": "inf" if value > 0 else "-inf"}
        return value
    if isinstance(value, (list, tuple)):
        return [tagged(each) for each in value]
    if isinstance(value, dict):
        if list(value) == ["$float"]:
            raise ValueError("a dict whose only key is $float is the channel's float tag")
        return {key: tagged(each) for key, each in value.items()}
    return value
'''
exec(TAGGING)


def encode(value) -> bytes:
    """controlcli.encode's line for `value`, the bytes the reference's wire writes (a NaN or an infinity as its tag)."""
    return (json.dumps(tagged(value), ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        absent = core.missing()
        if absent:
            raise AssertionError("not built: %s (run.py --build, or cargo build --release --manifest-path %s)"
                                 % (", ".join(absent), core.MANIFEST))

    def setUp(self):
        self.scratch = Path(tempfile.mkdtemp(prefix="rustdiff-"))
        self.addCleanup(__import__("shutil").rmtree, self.scratch, True)

    def profile(self, name: str) -> Path:
        folder = self.scratch / name
        folder.mkdir()
        return folder


class DefaultsDiff(Base):
    def test_defaults(self):
        mine, theirs = self.profile("rust"), self.profile("reference")
        rust_home, reference_home = mine / "home", theirs / "home"
        expected = reference.bridge("--home", reference_home, "defaults", profile=theirs)
        actual = core.stub("bridge", "--home", rust_home, "defaults",
                           environment=reference.scratch_environment(mine), cwd=mine)
        self.assertEqual((expected.returncode, expected.stderr), (0, b""), expected.stderr[-2000:])
        self.assertEqual((actual.returncode, actual.stderr), (0, b""), actual.stderr[-2000:])
        reply = canonical(actual.stdout, rust_home)
        self.assertEqual(reply, canonical(expected.stdout, reference_home), "the reply line differs from the tag's")
        self.assertEqual(reply, golden_line("defaults"), "the reply line differs from tests/golden/bridge/defaults.json")
        written = (rust_home / "config" / "settings.json").read_bytes()
        self.assertEqual(written, (reference_home / "config" / "settings.json").read_bytes(),
                         "settings.json differs from the tag's")
        RECORD.append("defaults: reply %d bytes, settings.json %d bytes, identical to %s and to the golden"
                      % (len(reply), len(written), reference.TAG))


# The tag's store opens the fixture its own store wrote and says, for each key, the record's state.
READ_STATES = r'''
import json, sys
from pathlib import Path
from codex_auto_resume.store import Store
root, keys = Path(sys.argv[1]), sys.argv[2:]
with Store(root) as store:
    print(json.dumps({"version": store.schema_version(),
                      "states": [[key, (store.get(key) or {}).get("state")] for key in keys]}))
'''


class StateFixtureDiff(Base):
    def test_record_states(self):
        profile = self.profile("reference")
        home = profile / "home"
        made = reference.run(released._WRITE_STATE, home, released.THREAD, released.OTHER, profile=profile)
        self.assertEqual(made.returncode, 0, made.stderr[-2000:])
        keys = sorted(json.loads(made.stdout)["states"]) + ["f" * 64]   # the last one is in no record
        opened = reference.run(READ_STATES, home, *keys, profile=profile)
        self.assertEqual(opened.returncode, 0, opened.stderr[-2000:])
        answer = json.loads(opened.stdout)
        states = dict(answer["states"])
        self.assertIsNone(states["f" * 64])
        self.assertGreater(len({state for state in states.values() if state}), 5, states)
        with core.Harness(reference.scratch_environment(self.profile("rust"))) as harness:
            for key in keys:
                number, line = harness.call("store.record_state", home=str(home), interruption_id=key)
                self.assertEqual(line, encode({"id": number, "reply": {"ok": True, "value": states[key]}}), key)
            number, line = harness.call("store.schema_version", home=str(home))
            self.assertEqual(line, encode({"id": number, "reply": {"ok": True, "value": answer["version"]}}))
            _number, sqlite = harness.call("sqlite.version")
        RECORD.append("state fixture: %d records (schema %d) written and opened by %s's store, the same %d values "
                      "read by car-harness (SQLite %s)" % (len(keys) - 1, answer["version"], reference.TAG,
                                                          len(keys) + 1, json.loads(sqlite)["reply"]["value"]))


# A child Python that asks the bridge for `defaults` through controlcli.main, and says which main it called.
ASK = r'''
import sys
{setup}
from codex_auto_resume import controlcli
sys.stderr.write("main=%s\n" % getattr(controlcli.main, "rust_core", "python"))
sys.stderr.flush()
sys.exit(controlcli.main(["--home", sys.argv[1], "defaults"]))
'''
LOOK = r'''
import sys
{setup}
from codex_auto_resume import controlcli
print(getattr(controlcli.main, "rust_core", "python"), "rustdiff_shim" in sys.modules)
'''
SEAMS = {
    # PYTHONPATH="src;tests", as every local run: tests/sitecustomize.py installs it.
    "sitecustomize": ("src;tests", ""),
    # A test_parts lane: PYTHONPATH=src, and the lane's work() installs it.
    "test_parts": ("src", "sys.path.insert(0, %r)\nimport test_parts\ntest_parts.rust_core()" % str(ROOT / "scripts")),
}


class ShimRoutes(Base):
    def child(self, script, seam, *arguments, rust=True):
        path, setup = SEAMS[seam]
        profile = self.profile("%s-%s-%s" % (seam, rust, len(list(self.scratch.iterdir()))))
        environment = reference.scratch_environment(profile, PYTHONPATH=os.pathsep.join(
            str(ROOT / part) for part in path.split(";")))
        if rust:
            environment["CODEX_AR_CORE"] = "rust"
        return profile, subprocess.run([sys.executable, "-X", "utf8", "-c", script.format(setup=setup),
                                        *map(str, arguments)], capture_output=True, env=environment,
                                       cwd=str(profile), creationflags=NO_WINDOW, timeout=300)

    def test_both_seams_reach_rust(self):
        for seam in SEAMS:
            with self.subTest(seam=seam):
                profile, done = self.child(ASK, seam, "HOME")
                home = profile / "HOME"
                self.assertEqual(done.returncode, 0, done.stderr[-2000:])
                self.assertIn(b"main=bridge", done.stderr)
                self.assertEqual(canonical(done.stdout, home), golden_line("defaults"))
                self.assertTrue((home / "config" / "settings.json").is_file())
        RECORD.append("shim: controlcli.main ran car-core-stub through tests/sitecustomize.py and test_parts' lane")

    def test_no_variable_no_shim(self):
        for seam in SEAMS:
            with self.subTest(seam=seam):
                _profile, done = self.child(LOOK, seam, rust=False)
                self.assertEqual((done.returncode, done.stdout.split()), (0, [b"python", b"False"]), done.stderr)
        RECORD.append("shim: without CODEX_AR_CORE, controlcli.main is Python's and the shim is not loaded")
