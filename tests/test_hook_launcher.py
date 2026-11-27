"""The advanced edition's Stop hook launcher (v0.6.20 gui/HookLauncher.cs; Rust since v0.6.27, P6 S6.2a / Q4): the MCP
launcher's twin for the one capability Codex itself starts, "Continue inside the turn" (plans/v0619-design/D-stop-hook.md).

It is car-adv-bin's codex-auto-resume-hook.exe now, built in the advanced Rust workspace only, for app/hook/ where the
hook's declaration names it (control/hookplugin.py `launcher()`), and it starts the installation's core as
`codex-auto-resume.exe hook --home <home>`. Held here: the C# launcher is gone and the standard workspace has no such
program; every child it starts gets no window and three redirected streams; and, run for real against a stand-in core,
it relays the handler's one answer whole and only from a handler that exited 0, drops the handler's standard error, and
passes (exit 0, nothing written) when nothing is installed, when the handler fails and when the handler hangs past its
bound - what v0.6.26's C# launcher did against its stand-in interpreter. It is not in an archive yet: the capability is
hidden until MHK, M4 and M4B pass, and shipping it waits for that, with the owner's review.

The built half runs the launcher cargo built (advanced/rust/target/{release,debug}); it is skipped, by name, where neither
is there (`cargo build -p car-adv-bin` in advanced/rust makes it).
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "advanced" / "rust" / "crates" / "car-adv-bin"
SOURCE = CRATE / "src" / "hook_launcher.rs"
MAIN = CRATE / "src" / "bin" / "hook.rs"
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = 0x08000000
EXE = "codex-auto-resume-hook.exe"


def built() -> Path | None:
    for profile in ("release", "debug"):
        found = ROOT / "advanced" / "rust" / "target" / profile / EXE
        if found.is_file():
            return found
    return None


# A stand-in for the installation's core: what it does is chosen by a file beside it, so one build serves every case.
# It records its arguments and its input, so the test sees the role and the home it was started with.
STAND_IN = r"""
using System;
using System.IO;
using System.Threading;
static class Program {
    static int Main(string[] args) {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string mode = File.ReadAllText(Path.Combine(here, "mode.txt")).Trim();
        File.WriteAllText(Path.Combine(here, "args.txt"), string.Join("\n", args));
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


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.text = SOURCE.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.code = self.text.split("#[cfg(test)]", 1)[0]
        self.main = MAIN.read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_the_c_sharp_launcher_is_gone_and_the_standard_workspace_has_none(self):
        self.assertFalse((ROOT / "gui" / "HookLauncher.cs").exists())
        for path in (ROOT / "rust").rglob("*"):
            if "target" in path.parts or not path.is_file() or path.suffix not in (".rs", ".toml"):
                continue
            with self.subTest(str(path.relative_to(ROOT))):
                self.assertNotIn("codex-auto-resume-hook", path.read_text(encoding="utf-8", errors="replace"))

    def test_it_is_a_bin_of_the_advanced_workspace(self):
        manifest = (CRATE / "Cargo.toml").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertIn('name = "codex-auto-resume-hook"\npath = "src/bin/hook.rs"', manifest)

    def test_its_child_is_the_core_s_hook_role_with_three_piped_streams_through_the_one_starter(self):
        self.assertIn('pub const ROLE: &str = "hook";', self.code)
        self.assertIn('"--home".to_owned()', self.code)
        self.assertIn("car_bin::launcher::core_of(home)", self.code)
        self.assertIn(".with_streams(Stream::Piped, Stream::Piped, Stream::Piped)", self.code)
        self.assertIn("SystemStarter.start(spawn)", self.code)
        self.assertNotIn("Command::new", self.code)

    def test_it_never_writes_to_standard_error_and_every_way_out_is_zero(self):
        """A hook's non-zero exit or its words on standard error may be read by Codex as something; the launcher's
        only failure is to pass."""
        for text in (self.code, self.main):
            self.assertNotIn("stderr()", text)
            self.assertNotIn("eprint", text)
        self.assertIn("std::process::exit(std::panic::catch_unwind(hook_launcher::run).unwrap_or(0));", self.main)
        run = self.code[self.code.index("pub fn run() -> i32"):]
        self.assertEqual(set(re.findall(r"\breturn\s+(-?\d+)\s*;", run)), {"0"})
        self.assertTrue(run.rstrip().endswith("    0\n}"), run[-40:])

    def test_the_bound_is_the_c_sharp_launcher_s(self):
        self.assertIn("pub const BOUND: Duration = Duration::from_millis(8000);", self.code)
        self.assertIn("pub const JOIN: Duration = Duration::from_millis(2000);", self.code)


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
@unittest.skipUnless(built(), "codex-auto-resume-hook.exe is not built (cargo build -p car-adv-bin in advanced/rust)")
class BuiltTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = Path(tempfile.mkdtemp(prefix="car-hook-launcher-"))
        cls.launcher = built()
        stand_in = cls.folder / "StandIn.cs"
        stand_in.write_text(STAND_IN, encoding="utf-8")
        cls.core = cls.folder / "codex-auto-resume.exe"
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/optimize+", "/out:" + str(cls.core),
                        "/reference:System.dll", str(stand_in)],
                       check=True, capture_output=True, timeout=180, creationflags=NO_WINDOW)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)

    def home(self, mode=None) -> Path:
        home = Path(tempfile.mkdtemp(prefix="car-hook-home-", dir=self.folder))
        if mode is not None:
            (home / "app" / "bin").mkdir(parents=True)
            (home / "app" / "src").mkdir(parents=True)
            shutil.copyfile(self.core, home / "app" / "bin" / "codex-auto-resume.exe")
            (home / "app" / "bin" / "mode.txt").write_text(mode, encoding="utf-8")
        return home

    def run_launcher(self, home, stdin=b'{"hook_event_name":"Stop"}', timeout=60):
        env = {key: value for key, value in os.environ.items()
               if key not in ("CODEX_AUTO_RESUME_PLUGIN_HOME", "CODEX_AUTO_RESUME_HOME")}
        env["CODEX_AUTO_RESUME_PLUGIN_HOME"] = str(home)
        started = time.monotonic()
        done = subprocess.run([str(self.launcher)], input=stdin, capture_output=True, timeout=timeout, env=env,
                              creationflags=NO_WINDOW)
        return done, time.monotonic() - started

    def test_the_handler_s_answer_is_relayed_whole_and_its_input_handed_over(self):
        home = self.home("block")
        done, _ = self.run_launcher(home)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout, b'{"decision":"block","reason":"go on"}')
        self.assertEqual(done.stderr, b"", "the handler's diagnostic never reaches Codex")
        self.assertEqual((home / "app" / "bin" / "seen.txt").read_bytes(), b'{"hook_event_name":"Stop"}')
        self.assertEqual((home / "app" / "bin" / "args.txt").read_text(encoding="utf-8").split("\n"),
                         ["hook", "--home", str(home)])

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
