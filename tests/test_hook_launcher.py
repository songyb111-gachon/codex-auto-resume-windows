"""The advanced edition's Stop hook launcher (gui/HookLauncher.cs, v0.6.20): the MCP launcher's twin for the one
capability Codex itself starts, "Continue inside the turn" (plans/v0619-design/D-stop-hook.md).

Held here: it compiles to the same bytes every time (normalize_pe, as every executable here); every child it starts
gets a hidden console; and, run for real against a stand-in interpreter, it relays the handler's one answer whole and
only from a handler that exited 0, drops the handler's standard error, and passes (exit 0, nothing written) when nothing
is installed, when the handler fails and when the handler hangs past its bound. It is not built into a release yet:
the capability is hidden until MHK, M4 and M4B pass, and shipping it in the advanced archive (build/make_gui.ps1,
build/make_release.py, the release workflow's count of executables) waits for that, with the owner's review.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

import normalize_pe  # noqa: E402

SOURCE = ROOT / "gui" / "HookLauncher.cs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = 0x08000000

# A stand-in for the bundled interpreter: what it does is chosen by a file beside it, so one build serves every case.
STAND_IN = r"""
using System;
using System.IO;
using System.Threading;
static class Program {
    static int Main(string[] args) {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string mode = File.ReadAllText(Path.Combine(here, "mode.txt")).Trim();
        string input = Console.In.ReadToEnd();
        File.WriteAllText(Path.Combine(here, "seen.txt"), input);
        Console.Error.Write("a diagnostic of the handler's");
        if (mode == "hang") { Thread.Sleep(60000); return 0; }
        if (mode == "fail") { Console.Out.Write("{\"decision\":\"block\"}"); return 1; }
        if (mode == "quiet") return 0;
        Console.Out.Write("{\"decision\":\"block\",\"reason\":\"go on\"}");
        return 0;
    }
}
"""


def _compile(source: Path, out: Path) -> Path:
    subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+", "/out:" + str(out),
                    "/reference:System.dll", str(source)],
                   check=True, capture_output=True, timeout=180, creationflags=NO_WINDOW)
    return out


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8")

    def test_its_child_gets_a_hidden_console_and_redirected_streams(self):
        for setting in ("UseShellExecute = false", "CreateNoWindow = true", "RedirectStandardInput = true",
                        "RedirectStandardOutput = true", "RedirectStandardError = true"):
            self.assertIn("info." + setting + ";", self.text)

    def test_it_never_writes_to_standard_error_and_every_way_out_is_zero(self):
        """A hook's non-zero exit or its words on standard error may be read by Codex as something; the launcher's
        only failure is to pass."""
        self.assertNotIn("Console.Error", self.text)
        self.assertNotIn("OpenStandardError", self.text)
        self.assertEqual(set(re.findall(r"\breturn\s+(-?\d+)\s*;", self.text)), {"0"})
        self.assertNotIn("return process.ExitCode", self.text)

    def test_it_starts_the_advanced_package_s_handler_with_the_installation_s_interpreter(self):
        self.assertIn('Path.Combine(home, "runtime", "python.exe")', self.text)
        self.assertIn("from codex_auto_resume_advanced.hook import main;", self.text)
        self.assertIn('"-I -c "', self.text)


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class CompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="car-hook-launcher-"))
        (cls.folder / "a").mkdir()
        cls.first = _compile(SOURCE, cls.folder / "a" / "codex-auto-resume-hook.exe")
        time.sleep(1.2)                     # the compiler's timestamp has one-second resolution
        (cls.folder / "b").mkdir()
        cls.second = _compile(SOURCE, cls.folder / "b" / "codex-auto-resume-hook.exe")
        stand_in = cls.folder / "StandIn.cs"
        stand_in.write_text(STAND_IN, encoding="utf-8")
        cls.interpreter = _compile(stand_in, cls.folder / "python.exe")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def test_two_builds_are_the_same_bytes_once_normalised(self):
        """Fails without normalize_pe: the in-box compiler stamps the second and a random MVID."""
        first = normalize_pe.normalise(self.first.read_bytes())
        second = normalize_pe.normalise(self.second.read_bytes())
        self.assertEqual(first, second)
        self.assertNotEqual(self.first.read_bytes(), self.second.read_bytes())

    def home(self, mode=None) -> Path:
        home = Path(tempfile.mkdtemp(prefix="car-hook-home-", dir=self.folder))
        if mode is not None:
            (home / "runtime").mkdir()
            (home / "app" / "src").mkdir(parents=True)
            shutil.copyfile(self.interpreter, home / "runtime" / "python.exe")
            (home / "runtime" / "mode.txt").write_text(mode, encoding="utf-8")
        return home

    def run_launcher(self, home, stdin=b'{"hook_event_name":"Stop"}', timeout=60):
        env = {key: value for key, value in os.environ.items()
               if key not in ("CODEX_AUTO_RESUME_PLUGIN_HOME", "CODEX_AUTO_RESUME_HOME")}
        env["CODEX_AUTO_RESUME_PLUGIN_HOME"] = str(home)
        started = time.monotonic()
        done = subprocess.run([str(self.first)], input=stdin, capture_output=True, timeout=timeout, env=env,
                              creationflags=NO_WINDOW)
        return done, time.monotonic() - started

    def test_the_handler_s_answer_is_relayed_whole_and_its_input_handed_over(self):
        home = self.home("block")
        done, _ = self.run_launcher(home)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b'{"decision":"block","reason":"go on"}')
        self.assertEqual(done.stderr, b"", "the handler's diagnostic never reaches Codex")
        self.assertEqual((home / "runtime" / "seen.txt").read_bytes(), b'{"hook_event_name":"Stop"}')

    def test_a_handler_that_failed_passes_with_nothing_written(self):
        done, _ = self.run_launcher(self.home("fail"))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    def test_a_quiet_handler_is_a_quiet_hook(self):
        done, _ = self.run_launcher(self.home("quiet"))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    def test_nothing_installed_passes_with_nothing_written(self):
        done, _ = self.run_launcher(self.home())
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))

    def test_a_handler_that_hangs_is_ended_at_the_bound_and_passes(self):
        done, took = self.run_launcher(self.home("hang"))
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, b"", b""))
        self.assertLess(took, 30)


if __name__ == "__main__":
    unittest.main()
