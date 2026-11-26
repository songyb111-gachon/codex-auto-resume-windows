"""Which Python the Rust diff harness's reference runs on (tests/rustdiff/refpython.py).

The reference is the tag's own Python, and it runs on the runtime the product ships - the bundled embeddable 3.14.10 -
unless `system` or a path is chosen. Held here: the default, what each choice resolves to, that an embeddable runtime
gets the tag's source through its own sys.path (it ignores PYTHONPATH), that a zip that is not the pinned one is refused,
and that the scratch copy goes when the process ends.

Nothing here reaches the network, the registry or a real home: the bundled zip is read where the build cache has it and
the tests that need it are skipped (named) where it is not; the CI lanes have no such zip and fetch none.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests")]

from rustdiff import refpython, reftwin  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_zip():
    """The bundled zip if some build/cache of this repository has it, with no fetch (CI's lanes have none)."""
    saved = os.environ.get("CI")
    os.environ.pop("CI", None)
    try:
        return refpython.bundled_zip()
    except RuntimeError:
        return None
    finally:
        if saved is not None:
            os.environ["CI"] = saved


class Choice(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (refpython.VARIABLE, refpython.RESOLVED_VARIABLE):
            os.environ.pop(name, None)
        refpython._CACHE.clear()
        self.addCleanup(refpython._CACHE.clear)

    def test_the_default_is_the_bundled_runtime(self):
        self.assertEqual(refpython.choice(), "bundled")
        self.assertEqual(refpython.DEFAULT, "bundled")

    def test_the_choice_is_the_variable_and_select_sets_it(self):
        refpython.select("system")
        self.assertEqual(refpython.choice(), "system")
        self.assertEqual(os.environ[refpython.VARIABLE], "system")

    def test_system_is_this_interpreter_and_honours_pythonpath(self):
        refpython.select("system")
        self.assertEqual(refpython.interpreter(), Path(sys.executable))
        self.assertFalse(refpython.ignores_environment(refpython.interpreter()))
        self.assertEqual(refpython.command("print(1)", "a", paths=["x"]),
                         [sys.executable, "-X", "utf8", "-c", "print(1)", "a"])
        self.assertIn("%d.%d" % sys.version_info[:2], refpython.version())

    def test_a_path_names_an_interpreter_or_its_folder(self):
        for value in (sys.executable, str(Path(sys.executable).parent)):
            with self.subTest(value=value):
                refpython.select(value)
                self.assertEqual(refpython.interpreter().resolve(), Path(sys.executable).resolve())

    def test_what_is_neither_is_refused_by_name(self):
        refpython.select(str(Path(tempfile.gettempdir()) / "no-such-python-here" / "python.exe"))
        with self.assertRaises(RuntimeError) as raised:
            refpython.interpreter()
        self.assertIn("no-such-python-here", str(raised.exception))

    def test_a_python_that_cannot_import_what_the_reference_needs_is_named(self):
        with mock.patch.object(refpython, "CHECK", "import a_module_no_runtime_has"):
            with self.assertRaises(RuntimeError) as raised:
                refpython.check(Path(sys.executable))
        self.assertIn("a_module_no_runtime_has", str(raised.exception))


class Pinned(unittest.TestCase):
    def test_a_zip_that_is_not_the_pinned_runtime_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="refpython-test-") as scratch:
            fake = Path(scratch) / "python-0.0.0-embed-amd64.zip"
            with zipfile.ZipFile(fake, "w") as bundle:
                bundle.writestr("python.exe", "not a program")
            with mock.patch.dict(os.environ, {refpython.ZIP_VARIABLE: str(fake)}):
                with self.assertRaises(RuntimeError) as raised:
                    refpython.bundled_zip()
        self.assertIn("is not the pinned runtime", str(raised.exception))
        self.assertIn(refpython._make_release().PYTHON_SHA256, str(raised.exception))

    def test_the_pin_is_the_one_the_runtime_list_names(self):
        import json

        keep = json.loads((ROOT / "build" / "runtime_keep.json").read_text(encoding="utf-8"))
        make_release = refpython._make_release()
        self.assertEqual(make_release.PYTHON_SHA256, keep["sha256"])
        self.assertEqual(make_release.PYTHON_VERSION, keep["python"])

    def test_a_member_outside_the_scratch_folder_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="refpython-test-") as scratch:
            evil = Path(scratch) / "evil.zip"
            with zipfile.ZipFile(evil, "w") as bundle:
                bundle.writestr("../outside.txt", "x")
            with self.assertRaises(RuntimeError):
                refpython._unpack(evil)


@unittest.skipUnless(find_zip(), "the bundled runtime's zip is in no build/cache here (CI's lanes fetch none)")
class Bundled(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        cls.addClassCleanup(patcher.stop)
        for name in (refpython.VARIABLE, refpython.RESOLVED_VARIABLE):
            os.environ.pop(name, None)
        refpython._CACHE.clear()
        cls.addClassCleanup(refpython._CACHE.clear)
        refpython.select("bundled")
        cls.exe = refpython.interpreter()

    def run_reference(self, script, *arguments, paths=(), environment=None):
        return subprocess.run(refpython.command(script, *arguments, paths=paths), capture_output=True, text=True,
                              encoding="utf-8", env=environment, creationflags=NO_WINDOW, timeout=120)

    def test_it_is_the_pinned_version_and_an_embeddable_one(self):
        self.assertEqual(refpython.version(), refpython._make_release().PYTHON_VERSION)
        self.assertTrue(refpython.ignores_environment(self.exe))
        self.assertNotEqual(self.exe, Path(sys.executable))
        self.assertTrue(str(self.exe).startswith(tempfile.gettempdir()) or Path(tempfile.gettempdir()) in self.exe.parents)

    def test_its_source_comes_through_sys_path_and_arguments_are_as_dash_c_has_them(self):
        with tempfile.TemporaryDirectory(prefix="refpython-test-") as scratch:
            (Path(scratch) / "refpython_probe_module.py").write_text("VALUE = 41 + 1\n", encoding="utf-8")
            done = self.run_reference("import sys, refpython_probe_module as m\nprint(m.VALUE, sys.argv, __name__)",
                                      "one", "two words", paths=[scratch])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "42 ['-c', 'one', 'two words'] __main__")

    def test_pythonpath_and_the_working_folder_reach_nothing(self):
        with tempfile.TemporaryDirectory(prefix="refpython-test-") as scratch:
            (Path(scratch) / "refpython_decoy_module.py").write_text("VALUE = 1\n", encoding="utf-8")
            environment = dict(os.environ, PYTHONPATH=scratch)
            done = subprocess.run(refpython.command("import refpython_decoy_module", paths=[]), capture_output=True,
                                  text=True, encoding="utf-8", env=environment, cwd=scratch,
                                  creationflags=NO_WINDOW, timeout=120)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ModuleNotFoundError", done.stderr)

    def test_a_script_may_start_with_a_future_import_and_its_errors_name_string(self):
        done = self.run_reference("from __future__ import annotations\nraise SystemExit(3)")
        self.assertEqual(done.returncode, 3, done.stderr)
        broken = self.run_reference("\n\nraise ValueError('x')")
        self.assertIn('File "<string>", line 3', broken.stderr)

    def test_the_standard_library_the_reference_imports_is_there(self):
        self.assertEqual(refpython.check(self.exe), refpython._make_release().PYTHON_VERSION)

    def test_the_scratch_copy_goes_when_the_process_ends_and_a_child_finds_it_again(self):
        probe = ("import sys; sys.path[0:0] = [r'%s']\nfrom rustdiff import refpython\n"
                 "exe = refpython.interpreter()\nprint(exe)\nprint(refpython.describe())")
        environment = dict(os.environ)
        for name in (refpython.VARIABLE, refpython.RESOLVED_VARIABLE):
            environment.pop(name, None)
        done = subprocess.run([sys.executable, "-X", "utf8", "-c", probe % (ROOT / "tests"), ], capture_output=True,
                              text=True, encoding="utf-8", env=environment, creationflags=NO_WINDOW, timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr)
        exe, described = done.stdout.splitlines()[:2]
        self.assertFalse(Path(exe).parent.exists(), "the unpacked runtime was left behind")
        self.assertIn("python 3.14", described)
        self.assertIn("embeddable", described)


class Twin(unittest.TestCase):
    """reftwin.py: the same script on a second Python, what differs logged, the run left as the chosen one made it."""
    SCRIPT = (
        "import sys, pathlib" + '\n' +
        "pathlib.Path('made.txt').write_text('python %d.%d' % sys.version_info[:2])" + '\n' +
        "print('same line')" + '\n' +
        "print(tuple(sys.version_info[:2]) if sys.argv[1:] == ['version'] else 'x')")

    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (refpython.VARIABLE, refpython.RESOLVED_VARIABLE, reftwin.VARIABLE, reftwin.LOG_VARIABLE):
            os.environ.pop(name, None)
        refpython._CACHE.clear()
        self.addCleanup(refpython._CACHE.clear)
        scratch = tempfile.TemporaryDirectory(prefix="refpython-twin-")
        self.addCleanup(scratch.cleanup)
        self.scratch = Path(scratch.name)
        self.home = self.scratch / "home"
        self.home.mkdir()
        (self.home / "given.txt").write_text("laid down by the case", encoding="utf-8")
        refpython.select("system")

    def twinned(self, *arguments):
        def start(which):
            return subprocess.run(refpython.command(self.SCRIPT, *arguments, paths=[], which=which), capture_output=True,
                                  cwd=str(self.home), creationflags=NO_WINDOW, timeout=120)

        return reftwin.twinned(start, self.home, self.SCRIPT, arguments)

    def test_no_twin_is_no_twin(self):
        self.assertIsNone(reftwin.twin())
        os.environ[reftwin.VARIABLE] = "system"
        self.assertEqual(reftwin.twin(), "system")

    def test_the_same_python_twice_differs_in_nothing_and_logs_nothing(self):
        os.environ[reftwin.VARIABLE] = sys.executable
        os.environ[reftwin.LOG_VARIABLE] = str(self.scratch / "log")
        done = self.twinned()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.home / "made.txt").read_text(encoding="utf-8"), "python %d.%d" % sys.version_info[:2])
        self.assertEqual((self.home / "given.txt").read_text(encoding="utf-8"), "laid down by the case")
        self.assertFalse((self.scratch / "log" / "calls.jsonl").exists())

    @unittest.skipUnless(find_zip(), "the bundled runtime's zip is in no build/cache here (CI's lanes fetch none)")
    def test_another_python_is_found_out_and_the_run_is_the_chosen_ones(self):
        os.environ[reftwin.VARIABLE] = "bundled"
        os.environ[reftwin.LOG_VARIABLE] = str(self.scratch / "log")
        done = self.twinned("version")
        self.assertIn("(%d, %d)" % sys.version_info[:2], done.stdout.decode())
        self.assertEqual((self.home / "made.txt").read_text(encoding="utf-8"), "python %d.%d" % sys.version_info[:2],
                         "the twin's file must not be what is left")
        import json

        entries = [json.loads(line) for line in (self.scratch / "log" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["differs"], ["stdout", "files"])
        self.assertIn(b"(3, 14)", (self.scratch / "log" / "00001-twin.out").read_bytes())


if __name__ == "__main__":
    unittest.main()
