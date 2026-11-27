"""A script FILE on the Rust diff harness's reference Python, and the places that now start it that way (follow 3.14, D).

`refpython.script_command(path, *arguments, paths=...)` is what `command` is for a script's text: on the embeddable runtime
(which ignores PYTHONPATH and the script's folder) the script runs as `__main__` with the argv `python path arguments` gives
it, the folders it needs on sys.path and its exit code the process's. The advanced reference (`advref`), the claim race, the
engine and the command-line reference, and the generators (through `productpy`) start the reference's Python this way and
no longer `sys.executable`; held here by what they run on (the version it prints) and by the source text.

Nothing here reaches the network, the registry or a real home; the bundled zip is read where a build cache has it, and the
tests that need it are skipped (named) where there is none.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests")]

from rustdiff import productpy, refpython  # noqa: E402

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
RUSTDIFF = ROOT / "tests" / "rustdiff"


def find_zip():
    saved = os.environ.pop("CI", None)
    try:
        return refpython.bundled_zip()
    except RuntimeError:
        return None
    finally:
        if saved is not None:
            os.environ["CI"] = saved


@unittest.skipIf(find_zip() is None, "no build/cache/python-3.14.10-embed-amd64.zip in this repository's worktrees")
class ScriptFile(unittest.TestCase):
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

    def write(self, scratch: str, text: str, name: str = "probe_script.py") -> Path:
        path = Path(scratch) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_a_file_runs_as_main_with_its_own_argv_and_its_exit_code(self):
        with tempfile.TemporaryDirectory(prefix="script-command-") as scratch:
            path = self.write(scratch, "import sys\nprint(__name__, sys.argv[0].endswith('probe_script.py'), sys.argv[1:], "
                                       "__file__ == sys.argv[0])\nraise SystemExit(5)\n")
            done = subprocess.run(refpython.script_command(path, "one", "two words"), capture_output=True, text=True,
                                  encoding="utf-8", creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(done.returncode, 5, done.stderr)
        self.assertEqual(done.stdout.strip(), "__main__ True ['one', 'two words'] True")

    def test_the_folders_it_needs_are_on_its_path_and_the_scripts_own_folder_is_not(self):
        with tempfile.TemporaryDirectory(prefix="script-command-") as scratch, \
                tempfile.TemporaryDirectory(prefix="script-command-lib-") as library:
            (Path(library) / "script_command_lib.py").write_text("VALUE = 6 * 7\n", encoding="utf-8")
            self.write(scratch, "VALUE = 0\n", "script_command_neighbour.py")
            path = self.write(scratch, "import script_command_lib\nprint(script_command_lib.VALUE)\n"
                                       "try:\n    import script_command_neighbour\nexcept ImportError:\n    print('isolated')\n")
            done = subprocess.run(refpython.script_command(path, paths=[library]), capture_output=True, text=True,
                                  encoding="utf-8", creationflags=NO_WINDOW, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.split(), ["42", "isolated"])

    def test_productpy_starts_a_script_and_a_text_on_the_bundled_runtime_through_refpython(self):
        with tempfile.TemporaryDirectory(prefix="script-command-") as scratch:
            path = self.write(scratch, "import sys\nprint(sys.version.split()[0], sys.argv[1:])\n")
            done = productpy.run([str(path), "a"], capture=True)
            text = productpy.run(["-c", "import sys\nprint(sys.version.split()[0], sys.argv[1:])", "b"], capture=True)
        wanted = refpython._make_release().PYTHON_VERSION
        self.assertEqual(done.stdout.decode().strip(), "%s ['a']" % wanted)
        self.assertEqual(text.stdout.decode().strip(), "%s ['b']" % wanted)
        self.assertEqual(productpy.interpreter(), refpython.interpreter("bundled"))


class NoMoreSystemExecutable(unittest.TestCase):
    """The reference's Python is `--reference-python`'s, not whatever started the run: these files start it through
    `reference.command`, `script_command` or `productpy`, so none of them names `sys.executable` for the reference."""

    FILES = ("advref.py", "diffs_store.py", "diffs_engine.py", "cliworld.py", "gen_cli.py", "gen_vocab.py", "gen_logbook.py",
             "gen_advcodex.py", "productpy.py",
             # Integration 10: every advanced family of the P7 seats, and the advanced proxy's two lanes (advproxy/ledger.py)
             "advdiff.py", "advplug.py", "advstore.py", "advcodex.py", "advcodexd.py", "advreport.py", "diffs_advhook_claim.py",
             "advcourier.py", "advaccount.py", "advusage.py", "advturns.py", "advturnsworld.py", "advtime.py",
             # Integration 11: S7.4's measurement family
             "advmeasure.py",
             "advproxy/ledger.py")

    def test_the_reference_is_never_started_by_sys_executable_in_these_files(self):
        for name in self.FILES:
            text = (RUSTDIFF / name).read_text(encoding="utf-8")
            code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
            code = re.sub(r'""".*?"""', "", code, flags=re.S)
            if name == "diffs_store.py":
                # the only start of a Python in this file that is not the reference's is none: all go through reference
                self.assertNotIn("sys.executable", code, name)
            else:
                self.assertNotRegex(code, r"\[\s*sys\.executable", name)
                self.assertNotIn("sys.executable,", code, name)


if __name__ == "__main__":
    unittest.main()
