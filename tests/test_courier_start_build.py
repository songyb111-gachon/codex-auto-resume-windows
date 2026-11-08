"""The release build stops when the advanced courier cannot start from the staged payload (v0.6.22,
build/make_release.py check_courier_starts).

An installed copy runs the embeddable runtime, whose python3XX._pth makes it ignore the environment. v0.6.22-beta.2 gave
the courier its import roots in PYTHONPATH alone, so no courier ever started from an installation, and nothing in CI ran
the start under such an interpreter (the live acceptance's F7). The build now asks the staged runtime for the courier's
command line and runs it in `--check` mode; these hold that check to telling the two apart.

The release build downloads the embeddable runtime; here a stand-in is made of the interpreter running the tests: its
executables and DLLs copied into a stage, with a python3XX._pth of their own naming its standard library - which makes it
ignore the environment exactly as the embeddable one does (held below, not assumed). The staged app is the two packages
copied as make_release places them, under app/src. Nothing is installed and nothing reaches the network.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = (ROOT / "src" / "codex_auto_resume", ROOT / "advanced" / "src" / "codex_auto_resume_advanced")


def load_builder():
    spec = importlib.util.spec_from_file_location("make_release_courier", ROOT / "build" / "make_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stand_in_runtime(runtime: Path) -> bool:
    """The running interpreter's python.exe, pythonw.exe and DLLs in `runtime`, with a ._pth naming its standard
    library; False where this interpreter has not the layout to copy."""
    base = Path(sys.base_prefix)
    libraries = [path for path in base.glob("python3*.dll") if path.name.lower() != "python3.dll"]
    if os.name != "nt" or len(libraries) != 1 or not all((base / name).is_file()
                                                          for name in ("python.exe", "pythonw.exe")):
        return False
    runtime.mkdir(parents=True)
    for path in base.glob("*.dll"):
        shutil.copyfile(path, runtime / path.name)
    for name in ("python.exe", "pythonw.exe"):
        shutil.copyfile(base / name, runtime / name)
    (runtime / (libraries[0].stem + "._pth")).write_text("%s\n%s\n" % (base / "Lib", base / "DLLs"), encoding="utf-8")
    return True


class CourierStartCheckTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="car-courier-build-")
        self.addCleanup(folder.cleanup)
        self.stage = Path(folder.name) / "stage"
        runtime = self.stage / "payload" / "runtime"
        if not stand_in_runtime(runtime):
            self.skipTest("this interpreter has no python3XX.dll, python.exe and pythonw.exe to stand in with")
        src = self.stage / "payload" / "app" / "src"
        for package in PACKAGES:
            shutil.copytree(package, src / package.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.builder = load_builder()

    def test_the_stand_in_ignores_the_environment_as_the_bundled_runtime_does(self):
        done = subprocess.run([str(self.stage / "payload" / "runtime" / "python.exe"), "-c",
                               "import sys; print(sys.flags.ignore_environment)"],
                              env=dict(os.environ, PYTHONPATH=str(ROOT / "src")), capture_output=True, text=True,
                              timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(done.stdout.strip(), "1", done.stderr)

    def test_the_payload_as_built_passes(self):
        self.builder.check_courier_starts(self.stage)

    def test_the_check_leaves_no_bytecode_in_the_stage(self):
        """v0.6.22's first release run: the check's imports wrote __pycache__ into the staged payload, the advanced
        archive carried it, and the edition audit (f) stopped the release. Both runs take -B, and a left __pycache__
        stops the build."""
        self.builder.check_courier_starts(self.stage)
        self.assertEqual(sorted(str(path) for path in (self.stage / "payload").rglob("__pycache__")), [])
        planted = self.stage / "payload" / "app" / "src" / "codex_auto_resume" / "__pycache__"
        planted.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(SystemExit) as stopped:
            self.builder.check_courier_starts(self.stage)
        self.assertIn("left bytecode", str(stopped.exception))

    def test_a_start_that_needs_pythonpath_stops_the_build(self):
        launch = self.stage / "payload" / "app" / "src" / "codex_auto_resume_advanced" / "courier" / "launch.py"
        text = launch.read_text(encoding="utf-8")
        start = '"-c", BOOTSTRAP, roots(),'
        self.assertEqual(text.count(start), 1, "the courier's command line is no longer built as this test expects")
        launch.write_text(text.replace(start, '"-m", MODULE,'), encoding="utf-8")       # v0.6.22-beta.2's command
        with self.assertRaises(SystemExit) as stopped:
            self.builder.check_courier_starts(self.stage)
        self.assertIn("does not start", str(stopped.exception))


if __name__ == "__main__":
    unittest.main()
