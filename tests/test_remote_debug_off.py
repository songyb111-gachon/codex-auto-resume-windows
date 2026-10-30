"""Remote debugging is off in every process the product's Python runs (v0.6.19-beta.3).

PEP 768, new in Python 3.14, which a release bundles from v0.6.19-beta.3 on: an interpreter with remote debugging on
can be made, by any process of the same user, to run a script of that process's choosing (sys.remote_exec), and it is
on unless the interpreter is told otherwise. Everything the product starts with its interpreter is told so on the
command line, right after the interpreter - `-X disable-remote-debug`, with hyphens: `-X disable_remote_debug`, as PEP
768 wrote it, is an unknown option that is kept without a word and leaves remote debugging on (measured on 3.14.7 and
on the bundled 3.14.9). What Windows starts from a value an older version wrote - the sign-in value, which keeps the
form released versions read, and an old notification-button value - reaches an entry point that starts itself once
more with the option before it does anything (scripts/watcher_launcher.py, src/auto_resume.py, scripts/plugin_setup.py).

* StaticTests - every place the product starts its interpreter, in Python, C# and PowerShell, carries the option.
* RuntimeTests (3.14 and later) - processes started the product's way report sys.is_remote_debug_enabled() False.
  Scratch homes with a stand-in engine only: nothing is installed or registered, no real home is read.

    PYTHONPATH="src;tests" python -m unittest test_remote_debug_off
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
for _entry in (str(ROOT / "src"), str(ROOT / "tests")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from codex_auto_resume import config, control, startup  # noqa: E402

OPTION = "disable-remote-debug"
WRONG = "disable_remote_debug"
# Every Python file the product runs: the engine, the two scripts that start or set it up, the advanced package.
PRODUCT_PY = (sorted((ROOT / "src").rglob("*.py")) + [ROOT / "scripts" / "plugin_setup.py",
              ROOT / "scripts" / "watcher_launcher.py"] + sorted((ROOT / "advanced" / "src").rglob("*.py")))
WINDOW_CS = sorted((ROOT / "gui").glob("*.cs")) + sorted((ROOT / "advanced" / "gui").glob("*.cs")) + \
    sorted((ROOT / "build" / "setup").glob("*.cs"))
PRODUCT_PS = (ROOT / "build" / "install" / "install.ps1", ROOT / "scripts" / "bootstrap.ps1")
# The first element of an argument list that is an interpreter of the product's.
INTERPRETER = re.compile(r"\binterpreter\b|pythonw|python_launcher\(|python_for_watcher\(|sys\.executable|\blauncher\b"
                         r"|str\(chosen\)")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _starts_with_option(node) -> bool:
    return (len(node.elts) > 1 and isinstance(node.elts[1], ast.Starred)
            and "NO_REMOTE_DEBUG" in ast.unparse(node.elts[1].value))


class StaticTests(unittest.TestCase):
    def test_the_option_is_spelled_the_way_python_reads_it(self):
        self.assertEqual(startup.NO_REMOTE_DEBUG, ("-X", OPTION))
        launcher = (ROOT / "scripts" / "watcher_launcher.py").read_text(encoding="utf-8")
        self.assertIn('NO_REMOTE_DEBUG = ("-X", "%s")' % OPTION, launcher)

    def test_no_python_argument_list_starts_the_interpreter_without_the_option(self):
        """Every list whose first element is an interpreter of the product's has the option right after it."""
        seen, offenders = [], []
        for path in PRODUCT_PY:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            functions = {}
            for function in ast.walk(tree):
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(function):
                        functions.setdefault(id(child), function.name)
            # A `%` operand formats text and an unpacking target names results: neither is a command line.
            formatted = {id(node.right) for node in ast.walk(tree)
                         if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)}
            for node in ast.walk(tree):
                if not isinstance(node, (ast.List, ast.Tuple)) or not node.elts:
                    continue
                if isinstance(node.ctx, ast.Store) or id(node) in formatted:
                    continue
                if not INTERPRETER.search(ast.unparse(node.elts[0])):
                    continue
                site = "%s:%d (%s)" % (_relative(path), node.lineno, functions.get(id(node), "-"))
                seen.append(site)
                if _starts_with_option(node):
                    continue
                # The sign-in value: the form released versions read, its launcher turns it off itself (EntryTests).
                if (_relative(path) == "src/codex_auto_resume/startup.py" and functions.get(id(node)) == "command_line"
                        and ast.unparse(node.elts[1]) == "*options"):
                    continue
                offenders.append(site + ": " + ast.unparse(node))
        self.assertEqual(offenders, [], "\n".join(offenders))
        # The scan reaches the starts it is about, so a renamed variable cannot make it pass by seeing nothing.
        for expected in ("src/codex_auto_resume/control/watcher.py", "scripts/plugin_setup.py",
                         "scripts/watcher_launcher.py", "src/codex_auto_resume/startup.py",
                         "advanced/src/codex_auto_resume_advanced/codex/wmi_escape.py"):
            self.assertTrue(any(site.startswith(expected + ":") for site in seen), expected)
        self.assertGreaterEqual(len(seen), 11, seen)

    def test_every_start_of_the_interpreter_in_python_goes_through_such_a_list(self):
        """A start with no list (a name built elsewhere) would pass the scan above unseen: each Popen/run of an
        interpreter names the list inline, or a command built by startup's own functions."""
        for path in PRODUCT_PY:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and ast.unparse(node.func).split(".")[-1] in ("Popen", "run")):
                    continue
                if not node.args:
                    continue
                first = node.args[0]
                text = ast.unparse(first)
                if not INTERPRETER.search(text) and not re.search(r"\barguments\b|\bargv\b", text):
                    continue
                with self.subTest(site="%s:%d" % (_relative(path), node.lineno)):
                    if isinstance(first, ast.Name):
                        continue                  # followed through its assignment: the list scan saw it
                    self.assertIsInstance(first, (ast.List, ast.BinOp), text)

    def test_the_shortcut_to_the_interpreter_carries_the_option(self):
        text = (ROOT / "src" / "codex_auto_resume" / "commands" / "install.py").read_text(encoding="utf-8")
        call = text[text.index("shortcut.install(target=startup.python_launcher()") - 400:
                    text.index("shortcut.install(target=startup.python_launcher()")]
        self.assertIn("*startup.NO_REMOTE_DEBUG, str(target)", call)

    def test_every_python_exe_the_window_and_the_mcp_launcher_start_is_given_the_option_first(self):
        starts = {}
        for path in WINDOW_CS:
            text = path.read_text(encoding="utf-8")
            for found in re.finditer(r"new ProcessStartInfo\(", text):
                end = text.find("Process.Start(", found.end())
                segment = text[found.start():end if end > 0 else len(text)]
                if not re.search(r"FileName = python;|ProcessStartInfo\(python\b", segment):
                    continue
                starts["%s:%d" % (_relative(path), text.count("\n", 0, found.start()) + 1)] = segment
        self.assertEqual(sorted(site.split(":")[0] for site in starts),
                         ["gui/Dashboard.cs", "gui/DashboardMaintenance.cs", "gui/HookLauncher.cs", "gui/McpLauncher.cs",
                          "gui/SettingsApp.cs"], sorted(starts))
        first = re.compile(r'Arguments = (Bridge\.)?NoRemoteDebug \+|ProcessStartInfo\(python, (Bridge\.)?NoRemoteDebug \+'
                           r'|arguments\.Append\(NoRemoteDebug\)\.Append\("-c "\)|Arguments = "-I -X %s -c "' % OPTION)
        for site, segment in starts.items():
            with self.subTest(site=site):
                self.assertRegex(segment, first)
        window = (ROOT / "gui" / "SettingsApp.cs").read_text(encoding="utf-8")
        self.assertIn('internal const string NoRemoteDebug = "-X %s ";' % OPTION, window)

    def test_every_bundled_python_the_installer_and_the_bootstrap_run_is_given_the_option_first(self):
        seen = 0
        for path in PRODUCT_PS:
            text = path.read_text(encoding="utf-8")
            assigned = {name.lower(): value for name, value in
                        re.findall(r"^\s*\$(\w+)\s*=\s*(@\(.*\))\s*$", text, re.MULTILINE)}
            for number, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                for found in re.finditer(r"&\s*\$(\w*(?:python|interpreter)\w*)\s+(\S+)(?:\s+(\S+))?", line, re.I):
                    seen += 1
                    with self.subTest(site="%s:%d" % (_relative(path), number)):
                        after, then = found.group(2), found.group(3)
                        if after.startswith("@"):
                            self.assertRegex(assigned.get(after[1:].lower(), ""), r"^@\('-X', '%s'" % OPTION, line)
                        else:
                            self.assertEqual((after, then), ("-X", OPTION), line)
                for found in re.finditer(r"Resolve-OutsideRun -Script \$\w*python\w* -Arguments (\$\w+|\(.+)", line, re.I):
                    seen += 1
                    with self.subTest(site="%s:%d" % (_relative(path), number)):
                        given = found.group(1)
                        if given.startswith("$"):
                            given = assigned.get(given[1:].lower(), "")
                        self.assertRegex(given, r"^\(?@\('-X', '%s'" % OPTION, line)
        self.assertGreaterEqual(seen, 10)

    def test_the_spelling_that_leaves_it_on_is_used_nowhere(self):
        """`disable_remote_debug` may be named only where a comment explains why it is not used."""
        offenders = []
        for path in PRODUCT_PY:
            with tokenize.open(path) as stream:
                for token in tokenize.generate_tokens(stream.readline):
                    if token.type == tokenize.STRING and WRONG in token.string and "PEP 768 wrote" not in token.string \
                            and "is an unknown option" not in token.string and "kept without a word" not in token.string:
                        offenders.append("%s:%d" % (_relative(path), token.start[0]))
        for path in WINDOW_CS + list(PRODUCT_PS):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if WRONG in line and not stripped.startswith(("//", "#", "///")):
                    offenders.append("%s:%d" % (_relative(path), number))
        self.assertEqual(offenders, [])


class EntryTests(unittest.TestCase):
    """What Windows starts from a value an older version wrote turns remote debugging off itself, first."""

    def main_block(self, path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        return text[text.index('if __name__ == "__main__":'):]

    def test_the_launcher_starts_itself_again_before_anything_runs(self):
        block = self.main_block(ROOT / "scripts" / "watcher_launcher.py")
        self.assertIn("sys.exit(0 if _again_without_remote_debug() else _guarded(sys.argv[1:]))", block)

    def test_the_two_other_entry_points_ask_before_their_main(self):
        for path in (ROOT / "src" / "auto_resume.py", ROOT / "scripts" / "plugin_setup.py"):
            with self.subTest(path=_relative(path)):
                block = self.main_block(path)
                # 2026-10-30: through again_under_chosen_python, which ends in the remote-debug guard (test_newest_python).
                self.assertRegex(block, r"again = (startup\.)?again_(without_remote_debug|under_chosen_python)\(__file__\)\n"
                                        r"\s*sys\.exit\(main\(\) if again is None else again\)")

    def test_every_sign_in_value_names_one_of_those_entry_points(self):
        """startup.command_line without the option is the sign-in value; it names the launcher or src/auto_resume.py."""
        offenders = []
        for path in PRODUCT_PY:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and ast.unparse(node.func) in ("startup.command_line", "command_line")
                        and not any(keyword.arg == "options" for keyword in node.keywords)):
                    entry = ast.unparse(node.args[0]) if node.args else ""
                    if not re.search(r"LAUNCHER_NAME|watcher-launcher\.py|\bentry\b|entry_script", entry):
                        offenders.append("%s:%d %s" % (_relative(path), node.lineno, entry))
        self.assertEqual(offenders, [])

    def test_the_doctor_reads_a_value_with_the_option(self):
        argv = ["C:\\Python\\pythonw.exe", "-X", OPTION, "C:\\Home\\watcher-launcher.py", "activate", "%1"]
        self.assertEqual(argv[startup.script_index(argv)], "C:\\Home\\watcher-launcher.py")
        self.assertEqual(startup.script_index(["pythonw.exe", "launcher.py", "run"]), 1)


FAKE_CLI = '''import json, os, sys
def main(argv=None):
    with open(os.environ["CAR_REMOTE_DEBUG_OUT"] + ".%d.json" % os.getpid(), "w", encoding="utf-8") as stream:
        json.dump({"remote": sys.is_remote_debug_enabled(), "argv": list(argv or []),
                   "option": "disable-remote-debug" in sys._xoptions}, stream)
    return 0
'''


@unittest.skipUnless(sys.version_info >= (3, 14), "PEP 768 is new in Python 3.14")
@unittest.skipUnless(os.name == "nt", "Windows starts")
class RuntimeTests(unittest.TestCase):
    """Processes started the product's way, on the interpreter running this test, in scratch homes."""

    def setUp(self):
        self.pythonw = Path(sys.executable).resolve().with_name("pythonw.exe")
        if not self.pythonw.is_file():
            self.skipTest("no pythonw.exe beside %s" % sys.executable)
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="car-remote-debug-")))
        engine = self.home / "app" / "src"
        (engine / "codex_auto_resume").mkdir(parents=True)
        (engine / "auto_resume.py").write_text("# stand-in\n", encoding="utf-8")
        (engine / "codex_auto_resume" / "__init__.py").write_text("", encoding="utf-8")
        (engine / "codex_auto_resume" / "cli.py").write_text(FAKE_CLI, encoding="utf-8")
        (self.home / "runtime.json").write_text(json.dumps({"mode": "local", "home": str(self.home)}),
                                                encoding="utf-8")
        shutil.copyfile(ROOT / "scripts" / "watcher_launcher.py", self.home / "watcher-launcher.py")
        self.out = self.home / "seen"
        environment = {name: value for name, value in os.environ.items() if name not in ("PYTHONPATH",)}
        environment["CAR_REMOTE_DEBUG_OUT"] = str(self.out)
        self.enterContext(mock.patch.dict(os.environ, environment, clear=True))

    def seen(self, timeout=60.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = sorted(self.home.glob("seen.*.json"))
            if found:
                time.sleep(0.2)
                return json.loads(found[0].read_text(encoding="utf-8"))
            time.sleep(0.1)
        log = self.home / "logs" / "launcher.log"
        self.fail("the stand-in engine never ran; launcher.log: %s"
                  % (log.read_text(encoding="utf-8") if log.is_file() else "none"))

    def relaunched(self) -> bool:
        log = self.home / "logs" / "launcher.log"
        return log.is_file() and "remote debugging was on" in log.read_text(encoding="utf-8")

    def start(self, command: str):
        argv = startup.parse_command(command)
        subprocess.Popen(argv, cwd=str(self.home), close_fds=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait(timeout=60)

    def test_the_interpreter_has_it_on_unless_told_and_only_the_hyphens_tell_it(self):
        def remote(*options):
            return subprocess.run([sys.executable, *options, "-c", "import sys;print(sys.is_remote_debug_enabled())"],
                                  capture_output=True, text=True, timeout=60).stdout.strip()
        self.assertEqual(remote(), "True")
        self.assertEqual(remote("-X", WRONG), "True")
        self.assertEqual(remote(*startup.NO_REMOTE_DEBUG), "False")

    def test_the_sign_in_value_ends_in_a_watcher_with_it_off(self):
        """The Run value as setup writes it, with no option: the launcher starts itself once more with it."""
        self.start(startup.command_line(self.home / "watcher-launcher.py", None, launcher=self.pythonw))
        seen = self.seen()
        self.assertEqual((seen["remote"], seen["option"], seen["argv"][-1:]), (False, True, ["run"]))
        self.assertTrue(self.relaunched())

    def test_the_notification_button_starts_it_off(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        self.addCleanup(sys.path.remove, str(ROOT / "scripts"))
        spec = importlib.util.spec_from_file_location("car_plugin_setup_probe", ROOT / "scripts" / "plugin_setup.py")
        plugin_setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(plugin_setup)
        command = plugin_setup.notification_command(self.home).replace('"%1"', '"codex-auto-resume:probe"')
        self.start(command)
        seen = self.seen()
        self.assertEqual((seen["remote"], seen["argv"][-2:]), (False, ["activate", "codex-auto-resume:probe"]))
        self.assertFalse(self.relaunched(), "the option was on the command line; nothing had to start again")

    def test_start_watcher_starts_it_off_with_no_second_start(self):
        """Start watcher from the window, the panel and the command line (control/watcher._launch_watcher)."""
        panel = control.Control(config.Paths(self.home))
        process = panel._launch_watcher()
        process.wait(timeout=60)
        seen = self.seen()
        self.assertEqual((seen["remote"], seen["option"]), (False, True))
        self.assertFalse(self.relaunched(), "the option was on the command line; nothing had to start again")

    def test_an_entry_point_run_without_the_option_runs_again_on_the_same_streams(self):
        """A published bootstrap runs setup with python.exe and reads what it prints: the entry point's guard runs
        it again with the option, on the same streams, and its exit code is the run's."""
        script = self.home / "entry.py"
        script.write_text("import sys\nsys.path.insert(0, %r)\n" % str(ROOT / "src") +
                          "from codex_auto_resume.startup import again_without_remote_debug\n"
                          "if __name__ == '__main__':\n"
                          "    again = again_without_remote_debug(__file__)\n"
                          "    if again is None:\n"
                          "        print('remote', sys.is_remote_debug_enabled(), sys.argv[1:])\n"
                          "        sys.exit(7)\n"
                          "    sys.exit(again)\n", encoding="utf-8")
        done = subprocess.run([sys.executable, str(script), "setup", "--keep-state"], capture_output=True, text=True,
                              timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual((done.returncode, done.stdout.strip()), (7, "remote False ['setup', '--keep-state']"))


if __name__ == "__main__":
    unittest.main()
