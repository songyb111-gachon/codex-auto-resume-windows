"""What the day the bundled Python moves leans on, tried while it is still 3.14: docs/DEVELOPMENT.md's section, the tool that
derives the runtime's list, the build's reading of a new Python's bytecode, and the maintainer's profiler script."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def load(name):
    spec = importlib.util.spec_from_file_location("py315_" + name, BUILD / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BytecodeReadingTests(unittest.TestCase):
    def test_an_import_after_many_names_is_still_read(self):
        """Past the 255th name (3.15 keeps two flags in the argument, so past the 63rd) IMPORT_NAME is preceded by EXTENDED_ARG,
        and build/runtime_check.py took that for the instruction before it: the release build stopped on a TypeError."""
        check = load("runtime_check")
        names = "\n".join("name%d = %d" % (index, index) for index in range(400))
        code = compile(names + "\nfrom .deep.place import thing\nimport a.b\n", "m", "exec")
        self.assertEqual(check.imports_in(code, "pack.m", False), {"pack.deep.place", "pack.deep.place.thing", "a.b"})

    def test_a_near_import_is_read_as_before(self):
        check = load("runtime_check")
        code = compile("from . import x\nfrom .. import y\nimport os\n", "m", "exec")
        self.assertEqual(check.imports_in(code, "a.b.c", False), {"a.b", "a.b.x", "a", "a.y", "os"})


class DerivingTheListTests(unittest.TestCase):
    def setUp(self):
        self.tool = load("runtime_keep")

    def test_a_runtimes_names_follow_its_version(self):
        self.assertEqual(self.tool.tag_of("3.15.2"), "python315")
        self.assertEqual(self.tool.renamed("python314._pth", "python315"), "python315._pth")
        self.assertEqual(self.tool.renamed("python314.zip stays", "python315"), "python315.zip stays")

    def test_a_module_brings_the_packages_above_it(self):
        members = {"a/__init__.pyc", "a/b/__init__.pyc", "a/b/c.pyc", "d.pyc"}
        self.assertEqual(self.tool._member_of("a.b.c", members), {"a/__init__.pyc", "a/b/__init__.pyc", "a/b/c.pyc"})
        self.assertEqual(self.tool._member_of("nothing", members), set())

    def test_a_wrong_digest_derives_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            archive, out = Path(folder) / "python.zip", Path(folder) / "out.json"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("python.exe", b"MZ")
            with self.assertRaises(SystemExit):
                self.tool.derive(archive, "3.15.2", "00" * 32, out)
            self.assertFalse(out.exists())

    def test_the_committed_list_is_still_the_bundled_ones(self):
        """The tool is for the day: until then the live list is 3.14's, whatever was tried against 3.15 in a scratch folder."""
        keep = json.loads((BUILD / "runtime_keep.json").read_text(encoding="utf-8"))
        make = load("make_release")
        self.assertEqual((keep["python"], keep["sha256"]), (make.PYTHON_VERSION, make.PYTHON_SHA256))
        self.assertTrue(make.PYTHON_VERSION.startswith("3.14."), "the switch to 3.15 is its own change: docs/DEVELOPMENT.md")

    def test_it_reads_only_what_ships(self):
        make = load("make_release")
        scripts = {path.name for path in self.tool._shipped_files() if path.parent == ROOT / "scripts"}
        self.assertEqual(scripts, {name for name in make.SHIPPED_SCRIPTS if name.endswith(".py")})


class TheDaysDocumentTests(unittest.TestCase):
    def section(self, name="docs/DEVELOPMENT.md", heading="## The day the bundled Python moves"):
        text = (ROOT / name).read_text(encoding="utf-8")
        self.assertIn(heading, text)
        return text[text.index(heading):]

    def test_it_names_everything_that_changes(self):
        section = self.section()
        for word in ("PYTHON_VERSION", "PYTHON_SHA256", "bundled_runtime", "release_build", "build/runtime_keep.py", "runtime_keep.json",
                     "LAZY_IMPORTS", "docs/CHANGELOG.md"):
            with self.subTest(word=word):
                self.assertIn(word, section)


class ProfilerScriptTests(unittest.TestCase):
    def setUp(self):
        self.tool = load("profile_tachyon")

    def test_it_is_not_shipped(self):
        make = load("make_release")
        self.assertNotIn("build", make.APP_TREES)
        self.assertNotIn("profile_tachyon.py", make.SHIPPED_SCRIPTS)
        self.assertNotIn("runtime_keep.py", make.SHIPPED_SCRIPTS)

    def test_a_target_starts_from_the_module_and_never_from_the_script(self):
        """src/auto_resume.py starts itself again with remote debugging off, and the profiler would watch a process that waits."""
        made = self.tool.command("python.exe", ["--mode", "cpu"], "S", "H", ("run", "--once"))
        self.assertEqual(made, ["python.exe", "-m", "profiling.sampling", "run", "--mode", "cpu", "S", "--home", "H", "run", "--once"])
        with tempfile.TemporaryDirectory() as folder:
            script = self.tool.starter(Path(folder), "codex_auto_resume.cli").read_text(encoding="utf-8")
        self.assertIn("runpy.run_module('codex_auto_resume.cli'", script)
        self.assertNotIn("auto_resume.py", script)

    def test_the_real_home_is_refused(self):
        with mock.patch.object(self.tool, "is_315", return_value=True), self.assertRaises(SystemExit):
            self.tool.main(["--home", str(self.tool.real_home()), "bridge"])

    def test_the_target_gets_a_machine_of_its_own(self):
        with tempfile.TemporaryDirectory() as folder:
            world = self.tool.scratch_world(Path(folder))
            for name in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "CODEX_HOME"):
                self.assertTrue(Path(world[name]).is_relative_to(Path(folder)), name)
            self.assertNotIn("CODEX_AR_EDITION", world)

    def test_every_format_is_one_the_option_list_takes(self):
        self.assertEqual(set(self.tool.FORMATS), {"pstats", "collapsed", "flamegraph", "gecko", "heatmap"})


if __name__ == "__main__":
    unittest.main()
