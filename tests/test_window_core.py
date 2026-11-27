"""The window's switch from Python to the Rust core (v0.6.27-alpha, P6 seat S6.2a; P6-DESIGN 1.7).

Every start of the window's runs one program, the installation's console core `root/app/bin/codex-auto-resume.exe`
(gui/CoreExe.cs), with the words the Python programs it replaces took: the one-shot bridge `bridge <command> [-]` (the
argument on stdin, never on the command line), the Dashboard's long-lived `bridge serve`, Repair's `setup --keep-state`
under the installer's lock, and the Desktop shortcut's `desktop-shortcut make|remove`. The wire does not change (D12):
the window reads every reply as it did. The strings cache is keyed "3" over plugin.json, the core and the catalogs, so a
v0.6.26 cache ("2", over five .py files) is never read as current. ChildTree spares the watcher's two images, the host
CodexAutoResume.exe and car-legacy's pythonw.exe. No `.py` is named in a string the window's code holds, but the
advanced sentinel `__init__.py` its edition check reads (gui/InstallerFlow.cs).

* SourceTests - read the C# with tests/guiscan.py's slices (each fails with the change reverted).
* CompiledTests - CoreExe.cs, ChildTree.cs and WindowJson.cs (with HostApp.cs, for OwnProcess) compiled alone with the in-box csc into a probe that is
  run, never a window: the path, the spared images over a made-up process table, and the cache key over a scratch
  installation's files. Nothing is started but the probe; no real home, registry or process is read.

    PYTHONPATH="src;tests" python -m unittest test_window_core
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import guiscan  # noqa: E402

ROOT = guiscan.ROOT
CSC = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
NO_WINDOW = 0x08000000


def code_of(text: str) -> str:
    """The C# with its comments taken out (line comments, block comments), string literals kept."""
    out, index, length = [], 0, len(text)
    while index < length:
        if text.startswith("//", index):
            end = text.find("\n", index)
            index = length if end < 0 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = length if end < 0 else end + 2
        elif text[index] == '"' and index > 0 and text[index - 1] == "@":
            end = index + 1
            while end < length:
                if text[end] == '"' and text.startswith('""', end):
                    end += 2
                    continue
                if text[end] == '"':
                    break
                end += 1
            out.append(text[index:end + 1])
            index = end + 1
        elif text[index] == '"':
            end = index + 1
            while end < length and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            out.append(text[index:end + 1])
            index = end + 1
        elif text[index] == "'":
            end = index + 1
            while end < length and text[end] != "'":
                end += 2 if text[end] == "\\" else 1
            out.append(text[index:end + 1])
            index = end + 1
        else:
            out.append(text[index])
            index += 1
    return "".join(out)


def literals(text: str) -> list:
    return re.findall(r'"(?:[^"\\\n]|\\.)*"', code_of(text))


class SourceTests(unittest.TestCase):
    def test_the_core_is_one_path_inside_the_installation(self):
        body = guiscan.member_body("CoreExe", "Path")
        self.assertIn('"app"), "bin"), Name)', body)
        self.assertIn('internal const string Name = "codex-auto-resume.exe";', guiscan.type_body("CoreExe"))

    def test_the_one_shot_bridge_runs_the_core_s_bridge_with_the_argument_on_stdin(self):
        bridge = guiscan.type_body("Bridge")
        self.assertIn("core = CoreExe.Path(root);", bridge)
        self.assertIn("get { return File.Exists(core); }", bridge)
        call = bridge                 # both Call overloads, and the fields they read
        self.assertIn("info.FileName = core;", call)
        self.assertIn('var arguments = new StringBuilder("bridge");', call)
        self.assertIn("arguments.Append(' ').Append(command);", call)
        self.assertIn('if (hasArgument) arguments.Append(" -");', call)
        for setting in ("UseShellExecute = false", "CreateNoWindow = true", "RedirectStandardInput = true"):
            self.assertIn("info." + setting + ";", call)
        self.assertNotIn("python", code_of(bridge).lower())

    def test_the_long_lived_bridge_runs_bridge_serve_from_the_same_core(self):
        start = guiscan.member_body("PersistentBridge", "StartLocked")
        self.assertIn("info.FileName = once.Core;", start)
        self.assertIn('info.Arguments = "bridge serve";', start)
        self.assertIn("info.CreateNoWindow = true;", start)
        failed = guiscan.member_body("PersistentBridge", "FailedLocked")
        self.assertIn("if (failures >= MaxFailures) givenUp.Restart();", failed)
        self.assertNotIn("UseBundled", guiscan.type_body("PersistentBridge"))

    def test_repair_runs_the_core_s_setup_under_the_install_lock(self):
        repair = guiscan.member_body("SettingsForm", "RunRepair")
        self.assertIn('new ProcessStartInfo(core, "setup --keep-state");', repair)
        self.assertIn('if (!File.Exists(core)) { outcome = "incomplete"; return; }', repair)
        self.assertIn('new System.Threading.Mutex(false, "Local\\\\CodexAutoResume.Install")', repair)
        self.assertIn('info.EnvironmentVariables["CODEX_AUTO_RESUME_PLUGIN_HOME"] = root;', repair)
        self.assertIn("info.CreateNoWindow = true;", repair)
        self.assertIn("string core = CoreExe.Path(root);", guiscan.member_body("SettingsForm", "Repair"))

    def test_the_desktop_shortcut_asks_the_core(self):
        change = guiscan.member_body("DesktopShortcut", "Change")
        self.assertIn("string core = CoreExe.Path(home);", change)
        self.assertIn('new ProcessStartInfo(core, "desktop-shortcut " + (make ? "make" : "remove"));', change)
        self.assertIn("if (!File.Exists(core)) return NotChanged;", change)
        self.assertIn("info.CreateNoWindow = true;", change)

    def test_the_strings_cache_is_keyed_3_over_the_core_and_the_catalogs(self):
        key = guiscan.member_body("StringsCache", "Key")
        self.assertIn('var key = new StringBuilder("3");', key)
        self.assertIn("Stamp(key, sha, CoreExe.Path(root));", key)
        self.assertIn('Stamp(key, sha, Path.Combine(Path.Combine(app, ".codex-plugin"), "plugin.json"));', key)
        self.assertIn('Directory.GetFiles(locales, "*.json")', key)
        self.assertEqual([each for each in literals(key) if ".py" in each], [])

    def test_the_watcher_s_two_images_are_spared(self):
        tree = guiscan.type_body("ChildTree")
        self.assertIn('internal static readonly string[] Spared = { "CodexAutoResume.exe", "pythonw.exe" };', tree)
        self.assertIn("if (IsSpared(one.Image)) continue;", guiscan.member_body("ChildTree", "Under"))

    def test_no_py_is_named_in_the_window_s_code_but_the_advanced_sentinel(self):
        """Comments may cite the Python a rule was ported from; what the code holds may not name a .py file: nothing
        the window runs or reads is Python since v0.6.27. The one exception is the edition check's sentinel, the
        advanced package's __init__.py in an archive or a tree (InstallerFlow's EditionOfSource and EditionOfArchive)."""
        found = {}
        for path in sorted((ROOT / "gui").glob("*.cs")):
            named = [each for each in literals(path.read_text(encoding="utf-8")) if re.search(r"\.pyw?\b", each)]
            if named:
                found[path.name] = named
        self.assertEqual(found, {"InstallerFlow.cs": ['"__init__.py"', '"__init__.py"']})
        flow = (ROOT / "gui" / "InstallerFlow.cs").read_text(encoding="utf-8")
        for line in flow.splitlines():
            if '"__init__.py"' in line and not line.lstrip().startswith("//"):
                with self.subTest(line.strip()):
                    self.assertTrue("AdvancedPackage" in line or "folder" in line, line)

    def test_the_compile_lists_know_the_core_and_none_of_the_three_files(self):
        self.assertIn("gui/CoreExe.cs", guiscan.manifest())
        self.assertIn("gui/CoreExe.cs", guiscan.groups()["installer"], "the setup programs are compiled with [installer] too")
        for gone in ("RuntimeChoice.cs", "McpLauncher.cs", "HookLauncher.cs"):
            with self.subTest(gone):
                self.assertFalse((ROOT / "gui" / gone).exists())
                self.assertNotIn("gui/" + gone, guiscan.manifest())
                self.assertNotIn(gone, (ROOT / "build" / "make_gui.ps1").read_text(encoding="utf-8"))
                self.assertNotIn(gone, (ROOT / "build" / "gui_stamp.py").read_text(encoding="utf-8"))
        for path in sorted((ROOT / "gui").glob("*.cs")):
            with self.subTest(path.name):
                self.assertNotIn("RuntimeChoice", path.read_text(encoding="utf-8"))

    def test_the_wire_the_window_reads_is_untouched(self):
        """D12: the replies are the bridge's, byte for byte; the consumer-fields test is the reference's and unchanged."""
        # From 0622dbeb3 (S6.3): the consumer-field scan leaves the host's surfaces out, which read the core's events
        # (car-host's tables, test_host_contract), not a bridge answer; nothing of the wire changed with it. From 2017a395d
        # (Integration 12): the host shell's two receivers (car_start's reply, a pump event) placed in LOCAL, for the same
        # reason; tests/golden/bridge is still 0622dbeb3's.
        done = subprocess.run(["git", "diff", "--quiet", "2017a395d", "--", "tests/test_consumer_fields.py",
                               "tests/golden/bridge"], cwd=ROOT, capture_output=True, timeout=60, creationflags=NO_WINDOW)
        if done.returncode not in (0, 1):
            self.skipTest("git could not compare with the seat's base: " + done.stderr.decode(errors="replace")[-200:])
        self.assertEqual(done.returncode, 0, "tests/test_consumer_fields.py or tests/golden/bridge changed")


PROBE = r"""
using System;
using System.Collections.Generic;
namespace CodexAutoResume {
    internal static class Probe {
        static int Main(string[] args) {
            if (args[0] == "path") { Console.Write(CoreExe.Path(args[1])); return 0; }
            if (args[0] == "key") { Console.Write(StringsCache.Key(args[1]) ?? "null"); return 0; }
            if (args[0] == "under") {
                // 1 the child (a core); under it 2 the host, 3 car-legacy's pythonw, 4 a core, 5 a python.exe;
                // under 2: 6; under 3: 7; under 4: 8.
                var all = new List<ChildTree.Listed>();
                int[][] rows = { new[] {2, 1}, new[] {3, 1}, new[] {4, 1}, new[] {5, 1}, new[] {6, 2}, new[] {7, 3}, new[] {8, 4} };
                string[] images = { args[1], args[2], "codex-auto-resume.exe", "python.exe", "conhost.exe", "cmd.exe", "codex.exe" };
                for (int i = 0; i < rows.Length; i++) {
                    var one = new ChildTree.Listed();
                    one.Id = rows[i][0]; one.Parent = rows[i][1]; one.Image = images[i];
                    all.Add(one);
                }
                List<int> found = ChildTree.Under(1, all, delegate(int pid) { return DateTime.MaxValue; });
                Console.Write(string.Join(",", found));
                return 0;
            }
            return 2;
        }
    }
}
"""


@unittest.skipUnless(CSC.is_file(), "the in-box C# compiler is not available")
class CompiledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.made = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.made.cleanup)
        folder = Path(cls.made.name)
        probe = folder / "Probe.cs"
        probe.write_text(PROBE, encoding="utf-8")
        cls.exe = folder / "probe.exe"
        subprocess.run([str(CSC), "/nologo", "/target:exe", "/platform:x64", "/reference:System.dll",
                        "/out:" + str(cls.exe), str(probe)] +
                       [str(ROOT / "gui" / name) for name in ("CoreExe.cs", "ChildTree.cs", "WindowJson.cs", "HostApp.cs")],
                       check=True, capture_output=True, timeout=300, creationflags=NO_WINDOW)

    def ask(self, *words, env=None) -> str:
        environment = {key: value for key, value in os.environ.items()
                       if key not in ("CODEX_AUTO_RESUME_LANG", "LC_ALL", "LC_MESSAGES", "LANG")}
        environment.update(env or {})
        return subprocess.run([str(self.exe)] + list(words), capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, creationflags=NO_WINDOW, check=True, env=environment).stdout

    def test_the_path(self):
        self.assertEqual(self.ask("path", r"C:\Users\ExampleUser\.codex-auto-resume"),
                         r"C:\Users\ExampleUser\.codex-auto-resume\app\bin\codex-auto-resume.exe")

    def test_the_host_and_car_legacy_s_pythonw_are_spared_with_what_they_started(self):
        for host, legacy in (("CodexAutoResume.exe", "pythonw.exe"), ("codexautoresume.EXE", "PYTHONW.EXE")):
            with self.subTest(host=host):
                self.assertEqual(self.ask("under", host, legacy), "4,5,8")
        # Neither spared: everything under the child is ended (the rule is the images', not the positions').
        self.assertEqual(self.ask("under", "notepad.exe", "python.exe"), "2,3,4,5,6,7,8")

    def make_home(self, folder: Path) -> Path:
        home = folder / "home"
        (home / "app" / ".codex-plugin").mkdir(parents=True)
        (home / "app" / ".codex-plugin" / "plugin.json").write_text('{"version": "0.6.27-alpha"}', encoding="utf-8")
        (home / "app" / "bin").mkdir(parents=True)
        (home / "app" / "bin" / "codex-auto-resume.exe").write_bytes(b"MZ one core")
        package = home / "app" / "src" / "codex_auto_resume"
        (package / "locales").mkdir(parents=True)
        (package / "locales" / "en.json").write_text('{"a": "b"}', encoding="utf-8")
        (package / "controlcli.py").write_text("# v0.6.26's bridge\n", encoding="utf-8")
        (home / "config").mkdir()
        return home

    def test_the_cache_key_is_3_and_follows_the_core_and_the_catalogs_not_the_python(self):
        with tempfile.TemporaryDirectory() as made:
            home = self.make_home(Path(made))
            first = self.ask("key", str(home))
            self.assertTrue(first.startswith("3|window "), first[:40])
            self.assertIn("|codex-auto-resume.exe ", first)
            self.assertNotIn(".py ", first)
            self.assertEqual(self.ask("key", str(home)), first, "the same installation, the same key")
            # A .py file of the v0.6.26 package is no input of the words any more.
            (home / "app" / "src" / "codex_auto_resume" / "controlcli.py").write_text("# changed\n", encoding="utf-8")
            self.assertEqual(self.ask("key", str(home)), first)
            # The core is: a core of the same length but other bytes is another key.
            (home / "app" / "bin" / "codex-auto-resume.exe").write_bytes(b"MZ new core")
            second = self.ask("key", str(home))
            self.assertNotEqual(second, first)
            # And the catalogs.
            (home / "app" / "src" / "codex_auto_resume" / "locales" / "en.json").write_text('{"a": "c"}',
                                                                                            encoding="utf-8")
            self.assertNotEqual(self.ask("key", str(home)), second)

    def test_a_missing_core_is_a_key_of_its_own(self):
        with tempfile.TemporaryDirectory() as made:
            home = self.make_home(Path(made))
            present = self.ask("key", str(home))
            (home / "app" / "bin" / "codex-auto-resume.exe").unlink()
            absent = self.ask("key", str(home))
            self.assertIn("|codex-auto-resume.exe -", absent)
            self.assertNotEqual(absent, present)


if __name__ == "__main__":
    unittest.main()
